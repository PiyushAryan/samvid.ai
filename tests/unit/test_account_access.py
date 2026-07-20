from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from contractmate.security.neon_auth import NeonAuthPrincipal
from contractmate.services.account_access import (
    AccountAccessService,
    AccountConflictError,
    InvalidInboundSenderError,
    SuperAdminInboundRejectedError,
)


@dataclass(frozen=True)
class FakeAccount:
    id: str
    email: str
    role: str = "user"
    state: str = "unclaimed"
    personal_workspace_id: str | None = "workspace-1"
    auth_subject: str | None = None


class FakeUserAccountRepository:
    def __init__(self, *accounts: FakeAccount) -> None:
        self.accounts = {account.email.casefold(): account for account in accounts}
        self.inbound_calls: list[tuple[str, str | None]] = []

    def get_by_email(self, email: str) -> FakeAccount | None:
        return self.accounts.get(email)

    def provision_inbound_user(
        self,
        *,
        email: str,
        display_name: str | None = None,
    ) -> FakeAccount:
        self.inbound_calls.append((email, display_name))
        account = FakeAccount(
            id=f"account-{len(self.accounts) + 1}",
            email=email,
            personal_workspace_id=f"workspace-{len(self.accounts) + 1}",
        )
        self.accounts[email] = account
        return account

    def provision_verified_user(
        self,
        *,
        auth_subject: str,
        email: str,
        display_name: str | None = None,
    ) -> FakeAccount:
        existing = self.accounts.get(email)
        account = (
            replace(existing, auth_subject=auth_subject, state="active")
            if existing
            else FakeAccount(
                id=f"account-{len(self.accounts) + 1}",
                email=email,
                state="active",
                auth_subject=auth_subject,
                personal_workspace_id=f"workspace-{len(self.accounts) + 1}",
            )
        )
        self.accounts[email] = account
        return account

    def bootstrap_super_admin(
        self,
        *,
        email: str,
        auth_subject: str | None = None,
        display_name: str | None = None,
    ) -> FakeAccount:
        account = FakeAccount(
            id="account-admin",
            email=email,
            role="super_admin",
            state="active",
            personal_workspace_id=None,
            auth_subject=auth_subject,
        )
        self.accounts[email] = account
        return account


def test_known_inbound_user_resolves_existing_private_workspace() -> None:
    repository = FakeUserAccountRepository(
        FakeAccount(id="account-known", email="known@example.com", state="active")
    )
    service = _service(repository)

    result = service.resolve_inbound_sender("Known User <known@example.com>")

    assert result.account_id == "account-known"
    assert result.email == "known@example.com"
    assert result.workspace_id == "workspace-1"
    assert repository.inbound_calls == []


def test_unknown_inbound_user_provisions_unclaimed_private_workspace() -> None:
    repository = FakeUserAccountRepository()
    service = _service(repository)

    result = service.resolve_inbound_sender("New Sender <new@example.com>")

    assert result.account_id == "account-1"
    assert result.workspace_id == "workspace-1"
    assert repository.inbound_calls == [("new@example.com", "New Sender")]


def test_inbound_email_is_normalized_exactly_for_lookup_and_result() -> None:
    repository = FakeUserAccountRepository()
    service = _service(repository)

    result = service.resolve_inbound_sender(
        '"Piyush Aryan" <PIYUSH+Contracts@Example.COM>'
    )

    assert result.email == "piyush+contracts@example.com"
    assert repository.inbound_calls == [
        ("piyush+contracts@example.com", "Piyush Aryan")
    ]


def test_super_admin_sender_is_rejected_before_repository_access() -> None:
    repository = FakeUserAccountRepository()
    service = _service(repository)

    with pytest.raises(SuperAdminInboundRejectedError):
        service.resolve_inbound_sender("Samvid Admin <ADMIN@SAMVID.ONLINE>")

    assert repository.accounts == {}
    assert repository.inbound_calls == []


def test_invalid_inbound_sender_raises_domain_error() -> None:
    service = _service(FakeUserAccountRepository())

    with pytest.raises(InvalidInboundSenderError):
        service.resolve_inbound_sender("not a mailbox")


def test_verified_principal_claims_existing_unclaimed_account() -> None:
    repository = FakeUserAccountRepository(
        FakeAccount(id="account-claimed", email="claim@example.com")
    )
    service = _service(repository)

    result = service.resolve_verified_principal(_principal(email="CLAIM@example.com"))

    assert result.account_id == "account-claimed"
    assert result.email == "claim@example.com"
    assert result.role == "user"
    assert result.state == "active"
    assert result.workspace_id == "workspace-1"
    assert repository.accounts["claim@example.com"].auth_subject == "neon-user-1"


def test_verified_super_admin_is_bound_without_a_private_workspace() -> None:
    repository = FakeUserAccountRepository()
    service = _service(repository)

    result = service.resolve_verified_principal(
        _principal(email="admin@samvid.online", subject="neon-admin")
    )

    assert result.role == "super_admin"
    assert result.workspace_id is None
    assert repository.accounts["admin@samvid.online"].auth_subject == "neon-admin"


def test_verified_email_bound_to_another_subject_is_a_conflict() -> None:
    repository = FakeUserAccountRepository(
        FakeAccount(
            id="account-bound",
            email="claim@example.com",
            state="active",
            auth_subject="different-subject",
        )
    )
    service = _service(repository)

    with pytest.raises(AccountConflictError):
        service.resolve_verified_principal(_principal(email="claim@example.com"))


def _service(repository: FakeUserAccountRepository) -> AccountAccessService:
    return AccountAccessService(
        repository=repository,
        super_admin_email="admin@samvid.online",
    )


def _principal(
    *,
    email: str,
    subject: str = "neon-user-1",
) -> NeonAuthPrincipal:
    return NeonAuthPrincipal(
        subject=subject,
        email=email,
        name="Verified User",
        email_verified=True,
        roles=frozenset({"authenticated"}),
        claims={},
    )
