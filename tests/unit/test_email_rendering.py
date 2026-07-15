from contractmate.email.rendering import render_review_email_text
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

    text = render_review_email_text(review)

    assert "Samvid Review Complete" in text
    assert "Page 2" in text
    assert "liability shall be unlimited" in text
