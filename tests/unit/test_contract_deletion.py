from __future__ import annotations

import json
import sqlite3

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.contracts import ContractRepository
from contractmate.workflows.states import WorkflowState


def test_contract_deletion_removes_content_and_preserves_tombstone_audit() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    repository = ContractRepository(connection)
    connection.execute(
        """
        INSERT INTO email_threads(id, workspace_id, thread_key, from_address, agno_session_id)
        VALUES ('thread-1', 'workspace-1', 'thread-key', 'user@example.com', 'agno-1')
        """
    )
    contract_id, version_id = repository.create_contract_with_version(
        workspace_id="workspace-1",
        email_thread_id="thread-1",
        title="Delete me",
        original_filename="delete-me.txt",
        mime_type="text/plain",
        size_bytes=9,
        sha256="a" * 64,
        object_key="workspace-1/aa/delete-me.txt",
        uploaded_by="user@example.com",
    )
    repository.update_contract_status(contract_id, WorkflowState.REVIEW_READY)

    connection.execute(
        "INSERT INTO parsed_documents VALUES ('parsed-1', ?, 'test', '1', 1, 0, '{}', '[]', CURRENT_TIMESTAMP)",
        (version_id,),
    )
    connection.execute(
        "INSERT INTO contract_reviews VALUES ('review-1', ?, 'test', 'test', '1', '{}', 'valid', CURRENT_TIMESTAMP)",
        (version_id,),
    )
    connection.execute(
        """
        INSERT INTO knowledge_indexes(
            id, workspace_id, contract_id, contract_version_id, embedding_provider,
            embedding_model, embedding_dimensions, reranker_provider, reranker_model,
            chunking_version, status
        ) VALUES ('index-1', 'workspace-1', ?, ?, 'fireworks', 'embed', 1024, 'fireworks', 'rerank', '1', 'ready')
        """,
        (contract_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO knowledge_chunks(
            id, knowledge_index_id, workspace_id, contract_id, contract_version_id,
            ordinal, content, content_sha256, metadata, embedding
        ) VALUES ('chunk-1', 'index-1', 'workspace-1', ?, ?, 0, 'secret clause', 'chunk-sha', '{}', '[]')
        """,
        (contract_id, version_id),
    )
    connection.execute(
        "INSERT INTO knowledge_index_outbox(id, workspace_id, contract_id, contract_version_id) VALUES ('knowledge-outbox-1', 'workspace-1', ?, ?)",
        (contract_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO contract_processing_runs(
            id, workspace_id, contract_id, contract_version_id, source, status
        ) VALUES ('run-1', 'workspace-1', ?, ?, 'upload', 'succeeded')
        """,
        (contract_id, version_id),
    )
    connection.execute(
        "INSERT INTO contract_processing_stages(id, processing_run_id, stage, status) VALUES ('stage-1', 'run-1', 'review', 'succeeded')"
    )
    connection.execute(
        """
        INSERT INTO outbound_email_outbox(
            id, workspace_id, contract_id, contract_version_id, thread_key,
            thread_position, message_type, to_address, from_address, subject,
            text_body, idempotency_key
        ) VALUES (
            'email-1', 'workspace-1', ?, ?, 'thread-key', 1, 'review',
            'user@example.com', 'contracts@samvid.online', 'Review', 'secret summary', 'review:delete'
        )
        """,
        (contract_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO signing_requests(id, workspace_id, contract_id, contract_version_id, created_by)
        VALUES ('request-1', 'workspace-1', ?, ?, 'user@example.com')
        """,
        (contract_id, version_id),
    )
    connection.execute(
        "INSERT INTO signers(id, signing_request_id, name, email) VALUES ('signer-1', 'request-1', 'Signer', 'signer@example.com')"
    )
    connection.execute(
        """
        INSERT INTO signer_status_events(id, signer_id, status, actor_email, actor_name)
        VALUES ('signer-event-1', 'signer-1', 'sent', 'user@example.com', 'User')
        """
    )
    connection.execute(
        """
        INSERT INTO proposed_actions(id, contract_id, action_type, payload_json, status, requested_by)
        VALUES ('action-1', ?, 'draft', '{}', 'pending', 'user@example.com')
        """,
        (contract_id,),
    )
    connection.execute(
        "INSERT INTO approvals(id, proposed_action_id, decision, decided_by) VALUES ('approval-1', 'action-1', 'approved', 'user@example.com')"
    )
    connection.execute(
        """
        INSERT INTO chat_sessions(id, workspace_id, account_id, title)
        VALUES ('chat-1', 'workspace-1', 'account-1', 'Contract question')
        """
    )
    connection.execute(
        """
        INSERT INTO chat_messages(id, workspace_id, session_id, sequence_number, role, content, citations)
        VALUES ('message-1', 'workspace-1', 'chat-1', 1, 'assistant', 'secret answer', ?)
        """,
        (json.dumps([{"contract_id": contract_id}]),),
    )
    connection.execute(
        "INSERT INTO audit_events(id, workspace_id, contract_id, actor_type, event_type, metadata_json) VALUES ('audit-1', 'workspace-1', ?, 'system', 'contract.reviewed', '{}')",
        (contract_id,),
    )
    connection.execute(
        "INSERT INTO platform_access_events(id, actor_account_id, workspace_id, contract_id, event_type) VALUES ('access-1', 'admin-1', 'workspace-1', ?, 'admin.contract.viewed')",
        (contract_id,),
    )
    connection.commit()

    deleted_objects: list[str] = []
    repository.delete_contract(
        workspace_id="workspace-1",
        contract_id=contract_id,
        deleted_by="user@example.com",
        delete_objects=lambda keys: deleted_objects.extend(keys),
    )

    assert deleted_objects == ["workspace-1/aa/delete-me.txt"]
    for table in (
        "contracts",
        "contract_versions",
        "parsed_documents",
        "contract_reviews",
        "knowledge_indexes",
        "knowledge_chunks",
        "knowledge_index_outbox",
        "contract_processing_runs",
        "contract_processing_stages",
        "outbound_email_outbox",
        "signing_requests",
        "signers",
        "signer_status_events",
        "proposed_actions",
        "approvals",
        "chat_sessions",
        "chat_messages",
        "email_threads",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    deletion_event = connection.execute(
        "SELECT contract_id, event_type, metadata_json FROM audit_events"
    ).fetchone()
    assert deletion_event["contract_id"] is None
    assert deletion_event["event_type"] == "contract.deleted"
    assert contract_id in deletion_event["metadata_json"]
    assert connection.execute(
        "SELECT contract_id FROM platform_access_events WHERE id = 'access-1'"
    ).fetchone()["contract_id"] is None
    connection.close()
