import pytest

from contractmate.settings import Settings
import json
from types import SimpleNamespace

from contractmate.workers.queue import (
    ContractReviewJob,
    KnowledgeIndexJob,
    KnowledgeQueueTopology,
    QueueTopology,
    RabbitMQContractQueue,
    RabbitMQDelivery,
    RabbitMQKnowledgeQueue,
)


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


def test_delivery_does_not_ack_when_confirmed_republish_fails() -> None:
    queue = _FakeQueue(QueueTopology(max_attempts=3), publish_error=RuntimeError("publish not confirmed"))
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
        ),
    )

    with pytest.raises(RuntimeError, match="publish not confirmed"):
        delivery.retry()

    assert channel.acked == []


def test_contract_consumer_disables_heartbeat_for_synchronous_work(monkeypatch) -> None:
    queue = RabbitMQContractQueue(rabbitmq_url="amqps://example", topology=QueueTopology())
    connection = _ConsumerConnection([])
    heartbeat_values: list[int | None] = []
    monkeypatch.setattr(
        queue,
        "_connection",
        lambda *, heartbeat_seconds=None: heartbeat_values.append(heartbeat_seconds) or connection,
    )
    monkeypatch.setattr(queue, "_declare_topology", lambda _channel: None)

    queue._ensure_consumer(prefetch_count=1)

    assert heartbeat_values == [0]


def test_contract_queue_reuses_its_consumer_connection_for_one_shot_receives(monkeypatch) -> None:
    queue = RabbitMQContractQueue(rabbitmq_url="amqps://example", topology=QueueTopology())
    connection = _ConsumerConnection(
        [
            _encoded_review_job(),
            None,
        ]
    )
    connections = []
    monkeypatch.setattr(queue, "_connection", lambda **_kwargs: connections.append(connection) or connection)
    monkeypatch.setattr(queue, "_declare_topology", lambda _channel: None)

    first = queue.receive(prefetch_count=1)
    assert first is not None
    first.ack()
    assert queue.receive(prefetch_count=1) is None

    assert connections == [connection]
    assert connection.channel_value.qos == [1]
    assert connection.channel_value.acked == [1]
    assert not connection.closed

    queue.close_consumer()
    assert connection.closed


def test_contract_queue_consumes_with_manual_ack_and_prefetch_one(monkeypatch) -> None:
    queue = RabbitMQContractQueue(rabbitmq_url="amqps://example", topology=QueueTopology())
    connection = _ConsumerConnection([_encoded_review_job()])
    monkeypatch.setattr(queue, "_connection", lambda **_kwargs: connection)
    monkeypatch.setattr(queue, "_declare_topology", lambda _channel: None)
    processed: list[str] = []
    stop = {"requested": False}

    def handle(delivery: RabbitMQDelivery) -> None:
        processed.append(delivery.job.job_id)
        delivery.ack()
        stop["requested"] = True

    queue.consume(handle, stop_requested=lambda: stop["requested"])

    assert processed == ["job-1"]
    assert connection.channel_value.qos == [1]
    assert connection.channel_value.acked == [1]
    assert connection.channel_value.cancelled == ["consumer-1"]
    assert connection.closed


def test_knowledge_queue_consumes_with_manual_ack_and_prefetch_one(monkeypatch) -> None:
    queue = RabbitMQKnowledgeQueue(rabbitmq_url="amqps://example", topology=KnowledgeQueueTopology())
    connection = _ConsumerConnection(
        [
            json.dumps(
                KnowledgeIndexJob(
                    job_id="knowledge-1",
                    contract_id="contract-1",
                    contract_version_id="version-1",
                    workspace_id="workspace-1",
                ).to_message()
            ).encode("utf-8")
        ]
    )
    monkeypatch.setattr(queue, "_connection", lambda **_kwargs: connection)
    monkeypatch.setattr(queue, "_declare_topology", lambda _channel: None)
    processed: list[str] = []
    stop = {"requested": False}

    def handle(delivery) -> None:
        processed.append(delivery.job.job_id)
        delivery.ack()
        stop["requested"] = True

    queue.consume(handle, stop_requested=lambda: stop["requested"])

    assert processed == ["knowledge-1"]
    assert connection.channel_value.qos == [1]
    assert connection.channel_value.acked == [1]
    assert connection.closed


class _FakeQueue:
    def __init__(self, topology: QueueTopology, *, publish_error: Exception | None = None) -> None:
        self.topology = topology
        self.publish_error = publish_error
        self.published: list[tuple[ContractReviewJob, str]] = []

    def _publish_on_channel(self, channel, job: ContractReviewJob, *, routing_key: str) -> None:
        self.published.append((job, routing_key))

    def _publish_confirmed_on_channel(self, channel, job: ContractReviewJob, *, routing_key: str) -> None:
        channel.confirm_delivery()
        if self.publish_error is not None:
            raise self.publish_error
        self._publish_on_channel(channel, job, routing_key=routing_key)


class _FakeChannel:
    def __init__(self) -> None:
        self.acked: list[int] = []
        self.confirmed = 0

    def confirm_delivery(self) -> None:
        self.confirmed += 1

    def basic_ack(self, *, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _encoded_review_job() -> bytes:
    return json.dumps(
        ContractReviewJob(
            job_id="job-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            workspace_id="workspace-1",
            email_thread_id="email-thread-1",
            requested_by="reviewer@example.com",
        ).to_message()
    ).encode("utf-8")


class _ConsumerConnection:
    def __init__(self, messages: list[bytes | None]) -> None:
        self.messages = messages
        self.closed = False
        self.is_closed = False
        self.channel_value = _ConsumerChannel(self)

    def channel(self) -> "_ConsumerChannel":
        return self.channel_value

    def process_data_events(self, *, time_limit: float) -> None:
        self.channel_value.deliver_next()

    def close(self) -> None:
        self.closed = True
        self.is_closed = True


class _ConsumerChannel:
    def __init__(self, connection: _ConsumerConnection) -> None:
        self.connection = connection
        self.is_closed = False
        self.qos: list[int] = []
        self.acked: list[int] = []
        self.cancelled: list[str] = []
        self._callback = None
        self._next_tag = 1

    def basic_qos(self, *, prefetch_count: int) -> None:
        self.qos.append(prefetch_count)

    def confirm_delivery(self) -> None:
        return None

    def basic_get(self, *, queue: str, auto_ack: bool):
        body = self.connection.messages.pop(0) if self.connection.messages else None
        if body is None:
            return None, None, None
        tag = self._next_tag
        self._next_tag += 1
        return SimpleNamespace(delivery_tag=tag), None, body

    def basic_consume(self, *, queue: str, on_message_callback, auto_ack: bool) -> str:
        self._callback = on_message_callback
        return "consumer-1"

    def basic_cancel(self, consumer_tag: str) -> None:
        self.cancelled.append(consumer_tag)

    def basic_ack(self, *, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)

    def deliver_next(self) -> None:
        if self._callback is None:
            return
        body = self.connection.messages.pop(0) if self.connection.messages else None
        if body is None:
            return
        tag = self._next_tag
        self._next_tag += 1
        self._callback(self, SimpleNamespace(delivery_tag=tag), None, body)
