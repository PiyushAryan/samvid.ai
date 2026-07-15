from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from pydantic import BaseModel

from contractmate.email.interface import EmailSender
from contractmate.email.messages import InboundEmailMessage, OutboundEmailMessage
from contractmate.email.rendering import render_review_email_text
from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService
from contractmate.settings import Settings


class EmailIngestionResult(BaseModel):
    message_id: str
    processed: list[ContractProcessingResult]
    ignored_attachments: list[str]


class EmailIngestionService:
    def __init__(
        self,
        *,
        settings: Settings,
        processing_service: ContractProcessingService,
        sender: EmailSender,
    ) -> None:
        self.settings = settings
        self.processing_service = processing_service
        self.sender = sender

    @classmethod
    def local(cls, settings: Settings) -> "EmailIngestionService":
        return cls(
            settings=settings,
            processing_service=ContractProcessingService.local(settings),
            sender=EmailSender(settings),
        )

    def process_inbound_email(self, message: InboundEmailMessage, *, send_response: bool = True) -> EmailIngestionResult:
        processed: list[ContractProcessingResult] = []
        ignored: list[str] = []
        for attachment in message.attachments:
            attachment_path = self._materialize_attachment(message, attachment.filename, attachment.content_base64, attachment.local_path)
            result = self.processing_service.review_local_file(
                file_path=attachment_path,
                workspace_id=self.settings.email_workspace_id,
                email_thread_id=message.email_thread_id,
                requested_by=str(message.from_address),
                declared_mime_type=attachment.mime_type,
            )
            processed.append(result)
            if not result.contract_id:
                ignored.append(attachment.filename)

        if send_response and processed:
            self._send_review_response(message, processed)
        return EmailIngestionResult(message_id=message.message_id, processed=processed, ignored_attachments=ignored)

    def _materialize_attachment(
        self,
        message: InboundEmailMessage,
        filename: str,
        content_base64: str | None,
        local_path: Path | None,
    ) -> Path:
        if local_path:
            return local_path
        assert content_base64 is not None
        digest = hashlib.sha256(message.message_id.encode("utf-8")).hexdigest()[:16]
        destination_dir = self.settings.inbound_attachment_dir / digest
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / Path(filename).name
        destination.write_bytes(base64.b64decode(content_base64))
        return destination

    def _send_review_response(self, message: InboundEmailMessage, results: list[ContractProcessingResult]) -> None:
        body_parts = []
        for result in results:
            if result.review:
                body_parts.append(render_review_email_text(result.review))
            else:
                body_parts.append(result.message)
        self.sender.send(
            OutboundEmailMessage(
                to_address=message.from_address,
                from_address=self.settings.email_from_address,
                subject=f"Samvid review: {message.subject or 'contract'}",
                text="\n\n---\n\n".join(body_parts),
            )
        )
