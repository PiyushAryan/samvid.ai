from __future__ import annotations

from typing import Any, Sequence

import pytest

from contractmate.ai.chunking import PageAwareChunker
from contractmate.ai.fireworks import EmbeddingVector
from contractmate.schemas.documents import DocumentPage, ParsedDocument
from contractmate.services.knowledge_indexing import (
    KnowledgeChunkPayload,
    KnowledgeIndexBackend,
    KnowledgeIndexSpec,
    KnowledgeIndexingService,
)


class FakeEmbeddings:
    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self.batches: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        self.batches.append(list(texts))
        return tuple(
            EmbeddingVector(index=index, values=tuple(float(index + 1) for _ in range(self.dimensions)))
            for index, _ in enumerate(texts)
        )


class FakeIndexBackend(KnowledgeIndexBackend):
    def __init__(self) -> None:
        self.calls: list[tuple[KnowledgeIndexSpec, Sequence[KnowledgeChunkPayload]]] = []

    def replace_index(self, *, spec: KnowledgeIndexSpec, chunks: Sequence[KnowledgeChunkPayload]) -> None:
        self.calls.append((spec, chunks))


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="parsed-1",
        sha256="a" * 64,
        mime_type="application/pdf",
        page_count=2,
        pages=[
            DocumentPage(page_number=1, text="Master services agreement between Alpha and Beta."),
            DocumentPage(page_number=2, text="Either party may terminate with thirty days written notice."),
        ],
        parser_name="pdfmuse",
        parser_version="1",
    )


def _review_json() -> dict[str, Any]:
    return {
        "contract_id": "contract-1",
        "contract_type": "Services agreement",
        "parties": [
            {
                "name": "Alpha",
                "role": "Customer",
                "evidence": {"page_number": 1, "exact_text": "between Alpha and Beta"},
            }
        ],
        "key_terms": [
            {
                "name": "Termination notice",
                "value": "30 days",
                "confidence": 0.96,
                "evidence": {"page_number": 2, "exact_text": "thirty days written notice"},
            }
        ],
        "risks": [
            {
                "title": "Short termination window",
                "severity": "medium",
                "clause_type": "termination",
                "explanation": "The notice window may be operationally short.",
                "recommendation": "Confirm the notice period is workable.",
                "evidence": {"page_number": 2, "exact_text": "thirty days written notice"},
                "confidence": 0.9,
            }
        ],
        "recommended_next_action": "Confirm the termination period.",
        "limitations": ["AI-generated review"],
    }


def test_indexing_combines_parsed_pages_and_structured_review_chunks_atomically() -> None:
    embeddings = FakeEmbeddings()
    backend = FakeIndexBackend()
    service = KnowledgeIndexingService(
        embeddings=embeddings,
        backend=backend,
        embedding_model="fireworks/qwen3-embedding-8b",
        reranker_model="fireworks/qwen3-reranker-8b",
        embedding_dimensions=4,
        embedding_batch_size=2,
        chunker=PageAwareChunker(max_chars=200, overlap_chars=20, min_boundary_chars=50),
    )

    result = service.index_contract(
        workspace_id="workspace-1",
        contract_id="contract-1",
        contract_version_id="version-1",
        parsed_document=_parsed_document(),
        review_json=_review_json(),
    )

    assert len(backend.calls) == 1
    spec, chunks = backend.calls[0]
    assert spec.workspace_id == "workspace-1"
    assert spec.embedding_provider == "fireworks"
    assert spec.embedding_dimensions == 4
    assert result.chunk_count == len(chunks) == 6
    assert sum(len(batch) for batch in embeddings.batches) == len(chunks)
    assert {chunk.metadata["source"] for chunk in chunks} == {"parsed_document", "contract_review"}
    risk = next(chunk for chunk in chunks if chunk.metadata.get("review_kind") == "risk")
    assert risk.page_start == risk.page_end == 2
    assert risk.metadata["citation"] == "contract-1 p.2"
    overview = next(chunk for chunk in chunks if chunk.metadata.get("review_kind") == "review_overview")
    assert overview.page_start is None
    assert overview.metadata["citation"] == "contract-1 review"
    assert all(len(chunk.embedding) == 4 for chunk in chunks)


def test_indexing_rejects_embedding_dimension_mismatch_before_backend_write() -> None:
    backend = FakeIndexBackend()
    service = KnowledgeIndexingService(
        embeddings=FakeEmbeddings(dimensions=3),
        backend=backend,
        embedding_model="embedding-model",
        reranker_model="reranker-model",
        embedding_dimensions=4,
    )

    with pytest.raises(ValueError, match="dimension mismatch"):
        service.index_contract(
            workspace_id="workspace-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            parsed_document=_parsed_document(),
            review_json=_review_json(),
        )

    assert backend.calls == []


def test_indexing_rejects_review_for_another_contract() -> None:
    backend = FakeIndexBackend()
    review = _review_json()
    review["contract_id"] = "different-contract"
    service = KnowledgeIndexingService(
        embeddings=FakeEmbeddings(),
        backend=backend,
        embedding_model="embedding-model",
        reranker_model="reranker-model",
        embedding_dimensions=4,
    )

    with pytest.raises(ValueError, match="does not match"):
        service.index_contract(
            workspace_id="workspace-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            parsed_document=_parsed_document(),
            review_json=review,
        )
