from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class ProposedActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class ProposedAction(BaseModel):
    id: UUID
    contract_id: str
    action_type: str
    payload: dict
    status: ProposedActionStatus = ProposedActionStatus.PENDING
    requested_by: str


class Approval(BaseModel):
    proposed_action_id: UUID
    decision: ApprovalDecision
    decided_by: str
    comment: str | None = None


class DraftResponse(BaseModel):
    contract_id: str
    text: str = Field(min_length=1)
    rationale: str
