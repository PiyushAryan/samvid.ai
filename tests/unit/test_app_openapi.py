import pytest


def test_app_generates_openapi_schema() -> None:
    pytest.importorskip("fastapi")

    from contractmate.app import create_app

    schema = create_app().openapi()

    assert schema["info"]["title"] == "Samvid"
    assert "/api/contracts" in schema["paths"]
    assert "/email/inbound" in schema["paths"]
