from __future__ import annotations

import base64
import sqlite3

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.slack import OutboundSlackIntent, SlackRepository
from contractmate.security.slack import SlackTokenCipher
from contractmate.services.outbound_slack_delivery import OutboundSlackDeliveryService


@pytest.fixture
def repository() -> SlackRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    yield SlackRepository(connection)
    connection.close()


def test_slack_delivery_preserves_order_and_provider_timestamp(repository: SlackRepository) -> None:
    cipher = SlackTokenCipher(_key())
    installation = repository.upsert_installation(
        team_id="T1", team_name="Example", bot_user_id="B1",
        encrypted_bot_token=cipher.encrypt("xoxb-secret"), installed_by_account_id="account-1",
    )
    repository.enqueue_outbound(_intent(installation.id, "receipt", "receipt-1"))
    repository.enqueue_outbound(_intent(installation.id, "review", "review-1"))
    client = _Client()
    delivery = OutboundSlackDeliveryService(
        repository=repository, token_cipher=cipher, client_factory=lambda _token: client,
    )

    assert delivery.drain_once() == 1
    assert client.calls[0]["thread_ts"] == "123.456"
    assert client.calls[0]["client_msg_id"]
    assert delivery.drain_once() == 1
    rows = repository.connection.execute(
        "SELECT status, provider_message_ts FROM outbound_slack_outbox ORDER BY thread_position"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("sent", "200.1"), ("sent", "200.2")]


def test_accepted_unrecorded_slack_retry_reuses_client_message_id(
    repository: SlackRepository, monkeypatch,
) -> None:
    cipher = SlackTokenCipher(_key())
    installation = repository.upsert_installation(
        team_id="T1", team_name="Example", bot_user_id="B1",
        encrypted_bot_token=cipher.encrypt("xoxb-secret"), installed_by_account_id="account-1",
    )
    outbox_id = repository.enqueue_outbound(_intent(installation.id, "review", "review-dedupe"))
    client = _Client()
    delivery = OutboundSlackDeliveryService(
        repository=repository, token_cipher=cipher, client_factory=lambda _token: client,
    )
    original_mark = repository.mark_outbound_sent
    monkeypatch.setattr(repository, "mark_outbound_sent", lambda **_kwargs: False)
    assert delivery.drain_once() == 0
    monkeypatch.setattr(repository, "mark_outbound_sent", original_mark)
    repository.connection.execute(
        "UPDATE outbound_slack_outbox SET lease_expires_at = '2000-01-01' WHERE id = ?",
        (outbox_id,),
    )
    repository.connection.commit()

    assert delivery.drain_once() == 1
    assert [call["client_msg_id"] for call in client.calls] == [outbox_id, outbox_id]


def test_reclaimed_outbound_lease_rejects_stale_owner(repository: SlackRepository) -> None:
    cipher = SlackTokenCipher(_key())
    installation = repository.upsert_installation(
        team_id="T1", team_name="Example", bot_user_id="B1",
        encrypted_bot_token=cipher.encrypt("xoxb-secret"), installed_by_account_id="account-1",
    )
    outbox_id = repository.enqueue_outbound(_intent(installation.id, "review", "review-owner"))
    original = repository.claim_due_outbound(limit=1, lease_seconds=60)[0]
    repository.connection.execute(
        "UPDATE outbound_slack_outbox SET lease_expires_at = '2000-01-01' WHERE id = ?",
        (outbox_id,),
    )
    repository.connection.commit()
    reclaimed = repository.claim_due_outbound(limit=1, lease_seconds=60)[0]

    assert repository.mark_outbound_sent(
        outbox_id=outbox_id, lease_token=original.lease_token, provider_message_ts="old",
    ) is False
    assert repository.reschedule_outbound(
        outbox_id=outbox_id, lease_token=original.lease_token,
        attempts=original.attempts, error="old owner",
    ) == "stale"
    assert repository.mark_outbound_sent(
        outbox_id=outbox_id, lease_token=reclaimed.lease_token, provider_message_ts="new",
    ) is True


def test_slack_delivery_honors_retry_after(repository: SlackRepository) -> None:
    cipher = SlackTokenCipher(_key())
    installation = repository.upsert_installation(
        team_id="T1", team_name=None, bot_user_id=None,
        encrypted_bot_token=cipher.encrypt("xoxb-secret"), installed_by_account_id="account-1",
    )
    outbox_id = repository.enqueue_outbound(_intent(installation.id, "review", "review-1"))
    response = SlackResponse(
        client=None, http_verb="POST", api_url="chat.postMessage", req_args={},
        data={"ok": False, "error": "ratelimited"}, headers={"Retry-After": "17"}, status_code=429,
    )
    client = _Client(error=SlackApiError("rate limited", response))

    service = OutboundSlackDeliveryService(
        repository=repository, token_cipher=cipher, client_factory=lambda _token: client,
    )
    assert service.drain_once() == 0
    row = repository.connection.execute(
        "SELECT status, last_error, next_attempt_at FROM outbound_slack_outbox WHERE id = ?", (outbox_id,)
    ).fetchone()
    assert row["status"] == "pending"
    assert row["last_error"] == "ratelimited"


def test_file_submission_claim_and_unknown_admission_are_idempotent(repository: SlackRepository) -> None:
    owner = repository.claim_file_submission(event_id="Ev1", file_id="F1")
    assert owner.status == "claimed"
    assert repository.claim_file_submission(event_id="Ev1", file_id="F1").status == "busy"
    assert owner.lease_token
    assert repository.complete_file_submission(
        event_id="Ev1", file_id="F1", lease_token=owner.lease_token,
    ) is True
    repository.connection.execute(
        "UPDATE inbound_slack_file_submissions SET lease_expires_at = '2000-01-01' WHERE event_id = 'Ev1' AND file_id = 'F1'"
    )
    repository.connection.commit()
    assert repository.claim_file_submission(event_id="Ev1", file_id="F1").status == "completed"

    assert repository.consume_unknown_sender_capacity(
        team_id="T1", slack_user_id="U1", attachments=2, event_id="Ev1",
    ) is True
    assert repository.consume_unknown_sender_capacity(
        team_id="T1", slack_user_id="U1", attachments=2, event_id="Ev1",
    ) is True
    rows = repository.connection.execute(
        "SELECT window_kind, attachment_count FROM slack_inbound_rate_limits ORDER BY window_kind"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("day", 2), ("hour", 2)]


def test_reclaimed_file_lease_rejects_stale_owner_completion_and_release(tmp_path) -> None:
    database = tmp_path / "claims.db"
    first_connection = sqlite3.connect(database)
    first_connection.row_factory = sqlite3.Row
    first_connection.executescript(SQLITE_SCHEMA_SQL)
    second_connection = sqlite3.connect(database)
    second_connection.row_factory = sqlite3.Row
    first = SlackRepository(first_connection)
    second = SlackRepository(second_connection)
    try:
        original = first.claim_file_submission(event_id="Ev1", file_id="F1")
        assert original.status == "claimed" and original.lease_token and original.review_job_id
        assert second.claim_file_submission(event_id="Ev1", file_id="F1").status == "busy"
        first_connection.execute(
            "UPDATE inbound_slack_file_submissions SET lease_expires_at = '2000-01-01' WHERE event_id = 'Ev1' AND file_id = 'F1'"
        )
        first_connection.commit()

        reclaimed = second.claim_file_submission(event_id="Ev1", file_id="F1")
        assert reclaimed.status == "claimed" and reclaimed.lease_token
        assert reclaimed.review_job_id == original.review_job_id
        assert first.complete_file_submission(
            event_id="Ev1", file_id="F1", lease_token=original.lease_token,
        ) is False
        assert first.release_file_submission(
            event_id="Ev1", file_id="F1", lease_token=original.lease_token,
        ) is False
        assert second.complete_file_submission(
            event_id="Ev1", file_id="F1", lease_token=reclaimed.lease_token,
        ) is True
    finally:
        first_connection.close()
        second_connection.close()


def test_review_execution_lease_deduplicates_ambiguous_publish(repository: SlackRepository) -> None:
    original = repository.claim_review_execution(submission_key="Ev1:F1")
    assert original.status == "claimed" and original.lease_token
    assert repository.renew_review_execution(
        submission_key="Ev1:F1", lease_token=original.lease_token, lease_seconds=900,
    ) is True
    assert repository.claim_review_execution(submission_key="Ev1:F1").status == "busy"
    repository.connection.execute(
        "UPDATE slack_review_executions SET lease_expires_at = '2000-01-01' WHERE submission_key = 'Ev1:F1'"
    )
    repository.connection.commit()
    reclaimed = repository.claim_review_execution(submission_key="Ev1:F1")
    assert reclaimed.status == "claimed" and reclaimed.lease_token
    assert repository.renew_review_execution(
        submission_key="Ev1:F1", lease_token=original.lease_token,
    ) is False
    assert repository.release_review_execution(
        submission_key="Ev1:F1", lease_token=original.lease_token,
    ) is False
    assert repository.complete_review_execution(
        submission_key="Ev1:F1", lease_token=reclaimed.lease_token,
    ) is True
    assert repository.claim_review_execution(submission_key="Ev1:F1").status == "completed"


def test_review_publish_outbox_rejects_stale_dispatcher_owner(repository: SlackRepository) -> None:
    payload = {
        "job_id": "job-1", "contract_id": "contract-1",
        "contract_version_id": "version-1", "workspace_id": "workspace-1",
        "email_thread_id": "slack:T1:C1:1.0", "requested_by": "user@example.com",
        "source_channel": "slack", "source_submission_key": "Ev1:F1",
    }
    repository.persist_review_job(
        submission_key="Ev1:F1", job_id="job-1", payload=payload,
    )
    original = repository.claim_due_review_jobs(limit=1, lease_seconds=60)[0]
    repository.connection.execute(
        "UPDATE slack_review_job_outbox SET lease_expires_at = '2000-01-01' WHERE submission_key = 'Ev1:F1'"
    )
    repository.connection.commit()
    reclaimed = repository.claim_due_review_jobs(limit=1, lease_seconds=60)[0]

    assert repository.mark_review_job_published(
        submission_key="Ev1:F1", lease_token=original.lease_token,
    ) is False
    assert repository.retry_review_job_publish(
        submission_key="Ev1:F1", lease_token=original.lease_token,
        attempts=original.attempts, error="stale",
    ) is False
    assert repository.mark_review_job_published(
        submission_key="Ev1:F1", lease_token=reclaimed.lease_token,
    ) is True


def test_reclaimed_event_rejects_stale_owner_and_busy_contention_preserves_attempts(repository: SlackRepository) -> None:
    repository.enqueue_event(
        event_id="Ev1", team_id="T1", event_type="app_mention",
        payload={"event": {"type": "app_mention", "channel": "C1", "ts": "1.0", "files": [{"id": "F1"}]}},
    )
    original_event = repository.claim_due_events(limit=1, lease_seconds=60)[0]
    file_owner = repository.claim_file_submission(event_id="Ev1", file_id="F1", lease_seconds=300)
    assert file_owner.status == "claimed"
    repository.connection.execute(
        "UPDATE inbound_slack_events SET lease_expires_at = '2000-01-01' WHERE id = ?", (original_event.id,)
    )
    repository.connection.commit()
    reclaimed_event = repository.claim_due_events(limit=1, lease_seconds=60)[0]
    assert repository.claim_file_submission(event_id="Ev1", file_id="F1").status == "busy"
    assert repository.complete_event(
        event_id=original_event.id, lease_token=original_event.lease_token, status="processed",
    ) is False
    assert repository.retry_event(
        event_id=original_event.id, lease_token=original_event.lease_token,
        attempts=original_event.attempts, error="stale",
    ) == "stale"
    assert repository.retry_event_contention(
        event_id=reclaimed_event.id, lease_token=reclaimed_event.lease_token, retry_after_seconds=1,
    ) is True
    row = repository.connection.execute(
        "SELECT status, attempts FROM inbound_slack_events WHERE id = ?", (original_event.id,)
    ).fetchone()
    assert tuple(row) == ("pending", 1)
    for _ in range(5):
        repository.connection.execute(
            "UPDATE inbound_slack_events SET next_attempt_at = '2000-01-01' WHERE id = ?", (original_event.id,)
        )
        repository.connection.commit()
        contended = repository.claim_due_events(limit=1, lease_seconds=60)[0]
        assert repository.claim_file_submission(event_id="Ev1", file_id="F1").status == "busy"
        assert repository.retry_event_contention(
            event_id=contended.id, lease_token=contended.lease_token, retry_after_seconds=1,
        )
        attempts = repository.connection.execute(
            "SELECT attempts FROM inbound_slack_events WHERE id = ?", (original_event.id,)
        ).fetchone()["attempts"]
        assert attempts == 1


class _Client:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def chat_postMessage(self, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(kwargs)
        return {"ok": True, "ts": f"200.{len(self.calls)}"}


def _intent(installation_id: str, message_type: str, key: str) -> OutboundSlackIntent:
    return OutboundSlackIntent(
        workspace_id="workspace-1", installation_id=installation_id,
        channel_id="C1", thread_ts="123.456", message_type=message_type,  # type: ignore[arg-type]
        text_body=message_type, idempotency_key=key,
    )


def _key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode()
