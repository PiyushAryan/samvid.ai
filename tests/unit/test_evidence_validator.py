from contractmate.schemas.contracts import ContractReview, ContractRisk, Evidence, RiskSeverity
from contractmate.schemas.documents import DocumentPage, ParsedDocument
from contractmate.tools.evidence_validator import validate_review_evidence


def _document() -> ParsedDocument:
    return ParsedDocument(
        document_id="contract-1",
        sha256="abc",
        mime_type="text/plain",
        page_count=1,
        pages=[DocumentPage(page_number=1, text="The Supplier's liability under this Agreement shall be unlimited.")],
        parser_name="test",
        parser_version="1",
    )


def test_validate_review_evidence_removes_unsupported_risks() -> None:
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
                evidence=Evidence(page_number=1, exact_text="liability under this Agreement shall be unlimited"),
                confidence=0.9,
            ),
            ContractRisk(
                title="Invented issue",
                severity=RiskSeverity.HIGH,
                clause_type="Other",
                explanation="Unsupported.",
                recommendation="Remove it.",
                evidence=Evidence(page_number=1, exact_text="not in the document"),
                confidence=0.9,
            ),
        ],
        recommended_next_action="Request revisions.",
        limitations=[],
    )

    result = validate_review_evidence(review, _document())

    assert [risk.title for risk in result.valid_review.risks] == ["Unlimited liability"]
    assert len(result.issues) == 1
    assert result.issues[0].error_code == "EVIDENCE_NOT_FOUND"
