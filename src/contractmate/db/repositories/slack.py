from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Literal
from uuid import uuid4


SlackEventStatus = Literal["pending", "processing", "processed", "ignored", "failed"]
SlackOutboxStatus = Literal["pending", "sending", "sent", "failed"]


class SlackInstallationConflictError(ValueError):
    """Raised when a Slack workspace is already owned by another Samvid account."""


@dataclass(frozen=True)
class SlackInstallation:
    id: str
    team_id: str
    team_name: str | None
    bot_user_id: str | None
    encrypted_bot_token: str
    installed_by_account_id: str
    status: str
    created_at: Any


@dataclass(frozen=True)
class InboundSlackEvent:
    id: str
    event_id: str
    team_id: str
    event_type: str
    payload: dict[str, Any]
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class OutboundSlackIntent:
    workspace_id: str
    installation_id: str
    channel_id: str
    thread_ts: str
    message_type: Literal["receipt", "review", "failure"]
    text_body: str
    idempotency_key: str
    contract_id: str | None = None
    contract_version_id: str | None = None
    blocks: list[dict[str, Any]] | None = None
    thread_position: int | None = None


@dataclass(frozen=True)
class OutboundSlackItem:
    id: str
    installation_id: str
    channel_id: str
    thread_ts: str
    message_type: str
    text_body: str
    blocks: list[dict[str, Any]] | None
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class SlackLeaseClaim:
    status: Literal["claimed", "busy", "completed"]
    lease_token: str | None = None
    review_job_id: str | None = None


@dataclass(frozen=True)
class SlackReviewJobOutboxItem:
    submission_key: str
    job_id: str
    payload: dict[str, Any]
    attempts: int
    lease_token: str


class SlackRepository:
    """Durable Slack installation, event, identity, and delivery storage."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_oauth_state(self, *, account_id: str, raw_state: str, ttl_seconds: int = 600) -> None:
        digest = _digest(raw_state)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=max(ttl_seconds, 60))
        with self._transaction(immediate=not self.is_postgres):
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO slack_oauth_states(state_hash, account_id, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(state_hash) DO NOTHING
                    """
                ),
                (digest, account_id, self._timestamp(expiry)),
            )

    def consume_oauth_state(self, *, raw_state: str) -> str | None:
        digest = _digest(raw_state)
        with self._transaction(immediate=not self.is_postgres):
            row = self.connection.execute(
                self._sql("SELECT account_id, expires_at, consumed_at FROM slack_oauth_states WHERE state_hash = ?"),
                (digest,),
            ).fetchone()
            if row is None or row["consumed_at"] is not None or _as_utc(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            updated = self.connection.execute(
                self._sql("UPDATE slack_oauth_states SET consumed_at = CURRENT_TIMESTAMP WHERE state_hash = ? AND consumed_at IS NULL"),
                (digest,),
            )
            return str(row["account_id"]) if updated.rowcount == 1 else None

    def upsert_installation(
        self,
        *,
        team_id: str,
        team_name: str | None,
        bot_user_id: str | None,
        encrypted_bot_token: str,
        installed_by_account_id: str,
    ) -> SlackInstallation:
        installation_id = str(uuid4())
        with self._transaction(immediate=not self.is_postgres):
            existing = self.connection.execute(
                self._sql("SELECT installed_by_account_id FROM slack_installations WHERE team_id = ?"),
                (team_id,),
            ).fetchone()
            if existing is not None and str(existing["installed_by_account_id"]) != installed_by_account_id:
                raise SlackInstallationConflictError("Slack workspace is already connected to another Samvid account")
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO slack_installations(
                        id, team_id, team_name, bot_user_id, encrypted_bot_token, installed_by_account_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active')
                    ON CONFLICT(team_id) DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        bot_user_id = EXCLUDED.bot_user_id,
                        encrypted_bot_token = EXCLUDED.encrypted_bot_token,
                        status = 'active', updated_at = CURRENT_TIMESTAMP
                    """
                ),
                (installation_id, team_id, team_name, bot_user_id, encrypted_bot_token, installed_by_account_id),
            )
        installation = self.get_installation_by_team(team_id=team_id)
        if installation is None:
            raise RuntimeError("Slack installation could not be saved")
        return installation

    def get_installation_by_team(self, *, team_id: str, active_only: bool = True) -> SlackInstallation | None:
        query = "SELECT * FROM slack_installations WHERE team_id = ?"
        params: tuple[Any, ...] = (team_id,)
        if active_only:
            query += " AND status = 'active'"
        row = self.connection.execute(self._sql(query), params).fetchone()
        return self._installation(row) if row else None

    def get_installation(self, *, installation_id: str) -> SlackInstallation | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM slack_installations WHERE id = ? AND status = 'active'"), (installation_id,)
        ).fetchone()
        return self._installation(row) if row else None

    def get_installation_for_account(
        self,
        *,
        installation_id: str,
        account_id: str,
        active_only: bool = True,
    ) -> SlackInstallation | None:
        query = "SELECT * FROM slack_installations WHERE id = ? AND installed_by_account_id = ?"
        if active_only:
            query += " AND status = 'active'"
        row = self.connection.execute(self._sql(query), (installation_id, account_id)).fetchone()
        return self._installation(row) if row else None

    def list_installations(self, *, account_id: str) -> list[SlackInstallation]:
        rows = self.connection.execute(
            self._sql("SELECT * FROM slack_installations WHERE installed_by_account_id = ? ORDER BY created_at DESC"), (account_id,)
        ).fetchall()
        return [self._installation(row) for row in rows]

    def disconnect_installation(self, *, installation_id: str, account_id: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_installations SET status = 'disconnected', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND installed_by_account_id = ? AND status = 'active'"""
                ),
                (installation_id, account_id),
            )
            if updated.rowcount == 1:
                self.connection.execute(
                    self._sql(
                        """UPDATE outbound_slack_outbox
                        SET status = 'failed', lease_token = NULL, lease_expires_at = NULL,
                            last_error = 'Slack installation disconnected', updated_at = CURRENT_TIMESTAMP
                        WHERE installation_id = ? AND status IN ('pending', 'sending')"""
                    ),
                    (installation_id,),
                )
        return updated.rowcount == 1

    def mark_installation_revoked(self, *, installation_id: str) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql(
                    "UPDATE slack_installations SET status = 'revoked', updated_at = CURRENT_TIMESTAMP WHERE id = ?"
                ),
                (installation_id,),
            )
            self.connection.execute(
                self._sql(
                    """UPDATE outbound_slack_outbox
                    SET status = 'failed', lease_token = NULL, lease_expires_at = NULL,
                        last_error = 'Slack credentials were revoked', updated_at = CURRENT_TIMESTAMP
                    WHERE installation_id = ? AND status IN ('pending', 'sending')"""
                ),
                (installation_id,),
            )

    def enqueue_event(self, *, event_id: str, team_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        event_row_id = str(uuid4())
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        statement = (
            """INSERT INTO inbound_slack_events(id, event_id, team_id, event_type, payload_json, payload_hash)
            VALUES (?, ?, ?, ?, ?::jsonb, ?) ON CONFLICT(event_id) DO NOTHING"""
            if self.is_postgres
            else """INSERT INTO inbound_slack_events(id, event_id, team_id, event_type, payload_json, payload_hash)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(event_id) DO NOTHING"""
        )
        with self._transaction(immediate=not self.is_postgres):
            inserted = self.connection.execute(
                self._sql(statement), (event_row_id, event_id, team_id, event_type, payload_json, _digest(payload_json))
            )
        return inserted.rowcount == 1

    def claim_due_events(self, *, limit: int = 10, lease_seconds: int = 120) -> list[InboundSlackEvent]:
        if limit < 1:
            return []
        now = datetime.now(timezone.utc)
        lease = now + timedelta(seconds=max(lease_seconds, 1))
        lock = " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            rows = self.connection.execute(
                self._sql(
                    f"""SELECT * FROM inbound_slack_events
                    WHERE (status = 'pending' AND next_attempt_at <= ?)
                       OR (status = 'processing' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                    ORDER BY received_at, id LIMIT ?{lock}"""
                ),
                (self._timestamp(now), self._timestamp(now), limit),
            ).fetchall()
            claimed: list[InboundSlackEvent] = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                lease_token = str(uuid4())
                self.connection.execute(
                    self._sql(
                        """UPDATE inbound_slack_events SET status = 'processing', attempts = ?, lease_token = ?, lease_expires_at = ?,
                        last_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?"""
                    ),
                    (attempts, lease_token, self._timestamp(lease), str(row["id"])),
                )
                payload = row["payload_json"]
                claimed.append(InboundSlackEvent(
                    id=str(row["id"]), event_id=str(row["event_id"]), team_id=str(row["team_id"]),
                    event_type=str(row["event_type"]), payload=json.loads(payload) if isinstance(payload, str) else dict(payload),
                    attempts=attempts, lease_token=lease_token,
                ))
        return claimed

    def complete_event(
        self, *, event_id: str, lease_token: str, status: Literal["processed", "ignored"], error: str | None = None,
    ) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_events SET status = ?, processed_at = CURRENT_TIMESTAMP, lease_token = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'processing' AND lease_token = ?"""
                ), (status, error, event_id, lease_token),
            )
        return updated.rowcount == 1

    def retry_event(
        self, *, event_id: str, lease_token: str, attempts: int, error: str,
        max_attempts: int = 5, retry_after_seconds: int | None = None,
    ) -> str:
        terminal = attempts >= max(max_attempts, 1)
        delay = retry_after_seconds if retry_after_seconds is not None else min(30 * (2 ** max(attempts - 1, 0)), 3600)
        next_time = datetime.now(timezone.utc) + timedelta(seconds=max(delay, 1))
        status = "failed" if terminal else "pending"
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_events SET status = ?, next_attempt_at = ?, lease_token = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'processing' AND lease_token = ?"""
                ), (status, self._timestamp(next_time), error[:2000], event_id, lease_token),
            )
        return status if updated.rowcount == 1 else "stale"

    def retry_event_contention(
        self, *, event_id: str, lease_token: str, retry_after_seconds: int = 30,
    ) -> bool:
        """Reschedule lease contention without consuming the failure-attempt budget."""
        next_time = datetime.now(timezone.utc) + timedelta(seconds=max(retry_after_seconds, 1))
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_events SET status = 'pending', attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                    next_attempt_at = ?, lease_token = NULL, lease_expires_at = NULL,
                    last_error = 'attachment lease busy', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'processing' AND lease_token = ?"""
                ), (self._timestamp(next_time), event_id, lease_token),
            )
        return updated.rowcount == 1

    def link_user(self, *, team_id: str, slack_user_id: str, account_id: str, email: str) -> None:
        with self._transaction(immediate=not self.is_postgres):
            self.connection.execute(
                self._sql(
                    """INSERT INTO slack_user_links(id, team_id, slack_user_id, account_id, email)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(team_id, slack_user_id) DO UPDATE SET account_id = EXCLUDED.account_id,
                        email = EXCLUDED.email, updated_at = CURRENT_TIMESTAMP"""
                ), (str(uuid4()), team_id, slack_user_id, account_id, email.casefold()),
            )

    def claim_file_submission(self, *, event_id: str, file_id: str, lease_seconds: int = 300) -> SlackLeaseClaim:
        """Claim one attachment with an opaque owner token and stable review job id."""
        now = datetime.now(timezone.utc)
        lease = now + timedelta(seconds=max(lease_seconds, 1))
        lease_token = str(uuid4())
        review_job_id = str(uuid4())
        with self._transaction(immediate=not self.is_postgres):
            inserted = self.connection.execute(
                self._sql(
                    """INSERT INTO inbound_slack_file_submissions(
                        event_id, file_id, lease_token, review_job_id, lease_expires_at
                    ) VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id, file_id) DO NOTHING"""
                ),
                (event_id, file_id, lease_token, review_job_id, self._timestamp(lease)),
            )
            if inserted.rowcount == 1:
                return SlackLeaseClaim("claimed", lease_token, review_job_id)
            row = self.connection.execute(
                self._sql(
                    "SELECT status, review_job_id, lease_expires_at FROM inbound_slack_file_submissions WHERE event_id = ? AND file_id = ?"
                ),
                (event_id, file_id),
            ).fetchone()
            if row is None:
                return SlackLeaseClaim("busy")
            if str(row["status"]) == "completed":
                return SlackLeaseClaim("completed", review_job_id=str(row["review_job_id"]))
            existing_job_id = str(row["review_job_id"])
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_file_submissions
                    SET status = 'processing', lease_token = ?, lease_expires_at = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = ? AND file_id = ? AND status IN ('pending', 'processing')
                      AND (status = 'pending' OR (lease_expires_at IS NOT NULL AND lease_expires_at <= ?))"""
                ),
                (lease_token, self._timestamp(lease), event_id, file_id, self._timestamp(now)),
            )
            return (
                SlackLeaseClaim("claimed", lease_token, existing_job_id)
                if updated.rowcount == 1 else SlackLeaseClaim("busy", review_job_id=existing_job_id)
            )

    def complete_file_submission(self, *, event_id: str, file_id: str, lease_token: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_file_submissions SET status = 'completed', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = ? AND file_id = ? AND status = 'processing' AND lease_token = ?"""
                ),
                (event_id, file_id, lease_token),
            )
        return updated.rowcount == 1

    def release_file_submission(self, *, event_id: str, file_id: str, lease_token: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE inbound_slack_file_submissions SET status = 'pending', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = ? AND file_id = ? AND status = 'processing' AND lease_token = ?"""
                ),
                (event_id, file_id, lease_token),
            )
        return updated.rowcount == 1

    def claim_review_execution(self, *, submission_key: str, lease_seconds: int = 900) -> SlackLeaseClaim:
        now = datetime.now(timezone.utc)
        lease = now + timedelta(seconds=max(lease_seconds, 1))
        token = str(uuid4())
        with self._transaction(immediate=not self.is_postgres):
            inserted = self.connection.execute(
                self._sql(
                    """INSERT INTO slack_review_executions(submission_key, lease_token, lease_expires_at)
                    VALUES (?, ?, ?) ON CONFLICT(submission_key) DO NOTHING"""
                ),
                (submission_key, token, self._timestamp(lease)),
            )
            if inserted.rowcount == 1:
                return SlackLeaseClaim("claimed", token)
            row = self.connection.execute(
                self._sql("SELECT status FROM slack_review_executions WHERE submission_key = ?"),
                (submission_key,),
            ).fetchone()
            if row is not None and str(row["status"]) == "completed":
                return SlackLeaseClaim("completed")
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_executions SET status = 'processing', lease_token = ?, lease_expires_at = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE submission_key = ? AND status IN ('pending', 'processing')
                    AND (status = 'pending' OR lease_expires_at <= ?)"""
                ),
                (token, self._timestamp(lease), submission_key, self._timestamp(now)),
            )
            return SlackLeaseClaim("claimed", token) if updated.rowcount == 1 else SlackLeaseClaim("busy")

    def get_review_execution_status(self, *, submission_key: str) -> str | None:
        row = self.connection.execute(
            self._sql("SELECT status FROM slack_review_executions WHERE submission_key = ?"),
            (submission_key,),
        ).fetchone()
        return str(row["status"]) if row is not None else None

    def complete_review_execution(self, *, submission_key: str, lease_token: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_executions SET status = 'completed', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE submission_key = ? AND status = 'processing' AND lease_token = ?"""
                ), (submission_key, lease_token),
            )
        return updated.rowcount == 1

    def renew_review_execution(
        self, *, submission_key: str, lease_token: str, lease_seconds: int = 900,
    ) -> bool:
        lease = datetime.now(timezone.utc) + timedelta(seconds=max(lease_seconds, 1))
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_executions SET lease_expires_at = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE submission_key = ? AND status = 'processing' AND lease_token = ?"""
                ), (self._timestamp(lease), submission_key, lease_token),
            )
        return updated.rowcount == 1

    def release_review_execution(self, *, submission_key: str, lease_token: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_executions SET status = 'pending', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE submission_key = ? AND status = 'processing' AND lease_token = ?"""
                ), (submission_key, lease_token),
            )
        return updated.rowcount == 1

    def persist_review_job(
        self, *, submission_key: str, job_id: str, payload: dict[str, Any],
    ) -> None:
        """Durably retain the exact RabbitMQ envelope before any publish attempt."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._transaction(immediate=not self.is_postgres):
            self.connection.execute(
                self._sql(
                    """INSERT INTO slack_review_job_outbox(
                        submission_key, job_id, contract_id, contract_version_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(submission_key) DO NOTHING"""
                ),
                (
                    submission_key, job_id, str(payload["contract_id"]),
                    str(payload["contract_version_id"]), encoded,
                ),
            )
            row = self.connection.execute(
                self._sql(
                    "SELECT job_id, payload_json FROM slack_review_job_outbox WHERE submission_key = ?"
                ),
                (submission_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Slack review job outbox row could not be persisted")
            stored_payload = row["payload_json"]
            if not isinstance(stored_payload, str):
                stored_payload = json.dumps(stored_payload, sort_keys=True, separators=(",", ":"))
            if str(row["job_id"]) != job_id or stored_payload != encoded:
                raise ValueError("Slack submission already has a different review job envelope")

    def claim_due_review_jobs(
        self, *, limit: int = 10, lease_seconds: int = 60,
    ) -> list[SlackReviewJobOutboxItem]:
        now = datetime.now(timezone.utc)
        lease = now + timedelta(seconds=max(lease_seconds, 1))
        lock = " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            rows = self.connection.execute(
                self._sql(
                    f"""SELECT * FROM slack_review_job_outbox
                    WHERE (status = 'pending' AND next_attempt_at <= ?)
                       OR (status = 'publishing' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                    ORDER BY next_attempt_at, created_at LIMIT ?{lock}"""
                ),
                (self._timestamp(now), self._timestamp(now), max(limit, 1)),
            ).fetchall()
            items: list[SlackReviewJobOutboxItem] = []
            for row in rows:
                token = str(uuid4())
                attempts = int(row["attempts"]) + 1
                updated = self.connection.execute(
                    self._sql(
                        """UPDATE slack_review_job_outbox SET status = 'publishing', attempts = ?,
                        lease_token = ?, lease_expires_at = ?, last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP WHERE submission_key = ?
                        AND status IN ('pending', 'publishing')"""
                    ),
                    (attempts, token, self._timestamp(lease), str(row["submission_key"])),
                )
                if updated.rowcount != 1:
                    continue
                raw = row["payload_json"]
                payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
                items.append(SlackReviewJobOutboxItem(
                    submission_key=str(row["submission_key"]), job_id=str(row["job_id"]),
                    payload=payload, attempts=attempts, lease_token=token,
                ))
        return items

    def mark_review_job_published(self, *, submission_key: str, lease_token: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_job_outbox SET status = 'published', published_at = CURRENT_TIMESTAMP,
                    lease_token = NULL, lease_expires_at = NULL, last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP WHERE submission_key = ?
                    AND status = 'publishing' AND lease_token = ?"""
                ),
                (submission_key, lease_token),
            )
        return updated.rowcount == 1

    def retry_review_job_publish(
        self, *, submission_key: str, lease_token: str, attempts: int, error: str,
    ) -> bool:
        delay = min(2 ** max(attempts - 1, 0), 60)
        when = datetime.now(timezone.utc) + timedelta(seconds=delay)
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """UPDATE slack_review_job_outbox SET status = 'pending', next_attempt_at = ?,
                    lease_token = NULL, lease_expires_at = NULL, last_error = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE submission_key = ?
                    AND status = 'publishing' AND lease_token = ?"""
                ),
                (self._timestamp(when), error[:2000], submission_key, lease_token),
            )
        return updated.rowcount == 1

    def consume_unknown_sender_capacity(
        self, *, team_id: str, slack_user_id: str, attachments: int, event_id: str | None = None,
    ) -> bool:
        """Allow no more than 2/hour and 5/day before account provisioning."""
        now = datetime.now(timezone.utc)
        windows = (("hour", now.replace(minute=0, second=0, microsecond=0), 2), ("day", now.replace(hour=0, minute=0, second=0, microsecond=0), 5))
        with self._transaction(immediate=not self.is_postgres):
            if event_id:
                admitted = self.connection.execute(
                    self._sql("SELECT 1 FROM slack_unknown_sender_admissions WHERE event_id = ?"),
                    (event_id,),
                ).fetchone()
                if admitted is not None:
                    return True
            counts: list[tuple[str, datetime, int, int]] = []
            for kind, start, limit in windows:
                row = self.connection.execute(
                    self._sql("SELECT attachment_count FROM slack_inbound_rate_limits WHERE team_id = ? AND slack_user_id = ? AND window_kind = ? AND window_start = ?"),
                    (team_id, slack_user_id, kind, self._timestamp(start)),
                ).fetchone()
                count = int(row["attachment_count"]) if row else 0
                if count + attachments > limit:
                    return False
                counts.append((kind, start, limit, count))
            for kind, start, _limit, count in counts:
                if count:
                    self.connection.execute(
                        self._sql("UPDATE slack_inbound_rate_limits SET attachment_count = ? WHERE team_id = ? AND slack_user_id = ? AND window_kind = ? AND window_start = ?"),
                        (count + attachments, team_id, slack_user_id, kind, self._timestamp(start)),
                    )
                else:
                    self.connection.execute(
                        self._sql("INSERT INTO slack_inbound_rate_limits(team_id, slack_user_id, window_kind, window_start, attachment_count) VALUES (?, ?, ?, ?, ?)"),
                        (team_id, slack_user_id, kind, self._timestamp(start), attachments),
                    )
            if event_id:
                self.connection.execute(
                    self._sql(
                        """INSERT INTO slack_unknown_sender_admissions(event_id, team_id, slack_user_id, attachment_count)
                        VALUES (?, ?, ?, ?)"""
                    ),
                    (event_id, team_id, slack_user_id, attachments),
                )
        return True

    def enqueue_outbound(self, intent: OutboundSlackIntent) -> str:
        outbox_id = str(uuid4())
        with self._transaction(immediate=not self.is_postgres):
            existing = self.connection.execute(
                self._sql("SELECT id FROM outbound_slack_outbox WHERE idempotency_key = ?"), (intent.idempotency_key,)
            ).fetchone()
            if existing:
                return str(existing["id"])
            if intent.thread_position is None:
                row = self.connection.execute(
                    self._sql("SELECT COALESCE(MAX(thread_position), 0) AS last_position FROM outbound_slack_outbox WHERE installation_id = ? AND channel_id = ? AND thread_ts = ?"),
                    (intent.installation_id, intent.channel_id, intent.thread_ts),
                ).fetchone()
                position = int(row["last_position"]) + 1
            else:
                position = intent.thread_position
            blocks_json = json.dumps(intent.blocks, separators=(",", ":")) if intent.blocks else None
            statement = (
                """INSERT INTO outbound_slack_outbox(id, workspace_id, installation_id, contract_id, contract_version_id,
                    channel_id, thread_ts, thread_position, message_type, text_body, blocks_json, idempotency_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?)"""
                if self.is_postgres else
                """INSERT INTO outbound_slack_outbox(id, workspace_id, installation_id, contract_id, contract_version_id,
                    channel_id, thread_ts, thread_position, message_type, text_body, blocks_json, idempotency_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            )
            self.connection.execute(self._sql(statement), (
                outbox_id, intent.workspace_id, intent.installation_id, intent.contract_id, intent.contract_version_id,
                intent.channel_id, intent.thread_ts, position, intent.message_type, intent.text_body, blocks_json, intent.idempotency_key,
            ))
            self.connection.execute(
                self._sql(
                    """UPDATE outbound_slack_outbox
                    SET status = 'failed', last_error = 'Slack installation is not active',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND NOT EXISTS (
                        SELECT 1 FROM slack_installations
                        WHERE id = ? AND status = 'active'
                    )"""
                ),
                (outbox_id, intent.installation_id),
            )
        return outbox_id

    def claim_due_outbound(self, *, limit: int = 25, lease_seconds: int = 120) -> list[OutboundSlackItem]:
        now = datetime.now(timezone.utc)
        lease = now + timedelta(seconds=max(lease_seconds, 1))
        lock = " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            rows = self.connection.execute(self._sql(f"""
                SELECT o.* FROM outbound_slack_outbox o
                WHERE ((o.status = 'pending' AND o.next_attempt_at <= ?)
                    OR (o.status = 'sending' AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at <= ?))
                AND NOT EXISTS (
                    SELECT 1 FROM outbound_slack_outbox earlier
                    WHERE earlier.installation_id = o.installation_id AND earlier.channel_id = o.channel_id
                      AND earlier.thread_ts = o.thread_ts AND earlier.thread_position < o.thread_position
                      AND earlier.status IN ('pending', 'sending')
                ) ORDER BY o.next_attempt_at, o.created_at LIMIT ?{lock}
            """), (self._timestamp(now), self._timestamp(now), max(limit, 1))).fetchall()
            claimed: list[OutboundSlackItem] = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                lease_token = str(uuid4())
                self.connection.execute(self._sql("UPDATE outbound_slack_outbox SET status = 'sending', attempts = ?, lease_token = ?, lease_expires_at = ?, last_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (attempts, lease_token, self._timestamp(lease), str(row["id"])))
                raw_blocks = row["blocks_json"]
                claimed.append(OutboundSlackItem(
                    id=str(row["id"]), installation_id=str(row["installation_id"]), channel_id=str(row["channel_id"]),
                    thread_ts=str(row["thread_ts"]), message_type=str(row["message_type"]), text_body=str(row["text_body"]),
                    blocks=json.loads(raw_blocks) if isinstance(raw_blocks, str) and raw_blocks else (list(raw_blocks) if raw_blocks else None), attempts=attempts,
                    lease_token=lease_token,
                ))
        return claimed

    def mark_outbound_sent(
        self, *, outbox_id: str, lease_token: str, provider_message_ts: str | None,
    ) -> bool:
        with self._transaction():
            updated = self.connection.execute(self._sql("""UPDATE outbound_slack_outbox SET status = 'sent', provider_message_ts = ?, sent_at = CURRENT_TIMESTAMP,
                lease_token = NULL, lease_expires_at = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'sending' AND lease_token = ?"""), (provider_message_ts, outbox_id, lease_token))
        return updated.rowcount == 1

    def reschedule_outbound(self, *, outbox_id: str, lease_token: str, attempts: int, error: str, retry_after_seconds: int | None = None, max_attempts: int = 5) -> str:
        terminal = attempts >= max(max_attempts, 1)
        delay = retry_after_seconds if retry_after_seconds is not None else min(30 * (2 ** max(attempts - 1, 0)), 3600)
        status = "failed" if terminal else "pending"
        when = datetime.now(timezone.utc) + timedelta(seconds=max(delay, 1))
        with self._transaction():
            updated = self.connection.execute(self._sql("""UPDATE outbound_slack_outbox SET status = ?, next_attempt_at = ?, lease_token = NULL, lease_expires_at = NULL,
                last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'sending'
                AND lease_token = ?
                AND EXISTS (
                    SELECT 1 FROM slack_installations installation
                    WHERE installation.id = outbound_slack_outbox.installation_id
                      AND installation.status = 'active'
                )"""), (status, self._timestamp(when), error[:2000], outbox_id, lease_token))
        return status if updated.rowcount == 1 else "stale"

    def _installation(self, row: Any) -> SlackInstallation:
        return SlackInstallation(id=str(row["id"]), team_id=str(row["team_id"]), team_name=str(row["team_name"]) if row["team_name"] else None,
            bot_user_id=str(row["bot_user_id"]) if row["bot_user_id"] else None, encrypted_bot_token=str(row["encrypted_bot_token"]),
            installed_by_account_id=str(row["installed_by_account_id"]), status=str(row["status"]), created_at=row["created_at"])

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    def _timestamp(self, value: datetime) -> Any:
        return value if self.is_postgres else value.isoformat()

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        if self.is_postgres:
            with self.connection.transaction():
                yield
            return
        self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
