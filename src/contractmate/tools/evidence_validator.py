from __future__ import annotations

from dataclasses import dataclass

from contractmate.parsers.normalization import controlled_normalize
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument


@dataclass(frozen=True)
class EvidenceValidationIssue:
    risk_title: str
    error_code: str
    message: str


@dataclass(frozen=True)
class EvidenceValidationResult:
    valid_review: ContractReview
    issues: list[EvidenceValidationIssue]


def validate_review_evidence(review: ContractReview, parsed_document: ParsedDocument) -> EvidenceValidationResult:
    pages = {page.page_number: controlled_normalize(page.text) for page in parsed_document.pages}
    valid_risks = []
    issues: list[EvidenceValidationIssue] = []
    for risk in review.risks:
        page_text = pages.get(risk.evidence.page_number)
        if page_text is None:
            issues.append(
                EvidenceValidationIssue(risk.title, "PAGE_NOT_FOUND", "Evidence page does not exist.")
            )
            continue
        evidence_text = controlled_normalize(risk.evidence.exact_text)
        if evidence_text not in page_text:
            issues.append(
                EvidenceValidationIssue(
                    risk.title,
                    "EVIDENCE_NOT_FOUND",
                    "Evidence exact_text was not found on the referenced page.",
                )
            )
            continue
        valid_risks.append(risk)

    return EvidenceValidationResult(
        valid_review=review.model_copy(update={"risks": valid_risks}),
        issues=issues,
    )
