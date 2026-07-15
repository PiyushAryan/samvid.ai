from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    RECEIVED = "received"
    VALIDATING = "validating"
    REJECTED_FILE = "rejected_file"
    QUEUED = "queued"
    PARSING = "parsing"
    OCR_REQUIRED = "ocr_required"
    PARSE_FAILED = "parse_failed"
    ANALYSING = "analysing"
    ANALYSIS_FAILED = "analysis_failed"
    VALIDATING_EVIDENCE = "validating_evidence"
    REVIEW_READY = "review_ready"
    DRAFT_REQUESTED = "draft_requested"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED_ACTION = "rejected_action"
    APPROVED_ACTION = "approved_action"
    COMPLETED = "completed"


ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.RECEIVED: {WorkflowState.VALIDATING},
    WorkflowState.VALIDATING: {WorkflowState.REJECTED_FILE, WorkflowState.QUEUED},
    WorkflowState.QUEUED: {WorkflowState.PARSING},
    WorkflowState.PARSING: {
        WorkflowState.OCR_REQUIRED,
        WorkflowState.PARSE_FAILED,
        WorkflowState.ANALYSING,
    },
    WorkflowState.ANALYSING: {
        WorkflowState.ANALYSIS_FAILED,
        WorkflowState.VALIDATING_EVIDENCE,
    },
    WorkflowState.VALIDATING_EVIDENCE: {
        WorkflowState.ANALYSING,
        WorkflowState.REVIEW_READY,
    },
    WorkflowState.REVIEW_READY: {
        WorkflowState.DRAFT_REQUESTED,
        WorkflowState.COMPLETED,
    },
    WorkflowState.DRAFT_REQUESTED: {WorkflowState.AWAITING_APPROVAL},
    WorkflowState.AWAITING_APPROVAL: {
        WorkflowState.REJECTED_ACTION,
        WorkflowState.APPROVED_ACTION,
    },
    WorkflowState.APPROVED_ACTION: {WorkflowState.COMPLETED},
    WorkflowState.REJECTED_FILE: set(),
    WorkflowState.OCR_REQUIRED: set(),
    WorkflowState.PARSE_FAILED: set(),
    WorkflowState.ANALYSIS_FAILED: set(),
    WorkflowState.REJECTED_ACTION: set(),
    WorkflowState.COMPLETED: set(),
}


def can_transition(current: WorkflowState, target: WorkflowState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
