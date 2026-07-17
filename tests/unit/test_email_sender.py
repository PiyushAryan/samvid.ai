from contractmate.email.interface import EmailSender
from contractmate.email.messages import OutboundEmailMessage
from contractmate.settings import Settings


def test_email_sender_uses_resend_when_api_key_is_configured(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr("resend.Emails.send", sent.append)
    settings = Settings(
        email_from_address="onboarding@resend.dev",
        resend_api_key="re_test",
    )
    message = OutboundEmailMessage(
        from_address=settings.email_from_address,
        to_address="piyusharyan81@gmail.com",
        subject="Hello World",
        text="Congrats on sending your first email!",
        html="<p>Congrats on sending your <strong>first email</strong>!</p>",
    )

    EmailSender(settings).send(message)

    assert sent == [
        {
            "from": "onboarding@resend.dev",
            "to": ["piyusharyan81@gmail.com"],
            "subject": "Hello World",
            "text": "Congrats on sending your first email!",
            "html": "<p>Congrats on sending your <strong>first email</strong>!</p>",
        }
    ]


def test_email_sender_adds_thread_headers_to_resend(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr("resend.Emails.send", sent.append)
    message = OutboundEmailMessage(
        from_address="onboarding@resend.dev",
        to_address="sender@example.com",
        subject="Re: Agreement",
        text="Review ready",
        in_reply_to="<message@example.com>",
        references="<earlier@example.com> <message@example.com>",
    )

    EmailSender(Settings(resend_api_key="re_test")).send(message)

    assert sent[0]["headers"] == {
        "In-Reply-To": "<message@example.com>",
        "References": "<earlier@example.com> <message@example.com>",
    }


def test_email_sender_adds_thread_headers_to_smtp(monkeypatch) -> None:
    smtp = _FakeSMTP()
    monkeypatch.setattr("smtplib.SMTP", lambda *_args, **_kwargs: smtp)
    message = OutboundEmailMessage(
        from_address="contracts@example.com",
        to_address="sender@example.com",
        subject="Re: Agreement",
        text="Review ready",
        in_reply_to="<message@example.com>",
        references="<earlier@example.com> <message@example.com>",
    )

    EmailSender(Settings(smtp_host="smtp.example.com", smtp_use_tls=False)).send(message)

    assert smtp.message["In-Reply-To"] == "<message@example.com>"
    assert smtp.message["References"] == "<earlier@example.com> <message@example.com>"


class _FakeSMTP:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass

    def send_message(self, message) -> None:
        self.message = message
