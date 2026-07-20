from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ChatSession:
    id: str
    workspace_id: str
    account_id: str
    contract_id: str | None
    title: str | None
    created_at: Any
    updated_at: Any


@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: str
    workspace_id: str
    session_id: str
    sequence_number: int
    role: str
    content: str
    citations: list[dict[str, Any]]
    model_provider: str | None
    model_name: str | None
    metadata: dict[str, Any]
    created_at: Any


class ChatRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_session(
        self,
        *,
        workspace_id: str,
        account_id: str,
        contract_id: str | None = None,
        title: str | None = None,
    ) -> ChatSession:
        self._require_account_workspace(workspace_id=workspace_id, account_id=account_id)
        if contract_id is not None:
            self._require_contract(workspace_id=workspace_id, contract_id=contract_id)
        session_id = str(uuid4())
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO chat_sessions(id, workspace_id, account_id, contract_id, title)
                    VALUES (?, ?, ?, ?, ?)
                    """
                ),
                (session_id, workspace_id, account_id, contract_id, title.strip() if title else None),
            )
        session = self.get_session(workspace_id=workspace_id, session_id=session_id)
        if session is None:
            raise RuntimeError("Chat session could not be created")
        return session

    def get_session(self, *, workspace_id: str, session_id: str) -> ChatSession | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM chat_sessions WHERE workspace_id = ? AND id = ?"),
            (workspace_id, session_id),
        ).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(
        self,
        *,
        workspace_id: str,
        account_id: str,
        contract_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        contract_filter = "AND contract_id = ?" if contract_id else ""
        params: tuple[Any, ...] = (
            (workspace_id, account_id, contract_id, max(1, min(limit, 200)), max(0, offset))
            if contract_id
            else (workspace_id, account_id, max(1, min(limit, 200)), max(0, offset))
        )
        rows = self.connection.execute(
            self._sql(
                f"""
                SELECT * FROM chat_sessions
                WHERE workspace_id = ? AND account_id = ? {contract_filter}
                ORDER BY updated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """
            ),
            params,
        ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def append_message(
        self,
        *,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
        citations: Sequence[Mapping[str, Any]] | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ChatMessage:
        if role not in {"system", "user", "assistant"}:
            raise ValueError("Invalid chat message role")
        content = content.strip()
        if not content:
            raise ValueError("Chat message content is required")
        message_id = str(uuid4())
        citations_json = json.dumps([dict(citation) for citation in citations or ()], separators=(",", ":"))
        metadata_json = json.dumps(dict(metadata or {}), separators=(",", ":"))
        json_cast = "::jsonb" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            row_lock = " FOR UPDATE" if self.is_postgres else ""
            session = self.connection.execute(
                self._sql(
                    f"SELECT id FROM chat_sessions WHERE workspace_id = ? AND id = ?{row_lock}"
                ),
                (workspace_id, session_id),
            ).fetchone()
            if session is None:
                raise KeyError("Chat session not found")
            sequence_row = self.connection.execute(
                self._sql(
                    """
                    SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_sequence
                    FROM chat_messages
                    WHERE workspace_id = ? AND session_id = ?
                    """
                ),
                (workspace_id, session_id),
            ).fetchone()
            sequence_number = int(sequence_row["next_sequence"])
            self.connection.execute(
                self._sql(
                    f"""
                    INSERT INTO chat_messages(
                        id, workspace_id, session_id, sequence_number, role, content, citations,
                        model_provider, model_name, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?{json_cast}, ?, ?, ?{json_cast})
                    """
                ),
                (
                    message_id,
                    workspace_id,
                    session_id,
                    sequence_number,
                    role,
                    content,
                    citations_json,
                    model_provider,
                    model_name,
                    metadata_json,
                ),
            )
            self.connection.execute(
                self._sql(
                    "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE workspace_id = ? AND id = ?"
                ),
                (workspace_id, session_id),
            )
        message = self.get_message(workspace_id=workspace_id, message_id=message_id)
        if message is None:
            raise RuntimeError("Chat message could not be created")
        return message

    def get_message(self, *, workspace_id: str, message_id: str) -> ChatMessage | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM chat_messages WHERE workspace_id = ? AND id = ?"),
            (workspace_id, message_id),
        ).fetchone()
        return self._message_from_row(row) if row else None

    def list_messages(
        self,
        *,
        workspace_id: str,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ChatMessage]:
        rows = self.connection.execute(
            self._sql(
                """
                SELECT cm.*
                FROM chat_messages cm
                JOIN chat_sessions cs ON cs.id = cm.session_id AND cs.workspace_id = cm.workspace_id
                WHERE cm.workspace_id = ? AND cm.session_id = ?
                ORDER BY cm.sequence_number
                LIMIT ? OFFSET ?
                """
            ),
            (workspace_id, session_id, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def update_title(self, *, workspace_id: str, session_id: str, title: str | None) -> bool:
        with self._transaction():
            result = self.connection.execute(
                self._sql(
                    """
                    UPDATE chat_sessions
                    SET title = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = ? AND id = ?
                    """
                ),
                (title.strip() if title else None, workspace_id, session_id),
            )
        return result.rowcount == 1

    def _require_account_workspace(self, *, workspace_id: str, account_id: str) -> None:
        row = self.connection.execute(
            self._sql(
                """
                SELECT 1 FROM user_accounts
                WHERE id = ? AND role = 'user' AND state = 'active' AND personal_workspace_id = ?
                """
            ),
            (account_id, workspace_id),
        ).fetchone()
        if row is None:
            raise KeyError("Active user account not found in workspace")

    def _require_contract(self, *, workspace_id: str, contract_id: str) -> None:
        row = self.connection.execute(
            self._sql("SELECT 1 FROM contracts WHERE workspace_id = ? AND id = ?"),
            (workspace_id, contract_id),
        ).fetchone()
        if row is None:
            raise KeyError("Contract not found in workspace")

    @staticmethod
    def _session_from_row(row: Any) -> ChatSession:
        return ChatSession(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            account_id=str(row["account_id"]),
            contract_id=str(row["contract_id"]) if row["contract_id"] is not None else None,
            title=str(row["title"]) if row["title"] is not None else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _message_from_row(row: Any) -> ChatMessage:
        raw_citations = row["citations"]
        raw_metadata = row["metadata"]
        citations = json.loads(raw_citations) if isinstance(raw_citations, str) else list(raw_citations)
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else dict(raw_metadata)
        return ChatMessage(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            session_id=str(row["session_id"]),
            sequence_number=int(row["sequence_number"]),
            role=str(row["role"]),
            content=str(row["content"]),
            citations=[dict(citation) for citation in citations],
            model_provider=str(row["model_provider"]) if row["model_provider"] is not None else None,
            model_name=str(row["model_name"]) if row["model_name"] is not None else None,
            metadata=metadata,
            created_at=row["created_at"],
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
