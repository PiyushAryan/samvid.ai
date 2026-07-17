import base64
import binascii
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from contractmate.api.routes import create_api_router
from contractmate.db.session import connect, initialize_database
from contractmate.email.messages import InboundEmailMessage
from contractmate.security.control_plane import authorize_control_plane_request
from contractmate.services.email_ingestion import EmailIngestionService
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
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'api' extra to run the HTTP app: uv sync --extra api") from exc

    settings = settings or Settings.from_env()
    settings.validate_runtime()

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
        if settings.is_production and request.url.path not in public_paths:
            if not _basic_auth_is_valid(request.headers.get("authorization"), settings):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                    headers={"WWW-Authenticate": 'Basic realm="Samvid", charset="UTF-8"'},
                )
                return _with_security_headers(response, settings=settings, request_path=request.url.path)
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
    def inbound_email(
        message: InboundEmailMessage,
        x_contractmate_email_secret: str | None = Header(default=None),
    ) -> dict:
        if settings.inbound_email_secret and not hmac.compare_digest(
            settings.inbound_email_secret,
            x_contractmate_email_secret or "",
        ):
            raise HTTPException(status_code=401, detail="Invalid inbound email secret")
        service = EmailIngestionService.local(settings)
        try:
            result = service.process_inbound_email(
                message,
                send_response=settings.auto_send_review_email,
            )
            return result.model_dump(mode="json")
        finally:
            service.close()

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
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'"
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
