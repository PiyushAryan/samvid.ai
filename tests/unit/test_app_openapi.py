import pytest


def test_app_generates_openapi_schema() -> None:
    pytest.importorskip("fastapi")

    from contractmate.app import create_app
    from contractmate.settings import Settings

    schema = create_app(Settings()).openapi()

    assert schema["info"]["title"] == "Samvid"
    assert "/api/contracts" in schema["paths"]
    assert "/email/inbound" in schema["paths"]


def test_production_app_requires_basic_auth_and_sets_security_headers(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app
    from contractmate.settings import Settings

    frontend_dist = tmp_path / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<main>Samvid</main>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    settings = Settings(
        app_env="production",
        app_access_username="samvid",
        app_access_password="private-beta-password",
        allowed_hosts=("testserver",),
        database_url="postgresql://user:pass@database/samvid",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
            model_api_key="model-key",
            fireworks_api_key="fireworks-key",
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


def test_app_can_skip_database_initialization(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import contractmate.app as app_module
    from contractmate.settings import Settings

    def fail_if_called(*_args, **_kwargs) -> None:
        raise AssertionError("database initialization should be skipped")

    monkeypatch.setattr(app_module, "initialize_database", fail_if_called)
    settings = Settings(auto_initialize_database=False)

    response = TestClient(app_module.create_app(settings)).get("/health")

    assert response.status_code == 200


def test_rabbitmq_mode_upload_persists_and_returns_queued(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app
    from contractmate.settings import Settings
    from contractmate.workers.queue import InMemoryContractQueue, RabbitMQContractQueue

    queue = InMemoryContractQueue()
    monkeypatch.setattr(
        RabbitMQContractQueue,
        "from_settings",
        classmethod(lambda _cls, _settings: queue),
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'samvid.db'}",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="model-key",
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        contract_processing_mode="rabbitmq",
    )

    response = TestClient(create_app(settings)).post(
        "/api/contracts",
        files={"file": ("vendor.txt", b"Vendor agreement text", "text/plain")},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    job = queue.receive()
    assert job is not None
    assert job.contract_id == response.json()["contract_id"]
