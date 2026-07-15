from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contractmate.agents.instructions import CONTRACT_REVIEW_SYSTEM_INSTRUCTIONS
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument
from contractmate.security.prompt_injection import wrap_untrusted_document_text


@dataclass
class AgnoContractReviewAgent:
    """Agno agent backed by OpenAIChat for structured contract extraction.

    This keeps Agno as the application-level AI framework while using OpenAI as
    the model provider.
    """

    model_id: str
    api_key: str
    prompt_version: str = "mvp-agno-openai-2026-07-14"
    model_provider: str = "openai"

    @property
    def model_name(self) -> str:
        return self.model_id

    def create_contract_review(self, *, contract_id: str, parsed_document: ParsedDocument) -> ContractReview:
        try:
            from agno.agent import Agent
            from agno.models.openai import OpenAIChat
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install Agno and OpenAI dependencies to use MODEL_PROVIDER=openai.") from exc
        except ImportError as exc:
            raise RuntimeError("Install the OpenAI SDK to use Agno's OpenAIChat model.") from exc

        agent = Agent(
            name="Contract Review Agent",
            model=OpenAIChat(id=self.model_id, api_key=self.api_key, strict_output=True),
            instructions=CONTRACT_REVIEW_SYSTEM_INSTRUCTIONS,
            output_schema=ContractReview,
            structured_outputs=True,
            parse_response=True,
        )
        response = agent.run(self._prompt(contract_id=contract_id, parsed_document=parsed_document))
        content = _extract_agno_content(response)
        if isinstance(content, ContractReview):
            return content
        return ContractReview.model_validate(content)

    def _prompt(self, *, contract_id: str, parsed_document: ParsedDocument) -> str:
        document_text = "\n\n".join(f"Page {page.page_number}\n{page.text}" for page in parsed_document.pages)
        return (
            f"Create a structured contract review for contract_id={contract_id}.\n"
            "Return only fields matching the ContractReview schema.\n"
            "Every risk must include exact evidence text copied from the supplied page-aware text.\n"
            "Use null for missing facts; do not guess.\n"
            "Separate document facts from risk interpretation and recommendations.\n\n"
            f"{wrap_untrusted_document_text(document_text)}"
        )


def _extract_agno_content(response: Any) -> Any:
    for attribute in ("content", "output", "data"):
        value = getattr(response, attribute, None)
        if value is not None:
            return value
    return response
