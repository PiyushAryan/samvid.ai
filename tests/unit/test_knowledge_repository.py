from __future__ import annotations

import sqlite3

import pytest

from contractmate.db.models import POSTGRES_EXTENSIONS_SQL, POSTGRES_SCHEMA_SQL, SQLITE_SCHEMA_SQL
from contractmate.db.repositories.knowledge import (
    EMBEDDING_DIMENSIONS,
    KnowledgeChunkInput,
    KnowledgeRepository,
)
from contractmate.db.session import initialize_database


def _embedding(first: float, second: float = 0.0) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[0] = first
    values[1] = second
    return values


@pytest.fixture
def repository() -> KnowledgeRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    _seed_contract(connection, workspace_id="workspace-a", contract_id="contract-a", version_id="version-a")
    _seed_contract(connection, workspace_id="workspace-b", contract_id="contract-b", version_id="version-b")
    connection.commit()
    yield KnowledgeRepository(connection)
    connection.close()


def test_postgres_schema_enables_pgvector_hybrid_indexes() -> None:
    assert "CREATE EXTENSION IF NOT EXISTS vector" in POSTGRES_EXTENSIONS_SQL
    assert "embedding vector(1024) NOT NULL" in POSTGRES_SCHEMA_SQL
    assert "USING hnsw (embedding vector_cosine_ops)" in POSTGRES_SCHEMA_SQL
    assert "USING GIN(search_vector)" in POSTGRES_SCHEMA_SQL
    assert "embedding TEXT NOT NULL" in SQLITE_SCHEMA_SQL


def test_postgres_initialization_installs_vector_before_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []

    class FakeConnection:
        def execute(self, statement: str) -> None:
            executed.append(statement)

        def commit(self) -> None:
            executed.append("COMMIT")

        def close(self) -> None:
            executed.append("CLOSE")

    monkeypatch.setattr("contractmate.db.session.connect_postgres", lambda _url: FakeConnection())

    initialize_database("postgresql://rag-test:rag-test@localhost/rag-vector-init")

    assert executed[0] == POSTGRES_EXTENSIONS_SQL
    assert executed[1] == POSTGRES_SCHEMA_SQL
    assert executed[-2:] == ["COMMIT", "CLOSE"]


def test_index_creation_is_idempotent_and_workspace_scoped(repository: KnowledgeRepository) -> None:
    first = _create_index(repository, workspace_id="workspace-a", contract_id="contract-a", version_id="version-a")
    second = _create_index(repository, workspace_id="workspace-a", contract_id="contract-a", version_id="version-a")

    assert second.id == first.id
    assert first.embedding_dimensions == 1024
    assert repository.get_index(workspace_id="workspace-b", index_id=first.id) is None
    with pytest.raises(KeyError):
        _create_index(repository, workspace_id="workspace-a", contract_id="contract-b", version_id="version-b")


def test_chunk_replacement_and_hybrid_search_preserve_workspace_isolation(
    repository: KnowledgeRepository,
) -> None:
    index_a = _create_index(
        repository,
        workspace_id="workspace-a",
        contract_id="contract-a",
        version_id="version-a",
    )
    repository.replace_chunks(
        workspace_id="workspace-a",
        index_id=index_a.id,
        chunks=[
            KnowledgeChunkInput(
                ordinal=0,
                content="Unlimited indemnity creates material liability exposure.",
                embedding=_embedding(1.0),
                page_start=3,
                page_end=3,
                token_count=7,
                metadata={"heading": "Indemnity"},
            ),
            KnowledgeChunkInput(
                ordinal=1,
                content="The agreement renews automatically every twelve months.",
                embedding=_embedding(0.0, 1.0),
                page_start=5,
                page_end=5,
            ),
        ],
    )
    assert repository.mark_ready(workspace_id="workspace-a", index_id=index_a.id)

    index_b = _create_index(
        repository,
        workspace_id="workspace-b",
        contract_id="contract-b",
        version_id="version-b",
    )
    repository.replace_chunks(
        workspace_id="workspace-b",
        index_id=index_b.id,
        chunks=[
            KnowledgeChunkInput(
                ordinal=0,
                content="Private workspace B indemnity text.",
                embedding=_embedding(1.0),
            )
        ],
    )
    repository.mark_ready(workspace_id="workspace-b", index_id=index_b.id)

    hits = repository.hybrid_search(
        workspace_id="workspace-a",
        query_text="indemnity liability",
        query_embedding=_embedding(1.0),
    )

    assert hits[0].chunk.content.startswith("Unlimited indemnity")
    assert all(hit.chunk.workspace_id == "workspace-a" for hit in hits)
    assert hits[0].chunk.metadata == {"heading": "Indemnity"}


def test_hybrid_search_excludes_ready_chunks_from_historical_contract_versions(
    repository: KnowledgeRepository,
) -> None:
    stale_index = _create_index(
        repository,
        workspace_id="workspace-a",
        contract_id="contract-a",
        version_id="version-a",
    )
    repository.replace_chunks(
        workspace_id="workspace-a",
        index_id=stale_index.id,
        chunks=[
            KnowledgeChunkInput(
                ordinal=0,
                content="Historical version contains an unlimited indemnity clause.",
                embedding=_embedding(1.0),
            )
        ],
    )
    repository.mark_ready(workspace_id="workspace-a", index_id=stale_index.id)

    connection = repository.connection
    connection.execute(
        """
        INSERT INTO contract_versions(
            id, contract_id, version_number, original_filename, mime_type,
            size_bytes, sha256, s3_object_key, uploaded_by
        ) VALUES ('version-a-current', 'contract-a', 2, 'current.pdf',
                  'application/pdf', 100, 'sha-current', 'object-current', 'test@example.com')
        """
    )
    connection.execute(
        "UPDATE contracts SET current_version_id = 'version-a-current' WHERE id = 'contract-a'"
    )
    connection.commit()
    current_index = _create_index(
        repository,
        workspace_id="workspace-a",
        contract_id="contract-a",
        version_id="version-a-current",
    )
    repository.replace_chunks(
        workspace_id="workspace-a",
        index_id=current_index.id,
        chunks=[
            KnowledgeChunkInput(
                ordinal=0,
                content="Current version caps indemnity at the annual fees paid.",
                embedding=_embedding(1.0),
            )
        ],
    )
    repository.mark_ready(workspace_id="workspace-a", index_id=current_index.id)

    hits = repository.hybrid_search(
        workspace_id="workspace-a",
        query_text="indemnity",
        query_embedding=_embedding(1.0),
    )

    assert [hit.chunk.contract_version_id for hit in hits] == ["version-a-current"]
    assert all("Historical" not in hit.chunk.content for hit in hits)


def test_invalid_replacement_does_not_delete_existing_chunks(repository: KnowledgeRepository) -> None:
    index = _create_index(
        repository,
        workspace_id="workspace-a",
        contract_id="contract-a",
        version_id="version-a",
    )
    repository.replace_chunks(
        workspace_id="workspace-a",
        index_id=index.id,
        chunks=[KnowledgeChunkInput(ordinal=0, content="Original", embedding=_embedding(1.0))],
    )

    with pytest.raises(ValueError, match="1024"):
        repository.replace_chunks(
            workspace_id="workspace-a",
            index_id=index.id,
            chunks=[KnowledgeChunkInput(ordinal=0, content="Invalid", embedding=[1.0, 0.0])],
        )

    chunks = repository.list_chunks(workspace_id="workspace-a", index_id=index.id)
    assert [chunk.content for chunk in chunks] == ["Original"]
    assert repository.list_chunks(workspace_id="workspace-b", index_id=index.id) == []


def _create_index(
    repository: KnowledgeRepository,
    *,
    workspace_id: str,
    contract_id: str,
    version_id: str,
):
    return repository.create_or_get_index(
        workspace_id=workspace_id,
        contract_id=contract_id,
        contract_version_id=version_id,
        embedding_provider="fireworks",
        embedding_model="qwen3-embedding-8b",
        reranker_provider="fireworks",
        reranker_model="qwen3-reranker-8b",
        chunking_version="contract-pages-v1",
    )


def _seed_contract(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    contract_id: str,
    version_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO contracts(id, workspace_id, email_thread_id, title, status, current_version_id, created_by)
        VALUES (?, ?, ?, ?, 'reviewed', ?, 'test@example.com')
        """,
        (contract_id, workspace_id, f"thread-{contract_id}", contract_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO contract_versions(
            id, contract_id, version_number, original_filename, mime_type,
            size_bytes, sha256, s3_object_key, uploaded_by
        ) VALUES (?, ?, 1, 'contract.pdf', 'application/pdf', 100, ?, ?, 'test@example.com')
        """,
        (version_id, contract_id, f"sha-{contract_id}", f"object-{contract_id}"),
    )
