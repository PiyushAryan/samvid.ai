from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from contractmate.db.models import POSTGRES_SCHEMA_SQL, SQLITE_SCHEMA_SQL


def sqlite_path_from_url(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    if database_url.startswith("postgresql"):
        return Path(".contractmate/local.db")
    return Path(database_url)


def connect(database_url: str) -> Any:
    if is_postgres_url(database_url):
        return connect_postgres(database_url)
    return connect_sqlite(database_url)


def connect_sqlite(database_url: str) -> sqlite3.Connection:
    path = sqlite_path_from_url(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SQLITE_SCHEMA_SQL)
    _migrate_legacy_slack_contracts_table(connection)
    connection.commit()
    return connection


def connect_postgres(database_url: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install psycopg to use PostgreSQL: uv sync") from exc

    connection = psycopg.connect(normalize_postgres_url(database_url), row_factory=dict_row)
    connection.execute(POSTGRES_SCHEMA_SQL)
    connection.commit()
    return connection


def is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))


def normalize_postgres_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _migrate_legacy_slack_contracts_table(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(contracts)").fetchall()}
    if "slack_thread_id" not in columns or "email_thread_id" in columns:
        return
    connection.executescript(
        """
        CREATE TABLE contracts_email_migration (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            email_thread_id TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL,
            current_version_id TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO contracts_email_migration(
            id, workspace_id, email_thread_id, title, status, current_version_id, created_by, created_at, updated_at
        )
        SELECT id, workspace_id, slack_thread_id, title, status, current_version_id, created_by, created_at, updated_at
        FROM contracts;

        DROP TABLE contracts;
        ALTER TABLE contracts_email_migration RENAME TO contracts;
        """
    )
