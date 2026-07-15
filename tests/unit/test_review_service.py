import pytest

from contractmate.agents.agno_contract_reviewer import AgnoContractReviewAgent
from contractmate.services.review_service import ReviewService
from contractmate.settings import Settings


def test_review_service_selects_agno_openai_provider() -> None:
    service = ReviewService.from_settings(
        Settings(model_provider="openai", model_id="gpt-5-mini", model_api_key="test-key")
    )

    assert isinstance(service.agent, AgnoContractReviewAgent)
    assert service.agent.model_id == "gpt-5-mini"
    assert service.agent.api_key == "test-key"


def test_review_service_requires_openai_key() -> None:
    with pytest.raises(RuntimeError):
        ReviewService.from_settings(Settings(model_provider="openai", model_api_key=None))


def test_review_service_rejects_non_openai_provider() -> None:
    with pytest.raises(ValueError):
        ReviewService.from_settings(Settings(model_provider="unsupported", model_api_key="test-key"))
