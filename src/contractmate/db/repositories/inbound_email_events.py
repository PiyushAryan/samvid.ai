from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Iterator


class InboundEventClaim(StrEnum):
    ACQUIRED = "acquired"
    COMPLETED = "completed"
    PROCESSING = "processing"


class InboundEmailEventRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def claim(
        self,
        *,
        event_id: str,
        email_message_id: str,
        workspace_id: str,
        event_type: str,
        payload_hash: str,
    ) -> InboundEventClaim:
        with self._transaction(immediate=not self.is_postgres):
            if self.is_postgres:
                inserted = self.connection.execute(
                    """
                    INSERT INTO inbound_email_events(
                        id, email_message_id, workspace_id, event_type, payload_hash, status
                    )
                    VALUES (%s, %s, %s, %s, %s, 'processing')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (event_id, email_message_id, workspace_id, event_type, payload_hash),
                ).fetchone()
                if inserted:
                    return InboundEventClaim.ACQUIRED
            else:
                inserted = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO inbound_email_events(
                        id, email_message_id, workspace_id, event_type, payload_hash, status
                    )
                    VALUES (?, ?, ?, ?, ?, 'processing')
                    """,
                    (event_id, email_message_id, workspace_id, event_type, payload_hash),
                )
                if inserted.rowcount == 1:
                    return InboundEventClaim.ACQUIRED

            row = self.connection.execute(
                self._sql("SELECT status FROM inbound_email_events WHERE email_message_id = ?"),
                (email_message_id,),
            ).fetchone()
            if row and str(row["status"]) == "completed":
                return InboundEventClaim.COMPLETED

            stale_condition = (
                "received_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes'"
                if self.is_postgres
                else "received_at <= datetime('now', '-10 minutes')"
            )
            reclaimed = self.connection.execute(
                self._sql(
                    f"""
                    UPDATE inbound_email_events
                    SET status = 'processing', payload_hash = ?, received_at = CURRENT_TIMESTAMP, processed_at = NULL
                    WHERE email_message_id = ?
                      AND (status = 'failed' OR (status = 'processing' AND {stale_condition}))
                    """
                ),
                (payload_hash, email_message_id),
            )
            if reclaimed.rowcount == 1:
                return InboundEventClaim.ACQUIRED
            return InboundEventClaim.PROCESSING

    def mark_completed(self, email_message_id: str) -> None:
        self._mark(email_message_id, "completed")

    def mark_failed(self, email_message_id: str) -> None:
        self._mark(email_message_id, "failed")

    def _mark(self, email_message_id: str, status: str) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    UPDATE inbound_email_events
                    SET status = ?, processed_at = CURRENT_TIMESTAMP
                    WHERE email_message_id = ?
                    """
                ),
                (status, email_message_id),
            )

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

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
