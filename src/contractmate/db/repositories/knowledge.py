from __future__ import annotations

import json
import math
import re
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4


EMBEDDING_DIMENSIONS = 1024
_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class KnowledgeIndex:
    id: str
    workspace_id: str
    contract_id: str
    contract_version_id: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    reranker_provider: str
    reranker_model: str
    chunking_version: str
    status: str
    chunk_count: int
    error_message: str | None
    indexed_at: Any | None
    created_at: Any
    updated_at: Any


@dataclass(frozen=True, slots=True)
class KnowledgeChunkInput:
    ordinal: int
    content: str
    embedding: Sequence[float]
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: str
    knowledge_index_id: str
    workspace_id: str
    contract_id: str
    contract_version_id: str
    ordinal: int
    content: str
    content_sha256: str
    page_start: int | None
    page_end: int | None
    token_count: int | None
    metadata: dict[str, Any]
    embedding: tuple[float, ...]
    created_at: Any


@dataclass(frozen=True, slots=True)
class KnowledgeSearchHit:
    chunk: KnowledgeChunk
    semantic_score: float
    lexical_score: float
    fused_score: float


class KnowledgeRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.is_postgres = connection.__class__.__module__.startswith("psycopg")

    def create_or_get_index(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        embedding_provider: str,
        embedding_model: str,
        reranker_provider: str,
        reranker_model: str,
        chunking_version: str,
    ) -> KnowledgeIndex:
        self._require_contract_version(
            workspace_id=workspace_id,
            contract_id=contract_id,
            contract_version_id=contract_version_id,
        )
        index_id = str(uuid4())
        statement = (
            """
            INSERT INTO knowledge_indexes(
                id, workspace_id, contract_id, contract_version_id,
                embedding_provider, embedding_model, embedding_dimensions,
                reranker_provider, reranker_model, chunking_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT (workspace_id, contract_version_id, embedding_model, chunking_version) DO NOTHING
            """
            if self.is_postgres
            else """
            INSERT OR IGNORE INTO knowledge_indexes(
                id, workspace_id, contract_id, contract_version_id,
                embedding_provider, embedding_model, embedding_dimensions,
                reranker_provider, reranker_model, chunking_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """
        )
        with self._transaction():
            self.connection.execute(
                self._sql(statement),
                (
                    index_id,
                    workspace_id,
                    contract_id,
                    contract_version_id,
                    embedding_provider,
                    embedding_model,
                    EMBEDDING_DIMENSIONS,
                    reranker_provider,
                    reranker_model,
                    chunking_version,
                ),
            )
        index = self.get_index_for_version(
            workspace_id=workspace_id,
            contract_version_id=contract_version_id,
            embedding_model=embedding_model,
            chunking_version=chunking_version,
        )
        if index is None:
            raise RuntimeError("Knowledge index could not be created")
        return index

    def replace_index(self, *, spec: Any, chunks: Sequence[Any]) -> None:
        """Persist one fully embedded contract index as an atomic replacement."""
        index = self.create_or_get_index(
            workspace_id=spec.workspace_id,
            contract_id=spec.contract_id,
            contract_version_id=spec.contract_version_id,
            embedding_provider=spec.embedding_provider,
            embedding_model=spec.embedding_model,
            reranker_provider=spec.reranker_provider,
            reranker_model=spec.reranker_model,
            chunking_version=spec.chunking_version,
        )
        self.mark_indexing(workspace_id=spec.workspace_id, index_id=index.id)
        try:
            self.replace_chunks(
                workspace_id=spec.workspace_id,
                index_id=index.id,
                chunks=[
                    KnowledgeChunkInput(
                        ordinal=chunk.ordinal,
                        content=chunk.content,
                        embedding=chunk.embedding,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        token_count=chunk.token_count,
                        metadata=chunk.metadata,
                    )
                    for chunk in chunks
                ],
            )
        except Exception as exc:
            self.mark_failed(workspace_id=spec.workspace_id, index_id=index.id, error_message=str(exc))
            raise
        self.mark_ready(workspace_id=spec.workspace_id, index_id=index.id)

    def get_index(self, *, workspace_id: str, index_id: str) -> KnowledgeIndex | None:
        row = self.connection.execute(
            self._sql("SELECT * FROM knowledge_indexes WHERE workspace_id = ? AND id = ?"),
            (workspace_id, index_id),
        ).fetchone()
        return self._index_from_row(row) if row else None

    def get_index_for_version(
        self,
        *,
        workspace_id: str,
        contract_version_id: str,
        embedding_model: str,
        chunking_version: str,
    ) -> KnowledgeIndex | None:
        row = self.connection.execute(
            self._sql(
                """
                SELECT * FROM knowledge_indexes
                WHERE workspace_id = ? AND contract_version_id = ?
                  AND embedding_model = ? AND chunking_version = ?
                LIMIT 1
                """
            ),
            (workspace_id, contract_version_id, embedding_model, chunking_version),
        ).fetchone()
        return self._index_from_row(row) if row else None

    def mark_indexing(self, *, workspace_id: str, index_id: str) -> bool:
        return self._set_status(workspace_id=workspace_id, index_id=index_id, status="indexing")

    def mark_ready(self, *, workspace_id: str, index_id: str) -> bool:
        return self._set_status(workspace_id=workspace_id, index_id=index_id, status="ready")

    def mark_failed(self, *, workspace_id: str, index_id: str, error_message: str) -> bool:
        return self._set_status(
            workspace_id=workspace_id,
            index_id=index_id,
            status="failed",
            error_message=error_message[:4000],
        )

    def replace_chunks(
        self,
        *,
        workspace_id: str,
        index_id: str,
        chunks: Sequence[KnowledgeChunkInput],
    ) -> list[KnowledgeChunk]:
        index = self.get_index(workspace_id=workspace_id, index_id=index_id)
        if index is None:
            raise KeyError("Knowledge index not found")

        prepared = [self._prepare_chunk(chunk) for chunk in chunks]
        ordinals = [item[0].ordinal for item in prepared]
        hashes = [item[1] for item in prepared]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("Chunk ordinals must be unique within an index")
        if len(set(hashes)) != len(hashes):
            raise ValueError("Chunk content must be unique within an index")

        insert_sql = (
            """
            INSERT INTO knowledge_chunks(
                id, knowledge_index_id, workspace_id, contract_id, contract_version_id,
                ordinal, content, content_sha256, page_start, page_end, token_count, metadata, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, CAST(? AS vector))
            """
            if self.is_postgres
            else """
            INSERT INTO knowledge_chunks(
                id, knowledge_index_id, workspace_id, contract_id, contract_version_id,
                ordinal, content, content_sha256, page_start, page_end, token_count, metadata, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        with self._transaction(immediate=not self.is_postgres):
            current = self._get_index_in_transaction(workspace_id=workspace_id, index_id=index_id)
            if current is None:
                raise KeyError("Knowledge index not found")
            self.connection.execute(
                self._sql("DELETE FROM knowledge_chunks WHERE workspace_id = ? AND knowledge_index_id = ?"),
                (workspace_id, index_id),
            )
            for chunk, content_hash, embedding in prepared:
                self.connection.execute(
                    self._sql(insert_sql),
                    (
                        str(uuid4()),
                        index_id,
                        workspace_id,
                        current.contract_id,
                        current.contract_version_id,
                        chunk.ordinal,
                        chunk.content.strip(),
                        content_hash,
                        chunk.page_start,
                        chunk.page_end,
                        chunk.token_count,
                        json.dumps(dict(chunk.metadata or {}), separators=(",", ":")),
                        self._serialize_embedding(embedding),
                    ),
                )
            self.connection.execute(
                self._sql(
                    """
                    UPDATE knowledge_indexes
                    SET status = 'indexing', chunk_count = ?, error_message = NULL,
                        indexed_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = ? AND id = ?
                    """
                ),
                (len(prepared), workspace_id, index_id),
            )
        return self.list_chunks(workspace_id=workspace_id, index_id=index_id)

    def list_chunks(self, *, workspace_id: str, index_id: str) -> list[KnowledgeChunk]:
        embedding_column = "embedding::text AS embedding" if self.is_postgres else "embedding"
        rows = self.connection.execute(
            self._sql(
                f"""
                SELECT id, knowledge_index_id, workspace_id, contract_id, contract_version_id,
                       ordinal, content, content_sha256, page_start, page_end, token_count,
                       metadata, {embedding_column}, created_at
                FROM knowledge_chunks
                WHERE workspace_id = ? AND knowledge_index_id = ?
                ORDER BY ordinal
                """
            ),
            (workspace_id, index_id),
        ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def hybrid_search(
        self,
        *,
        workspace_id: str,
        query_text: str,
        query_embedding: Sequence[float],
        contract_id: str | None = None,
        limit: int = 20,
        candidate_pool: int = 100,
    ) -> list[KnowledgeSearchHit]:
        embedding = self._validate_embedding(query_embedding)
        query_text = query_text.strip()
        if not query_text:
            raise ValueError("query_text is required")
        limit = max(1, min(limit, 100))
        candidate_pool = max(limit, min(candidate_pool, 500))
        if self.is_postgres:
            return self._postgres_hybrid_search(
                workspace_id=workspace_id,
                query_text=query_text,
                query_embedding=embedding,
                contract_id=contract_id,
                limit=limit,
                candidate_pool=candidate_pool,
            )
        return self._sqlite_hybrid_search(
            workspace_id=workspace_id,
            query_text=query_text,
            query_embedding=embedding,
            contract_id=contract_id,
            limit=limit,
            candidate_pool=candidate_pool,
        )

    def _postgres_hybrid_search(
        self,
        *,
        workspace_id: str,
        query_text: str,
        query_embedding: tuple[float, ...],
        contract_id: str | None,
        limit: int,
        candidate_pool: int,
    ) -> list[KnowledgeSearchHit]:
        contract_filter = "AND kc.contract_id = ?" if contract_id else ""
        contract_params: tuple[Any, ...] = (contract_id,) if contract_id else ()
        sql = f"""
            WITH query_values AS MATERIALIZED (
                SELECT CAST(? AS vector) AS embedding, websearch_to_tsquery('english', ?) AS text_query
            ),
            semantic AS MATERIALIZED (
                SELECT kc.id,
                       ROW_NUMBER() OVER (ORDER BY kc.embedding <=> q.embedding) AS semantic_rank,
                       1.0 - (kc.embedding <=> q.embedding) AS semantic_score
                FROM knowledge_chunks kc
                JOIN knowledge_indexes ki
                  ON ki.id = kc.knowledge_index_id AND ki.workspace_id = kc.workspace_id
                JOIN contracts current_contract
                  ON current_contract.id = kc.contract_id
                 AND current_contract.workspace_id = kc.workspace_id
                 AND current_contract.current_version_id = kc.contract_version_id
                CROSS JOIN query_values q
                WHERE kc.workspace_id = ? AND ki.status = 'ready' {contract_filter}
                ORDER BY kc.embedding <=> q.embedding
                LIMIT ?
            ),
            lexical AS MATERIALIZED (
                SELECT kc.id,
                       ROW_NUMBER() OVER (ORDER BY ts_rank_cd(kc.search_vector, q.text_query) DESC) AS lexical_rank,
                       ts_rank_cd(kc.search_vector, q.text_query) AS lexical_score
                FROM knowledge_chunks kc
                JOIN knowledge_indexes ki
                  ON ki.id = kc.knowledge_index_id AND ki.workspace_id = kc.workspace_id
                JOIN contracts current_contract
                  ON current_contract.id = kc.contract_id
                 AND current_contract.workspace_id = kc.workspace_id
                 AND current_contract.current_version_id = kc.contract_version_id
                CROSS JOIN query_values q
                WHERE kc.workspace_id = ? AND ki.status = 'ready'
                  AND kc.search_vector @@ q.text_query {contract_filter}
                ORDER BY lexical_score DESC
                LIMIT ?
            ),
            candidates AS (
                SELECT id FROM semantic UNION SELECT id FROM lexical
            )
            SELECT kc.id, kc.knowledge_index_id, kc.workspace_id, kc.contract_id,
                   kc.contract_version_id, kc.ordinal, kc.content, kc.content_sha256,
                   kc.page_start, kc.page_end, kc.token_count, kc.metadata,
                   kc.embedding::text AS embedding, kc.created_at,
                   COALESCE(s.semantic_score, 0.0) AS semantic_score,
                   COALESCE(l.lexical_score, 0.0) AS lexical_score,
                   COALESCE(1.0 / (60.0 + s.semantic_rank), 0.0)
                     + COALESCE(1.0 / (60.0 + l.lexical_rank), 0.0) AS fused_score
            FROM candidates c
            JOIN knowledge_chunks kc ON kc.id = c.id
            LEFT JOIN semantic s ON s.id = c.id
            LEFT JOIN lexical l ON l.id = c.id
            WHERE kc.workspace_id = ?
            ORDER BY fused_score DESC, semantic_score DESC, kc.id
            LIMIT ?
        """
        params = (
            self._serialize_embedding(query_embedding),
            query_text,
            workspace_id,
            *contract_params,
            candidate_pool,
            workspace_id,
            *contract_params,
            candidate_pool,
            workspace_id,
            limit,
        )
        rows = self.connection.execute(self._sql(sql), params).fetchall()
        return [self._search_hit_from_row(row) for row in rows]

    def _sqlite_hybrid_search(
        self,
        *,
        workspace_id: str,
        query_text: str,
        query_embedding: tuple[float, ...],
        contract_id: str | None,
        limit: int,
        candidate_pool: int,
    ) -> list[KnowledgeSearchHit]:
        contract_filter = "AND kc.contract_id = ?" if contract_id else ""
        params: tuple[Any, ...] = (workspace_id, contract_id) if contract_id else (workspace_id,)
        rows = self.connection.execute(
            f"""
            SELECT kc.*
            FROM knowledge_chunks kc
            JOIN knowledge_indexes ki
              ON ki.id = kc.knowledge_index_id AND ki.workspace_id = kc.workspace_id
            JOIN contracts current_contract
              ON current_contract.id = kc.contract_id
             AND current_contract.workspace_id = kc.workspace_id
             AND current_contract.current_version_id = kc.contract_version_id
            WHERE kc.workspace_id = ? AND ki.status = 'ready' {contract_filter}
            """,
            params,
        ).fetchall()
        query_terms = set(_TOKEN_PATTERN.findall(query_text.casefold()))
        scored: list[tuple[KnowledgeChunk, float, float]] = []
        for row in rows:
            chunk = self._chunk_from_row(row)
            semantic_score = self._cosine_similarity(query_embedding, chunk.embedding)
            chunk_terms = set(_TOKEN_PATTERN.findall(chunk.content.casefold()))
            lexical_score = len(query_terms & chunk_terms) / max(1, len(query_terms))
            scored.append((chunk, semantic_score, lexical_score))

        semantic_ranked = sorted(scored, key=lambda item: (-item[1], item[0].id))[:candidate_pool]
        lexical_ranked = sorted(scored, key=lambda item: (-item[2], item[0].id))[:candidate_pool]
        semantic_ranks = {item[0].id: rank for rank, item in enumerate(semantic_ranked, 1)}
        lexical_ranks = {
            item[0].id: rank for rank, item in enumerate(lexical_ranked, 1) if item[2] > 0
        }
        by_id = {item[0].id: item for item in semantic_ranked + lexical_ranked}
        hits = [
            KnowledgeSearchHit(
                chunk=item[0],
                semantic_score=item[1],
                lexical_score=item[2],
                fused_score=(
                    (1.0 / (60.0 + semantic_ranks[chunk_id]) if chunk_id in semantic_ranks else 0.0)
                    + (1.0 / (60.0 + lexical_ranks[chunk_id]) if chunk_id in lexical_ranks else 0.0)
                ),
            )
            for chunk_id, item in by_id.items()
        ]
        return sorted(hits, key=lambda hit: (-hit.fused_score, -hit.semantic_score, hit.chunk.id))[:limit]

    def _set_status(
        self,
        *,
        workspace_id: str,
        index_id: str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        indexed_at = "CURRENT_TIMESTAMP" if status == "ready" else "NULL"
        with self._transaction():
            result = self.connection.execute(
                self._sql(
                    f"""
                    UPDATE knowledge_indexes
                    SET status = ?, error_message = ?, indexed_at = {indexed_at}, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = ? AND id = ?
                    """
                ),
                (status, error_message, workspace_id, index_id),
            )
        return result.rowcount == 1

    def _require_contract_version(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
    ) -> None:
        row = self.connection.execute(
            self._sql(
                """
                SELECT 1
                FROM contracts c
                JOIN contract_versions cv ON cv.contract_id = c.id
                WHERE c.workspace_id = ? AND c.id = ? AND cv.id = ?
                """
            ),
            (workspace_id, contract_id, contract_version_id),
        ).fetchone()
        if row is None:
            raise KeyError("Contract version not found in workspace")

    def _get_index_in_transaction(self, *, workspace_id: str, index_id: str) -> KnowledgeIndex | None:
        row_lock = " FOR UPDATE" if self.is_postgres else ""
        row = self.connection.execute(
            self._sql(f"SELECT * FROM knowledge_indexes WHERE workspace_id = ? AND id = ?{row_lock}"),
            (workspace_id, index_id),
        ).fetchone()
        return self._index_from_row(row) if row else None

    @classmethod
    def _prepare_chunk(
        cls, chunk: KnowledgeChunkInput
    ) -> tuple[KnowledgeChunkInput, str, tuple[float, ...]]:
        if chunk.ordinal < 0:
            raise ValueError("Chunk ordinal cannot be negative")
        content = chunk.content.strip()
        if not content:
            raise ValueError("Chunk content is required")
        if chunk.page_start is not None and chunk.page_start < 1:
            raise ValueError("page_start must be positive")
        if chunk.page_end is not None and chunk.page_end < 1:
            raise ValueError("page_end must be positive")
        if chunk.page_start is not None and chunk.page_end is not None and chunk.page_end < chunk.page_start:
            raise ValueError("page_end cannot precede page_start")
        if chunk.token_count is not None and chunk.token_count < 0:
            raise ValueError("token_count cannot be negative")
        return chunk, sha256(content.encode("utf-8")).hexdigest(), cls._validate_embedding(chunk.embedding)

    @staticmethod
    def _validate_embedding(embedding: Sequence[float]) -> tuple[float, ...]:
        values = tuple(float(value) for value in embedding)
        if len(values) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Embedding must contain exactly {EMBEDDING_DIMENSIONS} dimensions")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Embedding values must be finite")
        return values

    @staticmethod
    def _serialize_embedding(embedding: Sequence[float]) -> str:
        return "[" + ",".join(format(value, ".17g") for value in embedding) + "]"

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _index_from_row(row: Any) -> KnowledgeIndex:
        return KnowledgeIndex(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            contract_id=str(row["contract_id"]),
            contract_version_id=str(row["contract_version_id"]),
            embedding_provider=str(row["embedding_provider"]),
            embedding_model=str(row["embedding_model"]),
            embedding_dimensions=int(row["embedding_dimensions"]),
            reranker_provider=str(row["reranker_provider"]),
            reranker_model=str(row["reranker_model"]),
            chunking_version=str(row["chunking_version"]),
            status=str(row["status"]),
            chunk_count=int(row["chunk_count"]),
            error_message=str(row["error_message"]) if row["error_message"] is not None else None,
            indexed_at=row["indexed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @classmethod
    def _chunk_from_row(cls, row: Any) -> KnowledgeChunk:
        raw_metadata = row["metadata"]
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else dict(raw_metadata)
        raw_embedding = row["embedding"]
        parsed_embedding = json.loads(raw_embedding) if isinstance(raw_embedding, str) else list(raw_embedding)
        return KnowledgeChunk(
            id=str(row["id"]),
            knowledge_index_id=str(row["knowledge_index_id"]),
            workspace_id=str(row["workspace_id"]),
            contract_id=str(row["contract_id"]),
            contract_version_id=str(row["contract_version_id"]),
            ordinal=int(row["ordinal"]),
            content=str(row["content"]),
            content_sha256=str(row["content_sha256"]),
            page_start=int(row["page_start"]) if row["page_start"] is not None else None,
            page_end=int(row["page_end"]) if row["page_end"] is not None else None,
            token_count=int(row["token_count"]) if row["token_count"] is not None else None,
            metadata=metadata,
            embedding=tuple(float(value) for value in parsed_embedding),
            created_at=row["created_at"],
        )

    @classmethod
    def _search_hit_from_row(cls, row: Any) -> KnowledgeSearchHit:
        return KnowledgeSearchHit(
            chunk=cls._chunk_from_row(row),
            semantic_score=float(row["semantic_score"]),
            lexical_score=float(row["lexical_score"]),
            fused_score=float(row["fused_score"]),
        )

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        try:
            if immediate:
                self.connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
