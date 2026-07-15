from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from contractmate.settings import Settings


REVIEW_REQUESTED_ROUTING_KEY = "contract.review.requested"
REVIEW_RETRY_ROUTING_KEY = "contract.review.retry"
REVIEW_DEAD_ROUTING_KEY = "contract.review.dead"


@dataclass(frozen=True)
class ContractReviewJob:
    job_id: str
    contract_id: str
    contract_version_id: str
    workspace_id: str
    email_thread_id: str
    requested_by: str
    attempt: int = 1

    def to_message(self) -> dict:
        return {
            "job_id": self.job_id,
            "contract_id": self.contract_id,
            "contract_version_id": self.contract_version_id,
            "workspace_id": self.workspace_id,
            "email_thread_id": self.email_thread_id,
            "requested_by": self.requested_by,
            "attempt": self.attempt,
        }

    @classmethod
    def from_message(cls, message: dict) -> "ContractReviewJob":
        return cls(
            job_id=str(message["job_id"]),
            contract_id=str(message["contract_id"]),
            contract_version_id=str(message["contract_version_id"]),
            workspace_id=str(message["workspace_id"]),
            email_thread_id=str(message["email_thread_id"]),
            requested_by=str(message["requested_by"]),
            attempt=int(message.get("attempt", 1)),
        )


class QueueTopology(BaseModel):
    exchange: str = "contract.events"
    review_queue: str = "contract.review.q"
    retry_queue: str = "contract.review.retry.q"
    dlq: str = "contract.review.dlq"
    retry_ttl_ms: int = Field(default=60_000, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    review_routing_key: str = REVIEW_REQUESTED_ROUTING_KEY
    retry_routing_key: str = REVIEW_RETRY_ROUTING_KEY
    dead_routing_key: str = REVIEW_DEAD_ROUTING_KEY

    @classmethod
    def from_settings(cls, settings: Settings) -> "QueueTopology":
        return cls(
            exchange=settings.rabbitmq_exchange,
            review_queue=settings.rabbitmq_review_queue,
            retry_queue=settings.rabbitmq_retry_queue,
            dlq=settings.rabbitmq_dlq,
            retry_ttl_ms=settings.rabbitmq_retry_ttl_ms,
            max_attempts=settings.rabbitmq_max_attempts,
        )


class ContractQueue(Protocol):
    def enqueue(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
    ) -> ContractReviewJob:
        ...


class InMemoryContractQueue:
    def __init__(self) -> None:
        self._jobs: deque[ContractReviewJob] = deque()

    def enqueue(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
    ) -> ContractReviewJob:
        job = ContractReviewJob(
            job_id=str(uuid4()),
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
        )
        self._jobs.append(job)
        return job

    def receive(self) -> ContractReviewJob | None:
        if not self._jobs:
            return None
        return self._jobs.popleft()


class RabbitMQContractQueue:
    """RabbitMQ adapter for durable contract-review job delivery.

    This adapter is intentionally narrow: queue payloads contain identifiers only,
    never contract text. The consumer side can use manual acknowledgements and
    database transactions around job processing.
    """

    def __init__(self, *, rabbitmq_url: str, topology: QueueTopology) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.topology = topology

    @classmethod
    def from_settings(cls, settings: Settings) -> "RabbitMQContractQueue":
        if not settings.rabbitmq_url:
            raise ValueError("RABBITMQ_URL is required for RabbitMQContractQueue.")
        return cls(
            rabbitmq_url=settings.rabbitmq_url,
            topology=QueueTopology.from_settings(settings),
        )

    def declare_topology(self) -> None:
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
        finally:
            connection.close()

    def enqueue(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
    ) -> ContractReviewJob:
        job = ContractReviewJob(
            job_id=str(uuid4()),
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
        )
        self.publish(job, routing_key=self.topology.review_routing_key)
        return job

    def publish(self, job: ContractReviewJob, *, routing_key: str) -> None:
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.confirm_delivery()
            self._publish_on_channel(channel, job, routing_key=routing_key)
        finally:
            connection.close()

    def receive(self, *, prefetch_count: int = 1) -> "RabbitMQDelivery | None":
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.basic_qos(prefetch_count=prefetch_count)
            method_frame, _, body = channel.basic_get(
                queue=self.topology.review_queue,
                auto_ack=False,
            )
            if method_frame is None:
                connection.close()
                return None
            message = json.loads(body.decode("utf-8"))
            return RabbitMQDelivery(
                queue=self,
                connection=connection,
                channel=channel,
                delivery_tag=method_frame.delivery_tag,
                job=ContractReviewJob.from_message(message),
            )
        except Exception:
            connection.close()
            raise

    def _connection(self):
        pika = self._pika()
        return pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))

    def _declare_topology(self, channel) -> None:
        channel.exchange_declare(exchange=self.topology.exchange, exchange_type="topic", durable=True)
        channel.queue_declare(queue=self.topology.review_queue, durable=True)
        channel.queue_bind(
            queue=self.topology.review_queue,
            exchange=self.topology.exchange,
            routing_key=self.topology.review_routing_key,
        )
        channel.queue_declare(
            queue=self.topology.retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self.topology.retry_ttl_ms,
                "x-dead-letter-exchange": self.topology.exchange,
                "x-dead-letter-routing-key": self.topology.review_routing_key,
            },
        )
        channel.queue_bind(
            queue=self.topology.retry_queue,
            exchange=self.topology.exchange,
            routing_key=self.topology.retry_routing_key,
        )
        channel.queue_declare(queue=self.topology.dlq, durable=True)
        channel.queue_bind(
            queue=self.topology.dlq,
            exchange=self.topology.exchange,
            routing_key=self.topology.dead_routing_key,
        )

    def _publish_on_channel(self, channel, job: ContractReviewJob, *, routing_key: str) -> None:
        pika = self._pika()
        channel.basic_publish(
            exchange=self.topology.exchange,
            routing_key=routing_key,
            body=json.dumps(job.to_message()).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                headers={"job_id": job.job_id, "attempt": job.attempt},
            ),
            mandatory=True,
        )

    def _pika(self):
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install the 'integrations' extra to use RabbitMQ.") from exc
        return pika


@dataclass
class RabbitMQDelivery:
    queue: RabbitMQContractQueue
    connection: object
    channel: object
    delivery_tag: int
    job: ContractReviewJob

    def ack(self) -> None:
        try:
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self.connection.close()

    def retry(self) -> None:
        if self.job.attempt >= self.queue.topology.max_attempts:
            self.dead_letter()
            return
        retry_job = ContractReviewJob(
            job_id=self.job.job_id,
            contract_id=self.job.contract_id,
            contract_version_id=self.job.contract_version_id,
            workspace_id=self.job.workspace_id,
            email_thread_id=self.job.email_thread_id,
            requested_by=self.job.requested_by,
            attempt=self.job.attempt + 1,
        )
        try:
            self.queue._publish_on_channel(
                self.channel,
                retry_job,
                routing_key=self.queue.topology.retry_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self.connection.close()

    def dead_letter(self) -> None:
        try:
            self.queue._publish_on_channel(
                self.channel,
                self.job,
                routing_key=self.queue.topology.dead_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self.connection.close()
