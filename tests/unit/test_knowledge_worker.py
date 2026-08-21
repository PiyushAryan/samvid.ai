from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import DocumentPage, ParsedDocument
from contractmate.settings import Settings
from contractmate.workers.knowledge_worker import KnowledgeIndexWorker, _load_index_inputs


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    return connection


def _seed_contract(connection: sqlite3.Connection, *, contract_id: str, version_id: str) -> None:
    parsed = ParsedDocument(
        document_id=f"parsed-{version_id}",
        sha256="a" * 64,
        mime_type="text/plain",
        page_count=1,
        pages=[DocumentPage(page_number=1, text=f"Text for {contract_id}")],
        parser_name="test",
        parser_version="1",
    )
    review = ContractReview(
        contract_id=contract_id,
        contract_type="Test agreement",
        recommended_next_action="Review the agreement.",
    )
    connection.execute(
        """
        INSERT INTO contracts(id, workspace_id, email_thread_id, title, status, current_version_id, created_by)
        VALUES (?, 'workspace-1', ?, ?, 'reviewed', ?, 'test@example.com')
        """,
        (contract_id, f"thread-{contract_id}", contract_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO contract_versions(
            id, contract_id, version_number, original_filename, mime_type,
            size_bytes, sha256, s3_object_key, uploaded_by
        ) VALUES (?, ?, 1, 'contract.txt', 'text/plain', 10, ?, ?, 'test@example.com')
        """,
        (version_id, contract_id, f"sha-{version_id}", f"object-{version_id}"),
    )
    connection.execute(
        """
        INSERT INTO parsed_documents(
            id, contract_version_id, parser_name, parser_version, page_count,
            requires_ocr, content_json, warnings_json
        ) VALUES (?, ?, 'test', '1', 1, 0, ?, '[]')
        """,
        (f"parsed-{version_id}", version_id, parsed.model_dump_json()),
    )
    connection.execute(
        """
        INSERT INTO contract_reviews(
            id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
        ) VALUES (?, ?, 'test', 'test', '1', ?, 'ready')
        """,
        (f"review-{version_id}", version_id, review.model_dump_json()),
    )
    connection.commit()


def test_load_index_inputs_requires_version_to_belong_to_queued_contract() -> None:
    connection = _connection()
    try:
        _seed_contract(connection, contract_id="contract-a", version_id="version-a")
        _seed_contract(connection, contract_id="contract-b", version_id="version-b")

        with pytest.raises(ValueError, match="expected workspace"):
            _load_index_inputs(
                connection,
                workspace_id="workspace-1",
                contract_id="contract-a",
                contract_version_id="version-b",
            )
    finally:
        connection.close()


def test_load_index_inputs_returns_matching_contract_version() -> None:
    connection = _connection()
    try:
        _seed_contract(connection, contract_id="contract-a", version_id="version-a")

        parsed, review = _load_index_inputs(
            connection,
            workspace_id="workspace-1",
            contract_id="contract-a",
            contract_version_id="version-a",
        )

        assert parsed.document_id == "parsed-version-a"
        assert review.contract_id == "contract-a"
    finally:
        connection.close()


def test_worker_acknowledges_index_job_for_deleted_contract(monkeypatch) -> None:
    connection = _connection()
    monkeypatch.setattr("contractmate.workers.knowledge_worker.connect", lambda _database_url: connection)

    class Delivery:
        def __init__(self) -> None:
            self.job = SimpleNamespace(
                job_id="job-deleted",
                workspace_id="workspace-1",
                contract_id="contract-deleted",
                contract_version_id="version-deleted",
                attempt=1,
            )
            self.acked = False
            self.retried = False

        def ack(self) -> None:
            self.acked = True

        def retry(self) -> None:
            self.retried = True

    delivery = Delivery()
    worker = KnowledgeIndexWorker(
        settings=Settings(
            database_url="sqlite:///:memory:",
            contract_processing_mode="rabbitmq",
            ai_gateway_api_key="test-key",
        ),
        queue=None,  # type: ignore[arg-type]
    )

    worker._process_delivery(delivery)

    assert delivery.acked
    assert not delivery.retried


@pytest.mark.parametrize(
    ("attempt", "expected_outbox_status"),
    [(1, "published"), (3, "failed")],
)
def test_worker_persists_sanitized_index_and_outbox_failure(
    monkeypatch,
    attempt: int,
    expected_outbox_status: str,
) -> None:
    connection = _connection()
    _seed_contract(connection, contract_id="contract-a", version_id="version-a")
    connection.execute(
        """
        INSERT INTO knowledge_index_outbox(
            id, workspace_id, contract_id, contract_version_id, status
        ) VALUES ('outbox-a', 'workspace-1', 'contract-a', 'version-a', 'published')
        """
    )
    connection.commit()
    monkeypatch.setattr("contractmate.workers.knowledge_worker.connect", lambda _database_url: _ConnectionProxy(connection))

    def fail_indexing(*_args, **_kwargs):
        raise RuntimeError("provider failed with api_key=top-secret")

    monkeypatch.setattr(
        "contractmate.workers.knowledge_worker.KnowledgeIndexingService.index_contract",
        fail_indexing,
    )
    delivery = _Delivery(attempt=attempt, outbox_id="outbox-a")
    worker = KnowledgeIndexWorker(
        settings=Settings(
            database_url="sqlite:///:memory:",
            contract_processing_mode="rabbitmq",
            ai_gateway_api_key="top-secret",
            rabbitmq_max_attempts=3,
        ),
        queue=None,  # type: ignore[arg-type]
    )

    worker._process_delivery(delivery)

    index = connection.execute("SELECT status, error_message FROM knowledge_indexes").fetchone()
    assert index["status"] == "failed"
    assert "top-secret" not in index["error_message"]
    assert "[redacted]" in index["error_message"]
    outbox = connection.execute(
        "SELECT status, last_error FROM knowledge_index_outbox WHERE id = 'outbox-a'"
    ).fetchone()
    assert outbox["status"] == expected_outbox_status
    assert outbox["last_error"] == index["error_message"]
    assert delivery.retried
    assert not delivery.acked
    connection.close()


class _ConnectionProxy:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def close(self) -> None:
        pass


class _Delivery:
    def __init__(self, *, attempt: int, outbox_id: str | None) -> None:
        self.job = SimpleNamespace(
            job_id="job-a",
            workspace_id="workspace-1",
            contract_id="contract-a",
            contract_version_id="version-a",
            attempt=attempt,
            outbox_id=outbox_id,
        )
        self.acked = False
        self.retried = False

    def ack(self) -> None:
        self.acked = True

    def retry(self) -> None:
        self.retried = True
