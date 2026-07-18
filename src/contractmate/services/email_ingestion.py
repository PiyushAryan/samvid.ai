from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from pydantic import BaseModel

from contractmate.email.interface import EmailSender
from contractmate.email.messages import InboundEmailMessage, OutboundEmailMessage
from contractmate.email.rendering import render_review_email_html, render_review_email_text
from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService
from contractmate.settings import Settings
from contractmate.workers.queue import ContractQueue, RabbitMQContractQueue
from contractmate.workflows.states import WorkflowState


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
        queue: ContractQueue | None = None,
    ) -> None:
        self.settings = settings
        self.processing_service = processing_service
        self.sender = sender
        self.queue = queue

    @classmethod
    def local(cls, settings: Settings) -> "EmailIngestionService":
        queue = (
            RabbitMQContractQueue.from_settings(settings)
            if settings.contract_processing_mode == "rabbitmq"
            else None
        )
        return cls(
            settings=settings,
            processing_service=ContractProcessingService.local(settings),
            sender=EmailSender(settings),
            queue=queue,
        )

    def process_inbound_email(self, message: InboundEmailMessage, *, send_response: bool = True) -> EmailIngestionResult:
        processed: list[ContractProcessingResult] = []
        ignored: list[str] = []
        for attachment in message.attachments:
            attachment_path = self._materialize_attachment(message, attachment.filename, attachment.content_base64, attachment.local_path)
            try:
                arguments = {
                    "file_path": attachment_path,
                    "workspace_id": self.settings.email_workspace_id,
                    "email_thread_id": message.email_thread_id,
                    "requested_by": str(message.from_address),
                    "declared_mime_type": attachment.mime_type,
                    "original_filename": attachment.filename,
                }
                result = (
                    self.processing_service.enqueue_local_file(
                        queue=self.queue,
                        send_review_email=send_response,
                        recipient_name=message.from_name,
                        response_address=message.response_address or message.from_address,
                        original_subject=message.subject,
                        in_reply_to=message.original_message_id,
                        references=message.references,
                        **arguments,
                    )
                    if self.queue is not None
                    else self.processing_service.review_local_file(**arguments)
                )
            finally:
                if attachment.local_path is None:
                    attachment_path.unlink(missing_ok=True)
            processed.append(result)
            if not result.contract_id:
                ignored.append(attachment.filename)

        if send_response and processed:
            immediate_results = [result for result in processed if result.status is not WorkflowState.QUEUED]
            if immediate_results:
                self._send_review_response(message, immediate_results)
        return EmailIngestionResult(message_id=message.message_id, processed=processed, ignored_attachments=ignored)

    def close(self) -> None:
        self.processing_service.close()

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
        text_parts = []
        html_parts = []
        for result in results:
            if result.review:
                contract_url = _contract_url(self.settings.frontend_origin, result.contract_id)
                text_parts.append(
                    render_review_email_text(
                        result.review,
                        recipient_name=message.from_name,
                        recipient_address=message.response_address or message.from_address,
                        contract_url=contract_url,
                    )
                )
                html_parts.append(
                    render_review_email_html(
                        result.review,
                        recipient_name=message.from_name,
                        recipient_address=message.response_address or message.from_address,
                        contract_url=contract_url,
                    )
                )
            else:
                text_parts.append(result.message)
        self.sender.send(
            OutboundEmailMessage(
                to_address=message.response_address or message.from_address,
                from_address=self.settings.email_from_address,
                subject=_reply_subject(message.subject),
                text="\n\n---\n\n".join(text_parts),
                html=html_parts[0] if len(results) == 1 and len(html_parts) == 1 else None,
                in_reply_to=message.original_message_id,
                references=message.references,
            )
        )


def _reply_subject(original_subject: str | None) -> str:
    subject = (original_subject or "Contract review").strip()
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


def _contract_url(frontend_origin: str, contract_id: str) -> str:
    return f"{frontend_origin.rstrip('/')}/contracts/{contract_id}"
