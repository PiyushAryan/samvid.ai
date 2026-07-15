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
