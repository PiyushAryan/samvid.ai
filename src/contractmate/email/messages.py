from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class EmailAttachment(BaseModel):
    filename: str
    mime_type: str | None = None
    content_base64: str | None = None
    local_path: Path | None = None

    @model_validator(mode="after")
    def require_content_or_path(self) -> "EmailAttachment":
        if not self.content_base64 and not self.local_path:
            raise ValueError("Email attachment requires either content_base64 or local_path.")
        return self


class InboundEmailMessage(BaseModel):
    message_id: str = Field(min_length=1)
    from_address: str = Field(min_length=3)
    from_name: str | None = None
    to_addresses: list[str] = Field(default_factory=list)
    subject: str = ""
    text: str = ""
    thread_id: str | None = None
    response_address: str | None = None
    original_message_id: str | None = None
    references: str | None = None
    attachments: list[EmailAttachment] = Field(default_factory=list)

    @property
    def email_thread_id(self) -> str:
        return self.thread_id or self.message_id


class OutboundEmailMessage(BaseModel):
    to_address: str = Field(min_length=3)
    from_address: str = Field(min_length=3)
    subject: str
    text: str
    html: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    idempotency_key: str | None = None
