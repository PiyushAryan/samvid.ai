from __future__ import annotations

from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument


def create_contract_review(
    *,
    contract_id: str,
    parsed_document: ParsedDocument,
    agent,
) -> ContractReview:
    return agent.create_contract_review(contract_id=contract_id, parsed_document=parsed_document)
