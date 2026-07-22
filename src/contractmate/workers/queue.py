from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from contractmate.settings import Settings


REVIEW_REQUESTED_ROUTING_KEY = "contract.review.requested"
REVIEW_RETRY_ROUTING_KEY = "contract.review.retry"
REVIEW_DEAD_ROUTING_KEY = "contract.review.dead"
KNOWLEDGE_INDEX_ROUTING_KEY = "contract.knowledge-index.requested"
KNOWLEDGE_INDEX_RETRY_ROUTING_KEY = "contract.knowledge-index.retry"
KNOWLEDGE_INDEX_DEAD_ROUTING_KEY = "contract.knowledge-index.dead"


logger = logging.getLogger(__name__)


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
    processing_run_id: str | None = None
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
                    "processing_run_id": self.processing_run_id,
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
            processing_run_id=str(message["processing_run_id"]) if message.get("processing_run_id") else None,
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


@dataclass(frozen=True)
class KnowledgeIndexJob:
    job_id: str
    contract_id: str
    contract_version_id: str
    workspace_id: str
    attempt: int = 1

    def to_message(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "contract_id": self.contract_id,
            "contract_version_id": self.contract_version_id,
            "workspace_id": self.workspace_id,
            "attempt": self.attempt,
        }

    @classmethod
    def from_message(cls, message: dict[str, object]) -> "KnowledgeIndexJob":
        return cls(
            job_id=str(message["job_id"]),
            contract_id=str(message["contract_id"]),
            contract_version_id=str(message["contract_version_id"]),
            workspace_id=str(message["workspace_id"]),
            attempt=int(message.get("attempt", 1)),
        )


class KnowledgeQueueTopology(BaseModel):
    exchange: str = "contract.events"
    queue: str = "contract.knowledge-index.q"
    retry_queue: str = "contract.knowledge-index.retry.q"
    dlq: str = "contract.knowledge-index.dlq"
    retry_ttl_ms: int = Field(default=60_000, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    routing_key: str = KNOWLEDGE_INDEX_ROUTING_KEY
    retry_routing_key: str = KNOWLEDGE_INDEX_RETRY_ROUTING_KEY
    dead_routing_key: str = KNOWLEDGE_INDEX_DEAD_ROUTING_KEY

    @classmethod
    def from_settings(cls, settings: Settings) -> "KnowledgeQueueTopology":
        return cls(
            exchange=settings.rabbitmq_exchange,
            queue=settings.rabbitmq_knowledge_index_queue,
            retry_queue=settings.rabbitmq_knowledge_index_retry_queue,
            dlq=settings.rabbitmq_knowledge_index_dlq,
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
        processing_run_id: str | None = None,
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
        processing_run_id: str | None = None,
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
            processing_run_id=processing_run_id,
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
        self._consumer_connection = None
        self._consumer_channel = None

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
        processing_run_id: str | None = None,
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
            processing_run_id=processing_run_id,
        )
        self.publish(job, routing_key=self.topology.review_routing_key)
        return job

    def publish(self, job: ContractReviewJob, *, routing_key: str) -> None:
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.confirm_delivery()
            if self._publish_on_channel(channel, job, routing_key=routing_key) is False:
                raise RuntimeError("RabbitMQ did not confirm contract review job publication")
        finally:
            connection.close()

    def receive(self, *, prefetch_count: int = 1) -> "RabbitMQDelivery | None":
        connection, channel = self._ensure_consumer(prefetch_count=prefetch_count)
        try:
            method_frame, _, body = channel.basic_get(
                queue=self.topology.review_queue,
                auto_ack=False,
            )
            if method_frame is None:
                return None
            message = json.loads(body.decode("utf-8"))
            return RabbitMQDelivery(
                queue=self,
                connection=connection,
                channel=channel,
                delivery_tag=method_frame.delivery_tag,
                job=ContractReviewJob.from_message(message),
                close_connection_on_finish=False,
            )
        except Exception:
            self.close_consumer()
            raise

    def consume(
        self,
        on_delivery: Callable[["RabbitMQDelivery"], None],
        *,
        stop_requested: Callable[[], bool] = lambda: False,
        reconnect_delay_seconds: float = 1.0,
    ) -> None:
        """Consume review jobs on one long-lived manual-ack channel.

        A worker processes deliveries synchronously.  The broker's prefetch of one
        therefore keeps at most one unacknowledged review assigned to the worker.
        Connection failures close the channel and retry with bounded backoff.
        """

        delay = max(reconnect_delay_seconds, 0.1)
        while not stop_requested():
            try:
                connection, channel = self._ensure_consumer(prefetch_count=1)

                def _callback(_channel, method, _properties, body) -> None:
                    try:
                        message = json.loads(body.decode("utf-8"))
                        delivery = RabbitMQDelivery(
                            queue=self,
                            connection=connection,
                            channel=channel,
                            delivery_tag=method.delivery_tag,
                            job=ContractReviewJob.from_message(message),
                            close_connection_on_finish=False,
                        )
                        on_delivery(delivery)
                    except Exception:
                        logger.exception("Could not process RabbitMQ review delivery")
                        try:
                            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        except Exception:
                            logger.exception("Could not requeue RabbitMQ review delivery")

                consumer_tag = channel.basic_consume(
                    queue=self.topology.review_queue,
                    on_message_callback=_callback,
                    auto_ack=False,
                )
                logger.info("Consuming contract review jobs from %s", self.topology.review_queue)
                while not stop_requested() and not getattr(connection, "is_closed", False):
                    connection.process_data_events(time_limit=1)
                if not getattr(channel, "is_closed", False):
                    channel.basic_cancel(consumer_tag)
                delay = max(reconnect_delay_seconds, 0.1)
            except KeyboardInterrupt:
                return
            except Exception:
                logger.exception("RabbitMQ review consumer disconnected; reconnecting in %.1fs", delay)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                self.close_consumer()

    def close_consumer(self) -> None:
        connection, self._consumer_connection = self._consumer_connection, None
        self._consumer_channel = None
        if connection is not None and not getattr(connection, "is_closed", False):
            connection.close()

    def _ensure_consumer(self, *, prefetch_count: int) -> tuple[object, object]:
        connection = self._consumer_connection
        channel = self._consumer_channel
        if (
            connection is not None
            and channel is not None
            and not getattr(connection, "is_closed", False)
            and not getattr(channel, "is_closed", False)
        ):
            return connection, channel

        self.close_consumer()
        connection = self._connection(heartbeat_seconds=0)
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.basic_qos(prefetch_count=prefetch_count)
            channel.confirm_delivery()
            setattr(channel, "_contractmate_confirms_enabled", True)
        except Exception:
            connection.close()
            raise
        self._consumer_connection = connection
        self._consumer_channel = channel
        return connection, channel

    def _connection(self, *, heartbeat_seconds: int | None = None):
        pika = self._pika()
        parameters = pika.URLParameters(self.rabbitmq_url)
        # BlockingConnection callbacks run on pika's I/O thread. A review can
        # synchronously wait for OCR or an LLM longer than the configured AMQP
        # heartbeat, and calling process_data_events from another thread is not
        # safe. Consumer connections therefore disable AMQP heartbeats; TCP
        # failures still raise and the consumer reconnect loop handles them.
        parameters.heartbeat = self.heartbeat_seconds if heartbeat_seconds is None else heartbeat_seconds
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
        return channel.basic_publish(
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

    def _publish_confirmed_on_channel(self, channel, job: ContractReviewJob, *, routing_key: str) -> None:
        if not getattr(channel, "_contractmate_confirms_enabled", False):
            channel.confirm_delivery()
            setattr(channel, "_contractmate_confirms_enabled", True)
        published = self._publish_on_channel(channel, job, routing_key=routing_key)
        if published is False:
            raise RuntimeError("RabbitMQ did not confirm republished contract review job")

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
    close_connection_on_finish: bool = True

    def ack(self) -> None:
        try:
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

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
            processing_run_id=self.job.processing_run_id,
            attempt=self.job.attempt + 1,
        )
        try:
            self.queue._publish_confirmed_on_channel(
                self.channel,
                retry_job,
                routing_key=self.queue.topology.retry_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

    def dead_letter(self) -> None:
        try:
            self.queue._publish_confirmed_on_channel(
                self.channel,
                self.job,
                routing_key=self.queue.topology.dead_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

    def _close_connection_if_needed(self) -> None:
        if self.close_connection_on_finish:
            self.connection.close()


class RabbitMQKnowledgeQueue:
    """Durable RabbitMQ adapter for document embedding and indexing jobs."""

    def __init__(self, *, rabbitmq_url: str, topology: KnowledgeQueueTopology, heartbeat_seconds: int = 600) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.topology = topology
        self.heartbeat_seconds = heartbeat_seconds
        self._consumer_connection = None
        self._consumer_channel = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "RabbitMQKnowledgeQueue":
        if not settings.rabbitmq_url:
            raise ValueError("RABBITMQ_URL is required for RabbitMQKnowledgeQueue.")
        return cls(
            rabbitmq_url=settings.rabbitmq_url,
            topology=KnowledgeQueueTopology.from_settings(settings),
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

    def enqueue(self, *, contract_id: str, contract_version_id: str, workspace_id: str) -> KnowledgeIndexJob:
        job = KnowledgeIndexJob(
            job_id=str(uuid4()),
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            workspace_id=workspace_id,
        )
        self.publish(job, routing_key=self.topology.routing_key)
        return job

    def publish(self, job: KnowledgeIndexJob, *, routing_key: str) -> None:
        connection = self._connection()
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.confirm_delivery()
            if self._publish_on_channel(channel, job, routing_key=routing_key) is False:
                raise RuntimeError("RabbitMQ did not confirm knowledge index job publication")
        finally:
            connection.close()

    def receive(self, *, prefetch_count: int = 1) -> "RabbitMQKnowledgeDelivery | None":
        connection, channel = self._ensure_consumer(prefetch_count=prefetch_count)
        try:
            method_frame, _, body = channel.basic_get(queue=self.topology.queue, auto_ack=False)
            if method_frame is None:
                return None
            message = json.loads(body.decode("utf-8"))
            return RabbitMQKnowledgeDelivery(
                queue=self,
                connection=connection,
                channel=channel,
                delivery_tag=method_frame.delivery_tag,
                job=KnowledgeIndexJob.from_message(message),
                close_connection_on_finish=False,
            )
        except Exception:
            self.close_consumer()
            raise

    def consume(
        self,
        on_delivery: Callable[["RabbitMQKnowledgeDelivery"], None],
        *,
        stop_requested: Callable[[], bool] = lambda: False,
        reconnect_delay_seconds: float = 1.0,
    ) -> None:
        delay = max(reconnect_delay_seconds, 0.1)
        while not stop_requested():
            try:
                connection, channel = self._ensure_consumer(prefetch_count=1)

                def _callback(_channel, method, _properties, body) -> None:
                    try:
                        message = json.loads(body.decode("utf-8"))
                        delivery = RabbitMQKnowledgeDelivery(
                            queue=self,
                            connection=connection,
                            channel=channel,
                            delivery_tag=method.delivery_tag,
                            job=KnowledgeIndexJob.from_message(message),
                            close_connection_on_finish=False,
                        )
                        on_delivery(delivery)
                    except Exception:
                        logger.exception("Could not process RabbitMQ knowledge-index delivery")
                        try:
                            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        except Exception:
                            logger.exception("Could not requeue RabbitMQ knowledge-index delivery")

                consumer_tag = channel.basic_consume(
                    queue=self.topology.queue,
                    on_message_callback=_callback,
                    auto_ack=False,
                )
                logger.info("Consuming knowledge index jobs from %s", self.topology.queue)
                while not stop_requested() and not getattr(connection, "is_closed", False):
                    connection.process_data_events(time_limit=1)
                if not getattr(channel, "is_closed", False):
                    channel.basic_cancel(consumer_tag)
                delay = max(reconnect_delay_seconds, 0.1)
            except KeyboardInterrupt:
                return
            except Exception:
                logger.exception("RabbitMQ knowledge consumer disconnected; reconnecting in %.1fs", delay)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                self.close_consumer()

    def close_consumer(self) -> None:
        connection, self._consumer_connection = self._consumer_connection, None
        self._consumer_channel = None
        if connection is not None and not getattr(connection, "is_closed", False):
            connection.close()

    def _ensure_consumer(self, *, prefetch_count: int) -> tuple[object, object]:
        connection = self._consumer_connection
        channel = self._consumer_channel
        if (
            connection is not None
            and channel is not None
            and not getattr(connection, "is_closed", False)
            and not getattr(channel, "is_closed", False)
        ):
            return connection, channel

        self.close_consumer()
        connection = self._connection(heartbeat_seconds=0)
        try:
            channel = connection.channel()
            self._declare_topology(channel)
            channel.basic_qos(prefetch_count=prefetch_count)
            channel.confirm_delivery()
            setattr(channel, "_contractmate_confirms_enabled", True)
        except Exception:
            connection.close()
            raise
        self._consumer_connection = connection
        self._consumer_channel = channel
        return connection, channel

    def _connection(self, *, heartbeat_seconds: int | None = None):
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install the 'rabbitmq' extra to use RabbitMQ.") from exc
        parameters = pika.URLParameters(self.rabbitmq_url)
        parameters.heartbeat = self.heartbeat_seconds if heartbeat_seconds is None else heartbeat_seconds
        parameters.blocked_connection_timeout = 30
        return pika.BlockingConnection(parameters)

    def _declare_topology(self, channel) -> None:
        channel.exchange_declare(exchange=self.topology.exchange, exchange_type="topic", durable=True)
        channel.queue_declare(queue=self.topology.queue, durable=True)
        channel.queue_bind(queue=self.topology.queue, exchange=self.topology.exchange, routing_key=self.topology.routing_key)
        channel.queue_declare(
            queue=self.topology.retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self.topology.retry_ttl_ms,
                "x-dead-letter-exchange": self.topology.exchange,
                "x-dead-letter-routing-key": self.topology.routing_key,
            },
        )
        channel.queue_bind(
            queue=self.topology.retry_queue,
            exchange=self.topology.exchange,
            routing_key=self.topology.retry_routing_key,
        )
        channel.queue_declare(queue=self.topology.dlq, durable=True)
        channel.queue_bind(queue=self.topology.dlq, exchange=self.topology.exchange, routing_key=self.topology.dead_routing_key)

    def _publish_on_channel(self, channel, job: KnowledgeIndexJob, *, routing_key: str):
        try:
            import pika
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install the 'rabbitmq' extra to use RabbitMQ.") from exc
        return channel.basic_publish(
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

    def _publish_confirmed_on_channel(self, channel, job: KnowledgeIndexJob, *, routing_key: str) -> None:
        if not getattr(channel, "_contractmate_confirms_enabled", False):
            channel.confirm_delivery()
            setattr(channel, "_contractmate_confirms_enabled", True)
        published = self._publish_on_channel(channel, job, routing_key=routing_key)
        if published is False:
            raise RuntimeError("RabbitMQ did not confirm republished knowledge index job")


@dataclass
class RabbitMQKnowledgeDelivery:
    queue: RabbitMQKnowledgeQueue
    connection: object
    channel: object
    delivery_tag: int
    job: KnowledgeIndexJob
    close_connection_on_finish: bool = True

    def ack(self) -> None:
        try:
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

    def retry(self) -> None:
        if self.job.attempt >= self.queue.topology.max_attempts:
            self.dead_letter()
            return
        retry_job = KnowledgeIndexJob(
            job_id=self.job.job_id,
            contract_id=self.job.contract_id,
            contract_version_id=self.job.contract_version_id,
            workspace_id=self.job.workspace_id,
            attempt=self.job.attempt + 1,
        )
        try:
            self.queue._publish_confirmed_on_channel(
                self.channel,
                retry_job,
                routing_key=self.queue.topology.retry_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

    def dead_letter(self) -> None:
        try:
            self.queue._publish_confirmed_on_channel(
                self.channel,
                self.job,
                routing_key=self.queue.topology.dead_routing_key,
            )
            self.channel.basic_ack(delivery_tag=self.delivery_tag)
        finally:
            self._close_connection_if_needed()

    def _close_connection_if_needed(self) -> None:
        if self.close_connection_on_finish:
            self.connection.close()
