from __future__ import annotations

from typing import Any, Mapping

import pytest

from contractmate.ai.fireworks import (
    FireworksAPIError,
    FireworksEmbeddingsClient,
    FireworksRerankClient,
)
from contractmate.services.chat_runtime import chat_retriever_from_settings
from contractmate.settings import Settings


class FakeTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        return self.response


def test_embeddings_adapter_sends_openai_compatible_payload_and_restores_index_order() -> None:
    transport = FakeTransport(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
    )
    client = FireworksEmbeddingsClient(
        api_key="fw-key",
        model_id="accounts/fireworks/models/embed-model",
        dimensions=2,
        transport=transport,
    )

    result = client.embed_documents(["first", "second"])

    assert [item.values for item in result] == [(0.1, 0.2), (0.3, 0.4)]
    call = transport.calls[0]
    assert call["url"] == "https://api.fireworks.ai/inference/v1/embeddings"
    assert call["headers"]["Authorization"] == "Bearer fw-key"
    assert call["payload"] == {
        "model": "accounts/fireworks/models/embed-model",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 2,
    }


def test_embeddings_adapter_rejects_inconsistent_dimensions() -> None:
    transport = FakeTransport(
        {"data": [{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2, 0.3]}]}
    )
    client = FireworksEmbeddingsClient(api_key="fw-key", model_id="embed", dimensions=2, transport=transport)

    with pytest.raises(FireworksAPIError, match="inconsistent dimensions"):
        client.embed_documents(["first", "second"])


def test_embeddings_adapter_rejects_response_with_unexpected_dimensions() -> None:
    client = FireworksEmbeddingsClient(
        api_key="fw-key",
        model_id="embed",
        dimensions=2,
        transport=FakeTransport({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}),
    )

    with pytest.raises(FireworksAPIError, match="expected 2, got 3"):
        client.embed_documents(["first"])


@pytest.mark.parametrize("dimensions", [0, -1, True, 1.5])
def test_embeddings_adapter_rejects_invalid_requested_dimensions(dimensions: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        FireworksEmbeddingsClient(api_key="fw-key", model_id="embed", dimensions=dimensions)


def test_chat_runtime_requests_the_configured_embedding_dimensions() -> None:
    settings = Settings(fireworks_api_key="fw-key", embedding_dimensions=1_024)

    retriever = chat_retriever_from_settings(settings=settings, repository=object())  # type: ignore[arg-type]

    assert retriever.embeddings.dimensions == settings.embedding_dimensions


def test_rerank_adapter_validates_and_sorts_results() -> None:
    transport = FakeTransport(
        {"data": [{"index": 0, "relevance_score": 0.4}, {"index": 1, "relevance_score": 0.9}]}
    )
    client = FireworksRerankClient(api_key="fw-key", model_id="reranker", transport=transport)

    result = client.rerank(query="termination", documents=["alpha", "beta"], top_n=2)

    assert [(item.index, item.relevance_score) for item in result] == [(1, 0.9), (0, 0.4)]
    assert transport.calls[0]["payload"] == {
        "model": "reranker",
        "query": "termination",
        "documents": ["alpha", "beta"],
        "top_n": 2,
    }


def test_rerank_adapter_rejects_out_of_range_indices() -> None:
    client = FireworksRerankClient(
        api_key="fw-key",
        model_id="reranker",
        transport=FakeTransport({"results": [{"index": 4, "relevance_score": 0.9}]}),
    )

    with pytest.raises(FireworksAPIError, match="invalid result"):
        client.rerank(query="query", documents=["only document"])
