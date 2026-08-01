from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time

import pytest

from contractmate.app import create_app
from contractmate.db.repositories.slack import OutboundSlackIntent, SlackInstallationConflictError, SlackRepository
from contractmate.db.repositories.user_accounts import UserAccountRepository
from contractmate.db.session import connect
from contractmate.security.neon_auth import NeonAuthPrincipal, NeonJWTVerifier
from contractmate.security.slack import InvalidSlackSignature, SlackTokenCipher, verify_slack_signature
from contractmate.settings import Settings


def _key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'slack.db'}",
        slack_enabled=True,
        slack_client_id="client-id",
        slack_client_secret="client-secret",
        slack_signing_secret="signing-secret",
        slack_token_encryption_key=_key(),
        slack_redirect_uri="https://samvid.example/slack/oauth/callback",
    )


def _signed_headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(
        b"signing-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    return {"x-slack-request-timestamp": timestamp, "x-slack-signature": signature}


def test_token_cipher_round_trip_and_tamper_rejection() -> None:
    cipher = SlackTokenCipher(_key())
    encrypted = cipher.encrypt("xoxb-secret")
    assert encrypted.startswith("v1.")
    assert "xoxb-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "xoxb-secret"
    with pytest.raises(ValueError):
        cipher.decrypt(encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B"))


def test_signature_rejects_replay_window() -> None:
    body = b"{}"
    old = "100"
    signature = "v0=" + hmac.new(b"secret", b"v0:100:{}", hashlib.sha256).hexdigest()
    with pytest.raises(InvalidSlackSignature):
        verify_slack_signature(body, timestamp=old, signature=signature, signing_secret="secret", now=401)


def test_oauth_state_stays_consumed_and_workspace_owner_cannot_change(tmp_path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'repo.db'}")
    repository = SlackRepository(connection)
    repository.create_oauth_state(account_id="account-a", raw_state="one-time")
    assert repository.consume_oauth_state(raw_state="one-time") == "account-a"
    repository.create_oauth_state(account_id="account-b", raw_state="one-time")
    assert repository.consume_oauth_state(raw_state="one-time") is None

    repository.upsert_installation(
        team_id="T1", team_name="Team", bot_user_id="B1",
        encrypted_bot_token="v1.token", installed_by_account_id="account-a",
    )
    with pytest.raises(SlackInstallationConflictError):
        repository.upsert_installation(
            team_id="T1", team_name="Team", bot_user_id="B2",
            encrypted_bot_token="v1.other", installed_by_account_id="account-b",
        )
    assert repository.get_installation_by_team(team_id="T1").installed_by_account_id == "account-a"  # type: ignore[union-attr]
    connection.close()


def test_signed_event_is_deduplicated_without_message_or_private_url(tmp_path) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path)
    payload = {
        "type": "event_callback",
        "event_id": "Ev1",
        "team_id": "T1",
        "event": {
            "type": "message", "channel_type": "im", "user": "U1", "channel": "D1", "ts": "1.2",
            "text": "private contract context",
            "files": [{"id": "F1", "name": "nda.pdf", "mimetype": "application/pdf", "size": 100,
                       "url_private": "https://files.slack.com/private"}],
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    client = TestClient(create_app(settings))
    first = client.post("/slack/events", content=body, headers=_signed_headers(body))
    second = client.post("/slack/events", content=body, headers=_signed_headers(body))
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"

    connection = connect(settings.database_url)
    stored = json.loads(connection.execute("SELECT payload_json FROM inbound_slack_events").fetchone()["payload_json"])
    assert "text" not in stored["event"]
    assert "url_private" not in stored["event"]["files"][0]
    connection.close()


def test_signed_event_outside_pilot_team_is_not_persisted(tmp_path) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path).model_copy(update={"slack_pilot_team_ids": ("T-PILOT",)})
    payload = {
        "type": "event_callback", "event_id": "Ev-outside", "team_id": "T-OTHER",
        "event": {"type": "app_mention", "user": "U1", "channel": "C1", "ts": "1.0", "files": []},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = TestClient(create_app(settings)).post("/slack/events", content=body, headers=_signed_headers(body))
    assert response.json() == {"status": "ignored", "reason": "workspace_not_in_pilot"}
    connection = connect(settings.database_url)
    assert connection.execute("SELECT COUNT(*) FROM inbound_slack_events").fetchone()[0] == 0
    connection.close()


def test_slack_install_requires_authenticated_account(tmp_path) -> None:
    from fastapi.testclient import TestClient

    response = TestClient(create_app(_settings(tmp_path))).post("/api/integrations/slack/install")
    assert response.status_code == 401


def test_slack_install_rejects_account_outside_pilot(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from contractmate.security.neon_auth import NeonAuthPrincipal, NeonJWTVerifier

    settings = _settings(tmp_path).model_copy(update={
        "auth_mode": "neon", "neon_auth_url": "https://example.neon.tech/auth",
        "samvid_super_admin_email": "admin@example.com",
        "slack_pilot_account_ids": ("pilot-account",),
    })
    principal = NeonAuthPrincipal(
        subject="user-1", email="user@example.com", name="User", email_verified=True,
        roles=frozenset({"authenticated"}), claims={},
    )
    monkeypatch.setattr(NeonJWTVerifier, "verify_authorization_header", lambda *_args: principal)
    response = TestClient(create_app(settings)).post(
        "/api/integrations/slack/install", headers={"authorization": "Bearer test"},
    )
    assert response.status_code == 403


def test_oauth_denial_requires_and_consumes_one_time_state(tmp_path) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path)
    connection = connect(settings.database_url)
    SlackRepository(connection).create_oauth_state(account_id="account-a", raw_state="denied-state")
    connection.close()

    client = TestClient(create_app(settings))
    missing = client.get("/slack/oauth/callback?error=access_denied", follow_redirects=False)
    invalid = client.get("/slack/oauth/callback?error=access_denied&state=not-valid", follow_redirects=False)
    denied = client.get("/slack/oauth/callback?error=access_denied&state=denied-state", follow_redirects=False)
    reused = client.get("/slack/oauth/callback?error=access_denied&state=denied-state", follow_redirects=False)
    assert missing.status_code == 400
    assert invalid.status_code == 400
    assert denied.status_code == 303
    assert denied.headers["location"].endswith("/settings?slack=denied")
    assert reused.status_code == 400

    connection = connect(settings.database_url)
    assert SlackRepository(connection).consume_oauth_state(raw_state="denied-state") is None
    connection.close()


@pytest.mark.parametrize(
    ("settings_update", "oauth_update", "expected_status"),
    [
        ({"slack_pilot_team_ids": ("T-PILOT",)}, {}, 403),
        ({}, {"scope": "chat:write"}, 502),
        ({}, {"team": {}}, 502),
    ],
)
def test_post_exchange_validation_failure_revokes_new_token(
    monkeypatch, tmp_path, settings_update, oauth_update, expected_status
) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path).model_copy(update=settings_update)
    connection = connect(settings.database_url)
    SlackRepository(connection).create_oauth_state(account_id="account-a", raw_state="validation-state")
    connection.close()
    oauth = {
        "ok": True,
        "access_token": "xoxb-new",
        "scope": ",".join(settings.slack_install_scopes),
        "team": {"id": "T-NEW", "name": "New Team"},
        "bot_user_id": "B1",
    }
    oauth.update(oauth_update)
    monkeypatch.setattr("contractmate.api.slack_routes._exchange_oauth_code", lambda *_args: oauth)
    revoked: list[str] = []
    monkeypatch.setattr("contractmate.api.slack_routes._revoke_slack_token", revoked.append)

    response = TestClient(create_app(settings)).get(
        "/slack/oauth/callback?code=code&state=validation-state",
        follow_redirects=False,
    )
    assert response.status_code == expected_status
    assert revoked == ["xoxb-new"]


@pytest.mark.parametrize(("new_token", "expected_revocations"), [("xoxb-new", ["xoxb-new"]), ("xoxb-old", [])])
def test_oauth_conflict_preserves_existing_installation_token(
    monkeypatch, tmp_path, new_token, expected_revocations
) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path)
    cipher = SlackTokenCipher(_key())
    connection = connect(settings.database_url)
    repository = SlackRepository(connection)
    repository.create_oauth_state(account_id="account-a", raw_state="conflict-state")
    existing = repository.upsert_installation(
        team_id="T-CONFLICT", team_name="Existing Team", bot_user_id="B-old",
        encrypted_bot_token=cipher.encrypt("xoxb-old"), installed_by_account_id="account-b",
    )
    connection.close()
    oauth = {
        "ok": True, "access_token": new_token,
        "scope": ",".join(settings.slack_install_scopes),
        "team": {"id": "T-CONFLICT", "name": "Existing Team"}, "bot_user_id": "B-new",
    }
    monkeypatch.setattr("contractmate.api.slack_routes._exchange_oauth_code", lambda *_args: oauth)
    revoked: list[str] = []
    monkeypatch.setattr("contractmate.api.slack_routes._revoke_slack_token", revoked.append)

    response = TestClient(create_app(settings)).get(
        "/slack/oauth/callback?code=code&state=conflict-state", follow_redirects=False,
    )
    assert response.status_code == 409
    assert revoked == expected_revocations
    connection = connect(settings.database_url)
    stored = SlackRepository(connection).get_installation(installation_id=existing.id)
    assert stored is not None
    assert stored.installed_by_account_id == "account-b"
    assert cipher.decrypt(stored.encrypted_bot_token) == "xoxb-old"
    connection.close()


def test_oauth_upsert_failure_revokes_new_token(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path)
    connection = connect(settings.database_url)
    SlackRepository(connection).create_oauth_state(account_id="account-a", raw_state="upsert-state")
    connection.close()
    oauth = {
        "ok": True, "access_token": "xoxb-new",
        "scope": ",".join(settings.slack_install_scopes),
        "team": {"id": "T-NEW", "name": "New Team"}, "bot_user_id": "B-new",
    }
    monkeypatch.setattr("contractmate.api.slack_routes._exchange_oauth_code", lambda *_args: oauth)
    monkeypatch.setattr(SlackRepository, "upsert_installation", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database failed")))
    revoked: list[str] = []
    monkeypatch.setattr("contractmate.api.slack_routes._revoke_slack_token", revoked.append)

    response = TestClient(create_app(settings)).get(
        "/slack/oauth/callback?code=code&state=upsert-state", follow_redirects=False,
    )
    assert response.status_code == 500
    assert revoked == ["xoxb-new"]

def test_disconnect_revokes_remote_token_and_stops_outbox(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    principal = NeonAuthPrincipal(
        subject="neon-user-a", email="user-a@example.com", name="User A",
        email_verified=True, roles=frozenset({"authenticated"}), claims={},
    )
    monkeypatch.setattr(NeonJWTVerifier, "verify_authorization_header", lambda _self, _header: principal)
    settings = _settings(tmp_path).model_copy(update={
        "auth_mode": "neon",
        "neon_auth_url": "https://auth.example/neondb/auth",
        "neon_auth_require_email_verified": True,
        "samvid_super_admin_email": "admin@samvid.online",
    })
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer user-a"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    connection = connect(settings.database_url)
    account = UserAccountRepository(connection).get_by_email("user-a@example.com")
    assert account is not None and account.personal_workspace_id is not None
    repository = SlackRepository(connection)
    installation = repository.upsert_installation(
        team_id="T-disconnect", team_name="Team", bot_user_id="B1",
        encrypted_bot_token=SlackTokenCipher(_key()).encrypt("xoxb-live"),
        installed_by_account_id=account.id,
    )
    outbox_id = repository.enqueue_outbound(OutboundSlackIntent(
        workspace_id=account.personal_workspace_id,
        installation_id=installation.id,
        channel_id="D1",
        thread_ts="1.0",
        message_type="receipt",
        text_body="Received",
        idempotency_key="disconnect-receipt",
    ))
    connection.close()

    revoked: list[str] = []
    monkeypatch.setattr("contractmate.api.slack_routes._revoke_slack_token", revoked.append)
    response = client.delete(f"/api/integrations/slack/{installation.id}", headers=headers)
    repeated = client.delete(f"/api/integrations/slack/{installation.id}", headers=headers)
    assert response.status_code == 204
    assert repeated.status_code == 204
    assert revoked == ["xoxb-live"]

    connection = connect(settings.database_url)
    assert SlackRepository(connection).get_installation_by_team(
        team_id="T-disconnect", active_only=False
    ).status == "disconnected"  # type: ignore[union-attr]
    outbox = connection.execute(
        "SELECT status, last_error FROM outbound_slack_outbox WHERE id = ?", (outbox_id,)
    ).fetchone()
    assert outbox["status"] == "failed"
    assert outbox["last_error"] == "Slack installation disconnected"
    repository = SlackRepository(connection)
    repository.reschedule_outbound(
        outbox_id=outbox_id, lease_token="stale-owner", attempts=1, error="late worker retry",
    )
    future_id = repository.enqueue_outbound(OutboundSlackIntent(
        workspace_id=account.personal_workspace_id,
        installation_id=installation.id,
        channel_id="D1",
        thread_ts="2.0",
        message_type="failure",
        text_body="Late result",
        idempotency_key="disconnect-late-result",
    ))
    assert connection.execute(
        "SELECT status FROM outbound_slack_outbox WHERE id = ?", (outbox_id,)
    ).fetchone()["status"] == "failed"
    assert connection.execute(
        "SELECT status FROM outbound_slack_outbox WHERE id = ?", (future_id,)
    ).fetchone()["status"] == "failed"
    connection.close()


def test_disconnect_keeps_installation_active_when_slack_revoke_fails(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    principal = NeonAuthPrincipal(
        subject="neon-user-a", email="user-a@example.com", name="User A",
        email_verified=True, roles=frozenset({"authenticated"}), claims={},
    )
    monkeypatch.setattr(NeonJWTVerifier, "verify_authorization_header", lambda _self, _header: principal)
    settings = _settings(tmp_path).model_copy(update={
        "auth_mode": "neon",
        "neon_auth_url": "https://auth.example/neondb/auth",
        "neon_auth_require_email_verified": True,
        "samvid_super_admin_email": "admin@samvid.online",
    })
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer user-a"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    connection = connect(settings.database_url)
    account = UserAccountRepository(connection).get_by_email("user-a@example.com")
    assert account is not None
    installation = SlackRepository(connection).upsert_installation(
        team_id="T-failure", team_name="Team", bot_user_id="B1",
        encrypted_bot_token=SlackTokenCipher(_key()).encrypt("xoxb-live"),
        installed_by_account_id=account.id,
    )
    connection.close()

    def fail_revoke(_token: str) -> None:
        raise RuntimeError("Slack unavailable")

    monkeypatch.setattr("contractmate.api.slack_routes._revoke_slack_token", fail_revoke)
    response = client.delete(f"/api/integrations/slack/{installation.id}", headers=headers)
    assert response.status_code == 502
    connection = connect(settings.database_url)
    assert SlackRepository(connection).get_installation(
        installation_id=installation.id
    ) is not None
    connection.close()

def test_sqlite_upgrade_allows_slack_source_and_nullable_email_thread(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE user_accounts (
            id TEXT PRIMARY KEY, auth_subject TEXT UNIQUE, email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT, role TEXT NOT NULL CHECK (role IN ('user', 'super_admin')),
            state TEXT NOT NULL CHECK (state IN ('unclaimed', 'active')), personal_workspace_id TEXT UNIQUE,
            source TEXT NOT NULL CHECK (source IN ('signup', 'inbound_email')), claimed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK ((role = 'super_admin' AND personal_workspace_id IS NULL) OR (role = 'user' AND personal_workspace_id IS NOT NULL))
        );
        CREATE TABLE contracts (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, email_thread_id TEXT NOT NULL, title TEXT,
            status TEXT NOT NULL, current_version_id TEXT, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO contracts(id, workspace_id, email_thread_id, status, created_by)
        VALUES ('c1', 'w1', 'samvid-upload-1', 'ready', 'user@example.com');
        """
    )
    connection.close()

    migrated = connect(f"sqlite:///{path}")
    migrated.execute(
        """INSERT INTO user_accounts(id, email, role, state, personal_workspace_id, source)
        VALUES ('u1', 'slack@example.com', 'user', 'unclaimed', 'w1', 'inbound_slack')"""
    )
    columns = {row["name"]: row for row in migrated.execute("PRAGMA table_info(contracts)")}
    assert columns["email_thread_id"]["notnull"] == 0
    source = migrated.execute("SELECT source_channel FROM contract_sources WHERE contract_id = 'c1'").fetchone()
    assert source["source_channel"] == "browser"
    migrated.close()
