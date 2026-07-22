from __future__ import annotations

from html import escape
import smtplib
from email.message import EmailMessage

import resend

from contractmate.email.messages import OutboundEmailMessage
from contractmate.settings import Settings


class EmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutboundEmailMessage) -> None:
        if self.settings.resend_api_key and self.settings.resend_api_key != "re_xxxxxxxxx":
            resend.api_key = self.settings.resend_api_key
            payload = {
                "from": str(message.from_address),
                "to": [str(message.to_address)],
                "subject": message.subject,
                "text": message.text,
                "html": message.html or _plain_text_html(message.text),
            }
            headers = _thread_headers(message)
            if headers:
                payload["headers"] = headers
            options = {"idempotency_key": message.idempotency_key} if message.idempotency_key else None
            if options is None:
                resend.Emails.send(payload)
            else:
                resend.Emails.send(payload, options)
            return

        if not self.settings.smtp_host:
            print(f"[email:dry-run] to={message.to_address} subject={message.subject}\n{message.text}")
            return

        email = EmailMessage()
        email["From"] = str(message.from_address)
        email["To"] = str(message.to_address)
        email["Subject"] = message.subject
        for name, value in _thread_headers(message).items():
            email[name] = value
        email.set_content(message.text)
        if message.html:
            email.add_alternative(message.html, subtype="html")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password or "")
            smtp.send_message(email)


def _plain_text_html(text: str) -> str:
    return f'<pre style="font-family: sans-serif; white-space: pre-wrap">{escape(text)}</pre>'


def _thread_headers(message: OutboundEmailMessage) -> dict[str, str]:
    headers: dict[str, str] = {}
    if message.in_reply_to:
        headers["In-Reply-To"] = message.in_reply_to
    if message.references:
        headers["References"] = message.references
    return headers
