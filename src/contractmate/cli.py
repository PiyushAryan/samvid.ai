from __future__ import annotations

import argparse
import json
import logging
import os
import signal
from threading import Event
from pathlib import Path

from contractmate.email.interface import EmailSender
from contractmate.email.messages import OutboundEmailMessage
from contractmate.db.session import initialize_database
from contractmate.db.session import connect
from contractmate.db.repositories.knowledge_outbox import KnowledgeOutboxRepository
from contractmate.db.repositories.user_accounts import UserAccountRepository
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.settings import Settings
from contractmate.workers.contract_worker import ContractWorker
from contractmate.workers.knowledge_worker import KnowledgeIndexWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Samvid contract intelligence utilities")
    subcommands = parser.add_subparsers(dest="command")

    review = subcommands.add_parser("review", help="Review a local contract-like file")
    review.add_argument("path", type=Path)
    review.add_argument("--workspace-id", default="local-workspace")
    review.add_argument("--email-thread-id", default="local-email-thread")
    review.add_argument("--user-id", default="local@example.com")

    test_email = subcommands.add_parser("send-test-email", help="Send a Resend configuration test")
    test_email.add_argument("--to", required=True, help="Recipient email address")

    worker = subcommands.add_parser("worker", help="Run the RabbitMQ contract review worker")
    worker.add_argument("--poll-interval", type=float, default=1.0, help="Seconds to wait when the queue is empty")

    knowledge_worker = subcommands.add_parser("knowledge-worker", help="Run the RabbitMQ knowledge indexing worker")
    knowledge_worker.add_argument("--poll-interval", type=float, default=1.0, help="Seconds to wait when the queue is empty")

    subcommands.add_parser(
        "knowledge-backfill",
        help="Queue current reviewed contract versions that do not have a ready knowledge index",
    )
    subcommands.add_parser(
        "knowledge-retry-failed",
        help="Reset failed knowledge indexes and delivery intents for another attempt",
    )
    subcommands.add_parser(
        "knowledge-status",
        help="Show knowledge index and durable delivery status counts",
    )

    subcommands.add_parser("migrate", help="Apply the current database schema using the direct database URL")

    args = parser.parse_args()
    if args.command == "review":
        service = ContractProcessingService.local(Settings.from_env())
        result = service.review_local_file(
            file_path=args.path,
            workspace_id=args.workspace_id,
            email_thread_id=args.email_thread_id,
            requested_by=args.user_id,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    if args.command == "send-test-email":
        settings = Settings.from_env()
        if not settings.resend_api_key or settings.resend_api_key == "re_xxxxxxxxx":
            parser.error("Replace RESEND_API_KEY=re_xxxxxxxxx in .env with your real Resend API key.")
        EmailSender(settings).send(
            OutboundEmailMessage(
                from_address=settings.email_from_address,
                to_address=args.to,
                subject="Hello World",
                text="Congrats on sending your first email!",
                html="<p>Congrats on sending your <strong>first email</strong>!</p>",
            )
        )
        print(f"Test email sent to {args.to}")
        return

    if args.command == "worker":
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        settings = Settings.from_env()
        settings.validate_runtime()
        stop_event = Event()

        def request_stop(signum: int, _frame: object) -> None:
            logging.getLogger(__name__).info("Received signal %s; stopping after the current job", signum)
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        ContractWorker.from_settings(settings).run_forever(
            poll_interval_seconds=max(args.poll_interval, 0.1),
            stop_requested=stop_event.is_set,
        )
        return

    if args.command == "knowledge-worker":
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        settings = Settings.from_env()
        settings.validate_runtime()
        stop_event = Event()

        def request_knowledge_stop(signum: int, _frame: object) -> None:
            logging.getLogger(__name__).info("Received signal %s; stopping after the current job", signum)
            stop_event.set()

        signal.signal(signal.SIGINT, request_knowledge_stop)
        signal.signal(signal.SIGTERM, request_knowledge_stop)
        KnowledgeIndexWorker.from_settings(settings).run_forever(
            poll_interval_seconds=max(args.poll_interval, 0.1),
            stop_requested=stop_event.is_set,
        )
        return

    if args.command in {"knowledge-backfill", "knowledge-retry-failed", "knowledge-status"}:
        settings = Settings.from_env()
        initialize_database(
            settings.database_url,
            schema_database_url=settings.database_direct_url,
        )
        connection = connect(settings.database_direct_url or settings.database_url)
        try:
            outbox = KnowledgeOutboxRepository(connection)
            if args.command == "knowledge-backfill":
                print(json.dumps({"queued": outbox.backfill()}, indent=2))
            elif args.command == "knowledge-retry-failed":
                print(json.dumps(outbox.retry_failed(), indent=2))
            else:
                print(json.dumps(outbox.status(), indent=2))
        finally:
            connection.close()
        return

    if args.command == "migrate":
        settings = Settings.from_env()
        initialize_database(
            settings.database_url,
            schema_database_url=settings.database_direct_url,
        )
        connection = connect(settings.database_direct_url or settings.database_url)
        try:
            accounts = UserAccountRepository(connection)
            if settings.samvid_super_admin_email:
                accounts.bootstrap_super_admin(email=settings.samvid_super_admin_email)
        finally:
            connection.close()
        print("Samvid database schema is current.")
        return

    parser.print_help()
