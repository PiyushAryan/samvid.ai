from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from contractmate.ai.fireworks import FireworksEmbeddingsClient
from contractmate.db.repositories.knowledge import KnowledgeRepository
from contractmate.db.session import connect, initialize_database
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.services.knowledge_indexing import KnowledgeIndexingService
from contractmate.settings import Settings
from contractmate.workers.queue import RabbitMQKnowledgeQueue


logger = logging.getLogger(__name__)


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
            service = KnowledgeIndexingService(
                embeddings=FireworksEmbeddingsClient(
                    api_key=self.settings.fireworks_api_key or "",
                    model_id=self.settings.embedding_model_id,
                    dimensions=self.settings.embedding_dimensions,
                    base_url=self.settings.fireworks_base_url,
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
        except Exception as exc:
            logger.exception(
                "Knowledge index job %s failed on attempt %s",
                delivery.job.job_id,
                delivery.job.attempt,
            )
            delivery.retry()
        else:
            logger.info(
                "Indexed %s chunks for contract %s",
                result.chunk_count,
                result.contract_id,
            )
            delivery.ack()
        finally:
            if connection is not None:
                connection.close()


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
        raise ValueError("Validated parsed document and review were not found in the expected workspace.")
    parsed_json = row["content_json"]
    review_json = row["review_json"]
    parsed = ParsedDocument.model_validate_json(parsed_json) if isinstance(parsed_json, str) else ParsedDocument.model_validate(parsed_json)
    review = ContractReview.model_validate_json(review_json) if isinstance(review_json, str) else ContractReview.model_validate(review_json)
    return parsed, review
