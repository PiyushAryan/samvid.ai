from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from contractmate.ai.chunking import DocumentChunk
from contractmate.ai.fireworks import EmbeddingVector, RerankResult


@dataclass(frozen=True)
class RetrievalQuery:
    workspace_id: str
    text: str
    limit: int = 8
    candidate_limit: int = 30
    filters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not self.text.strip():
            raise ValueError("workspace_id and query text are required.")
        if self.limit < 1 or self.candidate_limit < self.limit:
            raise ValueError("candidate_limit must be greater than or equal to a positive limit.")


@dataclass(frozen=True)
class ScoredChunk:
    chunk: DocumentChunk
    score: float


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    rrf_score: float
    rerank_score: float | None
    sources: tuple[str, ...]

    @property
    def citation(self) -> str:
        return self.chunk.citation


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]: ...


class RerankProvider(Protocol):
    def rerank(self, *, query: str, documents: Sequence[str], top_n: int | None = None) -> tuple[RerankResult, ...]: ...


class LexicalSearchBackend(Protocol):
    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        limit: int,
        filters: Mapping[str, Any],
    ) -> Sequence[ScoredChunk]: ...


class VectorSearchBackend(Protocol):
    def search(
        self,
        *,
        workspace_id: str,
        query_vector: Sequence[float],
        limit: int,
        filters: Mapping[str, Any],
    ) -> Sequence[ScoredChunk]: ...


@dataclass
class HybridRetrievalService:
    embeddings: EmbeddingProvider
    lexical_backend: LexicalSearchBackend
    vector_backend: VectorSearchBackend
    reranker: RerankProvider | None = None
    rrf_rank_constant: int = 60
    lexical_weight: float = 1.0
    vector_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.rrf_rank_constant < 1:
            raise ValueError("rrf_rank_constant must be positive.")
        if self.lexical_weight <= 0 or self.vector_weight <= 0:
            raise ValueError("Retrieval weights must be positive.")

    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        query_vector = self.embeddings.embed_documents([query.text])[0].values
        lexical = self.lexical_backend.search(
            workspace_id=query.workspace_id,
            query=query.text,
            limit=query.candidate_limit,
            filters=query.filters,
        )
        vector = self.vector_backend.search(
            workspace_id=query.workspace_id,
            query_vector=query_vector,
            limit=query.candidate_limit,
            filters=query.filters,
        )
        fused = self._rrf(lexical=lexical, vector=vector)
        if not fused or self.reranker is None:
            return tuple(fused[: query.limit])

        results = self.reranker.rerank(
            query=query.text,
            documents=[item.chunk.text for item in fused],
            top_n=min(query.limit, len(fused)),
        )
        reranked: list[RetrievedChunk] = []
        for result in results:
            item = fused[result.index]
            reranked.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    rrf_score=item.rrf_score,
                    rerank_score=result.relevance_score,
                    sources=item.sources,
                )
            )
        return tuple(reranked[: query.limit])

    def _rrf(
        self,
        *,
        lexical: Sequence[ScoredChunk],
        vector: Sequence[ScoredChunk],
    ) -> list[RetrievedChunk]:
        chunks: dict[str, DocumentChunk] = {}
        scores: dict[str, float] = {}
        sources: dict[str, set[str]] = {}
        for source_name, candidates, weight in (
            ("lexical", lexical, self.lexical_weight),
            ("vector", vector, self.vector_weight),
        ):
            seen: set[str] = set()
            for rank, candidate in enumerate(candidates, start=1):
                chunk_id = candidate.chunk.id
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                chunks.setdefault(chunk_id, candidate.chunk)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (self.rrf_rank_constant + rank)
                sources.setdefault(chunk_id, set()).add(source_name)
        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [
            RetrievedChunk(
                chunk=chunks[chunk_id],
                rrf_score=scores[chunk_id],
                rerank_score=None,
                sources=tuple(sorted(sources[chunk_id])),
            )
            for chunk_id in ordered
        ]
