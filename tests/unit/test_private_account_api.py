from __future__ import annotations

from types import SimpleNamespace

import pytest

from contractmate.db.repositories.user_accounts import UserAccountRepository
from contractmate.db.session import connect
from contractmate.security.neon_auth import NeonAuthPrincipal, NeonJWTVerifier
from contractmate.settings import Settings


@pytest.fixture
def private_api(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app

    principals = {
        "user-a": NeonAuthPrincipal(
            subject="neon-user-a",
            email="user-a@example.com",
            name="User A",
            email_verified=True,
            roles=frozenset({"authenticated"}),
            claims={},
        ),
        "user-b": NeonAuthPrincipal(
            subject="neon-user-b",
            email="user-b@example.com",
            name="User B",
            email_verified=True,
            roles=frozenset({"authenticated"}),
            claims={},
        ),
        "admin": NeonAuthPrincipal(
            subject="neon-admin",
            email="admin@samvid.online",
            name="Samvid Admin",
            email_verified=True,
            roles=frozenset({"authenticated"}),
            claims={},
        ),
    }

    def fake_verify(_self, authorization_header):
        token = (authorization_header or "").removeprefix("Bearer ")
        if token not in principals:
            from contractmate.security.neon_auth import NeonAuthenticationError

            raise NeonAuthenticationError("Authentication required")
        return principals[token]

    monkeypatch.setattr(NeonJWTVerifier, "verify_authorization_header", fake_verify)
    settings = Settings(
        auth_mode="neon",
        neon_auth_url="https://ep-example.neonauth.us-east-1.aws.neon.tech/neondb/auth",
        neon_auth_require_email_verified=True,
        database_url=f"sqlite:///{tmp_path / 'samvid.db'}",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="model-key",
        auto_send_review_email=False,
        samvid_super_admin_email="admin@samvid.online",
    )
    return SimpleNamespace(client=TestClient(create_app(settings)), settings=settings)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_private_contracts_are_isolated_and_super_admin_reads_are_audited(private_api) -> None:
    client = private_api.client
    settings = private_api.settings

    assert client.get("/api/auth/me", headers=_headers("user-a")).status_code == 200
    assert client.get("/api/auth/me", headers=_headers("user-b")).status_code == 200
    assert client.get("/api/auth/me", headers=_headers("admin")).status_code == 200

    connection = connect(settings.database_url)
    try:
        accounts = UserAccountRepository(connection)
        user_b = accounts.get_by_email("user-b@example.com")
        assert user_b is not None and user_b.personal_workspace_id
        connection.execute(
            """
            INSERT INTO contracts(id, workspace_id, email_thread_id, title, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("contract-user-b", user_b.personal_workspace_id, "thread-b", "Private agreement", "queued", user_b.email),
        )
        connection.commit()
    finally:
        connection.close()

    assert client.get("/api/contracts/contract-user-b", headers=_headers("user-a")).status_code == 404

    admin_contract = client.get("/api/admin/contracts/contract-user-b", headers=_headers("admin"))
    assert admin_contract.status_code == 200
    assert admin_contract.json()["title"] == "Private agreement"

    events = client.get("/api/admin/access-events", headers=_headers("admin"))
    assert events.status_code == 200
    assert events.json()["items"][0]["event_type"] == "admin.contract.viewed"
    assert events.json()["items"][0]["target_user_email"] == "user-b@example.com"

    assert client.post("/api/contracts", headers=_headers("admin")).status_code == 403
