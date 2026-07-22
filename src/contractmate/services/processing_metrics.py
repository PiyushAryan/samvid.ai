from __future__ import annotations

from typing import Any, Mapping

from contractmate.db.repositories.processing_runs import ProcessingRun, ProcessingRunRepository, ProcessingStage


class ProcessingMetricsService:
    """Typed facade for recording an end-to-end contract-processing timeline."""

    def __init__(self, repository: ProcessingRunRepository) -> None:
        self.repository = repository

    def queue_run(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        source: str,
        job_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingRun:
        return self.repository.create_run(
            workspace_id=workspace_id,
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            source=source,
            job_id=job_id,
            metadata=metadata,
        )

    def worker_started(self, *, run_id: str) -> bool:
        return self.repository.mark_worker_started(run_id=run_id)

    def job_enqueued(self, *, run_id: str, job_id: str) -> bool:
        return self.repository.set_job_id(run_id=run_id, job_id=job_id)

    def stage_started(
        self,
        *,
        run_id: str,
        stage: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingStage:
        return self.repository.start_stage(run_id=run_id, stage=stage, metadata=metadata)

    def stage_finished(
        self,
        *,
        run_id: str,
        stage: str,
        outcome: str = "completed",
        metadata: Mapping[str, Any] | None = None,
    ) -> ProcessingStage:
        return self.repository.complete_stage(
            run_id=run_id,
            stage=stage,
            outcome=outcome,
            metadata=metadata,
        )

    def stage_failed(self, *, run_id: str, stage: str, error: str) -> ProcessingStage:
        return self.repository.complete_stage(
            run_id=run_id,
            stage=stage,
            status="failed",
            outcome="failed",
            error=error,
        )

    def attempt_failed(self, *, run_id: str, stage: str, error: str) -> bool:
        return self.repository.record_attempt_failure(run_id=run_id, stage=stage, error=error)

    def completed(self, *, run_id: str, outcome: str = "review_ready") -> bool:
        return self.repository.mark_succeeded(run_id=run_id, outcome=outcome)

    def failed(self, *, run_id: str, stage: str, error: str) -> bool:
        return self.repository.mark_failed(run_id=run_id, stage=stage, error=error)

    def terminal_failed_for_contract(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        stage: str,
        error: str,
    ) -> bool:
        return self.repository.mark_latest_failed_for_contract(
            workspace_id=workspace_id,
            contract_id=contract_id,
            stage=stage,
            error=error,
        )
