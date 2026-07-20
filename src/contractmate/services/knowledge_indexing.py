from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from contractmate.ai.chunking import DocumentChunk, PageAwareChunker, PageContent
from contractmate.ai.fireworks import EmbeddingVector
from contractmate.schemas.contracts import ContractReview
from contractmate.schemas.documents import ParsedDocument


@dataclass(frozen=True)
class KnowledgeIndexSpec:
    workspace_id: str
    contract_id: str
    contract_version_id: str
    document_id: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    reranker_provider: str
    reranker_model: str
    chunking_version: str


@dataclass(frozen=True)
class KnowledgeChunkPayload:
    id: str
    ordinal: int
    content: str
    content_sha256: str
    page_start: int | None
    page_end: int | None
    token_count: int
    metadata: Mapping[str, Any]
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class KnowledgeIndexingResult:
    workspace_id: str
    contract_id: str
    contract_version_id: str
    chunk_count: int
    embedding_dimensions: int


class KnowledgeEmbeddingProvider(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]: ...


class KnowledgeIndexBackend(Protocol):
    def replace_index(
        self,
        *,
        spec: KnowledgeIndexSpec,
        chunks: Sequence[KnowledgeChunkPayload],
    ) -> None: ...


@dataclass
class KnowledgeIndexingService:
    embeddings: KnowledgeEmbeddingProvider
    backend: KnowledgeIndexBackend
    embedding_model: str
    reranker_model: str
    chunker: PageAwareChunker = field(default_factory=PageAwareChunker)
    embedding_dimensions: int = 1_024
    embedding_provider: str = "fireworks"
    reranker_provider: str = "fireworks"
    chunking_version: str = "page-aware-char-v1"
    embedding_batch_size: int = 32

    def __post_init__(self) -> None:
        if not self.embedding_model.strip() or not self.reranker_model.strip():
            raise ValueError("Embedding and reranker model IDs are required.")
        if self.embedding_dimensions < 1 or self.embedding_batch_size < 1:
            raise ValueError("Embedding dimensions and batch size must be positive.")

    def index_contract(
        self,
        *,
        workspace_id: str,
        contract_id: str,
        contract_version_id: str,
        parsed_document: ParsedDocument,
        review_json: ContractReview | Mapping[str, Any],
    ) -> KnowledgeIndexingResult:
        if not workspace_id.strip() or not contract_id.strip() or not contract_version_id.strip():
            raise ValueError("workspace_id, contract_id, and contract_version_id are required.")
        review = review_json if isinstance(review_json, ContractReview) else ContractReview.model_validate(review_json)
        if review.contract_id != contract_id:
            raise ValueError("Review contract_id does not match the indexed contract.")

        document_chunks = self.chunker.chunk_pages(
            document_id=parsed_document.document_id,
            contract_id=contract_id,
            pages=[
                PageContent(
                    page_number=page.page_number,
                    text=page.text,
                    metadata={"warnings": list(page.warnings)},
                )
                for page in parsed_document.pages
            ],
            metadata={
                "source": "parsed_document",
                "document_sha256": parsed_document.sha256,
                "mime_type": parsed_document.mime_type,
                "parser_name": parsed_document.parser_name,
                "parser_version": parsed_document.parser_version,
            },
        )
        review_chunks = _review_chunks(
            document_id=parsed_document.document_id,
            contract_id=contract_id,
            review=review,
        )
        chunks = tuple(document_chunks) + review_chunks
        if not chunks:
            raise ValueError("Parsed document and review produced no indexable content.")

        vectors = self._embed([chunk.text for chunk in chunks])
        payloads = tuple(
            _payload(chunk=chunk, ordinal=ordinal, embedding=vectors[ordinal].values)
            for ordinal, chunk in enumerate(chunks)
        )
        spec = KnowledgeIndexSpec(
            workspace_id=workspace_id,
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            document_id=parsed_document.document_id,
            embedding_provider=self.embedding_provider,
            embedding_model=self.embedding_model,
            embedding_dimensions=self.embedding_dimensions,
            reranker_provider=self.reranker_provider,
            reranker_model=self.reranker_model,
            chunking_version=self.chunking_version,
        )
        self.backend.replace_index(spec=spec, chunks=payloads)
        return KnowledgeIndexingResult(
            workspace_id=workspace_id,
            contract_id=contract_id,
            contract_version_id=contract_version_id,
            chunk_count=len(payloads),
            embedding_dimensions=self.embedding_dimensions,
        )

    def _embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        vectors: list[EmbeddingVector] = []
        for start in range(0, len(texts), self.embedding_batch_size):
            batch = texts[start : start + self.embedding_batch_size]
            batch_vectors = self.embeddings.embed_documents(batch)
            if len(batch_vectors) != len(batch):
                raise ValueError("Embedding provider returned the wrong number of vectors.")
            for vector in batch_vectors:
                if len(vector.values) != self.embedding_dimensions:
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {self.embedding_dimensions}, got {len(vector.values)}."
                    )
                vectors.append(EmbeddingVector(index=start + vector.index, values=vector.values))
        vectors.sort(key=lambda vector: vector.index)
        if [vector.index for vector in vectors] != list(range(len(texts))):
            raise ValueError("Embedding provider returned invalid batch indices.")
        return tuple(vectors)


def _review_chunks(
    *,
    document_id: str,
    contract_id: str,
    review: ContractReview,
) -> tuple[DocumentChunk, ...]:
    entries: list[tuple[str, int | None, str, Mapping[str, Any]]] = []
    overview_parts = [
        f"Contract type: {review.contract_type}",
        f"Recommended next action: {review.recommended_next_action}",
    ]
    if review.limitations:
        overview_parts.append("Limitations: " + "; ".join(review.limitations))
    entries.append(("review_overview", None, "\n".join(overview_parts), {"contract_type": review.contract_type}))

    for party in review.parties:
        evidence = party.evidence
        text = f"Party: {party.name}\nRole: {party.role or 'Not specified'}"
        if evidence:
            text += f"\nEvidence: {evidence.exact_text}"
        entries.append(("party", evidence.page_number if evidence else None, text, {"party_name": party.name}))

    for term in review.key_terms:
        evidence = term.evidence
        text = f"Key term: {term.name}\nValue: {term.value or 'Not specified'}\nConfidence: {term.confidence:.3f}"
        if evidence:
            text += f"\nEvidence: {evidence.exact_text}"
        entries.append(("key_term", evidence.page_number if evidence else None, text, {"term_name": term.name}))

    for risk in review.risks:
        text = (
            f"Risk: {risk.title}\nSeverity: {risk.severity.value}\nClause type: {risk.clause_type}\n"
            f"Explanation: {risk.explanation}\nRecommendation: {risk.recommendation}\n"
            f"Evidence: {risk.evidence.exact_text}\nConfidence: {risk.confidence:.3f}"
        )
        entries.append(
            (
                "risk",
                risk.evidence.page_number,
                text,
                {"risk_title": risk.title, "severity": risk.severity.value, "clause_type": risk.clause_type},
            )
        )

    chunks: list[DocumentChunk] = []
    for position, (kind, page_number, text, metadata) in enumerate(entries):
        identity = json.dumps(
            [document_id, contract_id, kind, position, page_number, text],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        chunks.append(
            DocumentChunk(
                id=hashlib.sha256(identity).hexdigest()[:24],
                document_id=document_id,
                contract_id=contract_id,
                page_number=page_number,
                text=text,
                start_char=0,
                end_char=len(text),
                metadata={"source": "contract_review", "review_kind": kind, **dict(metadata)},
            )
        )
    return tuple(chunks)


def _payload(*, chunk: DocumentChunk, ordinal: int, embedding: tuple[float, ...]) -> KnowledgeChunkPayload:
    content_sha256 = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    return KnowledgeChunkPayload(
        id=chunk.id,
        ordinal=ordinal,
        content=chunk.text,
        content_sha256=content_sha256,
        page_start=chunk.page_number,
        page_end=chunk.page_number,
        token_count=max(1, (len(chunk.text) + 3) // 4),
        metadata={**dict(chunk.metadata), "citation": chunk.citation, "document_id": chunk.document_id},
        embedding=embedding,
    )
