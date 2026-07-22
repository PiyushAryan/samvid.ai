from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Literal
from uuid import uuid4


OutboundEmailType = Literal["receipt", "review"]
OutboundEmailStatus = Literal["pending", "sending", "sent", "failed"]


@dataclass(frozen=True)
class OutboundEmailIntent:
    workspace_id: str
    thread_key: str
    message_type: OutboundEmailType
    to_address: str
    from_address: str
    subject: str
    text_body: str
    idempotency_key: str
    contract_id: str | None = None
    contract_version_id: str | None = None
    html_body: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    thread_position: int | None = None


@dataclass(frozen=True)
class OutboundEmailOutboxItem:
    id: str
    workspace_id: str
    contract_id: str | None
    contract_version_id: str | None
    thread_key: str
    thread_position: int
    message_type: OutboundEmailType
    to_address: str
    from_address: str
    subject: str
    text_body: str
    html_body: str | None
    in_reply_to: str | None
    references: str | None
    idempotency_key: str
    status: OutboundEmailStatus
    attempts: int


class OutboundEmailOutboxRepository:
    """Durable, ordered email-delivery intents with at-least-once claiming semantics."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def enqueue(self, intent: OutboundEmailIntent) -> str:
        """Persist an idempotent intent and return its stable outbox ID.

        A thread position is assigned transactionally when callers do not provide
        one. Earlier pending or leased items in the same thread block later ones;
        a terminal failed receipt does not block a final review indefinitely.
        """

        outbox_id = str(uuid4())
        with self._transaction(immediate=not self.is_postgres):
            existing = self.connection.execute(
                self._sql("SELECT id FROM outbound_email_outbox WHERE idempotency_key = ?"),
                (intent.idempotency_key,),
            ).fetchone()
            if existing is not None:
                return str(existing["id"])

            thread_position = intent.thread_position
            if thread_position is None:
                row = self.connection.execute(
                    self._sql(
                        """
                        SELECT COALESCE(MAX(thread_position), 0) AS latest_position
                        FROM outbound_email_outbox
                        WHERE thread_key = ?
                        """
                    ),
                    (intent.thread_key,),
                ).fetchone()
                thread_position = int(row["latest_position"]) + 1
            if thread_position < 1:
                raise ValueError("thread_position must be at least 1")
            occupied = self.connection.execute(
                self._sql(
                    """
                    SELECT 1 FROM outbound_email_outbox
                    WHERE thread_key = ? AND thread_position = ?
                    """
                ),
                (intent.thread_key, thread_position),
            ).fetchone()
            if occupied is not None:
                raise ValueError("thread_position is already assigned in this email thread")

            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO outbound_email_outbox(
                        id, workspace_id, contract_id, contract_version_id,
                        thread_key, thread_position, message_type,
                        to_address, from_address, subject, text_body, html_body,
                        in_reply_to, references_header, idempotency_key, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """
                ),
                (
                    outbox_id,
                    intent.workspace_id,
                    intent.contract_id,
                    intent.contract_version_id,
                    intent.thread_key,
                    thread_position,
                    intent.message_type,
                    intent.to_address,
                    intent.from_address,
                    intent.subject,
                    intent.text_body,
                    intent.html_body,
                    intent.in_reply_to,
                    intent.references,
                    intent.idempotency_key,
                ),
            )
            persisted = self.connection.execute(
                self._sql("SELECT id FROM outbound_email_outbox WHERE idempotency_key = ?"),
                (intent.idempotency_key,),
            ).fetchone()
        if persisted is None:
            raise RuntimeError("Outbound email intent could not be persisted")
        return str(persisted["id"])

    def claim_due(self, *, limit: int = 25, lease_seconds: int = 120) -> list[OutboundEmailOutboxItem]:
        if limit < 1:
            return []
        now = datetime.now(timezone.utc)
        now_value = self._timestamp(now)
        lease_value = self._timestamp(now + timedelta(seconds=max(lease_seconds, 1)))
        lock_suffix = " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            rows = self.connection.execute(
                self._sql(
                    f"""
                    SELECT o.*
                    FROM outbound_email_outbox o
                    WHERE (
                        (o.status = 'pending' AND o.next_attempt_at <= ?)
                        OR (
                            o.status = 'sending'
                            AND o.lease_expires_at IS NOT NULL
                            AND o.lease_expires_at <= ?
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM outbound_email_outbox earlier
                        WHERE earlier.thread_key = o.thread_key
                          AND earlier.thread_position < o.thread_position
                          AND earlier.status IN ('pending', 'sending')
                    )
                    ORDER BY o.next_attempt_at, o.created_at, o.id
                    LIMIT ?{lock_suffix}
                    """
                ),
                (now_value, now_value, limit),
            ).fetchall()
            claimed: list[OutboundEmailOutboxItem] = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                self.connection.execute(
                    self._sql(
                        """
                        UPDATE outbound_email_outbox
                        SET status = 'sending', attempts = ?, lease_expires_at = ?,
                            last_error = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """
                    ),
                    (attempts, lease_value, str(row["id"])),
                )
                claimed.append(self._item_from_row(row, status="sending", attempts=attempts))
        return claimed

    def mark_sent(self, *, outbox_id: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE outbound_email_outbox
                    SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                        lease_expires_at = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'sending'
                    """
                ),
                (outbox_id,),
            )
        return updated.rowcount == 1

    def reschedule(
        self,
        *,
        outbox_id: str,
        attempts: int,
        error: str,
        max_attempts: int,
        base_backoff_seconds: int,
    ) -> OutboundEmailStatus:
        terminal = attempts >= max(max_attempts, 1)
        delay_seconds = min(max(base_backoff_seconds, 1) * (2 ** max(attempts - 1, 0)), 3600)
        next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        status: OutboundEmailStatus = "failed" if terminal else "pending"
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    UPDATE outbound_email_outbox
                    SET status = ?, next_attempt_at = ?, lease_expires_at = NULL,
                        last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'sending'
                    """
                ),
                (status, self._timestamp(next_attempt_at), error[:4000], outbox_id),
            )
        return status

    def mark_failed(self, *, outbox_id: str, error: str) -> bool:
        with self._transaction():
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE outbound_email_outbox
                    SET status = 'failed', lease_expires_at = NULL, last_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('pending', 'sending')
                    """
                ),
                (error[:4000], outbox_id),
            )
        return updated.rowcount == 1

    def get(self, *, outbox_id: str) -> OutboundEmailOutboxItem | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM outbound_email_outbox WHERE id = ?"),
            (outbox_id,),
        ).fetchone()
        return self._item_from_row(row) if row is not None else None

    def is_sending(self, *, outbox_id: str) -> bool:
        row = self.connection.execute(
            self._sql("SELECT 1 FROM outbound_email_outbox WHERE id = ? AND status = 'sending'"),
            (outbox_id,),
        ).fetchone()
        return row is not None

    def status(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM outbound_email_outbox GROUP BY status ORDER BY status"
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _item_from_row(
        self,
        row: Any,
        *,
        status: OutboundEmailStatus | None = None,
        attempts: int | None = None,
    ) -> OutboundEmailOutboxItem:
        return OutboundEmailOutboxItem(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            contract_id=str(row["contract_id"]) if row["contract_id"] is not None else None,
            contract_version_id=str(row["contract_version_id"]) if row["contract_version_id"] is not None else None,
            thread_key=str(row["thread_key"]),
            thread_position=int(row["thread_position"]),
            message_type=str(row["message_type"]),  # type: ignore[arg-type]
            to_address=str(row["to_address"]),
            from_address=str(row["from_address"]),
            subject=str(row["subject"]),
            text_body=str(row["text_body"]),
            html_body=str(row["html_body"]) if row["html_body"] is not None else None,
            in_reply_to=str(row["in_reply_to"]) if row["in_reply_to"] is not None else None,
            references=str(row["references_header"]) if row["references_header"] is not None else None,
            idempotency_key=str(row["idempotency_key"]),
            status=status or str(row["status"]),  # type: ignore[arg-type]
            attempts=int(row["attempts"]) if attempts is None else attempts,
        )

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    def _timestamp(self, value: datetime) -> datetime | str:
        return value if self.is_postgres else value.isoformat(sep=" ", timespec="microseconds")

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        try:
            if immediate:
                self.connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
