from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator
from uuid import uuid4

from contractmate.schemas.signing import (
    SignerCreate,
    SignerOut,
    SignerStatus,
    SignerStatusEventCreate,
    SignerStatusEventOut,
    SigningRequestCreate,
    SigningRequestOut,
    SigningRequestStatus,
    TERMINAL_REQUEST_STATUSES,
    TERMINAL_SIGNER_STATUSES,
)


class SigningError(Exception):
    status_code = 400

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class SigningNotFound(SigningError):
    status_code = 404

    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(message, code="not_found")


class SigningConflict(SigningError):
    status_code = 409

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message, code=code)


class SigningRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_request(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        payload: SigningRequestCreate,
        actor_email: str,
        actor_name: str,
    ) -> SigningRequestOut:
        contract = self._get_contract(workspace_id=workspace_id, contract_id=contract_id)
        if contract is None:
            raise SigningNotFound()
        if not contract["current_version_id"]:
            raise SigningConflict("Contract has no current version to pin.", code="contract_version_missing")

        signer_emails = [signer.email.casefold() for signer in payload.signers]
        if len(signer_emails) != len(set(signer_emails)):
            raise SigningConflict("Signer emails must be unique within a signing request.", code="duplicate_signer_email")

        active = self._active_request_for_contract(workspace_id=workspace_id, contract_id=contract_id)
        if active is not None:
            raise SigningConflict("Contract already has an active signing request.", code="active_request_exists")

        request_id = str(uuid4())
        now = _now()
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO signing_requests(
                    id, workspace_id, contract_id, contract_version_id, active, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (
                    request_id,
                    workspace_id,
                    contract_id,
                    contract["current_version_id"],
                    self._db_bool(True),
                    actor_email,
                    now,
                ),
            )
            for index, signer in enumerate(payload.signers):
                self._insert_signer(
                    request_id=request_id,
                    signer=signer,
                    display_order=signer.display_order if signer.display_order is not None else index,
                    actor_email=actor_email,
                    actor_name=actor_name,
                )
                self._record_audit(
                    workspace_id=workspace_id,
                    contract_id=contract_id,
                    actor_email=actor_email,
                    event_type="signer.created",
                    metadata={"request_id": request_id, "email": signer.email},
                )
            self._record_audit(
                workspace_id=workspace_id,
                contract_id=contract_id,
                actor_email=actor_email,
                event_type="signing_request.created",
                metadata={"request_id": request_id, "signer_count": len(payload.signers)},
            )
        request = self.get_request(workspace_id=workspace_id, request_id=request_id)
        assert request is not None
        return request

    def add_signer(
        self,
        *,
        workspace_id: str,
        request_id: str,
        signer: SignerCreate,
        actor_email: str,
        actor_name: str,
    ) -> SigningRequestOut:
        request = self.get_request(workspace_id=workspace_id, request_id=request_id)
        if request is None:
            raise SigningNotFound()
        if request.status in TERMINAL_REQUEST_STATUSES:
            raise SigningConflict("Cannot add a signer to a terminal signing request.", code="request_terminal")

        row = self.connection.execute(
            self._sql("SELECT COALESCE(MAX(display_order), -1) AS max_order FROM signers WHERE signing_request_id = ?"),
            (request_id,),
        ).fetchone()
        display_order = signer.display_order if signer.display_order is not None else int(row["max_order"]) + 1

        with self._transaction():
            try:
                self._insert_signer(
                    request_id=request_id,
                    signer=signer,
                    display_order=display_order,
                    actor_email=actor_email,
                    actor_name=actor_name,
                )
            except Exception as exc:
                if _is_unique_violation(exc):
                    raise SigningConflict("Signer email already exists for this request.", code="duplicate_signer_email") from exc
                raise
            self._record_audit(
                workspace_id=workspace_id,
                contract_id=request.contract_id,
                actor_email=actor_email,
                event_type="signer.created",
                metadata={"request_id": request_id, "email": signer.email},
            )
        updated = self.get_request(workspace_id=workspace_id, request_id=request_id)
        assert updated is not None
        return updated

    def append_event(
        self,
        *,
        workspace_id: str,
        signer_id: str,
        payload: SignerStatusEventCreate,
        actor_email: str,
        actor_name: str,
    ) -> SigningRequestOut:
        signer_row = self._get_signer_with_request(workspace_id=workspace_id, signer_id=signer_id)
        if signer_row is None:
            raise SigningNotFound()

        existing = self.connection.execute(
            self._sql("SELECT * FROM signer_status_events WHERE id = ?"),
            (payload.id,),
        ).fetchone()
        if existing is not None:
            if (
                existing["signer_id"] == signer_id
                and existing["status"] == payload.status.value
                and (existing["note"] or None) == (payload.note or None)
            ):
                request = self.get_request(workspace_id=workspace_id, request_id=signer_row["request_id"])
                assert request is not None
                return request
            raise SigningConflict("Event id was already used for a different signer status event.", code="event_id_conflict")

        latest = self._latest_event_for_signer(signer_id)
        if latest is not None and latest["status"] == payload.status.value:
            raise SigningConflict("Signer already has this latest status.", code="duplicate_consecutive_status")

        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO signer_status_events(id, signer_id, status, note, actor_email, actor_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (payload.id, signer_id, payload.status.value, payload.note, actor_email, actor_name, _now()),
            )
            self._record_audit(
                workspace_id=workspace_id,
                contract_id=signer_row["contract_id"],
                actor_email=actor_email,
                event_type="signer.status_changed",
                metadata={
                    "request_id": signer_row["request_id"],
                    "signer_id": signer_id,
                    "status": payload.status.value,
                    "note": payload.note,
                },
            )

        request = self.get_request(workspace_id=workspace_id, request_id=signer_row["request_id"])
        assert request is not None
        self._sync_request_active_flag(request)
        updated = self.get_request(workspace_id=workspace_id, request_id=signer_row["request_id"])
        assert updated is not None
        return updated

    def get_request(self, *, workspace_id: str, request_id: str) -> SigningRequestOut | None:
        rows = self._fetch_request_rows(workspace_id=workspace_id, request_id=request_id)
        if not rows:
            return None
        return self._build_request(rows)

    def list_contract_requests(self, *, workspace_id: str, contract_id: str) -> list[SigningRequestOut]:
        if self._get_contract(workspace_id=workspace_id, contract_id=contract_id) is None:
            raise SigningNotFound()
        rows = self.connection.execute(
            self._sql(
                """
            SELECT sr.*, c.title AS contract_title
            FROM signing_requests sr
            JOIN contracts c ON c.id = sr.contract_id
            WHERE sr.workspace_id = ? AND sr.contract_id = ?
            ORDER BY sr.created_at DESC
            """
            ),
            (workspace_id, contract_id),
        ).fetchall()
        requests: list[SigningRequestOut] = []
        for row in rows:
            request = self.get_request(workspace_id=workspace_id, request_id=row["id"])
            if request is not None:
                requests.append(request)
        return requests

    def list_requests(self, *, workspace_id: str, status: SigningRequestStatus | None = None) -> list[SigningRequestOut]:
        rows = self.connection.execute(
            self._sql(
                """
            SELECT sr.*, c.title AS contract_title
            FROM signing_requests sr
            JOIN contracts c ON c.id = sr.contract_id
            WHERE sr.workspace_id = ?
            ORDER BY sr.created_at DESC
            """
            ),
            (workspace_id,),
        ).fetchall()
        requests = [request for row in rows if (request := self.get_request(workspace_id=workspace_id, request_id=row["id"]))]
        if status is not None:
            requests = [request for request in requests if request.status == status]
        return requests

    def signing_summary_for_contracts(self, *, workspace_id: str, contract_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not contract_ids:
            return {}
        summaries: dict[str, dict[str, Any]] = {}
        placeholders = ", ".join(["?"] * len(contract_ids))
        rows = self.connection.execute(
            self._sql(
                f"""
            SELECT id
            FROM signing_requests
            WHERE workspace_id = ? AND contract_id IN ({placeholders}) AND active = ?
            """
            ),
            (workspace_id, *contract_ids, self._db_bool(True)),
        ).fetchall()
        for row in rows:
            request = self.get_request(workspace_id=workspace_id, request_id=row["id"])
            if request is None:
                continue
            required = [signer for signer in request.signers if signer.required]
            summaries[request.contract_id] = {
                "active_request_id": request.id,
                "status": request.status.value,
                "required_signed": sum(1 for signer in required if signer.latest_status == SignerStatus.SIGNED),
                "required_total": len(required),
                "signer_total": len(request.signers),
            }
        return summaries

    def _insert_signer(
        self,
        *,
        request_id: str,
        signer: SignerCreate,
        display_order: int,
        actor_email: str,
        actor_name: str,
    ) -> str:
        signer_id = str(uuid4())
        now = _now()
        try:
            self.connection.execute(
                self._sql(
                    """
                INSERT INTO signers(id, signing_request_id, name, email, role, required, display_order, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
                ),
                (
                    signer_id,
                    request_id,
                    signer.name,
                    signer.email,
                    signer.role,
                    self._db_bool(signer.required),
                    display_order,
                    now,
                ),
            )
        except Exception as exc:
            if _is_unique_violation(exc):
                raise SigningConflict("Signer email already exists for this request.", code="duplicate_signer_email") from exc
            raise
        self.connection.execute(
            self._sql(
                """
            INSERT INTO signer_status_events(id, signer_id, status, note, actor_email, actor_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            ),
            (str(uuid4()), signer_id, SignerStatus.PENDING.value, "Signer added.", actor_email, actor_name, now),
        )
        return signer_id

    def _fetch_request_rows(self, *, workspace_id: str, request_id: str) -> list[Any]:
        return self.connection.execute(
            self._sql(
                """
            SELECT sr.*, c.title AS contract_title
            FROM signing_requests sr
            JOIN contracts c ON c.id = sr.contract_id
            WHERE sr.workspace_id = ? AND sr.id = ?
            """
            ),
            (workspace_id, request_id),
        ).fetchall()

    def _build_request(self, request_rows: list[Any]) -> SigningRequestOut:
        request_row = request_rows[0]
        signer_rows = self.connection.execute(
            self._sql(
                """
            SELECT *
            FROM signers
            WHERE signing_request_id = ?
            ORDER BY display_order ASC, created_at ASC
            """
            ),
            (request_row["id"],),
        ).fetchall()
        signers = [self._build_signer(row) for row in signer_rows]
        status = derive_request_status(signers)
        return SigningRequestOut(
            id=request_row["id"],
            workspace_id=request_row["workspace_id"],
            contract_id=request_row["contract_id"],
            contract_title=request_row["contract_title"],
            contract_version_id=request_row["contract_version_id"],
            status=status,
            active=bool(request_row["active"]),
            created_by=request_row["created_by"],
            created_at=str(request_row["created_at"]),
            closed_at=str(request_row["closed_at"]) if request_row["closed_at"] else None,
            signers=signers,
        )

    def _build_signer(self, signer_row: Any) -> SignerOut:
        event_rows = self.connection.execute(
            self._sql(
                """
            SELECT *
            FROM signer_status_events
            WHERE signer_id = ?
            ORDER BY created_at ASC, id ASC
            """
            ),
            (signer_row["id"],),
        ).fetchall()
        events = [
            SignerStatusEventOut(
                id=row["id"],
                signer_id=row["signer_id"],
                status=SignerStatus(row["status"]),
                note=row["note"],
                actor_email=row["actor_email"],
                actor_name=row["actor_name"],
                created_at=str(row["created_at"]),
            )
            for row in event_rows
        ]
        latest = events[-1].status if events else SignerStatus.PENDING
        return SignerOut(
            id=signer_row["id"],
            name=signer_row["name"],
            email=signer_row["email"],
            role=signer_row["role"],
            required=bool(signer_row["required"]),
            display_order=int(signer_row["display_order"]),
            latest_status=latest,
            created_at=str(signer_row["created_at"]),
            events=events,
        )

    def _sync_request_active_flag(self, request: SigningRequestOut) -> None:
        should_be_active = request.status not in TERMINAL_REQUEST_STATUSES
        if should_be_active:
            other = self._active_request_for_contract(workspace_id=request.workspace_id, contract_id=request.contract_id)
            if other is not None and other["id"] != request.id:
                raise SigningConflict(
                    "Cannot reactivate this request while another signing request is active.",
                    code="active_request_exists",
                )
        if request.active == should_be_active:
            return
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                UPDATE signing_requests
                SET active = ?, closed_at = CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END
                WHERE id = ?
                """
                ),
                (self._db_bool(should_be_active), self._db_bool(should_be_active), request.id),
            )

    def _active_request_for_contract(self, *, workspace_id: str, contract_id: str) -> Any | None:
        return self.connection.execute(
            self._sql(
                """
            SELECT *
            FROM signing_requests
            WHERE workspace_id = ? AND contract_id = ? AND active = ?
            LIMIT 1
            """
            ),
            (workspace_id, contract_id, self._db_bool(True)),
        ).fetchone()

    def _get_contract(self, *, workspace_id: str, contract_id: str) -> Any | None:
        return self.connection.execute(
            self._sql("SELECT * FROM contracts WHERE workspace_id = ? AND id = ?"),
            (workspace_id, contract_id),
        ).fetchone()

    def _get_signer_with_request(self, *, workspace_id: str, signer_id: str) -> Any | None:
        return self.connection.execute(
            self._sql(
                """
            SELECT
                s.id AS signer_id,
                s.signing_request_id AS request_id,
                sr.contract_id,
                sr.workspace_id
            FROM signers s
            JOIN signing_requests sr ON sr.id = s.signing_request_id
            WHERE sr.workspace_id = ? AND s.id = ?
            """
            ),
            (workspace_id, signer_id),
        ).fetchone()

    def _latest_event_for_signer(self, signer_id: str) -> Any | None:
        return self.connection.execute(
            self._sql(
                """
            SELECT *
            FROM signer_status_events
            WHERE signer_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
            ),
            (signer_id,),
        ).fetchone()

    def _record_audit(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        actor_email: str,
        event_type: str,
        metadata: dict[str, Any],
    ) -> None:
        self.connection.execute(
            self._sql(
                """
            INSERT INTO audit_events(id, workspace_id, contract_id, actor_type, actor_id, event_type, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            ),
            (str(uuid4()), workspace_id, contract_id, "user", actor_email, event_type, json.dumps(metadata), _now()),
        )

    def _sql(self, statement: str) -> str:
        if not self.is_postgres:
            return statement
        return statement.replace("?", "%s")

    def _db_bool(self, value: bool) -> bool | int:
        return value if self.is_postgres else int(value)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


def derive_request_status(signers: list[SignerOut]) -> SigningRequestStatus:
    if not signers or all(signer.latest_status == SignerStatus.PENDING for signer in signers):
        return SigningRequestStatus.NOT_STARTED

    required = [signer for signer in signers if signer.required]
    for terminal_status in (SignerStatus.DECLINED, SignerStatus.EXPIRED, SignerStatus.CANCELLED):
        if any(signer.latest_status == terminal_status for signer in required):
            return SigningRequestStatus(terminal_status.value)

    if required and all(signer.latest_status == SignerStatus.SIGNED for signer in required):
        return SigningRequestStatus.COMPLETED

    if not required and any(signer.latest_status in TERMINAL_SIGNER_STATUSES for signer in signers):
        return SigningRequestStatus.IN_PROGRESS

    return SigningRequestStatus.IN_PROGRESS


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _is_unique_violation(exc: Exception) -> bool:
    message = str(exc).lower()
    return "unique" in message or "duplicate key" in message
