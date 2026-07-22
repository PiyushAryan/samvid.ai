from __future__ import annotations

import logging
from typing import Protocol

from contractmate.db.repositories.outbound_email_outbox import (
    OutboundEmailIntent,
    OutboundEmailOutboxItem,
    OutboundEmailOutboxRepository,
)
from contractmate.email.messages import OutboundEmailMessage


logger = logging.getLogger(__name__)


class OutboundEmailSender(Protocol):
    def send(self, message: OutboundEmailMessage) -> None: ...


class OutboundEmailDeliveryService:
    """Claims and sends persisted email intents without reprocessing contracts."""

    def __init__(
        self,
        *,
        repository: OutboundEmailOutboxRepository,
        sender: OutboundEmailSender,
        max_attempts: int = 5,
        base_backoff_seconds: int = 30,
        lease_seconds: int = 120,
    ) -> None:
        self.repository = repository
        self.sender = sender
        self.max_attempts = max(max_attempts, 1)
        self.base_backoff_seconds = max(base_backoff_seconds, 1)
        self.lease_seconds = max(lease_seconds, 1)

    def enqueue(self, intent: OutboundEmailIntent) -> str:
        return self.repository.enqueue(intent)

    def drain_once(self, *, limit: int = 25) -> int:
        sent = 0
        for item in self.repository.claim_due(limit=limit, lease_seconds=self.lease_seconds):
            if not self.repository.is_sending(outbox_id=item.id):
                logger.info("Skipping cancelled outbound email %s", item.id)
                continue
            try:
                self.sender.send(self._message(item))
            except Exception as exc:
                status = self.repository.reschedule(
                    outbox_id=item.id,
                    attempts=item.attempts,
                    error=str(exc),
                    max_attempts=self.max_attempts,
                    base_backoff_seconds=self.base_backoff_seconds,
                )
                logger.exception(
                    "Outbound %s email %s failed on attempt %s; status=%s",
                    item.message_type,
                    item.id,
                    item.attempts,
                    status,
                )
                continue
            self.repository.mark_sent(outbox_id=item.id)
            sent += 1
        return sent

    @staticmethod
    def _message(item: OutboundEmailOutboxItem) -> OutboundEmailMessage:
        return OutboundEmailMessage(
            to_address=item.to_address,
            from_address=item.from_address,
            subject=item.subject,
            text=item.text_body,
            html=item.html_body,
            in_reply_to=item.in_reply_to,
            references=item.references,
            idempotency_key=item.idempotency_key,
        )
