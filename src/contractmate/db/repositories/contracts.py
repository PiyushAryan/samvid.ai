from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4

from contractmate.schemas.actions import Approval, ProposedAction
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.workflows.states import WorkflowState


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
