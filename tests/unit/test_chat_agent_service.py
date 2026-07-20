from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

import pytest

from contractmate.ai.chunking import DocumentChunk
from contractmate.ai.retrieval import RetrievedChunk
from contractmate.services.chat_agent import AgnoChatAgentService, CitationIntegrityError, OpenAIChatConfig


class FakeRetriever:
    def __init__(self, *, result_count: int = 1) -> None:
        self.workspace_ids: list[str] = []
        self.result_count = result_count

    def retrieve(self, query: Any) -> tuple[RetrievedChunk, ...]:
        self.workspace_ids.append(query.workspace_id)
        chunk = DocumentChunk(
            id="chunk-1",
            document_id="document-1",
            contract_id="contract-7",
            page_number=4,
            text="Either party may terminate with thirty days notice.",
            start_char=0,
            end_char=53,
            metadata={"title": "Services agreement"},
        )
        results = [RetrievedChunk(chunk=chunk, rrf_score=0.02, rerank_score=0.91, sources=("lexical", "vector"))]
        if self.result_count > 1:
            results.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        id="chunk-2",
                        document_id="document-2",
                        contract_id="contract-8",
                        page_number=9,
                        text="The agreement renews automatically for twelve months.",
                        start_char=0,
                        end_char=56,
                        metadata={"title": "Subscription agreement"},
                    ),
                    rrf_score=0.01,
                    rerank_score=0.82,
                    sources=("vector",),
                )
            )
        return tuple(results)


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def get_contract_summary(self, *, workspace_id: str, contract_id: str) -> Mapping[str, Any] | None:
        self.calls.append(("summary", workspace_id, contract_id))
        return {"contract_id": contract_id, "type": "Services agreement"}

    def get_contract_timeline(self, *, workspace_id: str, contract_id: str) -> Sequence[Mapping[str, Any]]:
        self.calls.append(("timeline", workspace_id, contract_id))
        return [{"event": "review_ready"}]


class FakeAgent:
    def __init__(self, tools: Sequence[Callable[..., Any]], *, content: str | None = None) -> None:
        self.tools = tools
        self.calls: list[dict[str, Any]] = []
        self.content = content or "The notice period is thirty days [S1]."
        self.search_results: list[dict[str, Any]] = []

    def run(self, input: str, **kwargs: Any) -> Any:
        self.calls.append({"input": input, **kwargs})
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(event="ToolCallStarted", content="Searching contracts"),
                    SimpleNamespace(event="RunContent", content="Thirty days"),
                    SimpleNamespace(event="RunCompleted", content=""),
                ]
            )
        self.search_results = self.tools[0]("notice period")
        return SimpleNamespace(content=self.content)


def test_openai_chat_config_reads_existing_environment_contract(monkeypatch: Any) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("CHAT_MODEL_ID", "gpt-5-mini")

    config = OpenAIChatConfig.from_env()

    assert config.api_key == "openai-key"
    assert config.model_id == "gpt-5-mini"


def test_chat_agent_exposes_only_scoped_read_tools_and_resolves_run_evidence() -> None:
    retriever = FakeRetriever()
    reader = FakeReader()
    agents: list[FakeAgent] = []

    def builder(tools: Sequence[Callable[..., Any]]) -> FakeAgent:
        agent = FakeAgent(tools)
        agents.append(agent)
        return agent

    service = AgnoChatAgentService(
        config=OpenAIChatConfig(api_key="openai-key", model_id="gpt-5-mini"),
        retriever=retriever,  # type: ignore[arg-type]
        reader=reader,
        agent_builder=builder,
    )

    response = service.answer(
        workspace_id="workspace-a",
        user_id="user-a",
        session_id="chat-a",
        message="What is the notice period?",
    )

    agent = agents[0]
    assert [tool.__name__ for tool in agent.tools] == [
        "search_contract_context",
        "get_contract_summary",
        "get_contract_timeline",
    ]
    search_result = agent.search_results
    assert search_result[0]["source_id"] == "S1"
    assert search_result[0]["document_title"] == "Services agreement"
    assert search_result[0]["retrieval_sources"] == ["lexical", "vector"]
    assert "chunk_id" not in search_result[0]
    assert "contract_id" not in search_result[0]
    assert retriever.workspace_ids == ["workspace-a"]
    assert agent.tools[1]("contract-7")["type"] == "Services agreement"
    assert reader.calls[-1] == ("summary", "workspace-a", "contract-7")
    assert response.citations == ("S1",)
    assert response.sources[0].chunk_id == "chunk-1"
    assert response.sources[0].contract_id == "contract-7"
    assert response.sources[0].contract_version_id == "document-1"
    assert response.sources[0].source_type == "knowledge_chunk"
    assert agent.calls[0]["metadata"] == {"workspace_id": "workspace-a"}


def test_chat_agent_rejects_unknown_run_citation() -> None:
    def builder(tools: Sequence[Callable[..., Any]]) -> FakeAgent:
        return FakeAgent(tools, content="The notice period is thirty days [S99].")

    service = AgnoChatAgentService(
        config=OpenAIChatConfig(api_key="openai-key", model_id="gpt-5-mini"),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        reader=FakeReader(),
        agent_builder=builder,
    )

    with pytest.raises(CitationIntegrityError, match="unknown evidence source"):
        service.answer(
            workspace_id="workspace-a",
            user_id="user-a",
            session_id="chat-a",
            message="What is the notice period?",
        )


def test_chat_agent_rejects_legacy_unregistered_citation() -> None:
    def builder(tools: Sequence[Callable[..., Any]]) -> FakeAgent:
        return FakeAgent(tools, content="The notice period is thirty days [contract-7 p.4].")

    service = AgnoChatAgentService(
        config=OpenAIChatConfig(api_key="openai-key", model_id="gpt-5-mini"),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        reader=FakeReader(),
        agent_builder=builder,
    )

    with pytest.raises(CitationIntegrityError, match="invalid evidence citation"):
        service.answer(
            workspace_id="workspace-a",
            user_id="user-a",
            session_id="chat-a",
            message="What is the notice period?",
        )


def test_chat_agent_returns_only_sources_cited_by_the_answer() -> None:
    def builder(tools: Sequence[Callable[..., Any]]) -> FakeAgent:
        return FakeAgent(tools, content="The agreement renews for twelve months [S2].")

    service = AgnoChatAgentService(
        config=OpenAIChatConfig(api_key="openai-key", model_id="gpt-5-mini"),
        retriever=FakeRetriever(result_count=2),  # type: ignore[arg-type]
        reader=FakeReader(),
        agent_builder=builder,
    )

    response = service.answer(
        workspace_id="workspace-a",
        user_id="user-a",
        session_id="chat-a",
        message="Does anything renew automatically?",
    )

    assert response.citations == ("S2",)
    assert [source.chunk_id for source in response.sources] == ["chunk-2"]


def test_chat_agent_normalizes_stream_events() -> None:
    agents: list[FakeAgent] = []

    def builder(tools: Sequence[Callable[..., Any]]) -> FakeAgent:
        agent = FakeAgent(tools)
        agents.append(agent)
        return agent

    service = AgnoChatAgentService(
        config=OpenAIChatConfig(api_key="openai-key", model_id="gpt-5-mini"),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        reader=FakeReader(),
        agent_builder=builder,
    )

    events = list(
        service.stream(
            workspace_id="workspace-a",
            user_id="user-a",
            session_id="chat-a",
            message="Summarize this contract",
        )
    )

    assert [(event.type, event.content) for event in events] == [
        ("tool", "Searching contracts"),
        ("delta", "Thirty days"),
        ("completed", ""),
    ]
