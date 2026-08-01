from __future__ import annotations

from collections import Counter

from contractmate.schemas.contracts import ContractReview


def receipt_message(filename: str) -> tuple[str, list[dict]]:
    text = f"Samvid received {filename} and queued it for contract review."
    return text, [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Contract received*\n`{_escape(filename)}` is queued for review."}},
    ]


def review_message(
    review: ContractReview | None,
    *,
    filename: str,
    contract_url: str,
    fallback_message: str,
) -> tuple[str, list[dict]]:
    if review is None:
        text = f"Review completed for {filename}. {fallback_message}"
        return text, [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Review completed*\n{_escape(filename)}"}},
            _actions(contract_url),
        ]

    counts = Counter(risk.severity.value for risk in review.risks)
    risk_counts = ", ".join(
        f"{counts[level]} {level}" for level in ("critical", "high", "medium", "low") if counts[level]
    ) or "No risks identified"
    titles = "\n".join(f"• {_escape(risk.title)}" for risk in review.risks[:3])
    text = f"Review completed for {filename}: {risk_counts}. Recommended action: {review.recommended_next_action}"
    fields = (
        f"*Risks*\n{risk_counts}\n\n"
        f"*Recommended action*\n{_escape(review.recommended_next_action)}"
    )
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Contract review ready"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*File*\n{_escape(filename)}\n\n{fields}"}},
    ]
    if titles:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Top risks*\n{titles}"}})
    blocks.append(_actions(contract_url))
    return text, blocks


def failure_message(filename: str) -> tuple[str, list[dict]]:
    text = f"Samvid could not complete the review for {filename}. Please try again or open Samvid for help."
    return text, [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Review failed*\nWe couldn't complete the review for {_escape(filename)}. Please try again."}},
    ]


def rejection_message(message: str) -> tuple[str, list[dict]]:
    text = f"Samvid could not accept this request: {message}"
    return text, [{"type": "section", "text": {"type": "mrkdwn", "text": f"*Contract not accepted*\n{_escape(message)}"}}]


def _actions(contract_url: str) -> dict:
    return {
        "type": "actions",
        "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open in Samvid"}, "url": contract_url}],
    }


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
