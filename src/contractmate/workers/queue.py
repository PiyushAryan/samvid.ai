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
    recipient_name: str | None = None
    response_address: str | None = None
    original_subject: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    send_review_email: bool = False
    attempt: int = 1

    def to_message(self) -> dict:
        message = {
            "job_id": self.job_id,
            "contract_id": self.contract_id,
            "contract_version_id": self.contract_version_id,
            "workspace_id": self.workspace_id,
            "email_thread_id": self.email_thread_id,
            "requested_by": self.requested_by,
            "send_review_email": self.send_review_email,
            "attempt": self.attempt,
        }
        message.update(
            {
                key: value
                for key, value in {
                    "recipient_name": self.recipient_name,
                    "response_address": self.response_address,
                    "original_subject": self.original_subject,
                    "in_reply_to": self.in_reply_to,
                    "references": self.references,
                }.items()
                if value is not None
            }
        )
        return message

    @classmethod
    def from_message(cls, message: dict) -> "ContractReviewJob":
        return cls(
            job_id=str(message["job_id"]),
            contract_id=str(message["contract_id"]),
            contract_version_id=str(message["contract_version_id"]),
            workspace_id=str(message["workspace_id"]),
            email_thread_id=str(message["email_thread_id"]),
            requested_by=str(message["requested_by"]),
            recipient_name=str(message["recipient_name"]) if message.get("recipient_name") else None,
            response_address=str(message["response_address"]) if message.get("response_address") else None,
            original_subject=str(message["original_subject"]) if message.get("original_subject") else None,
            in_reply_to=str(message["in_reply_to"]) if message.get("in_reply_to") else None,
            references=str(message["references"]) if message.get("references") else None,
            send_review_email=bool(message.get("send_review_email", False)),
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
        recipient_name: str | None = None,
        response_address: str | None = None,
        original_subject: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        send_review_email: bool = False,
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
        recipient_name: str | None = None,
        response_address: str | None = None,
        original_subject: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        send_review_email: bool = False,
    ) -> ContractReviewJob:
        job = ContractReviewJob(
            job_id=str(uuid4()),
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            recipient_name=recipient_name,
            response_address=response_address,
            original_subject=original_subject,
            in_reply_to=in_reply_to,
            references=references,
            send_review_email=send_review_email,
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

    def __init__(self, *, rabbitmq_url: str, topology: QueueTopology, heartbeat_seconds: int = 600) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.topology = topology
        self.heartbeat_seconds = heartbeat_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "RabbitMQContractQueue":
        if not settings.rabbitmq_url:
            raise ValueError("RABBITMQ_URL is required for RabbitMQContractQueue.")
        return cls(
            rabbitmq_url=settings.rabbitmq_url,
            topology=QueueTopology.from_settings(settings),
            heartbeat_seconds=settings.rabbitmq_heartbeat_seconds,
        )

    def declare_topology(self) -> None:
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
        finally:
            connection.close()

    def check_ready(self) -> None:
        self.declare_topology()

    def enqueue(
        self,
        *,
        contract_id: str,
        contract_version_id: str,
        workspace_id: str,
        email_thread_id: str,
        requested_by: str,
        recipient_name: str | None = None,
        response_address: str | None = None,
        original_subject: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        send_review_email: bool = False,
    ) -> ContractReviewJob:
        job = ContractReviewJob(
            job_id=str(uuid4()),
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            workspace_id=workspace_id,
            email_thread_id=email_thread_id,
            requested_by=requested_by,
            recipient_name=recipient_name,
            response_address=response_address,
            original_subject=original_subject,
            in_reply_to=in_reply_to,
            references=references,
            send_review_email=send_review_email,
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
        parameters = pika.URLParameters(self.rabbitmq_url)
        parameters.heartbeat = self.heartbeat_seconds
        parameters.blocked_connection_timeout = 30
        return pika.BlockingConnection(parameters)

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
            recipient_name=self.job.recipient_name,
            response_address=self.job.response_address,
            original_subject=self.job.original_subject,
            in_reply_to=self.job.in_reply_to,
            references=self.job.references,
            send_review_email=self.job.send_review_email,
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
