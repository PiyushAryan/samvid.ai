from __future__ import annotations

import argparse
import json
from pathlib import Path

from contractmate.email.interface import EmailSender
from contractmate.email.messages import OutboundEmailMessage
from contractmate.services.contract_processing import ContractProcessingService
from contractmate.settings import Settings
from contractmate.workers.contract_worker import ContractWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="ContractMate local MVP utilities")
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
        settings = Settings.from_env()
        settings.validate_runtime()
        ContractWorker.from_settings(settings).run_forever(poll_interval_seconds=max(args.poll_interval, 0.1))
        return

    parser.print_help()
