from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence
from uuid import uuid4

from contractmate.schemas.actions import Approval, ProposedAction
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.workflows.states import WorkflowState


class ContractDeletionError(ValueError):
    """Base error for a contract that cannot be deleted."""


class ContractDeletionNotFound(ContractDeletionError):
    """Raised when a contract does not belong to the requested workspace."""


class ContractDeletionConflict(ContractDeletionError):
    """Raised while a contract still has active background processing."""


_ACTIVE_PROCESSING_STATES = {
    WorkflowState.RECEIVED.value,
    WorkflowState.VALIDATING.value,
    WorkflowState.QUEUED.value,
    WorkflowState.PARSING.value,
    WorkflowState.ANALYSING.value,
    WorkflowState.VALIDATING_EVIDENCE.value,
}


class ContractRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_contract_with_version(
        self,
        *,
        workspace_id: str,
        email_thread_id: str,
        title: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        object_key: str,
        uploaded_by: str,
    ) -> tuple[str, str]:
        existing = self.connection.execute(
            self._sql(
                """
            SELECT c.id AS contract_id, v.id AS version_id
            FROM contracts c
            JOIN contract_versions v ON v.contract_id = c.id
            WHERE c.workspace_id = ? AND v.sha256 = ?
            ORDER BY v.created_at DESC
            LIMIT 1
            """
            ),
            (workspace_id, sha256),
        ).fetchone()
        if existing:
            return str(existing["contract_id"]), str(existing["version_id"])

        contract_id = str(uuid4())
        version_id = str(uuid4())
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO contracts(id, workspace_id, email_thread_id, title, status, current_version_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (contract_id, workspace_id, email_thread_id, title, WorkflowState.RECEIVED.value, version_id, uploaded_by),
            )
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO contract_versions(
                    id, contract_id, version_number, original_filename, mime_type, size_bytes, sha256, s3_object_key, uploaded_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (version_id, contract_id, 1, original_filename, mime_type, size_bytes, sha256, object_key, uploaded_by),
            )
        return contract_id, version_id

    def update_contract_status(self, contract_id: str, status: WorkflowState) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql("UPDATE contracts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                (status.value, contract_id),
            )

    def get_contract_version(self, *, contract_id: str, contract_version_id: str) -> Any | None:
        return self.connection.execute(
            self._sql(
                """
                SELECT
                    cv.*,
                    c.workspace_id,
                    c.email_thread_id,
                    c.created_by,
                    c.title
                FROM contract_versions cv
                JOIN contracts c ON c.id = cv.contract_id
                WHERE c.id = ? AND cv.id = ?
                """
            ),
            (contract_id, contract_version_id),
        ).fetchone()

    def delete_contract(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        deleted_by: str,
        delete_objects: Callable[[Sequence[str]], None],
    ) -> tuple[str, ...]:
        """Delete a completed contract and all content-bearing dependent records.

        Object deletion runs while the contract row is locked. If storage rejects
        the operation, the database transaction rolls back and the contract stays
        visible so the user can retry.
        """

        lock_suffix = " FOR UPDATE" if self.is_postgres else ""
        with self._transaction(immediate=not self.is_postgres):
            contract = self.connection.execute(
                self._sql(
                    f"""
                    SELECT id, email_thread_id, status
                    FROM contracts
                    WHERE workspace_id = ? AND id = ?{lock_suffix}
                    """
                ),
                (workspace_id, contract_id),
            ).fetchone()
            if contract is None:
                raise ContractDeletionNotFound("Contract not found.")
            if str(contract["status"]) in _ACTIVE_PROCESSING_STATES:
                raise ContractDeletionConflict("Wait for contract review processing to finish before deleting it.")

            version_rows = self.connection.execute(
                self._sql("SELECT id, s3_object_key FROM contract_versions WHERE contract_id = ?"),
                (contract_id,),
            ).fetchall()
            version_ids = [str(row["id"]) for row in version_rows]
            object_keys = tuple(
                dict.fromkeys(str(row["s3_object_key"]) for row in version_rows if row["s3_object_key"])
            )
            run_ids = self._select_ids_for_contract(
                table="contract_processing_runs",
                workspace_id=workspace_id,
                contract_id=contract_id,
            )
            action_rows = self.connection.execute(
                self._sql("SELECT id FROM proposed_actions WHERE contract_id = ?"),
                (contract_id,),
            ).fetchall()
            action_ids = [str(row["id"]) for row in action_rows]
            request_ids = self._select_ids_for_contract(
                table="signing_requests",
                workspace_id=workspace_id,
                contract_id=contract_id,
            )
            signer_ids = self._select_ids(
                table="signers",
                column="signing_request_id",
                values=request_ids,
            )
            chat_session_ids = self._contract_chat_session_ids(
                workspace_id=workspace_id,
                contract_id=contract_id,
            )

            delete_objects(object_keys)

            self._delete_by_ids("contract_processing_stages", "processing_run_id", run_ids)
            self.connection.execute(
                self._sql("DELETE FROM contract_processing_runs WHERE workspace_id = ? AND contract_id = ?"),
                (workspace_id, contract_id),
            )
            self._delete_by_ids("approvals", "proposed_action_id", action_ids)
            self.connection.execute(
                self._sql("DELETE FROM proposed_actions WHERE contract_id = ?"),
                (contract_id,),
            )
            self._delete_by_ids("signer_status_events", "signer_id", signer_ids)
            self._delete_by_ids("signers", "signing_request_id", request_ids)
            self.connection.execute(
                self._sql("DELETE FROM signing_requests WHERE workspace_id = ? AND contract_id = ?"),
                (workspace_id, contract_id),
            )
            self._delete_by_ids("chat_messages", "session_id", chat_session_ids)
            self._delete_by_ids("chat_sessions", "id", chat_session_ids)
            for table in ("knowledge_chunks", "knowledge_index_outbox", "knowledge_indexes"):
                self.connection.execute(
                    self._sql(f"DELETE FROM {table} WHERE workspace_id = ? AND contract_id = ?"),
                    (workspace_id, contract_id),
                )
            self.connection.execute(
                self._sql("DELETE FROM outbound_email_outbox WHERE workspace_id = ? AND contract_id = ?"),
                (workspace_id, contract_id),
            )
            self._delete_by_ids("parsed_documents", "contract_version_id", version_ids)
            self._delete_by_ids("contract_reviews", "contract_version_id", version_ids)
            self.connection.execute(
                self._sql("DELETE FROM audit_events WHERE workspace_id = ? AND contract_id = ?"),
                (workspace_id, contract_id),
            )
            self.connection.execute(
                self._sql(
                    "UPDATE platform_access_events SET contract_id = NULL WHERE workspace_id = ? AND contract_id = ?"
                ),
                (workspace_id, contract_id),
            )
            self.connection.execute(
                self._sql("DELETE FROM contract_versions WHERE contract_id = ?"),
                (contract_id,),
            )
            deleted = self.connection.execute(
                self._sql("DELETE FROM contracts WHERE workspace_id = ? AND id = ?"),
                (workspace_id, contract_id),
            )
            if deleted.rowcount != 1:
                raise ContractDeletionNotFound("Contract not found.")

            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO audit_events(
                        id, workspace_id, contract_id, actor_type, actor_id, event_type, metadata_json
                    ) VALUES (?, ?, NULL, 'user', ?, 'contract.deleted', ?)
                    """
                ),
                (
                    str(uuid4()),
                    workspace_id,
                    deleted_by,
                    json.dumps({"deleted_contract_id": contract_id, "version_count": len(version_ids)}),
                ),
            )
            email_thread_id = str(contract["email_thread_id"])
            self.connection.execute(
                self._sql(
                    """
                    DELETE FROM email_threads
                    WHERE workspace_id = ? AND id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM contracts
                          WHERE workspace_id = ? AND email_thread_id = ?
                      )
                    """
                ),
                (workspace_id, email_thread_id, workspace_id, email_thread_id),
            )
        return object_keys

    def save_parsed_document(self, *, contract_version_id: str, parsed_document: ParsedDocument) -> str:
        parsed_id = str(uuid4())
        warnings = [warning for page in parsed_document.pages for warning in page.warnings]
        statement = (
            """
            INSERT INTO parsed_documents(
                id, contract_version_id, parser_name, parser_version, page_count, requires_ocr, content_json, warnings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (contract_version_id) DO UPDATE SET
                id = EXCLUDED.id,
                parser_name = EXCLUDED.parser_name,
                parser_version = EXCLUDED.parser_version,
                page_count = EXCLUDED.page_count,
                requires_ocr = EXCLUDED.requires_ocr,
                content_json = EXCLUDED.content_json,
                warnings_json = EXCLUDED.warnings_json
            """
            if self.is_postgres
            else """
            INSERT OR REPLACE INTO parsed_documents(
                id, contract_version_id, parser_name, parser_version, page_count, requires_ocr, content_json, warnings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        with self._transaction():
            self.connection.execute(
                self._sql(statement),
                (
                    parsed_id,
                    contract_version_id,
                    parsed_document.parser_name,
                    parsed_document.parser_version,
                    parsed_document.page_count,
                    parsed_document.requires_ocr if self.is_postgres else int(parsed_document.requires_ocr),
                    parsed_document.model_dump_json(),
                    json.dumps(warnings),
                ),
            )
        return parsed_id

    def save_contract_review(
        self,
        *,
        contract_version_id: str,
        review: ContractReview,
        agent: Any,
        status: str = "valid",
    ) -> str:
        review_id = str(uuid4())
        statement = (
            """
            INSERT INTO contract_reviews(
                id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (contract_version_id) DO UPDATE SET
                id = EXCLUDED.id,
                model_provider = EXCLUDED.model_provider,
                model_name = EXCLUDED.model_name,
                prompt_version = EXCLUDED.prompt_version,
                review_json = EXCLUDED.review_json,
                status = EXCLUDED.status
            """
            if self.is_postgres
            else """
            INSERT OR REPLACE INTO contract_reviews(
                id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
        )
        with self._transaction():
            self.connection.execute(
                self._sql(statement),
                (
                    review_id,
                    contract_version_id,
                    agent.model_provider,
                    agent.model_name,
                    agent.prompt_version,
                    review.model_dump_json(),
                    status,
                ),
            )
        return review_id

    def finalize_contract_review(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        review: ContractReview,
        agent: Any,
        review_status: str = "valid",
        removed_findings: int = 0,
    ) -> tuple[str, str]:
        """Commit the review, visible state, audit event, and index intent together."""

        review_id = str(uuid4())
        audit_event_id = str(uuid4())
        outbox_id = str(uuid4())
        review_statement = (
            """
            INSERT INTO contract_reviews(
                id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (contract_version_id) DO UPDATE SET
                id = EXCLUDED.id,
                model_provider = EXCLUDED.model_provider,
                model_name = EXCLUDED.model_name,
                prompt_version = EXCLUDED.prompt_version,
                review_json = EXCLUDED.review_json,
                status = EXCLUDED.status
            """
            if self.is_postgres
            else """
            INSERT OR REPLACE INTO contract_reviews(
                id, contract_version_id, model_provider, model_name, prompt_version, review_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
        )
        outbox_statement = (
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
            version = self.connection.execute(
                self._sql(
                    """
                    SELECT 1
                    FROM contracts c
                    JOIN contract_versions cv ON cv.contract_id = c.id
                    WHERE c.workspace_id = ? AND c.id = ?
                      AND c.current_version_id = ? AND cv.id = ?
                    """
                ),
                (workspace_id, contract_id, contract_version_id, contract_version_id),
            ).fetchone()
            if version is None:
                raise ValueError("Contract version is not the current version in the expected workspace.")

            self.connection.execute(
                self._sql(review_statement),
                (
                    review_id,
                    contract_version_id,
                    agent.model_provider,
                    agent.model_name,
                    agent.prompt_version,
                    review.model_dump_json(),
                    review_status,
                ),
            )
            updated = self.connection.execute(
                self._sql(
                    """
                    UPDATE contracts
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = ? AND id = ? AND current_version_id = ?
                    """
                ),
                (WorkflowState.REVIEW_READY.value, workspace_id, contract_id, contract_version_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Contract could not be finalized in the expected workspace.")
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO audit_events(
                        id, workspace_id, contract_id, actor_type, actor_id, event_type, metadata_json
                    ) VALUES (?, ?, ?, 'system', NULL, 'contract.review_ready', ?)
                    """
                ),
                (audit_event_id, workspace_id, contract_id, json.dumps({"removed_findings": removed_findings})),
            )
            self.connection.execute(
                self._sql(outbox_statement),
                (outbox_id, workspace_id, contract_id, contract_version_id),
            )
            persisted_outbox = self.connection.execute(
                self._sql(
                    """
                    SELECT id
                    FROM knowledge_index_outbox
                    WHERE workspace_id = ? AND contract_version_id = ?
                    """
                ),
                (workspace_id, contract_version_id),
            ).fetchone()
            if persisted_outbox is None:
                raise RuntimeError("Knowledge indexing intent was not persisted.")
            outbox_id = str(persisted_outbox["id"])
        return review_id, outbox_id

    def get_contract_review(self, contract_id: str, *, contract_version_id: str | None = None) -> ContractReview | None:
        version_clause = "AND cr.contract_version_id = ?" if contract_version_id else ""
        parameters: tuple[str, ...] = (contract_id, contract_version_id) if contract_version_id else (contract_id,)
        row = self.connection.execute(
            self._sql(
                f"""
            SELECT cr.review_json
            FROM contract_reviews cr
            JOIN contract_versions cv ON cv.id = cr.contract_version_id
            WHERE cv.contract_id = ?
            {version_clause}
            ORDER BY cr.created_at DESC
            LIMIT 1
            """
            ),
            parameters,
        ).fetchone()
        if not row:
            return None
        review_json = row["review_json"]
        if isinstance(review_json, str):
            return ContractReview.model_validate_json(review_json)
        return ContractReview.model_validate(review_json)

    def save_proposed_action(self, action: ProposedAction) -> None:
        statement = (
            """
            INSERT INTO proposed_actions(id, contract_id, action_type, payload_json, status, requested_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                payload_json = EXCLUDED.payload_json,
                status = EXCLUDED.status,
                updated_at = CURRENT_TIMESTAMP
            """
            if self.is_postgres
            else """
            INSERT OR REPLACE INTO proposed_actions(id, contract_id, action_type, payload_json, status, requested_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
        )
        with self._transaction():
            self.connection.execute(
                self._sql(statement),
                (
                    str(action.id),
                    action.contract_id,
                    action.action_type,
                    json.dumps(action.payload),
                    action.status.value,
                    action.requested_by,
                ),
            )

    def save_approval(self, approval: Approval) -> None:
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO approvals(id, proposed_action_id, decision, decided_by, comment)
                VALUES (?, ?, ?, ?, ?)
                """
                ),
                (str(uuid4()), str(approval.proposed_action_id), approval.decision.value, approval.decided_by, approval.comment),
            )

    def _select_ids_for_contract(self, *, table: str, workspace_id: str, contract_id: str) -> list[str]:
        rows = self.connection.execute(
            self._sql(f"SELECT id FROM {table} WHERE workspace_id = ? AND contract_id = ?"),
            (workspace_id, contract_id),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _select_ids(self, *, table: str, column: str, values: Sequence[str]) -> list[str]:
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        rows = self.connection.execute(
            self._sql(f"SELECT id FROM {table} WHERE {column} IN ({placeholders})"),
            tuple(values),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _delete_by_ids(self, table: str, column: str, values: Sequence[str]) -> None:
        if not values:
            return
        placeholders = ", ".join("?" for _ in values)
        self.connection.execute(
            self._sql(f"DELETE FROM {table} WHERE {column} IN ({placeholders})"),
            tuple(values),
        )

    def _contract_chat_session_ids(self, *, workspace_id: str, contract_id: str) -> list[str]:
        session_ids = {
            str(row["id"])
            for row in self.connection.execute(
                self._sql("SELECT id FROM chat_sessions WHERE workspace_id = ? AND contract_id = ?"),
                (workspace_id, contract_id),
            ).fetchall()
        }
        rows = self.connection.execute(
            self._sql("SELECT session_id, citations FROM chat_messages WHERE workspace_id = ?"),
            (workspace_id,),
        ).fetchall()
        for row in rows:
            raw_citations = row["citations"]
            citations = json.loads(raw_citations) if isinstance(raw_citations, str) else list(raw_citations or [])
            if any(
                str(citation.get("contract_id")) == contract_id
                for citation in citations
                if isinstance(citation, dict)
            ):
                session_ids.add(str(row["session_id"]))
        return sorted(session_ids)

    def _sql(self, statement: str) -> str:
        if not self.is_postgres:
            return statement
        return statement.replace("?", "%s")

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        try:
            if immediate and not self.is_postgres:
                self.connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
