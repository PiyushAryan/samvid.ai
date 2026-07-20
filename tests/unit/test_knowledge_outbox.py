from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.contracts import ContractRepository
from contractmate.db.repositories.knowledge_outbox import KnowledgeOutboxRepository
from contractmate.schemas.contracts import ContractReview
from contractmate.services.knowledge_outbox import KnowledgeOutboxDispatcher


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    yield connection
    connection.close()


def test_finalize_review_commits_review_state_audit_and_outbox_atomically(
    connection: sqlite3.Connection,
) -> None:
    _seed_contract(connection)
    repository = ContractRepository(connection)

    review_id, outbox_id = repository.finalize_contract_review(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        review=_review(),
        agent=_agent(),
        removed_findings=2,
    )

    assert connection.execute("SELECT id FROM contract_reviews").fetchone()["id"] == review_id
    assert connection.execute("SELECT status FROM contracts").fetchone()["status"] == "review_ready"
    assert connection.execute("SELECT event_type FROM audit_events").fetchone()["event_type"] == "contract.review_ready"
    outbox = connection.execute("SELECT id, status FROM knowledge_index_outbox").fetchone()
    assert dict(outbox) == {"id": outbox_id, "status": "pending"}


def test_finalize_review_rolls_back_everything_when_outbox_write_fails(
    connection: sqlite3.Connection,
) -> None:
    _seed_contract(connection)
    connection.execute(
        """
        CREATE TRIGGER reject_knowledge_outbox
        BEFORE INSERT ON knowledge_index_outbox
        BEGIN
            SELECT RAISE(ABORT, 'outbox unavailable');
        END
        """
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        ContractRepository(connection).finalize_contract_review(
            workspace_id="workspace-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            review=_review(),
            agent=_agent(),
        )

    assert connection.execute("SELECT status FROM contracts").fetchone()["status"] == "analysing"
    assert connection.execute("SELECT COUNT(*) FROM contract_reviews").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM knowledge_index_outbox").fetchone()[0] == 0


def test_outbox_recovers_expired_lease_and_publishes_at_least_once(
    connection: sqlite3.Connection,
) -> None:
    _seed_contract(connection)
    repository = KnowledgeOutboxRepository(connection)
    outbox_id = repository.enqueue_intent(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
    )

    first_claim = repository.claim_due(limit=1, lease_seconds=120)
    assert first_claim[0].attempts == 1
    connection.execute(
        "UPDATE knowledge_index_outbox SET lease_expires_at = '2000-01-01 00:00:00' WHERE id = ?",
        (outbox_id,),
    )
    connection.commit()

    second_claim = repository.claim_due(limit=1, lease_seconds=120)
    assert second_claim[0].id == outbox_id
    assert second_claim[0].attempts == 2

    publisher = _Publisher()
    dispatcher = KnowledgeOutboxDispatcher(repository=repository, publisher=publisher)
    repository.reschedule(
        outbox_id=outbox_id,
        attempts=second_claim[0].attempts,
        error="temporary broker failure",
        max_attempts=10,
        base_backoff_seconds=1,
    )
    connection.execute(
        "UPDATE knowledge_index_outbox SET next_attempt_at = '2000-01-01 00:00:00' WHERE id = ?",
        (outbox_id,),
    )
    connection.commit()

    assert dispatcher.drain_once() == 1
    assert publisher.calls == [("workspace-1", "contract-1", "version-1")]
    row = connection.execute(
        "SELECT status, attempts, published_at, last_error FROM knowledge_index_outbox WHERE id = ?",
        (outbox_id,),
    ).fetchone()
    assert row["status"] == "published"
    assert row["attempts"] == 3
    assert row["published_at"] is not None
    assert row["last_error"] is None


def test_dispatcher_retains_failed_publish_for_retry(connection: sqlite3.Connection) -> None:
    _seed_contract(connection)
    repository = KnowledgeOutboxRepository(connection)
    outbox_id = repository.enqueue_intent(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
    )
    dispatcher = KnowledgeOutboxDispatcher(
        repository=repository,
        publisher=_Publisher(error=RuntimeError("rabbit unavailable")),
        max_attempts=3,
        base_backoff_seconds=1,
    )

    assert dispatcher.drain_once() == 0

    row = connection.execute(
        "SELECT status, attempts, last_error, next_attempt_at FROM knowledge_index_outbox WHERE id = ?",
        (outbox_id,),
    ).fetchone()
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["last_error"] == "rabbit unavailable"
    assert row["next_attempt_at"] is not None


def test_backfill_retry_and_status_operations(connection: sqlite3.Connection) -> None:
    _seed_contract(connection, status="review_ready")
    connection.execute(
        """
        INSERT INTO contract_reviews(
            id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
        ) VALUES ('review-1', 'version-1', 'openai', 'gpt-test', 'v1', '{}', 'valid')
        """
    )
    connection.commit()
    repository = KnowledgeOutboxRepository(connection)

    assert repository.backfill() == 1
    outbox_id = connection.execute("SELECT id FROM knowledge_index_outbox").fetchone()["id"]
    connection.execute(
        "UPDATE knowledge_index_outbox SET status = 'failed', last_error = 'exhausted' WHERE id = ?",
        (outbox_id,),
    )
    connection.commit()

    assert repository.retry_failed() == {"knowledge_indexes": 0, "outbox_intents": 1}
    assert repository.status()["outbox"] == {"pending": 1}


class _Publisher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def enqueue(self, *, contract_id: str, contract_version_id: str, workspace_id: str):
        self.calls.append((workspace_id, contract_id, contract_version_id))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(job_id="knowledge-job-1")


def _seed_contract(connection: sqlite3.Connection, *, status: str = "analysing") -> None:
    connection.execute(
        """
        INSERT INTO contracts(
            id, workspace_id, email_thread_id, title, status, current_version_id, created_by
        ) VALUES ('contract-1', 'workspace-1', 'thread-1', 'Contract', ?, 'version-1', 'user@example.com')
        """,
        (status,),
    )
    connection.execute(
        """
        INSERT INTO contract_versions(
            id, contract_id, version_number, original_filename, mime_type,
            size_bytes, sha256, s3_object_key, uploaded_by
        ) VALUES (
            'version-1', 'contract-1', 1, 'contract.pdf', 'application/pdf',
            100, 'sha-1', 'object-1', 'user@example.com'
        )
        """
    )
    connection.commit()


def _review() -> ContractReview:
    return ContractReview(
        contract_id="contract-1",
        contract_type="Services agreement",
        recommended_next_action="Review the terms.",
    )


def _agent() -> SimpleNamespace:
    return SimpleNamespace(model_provider="openai", model_name="gpt-test", prompt_version="v1")
