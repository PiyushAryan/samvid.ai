from __future__ import annotations

import json
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openrouter import OpenRouter


class OpenRouterAPIError(RuntimeError):
    """A sanitized OpenRouter API or transport failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JSONTransport(Protocol):
    def post_json(
        self, *, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout_seconds: float
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class UrllibJSONTransport:
    """Minimal transport for OpenRouter's documented REST endpoints."""

    def post_json(self, *, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any]:
        request = Request(url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured trusted API base URL.
                body = response.read()
        except HTTPError as exc:
            raise OpenRouterAPIError(_error_message(exc.read().decode("utf-8", errors="replace"), fallback=f"OpenRouter request failed with HTTP {exc.code}."), status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            raise OpenRouterAPIError("OpenRouter request failed.") from exc
        try:
            decoded = json.loads(body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise OpenRouterAPIError("OpenRouter returned an invalid JSON response.") from exc
        if not isinstance(decoded, dict):
            raise OpenRouterAPIError("OpenRouter returned an unexpected response shape.")
        return decoded


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
    # Tests inject a transport; production uses OpenRouter's official SDK.
    transport: JSONTransport | None = None

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
        if self.transport is not None:
            return self.transport.post_json(
                url=f"{self.base_url.rstrip('/')}/embeddings",
                headers=_headers(self.api_key, self.http_referer, self.app_title),
                payload=request_payload,
                timeout_seconds=self.timeout_seconds,
            )
        try:
            response = OpenRouter(
                api_key=self.api_key,
                http_referer=self.http_referer,
                x_open_router_title=self.app_title,
                server_url=self.base_url.rstrip("/"),
                timeout_ms=int(self.timeout_seconds * 1_000),
            ).embeddings.generate(**request_payload)
            payload = response.to_dict()
        except Exception as exc:
            raise OpenRouterAPIError("OpenRouter embeddings request failed.", status_code=getattr(exc, "status_code", None)) from exc
        if not isinstance(payload, Mapping):
            raise OpenRouterAPIError("OpenRouter returned an unexpected embeddings response.")
        return payload


@dataclass(frozen=True)
class OpenRouterRerankClient:
    api_key: str
    model_id: str
    base_url: str = "https://openrouter.ai/api/v1"
    http_referer: str | None = None
    app_title: str | None = None
    timeout_seconds: float = 30.0
    transport: JSONTransport | None = None

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
        if self.transport is not None:
            return self.transport.post_json(
                url=f"{self.base_url.rstrip('/')}/rerank",
                headers=_headers(self.api_key, self.http_referer, self.app_title),
                payload=request_payload,
                timeout_seconds=self.timeout_seconds,
            )
        try:
            response = OpenRouter(
                api_key=self.api_key,
                http_referer=self.http_referer,
                x_open_router_title=self.app_title,
                server_url=self.base_url.rstrip("/"),
                timeout_ms=int(self.timeout_seconds * 1_000),
            ).rerank.rerank(**request_payload)
            payload = response.to_dict()
        except Exception as exc:
            raise OpenRouterAPIError("OpenRouter rerank request failed.", status_code=getattr(exc, "status_code", None)) from exc
        if not isinstance(payload, Mapping):
            raise OpenRouterAPIError("OpenRouter returned an unexpected rerank response.")
        return payload


def _headers(api_key: str, http_referer: str | None, app_title: str | None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if http_referer and http_referer.strip():
        headers["HTTP-Referer"] = http_referer.strip()
    if app_title and app_title.strip():
        headers["X-Title"] = app_title.strip()
    return headers


def _error_message(detail: str, *, fallback: str) -> str:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(payload, Mapping):
        return fallback
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    return payload["message"] if isinstance(payload.get("message"), str) else fallback
