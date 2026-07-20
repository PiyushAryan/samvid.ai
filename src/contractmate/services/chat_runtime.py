from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from contractmate.ai.chunking import DocumentChunk
from contractmate.ai.fireworks import FireworksEmbeddingsClient, FireworksRerankClient
from contractmate.ai.retrieval import RetrievedChunk, RetrievalQuery
from contractmate.db.repositories.knowledge import KnowledgeRepository
from contractmate.settings import Settings


@dataclass
class DatabaseHybridRetriever:
    """Scoped lexical plus pgvector retrieval, with Fireworks reranking."""

    repository: KnowledgeRepository
    embeddings: FireworksEmbeddingsClient
    reranker: FireworksRerankClient

    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        vector = self.embeddings.embed_documents([query.text])[0].values
        contract_id = query.filters.get("contract_id") if query.filters else None
        if contract_id is not None and not isinstance(contract_id, str):
            raise ValueError("contract_id retrieval filter must be a string")
        hits = self.repository.hybrid_search(
            workspace_id=query.workspace_id,
            query_text=query.text,
            query_embedding=vector,
            contract_id=contract_id,
            limit=query.candidate_limit,
            candidate_pool=max(query.candidate_limit, 60),
        )
        if not hits:
            return ()
        reranked = self.reranker.rerank(
            query=query.text,
            documents=[hit.chunk.content for hit in hits],
            top_n=min(query.limit, len(hits)),
        )
        results: list[RetrievedChunk] = []
        for rerank in reranked:
            hit = hits[rerank.index]
            chunk = hit.chunk
            page_number = chunk.page_start if chunk.page_start is not None else chunk.page_end
            metadata = {
                **dict(chunk.metadata),
                "contract_version_id": chunk.contract_version_id,
                "source_type": str(chunk.metadata.get("source") or "knowledge_chunk"),
            }
            results.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        id=chunk.id,
                        document_id=str(chunk.metadata.get("document_id", chunk.contract_version_id)),
                        contract_id=chunk.contract_id,
                        page_number=page_number,
                        text=chunk.content,
                        start_char=0,
                        end_char=len(chunk.content),
                        metadata=metadata,
                    ),
                    rrf_score=hit.fused_score,
                    rerank_score=rerank.relevance_score,
                    sources=tuple(
                        source
                        for source, score in (("lexical", hit.lexical_score), ("vector", hit.semantic_score))
                        if score > 0
                    )
                    or ("vector",),
                )
            )
        return tuple(results)


@dataclass
class DatabaseContractReader:
    connection: Any

    @property
    def _postgres(self) -> bool:
        return self.connection.__class__.__module__.startswith("psycopg")

    def get_contract_summary(self, *, workspace_id: str, contract_id: str) -> Mapping[str, Any] | None:
        row = self.connection.execute(
            self._sql(
                """
                SELECT c.id, c.title, c.status, c.created_at, c.updated_at, cr.review_json
                FROM contracts c
                LEFT JOIN contract_versions cv ON cv.id = c.current_version_id
                LEFT JOIN contract_reviews cr ON cr.contract_version_id = cv.id
                WHERE c.workspace_id = ? AND c.id = ?
                LIMIT 1
                """
            ),
            (workspace_id, contract_id),
        ).fetchone()
        if row is None:
            return None
        review = row["review_json"]
        if isinstance(review, str):
            review = json.loads(review)
        return {
            "contract_id": str(row["id"]),
            "title": str(row["title"] or "Untitled contract"),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "review": review,
        }

    def get_contract_timeline(self, *, workspace_id: str, contract_id: str) -> Sequence[Mapping[str, Any]]:
        rows = self.connection.execute(
            self._sql(
                """
                SELECT event_type, actor_type, actor_id, metadata_json, created_at
                FROM audit_events
                WHERE workspace_id = ? AND contract_id = ?
                ORDER BY created_at DESC
                LIMIT 100
                """
            ),
            (workspace_id, contract_id),
        ).fetchall()
        return [
            {
                "event_type": str(row["event_type"]),
                "actor_type": str(row["actor_type"]),
                "actor_id": str(row["actor_id"]) if row["actor_id"] is not None else None,
                "metadata": json.loads(row["metadata_json"])
                if isinstance(row["metadata_json"], str)
                else dict(row["metadata_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self._postgres else statement


def chat_retriever_from_settings(*, settings: Settings, repository: KnowledgeRepository) -> DatabaseHybridRetriever:
    if not settings.fireworks_api_key:
        raise RuntimeError("FIREWORKS_API_KEY is required for contract chat.")
    return DatabaseHybridRetriever(
        repository=repository,
        embeddings=FireworksEmbeddingsClient(
            api_key=settings.fireworks_api_key,
            model_id=settings.embedding_model_id,
            dimensions=settings.embedding_dimensions,
            base_url=settings.fireworks_base_url,
        ),
        reranker=FireworksRerankClient(
            api_key=settings.fireworks_api_key,
            model_id=settings.rerank_model_id,
            base_url=settings.fireworks_base_url,
        ),
    )
