from __future__ import annotations

import logging
import time
from collections.abc import Callable

from contractmate.email.interface import EmailSender
from contractmate.email.messages import OutboundEmailMessage
from contractmate.email.rendering import render_review_email_text
from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService
from contractmate.settings import Settings
from contractmate.workers.queue import ContractReviewJob, RabbitMQContractQueue


logger = logging.getLogger(__name__)


class ContractWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: RabbitMQContractQueue,
        processing_service_factory: Callable[[Settings], ContractProcessingService] = ContractProcessingService.local,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.processing_service_factory = processing_service_factory

    @classmethod
    def from_settings(cls, settings: Settings) -> "ContractWorker":
        if settings.contract_processing_mode != "rabbitmq":
            raise ValueError("Set CONTRACT_PROCESSING_MODE=rabbitmq before starting the contract worker.")
        return cls(settings=settings, queue=RabbitMQContractQueue.from_settings(settings))

    def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        self.queue.declare_topology()
        logger.info("Contract review worker is polling queue %s", self.queue.topology.review_queue)
        while True:
            try:
                processed = self.run_once()
            except KeyboardInterrupt:
                return
            except Exception:
                logger.exception("Contract worker could not poll RabbitMQ")
                time.sleep(poll_interval_seconds)
                continue
            if not processed:
                time.sleep(poll_interval_seconds)

    def run_once(self) -> bool:
        delivery = self.queue.receive(prefetch_count=1)
        if delivery is None:
            return False

        service: ContractProcessingService | None = None
        try:
            service = self.processing_service_factory(self.settings)
            result = service.review_stored_contract(
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
                workspace_id=delivery.job.workspace_id,
            )
            if delivery.job.send_review_email:
                self._send_review_email(delivery.job, result)
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
                )
            delivery.retry()
        else:
            delivery.ack()
        finally:
            if service is not None:
                service.close()
        return True

    def _send_review_email(self, job: ContractReviewJob, result: ContractProcessingResult) -> None:
        text = render_review_email_text(result.review) if result.review else result.message
        EmailSender(self.settings).send(
            OutboundEmailMessage(
                to_address=job.requested_by,
                from_address=self.settings.email_from_address,
                subject="Samvid contract review",
                text=text,
            )
        )
