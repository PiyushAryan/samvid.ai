from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from uuid import uuid4


class UserAccountConflictError(ValueError):
    """Raised when one verified identity would take over another account."""


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: str
    auth_subject: str | None
    email: str
    display_name: str | None
    role: str
    state: str
    personal_workspace_id: str | None
    source: str
    claimed_at: Any | None
    created_at: Any
    updated_at: Any
    contract_count: int = 0


@dataclass(frozen=True, slots=True)
class PlatformAccessEvent:
    id: str
    actor_account_id: str
    target_account_id: str | None
    workspace_id: str | None
    contract_id: str | None
    event_type: str
    metadata: dict[str, Any]
    created_at: Any
    actor_email: str | None = None
    target_user_email: str | None = None
    contract_title: str | None = None


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not normalized or "@" not in normalized:
        raise ValueError("A valid email address is required")
    return normalized


class UserAccountRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def get_by_subject(self, auth_subject: str) -> UserAccount | None:
        return self._get("auth_subject = ?", (auth_subject,))

    def get_by_email(self, email: str) -> UserAccount | None:
        return self._get("email = ?", (normalize_email(email),))

    def get_by_id(self, account_id: str) -> UserAccount | None:
        return self._get("id = ?", (account_id,))

    def get_by_workspace(self, workspace_id: str) -> UserAccount | None:
        return self._get("personal_workspace_id = ?", (workspace_id,))

    def provision_verified_user(
        self,
        *,
        auth_subject: str,
        email: str,
        display_name: str | None = None,
    ) -> UserAccount:
        normalized_email = normalize_email(email)
        if not auth_subject.strip():
            raise ValueError("auth_subject is required")

        with self._transaction(immediate=not self.is_postgres):
            by_subject = self._get_in_transaction("auth_subject = ?", (auth_subject,))
            if by_subject:
                if by_subject.email != normalized_email:
                    raise UserAccountConflictError("Verified identity is already bound to another email")
                if by_subject.role == "super_admin":
                    return by_subject
                self._update_claimed_account(by_subject.id, auth_subject, display_name)
                return self._require_by_id(by_subject.id)

            by_email = self._get_in_transaction("email = ?", (normalized_email,))
            if by_email:
                if by_email.auth_subject not in (None, auth_subject):
                    raise UserAccountConflictError("Email is already bound to another verified identity")
                if by_email.role == "super_admin":
                    raise UserAccountConflictError("Super-admin accounts must be bound explicitly")
                self._update_claimed_account(by_email.id, auth_subject, display_name)
                return self._require_by_id(by_email.id)

            account_id = str(uuid4())
            workspace_id = self._new_workspace_id()
            self._insert_account(
                account_id=account_id,
                auth_subject=auth_subject,
                email=normalized_email,
                display_name=display_name,
                role="user",
                state="active",
                workspace_id=workspace_id,
                source="signup",
                claimed=True,
            )
            account = self._get_in_transaction("auth_subject = ?", (auth_subject,))
            if account is None:
                account = self._get_in_transaction("email = ?", (normalized_email,))
            if account is None:
                raise RuntimeError("Unable to provision verified user account")
            if account.auth_subject != auth_subject or account.email != normalized_email:
                raise UserAccountConflictError("Account was concurrently bound to another identity")
            return account

    def provision_inbound_user(self, *, email: str, display_name: str | None = None) -> UserAccount:
        normalized_email = normalize_email(email)
        with self._transaction(immediate=not self.is_postgres):
            existing = self._get_in_transaction("email = ?", (normalized_email,))
            if existing:
                if existing.role == "super_admin":
                    raise UserAccountConflictError("Super-admin email cannot receive personal contracts")
                return existing

            self._insert_account(
                account_id=str(uuid4()),
                auth_subject=None,
                email=normalized_email,
                display_name=display_name,
                role="user",
                state="unclaimed",
                workspace_id=self._new_workspace_id(),
                source="inbound_email",
                claimed=False,
            )
            account = self._get_in_transaction("email = ?", (normalized_email,))
            if account is None:
                raise RuntimeError("Unable to provision inbound user account")
            return account

    def bootstrap_super_admin(
        self,
        *,
        email: str,
        auth_subject: str | None = None,
        display_name: str | None = None,
    ) -> UserAccount:
        normalized_email = normalize_email(email)
        if auth_subject is not None and not auth_subject.strip():
            raise ValueError("auth_subject cannot be blank")

        with self._transaction(immediate=not self.is_postgres):
            if auth_subject:
                by_subject = self._get_in_transaction("auth_subject = ?", (auth_subject,))
                if by_subject and by_subject.email != normalized_email:
                    raise UserAccountConflictError("Verified identity is already bound to another email")

            existing = self._get_in_transaction("email = ?", (normalized_email,))
            if existing:
                if existing.role != "super_admin":
                    raise UserAccountConflictError("A personal account already uses the super-admin email")
                if auth_subject is not None and existing.auth_subject not in (None, auth_subject):
                    raise UserAccountConflictError("Super-admin email is already bound to another identity")
                self.connection.execute(
                    self._sql(
                        """
                        UPDATE user_accounts
                        SET auth_subject = COALESCE(?, auth_subject),
                            display_name = COALESCE(?, display_name),
                            state = ?, claimed_at = CASE WHEN ? THEN COALESCE(claimed_at, CURRENT_TIMESTAMP) ELSE claimed_at END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """
                    ),
                    (
                        auth_subject,
                        display_name,
                        "active" if auth_subject else existing.state,
                        auth_subject is not None,
                        existing.id,
                    ),
                )
                return self._require_by_id(existing.id)

            self._insert_account(
                account_id=str(uuid4()),
                auth_subject=auth_subject,
                email=normalized_email,
                display_name=display_name,
                role="super_admin",
                state="active" if auth_subject else "unclaimed",
                workspace_id=None,
                source="signup",
                claimed=auth_subject is not None,
            )
            account = self._get_in_transaction("email = ?", (normalized_email,))
            if account is None:
                raise RuntimeError("Unable to bootstrap super-admin account")
            if account.role != "super_admin" or account.personal_workspace_id is not None:
                raise UserAccountConflictError("A personal account already uses the super-admin email")
            if auth_subject is not None and account.auth_subject != auth_subject:
                raise UserAccountConflictError("Super-admin account was concurrently bound to another identity")
            return account

    def list_accounts(
        self,
        *,
        role: str | None = None,
        state: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[UserAccount], int]:
        if role not in (None, "user", "super_admin"):
            raise ValueError("Invalid account role")
        if state not in (None, "unclaimed", "active"):
            raise ValueError("Invalid account state")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        conditions: list[str] = []
        params: list[Any] = []
        if role:
            conditions.append("ua.role = ?")
            params.append(role)
        if state:
            conditions.append("ua.state = ?")
            params.append(state)
        if search:
            conditions.append("(lower(ua.email) LIKE ? OR lower(COALESCE(ua.display_name, '')) LIKE ?)")
            pattern = f"%{search.strip().casefold()}%"
            params.extend((pattern, pattern))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total_row = self.connection.execute(
            self._sql(f"SELECT COUNT(*) AS total FROM user_accounts ua {where}"),
            tuple(params),
        ).fetchone()
        rows = self.connection.execute(
            self._sql(
                f"""
                SELECT ua.*, COUNT(c.id) AS contract_count
                FROM user_accounts ua
                LEFT JOIN contracts c ON c.workspace_id = ua.personal_workspace_id
                {where}
                GROUP BY ua.id
                ORDER BY ua.created_at DESC, ua.id
                LIMIT ? OFFSET ?
                """
            ),
            (*params, limit, offset),
        ).fetchall()
        return [self._account_from_row(row) for row in rows], int(total_row["total"])

    def record_access_event(
        self,
        *,
        actor_account_id: str,
        event_type: str,
        target_account_id: str | None = None,
        workspace_id: str | None = None,
        contract_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid4())
        with self._transaction():
            self.connection.execute(
                self._sql(
                    """
                    INSERT INTO platform_access_events(
                        id, actor_account_id, target_account_id, workspace_id, contract_id, event_type, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    event_id,
                    actor_account_id,
                    target_account_id,
                    workspace_id,
                    contract_id,
                    event_type,
                    json.dumps(dict(metadata or {})),
                ),
            )
        return event_id

    def list_access_events(
        self,
        *,
        actor_account_id: str | None = None,
        target_account_id: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PlatformAccessEvent]:
        conditions: list[str] = []
        params: list[Any] = []
        if actor_account_id:
            conditions.append("actor_account_id = ?")
            params.append(actor_account_id)
        if target_account_id:
            conditions.append("target_account_id = ?")
            params.append(target_account_id)
        if search:
            pattern = f"%{search.strip().casefold()}%"
            conditions.append(
                "(lower(COALESCE(actor.email, '')) LIKE ? OR lower(COALESCE(target.email, '')) LIKE ? OR lower(COALESCE(contract.title, '')) LIKE ? OR lower(pae.event_type) LIKE ?)"
            )
            params.extend((pattern, pattern, pattern, pattern))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.connection.execute(
            self._sql(
                f"""
                SELECT
                    pae.*,
                    actor.email AS actor_email,
                    target.email AS target_user_email,
                    contract.title AS contract_title
                FROM platform_access_events pae
                LEFT JOIN user_accounts actor ON actor.id = pae.actor_account_id
                LEFT JOIN user_accounts target ON target.id = pae.target_account_id
                LEFT JOIN contracts contract ON contract.id = pae.contract_id
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """
            ),
            (*params, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _get(self, condition: str, params: tuple[Any, ...]) -> UserAccount | None:
        row = self.connection.execute(
            self._sql(f"SELECT ua.*, 0 AS contract_count FROM user_accounts ua WHERE {condition} LIMIT 1"),
            params,
        ).fetchone()
        return self._account_from_row(row) if row else None

    def _get_in_transaction(self, condition: str, params: tuple[Any, ...]) -> UserAccount | None:
        row = self.connection.execute(
            self._sql(f"SELECT ua.*, 0 AS contract_count FROM user_accounts ua WHERE {condition} LIMIT 1"),
            params,
        ).fetchone()
        return self._account_from_row(row) if row else None

    def _require_by_id(self, account_id: str) -> UserAccount:
        account = self._get_in_transaction("id = ?", (account_id,))
        if account is None:
            raise RuntimeError("User account disappeared during transaction")
        return account

    def _update_claimed_account(self, account_id: str, auth_subject: str, display_name: str | None) -> None:
        updated = self.connection.execute(
            self._sql(
                """
                UPDATE user_accounts
                SET auth_subject = ?, state = 'active',
                    display_name = COALESCE(?, display_name),
                    claimed_at = COALESCE(claimed_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND (auth_subject IS NULL OR auth_subject = ?)
                """
            ),
            (auth_subject, display_name, account_id, auth_subject),
        )
        if updated.rowcount != 1:
            raise UserAccountConflictError("Account was concurrently bound to another identity")

    def _insert_account(
        self,
        *,
        account_id: str,
        auth_subject: str | None,
        email: str,
        display_name: str | None,
        role: str,
        state: str,
        workspace_id: str | None,
        source: str,
        claimed: bool,
    ) -> None:
        statement = (
            """
            INSERT INTO user_accounts(
                id, auth_subject, email, display_name, role, state, personal_workspace_id, source, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT DO NOTHING
            """
            if self.is_postgres
            else """
            INSERT OR IGNORE INTO user_accounts(
                id, auth_subject, email, display_name, role, state, personal_workspace_id, source, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            """
        )
        self.connection.execute(
            self._sql(statement),
            (account_id, auth_subject, email, display_name, role, state, workspace_id, source, claimed),
        )

    @staticmethod
    def _new_workspace_id() -> str:
        return f"user-{uuid4()}"

    @staticmethod
    def _account_from_row(row: Any) -> UserAccount:
        keys = row.keys()
        return UserAccount(
            id=str(row["id"]),
            auth_subject=str(row["auth_subject"]) if row["auth_subject"] is not None else None,
            email=str(row["email"]),
            display_name=str(row["display_name"]) if row["display_name"] is not None else None,
            role=str(row["role"]),
            state=str(row["state"]),
            personal_workspace_id=(
                str(row["personal_workspace_id"]) if row["personal_workspace_id"] is not None else None
            ),
            source=str(row["source"]),
            claimed_at=row["claimed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            contract_count=int(row["contract_count"]) if "contract_count" in keys else 0,
        )

    @staticmethod
    def _event_from_row(row: Any) -> PlatformAccessEvent:
        raw_metadata = row["metadata"]
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else dict(raw_metadata)
        return PlatformAccessEvent(
            id=str(row["id"]),
            actor_account_id=str(row["actor_account_id"]),
            target_account_id=str(row["target_account_id"]) if row["target_account_id"] is not None else None,
            workspace_id=str(row["workspace_id"]) if row["workspace_id"] is not None else None,
            contract_id=str(row["contract_id"]) if row["contract_id"] is not None else None,
            event_type=str(row["event_type"]),
            metadata=metadata,
            created_at=row["created_at"],
            actor_email=str(row["actor_email"]) if row["actor_email"] is not None else None,
            target_user_email=str(row["target_user_email"]) if row["target_user_email"] is not None else None,
            contract_title=str(row["contract_title"]) if row["contract_title"] is not None else None,
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
