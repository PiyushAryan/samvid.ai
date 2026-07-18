from contractmate.email.rendering import email_recipient_name, render_review_email_html, render_review_email_text
from contractmate.schemas.contracts import ContractReview, ContractRisk, Evidence, RiskSeverity


def test_render_review_email_text_includes_evidence() -> None:
    review = ContractReview(
        contract_id="contract-1",
        contract_type="Vendor agreement",
        parties=[],
        key_terms=[],
        risks=[
            ContractRisk(
                title="Unlimited liability",
                severity=RiskSeverity.HIGH,
                clause_type="Liability",
                explanation="Uncapped exposure.",
                recommendation="Request a cap.",
                evidence=Evidence(page_number=2, exact_text="liability shall be unlimited"),
                confidence=0.9,
            )
        ],
        recommended_next_action="Request revisions.",
        limitations=["Not legal advice."],
    )

    text = render_review_email_text(
        review,
        recipient_name="Piyush Aryan",
        recipient_address="piyush@example.com",
        contract_url="https://samvid-ai.vercel.app/contracts/contract-1",
    )
    html = render_review_email_html(
        review,
        recipient_name="Piyush Aryan",
        recipient_address="piyush@example.com",
        contract_url="https://samvid-ai.vercel.app/contracts/contract-1",
    )

    assert text.startswith("Hi Piyush Aryan,")
    assert "Page 2" in text
    assert "liability shall be unlimited" in text
    assert "https://samvid-ai.vercel.app/contracts/contract-1" in text
    assert "Thanks,\nSamvid\n\nSent via Samvid" in text
    assert "Hi Piyush Aryan," in html
    assert 'href="https://samvid-ai.vercel.app/contracts/contract-1"' in html
    assert "Open contract in Samvid" in html
    assert "Sent via Samvid" in html


def test_email_recipient_name_falls_back_to_address_local_part() -> None:
    assert email_recipient_name(None, "piyush.aryan@example.com") == "Piyush Aryan"
    assert email_recipient_name(None, None) == "there"
