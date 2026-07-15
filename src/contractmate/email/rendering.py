from __future__ import annotations

from collections import defaultdict

from contractmate.schemas.contracts import ContractReview, RiskSeverity


def render_review_email_text(review: ContractReview) -> str:
    lines = [
        "Samvid Review Complete",
        "",
        f"Contract type: {review.contract_type}",
        f"Suggested next action: {review.recommended_next_action}",
        "",
    ]
    if review.parties:
        lines.append("Parties:")
        lines.extend(f"- {party.name}" for party in review.parties)
        lines.append("")

    risks_by_severity: dict[RiskSeverity, list] = defaultdict(list)
    for risk in review.risks:
        risks_by_severity[risk.severity].append(risk)

    for severity in [RiskSeverity.CRITICAL, RiskSeverity.HIGH, RiskSeverity.MEDIUM, RiskSeverity.LOW]:
        risks = risks_by_severity.get(severity, [])
        if not risks:
            continue
        lines.append(f"{severity.value.title()}-risk findings:")
        for index, risk in enumerate(risks, start=1):
            lines.extend(
                [
                    f"{index}. {risk.title}",
                    f"   Page {risk.evidence.page_number}",
                    f"   Evidence: \"{risk.evidence.exact_text}\"",
                    f"   Recommendation: {risk.recommendation}",
                    "",
                ]
            )

    if review.limitations:
        lines.extend(["Limitations:", *[f"- {item}" for item in review.limitations]])
    return "\n".join(lines).strip()
