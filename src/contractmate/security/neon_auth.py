from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import jwt


class NeonAuthenticationError(ValueError):
    """Raised when a Neon access token cannot be trusted."""


class NeonAuthorizationError(PermissionError):
    """Raised when an authenticated Neon user cannot access the workspace."""


@dataclass(frozen=True)
class NeonAuthPrincipal:
    subject: str
    email: str
    name: str
    email_verified: bool
    roles: frozenset[str]
    claims: dict[str, Any]


class NeonJWTVerifier:
    def __init__(
        self,
        *,
        auth_url: str,
        jwks_url: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        require_email_verified: bool = False,
        clock_skew_seconds: int = 30,
    ) -> None:
        normalized_auth_url = auth_url.rstrip("/")
        parsed = urlsplit(normalized_auth_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("NEON_AUTH_URL must be an absolute HTTPS URL")

        auth_origin = f"{parsed.scheme}://{parsed.netloc}"
        self.jwks_url = jwks_url or f"{normalized_auth_url}/.well-known/jwks.json"
        self.issuer = issuer or auth_origin
        self.audience = audience or auth_origin
        self.require_email_verified = require_email_verified
        self.clock_skew_seconds = clock_skew_seconds
        self._jwks_client = jwt.PyJWKClient(
            self.jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=900,
            timeout=5,
        )

    def verify_authorization_header(self, authorization_header: str | None) -> NeonAuthPrincipal:
        if not authorization_header:
            raise NeonAuthenticationError("Authentication required")
        scheme, separator, token = authorization_header.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not token.strip():
            raise NeonAuthenticationError("A bearer token is required")
        return self.verify_token(token.strip())

    def verify_token(self, token: str) -> NeonAuthPrincipal:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "EdDSA":
                raise NeonAuthenticationError("Unsupported token algorithm")
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["EdDSA"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.clock_skew_seconds,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        except NeonAuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError) as exc:
            raise NeonAuthenticationError("Invalid or expired access token") from exc

        subject = _required_string_claim(claims, "sub")
        email = _required_string_claim(claims, "email").casefold()
        if claims.get("id") and claims["id"] != subject:
            raise NeonAuthenticationError("Token subject mismatch")
        if claims.get("banned") is True:
            raise NeonAuthorizationError("This account has been disabled")

        roles = _roles_from_claim(claims.get("role"))
        if "authenticated" not in roles:
            raise NeonAuthorizationError("An authenticated Neon user is required")

        email_verified = bool(claims.get("emailVerified", claims.get("email_verified", False)))
        if self.require_email_verified and not email_verified:
            raise NeonAuthorizationError("Verify your email before opening the workspace")
        name = claims.get("name")
        if not isinstance(name, str) or not name.strip():
            name = email.split("@", 1)[0]
        return NeonAuthPrincipal(
            subject=subject,
            email=email,
            name=name.strip(),
            email_verified=email_verified,
            roles=frozenset(roles),
            claims=dict(claims),
        )


def _required_string_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise NeonAuthenticationError(f"Token is missing the {name} claim")
    return value.strip()


def _roles_from_claim(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.casefold()}
    if isinstance(value, list):
        return {role.casefold() for role in value if isinstance(role, str)}
    return set()
