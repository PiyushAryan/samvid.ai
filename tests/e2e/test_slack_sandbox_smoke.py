from __future__ import annotations

import os

import pytest
from slack_sdk import WebClient

from contractmate.db.repositories.slack import SlackRepository
from contractmate.db.session import connect
from contractmate.security.slack import SlackTokenCipher


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SLACK_SANDBOX_SMOKE") != "1",
    reason="set RUN_SLACK_SANDBOX_SMOKE=1 with dedicated Slack sandbox credentials",
)


def test_slack_sandbox_api_smoke(tmp_path) -> None:
    token = _required("SLACK_SANDBOX_BOT_TOKEN")
    team_id = _required("SLACK_SANDBOX_TEAM_ID")
    channel_id = _required("SLACK_SANDBOX_CHANNEL_ID")
    user_id = _required("SLACK_SANDBOX_USER_ID")
    file_id = _required("SLACK_SANDBOX_FILE_ID")
    encryption_key = _required("SLACK_TOKEN_ENCRYPTION_KEY")
    client = WebClient(token=token)

    auth = client.auth_test()
    assert auth["ok"] and auth["team_id"] == team_id
    assert client.users_info(user=user_id)["user"]["id"] == user_id
    assert client.files_info(file=file_id)["file"]["id"] == file_id

    connection = connect(f"sqlite:///{tmp_path / 'slack-sandbox.db'}")
    repository = SlackRepository(connection)
    installation = repository.upsert_installation(
        team_id=team_id, team_name=str(auth.get("team") or "Sandbox"),
        bot_user_id=str(auth.get("user_id") or "") or None,
        encrypted_bot_token=SlackTokenCipher(encryption_key).encrypt(token),
        installed_by_account_id="sandbox-account",
    )
    posted_ts = None
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text="Samvid Slack sandbox API smoke verification — safe to delete.",
            thread_ts=os.getenv("SLACK_SANDBOX_THREAD_TS") or None,
        )
        assert response["ok"] and response["ts"]
        posted_ts = str(response["ts"])
        assert repository.disconnect_installation(
            installation_id=installation.id, account_id="sandbox-account",
        )
        assert repository.get_installation(installation_id=installation.id) is None
    finally:
        if posted_ts:
            client.chat_delete(channel=channel_id, ts=posted_ts)
        connection.close()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.fail(f"{name} is required when RUN_SLACK_SANDBOX_SMOKE=1")
    return value
