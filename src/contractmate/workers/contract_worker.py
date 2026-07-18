from __future__ import annotations

import logging
import time
from collections.abc import Callable

from contractmate.email.interface import EmailSender
from contractmate.email.messages import OutboundEmailMessage
from contractmate.email.rendering import render_review_email_html, render_review_email_text
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

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.queue.declare_topology()
        logger.info("Contract review worker is polling queue %s", self.queue.topology.review_queue)
        while not stop_requested():
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
        logger.info("Contract review worker stopped")

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
        EmailSender(self.settings).send(
            OutboundEmailMessage(
                to_address=recipient_address,
                from_address=self.settings.email_from_address,
                subject=_reply_subject(job.original_subject),
                text=text,
                html=html,
                in_reply_to=job.in_reply_to,
                references=job.references,
            )
        )


def _reply_subject(original_subject: str | None) -> str:
    subject = (original_subject or "Contract review").strip()
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


def _contract_url(frontend_origin: str, contract_id: str) -> str:
    return f"{frontend_origin.rstrip('/')}/contracts/{contract_id}"
