import base64
import binascii
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from contractmate.api.routes import create_api_router
from contractmate.db.session import connect, initialize_database
from contractmate.email.resend_inbound import (
    MalformedResendWebhook,
    ResendInboundService,
    ResendWebhookEvent,
    parse_resend_webhook,
    recipient_is_allowed,
    verify_resend_webhook,
    webhook_payload_hash,
)
from contractmate.security.control_plane import authorize_control_plane_request
from contractmate.security.neon_auth import NeonAuthenticationError, NeonAuthorizationError, NeonJWTVerifier
from contractmate.settings import Settings
from contractmate.tools.document_storage import document_storage_from_settings
from contractmate.workers.queue import RabbitMQContractQueue

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None):
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.middleware.trustedhost import TrustedHostMiddleware
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.concurrency import run_in_threadpool
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'api' extra to run the HTTP app: uv sync --extra api") from exc

    settings = settings or Settings.from_env()
    settings.validate_runtime()
    neon_verifier = (
        NeonJWTVerifier(
            auth_url=settings.neon_auth_url or "",
            jwks_url=settings.neon_auth_jwks_url,
            issuer=settings.neon_auth_issuer,
            audience=settings.neon_auth_audience,
            allowed_emails=settings.neon_auth_allowed_emails,
            require_email_verified=settings.neon_auth_require_email_verified,
            clock_skew_seconds=settings.neon_auth_clock_skew_seconds,
        )
        if settings.auth_mode == "neon"
        else None
    )

    @asynccontextmanager
    async def lifespan(_app):
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)
        yield

    app = FastAPI(
        title="Samvid",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    if settings.app_env.casefold() in {"development", "dev", "local"}:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.frontend_origin, "http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def production_boundary(request: Request, call_next):
        public_paths = {"/health", "/ready", "/email/inbound", "/agentos/control-plane/status"}
        is_api_request = request.url.path == "/api" or request.url.path.startswith("/api/")
        if neon_verifier is not None and is_api_request:
            try:
                request.state.auth_principal = neon_verifier.verify_authorization_header(
                    request.headers.get("authorization")
                )
            except NeonAuthenticationError as exc:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": str(exc)},
                    headers={"WWW-Authenticate": "Bearer"},
                )
                return _with_security_headers(response, settings=settings, request_path=request.url.path)
            except NeonAuthorizationError as exc:
                response = JSONResponse(status_code=403, content={"detail": str(exc)})
                return _with_security_headers(response, settings=settings, request_path=request.url.path)
        elif settings.is_production and settings.auth_mode == "basic" and request.url.path not in public_paths:
            if not _basic_auth_is_valid(request.headers.get("authorization"), settings):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                    headers={"WWW-Authenticate": 'Basic realm="Samvid", charset="UTF-8"'},
                )
                return _with_security_headers(response, settings=settings, request_path=request.url.path)

        if (neon_verifier is not None and is_api_request) or (
            settings.is_production and settings.auth_mode == "basic" and request.url.path not in public_paths
        ):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                fetch_site = request.headers.get("sec-fetch-site")
                if fetch_site and fetch_site not in {"same-origin", "none"}:
                    response = JSONResponse(status_code=403, content={"detail": "Cross-site request rejected"})
                    return _with_security_headers(response, settings=settings, request_path=request.url.path)

        response = await call_next(request)
        return _with_security_headers(response, settings=settings, request_path=request.url.path)

    app.include_router(create_api_router(settings))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "samvid"}

    @app.get("/ready")
    def ready() -> dict:
        try:
            _check_runtime_dependencies(settings)
        except Exception as exc:
            logger.exception("Samvid readiness check failed")
            raise HTTPException(status_code=503, detail="Service dependencies are not ready") from exc
        return {"status": "ready", "service": "samvid"}

    @app.get("/agentos/control-plane/status")
    def control_plane_status(
        x_os_security_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        principal = authorize_control_plane_request(
            settings=settings,
            os_security_key_header=x_os_security_key,
            authorization_header=authorization,
            required_scope="runtime:read",
        )
        if principal is None:
            raise HTTPException(status_code=401, detail="Control Plane authentication required")
        return {
            "id": "contractmate-os",
            "service": "samvid",
            "env": settings.app_env,
            "tracing": settings.enable_tracing,
            "authorization_required": settings.is_production,
            "principal": {
                "subject": principal.subject,
                "auth_method": principal.auth_method,
                "scopes": sorted(principal.scopes),
            },
            "rabbitmq": {
                "enabled": settings.contract_processing_mode == "rabbitmq",
                "exchange": settings.rabbitmq_exchange,
                "review_queue": settings.rabbitmq_review_queue,
                "retry_queue": settings.rabbitmq_retry_queue,
                "dlq": settings.rabbitmq_dlq,
                "retry_ttl_ms": settings.rabbitmq_retry_ttl_ms,
                "max_attempts": settings.rabbitmq_max_attempts,
                "heartbeat_seconds": settings.rabbitmq_heartbeat_seconds,
            },
        }

    @app.post("/email/inbound")
    async def inbound_email(request: Request) -> dict:
        if not settings.resend_inbound_enabled:
            raise HTTPException(status_code=503, detail="Inbound email receiving is disabled")

        raw_payload = await request.body()
        try:
            verify_resend_webhook(
                raw_payload,
                event_id=request.headers.get("svix-id"),
                timestamp=request.headers.get("svix-timestamp"),
                signature=request.headers.get("svix-signature"),
                webhook_secret=settings.resend_webhook_secret or "",
            )
        except MalformedResendWebhook as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid Resend webhook signature") from exc

        try:
            event = parse_resend_webhook(raw_payload)
        except MalformedResendWebhook as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        event_id = request.headers.get("svix-id") or ""
        if event.type != "email.received":
            return {"event_id": event_id, "status": "ignored", "reason": "unsupported_event"}
        if not isinstance(event, ResendWebhookEvent):
            raise HTTPException(status_code=400, detail="Malformed Resend email.received event")
        if not recipient_is_allowed(event.data.to, settings.resend_inbound_recipients):
            return {"event_id": event_id, "status": "ignored", "reason": "recipient_not_allowed"}

        service = ResendInboundService.local(settings)
        try:
            result = await run_in_threadpool(
                service.process,
                event,
                event_id=event_id,
                payload_hash=webhook_payload_hash(raw_payload),
            )
            return result.model_dump(mode="json")
        except Exception as exc:
            logger.exception("Resend inbound event %s failed", event_id)
            raise HTTPException(status_code=500, detail="Inbound email processing failed") from exc
        finally:
            await run_in_threadpool(service.close)

    @app.get("/api/{full_path:path}", include_in_schema=False)
    def unknown_api_route(full_path: str):
        raise HTTPException(status_code=404, detail="API route not found")

    frontend_dist = Path("frontend/dist")
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str):
            requested = (frontend_dist / full_path).resolve()
            root = frontend_dist.resolve()
            if requested.exists() and requested.is_file() and (root in requested.parents or requested == root):
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")

    return app


def _basic_auth_is_valid(authorization_header: str | None, settings: Settings) -> bool:
    if not authorization_header or not settings.app_access_password:
        return False
    scheme, _, encoded = authorization_header.partition(" ")
    if scheme.casefold() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    return bool(separator) and hmac.compare_digest(username, settings.app_access_username) and hmac.compare_digest(
        password,
        settings.app_access_password,
    )


def _with_security_headers(response, *, settings: Settings, request_path: str):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    connect_sources = ["'self'"]
    if settings.neon_auth_url:
        parsed_auth_url = urlsplit(settings.neon_auth_url)
        if parsed_auth_url.scheme == "https" and parsed_auth_url.netloc:
            connect_sources.append(f"{parsed_auth_url.scheme}://{parsed_auth_url.netloc}")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; "
        f"script-src 'self'; frame-src 'self' blob:; connect-src {' '.join(connect_sources)}"
    )
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request_path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def _check_runtime_dependencies(settings: Settings) -> None:
    connection = connect(settings.database_url)
    try:
        connection.execute("SELECT 1").fetchone()
    finally:
        connection.close()

    document_storage_from_settings(settings).check_ready()
    if settings.contract_processing_mode == "rabbitmq":
        RabbitMQContractQueue.from_settings(settings).check_ready()
    settings.inbound_attachment_dir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".samvid-ready-", dir=settings.inbound_attachment_dir):
        pass
