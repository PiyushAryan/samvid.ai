from __future__ import annotations

import sqlite3

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.chat import ChatRepository


@pytest.fixture
def repository() -> ChatRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    for suffix in ("a", "b"):
        connection.execute(
            """
            INSERT INTO user_accounts(
                id, auth_subject, email, role, state, personal_workspace_id, source, claimed_at
            ) VALUES (?, ?, ?, 'user', 'active', ?, 'signup', CURRENT_TIMESTAMP)
            """,
            (f"account-{suffix}", f"subject-{suffix}", f"{suffix}@example.com", f"workspace-{suffix}"),
        )
        connection.execute(
            """
            INSERT INTO contracts(id, workspace_id, email_thread_id, status, created_by)
            VALUES (?, ?, ?, 'reviewed', ?)
            """,
            (f"contract-{suffix}", f"workspace-{suffix}", f"thread-{suffix}", f"{suffix}@example.com"),
        )
    connection.commit()
    yield ChatRepository(connection)
    connection.close()


def test_chat_session_and_messages_round_trip(repository: ChatRepository) -> None:
    session = repository.create_session(
        workspace_id="workspace-a",
        account_id="account-a",
        contract_id="contract-a",
        title="Indemnity review",
    )
    user_message = repository.append_message(
        workspace_id="workspace-a",
        session_id=session.id,
        role="user",
        content="What is the indemnity exposure?",
    )
    assistant_message = repository.append_message(
        workspace_id="workspace-a",
        session_id=session.id,
        role="assistant",
        content="The clause is uncapped.",
        citations=[{"chunk_id": "chunk-1", "page": 3}],
        model_provider="fireworks",
        model_name="qwen",
        metadata={"retrieval": "hybrid"},
    )

    messages = repository.list_messages(workspace_id="workspace-a", session_id=session.id)
    assert [message.id for message in messages] == [user_message.id, assistant_message.id]
    assert [message.sequence_number for message in messages] == [1, 2]
    assert messages[1].citations == [{"chunk_id": "chunk-1", "page": 3}]
    assert messages[1].metadata == {"retrieval": "hybrid"}
    assert repository.list_sessions(workspace_id="workspace-a", account_id="account-a")[0].id == session.id


def test_chat_repository_hides_cross_workspace_ids(repository: ChatRepository) -> None:
    session = repository.create_session(workspace_id="workspace-a", account_id="account-a")

    assert repository.get_session(workspace_id="workspace-b", session_id=session.id) is None
    assert repository.list_messages(workspace_id="workspace-b", session_id=session.id) == []
    with pytest.raises(KeyError):
        repository.append_message(
            workspace_id="workspace-b",
            session_id=session.id,
            role="user",
            content="Cross-workspace attempt",
        )


def test_session_requires_account_and_contract_in_same_workspace(repository: ChatRepository) -> None:
    with pytest.raises(KeyError):
        repository.create_session(workspace_id="workspace-a", account_id="account-b")

    with pytest.raises(KeyError):
        repository.create_session(
            workspace_id="workspace-a",
            account_id="account-a",
            contract_id="contract-b",
        )
