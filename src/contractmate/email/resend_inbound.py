from __future__ import annotations

import hashlib
import json
from email.utils import getaddresses, parseaddr
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Literal
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import resend
from pydantic import BaseModel, Field, ValidationError

from contractmate.db.repositories.inbound_email_events import InboundEmailEventRepository, InboundEventClaim
from contractmate.db.session import connect, initialize_database
from contractmate.email.messages import EmailAttachment, InboundEmailMessage
from contractmate.services.email_ingestion import EmailIngestionService
from contractmate.settings import Settings


SUPPORTED_ATTACHMENTS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}
MAX_ATTACHMENTS_PER_EMAIL = 5
RESEND_ATTACHMENT_HOST = "inbound-cdn.resend.com"


class ResendWebhookData(BaseModel):
    email_id: str = Field(min_length=1)
    to: list[str] = Field(default_factory=list)


class ResendWebhookEvent(BaseModel):
    type: str = Field(min_length=1)
    data: ResendWebhookData


class ResendWebhookEnvelope(BaseModel):
    type: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class ResendInboundResult(BaseModel):
    event_id: str
    email_id: str
    status: Literal["processed", "ignored", "duplicate", "processing"]
    processed_attachments: int = 0
    ignored_attachments: list[str] = Field(default_factory=list)


class MalformedResendWebhook(ValueError):
    pass


class PermanentAttachmentRejection(ValueError):
    pass


def verify_resend_webhook(
    raw_payload: bytes,
    *,
    event_id: str | None,
    timestamp: str | None,
    signature: str | None,
    webhook_secret: str,
) -> None:
    try:
        payload = raw_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedResendWebhook("Webhook payload must be UTF-8 JSON.") from exc
    resend.Webhooks.verify(
        {
            "payload": payload,
            "headers": {
                "id": event_id or "",
                "timestamp": timestamp or "",
                "signature": signature or "",
            },
            "webhook_secret": webhook_secret,
        }
    )


def parse_resend_webhook(raw_payload: bytes) -> ResendWebhookEvent | ResendWebhookEnvelope:
    try:
        payload = json.loads(raw_payload)
        envelope = ResendWebhookEnvelope.model_validate(payload)
        if envelope.type != "email.received":
            return envelope
        return ResendWebhookEvent.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as exc:
        raise MalformedResendWebhook("Malformed Resend webhook event.") from exc


def recipient_is_allowed(addresses: list[str], allowed_recipients: tuple[str, ...]) -> bool:
    allowed = {address.casefold() for address in allowed_recipients}
    received = {address.casefold() for _, address in getaddresses(addresses) if address}
    return bool(allowed.intersection(received))


class ResendReceivingClient:
    def __init__(self, api_key: str, *, open_url: Callable[..., Any] = urlopen) -> None:
        self.api_key = api_key
        self.open_url = open_url

    def get_email(self, email_id: str) -> dict[str, Any]:
        resend.api_key = self.api_key
        return dict(resend.Emails.Receiving.get(email_id, {"html_format": "cid"}))

    def list_attachments(self, email_id: str) -> list[dict[str, Any]]:
        resend.api_key = self.api_key
        response = resend.Emails.Receiving.Attachments.list(email_id, {"limit": 100})
        return [dict(attachment) for attachment in response.get("data", [])]

    def download_attachment(self, download_url: str, destination: Path, *, max_bytes: int) -> None:
        parsed = urlparse(download_url)
        if parsed.scheme != "https" or parsed.hostname != RESEND_ATTACHMENT_HOST:
            raise PermanentAttachmentRejection("Attachment download URL is not an approved Resend URL.")

        request = Request(download_url, headers={"User-Agent": "samvid-resend-inbound/1.0"})
        downloaded = 0
        with self.open_url(request, timeout=30) as response, destination.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise PermanentAttachmentRejection("Attachment exceeds the configured file-size limit.")
            while chunk := response.read(64 * 1024):
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise PermanentAttachmentRejection("Attachment exceeds the configured file-size limit.")
                output.write(chunk)


class ResendInboundService:
    def __init__(
        self,
        *,
        settings: Settings,
        event_repository: InboundEmailEventRepository,
        ingestion_service: EmailIngestionService,
        client: ResendReceivingClient,
    ) -> None:
        self.settings = settings
        self.event_repository = event_repository
        self.ingestion_service = ingestion_service
        self.client = client

    @classmethod
    def local(cls, settings: Settings) -> "ResendInboundService":
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)
        connection = connect(settings.database_url)
        return cls(
            settings=settings,
            event_repository=InboundEmailEventRepository(connection),
            ingestion_service=EmailIngestionService.local(settings),
            client=ResendReceivingClient(settings.resend_api_key or ""),
        )

    def process(self, event: ResendWebhookEvent, *, event_id: str, payload_hash: str) -> ResendInboundResult:
        email_id = event.data.email_id
        claim = self.event_repository.claim(
            event_id=event_id,
            email_message_id=email_id,
            workspace_id=self.settings.email_workspace_id,
            event_type=event.type,
            payload_hash=payload_hash,
        )
        if claim is InboundEventClaim.COMPLETED:
            return ResendInboundResult(event_id=event_id, email_id=email_id, status="duplicate")
        if claim is InboundEventClaim.PROCESSING:
            return ResendInboundResult(event_id=event_id, email_id=email_id, status="processing")

        temporary_files: list[Path] = []
        try:
            received_email = self.client.get_email(email_id)
            delivered_to = list(received_email.get("received_for") or []) + list(received_email.get("to") or [])
            if not recipient_is_allowed(delivered_to, self.settings.resend_inbound_recipients):
                self.event_repository.mark_completed(email_id)
                return ResendInboundResult(event_id=event_id, email_id=email_id, status="ignored")

            attachments, ignored, temporary_files = self._download_supported_attachments(email_id)
            if not attachments:
                self.event_repository.mark_completed(email_id)
                return ResendInboundResult(
                    event_id=event_id,
                    email_id=email_id,
                    status="ignored",
                    ignored_attachments=ignored,
                )

            sender = _parse_email_address(str(received_email.get("from") or ""))
            if not sender:
                self.event_repository.mark_completed(email_id)
                return ResendInboundResult(
                    event_id=event_id,
                    email_id=email_id,
                    status="ignored",
                    ignored_attachments=ignored,
                )
            reply_to = next(
                (
                    parsed
                    for value in received_email.get("reply_to") or []
                    if (parsed := _parse_email_address(str(value)))
                ),
                sender,
            )
            original_message_id = _safe_header_value(received_email.get("message_id"))
            references = _header_value(received_email.get("headers"), "references")
            message = InboundEmailMessage(
                message_id=email_id,
                thread_id=original_message_id or email_id,
                from_address=sender,
                response_address=reply_to,
                to_addresses=[str(value) for value in received_email.get("to") or []],
                subject=str(received_email.get("subject") or ""),
                text=str(received_email.get("text") or ""),
                original_message_id=original_message_id,
                references=_append_reference(references, original_message_id),
                attachments=attachments,
            )
            ingestion_result = self.ingestion_service.process_inbound_email(
                message,
                send_response=self.settings.auto_send_review_email,
            )
            self.event_repository.mark_completed(email_id)
            return ResendInboundResult(
                event_id=event_id,
                email_id=email_id,
                status="processed",
                processed_attachments=len(ingestion_result.processed),
                ignored_attachments=ignored + ingestion_result.ignored_attachments,
            )
        except Exception:
            self.event_repository.mark_failed(email_id)
            raise
        finally:
            for path in temporary_files:
                path.unlink(missing_ok=True)

    def close(self) -> None:
        self.ingestion_service.close()
        self.event_repository.connection.close()

    def _download_supported_attachments(
        self,
        email_id: str,
    ) -> tuple[list[EmailAttachment], list[str], list[Path]]:
        downloaded: list[EmailAttachment] = []
        ignored: list[str] = []
        temporary_files: list[Path] = []
        max_bytes = self.settings.max_file_size_mb * 1024 * 1024
        self.settings.inbound_attachment_dir.mkdir(parents=True, exist_ok=True)

        try:
            for attachment in self.client.list_attachments(email_id):
                filename = Path(str(attachment.get("filename") or "unnamed-attachment")).name
                mime_type = str(attachment.get("content_type") or "").partition(";")[0].strip().casefold()
                expected_suffix = SUPPORTED_ATTACHMENTS.get(mime_type)
                if (
                    attachment.get("content_disposition") != "attachment"
                    or not expected_suffix
                    or Path(filename).suffix.casefold() != expected_suffix
                ):
                    ignored.append(filename)
                    continue
                if len(downloaded) >= MAX_ATTACHMENTS_PER_EMAIL:
                    ignored.append(filename)
                    continue
                size = int(attachment.get("size") or 0)
                if size > max_bytes:
                    ignored.append(filename)
                    continue

                with NamedTemporaryFile(
                    prefix="samvid-resend-",
                    suffix=expected_suffix,
                    dir=self.settings.inbound_attachment_dir,
                    delete=False,
                ) as temporary:
                    destination = Path(temporary.name)
                temporary_files.append(destination)
                try:
                    self.client.download_attachment(
                        str(attachment.get("download_url") or ""),
                        destination,
                        max_bytes=max_bytes,
                    )
                except PermanentAttachmentRejection:
                    ignored.append(filename)
                    continue
                downloaded.append(EmailAttachment(filename=filename, mime_type=mime_type, local_path=destination))
        except Exception:
            for path in temporary_files:
                path.unlink(missing_ok=True)
            raise

        return downloaded, ignored, temporary_files


def webhook_payload_hash(raw_payload: bytes) -> str:
    return hashlib.sha256(raw_payload).hexdigest()


def _parse_email_address(value: str) -> str | None:
    address = parseaddr(value)[1].strip()
    return address if "@" in address else None


def _header_value(headers: Any, name: str) -> str | None:
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).casefold() == name.casefold() and value:
            return _safe_header_value(value)
    return None


def _append_reference(references: str | None, message_id: str | None) -> str | None:
    values = references.split() if references else []
    if message_id and message_id not in values:
        values.append(message_id)
    return " ".join(values) or None


def _safe_header_value(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or "\r" in normalized or "\n" in normalized or len(normalized) > 998:
        return None
    return normalized
