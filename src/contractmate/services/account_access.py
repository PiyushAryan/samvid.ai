from __future__ import annotations

from dataclasses import dataclass
from email.headerregistry import Address
from email.utils import parseaddr
from typing import Protocol

from contractmate.db.repositories.user_accounts import UserAccountConflictError
from contractmate.security.neon_auth import NeonAuthPrincipal


class AccountAccessError(RuntimeError):
    """Base class for account resolution failures."""


class InvalidInboundSenderError(AccountAccessError):
    """Raised when an inbound sender is missing or is not a valid mailbox."""


class SuperAdminInboundRejectedError(AccountAccessError):
    """Raised when the oversight-only account attempts contract intake."""


class AccountConflictError(AccountAccessError):
    """Raised when an identity cannot safely bind to an existing account."""


class UserAccountRecord(Protocol):
    """Account fields required by the access service."""

    id: str
    auth_subject: str | None
    email: str
    role: str
    state: str
    personal_workspace_id: str | None


class UserAccountRepositoryProtocol(Protocol):
    """Atomic persistence operations required for account resolution."""

    def get_by_email(self, email: str) -> UserAccountRecord | None: ...

    def provision_inbound_user(
        self,
        *,
        email: str,
        display_name: str | None = None,
    ) -> UserAccountRecord: ...

    def provision_verified_user(
        self,
        *,
        auth_subject: str,
        email: str,
        display_name: str | None = None,
    ) -> UserAccountRecord: ...

    def bootstrap_super_admin(
        self,
        *,
        email: str,
        auth_subject: str | None = None,
        display_name: str | None = None,
    ) -> UserAccountRecord: ...


@dataclass(frozen=True, slots=True)
class InboundAccountResolution:
    account_id: str
    email: str
    workspace_id: str


@dataclass(frozen=True, slots=True)
class VerifiedAccountResolution:
    account_id: str
    email: str
    role: str
    state: str
    workspace_id: str | None


class AccountAccessService:
    """Resolve private Samvid accounts for inbound mail and verified users."""

    def __init__(
        self,
        *,
        repository: UserAccountRepositoryProtocol,
        super_admin_email: str,
    ) -> None:
        try:
            self.super_admin_email = _parse_mailbox(super_admin_email)[1]
        except InvalidInboundSenderError as exc:
            raise ValueError("SAMVID_SUPER_ADMIN_EMAIL must be a valid mailbox") from exc
        self.repository = repository

    def resolve_inbound_sender(self, sender: str) -> InboundAccountResolution:
        display_name, email = _parse_mailbox(sender)
        if email == self.super_admin_email:
            raise SuperAdminInboundRejectedError(
                "The oversight-only super-admin account cannot receive personal contracts"
            )

        account = self.repository.get_by_email(email)
        if account is None:
            try:
                account = self.repository.provision_inbound_user(
                    email=email,
                    display_name=display_name or None,
                )
            except UserAccountConflictError as exc:
                raise AccountConflictError(str(exc)) from exc
        return _inbound_resolution(account, expected_email=email)

    def resolve_verified_principal(
        self,
        principal: NeonAuthPrincipal,
    ) -> VerifiedAccountResolution:
        if not principal.email_verified:
            raise AccountConflictError("A verified email is required to provision a Samvid account")

        _, email = _parse_mailbox(principal.email)
        existing = self.repository.get_by_email(email)
        _validate_identity_binding(existing, subject=principal.subject, expected_email=email)

        if email == self.super_admin_email:
            try:
                account = self.repository.bootstrap_super_admin(
                    auth_subject=principal.subject,
                    email=email,
                    display_name=principal.name or None,
                )
            except UserAccountConflictError as exc:
                raise AccountConflictError(str(exc)) from exc
            return _verified_resolution(
                account,
                subject=principal.subject,
                expected_email=email,
                expected_role="super_admin",
                workspace_required=False,
            )

        try:
            account = self.repository.provision_verified_user(
                auth_subject=principal.subject,
                email=email,
                display_name=principal.name or None,
            )
        except UserAccountConflictError as exc:
            raise AccountConflictError(str(exc)) from exc
        return _verified_resolution(
            account,
            subject=principal.subject,
            expected_email=email,
            expected_role="user",
            workspace_required=True,
        )


def normalize_mailbox(sender: str) -> str:
    """Return the canonical mailbox used for account identity comparisons."""

    return _parse_mailbox(sender)[1]


def _parse_mailbox(sender: str) -> tuple[str, str]:
    if not isinstance(sender, str) or not sender.strip():
        raise InvalidInboundSenderError("Inbound sender is required")
    if any(character in sender for character in ("\r", "\n", "\x00")):
        raise InvalidInboundSenderError("Inbound sender contains invalid control characters")

    display_name, mailbox = parseaddr(sender)
    mailbox = mailbox.strip()
    if not mailbox:
        raise InvalidInboundSenderError("Inbound sender must contain one valid mailbox")

    try:
        address = Address(addr_spec=mailbox)
    except (TypeError, ValueError) as exc:
        raise InvalidInboundSenderError("Inbound sender must contain one valid mailbox") from exc
    if not address.username or not address.domain:
        raise InvalidInboundSenderError("Inbound sender must contain a complete mailbox")

    normalized = f"{address.username}@{address.domain}".casefold()
    return display_name.strip(), normalized


def _inbound_resolution(
    account: UserAccountRecord,
    *,
    expected_email: str,
) -> InboundAccountResolution:
    _validate_account_email(account, expected_email)
    if account.role != "user":
        raise AccountConflictError("Inbound contracts require a normal user account")
    if account.state not in {"active", "unclaimed"}:
        raise AccountConflictError("Inbound account is not active or claimable")
    if not account.personal_workspace_id:
        raise AccountConflictError("Inbound account does not have a private workspace")
    return InboundAccountResolution(
        account_id=account.id,
        email=expected_email,
        workspace_id=account.personal_workspace_id,
    )


def _verified_resolution(
    account: UserAccountRecord,
    *,
    subject: str,
    expected_email: str,
    expected_role: str,
    workspace_required: bool,
) -> VerifiedAccountResolution:
    _validate_account_email(account, expected_email)
    if account.auth_subject != subject:
        raise AccountConflictError("Verified identity was not bound to the resolved account")
    if account.role != expected_role:
        raise AccountConflictError("Resolved account has an incompatible platform role")
    if account.state != "active":
        raise AccountConflictError("Verified account is not active")
    if workspace_required and not account.personal_workspace_id:
        raise AccountConflictError("Normal user account does not have a private workspace")
    if not workspace_required and account.personal_workspace_id is not None:
        raise AccountConflictError("The super-admin account cannot own a personal workspace")
    return VerifiedAccountResolution(
        account_id=account.id,
        email=expected_email,
        role=account.role,
        state=account.state,
        workspace_id=account.personal_workspace_id,
    )


def _validate_identity_binding(
    account: UserAccountRecord | None,
    *,
    subject: str,
    expected_email: str,
) -> None:
    if account is None:
        return
    _validate_account_email(account, expected_email)
    if account.auth_subject is not None and account.auth_subject != subject:
        raise AccountConflictError("Email is already bound to a different Neon identity")


def _validate_account_email(account: UserAccountRecord, expected_email: str) -> None:
    try:
        account_email = normalize_mailbox(account.email)
    except InvalidInboundSenderError as exc:
        raise AccountConflictError("Repository returned an account with an invalid email") from exc
    if account_email != expected_email:
        raise AccountConflictError("Repository returned an account for a different email")
