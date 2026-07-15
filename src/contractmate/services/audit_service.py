from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4


class AuditService:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def record(
        self,
        *,
        workspace_id: str,
        event_type: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        contract_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO audit_events(id, workspace_id, contract_id, actor_type, actor_id, event_type, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (
                    str(uuid4()),
                    workspace_id,
                    contract_id,
                    actor_type,
                    actor_id,
                    event_type,
                    json.dumps(metadata or {}),
                ),
            )

    def _sql(self, statement: str) -> str:
        if not self.is_postgres:
            return statement
        return statement.replace("?", "%s")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
