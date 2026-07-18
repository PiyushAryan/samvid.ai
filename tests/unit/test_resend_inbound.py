import base64
import hashlib
import hmac
import json
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from contractmate.db.repositories.inbound_email_events import InboundEmailEventRepository, InboundEventClaim
from contractmate.db.session import connect
from contractmate.email.resend_inbound import (
    ResendInboundResult,
    ResendInboundService,
    ResendReceivingClient,
    ResendWebhookEvent,
    parse_resend_webhook,
)
from contractmate.settings import Settings


WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"resend-test-secret").decode("ascii")


def test_resend_webhook_accepts_valid_signature_and_rejects_invalid_missing_and_expired(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import contractmate.app as app_module

    service = _FakeWebhookService()
    monkeypatch.setattr(
        app_module.ResendInboundService,
        "local",
        classmethod(lambda _cls, _settings: service),
    )
    client = TestClient(app_module.create_app(_webhook_settings()))
    payload = _event_payload()

    valid = client.post("/email/inbound", content=payload, headers=_signed_headers(payload))
    invalid = client.post(
        "/email/inbound",
        content=payload,
        headers={**_signed_headers(payload), "svix-signature": "v1,invalid"},
    )
    missing = client.post("/email/inbound", content=payload)
    expired = client.post(
        "/email/inbound",
        content=payload,
        headers=_signed_headers(payload, timestamp=int(time.time()) - 600),
    )

    assert valid.status_code == 200
    assert valid.json()["status"] == "processed"
    assert invalid.status_code == 401
    assert missing.status_code == 401
    assert expired.status_code == 401
    assert service.process_count == 1


def test_resend_webhook_rejects_malformed_signed_json_and_ignores_unrelated_events() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app

    client = TestClient(create_app(_webhook_settings()))
    malformed = b"not-json"
    unrelated = json.dumps({"type": "email.sent", "data": {"id": "email-1", "unexpected": True}}).encode()
    other_recipient = _event_payload(to=["other@oldimeluub.resend.app"])

    assert client.post("/email/inbound", content=malformed, headers=_signed_headers(malformed)).status_code == 400
    event_response = client.post("/email/inbound", content=unrelated, headers=_signed_headers(unrelated))
    recipient_response = client.post(
        "/email/inbound",
        content=other_recipient,
        headers=_signed_headers(other_recipient),
    )
    assert event_response.status_code == 200
    assert event_response.json()["reason"] == "unsupported_event"
    assert recipient_response.status_code == 200
    assert recipient_response.json()["reason"] == "recipient_not_allowed"


def test_resend_webhook_returns_500_for_transient_processing_failure(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import contractmate.app as app_module

    service = _FailingWebhookService()
    monkeypatch.setattr(
        app_module.ResendInboundService,
        "local",
        classmethod(lambda _cls, _settings: service),
    )
    payload = _event_payload()

    response = TestClient(app_module.create_app(_webhook_settings())).post(
        "/email/inbound",
        content=payload,
        headers=_signed_headers(payload),
    )

    assert response.status_code == 500
    assert service.closed


def test_inbound_service_downloads_supported_files_and_preserves_reply_metadata(tmp_path: Path) -> None:
    settings = _service_settings(tmp_path)
    repository = InboundEmailEventRepository(connect(settings.database_url))
    ingestion = _FakeIngestionService()
    client = _FakeReceivingClient()
    service = ResendInboundService(
        settings=settings,
        event_repository=repository,
        ingestion_service=ingestion,
        client=client,
    )
    event = parse_resend_webhook(_event_payload())

    first = service.process(event, event_id="evt-1", payload_hash="hash-1")
    second = service.process(event, event_id="evt-1", payload_hash="hash-1")

    assert first.status == "processed"
    assert first.processed_attachments == 1
    assert first.ignored_attachments == ["inline.png", "notes.md", "large.pdf"]
    assert second.status == "duplicate"
    assert ingestion.process_count == 1
    assert ingestion.message.response_address == "legal-replies@example.com"
    assert ingestion.message.from_address == "sender@example.com"
    assert ingestion.message.from_name == "Contract Sender"
    assert ingestion.message.original_message_id == "<original@example.com>"
    assert ingestion.message.references == "<earlier@example.com> <original@example.com>"
    assert ingestion.message.attachments[0].filename == "vendor.txt"
    assert not list(settings.inbound_attachment_dir.glob("samvid-resend-*"))
    service.close()


def test_inbound_service_marks_transient_failure_for_retry(tmp_path: Path) -> None:
    settings = _service_settings(tmp_path)
    repository = InboundEmailEventRepository(connect(settings.database_url))
    ingestion = _FakeIngestionService()
    client = _FakeReceivingClient(error=RuntimeError("Resend unavailable"))
    service = ResendInboundService(
        settings=settings,
        event_repository=repository,
        ingestion_service=ingestion,
        client=client,
    )
    event = parse_resend_webhook(_event_payload())

    with pytest.raises(RuntimeError, match="Resend unavailable"):
        service.process(event, event_id="evt-1", payload_hash="hash-1")

    row = repository.connection.execute(
        "SELECT status FROM inbound_email_events WHERE email_message_id = ?",
        (event.data.email_id,),
    ).fetchone()
    assert row["status"] == "failed"

    client.error = None
    retried = service.process(event, event_id="evt-1", payload_hash="hash-1")
    assert retried.status == "processed"
    service.close()


def test_inbound_service_caps_supported_attachments_at_five(tmp_path: Path) -> None:
    settings = _service_settings(tmp_path)
    repository = InboundEmailEventRepository(connect(settings.database_url))
    ingestion = _FakeIngestionService()
    client = _FakeReceivingClient()
    client.list_attachments = lambda _email_id: [
        _attachment(f"vendor-{index}.txt", "text/plain", 22) for index in range(6)
    ]
    service = ResendInboundService(
        settings=settings,
        event_repository=repository,
        ingestion_service=ingestion,
        client=client,
    )

    result = service.process(parse_resend_webhook(_event_payload()), event_id="evt-1", payload_hash="hash-1")

    assert result.processed_attachments == 5
    assert result.ignored_attachments == ["vendor-5.txt"]
    assert len(ingestion.message.attachments) == 5
    service.close()


def test_inbound_event_repository_reclaims_only_failed_or_stale_processing(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'events.db'}")
    repository = InboundEmailEventRepository(connection)
    arguments = {
        "event_id": "evt-1",
        "email_message_id": "email-1",
        "workspace_id": "workspace-1",
        "event_type": "email.received",
        "payload_hash": "hash-1",
    }

    assert repository.claim(**arguments) is InboundEventClaim.ACQUIRED
    assert repository.claim(**arguments) is InboundEventClaim.PROCESSING
    connection.execute(
        "UPDATE inbound_email_events SET received_at = datetime('now', '-11 minutes') WHERE email_message_id = ?",
        ("email-1",),
    )
    connection.commit()
    assert repository.claim(**arguments) is InboundEventClaim.ACQUIRED
    repository.mark_completed("email-1")
    assert repository.claim(**arguments) is InboundEventClaim.COMPLETED
    connection.close()


def test_resend_download_rejects_non_resend_host(tmp_path: Path) -> None:
    client = ResendReceivingClient("re_test")

    with pytest.raises(ValueError, match="approved Resend URL"):
        client.download_attachment(
            "https://example.com/contract.pdf",
            tmp_path / "contract.pdf",
            max_bytes=100,
        )


def test_resend_download_accepts_live_resend_cdn_host(tmp_path: Path) -> None:
    chunks = iter([b"contract-content", b""])
    response = SimpleNamespace(headers={}, read=lambda _size: next(chunks))
    client = ResendReceivingClient(
        "re_test",
        open_url=lambda *_args, **_kwargs: nullcontext(response),
    )
    destination = tmp_path / "contract.pdf"

    client.download_attachment(
        "https://cdn.resend.app/received-email/attachments/contract.pdf?signature=test",
        destination,
        max_bytes=100,
    )

    assert destination.read_bytes() == b"contract-content"


def test_inbound_settings_are_required_only_when_receiving_is_enabled() -> None:
    Settings().validate_runtime()

    with pytest.raises(ValueError, match="RESEND_WEBHOOK_SECRET"):
        Settings(resend_inbound_enabled=True, resend_api_key="re_test").validate_runtime()


class _FakeWebhookService:
    def __init__(self) -> None:
        self.process_count = 0

    def process(self, event, *, event_id: str, payload_hash: str) -> ResendInboundResult:
        self.process_count += 1
        assert payload_hash
        return ResendInboundResult(event_id=event_id, email_id=event.data.email_id, status="processed")

    def close(self) -> None:
        pass


class _FailingWebhookService:
    def __init__(self) -> None:
        self.closed = False

    def process(self, *_args, **_kwargs):
        raise RuntimeError("RabbitMQ unavailable")

    def close(self) -> None:
        self.closed = True


class _FakeIngestionService:
    def __init__(self) -> None:
        self.process_count = 0
        self.message = None

    def process_inbound_email(self, message, *, send_response: bool):
        self.process_count += 1
        self.message = message
        assert send_response
        for attachment in message.attachments:
            assert attachment.local_path.read_text(encoding="utf-8") == "Vendor agreement text"
        return SimpleNamespace(processed=[object() for _ in message.attachments], ignored_attachments=[])

    def close(self) -> None:
        pass


class _FakeReceivingClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def get_email(self, email_id: str) -> dict:
        if self.error:
            raise self.error
        return {
            "id": email_id,
            "from": "Contract Sender <sender@example.com>",
            "reply_to": ["Legal Replies <legal-replies@example.com>"],
            "to": ["contracts@oldimeluub.resend.app"],
            "received_for": ["contracts@oldimeluub.resend.app"],
            "subject": "Please review this agreement",
            "text": "Review attached.",
            "message_id": "<original@example.com>",
            "headers": {"References": "<earlier@example.com>"},
        }

    def list_attachments(self, email_id: str) -> list[dict]:
        return [
            _attachment("vendor.txt", "text/plain", 22),
            _attachment("inline.png", "image/png", 10, disposition="inline"),
            _attachment("notes.md", "text/plain", 10),
            _attachment("large.pdf", "application/pdf", 30 * 1024 * 1024),
        ]

    def download_attachment(self, download_url: str, destination: Path, *, max_bytes: int) -> None:
        assert download_url.startswith("https://inbound-cdn.resend.com/")
        destination.write_text("Vendor agreement text", encoding="utf-8")


def _attachment(filename: str, content_type: str, size: int, *, disposition: str = "attachment") -> dict:
    return {
        "id": filename,
        "filename": filename,
        "content_type": content_type,
        "content_disposition": disposition,
        "size": size,
        "download_url": f"https://inbound-cdn.resend.com/{filename}",
    }


def _webhook_settings() -> Settings:
    return Settings(
        auto_initialize_database=False,
        resend_inbound_enabled=True,
        resend_api_key="re_test",
        resend_webhook_secret=WEBHOOK_SECRET,
        resend_inbound_recipients=("contracts@oldimeluub.resend.app",),
    )


def _service_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'samvid.db'}",
        local_storage_dir=tmp_path / "files",
        inbound_attachment_dir=tmp_path / "inbound",
        resend_inbound_enabled=True,
        resend_api_key="re_test",
        resend_webhook_secret=WEBHOOK_SECRET,
        resend_inbound_recipients=("contracts@oldimeluub.resend.app",),
        model_api_key="model-key",
        auto_send_review_email=True,
    )


def _event_payload(*, to: list[str] | None = None) -> bytes:
    return json.dumps(
        {
            "type": "email.received",
            "data": {
                "email_id": "email-1",
                "to": to or ["contracts@oldimeluub.resend.app"],
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _signed_headers(payload: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    event_id = "evt-1"
    timestamp_value = str(timestamp or int(time.time()))
    secret = base64.b64decode(WEBHOOK_SECRET.removeprefix("whsec_"))
    signed = event_id.encode() + b"." + timestamp_value.encode() + b"." + payload
    signature = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode("ascii")
    return {
        "svix-id": event_id,
        "svix-timestamp": timestamp_value,
        "svix-signature": f"v1,{signature}",
        "content-type": "application/json",
    }
