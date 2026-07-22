from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel

from contractmate.db.repositories.contracts import ContractRepository
from contractmate.db.session import connect, initialize_database
from contractmate.ocr.base import OCRBackend, OCRProcessingError
from contractmate.ocr.sarvam_vision import SarvamVisionOCR
from contractmate.parsers.pdfmuse_parser import PdfMuseDocumentParser
from contractmate.schemas.contracts import ContractReview
from contractmate.security.file_validation import validate_uploaded_file
from contractmate.services.audit_service import AuditService
from contractmate.db.repositories.processing_runs import ProcessingRunRepository
from contractmate.services.processing_metrics import ProcessingMetricsService
from contractmate.services.review_service import ReviewService
from contractmate.settings import Settings
from contractmate.tools.document_storage import DocumentStorage, StoredDocument, document_storage_from_settings
from contractmate.workers.queue import ContractQueue
from contractmate.workflows.states import WorkflowState


logger = logging.getLogger(__name__)


class ContractProcessingResult(BaseModel):
    contract_id: str
    contract_version_id: str
    status: WorkflowState
    review: ContractReview | None = None
    message: str
    processing_run_id: str | None = None


@dataclass(frozen=True)
class IngestedContract:
    contract_id: str
    contract_version_id: str
    workspace_id: str
    email_thread_id: str
    requested_by: str
    original_filename: str
    mime_type: str
    sha256: str
    object_key: str


class ContractProcessingService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: ContractRepository,
        audit: AuditService,
        storage: DocumentStorage,
        parser: PdfMuseDocumentParser,
        ocr_backend: OCRBackend | None,
        review_service: ReviewService,
        metrics: ProcessingMetricsService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.audit = audit
        self.storage = storage
        self.parser = parser
        self.ocr_backend = ocr_backend
        self.review_service = review_service
        self.metrics = metrics or ProcessingMetricsService(ProcessingRunRepository(repository.connection))

    @classmethod
    def local(cls, settings: Settings) -> "ContractProcessingService":
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)
        connection = connect(settings.database_url)
        return cls(
            settings=settings,
            repository=ContractRepository(connection),
            audit=AuditService(connection),
            storage=document_storage_from_settings(settings),
            parser=PdfMuseDocumentParser(),
            ocr_backend=_ocr_backend_from_settings(settings),
            review_service=ReviewService.from_settings(settings),
            metrics=ProcessingMetricsService(ProcessingRunRepository(connection)),
        )

    def review_local_file(
        self,
        *,
        file_path: Path,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        declared_mime_type: str | None = None,
        original_filename: str | None = None,
        stored_object_key: str | None = None,
    ) -> ContractProcessingResult:
        ingested = self._ingest_local_file(
            file_path=file_path,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            declared_mime_type=declared_mime_type,
            original_filename=original_filename,
            stored_object_key=stored_object_key,
        )
        if isinstance(ingested, ContractProcessingResult):
            return ingested
        return self._review_ingested_file(ingested=ingested, file_path=file_path)

    def enqueue_local_file(
        self,
        *,
        queue: ContractQueue,
        file_path: Path,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        declared_mime_type: str | None = None,
        original_filename: str | None = None,
        stored_object_key: str | None = None,
        send_review_email: bool = False,
        recipient_name: str | None = None,
        response_address: str | None = None,
        original_subject: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> ContractProcessingResult:
        ingested = self._ingest_local_file(
            file_path=file_path,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            declared_mime_type=declared_mime_type,
            original_filename=original_filename,
            stored_object_key=stored_object_key,
        )
        if isinstance(ingested, ContractProcessingResult):
            return ingested

        self.repository.update_contract_status(ingested.contract_id, WorkflowState.QUEUED)
        processing_run_id = self._queue_processing_run(ingested)
        try:
            job = queue.enqueue(
                contract_id=ingested.contract_id,
                contract_version_id=ingested.contract_version_id,
                workspace_id=ingested.workspace_id,
                email_thread_id=ingested.email_thread_id,
                requested_by=ingested.requested_by,
                recipient_name=recipient_name,
                response_address=response_address,
                original_subject=original_subject,
                in_reply_to=in_reply_to,
                references=references,
                send_review_email=send_review_email,
                processing_run_id=processing_run_id,
            )
        except Exception as exc:
            self._metric_failed(processing_run_id, stage="queue", error=str(exc))
            self.repository.update_contract_status(ingested.contract_id, WorkflowState.ANALYSIS_FAILED)
            self.audit.record(
                workspace_id=ingested.workspace_id,
                contract_id=ingested.contract_id,
                event_type="contract.queue_failed",
                metadata={"error": str(exc)},
            )
            raise

        self.audit.record(
            workspace_id=ingested.workspace_id,
            contract_id=ingested.contract_id,
            event_type="contract.queued",
            metadata={"job_id": job.job_id},
        )
        if processing_run_id:
            self._metric_call("job_enqueued", run_id=processing_run_id, job_id=job.job_id)
        return ContractProcessingResult(
            contract_id=ingested.contract_id,
            contract_version_id=ingested.contract_version_id,
            status=WorkflowState.QUEUED,
            review=None,
            message="Contract review has been queued.",
            processing_run_id=processing_run_id,
        )

    def review_stored_contract(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        processing_run_id: str | None = None,
    ) -> ContractProcessingResult:
        row = self.repository.get_contract_version(
            contract_id=contract_id,
            contract_version_id=contract_version_id,
        )
        if row is None or str(row["workspace_id"]) != workspace_id:
            raise ValueError("Queued contract version was not found in the expected workspace.")

        # A broker retry after review persistence must only retry the delivery
        # outbox write. Re-running OCR and the model would be slow and can
        # produce a second review for the same contract version.
        existing_review = self.repository.get_contract_review(
            contract_id,
            contract_version_id=contract_version_id,
        )
        if existing_review is not None:
            self._metric_worker_started(processing_run_id)
            self._metric_completed(processing_run_id, outcome=WorkflowState.REVIEW_READY.value)
            return ContractProcessingResult(
                contract_id=contract_id,
                contract_version_id=contract_version_id,
                status=WorkflowState.REVIEW_READY,
                review=existing_review,
                message="Contract review is already ready.",
                processing_run_id=processing_run_id,
            )

        suffix = Path(str(row["original_filename"])).suffix
        with NamedTemporaryFile(prefix="samvid-worker-", suffix=suffix, delete=False) as tmp:
            file_path = Path(tmp.name)
        try:
            self._metric_worker_started(processing_run_id)
            self._metric_start(processing_run_id, "document_download")
            self.storage.download_contract_file(str(row["s3_object_key"]), file_path)
            self._metric_finish(processing_run_id, "document_download")
            validation = validate_uploaded_file(
                file_path,
                declared_mime_type=str(row["mime_type"]),
                max_size_mb=self.settings.max_file_size_mb,
            )
            if not validation.ok or validation.sha256 != str(row["sha256"]):
                raise ValueError("Stored contract failed integrity validation before review.")
            ingested = IngestedContract(
                contract_id=contract_id,
                contract_version_id=contract_version_id,
                workspace_id=workspace_id,
                email_thread_id=str(row["email_thread_id"]),
                requested_by=str(row["created_by"]),
                original_filename=str(row["original_filename"]),
                mime_type=str(row["mime_type"]),
                sha256=str(row["sha256"]),
                object_key=str(row["s3_object_key"]),
            )
            result = self._review_ingested_file(
                ingested=ingested,
                file_path=file_path,
                processing_run_id=processing_run_id,
            )
            if result.status is not WorkflowState.PARSE_FAILED:
                self._metric_completed(processing_run_id, outcome=result.status.value)
            return result.model_copy(update={"processing_run_id": processing_run_id})
        except Exception as exc:
            self._metric_attempt_failed(processing_run_id, stage="review", error=str(exc))
            raise
        finally:
            file_path.unlink(missing_ok=True)

    def mark_analysis_failed(
        self,
        *,
        contract_id: str,
        workspace_id: str,
        error: str,
        processing_run_id: str | None = None,
    ) -> None:
        if processing_run_id:
            self._metric_failed(processing_run_id, stage="review", error=error)
        else:
            self._metric_terminal_failed_for_contract(
                workspace_id=workspace_id,
                contract_id=contract_id,
                stage="review",
                error=error,
            )
        self.repository.update_contract_status(contract_id, WorkflowState.ANALYSIS_FAILED)
        self.audit.record(
            workspace_id=workspace_id,
            contract_id=contract_id,
            event_type="contract.analysis_failed",
            metadata={"error": error},
        )

    def close(self) -> None:
        self.repository.connection.close()

    def _ingest_local_file(
        self,
        *,
        file_path: Path,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        declared_mime_type: str | None,
        original_filename: str | None,
        stored_object_key: str | None,
    ) -> IngestedContract | ContractProcessingResult:
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
        stored = (
            StoredDocument(object_key=stored_object_key, file_path=file_path)
            if stored_object_key
            else self.storage.store_contract_file(
                file_path,
                workspace_id=workspace_id,
                sha256=validation.sha256,
            )
        )
        display_filename = original_filename or file_path.name
        contract_id, version_id = self.repository.create_contract_with_version(
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            title=display_filename,
            original_filename=display_filename,
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
            metadata={"filename": display_filename, "size_bytes": validation.size_bytes},
        )

        return IngestedContract(
            contract_id=contract_id,
            contract_version_id=version_id,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            original_filename=display_filename,
            mime_type=validation.mime_type,
            sha256=validation.sha256,
            object_key=stored.object_key,
        )

    def _review_ingested_file(
        self,
        *,
        ingested: IngestedContract,
        file_path: Path,
        processing_run_id: str | None = None,
    ) -> ContractProcessingResult:
        contract_id = ingested.contract_id
        version_id = ingested.contract_version_id
        self.repository.update_contract_status(contract_id, WorkflowState.PARSING)
        self._metric_start(processing_run_id, "parsing")
        parsed = self.parser.parse(
            file_path,
            document_id=contract_id,
            sha256=ingested.sha256,
            mime_type=ingested.mime_type,
        )
        self._metric_finish(processing_run_id, "parsing")
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
                workspace_id=ingested.workspace_id,
                contract_id=contract_id,
                event_type="contract.ocr_started",
                metadata={"provider": self.settings.ocr_provider},
            )
            try:
                self._metric_start(processing_run_id, "ocr")
                parsed = self.ocr_backend.extract(file_path, parsed_document=parsed)
            except OCRProcessingError as exc:
                self._metric_failed(processing_run_id, stage="ocr", error=str(exc))
                self.repository.update_contract_status(contract_id, WorkflowState.PARSE_FAILED)
                self.audit.record(
                    workspace_id=ingested.workspace_id,
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
            self._metric_finish(processing_run_id, "ocr")
            self.repository.save_parsed_document(contract_version_id=version_id, parsed_document=parsed)
            self.audit.record(
                workspace_id=ingested.workspace_id,
                contract_id=contract_id,
                event_type="contract.ocr_completed",
                metadata={"provider": self.settings.ocr_provider, "page_count": parsed.page_count},
            )

        self.repository.update_contract_status(contract_id, WorkflowState.ANALYSING)
        self._metric_start(processing_run_id, "review")
        validation_result = self.review_service.create_validated_review(
            contract_id=contract_id,
            parsed_document=parsed,
        )
        self._metric_finish(processing_run_id, "review")
        self._metric_start(processing_run_id, "review_persist")
        self.repository.finalize_contract_review(
            workspace_id=ingested.workspace_id,
            contract_id=contract_id,
            contract_version_id=version_id,
            review=validation_result.valid_review,
            agent=self.review_service.agent,
            review_status="valid" if not validation_result.issues else "valid_with_removed_findings",
            removed_findings=len(validation_result.issues),
        )
        self._metric_finish(processing_run_id, "review_persist")
        return ContractProcessingResult(
            contract_id=contract_id,
            contract_version_id=version_id,
            status=WorkflowState.REVIEW_READY,
            review=validation_result.valid_review,
            message="Contract review is ready.",
            processing_run_id=processing_run_id,
        )

    def _queue_processing_run(self, ingested: IngestedContract) -> str | None:
        try:
            return self.metrics.queue_run(
                workspace_id=ingested.workspace_id,
                contract_id=ingested.contract_id,
                contract_version_id=ingested.contract_version_id,
                source="inbound_email" if not ingested.email_thread_id.startswith("samvid-upload-") else "browser_upload",
            ).id
        except Exception:
            logger.exception("Could not create processing metrics for contract %s", ingested.contract_id)
            return None

    def _metric_worker_started(self, run_id: str | None) -> None:
        if run_id:
            self._metric_call("worker_started", run_id=run_id)

    def _metric_start(self, run_id: str | None, stage: str) -> None:
        if run_id:
            self._metric_call("stage_started", run_id=run_id, stage=stage)

    def _metric_finish(self, run_id: str | None, stage: str) -> None:
        if run_id:
            self._metric_call("stage_finished", run_id=run_id, stage=stage)

    def _metric_completed(self, run_id: str | None, *, outcome: str) -> None:
        if run_id:
            self._metric_call("completed", run_id=run_id, outcome=outcome)

    def _metric_failed(self, run_id: str | None, *, stage: str, error: str) -> None:
        if run_id:
            self._metric_call("failed", run_id=run_id, stage=stage, error=error)

    def _metric_attempt_failed(self, run_id: str | None, *, stage: str, error: str) -> None:
        if run_id:
            self._metric_call("stage_failed", run_id=run_id, stage=stage, error=error)
            self._metric_call("attempt_failed", run_id=run_id, stage=stage, error=error)

    def _metric_terminal_failed_for_contract(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        stage: str,
        error: str,
    ) -> None:
        self._metric_call(
            "terminal_failed_for_contract",
            workspace_id=workspace_id,
            contract_id=contract_id,
            stage=stage,
            error=error,
        )

    def _metric_call(self, method: str, **kwargs: object) -> None:
        try:
            getattr(self.metrics, method)(**kwargs)
        except Exception:
            logger.exception("Could not persist contract-processing metric %s", method)


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
        max_concurrency=settings.sarvam_ocr_max_concurrency,
    )
