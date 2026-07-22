import json
import logging
from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, BinaryIO
from urllib.parse import quote
from uuid import uuid4

from contractmate.db.repositories.contracts import (
    ContractDeletionConflict,
    ContractDeletionNotFound,
    ContractRepository,
)
from contractmate.db.repositories.chat import ChatMessage as PersistedChatMessage
from contractmate.db.repositories.chat import ChatRepository, ChatSession
from contractmate.db.repositories.knowledge import KnowledgeRepository
from contractmate.db.repositories.processing_runs import ProcessingRunRepository
from contractmate.db.repositories.signing import SigningConflict, SigningError, SigningNotFound, SigningRepository
from contractmate.db.repositories.user_accounts import UserAccountRepository
from contractmate.db.session import connect
from contractmate.schemas.contracts import BlobUploadAuthorization, ContractBlobUpload, ContractReview
from contractmate.schemas.chat import ChatMessageCreate, ChatSessionCreate
from contractmate.schemas.signing import SignerCreate, SignerStatusEventCreate, SigningRequestCreate, SigningRequestStatus
from contractmate.services.audit_service import AuditService
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.services.review_service import ReviewService
from contractmate.services.rate_limiting import UpstashRateLimiter, default_rate_limit_policy
from contractmate.services.account_access import AccountAccessError, AccountAccessService, VerifiedAccountResolution
from contractmate.services.chat_agent import AgnoChatAgentService, ChatEvidenceSource, OpenAIChatConfig
from contractmate.services.chat_runtime import DatabaseContractReader, chat_retriever_from_settings
from contractmate.settings import Settings
from contractmate.tools.document_storage import document_storage_from_settings
from contractmate.parsers.pdfmuse_parser import PdfMuseDocumentParser
from contractmate.services.contract_processing import _ocr_backend_from_settings
from contractmate.workers.queue import RabbitMQContractQueue
from contractmate.workflows.states import WorkflowState
from vercel.blob.errors import BlobError, BlobNotFoundError


logger = logging.getLogger(__name__)


def create_api_router(settings: Settings):
    try:
        from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
        from fastapi.responses import JSONResponse, Response, StreamingResponse
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'api' extra to run the HTTP app: uv sync --extra api") from exc

    router = APIRouter(prefix="/api")
    if settings.contract_processing_mode not in {"sync", "rabbitmq"}:
        raise ValueError("CONTRACT_PROCESSING_MODE must be 'sync' or 'rabbitmq'.")
    review_queue = (
        RabbitMQContractQueue.from_settings(settings)
        if settings.contract_processing_mode == "rabbitmq"
        else None
    )
    rate_limiter = UpstashRateLimiter(settings)

    def db_connection() -> Iterator[Any]:
        connection = connect(settings.database_url)
        try:
            yield connection
        finally:
            connection.close()

    def actor_email(request: Request) -> str:
        principal = getattr(request.state, "auth_principal", None)
        return principal.email if principal is not None else settings.samvid_local_actor_email

    def actor_name(request: Request) -> str:
        principal = getattr(request.state, "auth_principal", None)
        return principal.name if principal is not None else settings.samvid_local_actor_name

    def account_access(
        request: Request,
        connection: Any = Depends(db_connection),
    ) -> VerifiedAccountResolution:
        principal = getattr(request.state, "auth_principal", None)
        if principal is None:
            return VerifiedAccountResolution(
                account_id="local-user",
                email=settings.samvid_local_actor_email,
                role="user",
                state="active",
                workspace_id=settings.email_workspace_id,
            )
        if not settings.samvid_super_admin_email:
            raise HTTPException(status_code=503, detail={"code": "account_config_missing", "message": "Samvid account access is not configured."})
        try:
            return AccountAccessService(
                repository=UserAccountRepository(connection),
                super_admin_email=settings.samvid_super_admin_email,
            ).resolve_verified_principal(principal)
        except AccountAccessError as exc:
            raise HTTPException(status_code=403, detail={"code": "account_access_denied", "message": str(exc)}) from exc

    def personal_workspace(access: VerifiedAccountResolution = Depends(account_access)) -> str:
        if access.role != "user" or not access.workspace_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "read_only_super_admin", "message": "Super admins use the read-only admin console."},
            )
        return access.workspace_id

    def read_workspace(
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
    ) -> str:
        require_admission(operation="read", account_id=access.account_id, response=response)
        return personal_workspace(access)

    def super_admin(access: VerifiedAccountResolution = Depends(account_access)) -> VerifiedAccountResolution:
        if access.role != "super_admin":
            raise HTTPException(status_code=403, detail={"code": "super_admin_required", "message": "Super-admin access is required."})
        return access

    def rate_limit_headers(decision) -> dict[str, str]:
        remaining_values = [
            value
            for value in (decision.minute_remaining, decision.hourly_remaining, decision.daily_remaining)
            if value is not None
        ]
        remaining = min(remaining_values) if remaining_values else None
        headers: dict[str, str] = {}
        if remaining is not None:
            headers["RateLimit-Remaining"] = str(remaining)
        if decision.retry_after_seconds:
            headers["Retry-After"] = str(decision.retry_after_seconds)
            headers["RateLimit-Reset"] = str(decision.retry_after_seconds)
        return headers

    def require_admission(
        *,
        operation: str,
        account_id: str,
        response: Response | None = None,
    ) -> dict[str, str]:
        decision = rate_limiter.consume(default_rate_limit_policy(operation), account_id)
        headers = rate_limit_headers(decision)
        if decision.reason == "unavailable" and not decision.allowed:
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limit_unavailable", "message": "Request admission is temporarily unavailable."},
                headers=headers,
            )
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limit_exceeded",
                    "message": "This operation has reached its current limit.",
                    "retry_after_seconds": decision.retry_after_seconds,
                },
                headers=headers,
            )
        if response is not None:
            response.headers.update(headers)
        return headers

    def chat_session_response(
        session: ChatSession,
        *,
        repository: ChatRepository,
        include_messages: bool = False,
    ) -> dict[str, Any]:
        messages = repository.list_messages(workspace_id=session.workspace_id, session_id=session.id)
        response: dict[str, Any] = {
            "id": session.id,
            "title": session.title or "New conversation",
            "message_count": len(messages),
            "created_at": str(session.created_at),
            "updated_at": str(session.updated_at),
        }
        if include_messages:
            response["messages"] = [chat_message_response(message) for message in messages if message.role != "system"]
        return response

    def chat_message_response(message: PersistedChatMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "sources": message.citations,
            "created_at": str(message.created_at),
        }

    def chat_source_cards(
        *,
        connection: Any,
        workspace_id: str,
        evidence_sources: tuple[ChatEvidenceSource, ...],
    ) -> list[dict[str, Any]]:
        titles: dict[str, str] = {}
        sources: list[dict[str, Any]] = []
        for source in evidence_sources:
            contract_id = source.contract_id
            if contract_id not in titles:
                contract = _get_contract_row(connection, workspace_id=workspace_id, contract_id=contract_id)
                metadata_title = source.metadata.get("contract_title") or source.metadata.get("title")
                titles[contract_id] = (
                    str(contract["title"] or contract["original_filename"] or "Untitled contract")
                    if contract
                    else str(metadata_title or "Contract")
                )
            sources.append(
                {
                    "id": source.source_id,
                    "chunk_id": source.chunk_id,
                    "contract_id": contract_id,
                    "contract_version_id": source.contract_version_id,
                    "contract_title": titles[contract_id],
                    "page_number": source.page_number,
                    "source_type": source.source_type,
                    "excerpt": source.excerpt[:600],
                    "relevance": source.relevance,
                }
            )
        return sources

    @router.get("/auth/me")
    def authenticated_user(
        request: Request,
        access: VerifiedAccountResolution = Depends(account_access),
    ) -> dict[str, Any]:
        principal = getattr(request.state, "auth_principal", None)
        if principal is None:
            return {
                "user": {
                    "subject": "local-user",
                    "email": settings.samvid_local_actor_email,
                    "name": settings.samvid_local_actor_name,
                    "email_verified": True,
                },
                "account": {
                    "id": access.account_id,
                    "role": access.role,
                    "state": access.state,
                    "workspace_id": access.workspace_id,
                },
            }
        return {
            "user": {
                "subject": principal.subject,
                "email": principal.email,
                "name": principal.name,
                "email_verified": principal.email_verified,
            },
            "account": {
                "id": access.account_id,
                "role": access.role,
                "state": access.state,
                "workspace_id": access.workspace_id,
            },
        }

    @router.get("/chats")
    def list_chats(
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> list[dict[str, Any]]:
        repository = ChatRepository(connection)
        sessions = repository.list_sessions(workspace_id=workspace, account_id=access.account_id)
        return [chat_session_response(session, repository=repository) for session in sessions]

    @router.post("/chats")
    def create_chat(
        payload: ChatSessionCreate,
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        require_admission(operation="mutation", account_id=access.account_id, response=response)
        try:
            repository = ChatRepository(connection)
            session = repository.create_session(
                workspace_id=workspace,
                account_id=access.account_id,
                title=payload.title,
                contract_id=payload.contract_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Contract not found."}) from exc
        return chat_session_response(session, repository=repository)

    @router.get("/chats/{session_id}")
    def get_chat(
        session_id: str,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        repository = ChatRepository(connection)
        session = repository.get_session(workspace_id=workspace, session_id=session_id)
        if session is None or session.account_id != access.account_id:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Conversation not found."})
        return chat_session_response(session, repository=repository, include_messages=True)

    @router.post("/chats/{session_id}/messages")
    def send_chat_message(
        session_id: str,
        payload: ChatMessageCreate,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ):
        admission_headers = require_admission(operation="chat", account_id=access.account_id)
        content = payload.content.strip()
        if len(content) > settings.chat_max_input_chars:
            raise HTTPException(
                status_code=422,
                detail={"code": "message_too_large", "message": f"Messages are limited to {settings.chat_max_input_chars} characters."},
            )
        chats = ChatRepository(connection)
        session = chats.get_session(workspace_id=workspace, session_id=session_id)
        if session is None or session.account_id != access.account_id:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Conversation not found."})

        # Persist the user message before invoking external models so retries never
        # lose user input. The assistant reply is committed only after completion.
        chats.append_message(workspace_id=workspace, session_id=session_id, role="user", content=content)
        try:
            retriever = chat_retriever_from_settings(
                settings=settings,
                repository=KnowledgeRepository(connection),
            )
            agent = AgnoChatAgentService(
                config=OpenAIChatConfig(api_key=settings.model_api_key or "", model_id=settings.chat_model_id),
                retriever=retriever,
                reader=DatabaseContractReader(connection),
            )
            history = [
                {"role": message.role, "content": message.content}
                for message in chats.list_messages(workspace_id=workspace, session_id=session_id)[-13:-1]
                if message.role in {"user", "assistant"}
            ]
            answer = agent.answer(
                workspace_id=workspace,
                user_id=access.account_id,
                session_id=session_id,
                message=content,
                history=history,
            )
            sources = chat_source_cards(
                connection=connection,
                workspace_id=workspace,
                evidence_sources=answer.sources,
            )
            assistant_message = chats.append_message(
                workspace_id=workspace,
                session_id=session_id,
                role="assistant",
                content=answer.content,
                citations=sources,
                model_provider="openai",
                model_name=settings.chat_model_id,
                metadata={"citation_labels": list(answer.citations), "retrieval_count": len(sources)},
            )
        except Exception as exc:
            logger.exception("Contract chat failed for session %s", session_id)
            raise HTTPException(
                status_code=502,
                detail={"code": "chat_generation_failed", "message": "Samvid could not complete that contract answer."},
            ) from exc

        def event_stream() -> Iterator[str]:
            if sources:
                yield _sse_event("message.sources", {"type": "message.sources", "sources": sources})
            for fragment in _stream_fragments(answer.content):
                yield _sse_event("message.delta", {"type": "message.delta", "delta": fragment})
            yield _sse_event(
                "message.completed",
                {"type": "message.completed", "message": chat_message_response(assistant_message)},
            )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", **admission_headers},
        )

    @router.post("/uploads/authorize")
    def authorize_blob_upload(
        payload: BlobUploadAuthorization,
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
    ) -> dict[str, Any]:
        expected_prefix = f"contracts/{workspace}/"
        if not payload.pathname.startswith(expected_prefix):
            raise HTTPException(status_code=404, detail={"code": "blob_not_found", "message": "Upload path was not found."})
        decision = rate_limiter.reserve_upload(
            policy=default_rate_limit_policy("review"),
            identifier=access.account_id,
            pathname=payload.pathname,
        )
        headers = rate_limit_headers(decision)
        if decision.reason == "unavailable" and not decision.allowed:
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limit_unavailable", "message": "Upload admission is temporarily unavailable."},
                headers=headers,
            )
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limit_exceeded",
                    "message": "Contract review limit reached.",
                    "retry_after_seconds": decision.retry_after_seconds,
                },
                headers=headers,
            )
        response.headers.update(headers)
        return {"status": "authorized", "rate_limit": {"remaining": decision.hourly_remaining, "retry_after_seconds": decision.retry_after_seconds}}

    @router.get("/contracts")
    def list_contracts(
        search: str | None = Query(default=None),
        review_status: str | None = Query(default=None),
        signing_status: SigningRequestStatus | None = Query(default=None),
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> list[dict[str, Any]]:
        signing = SigningRepository(connection)
        rows = _list_contract_rows(connection, workspace_id=workspace, search=search, review_status=review_status)
        summaries = signing.signing_summary_for_contracts(workspace_id=workspace, contract_ids=[row["id"] for row in rows])
        response = [_contract_list_item(row, summaries.get(row["id"])) for row in rows]
        if signing_status is not None:
            response = [item for item in response if item["signing_summary"]["status"] == signing_status.value]
        return response

    @router.post("/contracts")
    def upload_contract(
        request: Request,
        response: Response,
        file: UploadFile = File(...),
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        admission_headers = require_admission(
            operation="review",
            account_id=access.account_id,
            response=response,
        )
        suffix = Path(file.filename or "contract").suffix
        with NamedTemporaryFile(prefix="samvid-upload-", suffix=suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)
            try:
                _copy_upload_with_limit(file.file, tmp, max_bytes=settings.max_file_size_mb * 1024 * 1024)
            except ValueError as exc:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail={"code": "file_too_large", "message": f"File exceeds {settings.max_file_size_mb} MB limit."},
                ) from exc
        try:
            service = ContractProcessingService(
                settings=settings,
                repository=ContractRepository(connection),
                audit=AuditService(connection),
                storage=document_storage_from_settings(settings),
                parser=PdfMuseDocumentParser(),
                ocr_backend=_ocr_backend_from_settings(settings),
                review_service=ReviewService.from_settings(settings),
            )
            arguments = {
                "file_path": temp_path,
                "workspace_id": workspace,
                "email_thread_id": f"samvid-upload-{uuid4()}",
                "requested_by": actor_email(request),
                "declared_mime_type": file.content_type,
            }
            result = (
                service.enqueue_local_file(queue=review_queue, **arguments)
                if review_queue is not None
                else service.review_local_file(**arguments)
            )
            if result.status is WorkflowState.QUEUED:
                return JSONResponse(status_code=202, content=result.model_dump(mode="json"), headers=admission_headers)
            return result.model_dump(mode="json")
        finally:
            temp_path.unlink(missing_ok=True)

    @router.post("/contracts/from-blob")
    def upload_contract_from_blob(
        request: Request,
        payload: ContractBlobUpload,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        if settings.document_storage_backend != "vercel_blob":
            raise HTTPException(
                status_code=409,
                detail={"code": "blob_storage_disabled", "message": "Direct Blob uploads are not enabled."},
            )

        expected_prefix = f"contracts/{workspace}/"
        if not payload.pathname.startswith(expected_prefix):
            raise HTTPException(
                status_code=404,
                detail={"code": "blob_not_found", "message": "Uploaded document was not found."},
            )

        lease = rate_limiter.acquire_upload_reservation(
            identifier=access.account_id,
            pathname=payload.pathname,
        )
        lease_headers = (
            {"Retry-After": str(lease.retry_after_seconds)}
            if lease.retry_after_seconds
            else {}
        )
        if lease.status == "unavailable" and not lease.allowed:
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limit_unavailable", "message": "Upload admission is temporarily unavailable."},
                headers=lease_headers,
            )
        if lease.status == "busy":
            raise HTTPException(
                status_code=409,
                detail={"code": "upload_processing", "message": "This upload is already being processed."},
                headers=lease_headers,
            )
        if lease.status == "consumed":
            raise HTTPException(
                status_code=409,
                detail={"code": "upload_already_processed", "message": "This upload has already been processed."},
            )
        if not lease.allowed:
            raise HTTPException(
                status_code=409,
                detail={"code": "upload_authorization_missing", "message": "The upload authorization has expired. Upload the contract again."},
            )

        storage = document_storage_from_settings(settings)
        lease_id = lease.lease_id
        durable_success = False
        temp_path: Path | None = None
        try:
            try:
                metadata = storage.stat_contract_file(payload.pathname)
            except (BlobError, FileNotFoundError) as exc:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "blob_not_found", "message": "Uploaded document was not found."},
                ) from exc
            if not metadata.object_key.startswith(expected_prefix):
                raise HTTPException(
                    status_code=404,
                    detail={"code": "blob_not_found", "message": "Uploaded document was not found."},
                )
            if metadata.size_bytes > settings.max_file_size_mb * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "file_too_large", "message": f"File exceeds {settings.max_file_size_mb} MB limit."},
                )

            suffix = Path(payload.original_filename).suffix
            with NamedTemporaryFile(prefix="samvid-blob-", suffix=suffix, delete=False) as tmp:
                temp_path = Path(tmp.name)
            storage.download_contract_file(metadata.object_key, temp_path)
            service = ContractProcessingService(
                settings=settings,
                repository=ContractRepository(connection),
                audit=AuditService(connection),
                storage=storage,
                parser=PdfMuseDocumentParser(),
                ocr_backend=_ocr_backend_from_settings(settings),
                review_service=ReviewService.from_settings(settings),
            )
            arguments = {
                "file_path": temp_path,
                "workspace_id": workspace,
                "email_thread_id": f"samvid-upload-{uuid4()}",
                "requested_by": actor_email(request),
                "declared_mime_type": metadata.content_type or payload.content_type,
                "original_filename": payload.original_filename,
                "stored_object_key": metadata.object_key,
            }
            result = (
                service.enqueue_local_file(queue=review_queue, **arguments)
                if review_queue is not None
                else service.review_local_file(**arguments)
            )
            if not result.contract_id:
                storage.delete_contract_file(metadata.object_key)
                if lease_id:
                    rate_limiter.release_upload_reservation(
                        identifier=access.account_id,
                        pathname=payload.pathname,
                        lease_id=lease_id,
                    )
                    lease_id = None
            else:
                durable_success = True
                if lease_id and not rate_limiter.mark_upload_reservation_consumed(
                    identifier=access.account_id,
                    pathname=payload.pathname,
                    lease_id=lease_id,
                ):
                    logger.error(
                        "upload_reservation_finalize_failed",
                        extra={
                            "event": "upload_reservation_finalize_failed",
                            "account_hash": rate_limiter.hash_identifier(access.account_id),
                            "pathname_hash": rate_limiter.hash_identifier(payload.pathname),
                        },
                    )
            if result.status is WorkflowState.QUEUED:
                return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
            return result.model_dump(mode="json")
        except Exception:
            if lease_id and not durable_success and not rate_limiter.release_upload_reservation(
                identifier=access.account_id,
                pathname=payload.pathname,
                lease_id=lease_id,
            ):
                logger.warning(
                    "upload_reservation_release_failed",
                    extra={
                        "event": "upload_reservation_release_failed",
                        "account_hash": rate_limiter.hash_identifier(access.account_id),
                        "pathname_hash": rate_limiter.hash_identifier(payload.pathname),
                    },
                )
            raise
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @router.get("/contracts/{contract_id}")
    def get_contract(
        contract_id: str,
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        signing = SigningRepository(connection)
        row = _get_contract_row(connection, workspace_id=workspace, contract_id=contract_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Contract not found."})
        review = _review_from_row(row)
        requests = signing.list_contract_requests(workspace_id=workspace, contract_id=contract_id)
        summary = signing.signing_summary_for_contracts(workspace_id=workspace, contract_ids=[contract_id]).get(contract_id)
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

    @router.delete("/contracts/{contract_id}", status_code=204)
    def delete_contract(
        request: Request,
        response: Response,
        contract_id: str,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> None:
        require_admission(operation="mutation", account_id=access.account_id, response=response)
        storage = document_storage_from_settings(settings)

        def delete_objects(object_keys) -> None:
            for object_key in object_keys:
                try:
                    storage.delete_contract_file(object_key)
                except (BlobNotFoundError, FileNotFoundError):
                    # Deletion is idempotent when a previous attempt removed the file
                    # but its database transaction did not commit.
                    continue

        try:
            ContractRepository(connection).delete_contract(
                workspace_id=workspace,
                contract_id=contract_id,
                deleted_by=actor_email(request),
                delete_objects=delete_objects,
            )
        except ContractDeletionNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "Contract not found."},
            ) from exc
        except ContractDeletionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "contract_processing", "message": str(exc)},
            ) from exc
        except BlobError as exc:
            logger.exception("Contract %s could not be removed from document storage", contract_id)
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "storage_delete_failed",
                    "message": "The document could not be deleted from storage. Try again.",
                },
            ) from exc

    @router.get("/contracts/{contract_id}/document")
    def get_document(
        contract_id: str,
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ):
        row = _get_contract_row(connection, workspace_id=workspace, contract_id=contract_id)
        if row is None or not row["s3_object_key"]:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."})
        try:
            content = document_storage_from_settings(settings).read_contract_file(row["s3_object_key"])
        except (BlobError, FileNotFoundError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "Document not found."},
            ) from exc
        disposition = "inline" if row["mime_type"] == "application/pdf" else "attachment"
        filename = str(row["original_filename"] or "contract")
        return Response(
            content=content,
            media_type=row["mime_type"],
            headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}"},
        )

    @router.post("/contracts/{contract_id}/signing-requests")
    def create_signing_request(
        request: Request,
        contract_id: str,
        payload: SigningRequestCreate,
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        require_admission(operation="mutation", account_id=access.account_id, response=response)
        try:
            signing = SigningRepository(connection)
            request = signing.create_request(
                workspace_id=workspace,
                contract_id=contract_id,
                payload=payload,
                actor_email=actor_email(request),
                actor_name=actor_name(request),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    @router.get("/contracts/{contract_id}/signing-requests")
    def list_contract_signing_requests(
        contract_id: str,
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> list[dict[str, Any]]:
        try:
            signing = SigningRepository(connection)
            requests = signing.list_contract_requests(workspace_id=workspace, contract_id=contract_id)
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return [request.model_dump(mode="json") for request in requests]

    @router.get("/signing-requests")
    def list_signing_requests(
        status: SigningRequestStatus | None = Query(default=None),
        workspace: str = Depends(read_workspace),
        connection: Any = Depends(db_connection),
    ) -> list[dict[str, Any]]:
        signing = SigningRepository(connection)
        requests = signing.list_requests(workspace_id=workspace, status=status)
        return [request.model_dump(mode="json") for request in requests]

    @router.post("/signing-requests/{request_id}/signers")
    def add_signer(
        request: Request,
        request_id: str,
        payload: SignerCreate,
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        require_admission(operation="mutation", account_id=access.account_id, response=response)
        try:
            signing = SigningRepository(connection)
            request = signing.add_signer(
                workspace_id=workspace,
                request_id=request_id,
                signer=payload,
                actor_email=actor_email(request),
                actor_name=actor_name(request),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    @router.post("/signers/{signer_id}/events")
    def append_signer_event(
        request: Request,
        signer_id: str,
        payload: SignerStatusEventCreate,
        response: Response,
        access: VerifiedAccountResolution = Depends(account_access),
        workspace: str = Depends(personal_workspace),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        require_admission(operation="mutation", account_id=access.account_id, response=response)
        try:
            signing = SigningRepository(connection)
            request = signing.append_event(
                workspace_id=workspace,
                signer_id=signer_id,
                payload=payload,
                actor_email=actor_email(request),
                actor_name=actor_name(request),
            )
        except SigningError as exc:
            raise _http_signing_error(exc) from exc
        return request.model_dump(mode="json")

    @router.get("/admin/users")
    def list_admin_users(
        search: str | None = Query(default=None),
        state: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        _admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        page_size = 50
        accounts, total = UserAccountRepository(connection).list_accounts(
            state=state,
            search=search,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": [_account_response(account) for account in accounts],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @router.get("/admin/users/{account_id}")
    def get_admin_user(
        account_id: str,
        admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        accounts = UserAccountRepository(connection)
        account = accounts.get_by_id(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Account not found."})
        accounts.record_access_event(
            actor_account_id=admin.account_id,
            target_account_id=account.id,
            workspace_id=account.personal_workspace_id,
            event_type="admin.user.viewed",
        )
        return _account_response(account, include_subject=True)

    @router.get("/admin/users/{account_id}/contracts")
    def list_admin_user_contracts(
        account_id: str,
        search: str | None = Query(default=None),
        review_status: str | None = Query(default=None),
        signing_status: SigningRequestStatus | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        accounts = UserAccountRepository(connection)
        account = accounts.get_by_id(account_id)
        if account is None or account.role != "user" or not account.personal_workspace_id:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User account not found."})
        signing = SigningRepository(connection)
        rows = _list_contract_rows(
            connection,
            workspace_id=account.personal_workspace_id,
            search=search,
            review_status=review_status,
        )
        summaries = signing.signing_summary_for_contracts(
            workspace_id=account.personal_workspace_id,
            contract_ids=[row["id"] for row in rows],
        )
        items = [_contract_list_item(row, summaries.get(row["id"])) for row in rows]
        if signing_status is not None:
            items = [item for item in items if item["signing_summary"]["status"] == signing_status.value]
        page_size = 50
        accounts.record_access_event(
            actor_account_id=admin.account_id,
            target_account_id=account.id,
            workspace_id=account.personal_workspace_id,
            event_type="admin.user_contracts.viewed",
        )
        return {
            "items": items[(page - 1) * page_size : page * page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
        }

    @router.get("/admin/contracts/{contract_id}")
    def get_admin_contract(
        contract_id: str,
        admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        row = _get_contract_row_any_workspace(connection, contract_id=contract_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Contract not found."})
        accounts = UserAccountRepository(connection)
        owner = accounts.get_by_workspace(str(row["workspace_id"]))
        signing = SigningRepository(connection)
        requests = signing.list_contract_requests(workspace_id=str(row["workspace_id"]), contract_id=contract_id)
        summary = signing.signing_summary_for_contracts(
            workspace_id=str(row["workspace_id"]),
            contract_ids=[contract_id],
        ).get(contract_id)
        accounts.record_access_event(
            actor_account_id=admin.account_id,
            target_account_id=owner.id if owner else None,
            workspace_id=str(row["workspace_id"]),
            contract_id=contract_id,
            event_type="admin.contract.viewed",
        )
        return _contract_detail_response(row, summary=summary, signing_requests=requests)

    @router.get("/admin/contracts/{contract_id}/document")
    def get_admin_document(
        contract_id: str,
        admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ):
        row = _get_contract_row_any_workspace(connection, contract_id=contract_id)
        if row is None or not row["s3_object_key"]:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."})
        accounts = UserAccountRepository(connection)
        owner = accounts.get_by_workspace(str(row["workspace_id"]))
        try:
            content = document_storage_from_settings(settings).read_contract_file(row["s3_object_key"])
        except (BlobError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Document not found."}) from exc
        accounts.record_access_event(
            actor_account_id=admin.account_id,
            target_account_id=owner.id if owner else None,
            workspace_id=str(row["workspace_id"]),
            contract_id=contract_id,
            event_type="admin.contract_document.viewed",
        )
        disposition = "inline" if row["mime_type"] == "application/pdf" else "attachment"
        filename = str(row["original_filename"] or "contract")
        return Response(
            content=content,
            media_type=row["mime_type"],
            headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}"},
        )

    @router.get("/admin/contracts/{contract_id}/signing")
    def get_admin_contract_signing(
        contract_id: str,
        admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> list[dict[str, Any]]:
        row = _get_contract_row_any_workspace(connection, contract_id=contract_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Contract not found."})
        accounts = UserAccountRepository(connection)
        owner = accounts.get_by_workspace(str(row["workspace_id"]))
        requests = SigningRepository(connection).list_contract_requests(
            workspace_id=str(row["workspace_id"]),
            contract_id=contract_id,
        )
        accounts.record_access_event(
            actor_account_id=admin.account_id,
            target_account_id=owner.id if owner else None,
            workspace_id=str(row["workspace_id"]),
            contract_id=contract_id,
            event_type="admin.contract_signing.viewed",
        )
        return [request.model_dump(mode="json") for request in requests]

    @router.get("/admin/access-events")
    def list_admin_access_events(
        search: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        _admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        page_size = 50
        events = UserAccountRepository(connection).list_access_events(
            search=search,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": [
                {
                    "id": event.id,
                    "actor_account_id": event.actor_account_id,
                    "actor_email": event.actor_email,
                    "target_user_id": event.target_account_id,
                    "target_user_email": event.target_user_email,
                    "workspace_id": event.workspace_id,
                    "contract_id": event.contract_id,
                    "contract_title": event.contract_title,
                    "event_type": event.event_type,
                    "metadata": event.metadata,
                    "created_at": str(event.created_at),
                }
                for event in events
            ],
            "total": len(events),
            "page": page,
            "page_size": page_size,
        }

    @router.get("/admin/operations/latency")
    def admin_processing_latency(
        sample_size: int = Query(default=500, ge=1, le=2000),
        _admin: VerifiedAccountResolution = Depends(super_admin),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        """Read-only recent processing latency and outcome telemetry."""
        runs = ProcessingRunRepository(connection).list_recent(limit=sample_size)
        completed_ms = [
            max(0, int((run.completed_at - run.queued_at).total_seconds() * 1000))
            for run in runs
            if run.queued_at is not None and run.completed_at is not None
        ]
        outcomes: dict[str, int] = {}
        for run in runs:
            outcomes[run.status] = outcomes.get(run.status, 0) + 1
        return {
            "sample_size": len(runs),
            "outcomes": outcomes,
            "end_to_end_ms": {
                "p50": _percentile(completed_ms, 50),
                "p95": _percentile(completed_ms, 95),
                "max": max(completed_ms) if completed_ms else None,
            },
        }

    return router


def _copy_upload_with_limit(source: BinaryIO, destination: BinaryIO, *, max_bytes: int) -> None:
    copied = 0
    while chunk := source.read(1024 * 1024):
        copied += len(chunk)
        if copied > max_bytes:
            raise ValueError("upload exceeds configured size limit")
        destination.write(chunk)


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


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


def _get_contract_row_any_workspace(connection: Any, *, contract_id: str) -> Any | None:
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
        WHERE c.id = ?
        LIMIT 1
    """
    if is_postgres:
        sql = sql.replace("?", "%s")
    return connection.execute(sql, (contract_id,)).fetchone()


def _contract_detail_response(
    row: Any,
    *,
    summary: dict[str, Any] | None,
    signing_requests: list[Any],
) -> dict[str, Any]:
    review = _review_from_row(row)
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
        "signing_requests": [request.model_dump(mode="json") for request in signing_requests],
    }


def _account_response(account: Any, *, include_subject: bool = False) -> dict[str, Any]:
    response = {
        "id": account.id,
        "email": account.email,
        "name": account.display_name or account.email.split("@", 1)[0],
        "role": account.role,
        "state": account.state,
        "source": account.source,
        "workspace_id": account.personal_workspace_id,
        "contract_count": account.contract_count,
        "claimed_at": str(account.claimed_at) if account.claimed_at else None,
        "created_at": str(account.created_at),
        "updated_at": str(account.updated_at),
    }
    if include_subject:
        response["auth_subject"] = account.auth_subject
    return response


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


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _stream_fragments(content: str, *, max_chars: int = 80) -> Iterator[str]:
    """Emit sentence-friendly chunks after the model response has been persisted."""
    remaining = content.strip()
    while remaining:
        if len(remaining) <= max_chars:
            yield remaining
            return
        split_at = max(remaining.rfind(" ", 0, max_chars), remaining.rfind("\n", 0, max_chars))
        if split_at < 1:
            split_at = max_chars
        else:
            split_at += 1
        yield remaining[:split_at]
        remaining = remaining[split_at:]
