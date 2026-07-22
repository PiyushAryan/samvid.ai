from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Literal, Mapping
from uuid import uuid4


ProcessingRunStatus = Literal["queued", "running", "succeeded", "failed"]
ProcessingStageStatus = Literal["running", "succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class ProcessingRun:
    id: str
    workspace_id: str
    contract_id: str
    contract_version_id: str
    job_id: str | None
    source: str
    status: ProcessingRunStatus
    outcome: str | None
    queued_at: datetime | None
    worker_started_at: datetime | None
    completed_at: datetime | None
    failure_stage: str | None
    failure_error: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProcessingStage:
    id: str
    processing_run_id: str
    stage: str
    status: ProcessingStageStatus
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    outcome: str | None
    error: str | None
    metadata: dict[str, Any]


class ProcessingRunRepository:
    """Durable timeline for contract-processing latency and failure analysis."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_run(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        source: str,
        job_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingRun:
        run_id = str(uuid4())
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO contract_processing_runs(
                        id, workspace_id, contract_id, contract_version_id,
                        job_id, source, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
                    """
                ),
                (
                    run_id,
                    workspace_id,
                    contract_id,
                    contract_version_id,
                    job_id,
                    source,
                    json.dumps(dict(metadata or {}), sort_keys=True),
                ),
            )
        run = self.get(run_id=run_id)
        if run is None:
            raise RuntimeError("Processing run could not be persisted")
        return run

    def mark_worker_started(self, *, run_id: str) -> bool:
        """Start a processing attempt without discarding prior retry history."""
        with self._transaction():
            row = self.connection.execute(
                self._sql("SELECT status, metadata_json FROM contract_processing_runs WHERE id = ?"),
                (run_id,),
            ).fetchone()
            if row is None or str(row["status"]) not in {"queued", "running"}:
                return False
            metadata = self._metadata_from_row(row)
            history = self._attempt_history(metadata)
            attempt = len(history) + 1
            history.append({"attempt": attempt, "started_at": self._metadata_timestamp()})
            metadata["attempt_count"] = attempt
            metadata["attempt_history"] = history
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_runs
                    SET status = 'running', worker_started_at = COALESCE(worker_started_at, CURRENT_TIMESTAMP),
                        metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('queued', 'running')
                    """
                ),
                (json.dumps(metadata, sort_keys=True), run_id),
            )
        return updated.rowcount == 1

    def set_job_id(self, *, run_id: str, job_id: str) -> bool:
        """Attach the broker job identifier after successful enqueueing."""
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_runs
                    SET job_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND job_id IS NULL
                    """
                ),
                (job_id, run_id),
            )
        return updated.rowcount == 1

    def start_stage(
        self,
        *,
        run_id: str,
        stage: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingStage:
        stage_id = str(uuid4())
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO contract_processing_stages(
                        id, processing_run_id, stage, status, metadata_json
                    ) VALUES (?, ?, ?, 'running', ?)
                    ON CONFLICT (processing_run_id, stage) DO UPDATE SET
                        status = 'running', started_at = CURRENT_TIMESTAMP,
                        completed_at = NULL, duration_ms = NULL, outcome = NULL,
                        error = NULL, metadata_json = EXCLUDED.metadata_json
                    """
                ),
                (stage_id, run_id, stage, json.dumps(dict(metadata or {}), sort_keys=True)),
            )
        persisted = self.get_stage(run_id=run_id, stage=stage)
        if persisted is None:
            raise RuntimeError("Processing stage could not be persisted")
        return persisted

    def complete_stage(
        self,
        *,
        run_id: str,
        stage: str,
        status: ProcessingStageStatus = "succeeded",
        outcome: str | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingStage:
        if status == "running":
            raise ValueError("A completed processing stage cannot remain running")
        stage_row = self.get_stage(run_id=run_id, stage=stage)
        if stage_row is None:
            stage_row = self.start_stage(run_id=run_id, stage=stage)
        completed_at = datetime.now(timezone.utc)
        started_at = stage_row.started_at or completed_at
        duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_stages
                    SET status = ?, completed_at = ?, duration_ms = ?, outcome = ?, error = ?,
                        metadata_json = ?
                    WHERE processing_run_id = ? AND stage = ?
                    """
                ),
                (
                    status,
                    self._timestamp(completed_at),
                    duration_ms,
                    outcome,
                    error[:4000] if error else None,
                    json.dumps(dict(metadata or stage_row.metadata), sort_keys=True),
                    run_id,
                    stage,
                ),
            )
        persisted = self.get_stage(run_id=run_id, stage=stage)
        if persisted is None:
            raise RuntimeError("Processing stage could not be completed")
        return persisted

    def mark_succeeded(self, *, run_id: str, outcome: str = "review_ready") -> bool:
        with self._transaction():
            row = self.connection.execute(
                self._sql("SELECT status, metadata_json FROM contract_processing_runs WHERE id = ?"),
                (run_id,),
            ).fetchone()
            if row is None or str(row["status"]) not in {"queued", "running"}:
                return False
            metadata = self._metadata_from_row(row)
            history = self._attempt_history(metadata)
            if history:
                history[-1].update({"completed_at": self._metadata_timestamp(), "outcome": outcome})
                metadata["attempt_history"] = history
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_runs
                    SET status = 'succeeded', outcome = ?, completed_at = CURRENT_TIMESTAMP,
                        failure_stage = NULL, failure_error = NULL, metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('queued', 'running')
                    """
                ),
                (outcome, json.dumps(metadata, sort_keys=True), run_id),
            )
        return updated.rowcount == 1

    def record_attempt_failure(self, *, run_id: str, stage: str, error: str) -> bool:
        """Record a retryable failure while keeping the overall run active.

        The compact attempt history avoids a schema migration while preserving the
        useful error context that would otherwise be overwritten by a later retry.
        """

        with self._transaction():
            row = self.connection.execute(
                self._sql("SELECT status, metadata_json FROM contract_processing_runs WHERE id = ?"),
                (run_id,),
            ).fetchone()
            if row is None or str(row["status"]) not in {"queued", "running"}:
                return False
            metadata = self._metadata_from_row(row)
            history = self._attempt_history(metadata)
            if not history:
                history.append({"attempt": 1, "started_at": self._metadata_timestamp()})
            latest = history[-1]
            latest.update(
                {
                    "failed_at": self._metadata_timestamp(),
                    "failure_stage": stage,
                    "failure_error": error[:4000],
                    "terminal": False,
                }
            )
            metadata["attempt_count"] = len(history)
            metadata["attempt_history"] = history
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_runs
                    SET status = 'running', outcome = NULL, completed_at = NULL,
                        failure_stage = NULL, failure_error = NULL, metadata_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('queued', 'running')
                    """
                ),
                (json.dumps(metadata, sort_keys=True), run_id),
            )
        return updated.rowcount == 1

    def mark_failed(self, *, run_id: str, stage: str, error: str, outcome: str = "failed") -> bool:
        with self._transaction():
            row = self.connection.execute(
                self._sql("SELECT status, metadata_json FROM contract_processing_runs WHERE id = ?"),
                (run_id,),
            ).fetchone()
            if row is None or str(row["status"]) not in {"queued", "running"}:
                return False
            metadata = self._metadata_from_row(row)
            history = self._attempt_history(metadata)
            if not history:
                history.append({"attempt": 1, "started_at": self._metadata_timestamp()})
            latest = history[-1]
            latest.update(
                {
                    "failed_at": self._metadata_timestamp(),
                    "failure_stage": stage,
                    "failure_error": error[:4000],
                    "terminal": True,
                }
            )
            metadata["attempt_count"] = len(history)
            metadata["attempt_history"] = history
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contract_processing_runs
                    SET status = 'failed', outcome = ?, completed_at = CURRENT_TIMESTAMP,
                        failure_stage = ?, failure_error = ?, metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('queued', 'running')
                    """
                ),
                (outcome, stage, error[:4000], json.dumps(metadata, sort_keys=True), run_id),
            )
        return updated.rowcount == 1

    def mark_latest_failed_for_contract(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        stage: str,
        error: str,
    ) -> bool:
        """Terminalize the currently active run when the worker exhausts retries."""

        row = self.connection.execute(
            self._sql(
                """
                SELECT id
                FROM contract_processing_runs
                WHERE workspace_id = ? AND contract_id = ? AND status IN ('queued', 'running')
                ORDER BY queued_at DESC, id DESC
                LIMIT 1
                """
            ),
            (workspace_id, contract_id),
        ).fetchone()
        if row is None:
            return False
        return self.mark_failed(run_id=str(row["id"]), stage=stage, error=error)

    def get(self, *, run_id: str) -> ProcessingRun | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM contract_processing_runs WHERE id = ?"),
            (run_id,),
        ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_recent(self, *, limit: int = 500) -> list[ProcessingRun]:
        """Return recent runs for operational latency reporting, newest first."""
        rows = self.connection.execute(
            self._sql(
                """
                SELECT * FROM contract_processing_runs
                ORDER BY queued_at DESC, id DESC
                LIMIT ?
                """
            ),
            (max(1, min(limit, 2_000)),),
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_stage(self, *, run_id: str, stage: str) -> ProcessingStage | None:
        row = self.connection.execute(
            self._sql(
                "SELECT * FROM contract_processing_stages WHERE processing_run_id = ? AND stage = ?"
            ),
            (run_id, stage),
        ).fetchone()
        return self._stage_from_row(row) if row is not None else None

    def list_stages(self, *, run_id: str) -> list[ProcessingStage]:
        rows = self.connection.execute(
            self._sql(
                "SELECT * FROM contract_processing_stages WHERE processing_run_id = ? ORDER BY started_at, id"
            ),
            (run_id,),
        ).fetchall()
        return [self._stage_from_row(row) for row in rows]

    def _run_from_row(self, row: Any) -> ProcessingRun:
        return ProcessingRun(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            contract_id=str(row["contract_id"]),
            contract_version_id=str(row["contract_version_id"]),
            job_id=str(row["job_id"]) if row["job_id"] is not None else None,
            source=str(row["source"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            outcome=str(row["outcome"]) if row["outcome"] is not None else None,
            queued_at=self._datetime(row["queued_at"]),
            worker_started_at=self._datetime(row["worker_started_at"]),
            completed_at=self._datetime(row["completed_at"]),
            failure_stage=str(row["failure_stage"]) if row["failure_stage"] is not None else None,
            failure_error=str(row["failure_error"]) if row["failure_error"] is not None else None,
            metadata=self._metadata_from_row(row),
        )

    def _stage_from_row(self, row: Any) -> ProcessingStage:
        return ProcessingStage(
            id=str(row["id"]),
            processing_run_id=str(row["processing_run_id"]),
            stage=str(row["stage"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            started_at=self._datetime(row["started_at"]),
            completed_at=self._datetime(row["completed_at"]),
            duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            outcome=str(row["outcome"]) if row["outcome"] is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            metadata=self._metadata_from_row(row),
        )

    @staticmethod
    def _attempt_history(metadata: dict[str, Any]) -> list[dict[str, Any]]:
        raw_history = metadata.get("attempt_history")
        if not isinstance(raw_history, list):
            return []
        return [dict(entry) for entry in raw_history if isinstance(entry, Mapping)]

    @staticmethod
    def _metadata_from_row(row: Any) -> dict[str, Any]:
        raw_metadata = row["metadata_json"]
        if isinstance(raw_metadata, str):
            decoded = json.loads(raw_metadata)
            return dict(decoded) if isinstance(decoded, Mapping) else {}
        return dict(raw_metadata or {})

    @staticmethod
    def _metadata_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    def _timestamp(self, value: datetime) -> datetime | str:
        return value if self.is_postgres else value.isoformat(sep=" ", timespec="microseconds")

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
