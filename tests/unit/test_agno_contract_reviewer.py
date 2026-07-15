from contractmate.agents.agno_contract_reviewer import _extract_agno_content
from contractmate.schemas.contracts import ContractReview


def test_extract_agno_content_prefers_content_attribute() -> None:
    review = ContractReview(
        contract_id="contract-1",
        contract_type="Vendor agreement",
        parties=[],
        key_terms=[],
        risks=[],
        recommended_next_action="Review with the contract owner.",
        limitations=["Not legal advice."],
    )

    response = type("Response", (), {"content": review})()

    assert _extract_agno_content(response) is review
