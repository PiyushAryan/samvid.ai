from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_env: str = "development"
    app_base_url: str | None = None
    app_access_username: str = "samvid"
    app_access_password: str | None = None
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    inbound_email_secret: str | None = None
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
    contract_processing_mode: str = "sync"
    model_provider: str = "openai"
    model_id: str = "gpt-5-mini"
    model_api_key: str | None = None
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
        if not self.inbound_email_secret or len(self.inbound_email_secret) < 16:
            errors.append("INBOUND_EMAIL_SECRET must contain at least 16 characters")
        if not self.app_access_password or len(self.app_access_password) < 16:
            errors.append("APP_ACCESS_PASSWORD must contain at least 16 characters")
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
            app_access_username=os.getenv("APP_ACCESS_USERNAME", "samvid"),
            app_access_password=os.getenv("APP_ACCESS_PASSWORD") or None,
            allowed_hosts=csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"),
            inbound_email_secret=os.getenv("INBOUND_EMAIL_SECRET") or None,
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
            contract_processing_mode=os.getenv("CONTRACT_PROCESSING_MODE", "sync").casefold(),
            model_provider=os.getenv("MODEL_PROVIDER", "openai"),
            model_id=os.getenv("MODEL_ID", "gpt-5-mini"),
            model_api_key=os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
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
