from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from contractmate.db.repositories.slack import SlackRepository
from contractmate.db.repositories.user_accounts import UserAccountRepository


class _Result:
    def __init__(self, *, row: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None) -> None:
        self.row = row
        self.rows = rows if rows is not None else ([row] if row is not None else [])
        self.rowcount = 1

    def fetchone(self) -> dict[str, Any] | None:
        return self.row

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakePostgresConnection:
    def __init__(self) -> None:
        self.in_transaction = False
        self.commits = 0
        self.rollbacks = 0
        self.transaction_contexts = 0

    def execute(self, statement: str, _params: tuple[Any, ...] = ()) -> _Result:
        self.in_transaction = True
        if "FROM slack_installations" in statement:
            return _Result(row={
                "id": "installation-1",
                "team_id": "T1",
                "team_name": "Team",
                "bot_user_id": "B1",
                "encrypted_bot_token": "encrypted",
                "installed_by_account_id": "account-1",
                "status": "active",
                "created_at": "2026-08-29T00:00:00Z",
            })
        if "FROM user_accounts" in statement:
            return _Result(row={
                "id": "account-1",
                "auth_subject": "subject-1",
                "email": "human@example.com",
                "display_name": "Human",
                "role": "user",
                "state": "active",
                "personal_workspace_id": "workspace-1",
                "source": "signup",
                "claimed_at": "2026-08-29T00:00:00Z",
                "created_at": "2026-08-29T00:00:00Z",
                "updated_at": "2026-08-29T00:00:00Z",
                "contract_count": 0,
            })
        if "FROM slack_review_executions" in statement:
            return _Result(row={"status": "completed"})
        return _Result()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transaction_contexts += 1
        try:
            yield
        except Exception:
            self.rollback()
            raise
        else:
            self.commit()

    def commit(self) -> None:
        self.commits += 1
        self.in_transaction = False

    def rollback(self) -> None:
        self.rollbacks += 1
        self.in_transaction = False


_FakePostgresConnection.__module__ = "psycopg.fake"


def test_slack_installation_reads_close_postgres_transactions() -> None:
    connection = _FakePostgresConnection()
    repository = SlackRepository(connection)

    assert repository.get_installation_by_team(team_id="T1") is not None
    assert connection.in_transaction is False
    assert repository.get_installation(installation_id="installation-1") is not None
    assert connection.in_transaction is False
    assert repository.get_installation_for_account(
        installation_id="installation-1", account_id="account-1",
    ) is not None
    assert connection.in_transaction is False
    assert len(repository.list_installations(account_id="account-1")) == 1
    assert connection.in_transaction is False
    assert connection.transaction_contexts == 4


def test_slack_review_status_read_closes_postgres_transaction() -> None:
    connection = _FakePostgresConnection()
    repository = SlackRepository(connection)

    assert repository.get_review_execution_status(submission_key="Ev1:F1") == "completed"
    assert connection.in_transaction is False
    assert connection.transaction_contexts == 1


def test_existing_account_lookup_closes_postgres_transaction_before_slack_write() -> None:
    connection = _FakePostgresConnection()
    accounts = UserAccountRepository(connection)
    slack = SlackRepository(connection)

    account = accounts.get_by_email("human@example.com")
    assert account is not None
    assert connection.in_transaction is False

    slack.link_user(
        team_id="T1",
        slack_user_id="U1",
        account_id=account.id,
        email=account.email,
    )
    assert connection.in_transaction is False
    assert connection.commits == 2
