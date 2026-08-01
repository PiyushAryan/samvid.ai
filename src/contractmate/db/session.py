from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from contractmate.db.models import POSTGRES_EXTENSIONS_SQL, POSTGRES_SCHEMA_SQL, SQLITE_SCHEMA_SQL

_initialized_postgres_schemas: set[str] = set()
_schema_lock = Lock()


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
    _run_sqlite_upgrade_migrations(connection)
    connection.commit()
    return connection


def connect_postgres(database_url: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install psycopg to use PostgreSQL: uv sync") from exc

    return psycopg.connect(normalize_postgres_url(database_url), row_factory=dict_row)


def initialize_database(database_url: str, *, schema_database_url: str | None = None) -> None:
    if not is_postgres_url(database_url):
        connection = connect_sqlite(database_url)
        connection.close()
        return

    migration_url = schema_database_url or database_url
    normalized_url = normalize_postgres_url(migration_url)
    with _schema_lock:
        if normalized_url in _initialized_postgres_schemas:
            return
        connection = connect_postgres(migration_url)
        try:
            connection.execute(POSTGRES_EXTENSIONS_SQL)
            connection.execute(POSTGRES_SCHEMA_SQL)
            _run_postgres_upgrade_migrations(connection)
            connection.commit()
        finally:
            connection.close()
        _initialized_postgres_schemas.add(normalized_url)


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


def _run_sqlite_upgrade_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied = {
        str(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if "20260731_slack_intake" in applied:
        _run_sqlite_slack_lease_migration(connection, applied)
        return

    account_schema_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'user_accounts'"
    ).fetchone()
    account_schema = str(account_schema_row["sql"] or "") if account_schema_row else ""
    if "inbound_slack" not in account_schema:
        connection.executescript(
            """
            CREATE TABLE user_accounts_slack_migration (
                id TEXT PRIMARY KEY,
                auth_subject TEXT UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT,
                role TEXT NOT NULL CHECK (role IN ('user', 'super_admin')),
                state TEXT NOT NULL CHECK (state IN ('unclaimed', 'active')),
                personal_workspace_id TEXT UNIQUE,
                source TEXT NOT NULL CHECK (source IN ('signup', 'inbound_email', 'inbound_slack')),
                claimed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK ((role = 'super_admin' AND personal_workspace_id IS NULL)
                    OR (role = 'user' AND personal_workspace_id IS NOT NULL))
            );
            INSERT INTO user_accounts_slack_migration(
                id, auth_subject, email, display_name, role, state, personal_workspace_id,
                source, claimed_at, created_at, updated_at
            )
            SELECT id, auth_subject, email, display_name, role, state, personal_workspace_id,
                source, claimed_at, created_at, updated_at
            FROM user_accounts;
            DROP TABLE user_accounts;
            ALTER TABLE user_accounts_slack_migration RENAME TO user_accounts;
            CREATE INDEX IF NOT EXISTS ix_user_accounts_role_state
                ON user_accounts(role, state, created_at);
            """
        )

    contract_columns = {
        str(row["name"]): row for row in connection.execute("PRAGMA table_info(contracts)").fetchall()
    }
    if "email_thread_id" in contract_columns and int(contract_columns["email_thread_id"]["notnull"]) == 1:
        connection.executescript(
            """
            CREATE TABLE contracts_slack_migration (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                email_thread_id TEXT,
                title TEXT,
                status TEXT NOT NULL,
                current_version_id TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO contracts_slack_migration(
                id, workspace_id, email_thread_id, title, status, current_version_id,
                created_by, created_at, updated_at
            )
            SELECT id, workspace_id, email_thread_id, title, status, current_version_id,
                created_by, created_at, updated_at
            FROM contracts;
            DROP TABLE contracts;
            ALTER TABLE contracts_slack_migration RENAME TO contracts;
            """
        )

    connection.execute(
        """INSERT OR IGNORE INTO contract_sources(contract_id, source_channel, source_thread_key)
        SELECT id,
            CASE WHEN email_thread_id LIKE 'samvid-upload-%' THEN 'browser' ELSE 'email' END,
            COALESCE(email_thread_id, id)
        FROM contracts"""
    )
    connection.execute(
        "INSERT INTO schema_migrations(version) VALUES (?)",
        ("20260731_slack_intake",),
    )
    _run_sqlite_slack_lease_migration(connection, applied)


def _run_sqlite_slack_lease_migration(connection: sqlite3.Connection, applied: set[str]) -> None:
    version = "20260731_slack_leases"
    if version in applied:
        _run_sqlite_slack_review_outbox_migration(connection, applied)
        return
    event_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(inbound_slack_events)")}
    if "lease_token" not in event_columns:
        connection.execute("ALTER TABLE inbound_slack_events ADD COLUMN lease_token TEXT")
    file_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(inbound_slack_file_submissions)")}
    if "review_job_id" not in file_columns or "lease_token" not in file_columns:
        connection.executescript(
            """
            ALTER TABLE inbound_slack_file_submissions RENAME TO inbound_slack_file_submissions_pre_leases;
            CREATE TABLE inbound_slack_file_submissions (
                event_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('pending', 'processing', 'completed')),
                lease_token TEXT,
                review_job_id TEXT NOT NULL,
                lease_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id, file_id)
            );
            INSERT INTO inbound_slack_file_submissions(
                event_id, file_id, status, lease_token, review_job_id, lease_expires_at, created_at, updated_at
            ) SELECT event_id, file_id, status, NULL, lower(hex(randomblob(16))), lease_expires_at, created_at, updated_at
              FROM inbound_slack_file_submissions_pre_leases;
            DROP TABLE inbound_slack_file_submissions_pre_leases;
            """
        )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS slack_review_executions (
            submission_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('pending', 'processing', 'completed')),
            lease_token TEXT,
            lease_expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    _run_sqlite_slack_review_outbox_migration(connection, applied)


def _run_sqlite_slack_review_outbox_migration(
    connection: sqlite3.Connection, applied: set[str],
) -> None:
    version = "20260731_slack_review_job_outbox"
    if version in applied or connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?", (version,),
    ).fetchone() is not None:
        outbound_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(outbound_slack_outbox)")
        }
        if "lease_token" not in outbound_columns:
            connection.execute("ALTER TABLE outbound_slack_outbox ADD COLUMN lease_token TEXT")
        return
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS slack_review_job_outbox (
            submission_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            contract_id TEXT NOT NULL,
            contract_version_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'publishing', 'published')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            lease_token TEXT,
            lease_expires_at TEXT,
            last_error TEXT,
            published_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS ix_slack_review_job_outbox_delivery
        ON slack_review_job_outbox(status, next_attempt_at, lease_expires_at);
        """
    )
    outbound_columns = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(outbound_slack_outbox)")
    }
    if "lease_token" not in outbound_columns:
        connection.execute("ALTER TABLE outbound_slack_outbox ADD COLUMN lease_token TEXT")
    connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))


def _run_postgres_upgrade_migrations(connection: Any) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    result = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = '20260731_slack_intake'"
    )
    row = result.fetchone() if hasattr(result, "fetchone") else None
    if row is not None:
        _run_postgres_slack_lease_migration(connection)
        return
    connection.execute("ALTER TABLE contracts ALTER COLUMN email_thread_id DROP NOT NULL")
    connection.execute("ALTER TABLE user_accounts DROP CONSTRAINT IF EXISTS user_accounts_source_check")
    connection.execute(
        """ALTER TABLE user_accounts ADD CONSTRAINT user_accounts_source_check
        CHECK (source IN ('signup', 'inbound_email', 'inbound_slack'))"""
    )
    connection.execute(
        """INSERT INTO contract_sources(contract_id, source_channel, source_thread_key)
        SELECT id,
            CASE WHEN email_thread_id LIKE 'samvid-upload-%' THEN 'browser' ELSE 'email' END,
            COALESCE(email_thread_id, id)
        FROM contracts
        ON CONFLICT(contract_id) DO NOTHING"""
    )
    connection.execute(
        "INSERT INTO schema_migrations(version) VALUES ('20260731_slack_intake')"
    )
    _run_postgres_slack_lease_migration(connection)


def _run_postgres_slack_lease_migration(connection: Any) -> None:
    result = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = '20260731_slack_leases'"
    )
    row = result.fetchone() if hasattr(result, "fetchone") else None
    if row is not None:
        _run_postgres_slack_review_outbox_migration(connection)
        return
    connection.execute("ALTER TABLE inbound_slack_events ADD COLUMN IF NOT EXISTS lease_token TEXT")
    connection.execute("ALTER TABLE inbound_slack_file_submissions ADD COLUMN IF NOT EXISTS lease_token TEXT")
    connection.execute("ALTER TABLE inbound_slack_file_submissions ADD COLUMN IF NOT EXISTS review_job_id TEXT")
    connection.execute(
        """UPDATE inbound_slack_file_submissions SET review_job_id = md5(random()::text || clock_timestamp()::text)
        WHERE review_job_id IS NULL"""
    )
    connection.execute("ALTER TABLE inbound_slack_file_submissions ALTER COLUMN review_job_id SET NOT NULL")
    connection.execute(
        "ALTER TABLE inbound_slack_file_submissions DROP CONSTRAINT IF EXISTS inbound_slack_file_submissions_status_check"
    )
    connection.execute(
        """ALTER TABLE inbound_slack_file_submissions ADD CONSTRAINT inbound_slack_file_submissions_status_check
        CHECK (status IN ('pending', 'processing', 'completed'))"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS slack_review_executions (
            submission_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('pending', 'processing', 'completed')),
            lease_token TEXT,
            lease_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute("INSERT INTO schema_migrations(version) VALUES ('20260731_slack_leases')")
    _run_postgres_slack_review_outbox_migration(connection)


def _run_postgres_slack_review_outbox_migration(connection: Any) -> None:
    version = "20260731_slack_review_job_outbox"
    result = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = %s", (version,),
    )
    row = result.fetchone() if hasattr(result, "fetchone") else None
    if row is not None:
        connection.execute("ALTER TABLE outbound_slack_outbox ADD COLUMN IF NOT EXISTS lease_token TEXT")
        return
    connection.execute(
        """CREATE TABLE IF NOT EXISTS slack_review_job_outbox (
            submission_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            contract_id TEXT NOT NULL,
            contract_version_id TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'publishing', 'published')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            lease_token TEXT,
            lease_expires_at TIMESTAMPTZ,
            last_error TEXT,
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS ix_slack_review_job_outbox_delivery
        ON slack_review_job_outbox(status, next_attempt_at, lease_expires_at)"""
    )
    connection.execute("ALTER TABLE outbound_slack_outbox ADD COLUMN IF NOT EXISTS lease_token TEXT")
    connection.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
