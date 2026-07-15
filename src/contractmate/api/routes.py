import json
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from contractmate.db.repositories.contracts import ContractRepository
from contractmate.db.repositories.signing import SigningConflict, SigningError, SigningNotFound, SigningRepository
from contractmate.db.session import connect
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.signing import SignerCreate, SignerStatusEventCreate, SigningRequestCreate, SigningRequestStatus
from contractmate.services.audit_service import AuditService
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.services.review_service import ReviewService
from contractmate.settings import Settings
from contractmate.tools.document_storage import LocalDocumentStorage
from contractmate.parsers.pdfmuse_parser import PdfMuseDocumentParser
from contractmate.services.contract_processing import _ocr_backend_from_settings


def create_api_router(settings: Settings):
    try:
        from fastapi import APIRouter, File, HTTPException, Query, UploadFile
        from fastapi.responses import FileResponse
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'api' extra to run the HTTP app: uv sync --extra api") from exc

    router = APIRouter(prefix="/api")
    connection: Any | None = None

    def db() -> Any:
        nonlocal connection
        if connection is None:
            connection = connect(settings.database_url)
        return connection

    def contract_repository() -> ContractRepository:
        return ContractRepository(db())

    def signing_repository() -> SigningRepository:
        return SigningRepository(db())

    def actor_email() -> str:
        return settings.samvid_local_actor_email

    def actor_name() -> str:
        return settings.samvid_local_actor_name

    def workspace_id() -> str:
        return settings.email_workspace_id

    @router.get("/contracts")
    def list_contracts(
        search: str | None = Query(default=None),
        review_status: str | None = Query(default=None),
        signing_status: SigningRequestStatus | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        connection = db()
        signing = signing_repository()
        rows = _list_contract_rows(connection, workspace_id=workspace_id(), search=search, review_status=review_status)
        summaries = signing.signing_summary_for_contracts(workspace_id=workspace_id(), contract_ids=[row["id"] for row in rows])
        response = [_contract_list_item(row, summaries.get(row["id"])) for row in rows]
        if signing_status is not None:
            response = [item for item in response if item["signing_summary"]["status"] == signing_status.value]
        return response

    @router.post("/contracts")
    async def upload_contract(file: UploadFile = File(...)) -> dict[str, Any]:
        suffix = Path(file.filename or "contract").suffix
        with NamedTemporaryFile(prefix="samvid-upload-", suffix=suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)
            shutil.copyfileobj(file.file, tmp)
        try:
            connection = db()
            service = ContractProcessingService(
                settings=settings,
                repository=contract_repository(),
                audit=AuditService(connection),
                storage=LocalDocumentStorage(settings.local_storage_dir),
                parser=PdfMuseDocumentParser(),
                ocr_backend=_ocr_backend_from_settings(settings),
                review_service=ReviewService.from_settings(settings),
            )
            result = service.review_local_file(
                file_path=temp_path,
                workspace_id=workspace_id(),
                email_thread_id=f"samvid-upload-{uuid4()}",
                requested_by=actor_email(),
                declared_mime_type=file.content_type,
            )
            return result.model_dump(mode="json")
        finally:
            temp_path.unlink(missing_ok=True)

    @router.get("/contracts/{contract_id}")
    def get_contract(contract_id: str) -> dict[str, Any]:
        connection = db()
        signing = signing_repository()
        row = _get_contract_row(connection, workspace_id=workspace_id(), contract_id=contract_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Contract not found."})
        review = _review_from_row(row)
        requests = signing.list_contract_requests(workspace_id=workspace_id(), contract_id=contract_id)
        summary = signing.signing_summary_for_contracts(workspace_id=workspace_id(), contract_ids=[contract_id]).get(contract_id)
        return {
            **_contract_list_item(row, summary),
            "current_version": {
                "id": row["version_id"],
                "original_filename": row["original_filename"],
                "mime_type": row["mime_type"],
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
                "created_at": row["version_created_at"],
            }
            if row["version_id"]
            else None,
            "review": review.model_dump(mode="json") if review else None,
            "signing_requests": [request.model_dump(mode="json") for request in requests],
        }

    @router.get("/contracts/{contract_id}/document")
    def get_document(contract_id: str):
        connection = db()
        row = _get_contract_row(connection, workspace_id=workspace_id(), contract_id=contract_id)
        if row is None or not row["s3_object_key"]:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."})
        root = settings.local_storage_dir.resolve()
        file_path = (root / row["s3_object_key"]).resolve()
        if root not in file_path.parents and file_path != root:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."})
        if not file_path.exists():
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."})
        disposition = "inline" if row["mime_type"] == "application/pdf" else "attachment"
        return FileResponse(
            file_path,
            media_type=row["mime_type"],
            filename=row["original_filename"],
            content_disposition_type=disposition,
        )

    @router.post("/contracts/{contract_id}/signing-requests")
    def create_signing_request(contract_id: str, payload: SigningRequestCreate) -> dict[str, Any]:
        try:
            signing = signing_repository()
            request = signing.create_request(
                workspace_id=workspace_id(),
                contract_id=contract_id,
                payload=payload,
                actor_email=actor_email(),
                actor_name=actor_name(),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    @router.get("/contracts/{contract_id}/signing-requests")
    def list_contract_signing_requests(contract_id: str) -> list[dict[str, Any]]:
        try:
            signing = signing_repository()
            requests = signing.list_contract_requests(workspace_id=workspace_id(), contract_id=contract_id)
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return [request.model_dump(mode="json") for request in requests]

    @router.get("/signing-requests")
    def list_signing_requests(status: SigningRequestStatus | None = Query(default=None)) -> list[dict[str, Any]]:
        signing = signing_repository()
        requests = signing.list_requests(workspace_id=workspace_id(), status=status)
        return [request.model_dump(mode="json") for request in requests]

    @router.post("/signing-requests/{request_id}/signers")
    def add_signer(request_id: str, payload: SignerCreate) -> dict[str, Any]:
        try:
            signing = signing_repository()
            request = signing.add_signer(
                workspace_id=workspace_id(),
                request_id=request_id,
                signer=payload,
                actor_email=actor_email(),
                actor_name=actor_name(),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    @router.post("/signers/{signer_id}/events")
    def append_signer_event(signer_id: str, payload: SignerStatusEventCreate) -> dict[str, Any]:
        try:
            signing = signing_repository()
            request = signing.append_event(
                workspace_id=workspace_id(),
                signer_id=signer_id,
                payload=payload,
                actor_email=actor_email(),
                actor_name=actor_name(),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    return router


def _list_contract_rows(connection: Any, *, workspace_id: str, search: str | None, review_status: str | None) -> list[Any]:
    is_postgres = connection.__class__.__module__.startswith("psycopg")
    clauses = ["c.workspace_id = ?"]
    params: list[Any] = [workspace_id]
    if search:
        clauses.append("(LOWER(c.title) LIKE ? OR LOWER(cv.original_filename) LIKE ?)")
        params.extend([f"%{search.casefold()}%", f"%{search.casefold()}%"])
    if review_status:
        clauses.append("c.status = ?")
        params.append(review_status)
    sql = f"""
        SELECT
            c.id,
            c.workspace_id,
            c.title,
            c.status,
            c.current_version_id,
            c.created_by,
            c.created_at,
            c.updated_at,
            cv.id AS version_id,
            cv.original_filename,
            cv.mime_type,
            cv.size_bytes,
            cv.sha256,
            cv.s3_object_key,
            cv.created_at AS version_created_at,
            cr.review_json,
            cr.status AS review_record_status
        FROM contracts c
        LEFT JOIN contract_versions cv ON cv.id = c.current_version_id
        LEFT JOIN contract_reviews cr ON cr.contract_version_id = cv.id
        WHERE {" AND ".join(clauses)}
        ORDER BY c.updated_at DESC, c.created_at DESC
    """
    if is_postgres:
        sql = sql.replace("?", "%s")
    return connection.execute(sql, tuple(params)).fetchall()


def _get_contract_row(connection: Any, *, workspace_id: str, contract_id: str) -> Any | None:
    is_postgres = connection.__class__.__module__.startswith("psycopg")
    sql = """
        SELECT
            c.id,
            c.workspace_id,
            c.title,
            c.status,
            c.current_version_id,
            c.created_by,
            c.created_at,
            c.updated_at,
            cv.id AS version_id,
            cv.original_filename,
            cv.mime_type,
            cv.size_bytes,
            cv.sha256,
            cv.s3_object_key,
            cv.created_at AS version_created_at,
            cr.review_json,
            cr.status AS review_record_status
        FROM contracts c
        LEFT JOIN contract_versions cv ON cv.id = c.current_version_id
        LEFT JOIN contract_reviews cr ON cr.contract_version_id = cv.id
        WHERE c.workspace_id = ? AND c.id = ?
        LIMIT 1
    """
    if is_postgres:
        sql = sql.replace("?", "%s")
    return connection.execute(sql, (workspace_id, contract_id)).fetchone()


def _contract_list_item(row: Any, signing_summary: dict[str, Any] | None) -> dict[str, Any]:
    review = _review_from_row(row)
    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    if review is not None:
        for risk in review.risks:
            risk_counts[risk.severity.value] += 1
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "title": row["title"] or row["original_filename"] or "Untitled contract",
        "review_status": row["status"],
        "created_by": row["created_by"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "current_version_id": row["current_version_id"],
        "original_filename": row["original_filename"],
        "mime_type": row["mime_type"],
        "risk_counts": risk_counts,
        "signing_summary": signing_summary
        or {
            "active_request_id": None,
            "status": None,
            "required_signed": 0,
            "required_total": 0,
            "signer_total": 0,
        },
    }


def _review_from_row(row: Any) -> ContractReview | None:
    review_json = row["review_json"]
    if not review_json:
        return None
    if isinstance(review_json, str):
        return ContractReview.model_validate_json(review_json)
    return ContractReview.model_validate(review_json)


def _http_signing_error(exc: SigningError):
    from fastapi import HTTPException

    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
