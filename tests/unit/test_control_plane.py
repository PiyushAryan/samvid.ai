import base64
import hashlib
import hmac
import json
import time

from contractmate.security.control_plane import authorize_control_plane_request, verify_hs256_jwt
from contractmate.settings import Settings


def test_production_control_plane_requires_authentication() -> None:
    settings = Settings(app_env="production", os_security_key="secret")

    principal = authorize_control_plane_request(
        settings=settings,
        os_security_key_header=None,
        authorization_header=None,
    )

    assert principal is None


def test_control_plane_accepts_os_security_key() -> None:
    settings = Settings(app_env="production", os_security_key="secret")

    principal = authorize_control_plane_request(
        settings=settings,
        os_security_key_header="secret",
        authorization_header=None,
    )

    assert principal is not None
    assert principal.auth_method == "os-security-key"
    assert principal.has_scope("runtime:read")


def test_verify_hs256_jwt_validates_signature_and_expiry() -> None:
    token = _jwt(
        {"sub": "admin-1", "scope": "runtime:read traces:read", "exp": int(time.time()) + 60},
        key="jwt-secret",
    )

    claims = verify_hs256_jwt(token=token, verification_key="jwt-secret")

    assert claims is not None
    assert claims["sub"] == "admin-1"
    assert verify_hs256_jwt(token=token, verification_key="wrong") is None


def _jwt(payload: dict, *, key: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_segment = _segment(header)
    payload_segment = _segment(payload)
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64(signature)}"


def _segment(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
