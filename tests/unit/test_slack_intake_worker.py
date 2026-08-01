from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from contractmate.db.repositories.slack import InboundSlackEvent, SlackLeaseClaim
from contractmate.settings import Settings
from contractmate.workers.queue import InMemoryContractQueue
from contractmate.workers.slack_worker import SlackFileSubmissionBusy, SlackIntakeWorker, _validate_slack_file_url


@pytest.mark.parametrize(
    "flag",
    ["deleted", "is_bot", "is_app_user", "is_restricted", "is_ultra_restricted", "is_stranger"],
)
def test_slack_identity_rejects_non_native_or_inactive_members(flag: str) -> None:
    worker = object.__new__(SlackIntakeWorker)
    member = {flag: True, "profile": {"email": "member@example.com"}}
    client = SimpleNamespace(users_info=lambda **_kwargs: {"user": member})

    assert worker._resolve_user(client, "U1") is None


def test_slack_identity_requires_email_and_accepts_active_human() -> None:
    worker = object.__new__(SlackIntakeWorker)
    no_email = SimpleNamespace(users_info=lambda **_kwargs: {"user": {"profile": {}}})
    human = SimpleNamespace(users_info=lambda **_kwargs: {
        "user": {"profile": {"email": "Human@Example.com", "display_name": "Human"}}
    })

    assert worker._resolve_user(no_email, "U1") is None
    identity = worker._resolve_user(human, "U1")
    assert identity is not None
    assert (identity.email, identity.display_name) == ("human@example.com", "Human")


def test_slack_download_rejects_unapproved_host_and_redirect(tmp_path: Path) -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "https://evil.example/contract.pdf"})
        )
    )
    destination = tmp_path / "contract.pdf"

    with pytest.raises(ValueError, match="approved Slack HTTPS host"):
        worker._download("https://files.slack.com/files-pri/T1-F1/test.pdf", destination, token="xoxb", max_bytes=100)
    with pytest.raises(ValueError, match="approved Slack HTTPS host"):
        _validate_slack_file_url("http://files.slack.com/files-pri/T1-F1/test.pdf")

    worker.http_client.close()


def test_partial_event_retry_reuses_stable_file_submission_key(monkeypatch, tmp_path: Path) -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.settings = Settings(max_file_size_mb=1)
    worker.queue = object()
    worker.repository = _IntentRepository()
    monkeypatch.setattr(
        SlackIntakeWorker,
        "_download",
        lambda _self, _url, destination, **_kwargs: destination.write_text("contract text", encoding="utf-8"),
    )
    service = _ProcessingService()
    event = _event(files=[{"id": "F1", "name": "vendor.txt", "mimetype": "text/plain", "size": 13}])
    client = SimpleNamespace(files_info=lambda **_kwargs: {
        "file": {
            "id": "F1", "name": "vendor.txt", "mimetype": "text/plain", "size": 13,
            "url_private_download": "https://files.slack.com/files-pri/T1-F1/vendor.txt",
        }
    })
    account = SimpleNamespace(personal_workspace_id="workspace-1", email="human@example.com")
    installation = SimpleNamespace(id="install-1")

    for _ in range(2):
        worker._process_file(
            event_record=event, installation=installation, client=client, token="xoxb", account=account,
            service=service, slack_file=event.payload["event"]["files"][0], file_index=0,
                channel_id="C1", thread_ts="1.0", source_key="slack:T1:C1:1.0",
                review_job_id="job-stable",
        )

    assert [call["source_submission_key"] for call in service.calls] == ["Ev1:F1", "Ev1:F1"]
    assert [intent.idempotency_key for intent in worker.repository.intents] == [
        "slack-receipt:Ev1:F1", "slack-receipt:Ev1:F1",
    ]


def test_multi_attachment_consumes_account_quota_once_and_processes_each(monkeypatch) -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.settings = Settings()
    worker.repository = _ProcessRepository()
    worker.accounts = _Accounts()
    worker.token_cipher = SimpleNamespace(decrypt=lambda _value: "xoxb")
    worker.client_factory = lambda _token: SimpleNamespace()
    worker.rate_limiter = _RateLimiter()
    processing = SimpleNamespace(close=lambda: None)
    worker.processing_service_factory = lambda _settings: processing
    monkeypatch.setattr(SlackIntakeWorker, "_resolve_user", lambda *_args: SimpleNamespace(email="human@example.com", display_name="Human"))
    processed: list[str] = []
    monkeypatch.setattr(SlackIntakeWorker, "_process_file", lambda _self, **kwargs: processed.append(kwargs["slack_file"]["id"]))

    assert worker._process(_event(files=[{"id": "F1"}, {"id": "F2"}])) == "processed"
    assert worker.rate_limiter.units == [2]
    assert processed == ["F1", "F2"]


def test_partial_event_retry_publishes_each_file_once_and_charges_quota_once(monkeypatch) -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.settings = Settings()
    worker.repository = _ProcessRepository()
    worker.accounts = _Accounts()
    worker.token_cipher = SimpleNamespace(decrypt=lambda _value: "xoxb")
    worker.client_factory = lambda _token: SimpleNamespace()
    worker.rate_limiter = _RateLimiter()
    worker.processing_service_factory = lambda _settings: SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        SlackIntakeWorker, "_resolve_user",
        lambda *_args: SimpleNamespace(email="human@example.com", display_name="Human"),
    )
    published: list[str] = []
    failed_second = False

    def process_file(_self, **kwargs):
        nonlocal failed_second
        file_id = kwargs["slack_file"]["id"]
        if file_id == "F2" and not failed_second:
            failed_second = True
            raise RuntimeError("temporary Slack failure")
        published.append(f"{kwargs['event_record'].event_id}:{file_id}")

    monkeypatch.setattr(SlackIntakeWorker, "_process_file", process_file)
    event = _event(files=[{"id": "F1"}, {"id": "F2"}])

    with pytest.raises(RuntimeError, match="temporary Slack failure"):
        worker._process(event)
    assert worker._process(event) == "processed"

    assert published == ["Ev1:F1", "Ev1:F2"]
    assert worker.rate_limiter.charge_count == 1
    assert worker.repository.completed == {("Ev1", "F1"), ("Ev1", "F2")}


def test_reclaimed_event_does_not_complete_while_file_lease_is_busy(monkeypatch) -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.settings = Settings()
    worker.repository = _BusyProcessRepository()
    worker.accounts = _Accounts()
    worker.token_cipher = SimpleNamespace(decrypt=lambda _value: "xoxb")
    worker.client_factory = lambda _token: SimpleNamespace()
    worker.rate_limiter = _RateLimiter()
    worker.processing_service_factory = lambda _settings: SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        SlackIntakeWorker, "_resolve_user",
        lambda *_args: SimpleNamespace(email="human@example.com", display_name="Human"),
    )
    monkeypatch.setattr(
        SlackIntakeWorker, "_process_file",
        lambda *_args, **_kwargs: pytest.fail("busy file must not be processed by a second owner"),
    )

    with pytest.raises(SlackFileSubmissionBusy, match="another event delivery"):
        worker._process(_event(files=[{"id": "F1"}]))


def test_terminal_event_retry_queues_source_thread_failure(monkeypatch) -> None:
    worker = object.__new__(SlackIntakeWorker)
    event = _event(files=[])
    worker.repository = SimpleNamespace(
        claim_due_review_jobs=lambda **_kwargs: [],
        claim_due_events=lambda **_kwargs: [event],
        retry_event=lambda **_kwargs: "failed",
    )
    worker.queue = InMemoryContractQueue()
    monkeypatch.setattr(SlackIntakeWorker, "_process", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))
    terminal: list[str] = []
    monkeypatch.setattr(SlackIntakeWorker, "_queue_terminal_event_failure", lambda _self, item: terminal.append(item.event_id))

    assert worker.run_once() == 1
    assert terminal == ["Ev1"]


def test_worker_ignores_workspace_outside_pilot_without_repository_access() -> None:
    worker = object.__new__(SlackIntakeWorker)
    worker.settings = Settings(slack_pilot_team_ids=("T-PILOT",))
    worker.repository = SimpleNamespace(
        get_installation_by_team=lambda **_kwargs: pytest.fail("outside-pilot event must not access installation")
    )
    assert worker._process(_event(files=[])) == "ignored"


def _event(*, files: list[dict]) -> InboundSlackEvent:
    return InboundSlackEvent(
        id="row-1", event_id="Ev1", team_id="T1", event_type="app_mention", attempts=5,
        lease_token="event-owner-1",
        payload={"event": {"type": "app_mention", "user": "U1", "channel": "C1", "ts": "1.0", "files": files}},
    )


class _IntentRepository:
    def __init__(self) -> None:
        self.intents = []

    def enqueue_outbound(self, intent):
        self.intents.append(intent)


class _ProcessingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue_local_file(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(contract_id="contract-1", contract_version_id="version-1")


class _ProcessRepository:
    def __init__(self) -> None:
        self.completed: set[tuple[str, str]] = set()

    def get_installation_by_team(self, **_kwargs):
        return SimpleNamespace(id="install-1", encrypted_bot_token="encrypted", installed_by_account_id="account-1", team_id="T1")

    def link_user(self, **_kwargs):
        return None

    def claim_file_submission(self, *, event_id, file_id):
        if (event_id, file_id) in self.completed:
            return SlackLeaseClaim("completed", review_job_id=f"job-{file_id}")
        return SlackLeaseClaim("claimed", f"lease-{file_id}", f"job-{file_id}")

    def complete_file_submission(self, *, event_id, file_id, lease_token):
        self.completed.add((event_id, file_id))
        return True

    def release_file_submission(self, **_kwargs):
        return True


class _BusyProcessRepository(_ProcessRepository):
    def claim_file_submission(self, *, event_id, file_id):
        return SlackLeaseClaim("busy", review_job_id=f"job-{file_id}")


class _Accounts:
    account = SimpleNamespace(
        id="account-1", email="human@example.com", display_name="Human", state="active",
        personal_workspace_id="workspace-1",
    )

    def get_by_email(self, _email):
        return self.account

    def get_by_id(self, _account_id):
        return self.account


class _RateLimiter:
    def __init__(self) -> None:
        self.units: list[int] = []
        self.reservations: set[str] = set()
        self.charge_count = 0

    def reserve_upload(self, *, policy: object, identifier: str, pathname: str, units: int):
        self.units.append(units)
        if pathname not in self.reservations:
            self.reservations.add(pathname)
            self.charge_count += 1
        return SimpleNamespace(allowed=True)
