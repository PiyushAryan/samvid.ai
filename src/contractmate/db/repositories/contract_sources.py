from __future__ import annotations

from typing import Any, Literal


ContractSourceChannel = Literal["browser", "email", "slack"]


class ContractSourceRepository:
    """Stores the channel/thread that originated a contract without changing legacy rows."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def upsert(self, *, contract_id: str, source_channel: ContractSourceChannel, source_thread_key: str) -> None:
        if source_channel not in {"browser", "email", "slack"}:
            raise ValueError("Unsupported contract source channel")
        statement = """
            INSERT INTO contract_sources(contract_id, source_channel, source_thread_key)
            VALUES (?, ?, ?)
            ON CONFLICT(contract_id) DO UPDATE SET
                source_channel = EXCLUDED.source_channel,
                source_thread_key = EXCLUDED.source_thread_key
        """
        self.connection.execute(self._sql(statement), (contract_id, source_channel, source_thread_key))

    def get(self, *, contract_id: str) -> tuple[str, str] | None:
        row = self.connection.execute(
            self._sql("SELECT source_channel, source_thread_key FROM contract_sources WHERE contract_id = ?"),
            (contract_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row["source_channel"]), str(row["source_thread_key"])

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement
