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


def render_receipt_email_text(
    *,
    attachment_count: int,
    recipient_name: str | None = None,
    recipient_address: str | None = None,
) -> str:
    name = email_recipient_name(recipient_name, recipient_address)
    document_label = "document" if attachment_count == 1 else "documents"
    return "\n".join(
        [
            f"Hi {name},",
            "",
            f"Samvid received {attachment_count} contract {document_label} and started the review.",
            "We will reply in this thread when the review is ready.",
            "",
            "Thanks,",
            "Samvid",
            "",
            "Sent via Samvid",
        ]
    )


def render_receipt_email_html(
    *,
    attachment_count: int,
    recipient_name: str | None = None,
    recipient_address: str | None = None,
) -> str:
    name = escape(email_recipient_name(recipient_name, recipient_address))
    document_label = "document" if attachment_count == 1 else "documents"
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f4f6f5;font-family:Arial,sans-serif;color:#14201e">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f5"><tr><td align="center" style="padding:28px 16px">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;border:1px solid #dfe5e3;border-radius:8px;background:#ffffff">'
        '<tr><td style="padding:22px 28px;border-bottom:1px solid #e7ecea"><strong style="font-size:18px;color:#14201e">Samvid</strong>'
        '<span style="float:right;color:#0d9488;font-size:12px;font-weight:700;text-transform:uppercase">Contract review</span></td></tr>'
        '<tr><td style="padding:30px 28px"><p style="margin:0 0 18px;font-size:16px;line-height:1.6">Hi '
        f'{name},</p><h1 style="margin:0 0 10px;font-size:24px;line-height:1.3;color:#14201e">Your review is underway.</h1>'
        '<p style="margin:0;color:#56625f;font-size:14px;line-height:1.6">'
        f"Samvid received {attachment_count} contract {document_label}. We will reply in this thread when the review is ready.</p>"
        '<p style="margin:28px 0 0;color:#56625f;font-size:13px;line-height:1.6">Thanks,<br><strong style="color:#14201e">Samvid</strong><br><br>Sent via Samvid</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )


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
            '<div style="padding:8px 0;border-top:1px solid #e7ecea;color:#30403c;font-size:13px;line-height:1.45">'
            f"<strong style=\"color:#14201e\">{escape(party.name)}</strong>"
            f"{f' <span style=\"color:#6b7673\">&middot; {escape(party.role)}</span>' if party.role else ''}</div>"
            for party in review.parties
        )
        party_html = _section("Parties", f'<div style="border-bottom:1px solid #e7ecea">{items}</div>')

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
            f'style="border:1px solid #e7ecea;border-radius:6px;border-collapse:separate">{rows}</table>',
        )

    risk_sections: list[str] = []
    for severity in SEVERITY_ORDER:
        color, background, border = SEVERITY_COLORS[severity]
        for risk in risks_by_severity.get(severity, []):
            risk_sections.append(
                f'<div style="margin:0 0 10px;padding:15px 16px;border:1px solid #dfe5e3;border-left:3px solid {color};'
                'border-radius:6px;background:#ffffff">'
                f'<div style="margin:0 0 9px;color:{color};font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase">'
                f'{escape(severity.value)} risk &middot; Page {risk.evidence.page_number}</div>'
                f'<h3 style="margin:0 0 6px;color:#14201e;font-size:15px;line-height:1.4">{escape(risk.title)}</h3>'
                f'<p style="margin:0 0 10px;color:#43514e;font-size:13px;line-height:1.55">{escape(risk.explanation)}</p>'
                f'<div style="margin:0 0 10px;padding:9px 11px;border-radius:4px;background:{background};'
                f'color:#43514e;font-size:12px;line-height:1.5">&ldquo;{escape(risk.evidence.exact_text)}&rdquo;</div>'
                f'<p style="margin:0;color:#263532;font-size:12px;line-height:1.55"><strong>Next step:</strong> '
                f'{escape(risk.recommendation)}</p></div>'
            )
    findings_html = "".join(risk_sections) or (
        '<div style="padding:14px 16px;border:1px solid #dfe5e3;border-radius:6px;background:#ffffff;'
        'color:#43514e;font-size:13px;line-height:1.55">No evidence-grounded risks were identified.</div>'
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
            '<div style="margin:26px 0 0">'
            f'<a href="{safe_url}" style="display:inline-block;padding:10px 14px;border-radius:6px;'
            'background:#0d9488;color:#ffffff;font-size:13px;font-weight:700;text-decoration:none">'
            "Open contract in Samvid &rarr;</a></div>"
        )

    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
        '<body style="margin:0;padding:0;background:#f6f7f4;font-family:Arial,Helvetica,sans-serif;color:#14201e">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f7f4">'
        '<tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:620px;border:1px solid #dfe5e3;border-radius:8px;background:#ffffff">'
        '<tr><td style="height:3px;background:#0d9488;font-size:0;line-height:0">&nbsp;</td></tr>'
        '<tr><td style="padding:19px 26px;border-bottom:1px solid #e7ecea">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>'
        '<td style="color:#14201e;font-size:17px;font-weight:700">Samvid</td>'
        '<td align="right" style="color:#0d9488;font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase">Review ready</td>'
        '</tr></table></td></tr><tr><td style="padding:28px 26px 10px">'
        f'<p style="margin:0 0 16px;color:#30403c;font-size:15px;line-height:1.55">Hi {name},</p>'
        '<h1 style="margin:0 0 8px;font-size:23px;line-height:1.25;color:#14201e">Your contract review is ready.</h1>'
        '<p style="margin:0 0 22px;color:#66736f;font-size:13px;line-height:1.55">Here is the short version, with evidence kept close to every finding.</p>'
        '<div style="margin:0 0 25px;padding:15px 16px;border:1px solid #dfe5e3;border-radius:6px;background:#f8faf9">'
        '<div style="margin-bottom:5px;color:#75817d;font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase">Document</div>'
        f'<div style="margin-bottom:14px;color:#14201e;font-size:14px;font-weight:700">{escape(review.contract_type)}</div>'
        '<div style="margin-bottom:5px;color:#75817d;font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase">Recommended next step</div>'
        f'<div style="color:#30403c;font-size:13px;line-height:1.55">{escape(review.recommended_next_action)}</div></div>'
        f'{party_html}{terms_html}{_section("Key findings", findings_html)}{limitations_html}{action_html}'
        '<p style="margin:26px 0 0;color:#43514e;font-size:13px;line-height:1.55">Thanks,<br><strong style="color:#14201e">Samvid</strong></p>'
        '</td></tr><tr><td style="padding:15px 26px;border-top:1px solid #e7ecea;color:#7a8582;font-size:10px">'
        "Sent via Samvid &middot; Contract intelligence that stays with the work</td></tr></table></td></tr></table></body></html>"
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
        '<div style="margin:0 0 25px">'
        f'<h2 style="margin:0 0 9px;color:#14201e;font-size:11px;font-weight:700;letter-spacing:0.08em;line-height:1.4;text-transform:uppercase">{escape(title)}</h2>'
        f"{content}</div>"
    )
