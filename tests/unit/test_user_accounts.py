from __future__ import annotations

import sqlite3

import pytest

from contractmate.db.models import SQLITE_SCHEMA_SQL
from contractmate.db.repositories.user_accounts import UserAccountConflictError, UserAccountRepository


@pytest.fixture
def repository() -> UserAccountRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    yield UserAccountRepository(connection)
    connection.close()


def test_inbound_provisioning_is_normalized_and_idempotent(repository: UserAccountRepository) -> None:
    first = repository.provision_inbound_user(email="  USER@Example.COM ", display_name="First")
    second = repository.provision_inbound_user(email="user@example.com", display_name="Ignored")

    assert second.id == first.id
    assert first.email == "user@example.com"
    assert first.role == "user"
    assert first.state == "unclaimed"
    assert first.auth_subject is None
    assert first.personal_workspace_id is not None
    assert first.source == "inbound_email"


def test_verified_identity_claims_inbound_account(repository: UserAccountRepository) -> None:
    inbound = repository.provision_inbound_user(email="User@Example.com")

    claimed = repository.provision_verified_user(
        auth_subject="neon-user-1",
        email=" user@example.COM ",
        display_name="Piyush Aryan",
    )

    assert claimed.id == inbound.id
    assert claimed.personal_workspace_id == inbound.personal_workspace_id
    assert claimed.auth_subject == "neon-user-1"
    assert claimed.display_name == "Piyush Aryan"
    assert claimed.state == "active"
    assert claimed.claimed_at is not None
    assert repository.provision_verified_user(
        auth_subject="neon-user-1", email="user@example.com"
    ).id == inbound.id


def test_new_verified_signup_gets_private_workspace(repository: UserAccountRepository) -> None:
    account = repository.provision_verified_user(
        auth_subject="neon-new-user",
        email="new@example.com",
        display_name="New User",
    )

    assert account.role == "user"
    assert account.state == "active"
    assert account.source == "signup"
    assert account.personal_workspace_id is not None
    assert account.personal_workspace_id.startswith("user-")
    assert repository.get_by_subject("neon-new-user") == account

    with pytest.raises(UserAccountConflictError):
        repository.provision_verified_user(
            auth_subject="neon-new-user",
            email="different@example.com",
        )


def test_super_admin_is_oversight_only_and_can_be_bound(repository: UserAccountRepository) -> None:
    bootstrapped = repository.bootstrap_super_admin(email="Admin@Samvid.Online", display_name="Samvid Admin")

    assert bootstrapped.role == "super_admin"
    assert bootstrapped.state == "unclaimed"
    assert bootstrapped.personal_workspace_id is None

    bound = repository.bootstrap_super_admin(
        email="admin@samvid.online",
        auth_subject="neon-admin",
    )

    assert bound.id == bootstrapped.id
    assert bound.state == "active"
    assert bound.auth_subject == "neon-admin"
    assert bound.personal_workspace_id is None

    repeated_bootstrap = repository.bootstrap_super_admin(email="admin@samvid.online")

    assert repeated_bootstrap.id == bound.id
    assert repeated_bootstrap.auth_subject == "neon-admin"
    assert repeated_bootstrap.state == "active"
    with pytest.raises(UserAccountConflictError):
        repository.provision_inbound_user(email="admin@samvid.online")


def test_access_events_and_account_listing_include_contract_counts(repository: UserAccountRepository) -> None:
    admin = repository.bootstrap_super_admin(email="admin@example.com", auth_subject="admin-sub")
    user = repository.provision_verified_user(auth_subject="user-sub", email="user@example.com")
    repository.connection.execute(
        """
        INSERT INTO contracts(id, workspace_id, email_thread_id, status, created_by)
        VALUES ('contract-1', ?, 'thread-1', 'received', 'user@example.com')
        """,
        (user.personal_workspace_id,),
    )
    repository.connection.commit()

    event_id = repository.record_access_event(
        actor_account_id=admin.id,
        target_account_id=user.id,
        workspace_id=user.personal_workspace_id,
        contract_id="contract-1",
        event_type="admin.contract.viewed",
        metadata={"reason": "support"},
    )

    accounts, total = repository.list_accounts(role="user")
    events = repository.list_access_events(actor_account_id=admin.id)
    assert total == 1
    assert accounts[0].id == user.id
    assert accounts[0].contract_count == 1
    assert events[0].id == event_id
    assert events[0].metadata == {"reason": "support"}
