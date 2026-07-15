import hmac
from pathlib import Path

from contractmate.api.routes import create_api_router
from contractmate.email.messages import InboundEmailMessage
from contractmate.security.control_plane import authorize_control_plane_request
from contractmate.services.email_ingestion import EmailIngestionService
from contractmate.settings import Settings


def create_app():
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'api' extra to run the HTTP app: uv sync --extra api") from exc

    settings = Settings.from_env()
    app = FastAPI(title="Samvid", version="0.1.0")
    if settings.app_env.casefold() in {"development", "dev", "local"}:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.frontend_origin, "http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(create_api_router(settings))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "samvid"}

    @app.get("/ready")
    def ready() -> dict:
        return {"status": "ready", "env": settings.app_env}

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
                "exchange": settings.rabbitmq_exchange,
                "review_queue": settings.rabbitmq_review_queue,
                "retry_queue": settings.rabbitmq_retry_queue,
                "dlq": settings.rabbitmq_dlq,
                "retry_ttl_ms": settings.rabbitmq_retry_ttl_ms,
                "max_attempts": settings.rabbitmq_max_attempts,
            },
        }

    @app.post("/email/inbound")
    async def inbound_email(
        request: Request,
        x_contractmate_email_secret: str | None = Header(default=None),
    ) -> dict:
        if settings.inbound_email_secret and not hmac.compare_digest(
            settings.inbound_email_secret,
            x_contractmate_email_secret or "",
        ):
            raise HTTPException(status_code=401, detail="Invalid inbound email secret")
        payload = await request.json()
        message = InboundEmailMessage.model_validate(payload)
        result = EmailIngestionService.local(settings).process_inbound_email(
            message,
            send_response=settings.auto_send_review_email,
        )
        return result.model_dump(mode="json")

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
