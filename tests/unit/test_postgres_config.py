from contractmate.db.session import is_postgres_url, normalize_postgres_url
from contractmate.settings import Settings


def test_settings_default_database_is_postgres() -> None:
    settings = Settings()

    assert settings.database_url.startswith("postgresql://")
    assert settings.model_provider == "openai"
    assert settings.model_id == "gpt-5-mini"


def test_postgres_url_helpers_support_psycopg_style_url() -> None:
    url = "postgresql+psycopg://user:pass@localhost:5432/db"

    assert is_postgres_url(url)
    assert normalize_postgres_url(url) == "postgresql://user:pass@localhost:5432/db"
