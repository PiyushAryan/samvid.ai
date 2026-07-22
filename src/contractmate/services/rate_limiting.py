"""Distributed admission control backed by Upstash Redis REST.

This module intentionally stores only opaque SHA-256 identifiers in Redis keys.
It is suitable for API routes and webhook handlers: callers receive a typed decision
instead of handling HTTP or Redis-specific details directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import logging
import re
from secrets import token_urlsafe
from types import MappingProxyType
from typing import Literal, Mapping

import httpx

from contractmate.settings import Settings


RateLimitMode = Literal["observe", "enforce"]

_OPERATION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_KEY_PREFIX = "samvid:ratelimit:v1"
_RESERVATION_PREFIX = "samvid:upload-reservation:v1"
_CONSUMED_RESERVATION_TTL_SECONDS = 86_400
_UPLOAD_PROCESSING_LEASE_SECONDS = 1_800
_UPLOAD_LEASE_RECOVERY_GRACE_SECONDS = 300

logger = logging.getLogger(__name__)


# Minute and hourly limits are token buckets. Daily is intentionally a hard cap:
# a burst that is allowed by the token bucket cannot exceed a product's daily
# allowance. Every mutation happens only after every configured limit passes.
_CONSUME_WINDOWS_LUA = """
local minute_limit = tonumber(ARGV[1])
local hourly_limit = tonumber(ARGV[2])
local daily_limit = tonumber(ARGV[3])
local units = tonumber(ARGV[4])
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000

local function bucket(key, capacity, interval)
  if capacity <= 0 then return nil, -1, 0 end
  local state = redis.call('HMGET', key, 'tokens', 'updated_at')
  local tokens = tonumber(state[1]) or capacity
  local updated_at = tonumber(state[2]) or now
  if updated_at > now then updated_at = now end
  tokens = math.min(capacity, tokens + (now - updated_at) * capacity / interval)
  local retry = tokens + 0.000001 < units and math.ceil((units - tokens) / (capacity / interval)) or 0
  return tokens, math.floor(tokens), retry
end

local minute_tokens, minute_remaining, minute_retry = bucket(KEYS[1], minute_limit, 60)
local hourly_tokens, hourly_remaining, hourly_retry = bucket(KEYS[2], hourly_limit, 3600)
local daily_used = tonumber(redis.call('GET', KEYS[3]) or '0')
local daily_remaining = daily_limit > 0 and math.max(0, daily_limit - daily_used) or -1
local day_ttl = math.max(1, math.ceil(86400 - (now % 86400)))
local daily_retry = daily_limit > 0 and daily_used + units > daily_limit and math.max(1, redis.call('TTL', KEYS[3]), day_ttl) or 0

local minute_denied = minute_limit > 0 and minute_tokens + 0.000001 < units
local hourly_denied = hourly_limit > 0 and hourly_tokens + 0.000001 < units
local daily_denied = daily_limit > 0 and daily_used + units > daily_limit
if minute_denied or hourly_denied or daily_denied then
  return {0, minute_remaining, hourly_remaining, daily_remaining, minute_retry, hourly_retry, daily_retry}
end

if minute_limit > 0 then
  local tokens_after = minute_tokens - units
  redis.call('HSET', KEYS[1], 'tokens', tokens_after, 'updated_at', now)
  redis.call('EXPIRE', KEYS[1], 120)
  minute_remaining = math.floor(tokens_after)
end
if hourly_limit > 0 then
  local tokens_after = hourly_tokens - units
  redis.call('HSET', KEYS[2], 'tokens', tokens_after, 'updated_at', now)
  redis.call('EXPIRE', KEYS[2], 7200)
  hourly_remaining = math.floor(tokens_after)
end
if daily_limit > 0 then
  local daily_after = redis.call('INCRBY', KEYS[3], units)
  if daily_after == units then redis.call('EXPIRE', KEYS[3], day_ttl) end
  daily_remaining = math.max(0, daily_limit - daily_after)
end

return {1, minute_remaining, hourly_remaining, daily_remaining, 0, 0, 0}
""".strip()


# The script checks an existing reservation before touching quota state. It then
# applies the same token-bucket and daily-cap admission atomically with SET NX.
_RESERVE_UPLOAD_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then return {2, 1, -1, -1, -1, 0, 0, 0} end

local minute_limit = tonumber(ARGV[1])
local hourly_limit = tonumber(ARGV[2])
local daily_limit = tonumber(ARGV[3])
local units = tonumber(ARGV[4])
local reservation_ttl = tonumber(ARGV[5])
local observe = tonumber(ARGV[6])
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000

local function bucket(key, capacity, interval)
  if capacity <= 0 then return nil, -1, 0 end
  local state = redis.call('HMGET', key, 'tokens', 'updated_at')
  local tokens = tonumber(state[1]) or capacity
  local updated_at = tonumber(state[2]) or now
  if updated_at > now then updated_at = now end
  tokens = math.min(capacity, tokens + (now - updated_at) * capacity / interval)
  local retry = tokens + 0.000001 < units and math.ceil((units - tokens) / (capacity / interval)) or 0
  return tokens, math.floor(tokens), retry
end

local minute_tokens, minute_remaining, minute_retry = bucket(KEYS[2], minute_limit, 60)
local hourly_tokens, hourly_remaining, hourly_retry = bucket(KEYS[3], hourly_limit, 3600)
local daily_used = tonumber(redis.call('GET', KEYS[4]) or '0')
local daily_remaining = daily_limit > 0 and math.max(0, daily_limit - daily_used) or -1
local day_ttl = math.max(1, math.ceil(86400 - (now % 86400)))
local daily_retry = daily_limit > 0 and daily_used + units > daily_limit and math.max(1, redis.call('TTL', KEYS[4]), day_ttl) or 0

local minute_denied = minute_limit > 0 and minute_tokens + 0.000001 < units
local hourly_denied = hourly_limit > 0 and hourly_tokens + 0.000001 < units
local daily_denied = daily_limit > 0 and daily_used + units > daily_limit
local denied = minute_denied or hourly_denied or daily_denied
if denied and observe == 0 then
  return {1, 0, minute_remaining, hourly_remaining, daily_remaining, minute_retry, hourly_retry, daily_retry}
end

if not denied then
  if minute_limit > 0 then
    local tokens_after = minute_tokens - units
    redis.call('HSET', KEYS[2], 'tokens', tokens_after, 'updated_at', now)
    redis.call('EXPIRE', KEYS[2], 120)
    minute_remaining = math.floor(tokens_after)
  end
  if hourly_limit > 0 then
    local tokens_after = hourly_tokens - units
    redis.call('HSET', KEYS[3], 'tokens', tokens_after, 'updated_at', now)
    redis.call('EXPIRE', KEYS[3], 7200)
    hourly_remaining = math.floor(tokens_after)
  end
  if daily_limit > 0 then
    local daily_after = redis.call('INCRBY', KEYS[4], units)
    if daily_after == units then redis.call('EXPIRE', KEYS[4], day_ttl) end
    daily_remaining = math.max(0, daily_limit - daily_after)
  end
end

redis.call('SET', KEYS[1], 'reserved', 'EX', reservation_ttl)
local observed_allowed = denied and 0 or 1
return {1, observed_allowed, minute_remaining, hourly_remaining, daily_remaining, minute_retry, hourly_retry, daily_retry}
""".strip()

_ACQUIRE_UPLOAD_RESERVATION_LUA = """
local value = redis.call('GET', KEYS[1])
if not value then return {0, 0} end
if value == 'consumed' then return {3, 0} end

local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1])
local lease_seconds = tonumber(ARGV[2])
local recovery_grace = tonumber(ARGV[3])

if string.sub(value, 1, 7) == 'leased:' then
  local lease_expiry = tonumber(string.match(value, ':(%d+)$'))
  if lease_expiry and lease_expiry > now then
    return {2, math.max(1, lease_expiry - now)}
  end
end

if value == 'reserved' or string.sub(value, 1, 7) == 'leased:' then
  local lease_expiry = now + lease_seconds
  local current_ttl = redis.call('TTL', KEYS[1])
  local required_ttl = lease_seconds + recovery_grace
  redis.call('SET', KEYS[1], 'leased:' .. ARGV[1] .. ':' .. lease_expiry)
  redis.call('EXPIRE', KEYS[1], math.max(current_ttl, required_ttl))
  return {1, lease_seconds}
end
return {0, 0}
""".strip()

_FINALIZE_UPLOAD_RESERVATION_LUA = """
local value = redis.call('GET', KEYS[1])
if not value or string.sub(value, 1, 7 + string.len(ARGV[1])) ~= 'leased:' .. ARGV[1] then return 0 end
local remaining = redis.call('PTTL', KEYS[1])
if remaining <= 0 then return 0 end
if ARGV[2] == 'consumed' then
  redis.call('SET', KEYS[1], 'consumed', 'EX', tonumber(ARGV[3]))
else
  redis.call('SET', KEYS[1], 'reserved', 'PX', remaining)
end
return 1
""".strip()


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """The token-bucket and daily-cap quotas applied to one operation."""

    operation: str
    minute_limit: int | None = None
    hourly_limit: int | None = None
    daily_limit: int | None = None

    def __post_init__(self) -> None:
        if not _OPERATION_PATTERN.fullmatch(self.operation):
            raise ValueError("operation must contain only lowercase letters, digits, ':', '_', or '-'")
        if self.minute_limit is None and self.hourly_limit is None and self.daily_limit is None:
            raise ValueError("at least one rate-limit window is required")
        for name, value in (
            ("minute_limit", self.minute_limit),
            ("hourly_limit", self.hourly_limit),
            ("daily_limit", self.daily_limit),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 when provided")


DEFAULT_RATE_LIMIT_POLICIES: Mapping[str, RateLimitPolicy] = MappingProxyType(
    {
        "chat": RateLimitPolicy("chat", minute_limit=10, daily_limit=100),
        "read": RateLimitPolicy("read", minute_limit=120),
        "mutation": RateLimitPolicy("mutation", minute_limit=30),
        "review": RateLimitPolicy("review", hourly_limit=5, daily_limit=20),
    }
)


def default_rate_limit_policy(operation: str) -> RateLimitPolicy:
    """Return the product policy for a supported API operation."""
    try:
        return DEFAULT_RATE_LIMIT_POLICIES[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported rate-limit operation: {operation}") from exc


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Effective result a caller should use to admit or reject work."""

    allowed: bool
    observed_allowed: bool | None
    mode: RateLimitMode
    configured: bool
    minute_remaining: int | None = None
    hourly_remaining: int | None = None
    daily_remaining: int | None = None
    retry_after_seconds: int | None = None
    reason: Literal["disabled", "allowed", "limited", "unavailable"] = "disabled"

    @property
    def enforced(self) -> bool:
        return self.mode == "enforce" and self.configured


@dataclass(frozen=True, slots=True)
class UploadReservationLease:
    """A non-destructive lease for one authorized Vercel Blob pathname."""

    status: Literal["acquired", "missing", "busy", "consumed", "disabled", "unavailable"]
    allowed: bool
    lease_id: str | None = None
    retry_after_seconds: int | None = None


class UpstashRateLimiter:
    """Consumes token buckets and daily caps in one atomic Upstash EVAL call.

    Minute and hourly limits refill continuously; daily quotas are hard UTC caps.
    The service supports multi-unit requests for inbound email attachments.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 1.0,
    ) -> None:
        self._mode: RateLimitMode = settings.rate_limit_mode
        self._url = (settings.upstash_redis_rest_url or "").rstrip("/")
        self._token = settings.upstash_redis_rest_token
        self._configured = bool(self._url and self._token)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def __enter__(self) -> "UpstashRateLimiter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def configured(self) -> bool:
        return self._configured

    def consume(
        self,
        policy: RateLimitPolicy,
        identifier: str,
        *,
        units: int = 1,
    ) -> RateLimitDecision:
        """Consume ``units`` from every configured window for ``identifier``.

        ``identifier`` may be an account id, email address, or IP address. It is
        hashed before being included in a Redis key and never sent as raw PII.
        """
        if units < 1:
            raise ValueError("units must be at least 1")
        if not identifier:
            raise ValueError("identifier is required")
        if not self._configured:
            return RateLimitDecision(
                allowed=True,
                observed_allowed=True,
                mode=self._mode,
                configured=False,
                reason="disabled",
            )

        minute_key, hourly_key, daily_key = self._quota_keys(policy.operation, identifier)
        command = [
            "EVAL",
            _CONSUME_WINDOWS_LUA,
            3,
            minute_key,
            hourly_key,
            daily_key,
            policy.minute_limit or 0,
            policy.hourly_limit or 0,
            policy.daily_limit or 0,
            units,
        ]

        try:
            response = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=command,
            )
            response.raise_for_status()
            result = response.json().get("result")
            (
                allowed,
                minute_remaining,
                hourly_remaining,
                daily_remaining,
                minute_retry,
                hourly_retry,
                daily_retry,
            ) = self._parse_result(result)
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return self._unavailable_decision(policy.operation, identifier)

        decision = self._decision_from_result(
            allowed=allowed,
            minute_remaining=minute_remaining,
            hourly_remaining=hourly_remaining,
            daily_remaining=daily_remaining,
            retry_after_seconds=max(minute_retry, hourly_retry, daily_retry) or None,
        )
        self._log_decision(decision, operation=policy.operation, identifier=identifier)
        return decision

    def reserve_upload(
        self,
        *,
        policy: RateLimitPolicy,
        identifier: str,
        pathname: str,
        ttl_seconds: int = 1_800,
    ) -> RateLimitDecision:
        """Atomically reserve a pathname and consume quota once when it is new."""
        if not pathname:
            raise ValueError("pathname is required")
        if not self._configured:
            return RateLimitDecision(
                allowed=True,
                observed_allowed=True,
                mode=self._mode,
                configured=False,
                reason="disabled",
            )

        minute_key, hourly_key, daily_key = self._quota_keys(policy.operation, identifier)
        command = [
            "EVAL",
            _RESERVE_UPLOAD_LUA,
            4,
            self._reservation_key(identifier, pathname),
            minute_key,
            hourly_key,
            daily_key,
            policy.minute_limit or 0,
            policy.hourly_limit or 0,
            policy.daily_limit or 0,
            1,
            max(1, ttl_seconds),
            1 if self._mode == "observe" else 0,
        ]
        try:
            response = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=command,
            )
            response.raise_for_status()
            result = response.json().get("result")
            action, allowed, minute_remaining, hourly_remaining, daily_remaining, minute_retry, hourly_retry, daily_retry = self._parse_reservation_result(result)
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return self._unavailable_decision(policy.operation, identifier)

        if action == 2:
            decision = RateLimitDecision(
                allowed=True,
                observed_allowed=True,
                mode=self._mode,
                configured=True,
                reason="allowed",
            )
        else:
            decision = self._decision_from_result(
                allowed=allowed,
                minute_remaining=minute_remaining,
                hourly_remaining=hourly_remaining,
                daily_remaining=daily_remaining,
                retry_after_seconds=max(minute_retry, hourly_retry, daily_retry) or None,
            )
        self._log_decision(decision, operation=policy.operation, identifier=identifier)
        return decision

    def acquire_upload_reservation(
        self,
        *,
        identifier: str,
        pathname: str,
        lease_seconds: int = _UPLOAD_PROCESSING_LEASE_SECONDS,
    ) -> UploadReservationLease:
        """Lease an existing reservation without deleting it before durable work."""
        if not pathname:
            return UploadReservationLease(status="missing", allowed=False)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        if not self._configured:
            return UploadReservationLease(status="disabled", allowed=True)
        lease_id = token_urlsafe(24)
        try:
            result = self._command(
                [
                    "EVAL",
                    _ACQUIRE_UPLOAD_RESERVATION_LUA,
                    1,
                    self._reservation_key(identifier, pathname),
                    lease_id,
                    lease_seconds,
                    _UPLOAD_LEASE_RECOVERY_GRACE_SECONDS,
                ]
            )
            if not isinstance(result, list) or len(result) != 2:
                raise ValueError("Upstash lease EVAL returned an unexpected result")
            action, retry_after_seconds = (int(value) for value in result)
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            self._log_unavailable(operation="review", identifier=identifier)
            return UploadReservationLease(status="unavailable", allowed=self._mode == "observe")
        if action == 1:
            return UploadReservationLease(
                status="acquired",
                allowed=True,
                lease_id=lease_id,
                retry_after_seconds=retry_after_seconds,
            )
        if action == 2:
            return UploadReservationLease(
                status="busy",
                allowed=False,
                retry_after_seconds=retry_after_seconds,
            )
        if action == 3:
            return UploadReservationLease(status="consumed", allowed=False)
        return UploadReservationLease(status="missing", allowed=False)

    def mark_upload_reservation_consumed(self, *, identifier: str, pathname: str, lease_id: str) -> bool:
        return self._finalize_upload_reservation(
            identifier=identifier,
            pathname=pathname,
            lease_id=lease_id,
            state="consumed",
        )

    def release_upload_reservation(self, *, identifier: str, pathname: str, lease_id: str) -> bool:
        """Return a leased reservation to retryable state after downstream failure."""
        return self._finalize_upload_reservation(
            identifier=identifier,
            pathname=pathname,
            lease_id=lease_id,
            state="reserved",
        )

    def _finalize_upload_reservation(
        self,
        *,
        identifier: str,
        pathname: str,
        lease_id: str,
        state: Literal["reserved", "consumed"],
    ) -> bool:
        if not self._configured:
            return True
        try:
            result = self._command(
                [
                    "EVAL",
                    _FINALIZE_UPLOAD_RESERVATION_LUA,
                    1,
                    self._reservation_key(identifier, pathname),
                    lease_id,
                    state,
                    _CONSUMED_RESERVATION_TTL_SECONDS,
                ]
            )
            return bool(int(result))
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            self._log_unavailable(operation="review", identifier=identifier)
            return False

    def _decision_from_result(
        self,
        *,
        allowed: bool,
        minute_remaining: int | None,
        hourly_remaining: int | None,
        daily_remaining: int | None,
        retry_after_seconds: int | None,
    ) -> RateLimitDecision:
        effective_allowed = allowed or self._mode == "observe"
        return RateLimitDecision(
            allowed=effective_allowed,
            observed_allowed=allowed,
            mode=self._mode,
            configured=True,
            minute_remaining=minute_remaining,
            hourly_remaining=hourly_remaining,
            daily_remaining=daily_remaining,
            retry_after_seconds=retry_after_seconds,
            reason="allowed" if allowed else "limited",
        )

    @staticmethod
    def hash_identifier(identifier: str) -> str:
        """Return a stable opaque key fragment without retaining the identifier."""
        return sha256(identifier.strip().casefold().encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_result(result: object) -> tuple[bool, int | None, int | None, int | None, int, int, int]:
        if not isinstance(result, list) or len(result) != 7:
            raise ValueError("Upstash EVAL returned an unexpected result")
        (
            raw_allowed,
            raw_minute,
            raw_hourly,
            raw_daily,
            raw_minute_retry,
            raw_hourly_retry,
            raw_daily_retry,
        ) = result
        allowed = bool(int(raw_allowed))

        def optional_remaining(value: object) -> int | None:
            parsed = int(value)
            return None if parsed < 0 else parsed

        return (
            allowed,
            optional_remaining(raw_minute),
            optional_remaining(raw_hourly),
            optional_remaining(raw_daily),
            max(0, int(raw_minute_retry)),
            max(0, int(raw_hourly_retry)),
            max(0, int(raw_daily_retry)),
        )

    @staticmethod
    def _parse_reservation_result(
        result: object,
    ) -> tuple[int, bool, int | None, int | None, int | None, int, int, int]:
        if not isinstance(result, list) or len(result) != 8:
            raise ValueError("Upstash upload reservation EVAL returned an unexpected result")
        action, *decision_values = result
        (
            allowed,
            minute_remaining,
            hourly_remaining,
            daily_remaining,
            minute_retry,
            hourly_retry,
            daily_retry,
        ) = UpstashRateLimiter._parse_result(decision_values)
        return (
            int(action),
            allowed,
            minute_remaining,
            hourly_remaining,
            daily_remaining,
            minute_retry,
            hourly_retry,
            daily_retry,
        )

    def _unavailable_decision(self, operation: str, identifier: str) -> RateLimitDecision:
        # Observe mode is non-disruptive. Enforce mode fails closed so costly
        # operations cannot bypass an admission-control outage.
        decision = RateLimitDecision(
            allowed=self._mode == "observe",
            observed_allowed=None,
            mode=self._mode,
            configured=True,
            retry_after_seconds=5,
            reason="unavailable",
        )
        self._log_unavailable(operation=operation, identifier=identifier)
        return decision

    def _command(self, command: list[object]) -> object:
        response = self._client.post(
            self._url,
            headers={"Authorization": f"Bearer {self._token}"},
            json=command,
        )
        response.raise_for_status()
        payload = response.json()
        if "result" not in payload:
            raise ValueError("Upstash command returned an unexpected result")
        return payload["result"]

    @classmethod
    def _reservation_key(cls, identifier: str, pathname: str) -> str:
        return f"{_RESERVATION_PREFIX}:{cls.hash_identifier(identifier)}:{cls.hash_identifier(pathname)}"

    @classmethod
    def _quota_keys(
        cls,
        operation: str,
        identifier: str,
    ) -> tuple[str, str, str]:
        identity_hash = cls.hash_identifier(identifier)
        return (
            f"{_KEY_PREFIX}:{operation}:{identity_hash}:minute",
            f"{_KEY_PREFIX}:{operation}:{identity_hash}:hour",
            f"{_KEY_PREFIX}:{operation}:{identity_hash}:day",
        )

    def _log_decision(self, decision: RateLimitDecision, *, operation: str, identifier: str) -> None:
        if self._mode == "observe" and decision.observed_allowed is False:
            logger.info(
                "rate_limit_would_block",
                extra={
                    "event": "rate_limit_would_block",
                    "operation": operation,
                    "identifier_hash": self.hash_identifier(identifier),
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )

    def _log_unavailable(self, *, operation: str, identifier: str) -> None:
        logger.warning(
            "rate_limit_unavailable",
            extra={
                "event": "rate_limit_unavailable",
                "operation": operation,
                "identifier_hash": self.hash_identifier(identifier),
                "mode": self._mode,
            },
        )
