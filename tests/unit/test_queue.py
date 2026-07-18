from contractmate.settings import Settings
from contractmate.workers.queue import ContractReviewJob, QueueTopology, RabbitMQDelivery


def test_contract_review_job_round_trips_without_contract_text() -> None:
    job = ContractReviewJob(
        job_id="job-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        workspace_id="workspace-1",
        email_thread_id="email-thread-1",
        requested_by="reviewer@example.com",
        send_review_email=True,
        attempt=2,
    )

    message = job.to_message()
    restored = ContractReviewJob.from_message(message)

    assert restored == job
    assert set(message) == {
        "job_id",
        "contract_id",
        "contract_version_id",
        "workspace_id",
        "email_thread_id",
        "requested_by",
        "send_review_email",
        "attempt",
    }


def test_contract_review_job_round_trips_optional_email_thread_metadata() -> None:
    job = ContractReviewJob(
        job_id="job-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        workspace_id="workspace-1",
        email_thread_id="email-thread-1",
        requested_by="sender@example.com",
        recipient_name="Contract Sender",
        response_address="replies@example.com",
        original_subject="Please review",
        in_reply_to="<message@example.com>",
        references="<earlier@example.com> <message@example.com>",
        send_review_email=True,
    )

    assert ContractReviewJob.from_message(job.to_message()) == job


def test_queue_topology_uses_rabbitmq_settings() -> None:
    settings = Settings(
        rabbitmq_exchange="contract.events.test",
        rabbitmq_review_queue="review.q",
        rabbitmq_retry_queue="retry.q",
        rabbitmq_dlq="dead.q",
        rabbitmq_retry_ttl_ms=15_000,
        rabbitmq_max_attempts=5,
    )

    topology = QueueTopology.from_settings(settings)

    assert topology.exchange == "contract.events.test"
    assert topology.review_queue == "review.q"
    assert topology.retry_queue == "retry.q"
    assert topology.dlq == "dead.q"
    assert topology.retry_ttl_ms == 15_000
    assert topology.max_attempts == 5
    assert topology.review_routing_key == "contract.review.requested"


def test_delivery_retry_increments_attempt_and_acks() -> None:
    queue = _FakeQueue(QueueTopology(max_attempts=3))
    channel = _FakeChannel()
    connection = _FakeConnection()
    delivery = RabbitMQDelivery(
        queue=queue,
        connection=connection,
        channel=channel,
        delivery_tag=10,
        job=ContractReviewJob(
            job_id="job-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            workspace_id="workspace-1",
            email_thread_id="email-thread-1",
            requested_by="reviewer@example.com",
            attempt=1,
        ),
    )

    delivery.retry()

    assert queue.published[0][0].attempt == 2
    assert queue.published[0][1] == "contract.review.retry"
    assert channel.acked == [10]
    assert connection.closed


def test_delivery_retry_routes_to_dlq_after_max_attempts() -> None:
    queue = _FakeQueue(QueueTopology(max_attempts=2))
    channel = _FakeChannel()
    delivery = RabbitMQDelivery(
        queue=queue,
        connection=_FakeConnection(),
        channel=channel,
        delivery_tag=10,
        job=ContractReviewJob(
            job_id="job-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            workspace_id="workspace-1",
            email_thread_id="email-thread-1",
            requested_by="reviewer@example.com",
            attempt=2,
        ),
    )

    delivery.retry()

    assert queue.published[0][1] == "contract.review.dead"
    assert channel.acked == [10]


class _FakeQueue:
    def __init__(self, topology: QueueTopology) -> None:
        self.topology = topology
        self.published: list[tuple[ContractReviewJob, str]] = []

    def _publish_on_channel(self, channel, job: ContractReviewJob, *, routing_key: str) -> None:
        self.published.append((job, routing_key))


class _FakeChannel:
    def __init__(self) -> None:
        self.acked: list[int] = []

    def basic_ack(self, *, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True
