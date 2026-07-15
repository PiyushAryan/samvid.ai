from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from contractmate.db.repositories.contracts import ContractRepository
from contractmate.db.session import connect
from contractmate.ocr.base import OCRBackend, OCRProcessingError
from contractmate.ocr.sarvam_vision import SarvamVisionOCR
from contractmate.parsers.pdfmuse_parser import PdfMuseDocumentParser
from contractmate.schemas.contracts import ContractReview
from contractmate.security.file_validation import validate_uploaded_file
from contractmate.services.audit_service import AuditService
from contractmate.services.review_service import ReviewService
from contractmate.settings import Settings
from contractmate.tools.document_storage import LocalDocumentStorage
from contractmate.workflows.states import WorkflowState


class ContractProcessingResult(BaseModel):
    contract_id: str
    contract_version_id: str
    status: WorkflowState
    review: ContractReview | None = None
    message: str


class ContractProcessingService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: ContractRepository,
        audit: AuditService,
        storage: LocalDocumentStorage,
        parser: PdfMuseDocumentParser,
        ocr_backend: OCRBackend | None,
        review_service: ReviewService,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.audit = audit
        self.storage = storage
        self.parser = parser
        self.ocr_backend = ocr_backend
        self.review_service = review_service

    @classmethod
    def local(cls, settings: Settings) -> "ContractProcessingService":
        connection = connect(settings.database_url)
        return cls(
            settings=settings,
            repository=ContractRepository(connection),
            audit=AuditService(connection),
            storage=LocalDocumentStorage(settings.local_storage_dir),
            parser=PdfMuseDocumentParser(),
            ocr_backend=_ocr_backend_from_settings(settings),
            review_service=ReviewService.from_settings(settings),
        )

    def review_local_file(
        self,
        *,
        file_path: Path,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        declared_mime_type: str | None = None,
    ) -> ContractProcessingResult:
        validation = validate_uploaded_file(
            file_path,
            declared_mime_type=declared_mime_type,
            max_size_mb=self.settings.max_file_size_mb,
        )
        if not validation.ok:
            return ContractProcessingResult(
                contract_id="",
                contract_version_id="",
                status=WorkflowState.REJECTED_FILE,
                review=None,
                message=validation.message or validation.error_code or "File rejected.",
            )

        assert validation.sha256 and validation.mime_type
        stored = self.storage.store_contract_file(
            file_path,
            workspace_id=workspace_id,
            sha256=validation.sha256,
        )
        contract_id, version_id = self.repository.create_contract_with_version(
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            title=file_path.name,
            original_filename=file_path.name,
            mime_type=validation.mime_type,
            size_bytes=validation.size_bytes,
            sha256=validation.sha256,
            object_key=stored.object_key,
            uploaded_by=requested_by,
        )
        self.audit.record(
            workspace_id=workspace_id,
            contract_id=contract_id,
            actor_type="user",
            actor_id=requested_by,
            event_type="contract.received",
            metadata={"filename": file_path.name, "size_bytes": validation.size_bytes},
        )

        self.repository.update_contract_status(contract_id, WorkflowState.PARSING)
        parsed = self.parser.parse(
            stored.file_path,
            document_id=contract_id,
            sha256=validation.sha256,
            mime_type=validation.mime_type,
        )
        self.repository.save_parsed_document(contract_version_id=version_id, parsed_document=parsed)
        if parsed.requires_ocr:
            if self.ocr_backend is None or not self.ocr_backend.supports(parsed.mime_type):
                self.repository.update_contract_status(contract_id, WorkflowState.OCR_REQUIRED)
                return ContractProcessingResult(
                    contract_id=contract_id,
                    contract_version_id=version_id,
                    status=WorkflowState.OCR_REQUIRED,
                    review=None,
                    message="The document requires OCR, but no compatible OCR provider is enabled.",
                )
            self.audit.record(
                workspace_id=workspace_id,
                contract_id=contract_id,
                event_type="contract.ocr_started",
                metadata={"provider": self.settings.ocr_provider},
            )
            try:
                parsed = self.ocr_backend.extract(stored.file_path, parsed_document=parsed)
            except OCRProcessingError as exc:
                self.repository.update_contract_status(contract_id, WorkflowState.PARSE_FAILED)
                self.audit.record(
                    workspace_id=workspace_id,
                    contract_id=contract_id,
                    event_type="contract.ocr_failed",
                    metadata={"provider": self.settings.ocr_provider, "error": str(exc)},
                )
                return ContractProcessingResult(
                    contract_id=contract_id,
                    contract_version_id=version_id,
                    status=WorkflowState.PARSE_FAILED,
                    review=None,
                    message=f"OCR could not process the document: {exc}",
                )
            self.repository.save_parsed_document(contract_version_id=version_id, parsed_document=parsed)
            self.audit.record(
                workspace_id=workspace_id,
                contract_id=contract_id,
                event_type="contract.ocr_completed",
                metadata={"provider": self.settings.ocr_provider, "page_count": parsed.page_count},
            )

        self.repository.update_contract_status(contract_id, WorkflowState.ANALYSING)
        validation_result = self.review_service.create_validated_review(
            contract_id=contract_id,
            parsed_document=parsed,
        )
        self.repository.save_contract_review(
            contract_version_id=version_id,
            review=validation_result.valid_review,
            agent=self.review_service.agent,
            status="valid" if not validation_result.issues else "valid_with_removed_findings",
        )
        self.repository.update_contract_status(contract_id, WorkflowState.REVIEW_READY)
        self.audit.record(
            workspace_id=workspace_id,
            contract_id=contract_id,
            event_type="contract.review_ready",
            metadata={"removed_findings": len(validation_result.issues)},
        )
        return ContractProcessingResult(
            contract_id=contract_id,
            contract_version_id=version_id,
            status=WorkflowState.REVIEW_READY,
            review=validation_result.valid_review,
            message="Contract review is ready.",
        )


def _ocr_backend_from_settings(settings: Settings) -> OCRBackend | None:
    if not settings.enable_ocr:
        return None
    if settings.ocr_provider.casefold() != "sarvam":
        raise ValueError(f"Unsupported OCR_PROVIDER={settings.ocr_provider!r}. Use 'sarvam'.")
    if not settings.sarvam_api_key:
        raise RuntimeError("SARVAM_API_KEY is required when ENABLE_OCR=true.")
    return SarvamVisionOCR(
        api_key=settings.sarvam_api_key,
        language=settings.sarvam_ocr_language,
        timeout_seconds=settings.sarvam_ocr_timeout_seconds,
    )
