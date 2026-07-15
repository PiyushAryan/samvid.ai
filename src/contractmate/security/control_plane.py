from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from contractmate.settings import Settings


@dataclass(frozen=True)
class ControlPlanePrincipal:
    subject: str
    scopes: frozenset[str]
    auth_method: str

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def authorize_control_plane_request(
    *,
    settings: Settings,
    os_security_key_header: str | None,
    authorization_header: str | None,
    required_scope: str = "runtime:read",
) -> ControlPlanePrincipal | None:
    security_key_principal = _authorize_security_key(
        settings=settings,
        os_security_key_header=os_security_key_header,
    )
    if security_key_principal and security_key_principal.has_scope(required_scope):
        return security_key_principal

    jwt_principal = _authorize_jwt(
        settings=settings,
        authorization_header=authorization_header,
    )
    if jwt_principal and jwt_principal.has_scope(required_scope):
        return jwt_principal

    if settings.is_production:
        return None
    if not settings.os_security_key and not settings.jwt_verification_key:
        return ControlPlanePrincipal(
            subject="local-developer",
            scopes=frozenset({"runtime:read", "traces:read", "sessions:read", "approvals:write"}),
            auth_method="local-dev",
        )
    return None


def _authorize_security_key(
    *,
    settings: Settings,
    os_security_key_header: str | None,
) -> ControlPlanePrincipal | None:
    if not settings.os_security_key or not os_security_key_header:
        return None
    if not hmac.compare_digest(settings.os_security_key, os_security_key_header):
        return None
    return ControlPlanePrincipal(
        subject="os-security-key",
        scopes=frozenset({"runtime:read", "traces:read", "sessions:read", "approvals:write"}),
        auth_method="os-security-key",
    )


def _authorize_jwt(
    *,
    settings: Settings,
    authorization_header: str | None,
) -> ControlPlanePrincipal | None:
    if not settings.jwt_verification_key or not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    claims = verify_hs256_jwt(token=token, verification_key=settings.jwt_verification_key)
    if claims is None:
        return None
    raw_scope = claims.get("scope") or claims.get("scp") or ""
    scopes = raw_scope if isinstance(raw_scope, list) else str(raw_scope).split()
    return ControlPlanePrincipal(
        subject=str(claims.get("sub", "unknown")),
        scopes=frozenset(str(scope) for scope in scopes),
        auth_method="jwt",
    )


def verify_hs256_jwt(*, token: str, verification_key: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_segment, payload_segment, signature_segment = parts
    try:
        header = _decode_json_segment(header_segment)
        payload = _decode_json_segment(payload_segment)
    except (ValueError, json.JSONDecodeError):
        return None
    if header.get("alg") != "HS256":
        return None
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = hmac.new(
        verification_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    supplied_signature = _decode_segment(signature_segment)
    if not hmac.compare_digest(expected_signature, supplied_signature):
        return None
    expires_at = payload.get("exp")
    if expires_at is not None:
        try:
            if int(expires_at) < int(time.time()):
                return None
        except (TypeError, ValueError):
            return None
    return payload


def _decode_json_segment(segment: str) -> dict:
    decoded = _decode_segment(segment)
    value = json.loads(decoded)
    if not isinstance(value, dict):
        raise ValueError("JWT segment must decode to an object.")
    return value


def _decode_segment(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)
