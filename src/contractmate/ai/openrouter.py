from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from numbers import Real
from typing import Any, Iterator, Mapping, Sequence

from openai import OpenAI


class OpenRouterAPIError(RuntimeError):
    """A sanitized OpenRouter API or transport failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EmbeddingVector:
    index: int
    values: tuple[float, ...]


@dataclass(frozen=True)
class RerankResult:
    index: int
    relevance_score: float


@dataclass(frozen=True)
class OpenRouterEmbeddingsClient:
    api_key: str
    model_id: str
    dimensions: int = 1_024
    base_url: str = "https://openrouter.ai/api/v1"
    http_referer: str | None = None
    app_title: str | None = None
    timeout_seconds: float = 30.0
    http_client: Any | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.model_id.strip():
            raise ValueError("OpenRouter API key and embedding model ID are required.")
        if isinstance(self.dimensions, bool) or not isinstance(self.dimensions, int) or self.dimensions < 1:
            raise ValueError("Embedding dimensions must be a positive integer.")

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        cleaned = tuple(text.strip() for text in texts)
        if not cleaned or any(not text for text in cleaned):
            raise ValueError("At least one non-empty text is required for embeddings.")
        request_payload = {"model": self.model_id, "input": list(cleaned), "encoding_format": "float", "dimensions": self.dimensions}
        payload = self._request_embeddings(request_payload)
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(cleaned):
            raise OpenRouterAPIError("OpenRouter embeddings response did not match the requested inputs.")
        vectors: list[EmbeddingVector] = []
        for fallback_index, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise OpenRouterAPIError("OpenRouter embeddings response contained an invalid item.")
            index, values = item.get("index", fallback_index), item.get("embedding")
            if not isinstance(index, int) or not isinstance(values, list) or not values or any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
                raise OpenRouterAPIError("OpenRouter embeddings response contained an invalid vector.")
            vectors.append(EmbeddingVector(index=index, values=tuple(float(value) for value in values)))
        vectors.sort(key=lambda vector: vector.index)
        if [vector.index for vector in vectors] != list(range(len(cleaned))):
            raise OpenRouterAPIError("OpenRouter embeddings response contained invalid indices.")
        dimensions = {len(vector.values) for vector in vectors}
        if len(dimensions) != 1:
            raise OpenRouterAPIError("OpenRouter embeddings response contained inconsistent dimensions.")
        actual_dimensions = dimensions.pop()
        if actual_dimensions != self.dimensions:
            raise OpenRouterAPIError(f"OpenRouter embeddings response dimension mismatch: expected {self.dimensions}, got {actual_dimensions}.")
        return tuple(vectors)

    def _request_embeddings(self, request_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            with _openai_client(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
                http_referer=self.http_referer,
                app_title=self.app_title,
                http_client=self.http_client,
            ) as client:
                response = client.embeddings.create(**request_payload)
        except Exception as exc:
            raise OpenRouterAPIError("OpenRouter embeddings request failed.", status_code=getattr(exc, "status_code", None)) from exc
        return {
            "data": [
                {"index": item.index, "embedding": item.embedding}
                for item in response.data
            ]
        }


@dataclass(frozen=True)
class OpenRouterRerankClient:
    api_key: str
    model_id: str
    base_url: str = "https://openrouter.ai/api/v1"
    http_referer: str | None = None
    app_title: str | None = None
    timeout_seconds: float = 30.0
    http_client: Any | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.model_id.strip():
            raise ValueError("OpenRouter API key and reranking model ID are required.")

    def rerank(self, *, query: str, documents: Sequence[str], top_n: int | None = None) -> tuple[RerankResult, ...]:
        normalized_query, normalized_documents = query.strip(), tuple(document.strip() for document in documents)
        if not normalized_query:
            raise ValueError("A non-empty query is required for reranking.")
        if not normalized_documents or any(not document for document in normalized_documents):
            raise ValueError("At least one non-empty document is required for reranking.")
        if top_n is not None and not 1 <= top_n <= len(normalized_documents):
            raise ValueError("top_n must be between one and the number of documents.")
        request_payload: dict[str, Any] = {"model": self.model_id, "query": normalized_query, "documents": list(normalized_documents)}
        if top_n is not None:
            request_payload["top_n"] = top_n
        payload = self._request_rerank(request_payload)
        raw_results = payload.get("data", payload.get("results"))
        if not isinstance(raw_results, list):
            raise OpenRouterAPIError("OpenRouter rerank response did not contain results.")
        results: list[RerankResult] = []
        seen: set[int] = set()
        for item in raw_results:
            if not isinstance(item, Mapping):
                raise OpenRouterAPIError("OpenRouter rerank response contained an invalid result.")
            index, score = item.get("index"), item.get("relevance_score", item.get("score"))
            if not isinstance(index, int) or index < 0 or index >= len(normalized_documents) or index in seen or isinstance(score, bool) or not isinstance(score, Real):
                raise OpenRouterAPIError("OpenRouter rerank response contained an invalid result.")
            seen.add(index)
            results.append(RerankResult(index=index, relevance_score=float(score)))
        if top_n is not None and len(results) > top_n:
            raise OpenRouterAPIError("OpenRouter rerank response exceeded the requested top_n.")
        results.sort(key=lambda result: result.relevance_score, reverse=True)
        return tuple(results)

    def _request_rerank(self, request_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            with _openai_client(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
                http_referer=self.http_referer,
                app_title=self.app_title,
                http_client=self.http_client,
            ) as client:
                payload = client.post(
                    "/rerank",
                    cast_to=dict[str, Any],
                    body=dict(request_payload),
                )
        except Exception as exc:
            raise OpenRouterAPIError("OpenRouter rerank request failed.", status_code=getattr(exc, "status_code", None)) from exc
        if not isinstance(payload, Mapping):
            raise OpenRouterAPIError("OpenRouter returned an unexpected rerank response.")
        return payload


@contextmanager
def _openai_client(
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
    http_referer: str | None,
    app_title: str | None,
    http_client: Any | None,
) -> Iterator[Any]:
    headers: dict[str, str] = {}
    if http_referer and http_referer.strip():
        headers["HTTP-Referer"] = http_referer.strip()
    if app_title and app_title.strip():
        headers["X-Title"] = app_title.strip()
    created = OpenAI(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        max_retries=2,
        default_headers=headers or None,
        http_client=http_client,
    )
    try:
        yield created
    finally:
        if http_client is None:
            created.close()
