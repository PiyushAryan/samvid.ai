from __future__ import annotations

import json
import hmac
import secrets
from typing import Any, Iterator
from urllib.parse import urlencode

try:
    from fastapi import APIRouter, Depends, HTTPException, Request, Response
    from fastapi.responses import RedirectResponse
    from starlette.concurrency import run_in_threadpool
except ModuleNotFoundError as exc:
    raise RuntimeError("Install the 'api' extra to run the Slack HTTP integration") from exc

from contractmate.db.repositories.slack import SlackInstallationConflictError, SlackRepository
from contractmate.db.repositories.user_accounts import UserAccountRepository
from contractmate.db.session import connect
from contractmate.security.slack import InvalidSlackSignature, SlackTokenCipher, verify_slack_signature
from contractmate.services.account_access import AccountAccessError, AccountAccessService
from contractmate.settings import Settings


def create_slack_router(settings: Settings):
    router = APIRouter()

    def db_connection() -> Iterator[Any]:
        connection = connect(settings.database_url)
        try:
            yield connection
        finally:
            connection.close()

    def account_id(request: Request, connection: Any = Depends(db_connection)) -> str:
        principal = getattr(request.state, "auth_principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="An authenticated Samvid account is required")
        if not settings.samvid_super_admin_email:
            raise HTTPException(status_code=503, detail="Samvid account access is not configured")
        try:
            access = AccountAccessService(
                repository=UserAccountRepository(connection),
                super_admin_email=settings.samvid_super_admin_email,
            ).resolve_verified_principal(principal)
        except AccountAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if access.role != "user":
            raise HTTPException(status_code=403, detail="A personal Samvid account is required")
        return access.account_id

    @router.post("/api/integrations/slack/install")
    def begin_install(
        actor_account_id: str = Depends(account_id),
        connection: Any = Depends(db_connection),
    ) -> dict[str, str]:
        _require_enabled(settings, HTTPException)
        if settings.slack_pilot_account_ids and actor_account_id not in settings.slack_pilot_account_ids:
            raise HTTPException(status_code=403, detail="Slack integration is limited to pilot accounts")
        raw_state = secrets.token_urlsafe(32)
        SlackRepository(connection).create_oauth_state(account_id=actor_account_id, raw_state=raw_state)
        authorize_url = "https://slack.com/oauth/v2/authorize?" + urlencode(
            {
                "client_id": settings.slack_client_id or "",
                "scope": ",".join(settings.slack_install_scopes),
                "redirect_uri": _redirect_uri(settings),
                "state": raw_state,
            }
        )
        return {"authorize_url": authorize_url}

    @router.get("/slack/oauth/callback")
    async def oauth_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ):
        _require_enabled(settings, HTTPException)
        if not state:
            raise HTTPException(status_code=400, detail="Slack OAuth state is required")

        connection = connect(settings.database_url)
        try:
            repository = SlackRepository(connection)
            actor_account_id = repository.consume_oauth_state(raw_state=state)
            if actor_account_id is None:
                raise HTTPException(status_code=400, detail="Slack OAuth state is invalid, expired, or already used")
            if error:
                return RedirectResponse(_frontend_result_url(settings, "denied"), status_code=303)
            if not code:
                raise HTTPException(status_code=400, detail="Slack OAuth code is required")
            try:
                oauth = await run_in_threadpool(_exchange_oauth_code, settings, code)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail="Slack OAuth exchange failed") from exc
            token = str(oauth.get("access_token") or "")
            team = oauth.get("team") if isinstance(oauth.get("team"), dict) else {}
            team_id = str(team.get("id") or "")
            existing_installation = (
                repository.get_installation_by_team(team_id=team_id, active_only=False) if team_id else None
            )
            try:
                if not token or not team_id:
                    raise HTTPException(
                        status_code=502,
                        detail="Slack OAuth response did not include a workspace and bot token",
                    )
                if (
                    existing_installation is not None
                    and existing_installation.installed_by_account_id != actor_account_id
                ):
                    raise SlackInstallationConflictError(
                        "Slack workspace is already connected to another Samvid account"
                    )
                if settings.slack_pilot_team_ids and team_id not in settings.slack_pilot_team_ids:
                    raise HTTPException(status_code=403, detail="Slack workspace is not included in the pilot")
                granted_scopes = {
                    value.strip() for value in str(oauth.get("scope") or "").split(",") if value.strip()
                }
                if set(settings.slack_install_scopes).difference(granted_scopes):
                    raise HTTPException(status_code=502, detail="Slack did not grant all required bot scopes")
                repository.upsert_installation(
                    team_id=team_id,
                    team_name=str(team.get("name")) if team.get("name") else None,
                    bot_user_id=str(oauth.get("bot_user_id")) if oauth.get("bot_user_id") else None,
                    encrypted_bot_token=SlackTokenCipher(settings.slack_token_encryption_key or "").encrypt(token),
                    installed_by_account_id=actor_account_id,
                )
            except Exception as exc:
                current_installation = existing_installation
                if team_id:
                    try:
                        current_installation = repository.get_installation_by_team(
                            team_id=team_id,
                            active_only=False,
                        ) or current_installation
                    except Exception:
                        pass
                if token and not _token_matches_active_installation(
                    installation=current_installation,
                    token=token,
                    cipher=SlackTokenCipher(settings.slack_token_encryption_key or ""),
                ):
                    try:
                        await run_in_threadpool(_revoke_slack_token, token)
                    except RuntimeError as revoke_exc:
                        raise HTTPException(
                            status_code=502,
                            detail="Slack OAuth failed and the new authorization could not be revoked",
                        ) from revoke_exc
                if isinstance(exc, SlackInstallationConflictError):
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                if isinstance(exc, HTTPException):
                    raise exc
                raise HTTPException(status_code=500, detail="Slack installation could not be saved") from exc
        finally:
            connection.close()
        return RedirectResponse(_frontend_result_url(settings, "connected"), status_code=303)

    @router.get("/api/integrations/slack")
    def list_installations(
        actor_account_id: str = Depends(account_id),
        connection: Any = Depends(db_connection),
    ) -> dict[str, Any]:
        rows = SlackRepository(connection).list_installations(account_id=actor_account_id) if settings.slack_enabled else []
        return {
            "enabled": settings.slack_enabled,
            "installations": [
                {
                    "id": row.id,
                    "team_id": row.team_id,
                    "team_name": row.team_name,
                    "status": row.status,
                    "created_at": str(row.created_at),
                }
                for row in rows
            ],
        }

    @router.delete(
        "/api/integrations/slack/{installation_id}", status_code=204,
        response_class=Response, response_model=None,
    )
    async def disconnect_installation(
        installation_id: str,
        actor_account_id: str = Depends(account_id),
        connection: Any = Depends(db_connection),
    ):
        repository = SlackRepository(connection)
        installation = repository.get_installation_for_account(
            installation_id=installation_id,
            account_id=actor_account_id,
            active_only=False,
        )
        if installation is None:
            raise HTTPException(status_code=404, detail="Slack installation not found")
        if installation.status != "active":
            return Response(status_code=204)
        try:
            token = SlackTokenCipher(settings.slack_token_encryption_key or "").decrypt(
                installation.encrypted_bot_token
            )
            await run_in_threadpool(_revoke_slack_token, token)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Slack installation token could not be decrypted") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail="Slack authorization could not be revoked") from exc
        repository.disconnect_installation(installation_id=installation_id, account_id=actor_account_id)
        return Response(status_code=204)

    @router.post("/slack/events")
    async def slack_events(request: Request) -> dict[str, Any]:
        _require_enabled(settings, HTTPException)
        raw_body = await request.body()
        try:
            verify_slack_signature(
                raw_body,
                timestamp=request.headers.get("x-slack-request-timestamp"),
                signature=request.headers.get("x-slack-signature"),
                signing_secret=settings.slack_signing_secret or "",
            )
        except InvalidSlackSignature as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Slack event payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Slack event payload must be an object")
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if not isinstance(challenge, str):
                raise HTTPException(status_code=400, detail="Slack URL verification challenge is missing")
            return {"challenge": challenge}
        if payload.get("type") != "event_callback":
            return {"status": "ignored", "reason": "unsupported_envelope"}

        normalized = _normalize_event(payload)
        if normalized is None:
            return {"status": "ignored", "reason": "unsupported_event"}
        if settings.slack_pilot_team_ids and normalized["team_id"] not in settings.slack_pilot_team_ids:
            return {"status": "ignored", "reason": "workspace_not_in_pilot"}

        def persist() -> bool:
            connection = connect(settings.database_url)
            try:
                return SlackRepository(connection).enqueue_event(
                    event_id=normalized["event_id"],
                    team_id=normalized["team_id"],
                    event_type=normalized["event"]["type"],
                    payload=normalized,
                )
            finally:
                connection.close()

        inserted = await run_in_threadpool(persist)
        return {"status": "accepted" if inserted else "duplicate", "event_id": normalized["event_id"]}

    return router


def _require_enabled(settings: Settings, http_exception: type[Exception]) -> None:
    if not settings.slack_enabled:
        raise http_exception(status_code=503, detail="Slack integration is disabled")


def _redirect_uri(settings: Settings) -> str:
    if settings.slack_redirect_uri:
        return settings.slack_redirect_uri
    return f"{(settings.app_base_url or settings.frontend_origin).rstrip('/')}/slack/oauth/callback"


def _frontend_result_url(settings: Settings, result: str) -> str:
    return f"{settings.frontend_origin.rstrip('/')}/settings?slack={result}"


def _exchange_oauth_code(settings: Settings, code: str) -> dict[str, Any]:
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install slack_sdk to enable Slack OAuth") from exc
    try:
        response = WebClient().oauth_v2_access(
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret,
            code=code,
            redirect_uri=_redirect_uri(settings),
        )
    except SlackApiError as exc:
        raise RuntimeError(f"Slack OAuth exchange failed: {exc.response.get('error', 'unknown_error')}") from exc
    data = dict(response.data)
    if not data.get("ok"):
        raise RuntimeError(f"Slack OAuth exchange failed: {data.get('error', 'unknown_error')}")
    return data


def _revoke_slack_token(token: str) -> None:
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install slack_sdk to revoke Slack authorization") from exc
    try:
        response = WebClient(token=token).auth_revoke()
    except SlackApiError as exc:
        error = str(exc.response.get("error") or "unknown_error")
        if error in {"invalid_auth", "not_authed", "token_revoked", "account_inactive"}:
            return
        raise RuntimeError(f"Slack auth.revoke failed: {error}") from exc
    if not response.get("ok"):
        error = str(response.get("error") or "unknown_error")
        if error in {"invalid_auth", "not_authed", "token_revoked", "account_inactive"}:
            return
        raise RuntimeError(f"Slack auth.revoke failed: {error}")


def _token_matches_active_installation(
    *,
    installation: Any | None,
    token: str,
    cipher: SlackTokenCipher,
) -> bool:
    if installation is None or installation.status != "active":
        return False
    try:
        return hmac.compare_digest(cipher.decrypt(installation.encrypted_bot_token), token)
    except ValueError:
        return False


def _normalize_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_id = payload.get("event_id")
    team_id = payload.get("team_id")
    event = payload.get("event")
    if not isinstance(event_id, str) or not event_id or not isinstance(team_id, str) or not team_id:
        return None
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if event_type != "app_mention" and not (event_type == "message" and event.get("channel_type") == "im"):
        return None
    normalized_event = {
        key: event[key]
        for key in (
            "type", "user", "channel", "channel_type", "ts", "thread_ts", "subtype",
            "bot_id", "user_team", "team", "is_ext_shared_channel",
        )
        if key in event
    }
    normalized_event["files"] = [
        {
            key: item[key]
            for key in ("id", "name", "mimetype", "filetype", "size")
            if key in item
        }
        for item in event.get("files", [])
        if isinstance(item, dict)
    ]
    return {"event_id": event_id, "team_id": team_id, "event": normalized_event}
