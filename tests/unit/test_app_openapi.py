import pytest


def test_app_generates_openapi_schema() -> None:
    pytest.importorskip("fastapi")

    from contractmate.app import create_app

    schema = create_app().openapi()

    assert schema["info"]["title"] == "Samvid"
    assert "/api/contracts" in schema["paths"]
    assert "/email/inbound" in schema["paths"]


def test_production_app_requires_basic_auth_and_sets_security_headers(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app
    from contractmate.settings import Settings

    settings = Settings(
        app_env="production",
        app_access_username="samvid",
        app_access_password="private-beta-password",
        allowed_hosts=("testserver",),
        inbound_email_secret="inbound-email-secret",
        database_url="postgresql://user:pass@database/samvid",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="model-key",
        auto_send_review_email=False,
    )
    client = TestClient(create_app(settings))

    assert client.get("/health").status_code == 200
    unauthenticated = client.get("/")
    authenticated = client.get("/", auth=("samvid", "private-beta-password"))

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"].startswith("Basic")
    assert authenticated.status_code == 200
    assert authenticated.headers["x-content-type-options"] == "nosniff"
    assert "max-age=31536000" in authenticated.headers["strict-transport-security"]


def test_ready_checks_database_and_storage(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app
    from contractmate.settings import Settings

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'samvid.db'}",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
    )

    response = TestClient(create_app(settings)).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "samvid"}
    assert settings.local_storage_dir.is_dir()
    assert settings.inbound_attachment_dir.is_dir()
