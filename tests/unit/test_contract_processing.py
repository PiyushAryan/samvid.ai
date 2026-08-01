from pathlib import Path

import pytest

from contractmate.agents.agno_contract_reviewer import AgnoContractReviewAgent
from contractmate.ocr.sarvam_vision import SarvamVisionOCR
from contractmate.schemas.documents import DocumentPage, DocumentSpan, ParsedDocument
from contractmate.schemas.contracts import ContractReview, ContractRisk, Evidence, RiskSeverity
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.db.repositories.processing_runs import ProcessingRunRepository
from contractmate.db.repositories.slack import SlackRepository
from contractmate.settings import Settings
from contractmate.workers.queue import InMemoryContractQueue
from contractmate.workers.review_publish_outbox import SlackReviewPublishDispatcher
from contractmate.workflows.states import WorkflowState


def test_contract_processing_end_to_end_with_agno_review_stub(monkeypatch, tmp_path: Path) -> None:
    contract = tmp_path / "vendor-agreement.txt"
    contract.write_text(
        """
        This Vendor Agreement is made between Acme Ltd and Example Technologies.
        The effective date is 1 January 2026.
        The term is 12 months.
        This Agreement renews automatically unless terminated with 60 days notice.
        The Supplier's liability under this Agreement shall be unlimited.
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_provider="openai",
        model_api_key="test-key",
    )

    result = ContractProcessingService.local(settings).review_local_file(
        file_path=contract,
        workspace_id="T1",
        email_thread_id="email-thread-1",
        requested_by="reviewer@example.com",
    )

    assert result.status is WorkflowState.REVIEW_READY
    assert result.review is not None
    assert result.review.contract_type == "Vendor agreement"
    assert {risk.title for risk in result.review.risks} == {"Unlimited liability", "Automatic renewal"}


def test_contract_processing_uses_sarvam_for_scanned_pdf(monkeypatch, tmp_path: Path) -> None:
    from pypdf import PdfWriter

    contract = tmp_path / "scanned-vendor-agreement.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with contract.open("wb") as output:
        writer.write(output)

    def fake_ocr(self, file_path, *, parsed_document):
        text = (
            "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
            "The Supplier's liability under this Agreement shall be unlimited."
        )
        return ParsedDocument(
            document_id=parsed_document.document_id,
            sha256=parsed_document.sha256,
            mime_type=parsed_document.mime_type,
            page_count=1,
            pages=[
                DocumentPage(
                    page_number=1,
                    text=text,
                    spans=[DocumentSpan(text=text, page_number=1)],
                )
            ],
            parser_name="sarvam-vision",
            parser_version="test",
            requires_ocr=False,
        )

    monkeypatch.setattr(SarvamVisionOCR, "extract", fake_ocr)
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_provider="openai",
        model_api_key="test-key",
        enable_ocr=True,
        sarvam_api_key="sarvam-key",
    )

    result = ContractProcessingService.local(settings).review_local_file(
        file_path=contract,
        workspace_id="T1",
        email_thread_id="email-thread-ocr",
        requested_by="reviewer@example.com",
    )

    assert result.status is WorkflowState.REVIEW_READY
    assert result.review is not None
    assert result.review.risks[0].title == "Unlimited liability"


def test_queued_contract_is_reviewed_from_durable_storage(monkeypatch, tmp_path: Path) -> None:
    contract = tmp_path / "queued-vendor-agreement.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The Supplier's liability under this Agreement shall be unlimited.",
        encoding="utf-8",
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_provider="openai",
        model_api_key="test-key",
    )
    queue = InMemoryContractQueue()
    producer = ContractProcessingService.local(settings)
    try:
        queued = producer.enqueue_local_file(
            queue=queue,
            file_path=contract,
            workspace_id="T1",
            email_thread_id="email-thread-queued",
            requested_by="reviewer@example.com",
        )
    finally:
        producer.close()

    job = queue.receive()
    assert job is not None
    assert queued.status is WorkflowState.QUEUED

    consumer = ContractProcessingService.local(settings)
    try:
        result = consumer.review_stored_contract(
            contract_id=job.contract_id,
            contract_version_id=job.contract_version_id,
            workspace_id=job.workspace_id,
        )
    finally:
        consumer.close()

    assert result.status is WorkflowState.REVIEW_READY
    assert result.review is not None
    assert result.review.risks[0].title == "Unlimited liability"


def test_existing_review_restores_contract_to_review_ready(monkeypatch, tmp_path: Path) -> None:
    contract = tmp_path / "existing-review.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The Supplier's liability under this Agreement shall be unlimited.",
        encoding="utf-8",
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_provider="openai",
        model_api_key="test-key",
    )

    producer = ContractProcessingService.local(settings)
    try:
        reviewed = producer.review_local_file(
            file_path=contract,
            workspace_id="T1",
            email_thread_id="email-thread-existing-review",
            requested_by="reviewer@example.com",
        )
        producer.repository.update_contract_status(reviewed.contract_id, WorkflowState.QUEUED)
    finally:
        producer.close()

    consumer = ContractProcessingService.local(settings)
    try:
        result = consumer.review_stored_contract(
            contract_id=reviewed.contract_id,
            contract_version_id=reviewed.contract_version_id,
            workspace_id="T1",
        )
        persisted = consumer.repository.connection.execute(
            "SELECT status FROM contracts WHERE id = ?",
            (reviewed.contract_id,),
        ).fetchone()
    finally:
        consumer.close()

    assert result.status is WorkflowState.REVIEW_READY
    assert result.review is not None
    assert persisted is not None
    assert persisted["status"] == WorkflowState.REVIEW_READY.value


def test_enqueue_failure_marks_processing_run_failed(tmp_path: Path) -> None:
    contract = tmp_path / "queue-failure.txt"
    contract.write_text("A valid contract document.", encoding="utf-8")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    try:
        with pytest.raises(RuntimeError, match="broker unavailable"):
            service.enqueue_local_file(
                queue=_FailingQueue(),
                file_path=contract,
                workspace_id="workspace-1",
                email_thread_id="samvid-upload-test",
                requested_by="user@example.com",
            )

        runs = ProcessingRunRepository(service.repository.connection).list_recent()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].failure_stage == "queue"
        assert runs[0].failure_error == "broker unavailable"
    finally:
        service.close()


def test_slack_enqueue_records_slack_processing_source(tmp_path: Path) -> None:
    contract = tmp_path / "slack-contract.txt"
    contract.write_text("A valid contract submitted through Slack.", encoding="utf-8")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    try:
        service.enqueue_local_file(
            queue=InMemoryContractQueue(),
            file_path=contract,
            workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:123.456",
            requested_by="user@example.com",
            source_channel="slack",
            slack_installation_id="installation-1",
            slack_channel_id="C1",
            slack_thread_ts="123.456",
        )

        runs = ProcessingRunRepository(service.repository.connection).list_recent()
        assert len(runs) == 1
        assert runs[0].source == "slack"
    finally:
        service.close()


def test_completed_ambiguous_slack_publish_retry_does_not_requeue_or_create_run(monkeypatch, tmp_path: Path) -> None:
    contract = tmp_path / "ambiguous-slack.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The effective date is 1 January 2026 and the term is 12 months. "
        "The Supplier's liability under this Agreement shall be unlimited.", encoding="utf-8",
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files", model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    queue = InMemoryContractQueue()
    try:
        reviewed = service.review_local_file(
            file_path=contract, workspace_id="workspace-1", email_thread_id="slack:T1:C1:1.0",
            requested_by="user@example.com", source_channel="slack",
        )
        execution_repository = SlackRepository(service.repository.connection)
        execution = execution_repository.claim_review_execution(submission_key="Ev1:F1")
        assert execution.lease_token
        assert execution_repository.complete_review_execution(
            submission_key="Ev1:F1", lease_token=execution.lease_token,
        )
        assert execution_repository.get_review_execution_status(submission_key="Ev1:F1") == "completed"
        assert service.repository.get_contract_review(
            reviewed.contract_id, contract_version_id=reviewed.contract_version_id,
        ) is not None
        runs_before = len(ProcessingRunRepository(service.repository.connection).list_recent())

        retried = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:1.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key="Ev1:F1", review_job_id="stable-job",
            slack_installation_id="install-1", slack_channel_id="C1", slack_thread_ts="1.0",
        )
        runs_after = len(ProcessingRunRepository(service.repository.connection).list_recent())
        status = service.repository.connection.execute(
            "SELECT status FROM contracts WHERE id = ?", (reviewed.contract_id,),
        ).fetchone()["status"]
    finally:
        service.close()

    assert retried.status is WorkflowState.REVIEW_READY
    assert queue.receive() is None
    assert runs_after == runs_before
    assert status == WorkflowState.REVIEW_READY.value


def test_processing_slack_submission_retry_reuses_active_run_without_requeue(tmp_path: Path) -> None:
    contract = tmp_path / "processing-slack.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The effective date is 1 January 2026 and the term is 12 months.",
        encoding="utf-8",
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files", model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    queue = InMemoryContractQueue()
    try:
        first = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:1.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key="Ev-processing:F1",
            review_job_id="stable-processing-job", slack_installation_id="install-1",
            slack_channel_id="C1", slack_thread_ts="1.0",
        )
        execution = SlackRepository(service.repository.connection).claim_review_execution(
            submission_key="Ev-processing:F1",
        )
        assert execution.status == "claimed"
        service.repository.update_contract_status(first.contract_id, WorkflowState.ANALYSING)

        retried = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:1.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key="Ev-processing:F1",
            review_job_id="stable-processing-job", slack_installation_id="install-1",
            slack_channel_id="C1", slack_thread_ts="1.0",
        )
        runs = ProcessingRunRepository(service.repository.connection).list_recent()
        persisted_status = service.repository.connection.execute(
            "SELECT status FROM contracts WHERE id = ?", (first.contract_id,),
        ).fetchone()["status"]
        original_job = queue.receive()
        duplicate_job = queue.receive()
    finally:
        service.close()

    assert retried.processing_run_id == first.processing_run_id
    assert len(runs) == 1
    assert persisted_status == WorkflowState.ANALYSING.value
    assert original_job is not None
    assert duplicate_job is None


@pytest.mark.parametrize("terminal_status", [WorkflowState.OCR_REQUIRED, WorkflowState.PARSE_FAILED])
def test_completed_non_review_slack_submission_retry_preserves_terminal_status(
    tmp_path: Path, terminal_status: WorkflowState,
) -> None:
    contract = tmp_path / f"completed-{terminal_status.value}.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The effective date is 1 January 2026 and the term is 12 months.",
        encoding="utf-8",
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files", model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    queue = InMemoryContractQueue()
    submission_key = f"Ev-{terminal_status.value}:F1"
    try:
        first = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:1.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key=submission_key,
            review_job_id=f"stable-{terminal_status.value}", slack_installation_id="install-1",
            slack_channel_id="C1", slack_thread_ts="1.0",
        )
        assert queue.receive() is not None
        execution_repository = SlackRepository(service.repository.connection)
        execution = execution_repository.claim_review_execution(submission_key=submission_key)
        assert execution.lease_token
        service.repository.update_contract_status(first.contract_id, terminal_status)
        assert execution_repository.complete_review_execution(
            submission_key=submission_key, lease_token=execution.lease_token,
        )

        retried = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:1.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key=submission_key,
            review_job_id=f"stable-{terminal_status.value}", slack_installation_id="install-1",
            slack_channel_id="C1", slack_thread_ts="1.0",
        )
    finally:
        service.close()

    assert retried.status is terminal_status
    assert retried.review is None
    assert queue.receive() is None


def test_unconfirmed_slack_publish_retry_republishes_same_run_envelope(tmp_path: Path) -> None:
    contract = tmp_path / "unconfirmed-slack.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The effective date is 1 January 2026 and the term is 12 months.",
        encoding="utf-8",
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files", model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    queue = _AcceptedButUnconfirmedQueue()
    try:
        first = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:2.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key="Ev-unconfirmed:F1",
            review_job_id="stable-unconfirmed-job", slack_installation_id="install-1",
            slack_channel_id="C1", slack_thread_ts="2.0",
        )
        service.repository.connection.execute(
            "UPDATE slack_review_job_outbox SET next_attempt_at = '2000-01-01T00:00:00+00:00'"
        )
        service.repository.connection.commit()
        SlackReviewPublishDispatcher(
            repository=SlackRepository(service.repository.connection), queue=queue.inner,
        ).drain_once()
        first_job = queue.inner.receive()
        second_job = queue.inner.receive()
        runs = ProcessingRunRepository(service.repository.connection).list_recent()
        outbox = service.repository.connection.execute(
            "SELECT status, attempts FROM slack_review_job_outbox WHERE submission_key = ?",
            ("Ev-unconfirmed:F1",),
        ).fetchone()
    finally:
        service.close()

    assert first_job is not None and second_job is not None
    assert first_job.job_id == second_job.job_id == "stable-unconfirmed-job"
    assert first_job.processing_run_id == second_job.processing_run_id == first.processing_run_id
    assert len(runs) == 1
    assert runs[0].status == "queued"
    assert outbox["status"] == "published"
    assert outbox["attempts"] == 2


def test_new_slack_submission_of_reviewed_sha_is_queued_for_its_own_final(monkeypatch, tmp_path: Path) -> None:
    contract = tmp_path / "same-reviewed-sha.txt"
    contract.write_text(
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The effective date is 1 January 2026 and the term is 12 months. "
        "The Supplier's liability under this Agreement shall be unlimited.", encoding="utf-8",
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files", model_api_key="test-key",
    )
    service = ContractProcessingService.local(settings)
    queue = InMemoryContractQueue()
    try:
        reviewed = service.review_local_file(
            file_path=contract, workspace_id="workspace-1", email_thread_id="email-thread-1",
            requested_by="user@example.com", source_channel="email",
        )
        submitted = service.enqueue_local_file(
            queue=queue, file_path=contract, workspace_id="workspace-1",
            email_thread_id="slack:T1:C1:2.0", requested_by="user@example.com",
            source_channel="slack", source_submission_key="Ev2:F1", review_job_id="stable-job-2",
            slack_installation_id="install-1", slack_channel_id="C1", slack_thread_ts="2.0",
        )
        job = queue.receive()
    finally:
        service.close()

    assert submitted.status is WorkflowState.QUEUED
    assert submitted.contract_id == reviewed.contract_id
    assert job is not None
    assert job.source_submission_key == "Ev2:F1"
    assert job.slack_thread_ts == "2.0"


class _FailingQueue:
    def enqueue(self, **_kwargs):
        raise RuntimeError("broker unavailable")


class _AcceptedButUnconfirmedQueue:
    def __init__(self) -> None:
        self.inner = InMemoryContractQueue()
        self.first = True

    def enqueue(self, **kwargs):
        job = self.inner.enqueue(**kwargs)
        if self.first:
            self.first = False
            raise RuntimeError("publisher confirmation lost")
        return job


def _fake_contract_review(self, *, contract_id, parsed_document) -> ContractReview:
    return ContractReview(
        contract_id=contract_id,
        contract_type="Vendor agreement",
        parties=[],
        key_terms=[],
        risks=[
            ContractRisk(
                title="Unlimited liability",
                severity=RiskSeverity.HIGH,
                clause_type="Liability",
                explanation="The agreement may expose a party to uncapped liability.",
                recommendation="Request an aggregate liability cap.",
                evidence=Evidence(
                    page_number=1,
                    exact_text="The Supplier's liability under this Agreement shall be unlimited",
                ),
                confidence=0.9,
            ),
            ContractRisk(
                title="Automatic renewal",
                severity=RiskSeverity.MEDIUM,
                clause_type="Auto-renewal",
                explanation="The agreement may renew unless notice is given.",
                recommendation="Add a renewal reminder.",
                evidence=Evidence(
                    page_number=1,
                    exact_text="This Agreement renews automatically unless terminated with 60 days notice",
                ),
                confidence=0.9,
            ),
        ],
        recommended_next_action="Request revisions before approval.",
        limitations=["Not legal advice."],
    )
