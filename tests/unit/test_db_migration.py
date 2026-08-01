import sqlite3
from pathlib import Path

from contractmate.db.session import connect


def test_connect_migrates_legacy_slack_contract_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE contracts (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            slack_thread_id TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL,
            current_version_id TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO contracts(id, workspace_id, slack_thread_id, title, status, current_version_id, created_by)
        VALUES ('c1', 'w1', 'legacy-thread', 'Contract', 'received', 'v1', 'u1');
        """
    )
    connection.close()

    migrated = connect(f"sqlite:///{db_path}")
    columns = {row["name"] for row in migrated.execute("PRAGMA table_info(contracts)").fetchall()}
    row = migrated.execute("SELECT email_thread_id FROM contracts WHERE id = 'c1'").fetchone()

    assert "email_thread_id" in columns
    assert "slack_thread_id" not in columns
    assert row["email_thread_id"] == "legacy-thread"


def test_connect_upgrades_prelease_slack_schema_after_intake_migration_recorded(tmp_path: Path) -> None:
    db_path = tmp_path / "prelease.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO schema_migrations(version) VALUES ('20260731_slack_intake');
        CREATE TABLE inbound_slack_events (
            id TEXT PRIMARY KEY, event_id TEXT UNIQUE, team_id TEXT, event_type TEXT, payload_json TEXT,
            payload_hash TEXT, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
            next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP, lease_expires_at TEXT, last_error TEXT,
            received_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE inbound_slack_file_submissions (
            event_id TEXT, file_id TEXT, status TEXT DEFAULT 'processing', lease_expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(event_id, file_id)
        );
        INSERT INTO inbound_slack_file_submissions(event_id, file_id) VALUES ('Ev1', 'F1');
        """
    )
    connection.commit()
    connection.close()

    migrated = connect(f"sqlite:///{db_path}")
    event_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(inbound_slack_events)")}
    file_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(inbound_slack_file_submissions)")}
    row = migrated.execute(
        "SELECT review_job_id FROM inbound_slack_file_submissions WHERE event_id = 'Ev1' AND file_id = 'F1'"
    ).fetchone()
    versions = {row["version"] for row in migrated.execute("SELECT version FROM schema_migrations")}
    outbound_columns = {
        row["name"] for row in migrated.execute("PRAGMA table_info(outbound_slack_outbox)")
    }
    review_outbox_exists = migrated.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'slack_review_job_outbox'"
    ).fetchone()
    migrated.close()

    assert "lease_token" in event_columns
    assert {"lease_token", "review_job_id"}.issubset(file_columns)
    assert row is not None and row["review_job_id"]
    assert "20260731_slack_leases" in versions
    assert "20260731_slack_review_job_outbox" in versions
    assert "lease_token" in outbound_columns
    assert review_outbox_exists is not None
