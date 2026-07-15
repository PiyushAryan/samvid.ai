from pathlib import Path

from contractmate.agents.agno_contract_reviewer import AgnoContractReviewAgent
from contractmate.ocr.sarvam_vision import SarvamVisionOCR
from contractmate.schemas.documents import DocumentPage, DocumentSpan, ParsedDocument
from contractmate.schemas.contracts import ContractReview, ContractRisk, Evidence, RiskSeverity
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.settings import Settings
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
