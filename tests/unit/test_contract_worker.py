from contractmate.services.contract_processing import ContractProcessingResult
from contractmate.schemas.contracts import ContractReview
from contractmate.settings import Settings
from contractmate.workers.contract_worker import ContractWorker
from contractmate.workers.queue import ContractReviewJob, QueueTopology
from contractmate.workflows.states import WorkflowState


def test_worker_acknowledges_successful_review() -> None:
    service = _FakeProcessingService()
    delivery = _FakeDelivery(_job())
    worker = ContractWorker(
        settings=Settings(),
        queue=_FakeQueue(delivery),
        processing_service_factory=lambda _settings: service,
    )

    assert worker.run_once()

    assert delivery.acked
    assert not delivery.retried
    assert service.closed


def test_worker_marks_terminal_failure_before_dead_lettering() -> None:
    service = _FakeProcessingService(error=RuntimeError("model unavailable"))
    delivery = _FakeDelivery(_job(attempt=3))
    worker = ContractWorker(
        settings=Settings(),
        queue=_FakeQueue(delivery, max_attempts=3),
        processing_service_factory=lambda _settings: service,
    )

    assert worker.run_once()

    assert delivery.retried
    assert service.failed == [("contract-1", "workspace-1", "model unavailable")]
    assert service.closed


def test_worker_retries_when_processing_service_cannot_start() -> None:
    delivery = _FakeDelivery(_job())
    worker = ContractWorker(
        settings=Settings(),
        queue=_FakeQueue(delivery),
        processing_service_factory=lambda _settings: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert worker.run_once()

    assert delivery.retried
    assert not delivery.acked


def test_worker_stops_before_polling_when_shutdown_is_requested() -> None:
    queue = _FakeQueue(None)
    worker = ContractWorker(settings=Settings(), queue=queue)

    worker.run_forever(stop_requested=lambda: True)

    assert queue.topology_declared
    assert queue.receive_count == 0


def test_worker_sends_review_as_threaded_reply(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(
        "contractmate.workers.contract_worker.EmailSender.send",
        lambda _sender, message: sent.append(message),
    )
    worker = ContractWorker(
        settings=Settings(
            email_from_address="onboarding@resend.dev",
            frontend_origin="https://samvid-ai.vercel.app",
        ),
        queue=_FakeQueue(None),
    )
    job = ContractReviewJob(
        job_id="job-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        workspace_id="workspace-1",
        email_thread_id="thread-1",
        requested_by="sender@example.com",
        recipient_name="Contract Sender",
        response_address="replies@example.com",
        original_subject="Please review",
        in_reply_to="<message@example.com>",
        references="<earlier@example.com> <message@example.com>",
        send_review_email=True,
    )
    result = ContractProcessingResult(
        contract_id="contract-1",
        contract_version_id="version-1",
        status=WorkflowState.REVIEW_READY,
        review=ContractReview(
            contract_id="contract-1",
            contract_type="Vendor agreement",
            recommended_next_action="Request revisions.",
        ),
        message="Contract review is ready.",
    )

    worker._send_review_email(job, result)

    assert sent[0].to_address == "replies@example.com"
    assert sent[0].subject == "Re: Please review"
    assert sent[0].text.startswith("Hi Contract Sender,")
    assert "https://samvid-ai.vercel.app/contracts/contract-1" in sent[0].text
    assert sent[0].html is not None
    assert "Open contract in Samvid" in sent[0].html
    assert "Sent via Samvid" in sent[0].html
    assert sent[0].in_reply_to == "<message@example.com>"
    assert sent[0].references == "<earlier@example.com> <message@example.com>"


def _job(*, attempt: int = 1) -> ContractReviewJob:
    return ContractReviewJob(
        job_id="job-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        workspace_id="workspace-1",
        email_thread_id="thread-1",
        requested_by="reviewer@example.com",
        attempt=attempt,
    )


class _FakeQueue:
    def __init__(self, delivery, *, max_attempts: int = 3) -> None:
        self.delivery = delivery
        self.topology = QueueTopology(max_attempts=max_attempts)
        self.topology_declared = False
        self.receive_count = 0

    def declare_topology(self) -> None:
        self.topology_declared = True

    def receive(self, *, prefetch_count: int = 1):
        assert prefetch_count == 1
        self.receive_count += 1
        delivery, self.delivery = self.delivery, None
        return delivery


class _FakeDelivery:
    def __init__(self, job: ContractReviewJob) -> None:
        self.job = job
        self.acked = False
        self.retried = False

    def ack(self) -> None:
        self.acked = True

    def retry(self) -> None:
        self.retried = True


class _FakeProcessingService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.failed: list[tuple[str, str, str]] = []
        self.closed = False

    def review_stored_contract(self, *, contract_id: str, contract_version_id: str, workspace_id: str):
        if self.error:
            raise self.error
        return ContractProcessingResult(
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            status=WorkflowState.REVIEW_READY,
            message="Contract review is ready.",
        )

    def mark_analysis_failed(self, *, contract_id: str, workspace_id: str, error: str) -> None:
        self.failed.append((contract_id, workspace_id, error))

    def close(self) -> None:
        self.closed = True
