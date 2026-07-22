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
    delivery = _FakeDelivery(_job(attempt=3, processing_run_id="run-1"))
    worker = ContractWorker(
        settings=Settings(),
        queue=_FakeQueue(delivery, max_attempts=3),
        processing_service_factory=lambda _settings: service,
    )

    assert worker.run_once()

    assert delivery.retried
    assert service.failed == [("contract-1", "workspace-1", "model unavailable", "run-1")]
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


def test_worker_uses_long_lived_consumer_when_queue_supports_it() -> None:
    service = _FakeProcessingService()
    delivery = _FakeDelivery(_job())
    queue = _ConsumingQueue(delivery)
    worker = ContractWorker(
        settings=Settings(),
        queue=queue,
        processing_service_factory=lambda _settings: service,
    )

    worker.run_forever()

    assert queue.consume_count == 1
    assert queue.receive_count == 0
    assert delivery.acked
    assert service.closed


def test_worker_sends_review_as_threaded_reply(monkeypatch) -> None:
    queued = []

    class _Outbox:
        def __init__(self, _connection) -> None:
            pass

        def enqueue(self, intent) -> None:
            queued.append(intent)

    monkeypatch.setattr("contractmate.workers.contract_worker.OutboundEmailOutboxRepository", _Outbox)
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

    worker._queue_review_email(_ServiceWithConnection(), job, result)

    assert queued[0].to_address == "replies@example.com"
    assert queued[0].subject == "Re: Please review"
    assert queued[0].text_body.startswith("Hi Contract Sender,")
    assert "https://samvid-ai.vercel.app/contracts/contract-1" in queued[0].text_body
    assert queued[0].html_body is not None
    assert "Open contract in Samvid" in queued[0].html_body
    assert "Sent via Samvid" in queued[0].html_body
    assert queued[0].in_reply_to == "<message@example.com>"
    assert queued[0].references == "<earlier@example.com> <message@example.com>"
    assert queued[0].idempotency_key == "review:job-1"


def _job(*, attempt: int = 1, processing_run_id: str | None = None) -> ContractReviewJob:
    return ContractReviewJob(
        job_id="job-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        workspace_id="workspace-1",
        email_thread_id="thread-1",
        requested_by="reviewer@example.com",
        attempt=attempt,
        processing_run_id=processing_run_id,
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


class _ConsumingQueue(_FakeQueue):
    def __init__(self, delivery) -> None:
        super().__init__(delivery)
        self.consume_count = 0

    def consume(self, on_delivery, *, stop_requested, reconnect_delay_seconds: float) -> None:
        self.consume_count += 1
        assert reconnect_delay_seconds == 1.0
        delivery, self.delivery = self.delivery, None
        assert delivery is not None
        on_delivery(delivery)


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
        self.failed: list[tuple[str, str, str, str | None]] = []
        self.closed = False

    def review_stored_contract(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        processing_run_id: str | None = None,
    ):
        if self.error:
            raise self.error
        return ContractProcessingResult(
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            status=WorkflowState.REVIEW_READY,
            message="Contract review is ready.",
        )

    def mark_analysis_failed(
        self,
        *,
        contract_id: str,
        workspace_id: str,
        error: str,
        processing_run_id: str | None = None,
    ) -> None:
        self.failed.append((contract_id, workspace_id, error, processing_run_id))

    def close(self) -> None:
        self.closed = True


class _ServiceWithConnection:
    class _Repository:
        connection = object()

    repository = _Repository()
