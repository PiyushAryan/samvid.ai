from __future__ import annotations

from pathlib import Path

from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService


class ContractReviewWorkflow:
    def __init__(self, processing_service: ContractProcessingService) -> None:
        self.processing_service = processing_service

    def process_upload(
        self,
        *,
        file_path: Path,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        declared_mime_type: str | None = None,
    ) -> ContractProcessingResult:
        return self.processing_service.review_local_file(
            file_path=file_path,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            declared_mime_type=declared_mime_type,
        )
