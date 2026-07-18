from __future__ import annotations

from collections import defaultdict
from html import escape

from contractmate.schemas.contracts import ContractReview, RiskSeverity


SEVERITY_ORDER = [RiskSeverity.CRITICAL, RiskSeverity.HIGH, RiskSeverity.MEDIUM, RiskSeverity.LOW]
SEVERITY_COLORS = {
    RiskSeverity.CRITICAL: ("#991b1b", "#fef2f2", "#fecaca"),
    RiskSeverity.HIGH: ("#b45309", "#fffbeb", "#fde68a"),
    RiskSeverity.MEDIUM: ("#a16207", "#fefce8", "#fef08a"),
    RiskSeverity.LOW: ("#166534", "#f0fdf4", "#bbf7d0"),
}


def render_review_email_text(
    review: ContractReview,
    *,
    recipient_name: str | None = None,
    recipient_address: str | None = None,
    contract_url: str | None = None,
) -> str:
    name = email_recipient_name(recipient_name, recipient_address)
    lines = [
        f"Hi {name},",
        "",
        "Your contract review is ready.",
        "",
        f"Contract type: {review.contract_type}",
        f"Recommended next step: {review.recommended_next_action}",
        "",
    ]
    if review.parties:
        lines.append("Parties")
        lines.extend(f"- {party.name}{f' ({party.role})' if party.role else ''}" for party in review.parties)
        lines.append("")
    if review.key_terms:
        lines.append("Key terms")
        lines.extend(f"- {term.name}: {term.value or 'Not found'}" for term in review.key_terms)
        lines.append("")

    risks_by_severity = _risks_by_severity(review)
    lines.extend(["Key findings", ""])
    if not review.risks:
        lines.extend(["No evidence-grounded risks were identified.", ""])
    for severity in SEVERITY_ORDER:
        for risk in risks_by_severity.get(severity, []):
            lines.extend(
                [
                    f"[{severity.value.upper()}] {risk.title}",
                    f"Why it matters: {risk.explanation}",
                    f"Evidence (Page {risk.evidence.page_number}): \"{risk.evidence.exact_text}\"",
                    f"Recommendation: {risk.recommendation}",
                    "",
                ]
            )

    if review.limitations:
        lines.extend(["Review limitations", *[f"- {item}" for item in review.limitations], ""])
    if contract_url:
        lines.extend(["Open the contract in Samvid:", contract_url, ""])
    lines.extend(["Thanks,", "Samvid", "", "Sent via Samvid"])
    return "\n".join(lines).strip()


def render_review_email_html(
    review: ContractReview,
    *,
    recipient_name: str | None = None,
    recipient_address: str | None = None,
    contract_url: str | None = None,
) -> str:
    name = escape(email_recipient_name(recipient_name, recipient_address))
    risks_by_severity = _risks_by_severity(review)
    party_html = ""
    if review.parties:
        items = "".join(
            f"<li style=\"margin:0 0 6px\"><strong>{escape(party.name)}</strong>"
            f"{f' &mdash; {escape(party.role)}' if party.role else ''}</li>"
            for party in review.parties
        )
        party_html = _section("Parties", f'<ul style="margin:0;padding-left:20px;color:#34413f">{items}</ul>')

    terms_html = ""
    if review.key_terms:
        rows = "".join(
            '<tr>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e7ecea;color:#56625f;font-size:13px">{escape(term.name)}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e7ecea;color:#14201e;font-size:13px;font-weight:700">'
            f'{escape(term.value or "Not found")}</td></tr>'
            for term in review.key_terms
        )
        terms_html = _section(
            "Key terms",
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            f'style="border:1px solid #e7ecea;border-radius:6px">{rows}</table>',
        )

    risk_sections: list[str] = []
    for severity in SEVERITY_ORDER:
        color, background, border = SEVERITY_COLORS[severity]
        for risk in risks_by_severity.get(severity, []):
            risk_sections.append(
                '<div style="margin:0 0 14px;padding:18px;border:1px solid #dfe5e3;border-radius:6px;background:#ffffff">'
                f'<span style="display:inline-block;margin-bottom:10px;padding:3px 7px;border:1px solid {border};'
                f'border-radius:4px;background:{background};color:{color};font-size:11px;font-weight:700;'
                f'text-transform:uppercase">{escape(severity.value)}</span>'
                f'<h3 style="margin:0 0 8px;color:#14201e;font-size:16px;line-height:1.4">{escape(risk.title)}</h3>'
                f'<p style="margin:0 0 10px;color:#43514e;font-size:14px;line-height:1.6">{escape(risk.explanation)}</p>'
                f'<div style="margin:0 0 10px;padding:11px 13px;border-left:3px solid #0d9488;background:#f4f8f7;'
                f'color:#43514e;font-size:13px;line-height:1.55"><strong>Page {risk.evidence.page_number}:</strong> '
                f'&ldquo;{escape(risk.evidence.exact_text)}&rdquo;</div>'
                f'<p style="margin:0;color:#263532;font-size:14px;line-height:1.6"><strong>Recommendation:</strong> '
                f'{escape(risk.recommendation)}</p></div>'
            )
    findings_html = "".join(risk_sections) or (
        '<p style="margin:0;color:#43514e;font-size:14px;line-height:1.6">'
        "No evidence-grounded risks were identified.</p>"
    )

    limitations_html = ""
    if review.limitations:
        items = "".join(f'<li style="margin:0 0 6px">{escape(item)}</li>' for item in review.limitations)
        limitations_html = _section(
            "Review limitations",
            f'<ul style="margin:0;padding-left:20px;color:#56625f;font-size:13px;line-height:1.6">{items}</ul>',
        )

    action_html = ""
    if contract_url:
        safe_url = escape(contract_url, quote=True)
        action_html = (
            '<div style="margin:28px 0">'
            f'<a href="{safe_url}" style="display:inline-block;padding:11px 17px;border-radius:6px;'
            'background:#0d9488;color:#ffffff;font-size:14px;font-weight:700;text-decoration:none">'
            "Open contract in Samvid</a></div>"
        )

    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f4f6f5;font-family:Arial,sans-serif;color:#14201e">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f5">'
        '<tr><td align="center" style="padding:28px 16px">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:640px;border:1px solid #dfe5e3;border-radius:8px;background:#ffffff">'
        '<tr><td style="padding:22px 28px;border-bottom:1px solid #e7ecea">'
        '<strong style="font-size:18px;color:#14201e">Samvid</strong>'
        '<span style="float:right;color:#0d9488;font-size:12px;font-weight:700;text-transform:uppercase">Contract review</span>'
        '</td></tr><tr><td style="padding:30px 28px">'
        f'<p style="margin:0 0 18px;font-size:16px;line-height:1.6">Hi {name},</p>'
        '<h1 style="margin:0 0 10px;font-size:24px;line-height:1.3;color:#14201e">Your contract review is ready.</h1>'
        '<p style="margin:0 0 24px;color:#56625f;font-size:14px;line-height:1.6">'
        "Samvid reviewed the document and organized the key terms, risks, and recommended next step below.</p>"
        '<div style="margin:0 0 24px;padding:16px;border:1px solid #dfe5e3;border-radius:6px;background:#f8faf9">'
        f'<div style="margin-bottom:8px;color:#6b7673;font-size:11px;font-weight:700;text-transform:uppercase">Contract type</div>'
        f'<div style="margin-bottom:16px;font-size:15px;font-weight:700">{escape(review.contract_type)}</div>'
        '<div style="margin-bottom:8px;color:#6b7673;font-size:11px;font-weight:700;text-transform:uppercase">Recommended next step</div>'
        f'<div style="font-size:14px;line-height:1.6">{escape(review.recommended_next_action)}</div></div>'
        f'{party_html}{terms_html}{_section("Key findings", findings_html)}{limitations_html}{action_html}'
        '<p style="margin:28px 0 0;color:#263532;font-size:14px;line-height:1.6">Thanks,<br><strong>Samvid</strong></p>'
        '</td></tr><tr><td style="padding:16px 28px;border-top:1px solid #e7ecea;color:#7a8582;font-size:11px">'
        "Sent via Samvid</td></tr></table></td></tr></table></body></html>"
    )


def email_recipient_name(display_name: str | None, address: str | None) -> str:
    if display_name and display_name.strip():
        return " ".join(display_name.split())
    local_part = (address or "").partition("@")[0]
    words = local_part.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words) or "there"


def _risks_by_severity(review: ContractReview) -> dict[RiskSeverity, list]:
    grouped: dict[RiskSeverity, list] = defaultdict(list)
    for risk in review.risks:
        grouped[risk.severity].append(risk)
    return grouped


def _section(title: str, content: str) -> str:
    return (
        '<div style="margin:0 0 24px">'
        f'<h2 style="margin:0 0 12px;color:#14201e;font-size:16px;line-height:1.4">{escape(title)}</h2>'
        f"{content}</div>"
    )
