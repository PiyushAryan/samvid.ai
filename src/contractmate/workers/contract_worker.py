from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Event, Thread

from contractmate.email.rendering import render_review_email_html, render_review_email_text
from contractmate.db.repositories.outbound_email_outbox import OutboundEmailIntent, OutboundEmailOutboxRepository
from contractmate.db.repositories.slack import OutboundSlackIntent, SlackRepository
from contractmate.db.session import connect
from contractmate.services.contract_processing import ContractProcessingResult, ContractProcessingService
from contractmate.services.knowledge_outbox import KnowledgeOutboxDispatcher
from contractmate.settings import Settings
from contractmate.slack.rendering import failure_message, review_message
from contractmate.workers.queue import ContractReviewJob, RabbitMQContractQueue, RabbitMQKnowledgeQueue
from contractmate.workflows.states import WorkflowState


logger = logging.getLogger(__name__)


class SlackExecutionLeaseHeartbeat:
    def __init__(self, settings: Settings, submission_key: str, lease_token: str, *, lease_seconds: int = 900) -> None:
        self.settings = settings
        self.submission_key = submission_key
        self.lease_token = lease_token
        self.lease_seconds = lease_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._thread = Thread(target=self._run, name="slack-review-lease-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = max(min(self.lease_seconds // 3, 60), 1)
        while not self._stop.wait(interval):
            connection = None
            try:
                connection = connect(self.settings.database_url)
                repository = SlackRepository(connection)
                if not repository.renew_review_execution(
                    submission_key=self.submission_key,
                    lease_token=self.lease_token,
                    lease_seconds=self.lease_seconds,
                ):
                    return
            except Exception:
                logger.exception("Slack review lease heartbeat failed")
            finally:
                if connection is not None:
                    connection.close()


class ContractWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: RabbitMQContractQueue,
        knowledge_queue: RabbitMQKnowledgeQueue | None = None,
        outbox_dispatcher: KnowledgeOutboxDispatcher | None = None,
        processing_service_factory: Callable[[Settings], ContractProcessingService] = ContractProcessingService.local,
        heartbeat_factory: Callable[[Settings, str, str], SlackExecutionLeaseHeartbeat] = SlackExecutionLeaseHeartbeat,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.knowledge_queue = knowledge_queue
        self.outbox_dispatcher = outbox_dispatcher
        self.processing_service_factory = processing_service_factory
        self.heartbeat_factory = heartbeat_factory

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
        slack_execution: tuple[SlackRepository, str] | None = None
        heartbeat: SlackExecutionLeaseHeartbeat | None = None
        try:
            service = self.processing_service_factory(self.settings)
            if delivery.job.source_channel == "slack" and delivery.job.source_submission_key:
                execution_repository = SlackRepository(service.repository.connection)
                claim = execution_repository.claim_review_execution(
                    submission_key=delivery.job.source_submission_key,
                )
                if claim.status == "completed":
                    delivery.ack()
                    return
                if claim.status == "busy":
                    retry_contention = getattr(delivery, "retry_contention", delivery.retry)
                    retry_contention()
                    return
                assert claim.lease_token
                slack_execution = (execution_repository, claim.lease_token)
                heartbeat = self.heartbeat_factory(
                    self.settings, delivery.job.source_submission_key, claim.lease_token,
                )
                heartbeat.start()
            result = service.review_stored_contract(
                contract_id=delivery.job.contract_id,
                contract_version_id=delivery.job.contract_version_id,
                workspace_id=delivery.job.workspace_id,
                processing_run_id=delivery.job.processing_run_id,
            )
            if delivery.job.send_review_email:
                self._queue_review_email(service, delivery.job, result)
            if delivery.job.source_channel == "slack":
                if slack_execution and not slack_execution[0].renew_review_execution(
                    submission_key=delivery.job.source_submission_key or "",
                    lease_token=slack_execution[1],
                ):
                    raise RuntimeError("Slack review execution lease ownership changed")
                if result.status is WorkflowState.REVIEW_READY:
                    self._queue_slack_review(service, delivery.job, result)
                else:
                    self._queue_slack_failure(service, delivery.job)
            if slack_execution and not slack_execution[0].complete_review_execution(
                submission_key=delivery.job.source_submission_key or "",
                lease_token=slack_execution[1],
            ):
                raise RuntimeError("Slack review execution lease ownership changed")
        except Exception as exc:
            logger.exception(
                "Contract review job %s failed on attempt %s",
                delivery.job.job_id,
                delivery.job.attempt,
            )
            if slack_execution and not slack_execution[0].renew_review_execution(
                submission_key=delivery.job.source_submission_key or "",
                lease_token=slack_execution[1],
            ):
                # A newer owner is responsible for contract state and Slack
                # delivery. This stale duplicate must not mutate either.
                delivery.ack()
                return
            if service is not None and delivery.job.attempt >= self.queue.topology.max_attempts:
                service.mark_analysis_failed(
                    contract_id=delivery.job.contract_id,
                    workspace_id=delivery.job.workspace_id,
                    error=str(exc),
                    processing_run_id=delivery.job.processing_run_id,
                )
                if delivery.job.source_channel == "slack":
                    self._queue_slack_failure(service, delivery.job)
                if slack_execution:
                    slack_execution[0].complete_review_execution(
                        submission_key=delivery.job.source_submission_key or "",
                        lease_token=slack_execution[1],
                    )
            elif slack_execution:
                slack_execution[0].release_review_execution(
                    submission_key=delivery.job.source_submission_key or "",
                    lease_token=slack_execution[1],
                )
            delivery.retry()
        else:
            delivery.ack()
        finally:
            if heartbeat is not None:
                heartbeat.stop()
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

    def _queue_slack_review(
        self,
        service: ContractProcessingService,
        job: ContractReviewJob,
        result: ContractProcessingResult,
    ) -> None:
        if not job.slack_installation_id or not job.slack_channel_id or not job.slack_thread_ts:
            raise ValueError("Slack review job is missing its reply target")
        row = service.repository.get_contract_version(
            contract_id=job.contract_id,
            contract_version_id=job.contract_version_id,
        )
        filename = str(row["original_filename"]) if row else "contract"
        contract_url = _contract_url(self.settings.frontend_origin, job.contract_id)
        text, blocks = review_message(
            result.review,
            filename=filename,
            contract_url=contract_url,
            fallback_message=result.message,
        )
        SlackRepository(service.repository.connection).enqueue_outbound(OutboundSlackIntent(
            workspace_id=job.workspace_id,
            installation_id=job.slack_installation_id,
            channel_id=job.slack_channel_id,
            thread_ts=job.slack_thread_ts,
            message_type="review",
            text_body=text,
            blocks=blocks,
            contract_id=job.contract_id,
            contract_version_id=job.contract_version_id,
            idempotency_key=f"slack-review:{job.source_submission_key or job.job_id}",
        ))

    def _queue_slack_failure(self, service: ContractProcessingService, job: ContractReviewJob) -> None:
        if not job.slack_installation_id or not job.slack_channel_id or not job.slack_thread_ts:
            return
        row = service.repository.get_contract_version(
            contract_id=job.contract_id,
            contract_version_id=job.contract_version_id,
        )
        filename = str(row["original_filename"]) if row else "contract"
        text, blocks = failure_message(filename)
        SlackRepository(service.repository.connection).enqueue_outbound(OutboundSlackIntent(
            workspace_id=job.workspace_id,
            installation_id=job.slack_installation_id,
            channel_id=job.slack_channel_id,
            thread_ts=job.slack_thread_ts,
            message_type="failure",
            text_body=text,
            blocks=blocks,
            contract_id=job.contract_id,
            contract_version_id=job.contract_version_id,
            idempotency_key=f"slack-failure:{job.source_submission_key or job.job_id}",
        ))


def _reply_subject(original_subject: str | None) -> str:
    subject = (original_subject or "Contract review").strip()
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


def _contract_url(frontend_origin: str, contract_id: str) -> str:
    return f"{frontend_origin.rstrip('/')}/contracts/{contract_id}"
