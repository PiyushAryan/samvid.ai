from __future__ import annotations

import logging
from typing import Any, Callable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from contractmate.db.repositories.slack import OutboundSlackItem, SlackRepository
from contractmate.security.slack import SlackTokenCipher


logger = logging.getLogger(__name__)


class OutboundSlackDeliveryService:
    """Deliver Slack intents without ever causing contract analysis to rerun."""

    def __init__(
        self,
        *,
        repository: SlackRepository,
        token_cipher: SlackTokenCipher,
        client_factory: Callable[[str], Any] = lambda token: WebClient(token=token),
        max_attempts: int = 5,
    ) -> None:
        self.repository = repository
        self.token_cipher = token_cipher
        self.client_factory = client_factory
        self.max_attempts = max(max_attempts, 1)

    def drain_once(self, *, limit: int = 25) -> int:
        delivered = 0
        for item in self.repository.claim_due_outbound(limit=limit):
            if self._deliver(item):
                delivered += 1
        return delivered

    def _deliver(self, item: OutboundSlackItem) -> bool:
        installation = self.repository.get_installation(installation_id=item.installation_id)
        if installation is None:
            self.repository.reschedule_outbound(
                outbox_id=item.id,
                lease_token=item.lease_token,
                attempts=item.attempts,
                error="Slack installation is no longer active",
                max_attempts=item.attempts,
            )
            return False
        try:
            token = self.token_cipher.decrypt(installation.encrypted_bot_token)
            response = self.client_factory(token).chat_postMessage(
                channel=item.channel_id,
                thread_ts=item.thread_ts,
                text=item.text_body,
                blocks=item.blocks,
                client_msg_id=item.id,
            )
            provider_ts = response.get("ts") if hasattr(response, "get") else None
            return self.repository.mark_outbound_sent(
                outbox_id=item.id,
                lease_token=item.lease_token,
                provider_message_ts=str(provider_ts) if provider_ts else None,
            )
        except SlackApiError as exc:
            error_code = str(exc.response.get("error", "slack_api_error"))
            if error_code in {"invalid_auth", "account_inactive", "token_revoked"}:
                self.repository.mark_installation_revoked(installation_id=item.installation_id)
                self.repository.reschedule_outbound(
                    outbox_id=item.id,
                    lease_token=item.lease_token,
                    attempts=item.attempts,
                    error=error_code,
                    max_attempts=item.attempts,
                )
                return False
            self.repository.reschedule_outbound(
                outbox_id=item.id,
                lease_token=item.lease_token,
                attempts=item.attempts,
                error=error_code,
                retry_after_seconds=_retry_after(exc),
                max_attempts=self.max_attempts,
            )
            return False
        except Exception as exc:
            logger.warning("Slack outbox item %s failed: %s", item.id, exc)
            self.repository.reschedule_outbound(
                outbox_id=item.id,
                lease_token=item.lease_token,
                attempts=item.attempts,
                error=str(exc),
                max_attempts=self.max_attempts,
            )
            return False


def _retry_after(exc: SlackApiError) -> int | None:
    status = getattr(exc.response, "status_code", None)
    if status != 429:
        return None
    headers = getattr(exc.response, "headers", {}) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return 1
