from __future__ import annotations

from uuid import UUID, uuid4

from contractmate.schemas.actions import (
    Approval,
    ApprovalDecision,
    DraftResponse,
    ProposedAction,
    ProposedActionStatus,
)
from contractmate.schemas.contracts import ContractReview, RiskSeverity


def draft_contract_response(review: ContractReview) -> DraftResponse:
    priority_risks = [
        risk for risk in review.risks if risk.severity in {RiskSeverity.CRITICAL, RiskSeverity.HIGH}
    ]
    if priority_risks:
        topics = ", ".join(risk.title.lower() for risk in priority_risks[:3])
        text = (
            "Thank you for sharing the agreement. Before proceeding, we would like to "
            f"discuss the {topics} provisions and align the language with our standard position."
        )
        rationale = "Draft focuses on high-priority risks with validated evidence."
    else:
        text = (
            "Thank you for sharing the agreement. We have reviewed the main terms and "
            "would like to clarify a few points before moving forward."
        )
        rationale = "Draft asks for clarification because no high-risk finding was validated."
    return DraftResponse(contract_id=review.contract_id, text=text, rationale=rationale)


def request_human_approval(*, draft: DraftResponse, requested_by: str) -> ProposedAction:
    return ProposedAction(
        id=uuid4(),
        contract_id=draft.contract_id,
        action_type="draft_contract_response",
        payload=draft.model_dump(mode="json"),
        requested_by=requested_by,
    )


def record_approval(
    *,
    action: ProposedAction,
    decision: ApprovalDecision,
    decided_by: str,
    comment: str | None = None,
) -> tuple[ProposedAction, Approval]:
    if action.status is not ProposedActionStatus.PENDING:
        raise ValueError("A proposed action can receive only one final decision.")
    status = {
        ApprovalDecision.APPROVE: ProposedActionStatus.APPROVED,
        ApprovalDecision.REQUEST_CHANGES: ProposedActionStatus.CHANGES_REQUESTED,
        ApprovalDecision.REJECT: ProposedActionStatus.REJECTED,
    }[decision]
    updated = action.model_copy(update={"status": status})
    return updated, Approval(proposed_action_id=UUID(str(action.id)), decision=decision, decided_by=decided_by, comment=comment)
