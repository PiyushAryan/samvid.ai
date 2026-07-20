from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_env: str = "development"
    app_base_url: str | None = None
    auth_mode: str = "basic"
    app_access_username: str = "samvid"
    app_access_password: str | None = None
    neon_auth_url: str | None = None
    neon_auth_jwks_url: str | None = None
    neon_auth_issuer: str | None = None
    neon_auth_audience: str | None = None
    neon_auth_require_email_verified: bool = False
    neon_auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    samvid_super_admin_email: str | None = None
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    resend_inbound_enabled: bool = False
    resend_webhook_secret: str | None = None
    resend_inbound_recipients: tuple[str, ...] = ()
    email_workspace_id: str = "email-workspace"
    email_from_address: str = "contractmate@example.com"
    resend_api_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    database_url: str = "postgresql://contractmate:contractmate@localhost:5432/contractmate"
    database_direct_url: str | None = None
    auto_initialize_database: bool = True
    document_storage_backend: str = "local"
    local_storage_dir: Path = Path(".contractmate/files")
    inbound_attachment_dir: Path = Path(".contractmate/inbound-email")
    blob_read_write_token: str | None = None
    blob_store_id: str | None = None
    vercel_oidc_token: str | None = None
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    rabbitmq_url: str | None = None
    rabbitmq_exchange: str = "contract.events"
    rabbitmq_review_queue: str = "contract.review.q"
    rabbitmq_retry_queue: str = "contract.review.retry.q"
    rabbitmq_dlq: str = "contract.review.dlq"
    rabbitmq_retry_ttl_ms: int = Field(default=60_000, ge=1)
    rabbitmq_max_attempts: int = Field(default=3, ge=1)
    rabbitmq_heartbeat_seconds: int = Field(default=600, ge=0)
    rabbitmq_knowledge_index_queue: str = "contract.knowledge-index.q"
    rabbitmq_knowledge_index_retry_queue: str = "contract.knowledge-index.retry.q"
    rabbitmq_knowledge_index_dlq: str = "contract.knowledge-index.dlq"
    contract_processing_mode: str = "sync"
    model_provider: str = "openai"
    model_id: str = "gpt-5-mini"
    model_api_key: str | None = None
    agentic_chat_enabled: bool = False
    chat_model_id: str = "gpt-5-mini"
    chat_max_input_chars: int = Field(default=4_000, ge=100, le=20_000)
    fireworks_api_key: str | None = None
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"
    embedding_model_id: str = "fireworks/qwen3-embedding-8b"
    embedding_dimensions: int = Field(default=1024, ge=1024, le=1024)
    rerank_model_id: str = "fireworks/qwen3-reranker-8b"
    max_file_size_mb: int = Field(default=20, ge=1)
    contract_retention_days: int = Field(default=30, ge=1)
    enable_ocr: bool = False
    ocr_provider: str = "sarvam"
    sarvam_api_key: str | None = None
    sarvam_ocr_language: str = "en-IN"
    sarvam_ocr_timeout_seconds: int = Field(default=600, ge=1)
    enable_tracing: bool = True
    auto_send_review_email: bool = True
    os_security_key: str | None = None
    jwt_verification_key: str | None = None
    samvid_local_actor_email: str = "local@samvid.local"
    samvid_local_actor_name: str = "Local Samvid User"
    frontend_origin: str = "http://localhost:5173"

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() in {"production", "prod"}

    def validate_runtime(self) -> None:
        inbound_errors: list[str] = []
        if self.resend_inbound_enabled:
            if not self.resend_api_key or self.resend_api_key == "re_xxxxxxxxx":
                inbound_errors.append("RESEND_API_KEY is required when Resend inbound receiving is enabled")
            if not self.resend_webhook_secret:
                inbound_errors.append("RESEND_WEBHOOK_SECRET is required when Resend inbound receiving is enabled")
            if not self.resend_inbound_recipients:
                inbound_errors.append("RESEND_INBOUND_RECIPIENTS is required when Resend inbound receiving is enabled")
            if not self.samvid_super_admin_email:
                inbound_errors.append("SAMVID_SUPER_ADMIN_EMAIL is required when Resend inbound receiving is enabled")
        if inbound_errors:
            raise ValueError("Invalid inbound email configuration: " + "; ".join(inbound_errors))

        if not self.is_production:
            return

        errors: list[str] = []
        if not self.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            errors.append("DATABASE_URL must point to PostgreSQL")
        if self.database_direct_url and not self.database_direct_url.startswith(
            ("postgres://", "postgresql://", "postgresql+psycopg://")
        ):
            errors.append("DATABASE_URL_UNPOOLED must point to PostgreSQL")
        if not self.model_api_key:
            errors.append("OPENAI_API_KEY or MODEL_API_KEY is required")
        if self.auth_mode not in {"basic", "neon"}:
            errors.append("AUTH_MODE must be 'basic' or 'neon'")
        if self.auth_mode == "basic" and (not self.app_access_password or len(self.app_access_password) < 16):
            errors.append("APP_ACCESS_PASSWORD must contain at least 16 characters when AUTH_MODE=basic")
        if self.auth_mode == "neon":
            if not self.neon_auth_url:
                errors.append("NEON_AUTH_URL is required when AUTH_MODE=neon")
            if not self.neon_auth_require_email_verified:
                errors.append("NEON_AUTH_REQUIRE_EMAIL_VERIFIED must be true in production when AUTH_MODE=neon")
            if not self.samvid_super_admin_email:
                errors.append("SAMVID_SUPER_ADMIN_EMAIL is required when AUTH_MODE=neon")
        if not self.fireworks_api_key:
            errors.append("FIREWORKS_API_KEY is required for contract chat")
        if not self.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            errors.append("Contract chat requires PostgreSQL with pgvector")
        if self.enable_ocr and not self.sarvam_api_key:
            errors.append("SARVAM_API_KEY is required when OCR is enabled")
        if self.auto_send_review_email and not (self.resend_api_key or self.smtp_host):
            errors.append("RESEND_API_KEY or SMTP_HOST is required when automatic email delivery is enabled")
        if self.document_storage_backend not in {"local", "vercel_blob"}:
            errors.append("DOCUMENT_STORAGE_BACKEND must be 'local' or 'vercel_blob'")
        if self.document_storage_backend == "local" and not self.local_storage_dir.is_absolute():
            errors.append("LOCAL_STORAGE_DIR must be an absolute persistent path when local storage is enabled")
        if self.document_storage_backend == "vercel_blob" and not (
            self.blob_read_write_token or (self.blob_store_id and self.vercel_oidc_token)
        ):
            errors.append("Vercel Blob requires BLOB_READ_WRITE_TOKEN or Vercel OIDC credentials")
        if self.contract_processing_mode not in {"sync", "rabbitmq"}:
            errors.append("CONTRACT_PROCESSING_MODE must be 'sync' or 'rabbitmq'")
        if self.contract_processing_mode == "rabbitmq" and not self.rabbitmq_url:
            errors.append("RABBITMQ_URL is required when CONTRACT_PROCESSING_MODE=rabbitmq")
        if not self.inbound_attachment_dir.is_absolute():
            errors.append("INBOUND_ATTACHMENT_DIR must be an absolute writable path")
        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv_file()

        def bool_env(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.lower() in {"1", "true", "yes", "on"}

        def csv_env(name: str, default: str) -> tuple[str, ...]:
            values = [value.strip() for value in os.getenv(name, default).split(",")]
            return tuple(value for value in values if value)

        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            app_base_url=os.getenv("APP_BASE_URL") or None,
            auth_mode=os.getenv("AUTH_MODE", "basic").casefold(),
            app_access_username=os.getenv("APP_ACCESS_USERNAME", "samvid"),
            app_access_password=os.getenv("APP_ACCESS_PASSWORD") or None,
            neon_auth_url=os.getenv("NEON_AUTH_URL") or os.getenv("NEON_AUTH_BASE_URL") or None,
            neon_auth_jwks_url=os.getenv("NEON_AUTH_JWKS_URL") or None,
            neon_auth_issuer=os.getenv("NEON_AUTH_ISSUER") or None,
            neon_auth_audience=os.getenv("NEON_AUTH_AUDIENCE") or None,
            neon_auth_require_email_verified=bool_env("NEON_AUTH_REQUIRE_EMAIL_VERIFIED", False),
            neon_auth_clock_skew_seconds=int(os.getenv("NEON_AUTH_CLOCK_SKEW_SECONDS", "30")),
            samvid_super_admin_email=os.getenv("SAMVID_SUPER_ADMIN_EMAIL") or None,
            allowed_hosts=csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"),
            resend_inbound_enabled=bool_env("RESEND_INBOUND_ENABLED", False),
            resend_webhook_secret=os.getenv("RESEND_WEBHOOK_SECRET") or None,
            resend_inbound_recipients=csv_env("RESEND_INBOUND_RECIPIENTS", ""),
            email_workspace_id=os.getenv("EMAIL_WORKSPACE_ID", "email-workspace"),
            email_from_address=os.getenv("EMAIL_FROM_ADDRESS", "contractmate@example.com"),
            resend_api_key=os.getenv("RESEND_API_KEY") or None,
            smtp_host=os.getenv("SMTP_HOST") or None,
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME") or None,
            smtp_password=os.getenv("SMTP_PASSWORD") or None,
            smtp_use_tls=bool_env("SMTP_USE_TLS", True),
            database_url=os.getenv("DATABASE_URL", "postgresql://contractmate:contractmate@localhost:5432/contractmate"),
            database_direct_url=os.getenv("DATABASE_URL_UNPOOLED") or None,
            auto_initialize_database=bool_env("AUTO_INITIALIZE_DATABASE", True),
            document_storage_backend=os.getenv("DOCUMENT_STORAGE_BACKEND", "local").casefold(),
            local_storage_dir=Path(os.getenv("LOCAL_STORAGE_DIR", ".contractmate/files")),
            inbound_attachment_dir=Path(os.getenv("INBOUND_ATTACHMENT_DIR", ".contractmate/inbound-email")),
            blob_read_write_token=os.getenv("BLOB_READ_WRITE_TOKEN") or None,
            blob_store_id=os.getenv("BLOB_STORE_ID") or None,
            vercel_oidc_token=os.getenv("VERCEL_OIDC_TOKEN") or None,
            s3_bucket=os.getenv("S3_BUCKET") or None,
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            rabbitmq_url=os.getenv("RABBITMQ_URL") or None,
            rabbitmq_exchange=os.getenv("RABBITMQ_EXCHANGE", "contract.events"),
            rabbitmq_review_queue=os.getenv("RABBITMQ_REVIEW_QUEUE", "contract.review.q"),
            rabbitmq_retry_queue=os.getenv("RABBITMQ_RETRY_QUEUE", "contract.review.retry.q"),
            rabbitmq_dlq=os.getenv("RABBITMQ_DLQ", "contract.review.dlq"),
            rabbitmq_retry_ttl_ms=int(os.getenv("RABBITMQ_RETRY_TTL_MS", "60000")),
            rabbitmq_max_attempts=int(os.getenv("RABBITMQ_MAX_ATTEMPTS", "3")),
            rabbitmq_heartbeat_seconds=int(os.getenv("RABBITMQ_HEARTBEAT_SECONDS", "600")),
            rabbitmq_knowledge_index_queue=os.getenv("RABBITMQ_KNOWLEDGE_INDEX_QUEUE", "contract.knowledge-index.q"),
            rabbitmq_knowledge_index_retry_queue=os.getenv(
                "RABBITMQ_KNOWLEDGE_INDEX_RETRY_QUEUE", "contract.knowledge-index.retry.q"
            ),
            rabbitmq_knowledge_index_dlq=os.getenv("RABBITMQ_KNOWLEDGE_INDEX_DLQ", "contract.knowledge-index.dlq"),
            contract_processing_mode=os.getenv("CONTRACT_PROCESSING_MODE", "sync").casefold(),
            model_provider=os.getenv("MODEL_PROVIDER", "openai"),
            model_id=os.getenv("MODEL_ID", "gpt-5-mini"),
            model_api_key=os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
            agentic_chat_enabled=bool_env("AGENTIC_CHAT_ENABLED", False),
            chat_model_id=os.getenv("CHAT_MODEL_ID", os.getenv("MODEL_ID", "gpt-5-mini")),
            chat_max_input_chars=int(os.getenv("CHAT_MAX_INPUT_CHARS", "4000")),
            fireworks_api_key=os.getenv("FIREWORKS_API_KEY") or None,
            fireworks_base_url=os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").rstrip("/"),
            embedding_model_id=os.getenv("EMBEDDING_MODEL_ID", "fireworks/qwen3-embedding-8b"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
            rerank_model_id=os.getenv("RERANK_MODEL_ID", "fireworks/qwen3-reranker-8b"),
            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "20")),
            contract_retention_days=int(os.getenv("CONTRACT_RETENTION_DAYS", "30")),
            enable_ocr=bool_env("ENABLE_OCR", False),
            ocr_provider=os.getenv("OCR_PROVIDER", "sarvam"),
            sarvam_api_key=os.getenv("SARVAM_API_KEY") or None,
            sarvam_ocr_language=os.getenv("SARVAM_OCR_LANGUAGE", "en-IN"),
            sarvam_ocr_timeout_seconds=int(os.getenv("SARVAM_OCR_TIMEOUT_SECONDS", "600")),
            enable_tracing=bool_env("ENABLE_TRACING", True),
            auto_send_review_email=bool_env("AUTO_SEND_REVIEW_EMAIL", True),
            os_security_key=os.getenv("OS_SECURITY_KEY") or None,
            jwt_verification_key=os.getenv("JWT_VERIFICATION_KEY") or None,
            samvid_local_actor_email=os.getenv("SAMVID_LOCAL_ACTOR_EMAIL", "local@samvid.local"),
            samvid_local_actor_name=os.getenv("SAMVID_LOCAL_ACTOR_NAME", "Local Samvid User"),
            frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        )


def load_dotenv_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
