from __future__ import annotations

import json
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FireworksAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JSONTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class UrllibJSONTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is fixed by configuration.
                body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FireworksAPIError(_error_message(detail, fallback=str(exc)), status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            raise FireworksAPIError(f"Fireworks request failed: {exc}") from exc

        try:
            decoded = json.loads(body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FireworksAPIError("Fireworks returned an invalid JSON response.") from exc
        if not isinstance(decoded, dict):
            raise FireworksAPIError("Fireworks returned an unexpected response shape.")
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
class FireworksEmbeddingsClient:
    api_key: str
    model_id: str
    dimensions: int = 1_024
    base_url: str = "https://api.fireworks.ai/inference/v1"
    timeout_seconds: float = 30.0
    transport: JSONTransport = UrllibJSONTransport()

    def __post_init__(self) -> None:
        if isinstance(self.dimensions, bool) or not isinstance(self.dimensions, int) or self.dimensions < 1:
            raise ValueError("Embedding dimensions must be a positive integer.")

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        cleaned = tuple(text.strip() for text in texts)
        if not cleaned or any(not text for text in cleaned):
            raise ValueError("At least one non-empty text is required for embeddings.")
        payload = self.transport.post_json(
            url=f"{self.base_url.rstrip('/')}/embeddings",
            headers=_headers(self.api_key),
            payload={
                "model": self.model_id,
                "input": list(cleaned),
                "encoding_format": "float",
                "dimensions": self.dimensions,
            },
            timeout_seconds=self.timeout_seconds,
        )
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(cleaned):
            raise FireworksAPIError("Fireworks embeddings response did not match the requested inputs.")

        vectors: list[EmbeddingVector] = []
        for fallback_index, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise FireworksAPIError("Fireworks embeddings response contained an invalid item.")
            index = item.get("index", fallback_index)
            values = item.get("embedding")
            if not isinstance(index, int) or not isinstance(values, list) or not values:
                raise FireworksAPIError("Fireworks embeddings response contained an invalid vector.")
            if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
                raise FireworksAPIError("Fireworks embeddings response contained a non-numeric vector.")
            vectors.append(EmbeddingVector(index=index, values=tuple(float(value) for value in values)))
        vectors.sort(key=lambda vector: vector.index)
        if [vector.index for vector in vectors] != list(range(len(cleaned))):
            raise FireworksAPIError("Fireworks embeddings response contained invalid indices.")
        dimensions = {len(vector.values) for vector in vectors}
        if len(dimensions) != 1:
            raise FireworksAPIError("Fireworks embeddings response contained inconsistent dimensions.")
        actual_dimensions = dimensions.pop()
        if actual_dimensions != self.dimensions:
            raise FireworksAPIError(
                "Fireworks embeddings response dimension mismatch: "
                f"expected {self.dimensions}, got {actual_dimensions}."
            )
        return tuple(vectors)


@dataclass(frozen=True)
class FireworksRerankClient:
    api_key: str
    model_id: str
    base_url: str = "https://api.fireworks.ai/inference/v1"
    timeout_seconds: float = 30.0
    transport: JSONTransport = UrllibJSONTransport()

    def rerank(self, *, query: str, documents: Sequence[str], top_n: int | None = None) -> tuple[RerankResult, ...]:
        normalized_query = query.strip()
        normalized_documents = tuple(document.strip() for document in documents)
        if not normalized_query:
            raise ValueError("A non-empty query is required for reranking.")
        if not normalized_documents or any(not document for document in normalized_documents):
            raise ValueError("At least one non-empty document is required for reranking.")
        if top_n is not None and not 1 <= top_n <= len(normalized_documents):
            raise ValueError("top_n must be between one and the number of documents.")

        request_payload: dict[str, Any] = {
            "model": self.model_id,
            "query": normalized_query,
            "documents": list(normalized_documents),
        }
        if top_n is not None:
            request_payload["top_n"] = top_n
        payload = self.transport.post_json(
            url=f"{self.base_url.rstrip('/')}/rerank",
            headers=_headers(self.api_key),
            payload=request_payload,
            timeout_seconds=self.timeout_seconds,
        )
        raw_results = payload.get("data", payload.get("results"))
        if not isinstance(raw_results, list):
            raise FireworksAPIError("Fireworks rerank response did not contain results.")
        results: list[RerankResult] = []
        seen: set[int] = set()
        for item in raw_results:
            if not isinstance(item, Mapping):
                raise FireworksAPIError("Fireworks rerank response contained an invalid result.")
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(normalized_documents)
                or index in seen
                or isinstance(score, bool)
                or not isinstance(score, Real)
            ):
                raise FireworksAPIError("Fireworks rerank response contained an invalid result.")
            seen.add(index)
            results.append(RerankResult(index=index, relevance_score=float(score)))
        results.sort(key=lambda item: item.relevance_score, reverse=True)
        return tuple(results)


def _headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("A Fireworks API key is required.")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _error_message(body: str, *, fallback: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return fallback
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(error, str):
            return error
    return fallback
