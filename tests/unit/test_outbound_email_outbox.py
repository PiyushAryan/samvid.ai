from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.outbound_email_outbox import (
    OutboundEmailIntent,
    OutboundEmailOutboxRepository,
)
from contractmate.email.messages import OutboundEmailMessage
from contractmate.services.outbound_email_delivery import OutboundEmailDeliveryService


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    yield connection
    connection.close()


def test_outbox_is_idempotent_and_preserves_thread_order(connection: sqlite3.Connection) -> None:
    repository = OutboundEmailOutboxRepository(connection)
    receipt_id = repository.enqueue(_intent("receipt", "message-1:receipt"))
    review_id = repository.enqueue(_intent("review", "message-1:review"))

    assert repository.enqueue(_intent("receipt", "message-1:receipt")) == receipt_id
    receipt = repository.claim_due(limit=10)[0]
    assert (receipt.id, receipt.thread_position, receipt.message_type) == (receipt_id, 1, "receipt")

    # The review is held until its earlier receipt intent reaches a terminal state.
    assert repository.claim_due(limit=10) == []
    assert repository.mark_sent(outbox_id=receipt_id)
    assert [item.id for item in repository.claim_due(limit=10)] == [review_id]


def test_failed_receipt_does_not_block_review_forever(connection: sqlite3.Connection) -> None:
    repository = OutboundEmailOutboxRepository(connection)
    receipt_id = repository.enqueue(_intent("receipt", "message-2:receipt"))
    review_id = repository.enqueue(_intent("review", "message-2:review"))

    assert repository.claim_due(limit=1)[0].id == receipt_id
    assert repository.mark_failed(outbox_id=receipt_id, error="recipient unavailable")
    assert [item.id for item in repository.claim_due(limit=10)] == [review_id]


def test_explicit_thread_position_cannot_collide(connection: sqlite3.Connection) -> None:
    repository = OutboundEmailOutboxRepository(connection)
    repository.enqueue(_intent("receipt", "message-position:receipt"))

    with pytest.raises(ValueError, match="already assigned"):
        repository.enqueue(replace(_intent("review", "message-position:review"), thread_position=1))


def test_expired_lease_is_reclaimed_and_send_failure_is_rescheduled(connection: sqlite3.Connection) -> None:
    repository = OutboundEmailOutboxRepository(connection)
    outbox_id = repository.enqueue(_intent("review", "message-3:review"))
    first = repository.claim_due(limit=1, lease_seconds=120)[0]
    connection.execute(
        "UPDATE outbound_email_outbox SET lease_expires_at = '2000-01-01 00:00:00' WHERE id = ?",
        (outbox_id,),
    )
    connection.commit()

    second = repository.claim_due(limit=1, lease_seconds=120)[0]
    assert second.attempts == first.attempts + 1
    assert repository.reschedule(
        outbox_id=outbox_id,
        attempts=second.attempts,
        error="temporary email provider failure",
        max_attempts=3,
        base_backoff_seconds=1,
    ) == "pending"

    row = connection.execute(
        "SELECT status, attempts, lease_expires_at, last_error FROM outbound_email_outbox WHERE id = ?",
        (outbox_id,),
    ).fetchone()
    assert dict(row) == {
        "status": "pending",
        "attempts": 2,
        "lease_expires_at": None,
        "last_error": "temporary email provider failure",
    }


def test_delivery_service_marks_success_and_does_not_reprocess_email(connection: sqlite3.Connection) -> None:
    repository = OutboundEmailOutboxRepository(connection)
    repository.enqueue(_intent("review", "message-4:review"))
    sender = _Sender()

    assert OutboundEmailDeliveryService(repository=repository, sender=sender).drain_once() == 1
    assert sender.messages[0].subject == "Re: Contract"
    assert repository.status() == {"sent": 1}


def _intent(message_type: str, key: str) -> OutboundEmailIntent:
    return OutboundEmailIntent(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        thread_key=key.split(":")[0],
        message_type=message_type,  # type: ignore[arg-type]
        to_address="user@example.com",
        from_address="contracts@samvid.online",
        subject="Re: Contract",
        text_body="Your contract is ready.",
        html_body="<p>Your contract is ready.</p>",
        in_reply_to="<message@example.com>",
        references="<message@example.com>",
        idempotency_key=key,
    )


class _Sender:
    def __init__(self) -> None:
        self.messages: list[OutboundEmailMessage] = []

    def send(self, message: OutboundEmailMessage) -> None:
        self.messages.append(message)
