from __future__ import annotations

import logging
import time
from collections.abc import Callable

from contractmate.email.rendering import render_review_email_html, render_review_email_text
from contractmate.db.repositories.outbound_email_outbox import OutboundEmailIntent, OutboundEmailOutboxRepository
from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService
from contractmate.services.knowledge_outbox import KnowledgeOutboxDispatcher
from contractmate.settings import Settings
from contractmate.workers.queue import ContractReviewJob, RabbitMQContractQueue, RabbitMQKnowledgeQueue


logger = logging.getLogger(__name__)


class ContractWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: RabbitMQContractQueue,
        knowledge_queue: RabbitMQKnowledgeQueue | None = None,
        outbox_dispatcher: KnowledgeOutboxDispatcher | None = None,
        processing_service_factory: Callable[[Settings], ContractProcessingService] = ContractProcessingService.local,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.knowledge_queue = knowledge_queue
        self.outbox_dispatcher = outbox_dispatcher
        self.processing_service_factory = processing_service_factory

    @classmethod
    def from_settings(cls, settings: Settings) -> "ContractWorker":
        if settings.contract_processing_mode != "rabbitmq":
            raise ValueError("Set CONTRACT_PROCESSING_MODE=rabbitmq before starting the contract worker.")
        return cls(
            settings=settings,
            queue=RabbitMQContractQueue.from_settings(settings),
        )

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.queue.declare_topology()
        if self.knowledge_queue is not None:
            self.knowledge_queue.declare_topology()
        logger.info("Contract review worker is consuming queue %s", self.queue.topology.review_queue)
        try:
            consume = getattr(self.queue, "consume", None)
            if callable(consume):
                consume(
                    self._process_delivery,
                    stop_requested=stop_requested,
                    reconnect_delay_seconds=poll_interval_seconds,
                )
            else:
                # Retain the one-shot polling path for in-memory queues and tests.
                while not stop_requested():
                    try:
                        processed = self.run_once()
                    except KeyboardInterrupt:
                        return
                    except Exception:
                        logger.exception("Contract worker could not poll RabbitMQ or drain the knowledge outbox")
                        time.sleep(poll_interval_seconds)
                        continue
                    if not processed:
                        time.sleep(poll_interval_seconds)
        finally:
            if self.outbox_dispatcher is not None:
                self.outbox_dispatcher.close()
        logger.info("Contract review worker stopped")

    def run_once(self) -> bool:
        delivery = self.queue.receive(prefetch_count=1)
        if delivery is None:
            return False

        self._process_delivery(delivery)
        return True

    def _process_delivery(self, delivery) -> None:
        service: ContractProcessingService | None = None
        try:
            service = self.processing_service_factory(self.settings)
            result = service.review_stored_contract(
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
                workspace_id=delivery.job.workspace_id,
                processing_run_id=delivery.job.processing_run_id,
            )
            if delivery.job.send_review_email:
                self._queue_review_email(service, delivery.job, result)
        except Exception as exc:
            logger.exception(
                "Contract review job %s failed on attempt %s",
                delivery.job.job_id,
                delivery.job.attempt,
            )
            if service is not None and delivery.job.attempt >= self.queue.topology.max_attempts:
                service.mark_analysis_failed(
                    contract_id=delivery.job.contract_id,
                    workspace_id=delivery.job.workspace_id,
                    error=str(exc),
                    processing_run_id=delivery.job.processing_run_id,
                )
            delivery.retry()
        else:
            delivery.ack()
        finally:
            if service is not None:
                service.close()

    def _drain_knowledge_outbox(self) -> int:
        if self.outbox_dispatcher is None:
            return 0
        return self.outbox_dispatcher.drain_once()

    def _queue_review_email(
        self,
        service: ContractProcessingService,
        job: ContractReviewJob,
        result: ContractProcessingResult,
    ) -> None:
        recipient_address = job.response_address or job.requested_by
        contract_url = _contract_url(self.settings.frontend_origin, job.contract_id)
        text = (
            render_review_email_text(
                result.review,
                recipient_name=job.recipient_name,
                recipient_address=recipient_address,
                contract_url=contract_url,
            )
            if result.review
            else result.message
        )
        html = (
            render_review_email_html(
                result.review,
                recipient_name=job.recipient_name,
                recipient_address=recipient_address,
                contract_url=contract_url,
            )
            if result.review
            else None
        )
        OutboundEmailOutboxRepository(service.repository.connection).enqueue(
            OutboundEmailIntent(
                workspace_id=job.workspace_id,
                contract_id=job.contract_id,
                contract_version_id=job.contract_version_id,
                thread_key=job.email_thread_id,
                message_type="review",
                to_address=recipient_address,
                from_address=self.settings.email_from_address,
                subject=_reply_subject(job.original_subject),
                text_body=text,
                html_body=html,
                in_reply_to=job.in_reply_to,
                references=job.references,
                idempotency_key=f"review:{job.job_id}",
            )
        )


def _reply_subject(original_subject: str | None) -> str:
    subject = (original_subject or "Contract review").strip()
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


def _contract_url(frontend_origin: str, contract_id: str) -> str:
    return f"{frontend_origin.rstrip('/')}/contracts/{contract_id}"
