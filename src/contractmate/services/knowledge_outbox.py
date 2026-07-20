from __future__ import annotations

import logging
from typing import Protocol

from contractmate.db.repositories.knowledge_outbox import KnowledgeOutboxRepository
from contractmate.db.session import connect, initialize_database
from contractmate.settings import Settings


logger = logging.getLogger(__name__)


class KnowledgeJobPublisher(Protocol):
    def enqueue(self, *, contract_id: str, contract_version_id: str, workspace_id: str): ...


class KnowledgeOutboxDispatcher:
    def __init__(
        self,
        *,
        repository: KnowledgeOutboxRepository,
        publisher: KnowledgeJobPublisher,
        max_attempts: int = 10,
        base_backoff_seconds: int = 30,
        lease_seconds: int = 120,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.max_attempts = max(max_attempts, 1)
        self.base_backoff_seconds = max(base_backoff_seconds, 1)
        self.lease_seconds = max(lease_seconds, 1)

    @classmethod
    def from_settings(cls, *, settings: Settings, publisher: KnowledgeJobPublisher) -> "KnowledgeOutboxDispatcher":
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)
        connection = connect(settings.database_url)
        return cls(
            repository=KnowledgeOutboxRepository(connection),
            publisher=publisher,
            max_attempts=max(settings.rabbitmq_max_attempts, 3),
            base_backoff_seconds=max(settings.rabbitmq_retry_ttl_ms // 1000, 1),
        )

    def drain_once(self, *, limit: int = 25) -> int:
        published = 0
        items = self.repository.claim_due(limit=limit, lease_seconds=self.lease_seconds)
        for item in items:
            try:
                job = self.publisher.enqueue(
                    contract_id=item.contract_id,
                    contract_version_id=item.contract_version_id,
                    workspace_id=item.workspace_id,
                )
            except Exception as exc:
                logger.exception(
                    "Knowledge outbox delivery %s failed on attempt %s",
                    item.id,
                    item.attempts,
                )
                self.repository.reschedule(
                    outbox_id=item.id,
                    attempts=item.attempts,
                    error=str(exc),
                    max_attempts=self.max_attempts,
                    base_backoff_seconds=self.base_backoff_seconds,
                )
                continue
            self.repository.mark_published(outbox_id=item.id)
            published += 1
            logger.info(
                "Published knowledge indexing job %s from outbox %s for contract %s",
                job.job_id,
                item.id,
                item.contract_id,
            )
        return published

    def close(self) -> None:
        self.repository.connection.close()
