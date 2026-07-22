from __future__ import annotations

import logging
import time
from collections.abc import Callable

from contractmate.db.repositories.outbound_email_outbox import OutboundEmailOutboxRepository
from contractmate.db.session import connect, initialize_database
from contractmate.email.interface import EmailSender
from contractmate.services.knowledge_outbox import KnowledgeOutboxDispatcher
from contractmate.services.outbound_email_delivery import OutboundEmailDeliveryService
from contractmate.settings import Settings
from contractmate.workers.queue import RabbitMQKnowledgeQueue


logger = logging.getLogger(__name__)


class DeliveryWorker:
    """Delivers durable email and knowledge-index outbox intents.

    Review workers only persist their durable results. This worker handles the
    retryable network work afterwards, so a transient email provider failure can
    never trigger a second OCR or LLM review.
    """

    def __init__(
        self,
        *,
        email_delivery: OutboundEmailDeliveryService,
        knowledge_dispatcher: KnowledgeOutboxDispatcher,
    ) -> None:
        self.email_delivery = email_delivery
        self.knowledge_dispatcher = knowledge_dispatcher

    @classmethod
    def from_settings(cls, settings: Settings) -> "DeliveryWorker":
        if settings.contract_processing_mode != "rabbitmq":
            raise ValueError("Set CONTRACT_PROCESSING_MODE=rabbitmq before starting the delivery worker.")
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)

        connection = connect(settings.database_url)
        knowledge_queue = RabbitMQKnowledgeQueue.from_settings(settings)
        return cls(
            email_delivery=OutboundEmailDeliveryService(
                repository=OutboundEmailOutboxRepository(connection),
                sender=EmailSender(settings),
                max_attempts=max(settings.rabbitmq_max_attempts, 3),
                base_backoff_seconds=max(settings.rabbitmq_retry_ttl_ms // 1000, 1),
            ),
            knowledge_dispatcher=KnowledgeOutboxDispatcher.from_settings(
                settings=settings,
                publisher=knowledge_queue,
            ),
        )

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        interval = max(poll_interval_seconds, 0.1)
        logger.info("Samvid delivery worker started")
        try:
            while not stop_requested():
                try:
                    delivered = self.run_once()
                except KeyboardInterrupt:
                    return
                except Exception:
                    logger.exception("Samvid delivery worker could not drain outboxes")
                    delivered = 0
                if not delivered:
                    time.sleep(interval)
        finally:
            self.close()

    def run_once(self) -> int:
        published = self.knowledge_dispatcher.drain_once()
        sent = self.email_delivery.drain_once()
        return published + sent

    def close(self) -> None:
        self.knowledge_dispatcher.close()
        self.email_delivery.repository.connection.close()
