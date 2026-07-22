from __future__ import annotations

import sqlite3

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.processing_runs import ProcessingRunRepository
from contractmate.services.processing_metrics import ProcessingMetricsService


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    yield connection
    connection.close()


def test_processing_run_records_stage_timestamps_duration_and_success(connection: sqlite3.Connection) -> None:
    metrics = ProcessingMetricsService(ProcessingRunRepository(connection))
    run = metrics.queue_run(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        source="email",
        job_id="job-1",
        metadata={"correlation_id": "trace-1"},
    )

    assert run.status == "queued"
    assert metrics.worker_started(run_id=run.id)
    metrics.stage_started(run_id=run.id, stage="blob_download", metadata={"object_key": "contracts/a.pdf"})
    stage = metrics.stage_finished(run_id=run.id, stage="blob_download", outcome="downloaded")
    assert stage.status == "succeeded"
    assert stage.duration_ms is not None and stage.duration_ms >= 0
    assert stage.metadata == {"object_key": "contracts/a.pdf"}
    assert metrics.completed(run_id=run.id)

    persisted = metrics.repository.get(run_id=run.id)
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.outcome == "review_ready"
    assert persisted.worker_started_at is not None
    assert persisted.completed_at is not None


def test_processing_run_records_stage_and_run_failure(connection: sqlite3.Connection) -> None:
    repository = ProcessingRunRepository(connection)
    run = repository.create_run(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        source="browser_upload",
    )
    repository.mark_worker_started(run_id=run.id)
    stage = repository.complete_stage(
        run_id=run.id,
        stage="ocr",
        status="failed",
        outcome="provider_error",
        error="Sarvam timed out",
    )
    assert stage.status == "failed"
    assert stage.error == "Sarvam timed out"
    assert repository.mark_failed(run_id=run.id, stage="ocr", error="Sarvam timed out")

    persisted = repository.get(run_id=run.id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.failure_stage == "ocr"
    assert persisted.failure_error == "Sarvam timed out"


def test_retryable_attempt_failure_can_later_succeed(connection: sqlite3.Connection) -> None:
    repository = ProcessingRunRepository(connection)
    run = repository.create_run(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        source="inbound_email",
    )

    assert repository.mark_worker_started(run_id=run.id)
    assert repository.record_attempt_failure(run_id=run.id, stage="review", error="temporary timeout")
    assert repository.mark_worker_started(run_id=run.id)
    assert repository.mark_succeeded(run_id=run.id)

    persisted = repository.get(run_id=run.id)
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.failure_error is None
    assert persisted.metadata["attempt_count"] == 2
    assert persisted.metadata["attempt_history"][0]["failure_error"] == "temporary timeout"
    assert persisted.metadata["attempt_history"][0]["terminal"] is False
    assert persisted.metadata["attempt_history"][1]["outcome"] == "review_ready"
