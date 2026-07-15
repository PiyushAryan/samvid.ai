from __future__ import annotations

from typing import Any

from contractmate.agents.agno_contract_reviewer import AgnoContractReviewAgent
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.settings import Settings
from contractmate.tools.evidence_validator import EvidenceValidationResult, validate_review_evidence


class ReviewService:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReviewService":
        provider = settings.model_provider.casefold()
        if provider == "openai":
            if not settings.model_api_key:
                raise RuntimeError("MODEL_API_KEY or OPENAI_API_KEY is required when MODEL_PROVIDER=openai.")
            return cls(AgnoContractReviewAgent(model_id=settings.model_id, api_key=settings.model_api_key))
        raise ValueError(f"Unsupported MODEL_PROVIDER={settings.model_provider!r}. Use 'openai'.")

    def create_validated_review(self, *, contract_id: str, parsed_document: ParsedDocument) -> EvidenceValidationResult:
        review: ContractReview = self.agent.create_contract_review(
            contract_id=contract_id,
            parsed_document=parsed_document,
        )
        return validate_review_evidence(review, parsed_document)
