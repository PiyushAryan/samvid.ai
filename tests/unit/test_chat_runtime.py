from __future__ import annotations

from types import SimpleNamespace

from contractmate.ai.openrouter import EmbeddingVector
from contractmate.ai.retrieval import RetrievalQuery
from contractmate.services.chat_runtime import DatabaseHybridRetriever


class _Embeddings:
    def embed_documents(self, texts):
        return (EmbeddingVector(index=0, values=(1.0,)),)


class _EmptyReranker:
    def rerank(self, **_kwargs):
        return ()


class _Repository:
    def hybrid_search(self, **kwargs):
        assert kwargs["contract_id"] == "contract-1"
        chunk = SimpleNamespace(
            id="chunk-1",
            contract_id="contract-1",
            contract_version_id="version-1",
            page_start=2,
            page_end=2,
            content="Web Designer Trainee in the Web Development Department",
            metadata={"source": "parsed_document"},
        )
        return [SimpleNamespace(chunk=chunk, fused_score=0.8, lexical_score=1.0, semantic_score=0.7)]


def test_database_retriever_falls_back_to_fused_candidates_when_reranker_is_empty() -> None:
    retriever = DatabaseHybridRetriever(
        repository=_Repository(),  # type: ignore[arg-type]
        embeddings=_Embeddings(),  # type: ignore[arg-type]
        reranker=_EmptyReranker(),  # type: ignore[arg-type]
    )

    results = retriever.retrieve(
        RetrievalQuery(
            workspace_id="workspace-1",
            text="web designer",
            limit=5,
            candidate_limit=10,
            filters={"contract_id": "contract-1"},
        )
    )

    assert len(results) == 1
    assert results[0].chunk.text.startswith("Web Designer Trainee")
    assert results[0].rerank_score is None
    assert results[0].sources == ("lexical", "vector")
