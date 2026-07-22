from types import SimpleNamespace

import pytest

from contractmate.db.repositories.inbound_email_events import InboundEventClaim
from contractmate.email.resend_inbound import ResendInboundService, ResendWebhookEvent
from contractmate.services.rate_limiting import RateLimitDecision
from contractmate.settings import Settings


@pytest.mark.parametrize(
    ("state", "expected_operation", "expected_identifier"),
    [
        ("active", "review", "account-1"),
        ("unclaimed", "inbound-email", "sender@example.com"),
    ],
)
def test_only_active_accounts_receive_regular_inbound_quota(
    state: str,
    expected_operation: str,
    expected_identifier: str,
) -> None:
    limiter = _DenyingRateLimiter()
    service = ResendInboundService(
        settings=Settings(
            resend_inbound_recipients=("contracts@oldimeluub.resend.app",),
            max_file_size_mb=20,
        ),
        event_repository=_EventRepository(),
        ingestion_service=SimpleNamespace(),
        client=_ReceivingClient(),
        account_access=SimpleNamespace(
            repository=SimpleNamespace(
                get_by_email=lambda _email: SimpleNamespace(
                    id="account-1",
                    role="user",
                    state=state,
                )
            )
        ),
        rate_limiter=limiter,
    )

    result = service.process(
        ResendWebhookEvent(
            type="email.received",
            data={
                "email_id": "email-1",
                "to": ["contracts@oldimeluub.resend.app"],
            },
        ),
        event_id="event-1",
        payload_hash="payload-hash",
    )

    assert result.status == "rate_limited"
    assert limiter.operation == expected_operation
    assert limiter.identifier == expected_identifier
    assert limiter.units == 1


class _EventRepository:
    def claim(self, **_kwargs):
        return InboundEventClaim.ACQUIRED

    def mark_completed(self, _email_id: str) -> None:
        pass

    def mark_failed(self, _email_id: str) -> None:
        pass


class _ReceivingClient:
    def get_email(self, _email_id: str) -> dict:
        return {
            "from": "Sender <sender@example.com>",
            "to": ["contracts@oldimeluub.resend.app"],
        }

    def list_attachments(self, _email_id: str) -> list[dict]:
        return [
            {
                "filename": "contract.txt",
                "content_type": "text/plain",
                "content_disposition": "attachment",
                "size": 100,
            }
        ]


class _DenyingRateLimiter:
    operation = ""
    identifier = ""
    units = 0

    def consume(self, policy, identifier: str, *, units: int):
        self.operation = policy.operation
        self.identifier = identifier
        self.units = units
        return RateLimitDecision(
            allowed=False,
            observed_allowed=False,
            mode="enforce",
            configured=True,
            reason="limited",
        )
