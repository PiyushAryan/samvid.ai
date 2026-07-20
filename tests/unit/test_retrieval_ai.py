from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from contractmate.ai.chunking import DocumentChunk, PageAwareChunker, PageContent
from contractmate.ai.fireworks import EmbeddingVector, RerankResult
from contractmate.ai.retrieval import HybridRetrievalService, RetrievalQuery, ScoredChunk


def _chunk(chunk_id: str, text: str, page: int = 1) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id="document-1",
        contract_id="contract-1",
        page_number=page,
        text=text,
        start_char=0,
        end_char=len(text),
    )


class FakeEmbeddings:
    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        assert texts == ["termination rights"]
        return (EmbeddingVector(index=0, values=(0.2, 0.8)),)


class FakeLexical:
    calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Sequence[ScoredChunk]:
        self.calls.append(kwargs)
        return [ScoredChunk(_chunk("a", "alpha"), 9), ScoredChunk(_chunk("b", "beta", 2), 8)]


class FakeVector:
    calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Sequence[ScoredChunk]:
        self.calls.append(kwargs)
        return [ScoredChunk(_chunk("b", "beta", 2), 0.9), ScoredChunk(_chunk("c", "gamma", 3), 0.8)]


class FakeReranker:
    def rerank(self, *, query: str, documents: Sequence[str], top_n: int | None = None) -> tuple[RerankResult, ...]:
        assert query == "termination rights"
        assert list(documents)[:3] == ["beta", "alpha", "gamma"]
        assert top_n == 2
        return (RerankResult(index=1, relevance_score=0.95), RerankResult(index=0, relevance_score=0.8))


def test_page_chunker_never_crosses_pages_and_keeps_offsets_and_citations() -> None:
    chunker = PageAwareChunker(max_chars=100, overlap_chars=20, min_boundary_chars=40)
    pages = [
        PageContent(page_number=1, text=("First sentence. " * 12).strip()),
        PageContent(page_number=2, text="Second page clause."),
    ]

    chunks = chunker.chunk_pages(document_id="doc", contract_id="contract", pages=pages)

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert all(chunk.end_char > chunk.start_char for chunk in chunks)
    assert chunks[-1].citation == "contract p.2"
    assert len({chunk.id for chunk in chunks}) == len(chunks)


def test_page_chunker_rejects_duplicate_page_numbers() -> None:
    with pytest.raises(ValueError, match="unique positive"):
        PageAwareChunker().chunk_pages(
            document_id="doc",
            contract_id="contract",
            pages=[PageContent(1, "a"), PageContent(1, "b")],
        )


def test_hybrid_retrieval_scopes_both_backends_and_reranks_rrf_candidates() -> None:
    lexical = FakeLexical()
    vector = FakeVector()
    service = HybridRetrievalService(
        embeddings=FakeEmbeddings(),
        lexical_backend=lexical,
        vector_backend=vector,
        reranker=FakeReranker(),
    )

    results = service.retrieve(
        RetrievalQuery(
            workspace_id="private-workspace",
            text="termination rights",
            limit=2,
            candidate_limit=3,
            filters={"contract_id": "contract-1"},
        )
    )

    assert [item.chunk.id for item in results] == ["a", "b"]
    assert results[0].rerank_score == 0.95
    assert results[1].sources == ("lexical", "vector")
    assert lexical.calls[0]["workspace_id"] == "private-workspace"
    assert vector.calls[0]["workspace_id"] == "private-workspace"
    assert vector.calls[0]["query_vector"] == (0.2, 0.8)
    assert lexical.calls[0]["filters"] == {"contract_id": "contract-1"}


def test_retrieval_query_requires_workspace_scope() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        RetrievalQuery(workspace_id="", text="question")
