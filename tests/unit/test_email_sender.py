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
