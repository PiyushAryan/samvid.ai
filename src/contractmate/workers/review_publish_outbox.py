from __future__ import annotations

import logging

from contractmate.db.repositories.slack import SlackRepository
from contractmate.workers.queue import ContractQueue


logger = logging.getLogger(__name__)


class SlackReviewPublishDispatcher:
    """Publishes durable Slack review envelopes with confirm-safe retries."""

    def __init__(self, *, repository: SlackRepository, queue: ContractQueue) -> None:
        self.repository = repository
        self.queue = queue

    def drain_once(self, *, limit: int = 10) -> int:
        items = self.repository.claim_due_review_jobs(limit=limit)
        for item in items:
            try:
                job = self.queue.enqueue(**item.payload)
                if job.job_id != item.job_id:
                    raise RuntimeError("RabbitMQ returned a different stable review job identifier")
            except Exception as exc:
                # A publisher-confirm failure may still mean RabbitMQ accepted
                # the message. Keep the exact envelope pending; consumer-side
                # submission claims safely absorb a later duplicate publish.
                logger.warning(
                    "Slack review job %s publish was not confirmed: %s",
                    item.job_id,
                    exc,
                )
                self.repository.retry_review_job_publish(
                    submission_key=item.submission_key,
                    lease_token=item.lease_token,
                    attempts=item.attempts,
                    error=str(exc),
                )
            else:
                self.repository.mark_review_job_published(
                    submission_key=item.submission_key,
                    lease_token=item.lease_token,
                )
        return len(items)
