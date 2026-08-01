from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from slack_sdk import WebClient

from contractmate.db.repositories.slack import InboundSlackEvent, OutboundSlackIntent, SlackInstallation, SlackRepository
from contractmate.db.repositories.user_accounts import UserAccount, UserAccountRepository
from contractmate.db.session import connect, initialize_database
from contractmate.security.slack import SlackTokenCipher
from contractmate.security.file_validation import validate_uploaded_file
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.services.rate_limiting import UpstashRateLimiter, default_rate_limit_policy
from contractmate.settings import Settings
from contractmate.slack.rendering import receipt_message, rejection_message
from contractmate.workers.queue import RabbitMQContractQueue
from contractmate.workers.review_publish_outbox import SlackReviewPublishDispatcher


logger = logging.getLogger(__name__)
_MAX_ATTACHMENTS = 5
_ALLOWED_SLACK_FILE_HOSTS = frozenset({"files.slack.com", "slack-files.com"})


class SlackFileSubmissionBusy(RuntimeError):
    """Another event delivery still owns at least one attachment lease."""


@dataclass(frozen=True, slots=True)
class SlackMemberIdentity:
    email: str
    display_name: str | None


class SlackIntakeWorker:
    """Turns durable Slack Events API records into ordinary review jobs."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: SlackRepository,
        accounts: UserAccountRepository,
        queue: RabbitMQContractQueue,
        token_cipher: SlackTokenCipher,
        processing_service_factory: Callable[[Settings], ContractProcessingService] = ContractProcessingService.local,
        client_factory: Callable[[str], Any] = lambda token: WebClient(token=token),
        http_client: httpx.Client | None = None,
        rate_limiter: UpstashRateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.accounts = accounts
        self.queue = queue
        self.token_cipher = token_cipher
        self.processing_service_factory = processing_service_factory
        self.client_factory = client_factory
        self.http_client = http_client or httpx.Client(timeout=30, follow_redirects=False)
        self._owns_http_client = http_client is None
        self.rate_limiter = rate_limiter or UpstashRateLimiter(settings)
        self._owns_rate_limiter = rate_limiter is None

    @classmethod
    def from_settings(cls, settings: Settings) -> "SlackIntakeWorker":
        if not settings.slack_enabled:
            raise ValueError("Set SLACK_ENABLED=true before starting the Slack intake worker.")
        if settings.contract_processing_mode != "rabbitmq":
            raise ValueError("Set CONTRACT_PROCESSING_MODE=rabbitmq before starting the Slack intake worker.")
        if settings.auto_initialize_database:
            initialize_database(settings.database_url, schema_database_url=settings.database_direct_url)
        connection = connect(settings.database_url)
        return cls(
            settings=settings,
            repository=SlackRepository(connection),
            accounts=UserAccountRepository(connection),
            queue=RabbitMQContractQueue.from_settings(settings),
            token_cipher=SlackTokenCipher(settings.slack_token_encryption_key or ""),
        )

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.queue.declare_topology()
        interval = max(poll_interval_seconds, 0.1)
        logger.info("Slack intake worker started")
        try:
            while not stop_requested():
                try:
                    handled = self.run_once()
                except KeyboardInterrupt:
                    return
                except Exception:
                    logger.exception("Slack intake worker could not claim events")
                    handled = 0
                if not handled:
                    time.sleep(interval)
        finally:
            self.close()

    def run_once(self, *, limit: int = 10) -> int:
        published = SlackReviewPublishDispatcher(
            repository=self.repository, queue=self.queue,
        ).drain_once(limit=limit)
        events = self.repository.claim_due_events(limit=limit)
        for event in events:
            try:
                status = self._process(event)
            except SlackFileSubmissionBusy:
                self.repository.retry_event_contention(event_id=event.id, lease_token=event.lease_token)
            except Exception as exc:
                logger.exception("Slack event %s failed", event.event_id)
                retry_status = self.repository.retry_event(
                    event_id=event.id, lease_token=event.lease_token, attempts=event.attempts, error=str(exc),
                )
                if retry_status == "failed":
                    try:
                        self._queue_terminal_event_failure(event)
                    except Exception:
                        logger.exception("Could not queue terminal Slack failure for event %s", event.event_id)
            else:
                self.repository.complete_event(event_id=event.id, lease_token=event.lease_token, status=status)
        return len(events) + published

    def _queue_terminal_event_failure(self, event_record: InboundSlackEvent) -> None:
        event = event_record.payload.get("event", event_record.payload)
        if not isinstance(event, dict) or not event.get("channel") or not event.get("ts"):
            return
        installation = self.repository.get_installation_by_team(team_id=event_record.team_id)
        if installation is None:
            return
        self._queue_rejection(
            installation=installation,
            workspace_id=self._installation_workspace(installation),
            channel_id=str(event["channel"]),
            thread_ts=str(event.get("thread_ts") or event["ts"]),
            idempotency_key=f"slack-rejection:{event_record.event_id}:terminal",
            message="Samvid could not process this Slack request after several attempts. Please try again.",
        )

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()
        if self._owns_rate_limiter:
            self.rate_limiter.close()
        self.repository.connection.close()

    def _process(self, event_record: InboundSlackEvent) -> str:
        if self.settings.slack_pilot_team_ids and event_record.team_id not in self.settings.slack_pilot_team_ids:
            return "ignored"
        event = event_record.payload.get("event", event_record.payload)
        if not isinstance(event, dict) or not _is_supported_event(event):
            return "ignored"
        installation = self.repository.get_installation_by_team(team_id=event_record.team_id)
        if installation is None:
            return "ignored"
        token = self.token_cipher.decrypt(installation.encrypted_bot_token)
        client = self.client_factory(token)
        user = self._resolve_user(client, str(event.get("user", "")))
        files = [item for item in event.get("files", []) if isinstance(item, dict)][:_MAX_ATTACHMENTS]
        channel_id = str(event["channel"])
        thread_ts = str(event.get("thread_ts") or event["ts"])
        fallback_workspace = self._installation_workspace(installation)
        if user is None:
            self._queue_rejection(
                installation=installation,
                workspace_id=fallback_workspace,
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:identity",
                message="Only active, native human workspace members with an email address can submit contracts.",
            )
            return "ignored"
        if not files:
            self._queue_rejection(
                installation=installation,
                workspace_id=fallback_workspace,
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:files",
                message="Attach a PDF, DOCX, or plain-text contract to your DM or @mention.",
            )
            return "ignored"

        account = self.accounts.get_by_email(user.email)
        if account is None and not self.repository.consume_unknown_sender_capacity(
            team_id=event_record.team_id,
            slack_user_id=str(event["user"]),
            attachments=len(files),
            event_id=event_record.event_id,
        ):
            self._queue_rejection(
                installation=installation,
                workspace_id=fallback_workspace,
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:bootstrap-limit",
                message="The new-user Slack intake limit has been reached. Please try again later.",
            )
            return "ignored"
        account = account or self.accounts.provision_inbound_user(
            email=user.email,
            display_name=user.display_name,
            source="inbound_slack",
        )
        if account.state not in {"active", "unclaimed"} or not account.personal_workspace_id:
            self._queue_rejection(
                installation=installation,
                workspace_id=fallback_workspace,
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:account",
                message="Your Samvid account cannot currently accept contracts.",
            )
            return "ignored"
        quota = self.rate_limiter.reserve_upload(
            policy=default_rate_limit_policy("review"),
            identifier=account.id,
            pathname=f"slack-event/{event_record.event_id}",
            units=len(files),
        )
        if not quota.allowed:
            self._queue_rejection(
                installation=installation,
                workspace_id=account.personal_workspace_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:review-limit",
                message="Your contract review limit has been reached. Please try again later.",
            )
            return "ignored"

        self.repository.link_user(
            team_id=event_record.team_id,
            slack_user_id=str(event["user"]),
            account_id=account.id,
            email=account.email,
        )
        source_key = f"slack:{event_record.team_id}:{channel_id}:{thread_ts}"
        service = self.processing_service_factory(self.settings)
        busy_submission = False
        try:
            for index, slack_file in enumerate(files):
                file_key = str(slack_file.get("id") or index)
                claim = self.repository.claim_file_submission(event_id=event_record.event_id, file_id=file_key)
                if claim.status == "completed":
                    continue
                if claim.status == "busy":
                    busy_submission = True
                    continue
                assert claim.lease_token and claim.review_job_id
                try:
                    self._process_file(
                        event_record=event_record,
                        installation=installation,
                        client=client,
                        token=token,
                        account=account,
                        service=service,
                        slack_file=slack_file,
                        file_index=index,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        source_key=source_key,
                        review_job_id=claim.review_job_id,
                    )
                except Exception:
                    self.repository.release_file_submission(
                        event_id=event_record.event_id, file_id=file_key, lease_token=claim.lease_token,
                    )
                    raise
                else:
                    if not self.repository.complete_file_submission(
                        event_id=event_record.event_id, file_id=file_key, lease_token=claim.lease_token,
                    ):
                        raise SlackFileSubmissionBusy("Slack attachment lease ownership changed during processing")
        finally:
            service.close()
        if busy_submission:
            raise SlackFileSubmissionBusy("A Slack attachment is still being processed by another event delivery")
        return "processed"

    def _process_file(
        self,
        *,
        event_record: InboundSlackEvent,
        installation: SlackInstallation,
        client: Any,
        token: str,
        account: UserAccount,
        service: ContractProcessingService,
        slack_file: dict[str, Any],
        file_index: int,
        channel_id: str,
        thread_ts: str,
        source_key: str,
        review_job_id: str,
    ) -> None:
        file_key = str(slack_file.get("id") or file_index)
        if not slack_file.get("id"):
            self._queue_rejection(
                installation=installation,
                workspace_id=account.personal_workspace_id or "",
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:{file_key}",
                message="A Slack attachment was missing its file identifier.",
            )
            return
        # Private URLs are intentionally excluded from the durable event row.
        # Resolve the short-lived download target only inside this worker.
        file_response = client.files_info(file=file_key)
        live_file = file_response.get("file", {})
        if not isinstance(live_file, dict):
            raise ValueError("Slack did not return attachment metadata")
        filename = Path(str(live_file.get("name") or slack_file.get("name") or f"contract-{file_index + 1}" )).name
        declared_size = int(live_file.get("size") or slack_file.get("size") or 0)
        if declared_size > self.settings.max_file_size_mb * 1024 * 1024:
            self._queue_rejection(
                installation=installation,
                workspace_id=account.personal_workspace_id or "",
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:{file_key}",
                message=f"{filename} exceeds the {self.settings.max_file_size_mb} MB limit.",
            )
            return
        url = str(live_file.get("url_private_download") or live_file.get("url_private") or "")
        suffix = Path(filename).suffix[:12]
        with NamedTemporaryFile(prefix="samvid-slack-", suffix=suffix, delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self._download(url, path, token=token, max_bytes=self.settings.max_file_size_mb * 1024 * 1024)
            validation = validate_uploaded_file(
                path,
                declared_mime_type=str(live_file.get("mimetype") or slack_file.get("mimetype") or "") or None,
                max_size_mb=self.settings.max_file_size_mb,
            )
            if not validation.ok:
                raise ValueError(validation.message or "file validation failed")
            # Persist the receipt before publishing the review job. This makes
            # thread ordering deterministic even if a review worker is idle and
            # consumes the job immediately.
            text, blocks = receipt_message(filename)
            self.repository.enqueue_outbound(OutboundSlackIntent(
                workspace_id=account.personal_workspace_id or "",
                installation_id=installation.id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                message_type="receipt",
                text_body=text,
                blocks=blocks,
                idempotency_key=f"slack-receipt:{event_record.event_id}:{file_key}",
            ))
            result = service.enqueue_local_file(
                queue=self.queue,
                file_path=path,
                workspace_id=account.personal_workspace_id or "",
                email_thread_id=source_key,
                requested_by=account.email,
                declared_mime_type=str(live_file.get("mimetype") or slack_file.get("mimetype") or "") or None,
                original_filename=filename,
                source_channel="slack",
                slack_installation_id=installation.id,
                slack_channel_id=channel_id,
                slack_thread_ts=thread_ts,
                source_submission_key=f"{event_record.event_id}:{file_key}",
                review_job_id=review_job_id,
            )
            if not result.contract_id:
                self._queue_rejection(
                    installation=installation,
                    workspace_id=account.personal_workspace_id or "",
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    idempotency_key=f"slack-rejection:{event_record.event_id}:{file_key}",
                    message=f"{filename}: {result.message}",
                )
                return
        except (httpx.HTTPError, ValueError) as exc:
            self._queue_rejection(
                installation=installation,
                workspace_id=account.personal_workspace_id or "",
                channel_id=channel_id,
                thread_ts=thread_ts,
                idempotency_key=f"slack-rejection:{event_record.event_id}:{file_key}",
                message=f"{filename} could not be downloaded or validated: {exc}",
            )
        finally:
            path.unlink(missing_ok=True)

    def _download(self, url: str, destination: Path, *, token: str, max_bytes: int) -> None:
        current = url
        for _ in range(4):
            _validate_slack_file_url(current)
            with self.http_client.stream("GET", current, headers={"Authorization": f"Bearer {token}"}) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Slack returned an empty file redirect")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                size = 0
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("file exceeds the configured size limit")
                        output.write(chunk)
                return
        raise ValueError("Slack file download redirected too many times")

    def _resolve_user(self, client: Any, slack_user_id: str) -> SlackMemberIdentity | None:
        if not slack_user_id:
            return None
        response = client.users_info(user=slack_user_id)
        member = response.get("user", {})
        profile = member.get("profile", {}) if isinstance(member, dict) else {}
        email = str(profile.get("email") or "").strip().casefold()
        if (
            not email
            or member.get("deleted")
            or member.get("is_bot")
            or member.get("is_app_user")
            or member.get("is_restricted")
            or member.get("is_ultra_restricted")
            or member.get("is_stranger")
        ):
            return None
        return SlackMemberIdentity(
            email=email,
            display_name=str(profile.get("display_name") or profile.get("real_name") or "").strip() or None,
        )

    def _installation_workspace(self, installation: SlackInstallation) -> str:
        owner = self.accounts.get_by_id(installation.installed_by_account_id)
        return owner.personal_workspace_id if owner and owner.personal_workspace_id else f"slack:{installation.team_id}"

    def _queue_rejection(
        self,
        *,
        installation: SlackInstallation,
        workspace_id: str,
        channel_id: str,
        thread_ts: str,
        idempotency_key: str,
        message: str,
    ) -> None:
        text, blocks = rejection_message(message)
        self.repository.enqueue_outbound(OutboundSlackIntent(
            workspace_id=workspace_id,
            installation_id=installation.id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_type="failure",
            text_body=text,
            blocks=blocks,
            idempotency_key=idempotency_key,
        ))


def _is_supported_event(event: dict[str, Any]) -> bool:
    if event.get("bot_id") or event.get("subtype"):
        return False
    event_type = event.get("type")
    return event_type == "app_mention" or (
        event_type == "message" and event.get("channel_type") == "im"
    )


def _validate_slack_file_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or hostname not in _ALLOWED_SLACK_FILE_HOSTS:
        raise ValueError("file URL is not an approved Slack HTTPS host")
