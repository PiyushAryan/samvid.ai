from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contractmate.security.neon_auth import NeonAuthenticationError, NeonAuthorizationError, NeonJWTVerifier


AUTH_URL = "https://ep-example.neonauth.us-east-1.aws.neon.tech/neondb/auth"
AUTH_ORIGIN = "https://ep-example.neonauth.us-east-1.aws.neon.tech"


def make_verifier():
    private_key = Ed25519PrivateKey.generate()
    verifier = NeonJWTVerifier(auth_url=AUTH_URL)
    verifier._jwks_client.get_signing_key_from_jwt = lambda _token: SimpleNamespace(key=private_key.public_key())
    return verifier, private_key


def make_token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "sub": "user_123",
        "id": "user_123",
        "email": "owner@example.com",
        "name": "Workspace Owner",
        "emailVerified": True,
        "role": "authenticated",
        "iss": AUTH_ORIGIN,
        "aud": AUTH_ORIGIN,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="EdDSA", headers={"kid": "test-key"})


def test_verifier_accepts_valid_neon_token() -> None:
    verifier, private_key = make_verifier()

    principal = verifier.verify_token(make_token(private_key))

    assert principal.subject == "user_123"
    assert principal.email == "owner@example.com"
    assert principal.name == "Workspace Owner"
    assert principal.roles == frozenset({"authenticated"})


def test_verifier_rejects_wrong_audience() -> None:
    verifier, private_key = make_verifier()

    with pytest.raises(NeonAuthenticationError, match="Invalid or expired"):
        verifier.verify_token(make_token(private_key, aud="https://other.example.com"))


def test_verifier_accepts_verified_identity_for_account_provisioning() -> None:
    verifier, private_key = make_verifier()

    principal = verifier.verify_token(make_token(private_key, email="someone@example.com"))

    assert principal.email == "someone@example.com"


def test_verifier_can_require_verified_email() -> None:
    verifier, private_key = make_verifier()
    verifier.require_email_verified = True

    with pytest.raises(NeonAuthorizationError, match="Verify your email"):
        verifier.verify_token(make_token(private_key, emailVerified=False))


def test_verifier_requires_bearer_scheme() -> None:
    verifier, _private_key = make_verifier()

    with pytest.raises(NeonAuthenticationError, match="bearer token"):
        verifier.verify_authorization_header("Basic abc123")


def test_neon_mode_keeps_spa_public_and_protects_api(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from contractmate.app import create_app
    from contractmate.security.neon_auth import NeonAuthPrincipal
    from contractmate.settings import Settings

    frontend_dist = tmp_path / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<main>Samvid</main>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    principal = NeonAuthPrincipal(
        subject="user_123",
        email="owner@example.com",
        name="Workspace Owner",
        email_verified=True,
        roles=frozenset({"authenticated"}),
        claims={},
    )

    def fake_verify(self, authorization_header):
        if authorization_header != "Bearer valid-token":
            raise NeonAuthenticationError("Authentication required")
        return principal

    monkeypatch.setattr(NeonJWTVerifier, "verify_authorization_header", fake_verify)
    settings = Settings(
        app_env="development",
        auth_mode="neon",
        neon_auth_url=AUTH_URL,
        neon_auth_require_email_verified=True,
        allowed_hosts=("testserver",),
        database_url=f"sqlite:///{tmp_path / 'samvid.db'}",
        local_storage_dir=tmp_path / "contracts",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="model-key",
        auto_send_review_email=False,
        samvid_super_admin_email="admin@samvid.online",
    )
    client = TestClient(create_app(settings))

    assert client.get("/").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "subject": "user_123",
            "email": "owner@example.com",
            "name": "Workspace Owner",
            "email_verified": True,
        },
        "account": {
            "id": response.json()["account"]["id"],
            "role": "user",
            "state": "active",
            "workspace_id": response.json()["account"]["workspace_id"],
        },
    }
    assert response.json()["account"]["workspace_id"].startswith("user-")
