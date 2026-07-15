from contractmate.workflows.states import WorkflowState, can_transition


def test_contract_review_state_machine_allows_expected_paths() -> None:
    assert can_transition(WorkflowState.RECEIVED, WorkflowState.VALIDATING)
    assert can_transition(WorkflowState.PARSING, WorkflowState.ANALYSING)
    assert can_transition(WorkflowState.VALIDATING_EVIDENCE, WorkflowState.REVIEW_READY)
    assert not can_transition(WorkflowState.RECEIVED, WorkflowState.REVIEW_READY)
