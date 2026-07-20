from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import uuid4


@dataclass(frozen=True)
class KnowledgeOutboxItem:
    id: str
    workspace_id: str
    contract_id: str
    contract_version_id: str
    status: str
    attempts: int


class KnowledgeOutboxRepository:
    """Database-backed delivery intents for knowledge indexing jobs."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def enqueue_intent(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        force: bool = False,
    ) -> str:
        outbox_id = str(uuid4())
        if force:
            statement = (
                """
                INSERT INTO knowledge_index_outbox(
                    id, workspace_id, contract_id, contract_version_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT (workspace_id, contract_version_id) DO UPDATE SET
                    contract_id = EXCLUDED.contract_id,
                    status = 'pending',
                    attempts = 0,
                    next_attempt_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL,
                    last_error = NULL,
                    published_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """
                if self.is_postgres
                else """
                INSERT INTO knowledge_index_outbox(
                    id, workspace_id, contract_id, contract_version_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT (workspace_id, contract_version_id) DO UPDATE SET
                    contract_id = excluded.contract_id,
                    status = 'pending',
                    attempts = 0,
                    next_attempt_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL,
                    last_error = NULL,
                    published_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
        else:
            statement = (
                """
                INSERT INTO knowledge_index_outbox(
                    id, workspace_id, contract_id, contract_version_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT (workspace_id, contract_version_id) DO NOTHING
                """
                if self.is_postgres
                else """
                INSERT OR IGNORE INTO knowledge_index_outbox(
                    id, workspace_id, contract_id, contract_version_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """
            )
        with self._transaction():
            self.connection.execute(
                self._sql(statement),
                (outbox_id, workspace_id, contract_id, contract_version_id),
            )
            row = self.connection.execute(
                self._sql(
                    """
                    SELECT id FROM knowledge_index_outbox
                    WHERE workspace_id = ? AND contract_version_id = ?
                    """
                ),
                (workspace_id, contract_version_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Knowledge indexing intent could not be persisted")
        return str(row["id"])

    def claim_due(self, *, limit: int = 25, lease_seconds: int = 120) -> list[KnowledgeOutboxItem]:
        if limit < 1:
            return []
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=max(lease_seconds, 1))
        now_value = self._timestamp(now)
        lease_value = self._timestamp(lease_expires_at)
        lock_suffix = " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            rows = self.connection.execute(
                self._sql(
                    f"""
                    SELECT id, workspace_id, contract_id, contract_version_id, status, attempts
                    FROM knowledge_index_outbox
                    WHERE (status = 'pending' AND next_attempt_at <= ?)
                       OR (status = 'publishing' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                    ORDER BY next_attempt_at, created_at, id
                    LIMIT ?{lock_suffix}
                    """
                ),
                (now_value, now_value, limit),
            ).fetchall()
            claimed: list[KnowledgeOutboxItem] = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                self.connection.execute(
                    self._sql(
                        """
                        UPDATE knowledge_index_outbox
                        SET status = 'publishing', attempts = ?, lease_expires_at = ?,
                            last_error = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """
                    ),
                    (attempts, lease_value, str(row["id"])),
                )
                claimed.append(
                    KnowledgeOutboxItem(
                        id=str(row["id"]),
                        workspace_id=str(row["workspace_id"]),
                        contract_id=str(row["contract_id"]),
                        contract_version_id=str(row["contract_version_id"]),
                        status="publishing",
                        attempts=attempts,
                    )
                )
        return claimed

    def mark_published(self, *, outbox_id: str) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    UPDATE knowledge_index_outbox
                    SET status = 'published', published_at = CURRENT_TIMESTAMP,
                        lease_expires_at = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'publishing'
                    """
                ),
                (outbox_id,),
            )

    def reschedule(
        self,
        *,
        outbox_id: str,
        attempts: int,
        error: str,
        max_attempts: int,
        base_backoff_seconds: int,
    ) -> None:
        terminal = attempts >= max(max_attempts, 1)
        delay_seconds = min(max(base_backoff_seconds, 1) * (2 ** max(attempts - 1, 0)), 3600)
        next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    UPDATE knowledge_index_outbox
                    SET status = ?, next_attempt_at = ?, lease_expires_at = NULL,
                        last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'publishing'
                    """
                ),
                (
                    "failed" if terminal else "pending",
                    self._timestamp(next_attempt_at),
                    error[:4000],
                    outbox_id,
                ),
            )

    def backfill(self) -> int:
        rows = self.connection.execute(
            self._sql(
                """
                SELECT c.workspace_id, c.id AS contract_id, c.current_version_id AS contract_version_id
                FROM contracts c
                JOIN contract_versions cv
                  ON cv.id = c.current_version_id AND cv.contract_id = c.id
                JOIN contract_reviews cr ON cr.contract_version_id = cv.id
                WHERE c.status = 'review_ready'
                  AND NOT EXISTS (
                      SELECT 1 FROM knowledge_indexes ki
                      WHERE ki.workspace_id = c.workspace_id
                        AND ki.contract_id = c.id
                        AND ki.contract_version_id = cv.id
                        AND ki.status = 'ready'
                  )
                ORDER BY c.updated_at, c.id
                """
            )
        ).fetchall()
        for row in rows:
            self.enqueue_intent(
                workspace_id=str(row["workspace_id"]),
                contract_id=str(row["contract_id"]),
                contract_version_id=str(row["contract_version_id"]),
                force=True,
            )
        return len(rows)

    def retry_failed(self) -> dict[str, int]:
        failed_indexes = self.connection.execute(
            self._sql(
                """
                SELECT workspace_id, contract_id, contract_version_id
                FROM knowledge_indexes WHERE status = 'failed'
                """
            )
        ).fetchall()
        failed_outbox = self.connection.execute(
            """
            SELECT workspace_id, contract_id, contract_version_id
            FROM knowledge_index_outbox WHERE status = 'failed'
            """
        ).fetchall()
        with self._transaction():
            self.connection.execute(
                """
                UPDATE knowledge_indexes
                SET status = 'pending', error_message = NULL, indexed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'failed'
                """
            )
        intents = {
            (str(row["workspace_id"]), str(row["contract_id"]), str(row["contract_version_id"]))
            for row in [*failed_indexes, *failed_outbox]
        }
        for workspace_id, contract_id, contract_version_id in intents:
            self.enqueue_intent(
                workspace_id=workspace_id,
                contract_id=contract_id,
                contract_version_id=contract_version_id,
                force=True,
            )
        return {"knowledge_indexes": len(failed_indexes), "outbox_intents": len(intents)}

    def status(self) -> dict[str, dict[str, int]]:
        outbox_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM knowledge_index_outbox GROUP BY status ORDER BY status"
        ).fetchall()
        index_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM knowledge_indexes GROUP BY status ORDER BY status"
        ).fetchall()
        return {
            "outbox": {str(row["status"]): int(row["count"]) for row in outbox_rows},
            "indexes": {str(row["status"]): int(row["count"]) for row in index_rows},
        }

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    def _timestamp(self, value: datetime) -> datetime | str:
        if self.is_postgres:
            return value
        return value.isoformat(sep=" ", timespec="microseconds")

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
