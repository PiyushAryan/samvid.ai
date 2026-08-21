from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from contractmate.ai.openrouter import OpenRouterEmbeddingsClient
from contractmate.db.repositories.knowledge import KnowledgeRepository
from contractmate.db.repositories.knowledge_outbox import KnowledgeOutboxRepository
from contractmate.db.session import connect, initialize_database
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.services.knowledge_indexing import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_RERANKER_PROVIDER,
    KnowledgeIndexingService,
)
from contractmate.settings import Settings
from contractmate.workers.queue import RabbitMQKnowledgeQueue


logger = logging.getLogger(__name__)


class KnowledgeIndexInputNotFound(ValueError):
    """The contract was removed after its indexing job was published."""


@dataclass
class KnowledgeIndexWorker:
    settings: Settings
    queue: RabbitMQKnowledgeQueue

    @classmethod
    def from_settings(cls, settings: Settings) -> "KnowledgeIndexWorker":
        if settings.contract_processing_mode != "rabbitmq":
            raise ValueError("Set CONTRACT_PROCESSING_MODE=rabbitmq before starting the knowledge index worker.")
        return cls(settings=settings, queue=RabbitMQKnowledgeQueue.from_settings(settings))

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.queue.declare_topology()
        logger.info("Knowledge index worker is consuming queue %s", self.queue.topology.queue)
        consume = getattr(self.queue, "consume", None)
        if callable(consume):
            consume(
                self._process_delivery,
                stop_requested=stop_requested,
                reconnect_delay_seconds=poll_interval_seconds,
            )
            logger.info("Knowledge index worker stopped")
            return

        while not stop_requested():
            try:
                processed = self.run_once()
            except KeyboardInterrupt:
                return
            except Exception:
                logger.exception("Knowledge index worker could not poll RabbitMQ")
                time.sleep(poll_interval_seconds)
                continue
            if not processed:
                time.sleep(poll_interval_seconds)
        logger.info("Knowledge index worker stopped")

    def run_once(self) -> bool:
        delivery = self.queue.receive(prefetch_count=1)
        if delivery is None:
            return False
        self._process_delivery(delivery)
        return True

    def _process_delivery(self, delivery) -> None:
        connection: Any | None = None
        repository: KnowledgeRepository | None = None
        index_id: str | None = None
        try:
            if self.settings.auto_initialize_database:
                initialize_database(self.settings.database_url, schema_database_url=self.settings.database_direct_url)
            connection = connect(self.settings.database_url)
            repository = KnowledgeRepository(connection)
            parsed, review = _load_index_inputs(
                connection,
                workspace_id=delivery.job.workspace_id,
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
            )
            index = repository.create_or_get_index(
                workspace_id=delivery.job.workspace_id,
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
                embedding_provider=DEFAULT_EMBEDDING_PROVIDER,
                embedding_model=self.settings.embedding_model_id,
                reranker_provider=DEFAULT_RERANKER_PROVIDER,
                reranker_model=self.settings.rerank_model_id,
                chunking_version=DEFAULT_CHUNKING_VERSION,
            )
            index_id = index.id
            repository.mark_indexing(workspace_id=delivery.job.workspace_id, index_id=index_id)
            service = KnowledgeIndexingService(
                embeddings=OpenRouterEmbeddingsClient(
                    api_key=self.settings.openrouter_api_key or "",
                    model_id=self.settings.embedding_model_id,
                    dimensions=self.settings.embedding_dimensions,
                    base_url=self.settings.openrouter_base_url,
                    http_referer=self.settings.openrouter_http_referer,
                    app_title=self.settings.openrouter_app_title,
                ),
                backend=repository,
                embedding_model=self.settings.embedding_model_id,
                reranker_model=self.settings.rerank_model_id,
                embedding_dimensions=self.settings.embedding_dimensions,
            )
            result = service.index_contract(
                workspace_id=delivery.job.workspace_id,
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
                parsed_document=parsed,
                review_json=review,
            )
        except KnowledgeIndexInputNotFound:
            logger.info(
                "Knowledge index job %s was cancelled because contract %s no longer exists",
                delivery.job.job_id,
                delivery.job.contract_id,
            )
            delivery.ack()
        except Exception as exc:
            error = _sanitize_index_error(exc, secrets=(self.settings.openrouter_api_key,))
            if repository is not None and index_id is not None:
                repository.mark_failed(
                    workspace_id=delivery.job.workspace_id,
                    index_id=index_id,
                    error_message=error,
                )
            outbox_id = getattr(delivery.job, "outbox_id", None)
            if connection is not None and outbox_id:
                KnowledgeOutboxRepository(connection).record_consumer_failure(
                    outbox_id=outbox_id,
                    error=error,
                    terminal=delivery.job.attempt >= self.settings.rabbitmq_max_attempts,
                )
            logger.exception(
                "Knowledge index job %s failed on attempt %s",
                delivery.job.job_id,
                delivery.job.attempt,
            )
            delivery.retry()
        else:
            outbox_id = getattr(delivery.job, "outbox_id", None)
            if connection is not None and outbox_id:
                KnowledgeOutboxRepository(connection).clear_consumer_error(outbox_id=outbox_id)
            logger.info(
                "Indexed %s chunks for contract %s",
                result.chunk_count,
                result.contract_id,
            )
            delivery.ack()
        finally:
            if connection is not None:
                connection.close()


_BEARER_SECRET_PATTERN = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)(api[-_ ]?key|authorization|token|secret)(\s*[:=]\s*)[^\s,;]+"
)


def _sanitize_index_error(exc: Exception, *, secrets: tuple[str | None, ...] = ()) -> str:
    message = " ".join(str(exc).split())
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    message = _BEARER_SECRET_PATTERN.sub(r"\1[redacted]", message)
    message = _KEY_VALUE_SECRET_PATTERN.sub(r"\1\2[redacted]", message)
    if not message:
        message = "Knowledge indexing failed without an error message."
    return f"{type(exc).__name__}: {message}"[:1000]


def _load_index_inputs(
    connection: Any,
    *,
    workspace_id: str,
    contract_id: str,
    contract_version_id: str,
) -> tuple[ParsedDocument, ContractReview]:
    is_postgres = connection.__class__.__module__.startswith("psycopg")
    query = """
        SELECT pd.content_json, cr.review_json
        FROM contracts c
        JOIN contract_versions cv
          ON cv.contract_id = c.id AND cv.id = ?
        JOIN parsed_documents pd ON pd.contract_version_id = cv.id
        JOIN contract_reviews cr ON cr.contract_version_id = pd.contract_version_id
        WHERE c.workspace_id = ? AND c.id = ?
        LIMIT 1
    """
    row = connection.execute(
        query.replace("?", "%s") if is_postgres else query,
        (contract_version_id, workspace_id, contract_id),
    ).fetchone()
    if row is None:
        raise KnowledgeIndexInputNotFound(
            "Validated parsed document and review were not found in the expected workspace."
        )
    parsed_json = row["content_json"]
    review_json = row["review_json"]
    parsed = ParsedDocument.model_validate_json(parsed_json) if isinstance(parsed_json, str) else ParsedDocument.model_validate(parsed_json)
    review = ContractReview.model_validate_json(review_json) if isinstance(review_json, str) else ContractReview.model_validate(review_json)
    return parsed, review
