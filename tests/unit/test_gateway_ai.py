from __future__ import annotations

from typing import Any, Mapping

import pytest

from contractmate.ai.openrouter import OpenRouterAPIError, OpenRouterEmbeddingsClient, OpenRouterRerankClient
from contractmate.services.chat_runtime import chat_retriever_from_settings
from contractmate.settings import Settings


class FakeTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        return self.response


def test_embeddings_adapter_sends_openrouter_payload_and_restores_index_order() -> None:
    transport = FakeTransport(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
    )
    client = OpenRouterEmbeddingsClient(
        api_key="openrouter-key",
        model_id="openai/text-embedding-3-small",
        dimensions=2,
        transport=transport,
    )

    result = client.embed_documents(["first", "second"])

    assert [item.values for item in result] == [(0.1, 0.2), (0.3, 0.4)]
    call = transport.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert call["headers"]["Authorization"] == "Bearer openrouter-key"
    assert call["payload"] == {
        "model": "openai/text-embedding-3-small",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 2,
    }


def test_embeddings_adapter_rejects_inconsistent_dimensions() -> None:
    transport = FakeTransport(
        {"data": [{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2, 0.3]}]}
    )
    client = OpenRouterEmbeddingsClient(api_key="openrouter-key", model_id="embed", dimensions=2, transport=transport)

    with pytest.raises(OpenRouterAPIError, match="inconsistent dimensions"):
        client.embed_documents(["first", "second"])


def test_embeddings_adapter_rejects_response_with_unexpected_dimensions() -> None:
    client = OpenRouterEmbeddingsClient(
        api_key="openrouter-key",
        model_id="embed",
        dimensions=2,
        transport=FakeTransport({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}),
    )

    with pytest.raises(OpenRouterAPIError, match="expected 2, got 3"):
        client.embed_documents(["first"])


@pytest.mark.parametrize("dimensions", [0, -1, True, 1.5])
def test_embeddings_adapter_rejects_invalid_requested_dimensions(dimensions: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        OpenRouterEmbeddingsClient(api_key="openrouter-key", model_id="embed", dimensions=dimensions)


def test_chat_runtime_requests_the_configured_embedding_dimensions() -> None:
    settings = Settings(openrouter_api_key="openrouter-key", embedding_dimensions=1_024)

    retriever = chat_retriever_from_settings(settings=settings, repository=object())  # type: ignore[arg-type]

    assert retriever.embeddings.dimensions == settings.embedding_dimensions


def test_optional_openrouter_attribution_headers_are_only_sent_when_configured() -> None:
    transport = FakeTransport({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    client = OpenRouterEmbeddingsClient(
        api_key="openrouter-key",
        model_id="embed",
        dimensions=2,
        http_referer="https://samvid.example",
        app_title="Samvid",
        transport=transport,
    )

    client.embed_documents(["document"])

    assert transport.calls[0]["headers"] == {
        "Authorization": "Bearer openrouter-key",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://samvid.example",
        "X-Title": "Samvid",
    }


def test_rerank_adapter_validates_and_sorts_results() -> None:
    transport = FakeTransport(
        {"data": [{"index": 0, "relevance_score": 0.4}, {"index": 1, "relevance_score": 0.9}]}
    )
    client = OpenRouterRerankClient(api_key="openrouter-key", model_id="cohere/rerank-v3.5", transport=transport)

    result = client.rerank(query="termination", documents=["alpha", "beta"], top_n=2)

    assert [(item.index, item.relevance_score) for item in result] == [(1, 0.9), (0, 0.4)]
    assert transport.calls[0]["url"] == "https://openrouter.ai/api/v1/rerank"
    assert transport.calls[0]["payload"] == {
        "model": "cohere/rerank-v3.5",
        "query": "termination",
        "documents": ["alpha", "beta"],
        "top_n": 2,
    }


def test_rerank_adapter_rejects_out_of_range_indices() -> None:
    client = OpenRouterRerankClient(
        api_key="openrouter-key",
        model_id="cohere/rerank-v3.5",
        transport=FakeTransport({"results": [{"index": 4, "relevance_score": 0.9}]}),
    )

    with pytest.raises(OpenRouterAPIError, match="invalid result"):
        client.rerank(query="query", documents=["only document"])
