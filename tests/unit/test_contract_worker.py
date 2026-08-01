import pytest

from contractmate.services.contract_processing import ContractProcessingResult
from contractmate.schemas.contracts import ContractReview
from contractmate.settings import Settings
from contractmate.workers.contract_worker import ContractWorker
from contractmate.workers.queue import ContractReviewJob, QueueTopology
from contractmate.workflows.states import WorkflowState
from contractmate.db.repositories.slack import SlackLeaseClaim


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


def test_slack_review_idempotency_is_unique_per_submission(monkeypatch) -> None:
    queued = []

    class _Outbox:
        def __init__(self, _connection) -> None:
            pass

        def enqueue_outbound(self, intent) -> None:
            queued.append(intent)

    class _Repository:
        connection = object()

        def get_contract_version(self, **_kwargs):
            return {"original_filename": "vendor.pdf"}

    class _Service:
        repository = _Repository()

    monkeypatch.setattr("contractmate.workers.contract_worker.SlackRepository", _Outbox)
    worker = ContractWorker(settings=Settings(frontend_origin="https://samvid.online"), queue=_FakeQueue(None))
    result = ContractProcessingResult(
        contract_id="contract-1", contract_version_id="version-1",
        status=WorkflowState.REVIEW_READY, message="Review ready.",
    )
    base = dict(
        contract_id="contract-1", contract_version_id="version-1", workspace_id="workspace-1",
        email_thread_id="slack:T:C:1", requested_by="user@example.com", source_channel="slack",
        slack_installation_id="install-1", slack_channel_id="C1", slack_thread_ts="1.0",
    )

    worker._queue_slack_review(
        _Service(), ContractReviewJob(job_id="job-1", source_submission_key="Ev1:F1", **base), result,
    )
    worker._queue_slack_review(
        _Service(), ContractReviewJob(job_id="job-2", source_submission_key="Ev2:F1", **base), result,
    )
    # A crash/retry may republish the same source submission under a new
    # broker job id; its durable Slack response must still deduplicate.
    worker._queue_slack_review(
        _Service(), ContractReviewJob(job_id="job-3", source_submission_key="Ev1:F1", **base), result,
    )

    assert [intent.idempotency_key for intent in queued] == [
        "slack-review:Ev1:F1", "slack-review:Ev2:F1", "slack-review:Ev1:F1",
    ]


def test_ambiguous_duplicate_job_executes_review_and_final_once(monkeypatch) -> None:
    class _ExecutionRepository:
        status = "pending"
        intents = []

        def __init__(self, _connection) -> None:
            pass

        def claim_review_execution(self, **_kwargs):
            if self.status == "completed":
                return SlackLeaseClaim("completed")
            self.__class__.status = "processing"
            return SlackLeaseClaim("claimed", "owner-1")

        def complete_review_execution(self, **_kwargs):
            self.__class__.status = "completed"
            return True

        def renew_review_execution(self, **_kwargs):
            return self.status == "processing"

        def release_review_execution(self, **_kwargs):
            self.__class__.status = "pending"
            return True

        def enqueue_outbound(self, intent):
            self.__class__.intents.append(intent)

    class _Repository:
        connection = object()

        def get_contract_version(self, **_kwargs):
            return {"original_filename": "vendor.pdf"}

    class _Service:
        repository = _Repository()
        reviews = 0

        def review_stored_contract(self, **kwargs):
            self.__class__.reviews += 1
            return ContractProcessingResult(
                contract_id=kwargs["contract_id"], contract_version_id=kwargs["contract_version_id"],
                status=WorkflowState.REVIEW_READY, message="Review ready.",
            )

        def close(self):
            pass

    monkeypatch.setattr("contractmate.workers.contract_worker.SlackRepository", _ExecutionRepository)
    job = ContractReviewJob(
        job_id="stable-job", contract_id="contract-1", contract_version_id="version-1",
        workspace_id="workspace-1", email_thread_id="slack:T:C:1", requested_by="user@example.com",
        source_channel="slack", source_submission_key="Ev1:F1", slack_installation_id="install-1",
        slack_channel_id="C1", slack_thread_ts="1.0",
    )
    first = _FakeDelivery(job)
    second = _FakeDelivery(job)

    ContractWorker(
        settings=Settings(), queue=_FakeQueue(first), processing_service_factory=lambda _settings: _Service(),
        heartbeat_factory=lambda *_args: _NoopHeartbeat(),
    ).run_once()
    ContractWorker(
        settings=Settings(), queue=_FakeQueue(second), processing_service_factory=lambda _settings: _Service(),
        heartbeat_factory=lambda *_args: _NoopHeartbeat(),
    ).run_once()

    assert first.acked and second.acked
    assert _Service.reviews == 1
    assert len(_ExecutionRepository.intents) == 1
    assert _ExecutionRepository.intents[0].idempotency_key == "slack-review:Ev1:F1"


def test_lost_terminal_execution_owner_cannot_mark_failed_or_emit_slack_failure(monkeypatch) -> None:
    class _LostRepository:
        def __init__(self, _connection) -> None:
            pass

        def claim_review_execution(self, **_kwargs):
            return SlackLeaseClaim("claimed", "stale-owner")

        def renew_review_execution(self, **_kwargs):
            return False

    class _Repository:
        connection = object()

    class _Service:
        repository = _Repository()
        marked_failed = False

        def review_stored_contract(self, **_kwargs):
            raise RuntimeError("model failed after lease loss")

        def mark_analysis_failed(self, **_kwargs):
            self.__class__.marked_failed = True

        def close(self):
            pass

    monkeypatch.setattr("contractmate.workers.contract_worker.SlackRepository", _LostRepository)
    job = ContractReviewJob(
        job_id="stable-job", contract_id="contract-1", contract_version_id="version-1",
        workspace_id="workspace-1", email_thread_id="slack:T:C:1", requested_by="user@example.com",
        source_channel="slack", source_submission_key="Ev1:F1", slack_installation_id="install-1",
        slack_channel_id="C1", slack_thread_ts="1.0", attempt=3,
    )
    delivery = _FakeDelivery(job)
    worker = ContractWorker(
        settings=Settings(), queue=_FakeQueue(delivery, max_attempts=3),
        processing_service_factory=lambda _settings: _Service(),
        heartbeat_factory=lambda *_args: _NoopHeartbeat(),
    )

    worker.run_once()

    assert delivery.acked and not delivery.retried
    assert _Service.marked_failed is False


@pytest.mark.parametrize("status", [WorkflowState.OCR_REQUIRED, WorkflowState.PARSE_FAILED])
def test_nonreview_slack_terminal_result_emits_failure_not_completed(monkeypatch, status) -> None:
    intents = []

    class _ExecutionRepository:
        def __init__(self, _connection) -> None:
            pass

        def claim_review_execution(self, **_kwargs):
            return SlackLeaseClaim("claimed", "owner-1")

        def renew_review_execution(self, **_kwargs):
            return True

        def complete_review_execution(self, **_kwargs):
            return True

        def enqueue_outbound(self, intent):
            intents.append(intent)

    class _Repository:
        connection = object()

        def get_contract_version(self, **_kwargs):
            return {"original_filename": "vendor.pdf"}

    class _Service:
        repository = _Repository()

        def review_stored_contract(self, **kwargs):
            return ContractProcessingResult(
                contract_id=kwargs["contract_id"], contract_version_id=kwargs["contract_version_id"],
                status=status, message="Review could not be completed.",
            )

        def close(self):
            pass

    monkeypatch.setattr("contractmate.workers.contract_worker.SlackRepository", _ExecutionRepository)
    job = ContractReviewJob(
        job_id="stable-job", contract_id="contract-1", contract_version_id="version-1",
        workspace_id="workspace-1", email_thread_id="slack:T:C:1", requested_by="user@example.com",
        source_channel="slack", source_submission_key=f"Ev-{status.value}:F1",
        slack_installation_id="install-1", slack_channel_id="C1", slack_thread_ts="1.0",
    )
    delivery = _FakeDelivery(job)

    ContractWorker(
        settings=Settings(), queue=_FakeQueue(delivery), processing_service_factory=lambda _settings: _Service(),
        heartbeat_factory=lambda *_args: _NoopHeartbeat(),
    ).run_once()

    assert delivery.acked
    assert len(intents) == 1
    assert intents[0].message_type == "failure"
    assert "could not complete" in intents[0].text_body


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


class _NoopHeartbeat:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
