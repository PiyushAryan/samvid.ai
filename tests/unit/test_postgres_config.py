import pytest

from contractmate.db.session import is_postgres_url, normalize_postgres_url
from contractmate.settings import Settings


def test_settings_default_database_is_postgres() -> None:
    settings = Settings()

    assert settings.database_url.startswith("postgresql://")
    assert settings.auto_initialize_database is True
    assert settings.model_provider == "openai"
    assert settings.model_id == "gpt-5-mini"


def test_postgres_url_helpers_support_psycopg_style_url() -> None:
    url = "postgresql+psycopg://user:pass@localhost:5432/db"

    assert is_postgres_url(url)
    assert normalize_postgres_url(url) == "postgresql://user:pass@localhost:5432/db"


def test_postgres_url_helpers_support_render_style_url() -> None:
    url = "postgres://user:pass@database:5432/db"

    assert is_postgres_url(url)
    assert normalize_postgres_url(url) == "postgresql://user:pass@database:5432/db"


def test_production_settings_fail_fast_when_secrets_are_missing(tmp_path) -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql://user:pass@database/samvid",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        auto_send_review_email=False,
    )

    with pytest.raises(ValueError, match="APP_ACCESS_PASSWORD"):
        settings.validate_runtime()


def test_production_settings_accept_vercel_blob_oidc(tmp_path) -> None:
    settings = Settings(
        app_env="production",
        app_access_password="private-beta-password",
        database_url="postgresql://user:pass@database/samvid",
        document_storage_backend="vercel_blob",
        local_storage_dir=tmp_path / "unused-local-storage",
        inbound_attachment_dir=tmp_path / "inbound",
        blob_store_id="store_contracts",
        vercel_oidc_token="oidc-token",
        model_api_key="model-key",
        auto_send_review_email=False,
    )

    settings.validate_runtime()


def test_production_settings_accept_neon_auth_without_basic_password(tmp_path) -> None:
    settings = Settings(
        app_env="production",
        auth_mode="neon",
        neon_auth_url="https://ep-example.neonauth.us-east-1.aws.neon.tech/neondb/auth",
        neon_auth_allowed_emails=("owner@example.com",),
        neon_auth_require_email_verified=True,
        database_url="postgresql://user:pass@database/samvid",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="model-key",
        auto_send_review_email=False,
    )

    settings.validate_runtime()


def test_auto_initialize_database_can_be_disabled_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_INITIALIZE_DATABASE", "false")

    settings = Settings.from_env()

    assert settings.auto_initialize_database is False
