import base64
from pathlib import Path

from contractmate.agents.agno_contract_reviewer import AgnoContractReviewAgent
from contractmate.email.messages import EmailAttachment, InboundEmailMessage
from contractmate.schemas.contracts import ContractReview, ContractRisk, Evidence, RiskSeverity
from contractmate.services.email_ingestion import EmailIngestionService
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.settings import Settings
from contractmate.workers.queue import InMemoryContractQueue
from contractmate.workflows.states import WorkflowState


def test_email_ingestion_processes_base64_attachment(monkeypatch, tmp_path: Path) -> None:
    content = (
        "This Vendor Agreement is made between Acme Ltd and Example Technologies. "
        "The Supplier's liability under this Agreement shall be unlimited."
    )
    monkeypatch.setattr(AgnoContractReviewAgent, "create_contract_review", _fake_contract_review)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        inbound_attachment_dir=tmp_path / "inbound",
        email_workspace_id="email-workspace",
        model_provider="openai",
        model_api_key="test-key",
    )
    message = InboundEmailMessage(
        message_id="email-1",
        thread_id="thread-1",
        from_address="sender@example.com",
        to_addresses=["contracts@example.com"],
        subject="Please review",
        attachments=[
            EmailAttachment(
                filename="vendor-agreement.txt",
                mime_type="text/plain",
                content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
            )
        ],
    )

    result = EmailIngestionService.local(settings).process_inbound_email(message, send_response=False)

    assert result.message_id == "email-1"
    assert len(result.processed) == 1
    assert result.processed[0].status is WorkflowState.REVIEW_READY
    assert result.processed[0].review is not None
    assert result.processed[0].review.risks[0].title == "Unlimited liability"


def test_email_ingestion_reports_rejected_attachment_reason(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        inbound_attachment_dir=tmp_path / "inbound",
        model_provider="openai",
        model_api_key="test-key",
    )
    message = InboundEmailMessage(
        message_id="email-missing-file",
        from_address="sender@example.com",
        attachments=[
            EmailAttachment(
                filename="missing.pdf",
                mime_type="application/pdf",
                local_path=tmp_path / "missing.pdf",
            )
        ],
    )

    result = EmailIngestionService.local(settings).process_inbound_email(message, send_response=False)

    assert result.ignored_attachments == ["missing.pdf"]
    assert len(result.processed) == 1
    assert result.processed[0].status is WorkflowState.REJECTED_FILE
    assert result.processed[0].message == "Uploaded file was not found."


def test_email_ingestion_queues_review_and_defers_response(monkeypatch, tmp_path: Path) -> None:
    content = "Vendor Agreement with enough readable contract text for asynchronous review processing."
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'contractmate.db'}",
        local_storage_dir=tmp_path / "files",
        inbound_attachment_dir=tmp_path / "inbound",
        model_api_key="test-key",
    )
    message = InboundEmailMessage(
        message_id="email-queued",
        from_address="sender@example.com",
        attachments=[
            EmailAttachment(
                filename="vendor-agreement.txt",
                mime_type="text/plain",
                content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
            )
        ],
    )
    queue = InMemoryContractQueue()
    sender = type("Sender", (), {"send": lambda self, message: (_ for _ in ()).throw(AssertionError("response must be deferred"))})()
    service = EmailIngestionService(
        settings=settings,
        processing_service=ContractProcessingService.local(settings),
        sender=sender,
        queue=queue,
    )
    try:
        result = service.process_inbound_email(message, send_response=True)
    finally:
        service.close()

    job = queue.receive()
    assert result.processed[0].status is WorkflowState.QUEUED
    assert job is not None
    assert job.send_review_email


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
            )
        ],
        recommended_next_action="Request revisions before approval.",
        limitations=["Not legal advice."],
    )
