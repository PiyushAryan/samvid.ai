from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class InvalidSlackSignature(ValueError):
    """Raised when a Slack request cannot be authenticated."""


class SlackTokenCipher:
    """Versioned AES-256-GCM envelope encryption for Slack bot tokens."""

    _VERSION = "v1"
    _AAD = b"samvid:slack-bot-token:v1"

    def __init__(self, encoded_key: str) -> None:
        try:
            padded = encoded_key.strip() + "=" * (-len(encoded_key.strip()) % 4)
            key = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
            raise ValueError("SLACK_TOKEN_ENCRYPTION_KEY must be a base64url-encoded 32-byte key") from exc
        if len(key) != 32:
            raise ValueError("SLACK_TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, token: str) -> str:
        if not token:
            raise ValueError("Slack bot token cannot be empty")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, token.encode("utf-8"), self._AAD)
        envelope = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
        return f"{self._VERSION}.{envelope}"

    def decrypt(self, envelope: str) -> str:
        version, separator, payload = envelope.partition(".")
        if separator != "." or version != self._VERSION or not payload:
            raise ValueError("Unsupported Slack token encryption envelope")
        try:
            padded = payload + "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            if len(decoded) < 29:
                raise ValueError("Encrypted Slack token is malformed")
            plaintext = self._cipher.decrypt(decoded[:12], decoded[12:], self._AAD)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise ValueError("Encrypted Slack token could not be decrypted") from exc


def verify_slack_signature(
    raw_body: bytes,
    *,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> None:
    if not timestamp or not signature or not signing_secret:
        raise InvalidSlackSignature("Missing Slack signature headers")
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise InvalidSlackSignature("Invalid Slack request timestamp") from exc
    current_time = int(time.time()) if now is None else now
    if abs(current_time - request_time) > tolerance_seconds:
        raise InvalidSlackSignature("Slack request timestamp is outside the allowed window")
    base = b"v0:" + timestamp.encode("ascii") + b":" + raw_body
    expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidSlackSignature("Invalid Slack request signature")
