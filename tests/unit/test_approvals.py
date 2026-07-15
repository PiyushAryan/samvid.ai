from uuid import uuid4

import pytest

from contractmate.schemas.actions import ApprovalDecision, ProposedAction, ProposedActionStatus
from contractmate.tools.approvals import record_approval


def test_record_approval_is_one_way() -> None:
    action = ProposedAction(
        id=uuid4(),
        contract_id="contract-1",
        action_type="draft_contract_response",
        payload={"text": "draft"},
        requested_by="U1",
    )

    approved, approval = record_approval(action=action, decision=ApprovalDecision.APPROVE, decided_by="U2")

    assert approved.status is ProposedActionStatus.APPROVED
    assert approval.decided_by == "U2"
    with pytest.raises(ValueError):
        record_approval(action=approved, decision=ApprovalDecision.REJECT, decided_by="U2")
