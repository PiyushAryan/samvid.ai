from __future__ import annotations

import json
import logging

import httpx
import pytest

from contractmate.services.rate_limiting import (
    DEFAULT_RATE_LIMIT_POLICIES,
    RateLimitPolicy,
    UpstashRateLimiter,
    default_rate_limit_policy,
)
from contractmate.settings import Settings


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _settings(*, mode: str = "enforce") -> Settings:
    return Settings(
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="token",
        rate_limit_mode=mode,
    )


def test_unconfigured_limiter_allows_work_without_making_a_request() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    limiter = UpstashRateLimiter(Settings(), client=_client(handler))

    decision = limiter.consume(RateLimitPolicy("chat", hourly_limit=10), "account@example.com")

    assert decision.allowed is True
    assert decision.configured is False
    assert decision.reason == "disabled"
    assert called is False


def test_consume_uses_upstash_eval_with_hashed_identifier_and_multiple_units() -> None:
    captured: list[list[object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).rstrip("/") == "https://example.upstash.io"
        assert request.headers["Authorization"] == "Bearer token"
        command = json.loads(request.content)
        captured.append(command)
        return httpx.Response(200, json={"result": [1, -1, 3, 17, 0, 0, 0]})

    limiter = UpstashRateLimiter(_settings(), client=_client(handler))
    decision = limiter.consume(
        RateLimitPolicy("inbound-email", hourly_limit=5, daily_limit=20),
        "Piyush.Aryan@example.com",
        units=2,
    )

    command = captured[0]
    identity_hash = UpstashRateLimiter.hash_identifier("Piyush.Aryan@example.com")
    assert command[0] == "EVAL"
    assert command[2] == 3
    assert "Piyush.Aryan@example.com" not in str(command)
    assert identity_hash in command[3]
    assert command[-4:] == [0, 5, 20, 2]
    assert "HMGET" in command[1]
    assert "INCRBY" in command[1]
    assert decision.allowed is True
    assert decision.observed_allowed is True
    assert decision.hourly_remaining == 3
    assert decision.daily_remaining == 17


def test_minute_limit_is_evaluated_and_exposed_in_the_decision() -> None:
    limiter = UpstashRateLimiter(
        _settings(),
        client=_client(lambda _request: httpx.Response(200, json={"result": [1, 8, -1, 91, 0, 0, 0]})),
    )

    decision = limiter.consume(
        RateLimitPolicy("chat", minute_limit=10, daily_limit=100),
        "account-id",
        units=2,
    )

    assert decision.allowed is True
    assert decision.minute_remaining == 8
    assert decision.hourly_remaining is None
    assert decision.daily_remaining == 91


def test_minute_limit_denial_returns_the_minute_retry_after() -> None:
    limiter = UpstashRateLimiter(
        _settings(),
        client=_client(lambda _request: httpx.Response(200, json={"result": [0, 0, -1, 93, 45, 0, 0]})),
    )

    decision = limiter.consume(default_rate_limit_policy("chat"), "account-id")

    assert decision.allowed is False
    assert decision.minute_remaining == 0
    assert decision.daily_remaining == 93
    assert decision.retry_after_seconds == 45


def test_default_policies_match_the_product_admission_rules() -> None:
    assert DEFAULT_RATE_LIMIT_POLICIES["chat"] == RateLimitPolicy("chat", minute_limit=10, daily_limit=100)
    assert DEFAULT_RATE_LIMIT_POLICIES["read"] == RateLimitPolicy("read", minute_limit=120)
    assert DEFAULT_RATE_LIMIT_POLICIES["mutation"] == RateLimitPolicy("mutation", minute_limit=30)
    assert DEFAULT_RATE_LIMIT_POLICIES["review"] == RateLimitPolicy("review", hourly_limit=5, daily_limit=20)
    with pytest.raises(ValueError, match="unsupported"):
        default_rate_limit_policy("unknown")


def test_observe_mode_reports_limit_without_blocking() -> None:
    limiter = UpstashRateLimiter(
        _settings(mode="observe"),
        client=_client(lambda _request: httpx.Response(200, json={"result": [0, -1, 0, 12, 0, 600, 0]})),
    )

    decision = limiter.consume(RateLimitPolicy("review", hourly_limit=5, daily_limit=20), "account-id")

    assert decision.allowed is True
    assert decision.observed_allowed is False
    assert decision.reason == "limited"
    assert decision.retry_after_seconds == 600


def test_upload_reservation_is_one_atomic_eval_and_duplicate_does_not_readmit() -> None:
    commands: list[list[object]] = []
    results = iter(
        [
            [1, 1, -1, 4, 19, 0, 0, 0],
            [2, 1, -1, -1, -1, 0, 0, 0],
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        commands.append(json.loads(request.content))
        return httpx.Response(200, json={"result": next(results)})

    limiter = UpstashRateLimiter(_settings(), client=_client(handler))
    policy = default_rate_limit_policy("review")
    first = limiter.reserve_upload(policy=policy, identifier="account-id", pathname="contracts/ws/file.pdf")
    duplicate = limiter.reserve_upload(policy=policy, identifier="account-id", pathname="contracts/ws/file.pdf")

    assert first.allowed is True
    assert duplicate.allowed is True
    command = commands[0]
    assert command[0] == "EVAL"
    assert command[2] == 4
    assert "contracts/ws/file.pdf" not in str(command)
    assert "account-id" not in str(command)
    assert "redis.call('GET', KEYS[1])" in command[1]
    assert "redis.call('SET', KEYS[1], 'reserved'" in command[1]
    assert "HMGET" in command[1]
    assert "INCRBY" in command[1]


@pytest.mark.parametrize(
    ("result", "status", "allowed", "retry_after"),
    [
        ([1, 1800], "acquired", True, 1800),
        ([2, 17], "busy", False, 17),
        ([3, 0], "consumed", False, None),
        ([0, 0], "missing", False, None),
    ],
)
def test_upload_reservation_lease_states(result, status, allowed, retry_after) -> None:
    limiter = UpstashRateLimiter(
        _settings(),
        client=_client(lambda _request: httpx.Response(200, json={"result": result})),
    )

    lease = limiter.acquire_upload_reservation(identifier="account-id", pathname="contracts/ws/file.pdf")

    assert lease.status == status
    assert lease.allowed is allowed
    assert lease.retry_after_seconds == retry_after
    if status == "acquired":
        assert lease.lease_id


def test_upload_reservation_finalize_supports_consumed_and_retryable_release() -> None:
    commands: list[list[object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        commands.append(json.loads(request.content))
        return httpx.Response(200, json={"result": 1})

    limiter = UpstashRateLimiter(_settings(), client=_client(handler))
    assert limiter.release_upload_reservation(
        identifier="account-id", pathname="contracts/ws/file.pdf", lease_id="lease-1"
    )
    assert limiter.mark_upload_reservation_consumed(
        identifier="account-id", pathname="contracts/ws/file.pdf", lease_id="lease-2"
    )

    assert commands[0][-3:] == ["lease-1", "reserved", 86400]
    assert commands[1][-3:] == ["lease-2", "consumed", 86400]
    assert "leased:" in commands[0][1]


def test_observe_mode_logs_hashed_would_block_without_raw_identifier(caplog) -> None:
    limiter = UpstashRateLimiter(
        _settings(mode="observe"),
        client=_client(lambda _request: httpx.Response(200, json={"result": [0, 0, -1, 90, 30, 0, 0]})),
    )

    with caplog.at_level(logging.INFO):
        limiter.consume(default_rate_limit_policy("chat"), "private@example.com")

    assert "rate_limit_would_block" in caplog.text
    assert "private@example.com" not in caplog.text


def test_enforce_mode_blocks_and_returns_retry_metadata() -> None:
    limiter = UpstashRateLimiter(
        _settings(),
        client=_client(lambda _request: httpx.Response(200, json={"result": [0, -1, 0, 0, 0, 120, 3600]})),
    )

    decision = limiter.consume(RateLimitPolicy("review", hourly_limit=5, daily_limit=20), "account-id")

    assert decision.allowed is False
    assert decision.observed_allowed is False
    assert decision.retry_after_seconds == 3600
    assert decision.enforced is True


@pytest.mark.parametrize(
    ("mode", "expected_allowed"),
    [("observe", True), ("enforce", False)],
)
def test_upstash_failure_is_non_disruptive_in_observe_and_fails_closed_in_enforce(
    mode: str, expected_allowed: bool
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Upstash unavailable")

    limiter = UpstashRateLimiter(_settings(mode=mode), client=_client(handler))

    decision = limiter.consume(RateLimitPolicy("chat", hourly_limit=10), "account-id")

    assert decision.allowed is expected_allowed
    assert decision.observed_allowed is None
    assert decision.reason == "unavailable"


def test_policy_rejects_invalid_operation_limits_and_units() -> None:
    with pytest.raises(ValueError, match="operation"):
        RateLimitPolicy("Chat", hourly_limit=10)
    with pytest.raises(ValueError, match="at least one"):
        RateLimitPolicy("chat")
    with pytest.raises(ValueError, match="at least 1"):
        RateLimitPolicy("chat", hourly_limit=0)
    with pytest.raises(ValueError, match="at least 1"):
        RateLimitPolicy("chat", minute_limit=0)

    limiter = UpstashRateLimiter(Settings())
    with pytest.raises(ValueError, match="units"):
        limiter.consume(RateLimitPolicy("chat", hourly_limit=10), "account-id", units=0)


def test_settings_reads_rate_limit_mode_without_local_dotenv_interference(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_MODE", "enforce")

    settings = Settings.from_env()

    assert settings.rate_limit_mode == "enforce"
