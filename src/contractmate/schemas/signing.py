from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SignerStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    VIEWED = "viewed"
    SIGNED = "signed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SigningRequestStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_SIGNER_STATUSES = {
    SignerStatus.DECLINED,
    SignerStatus.EXPIRED,
    SignerStatus.CANCELLED,
}

TERMINAL_REQUEST_STATUSES = {
    SigningRequestStatus.COMPLETED,
    SigningRequestStatus.DECLINED,
    SigningRequestStatus.EXPIRED,
    SigningRequestStatus.CANCELLED,
}


class SignerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    role: str | None = Field(default=None, max_length=120)
    required: bool = True
    display_order: int | None = Field(default=None, ge=0)

    @field_validator("email")
    @classmethod
    def require_email_shape(cls, value: str) -> str:
        normalized = value.strip()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email must be a valid email address")
        return normalized


class SigningRequestCreate(BaseModel):
    signers: list[SignerCreate] = Field(default_factory=list)


class SignerStatusEventCreate(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    status: SignerStatus
    note: str | None = Field(default=None, max_length=1000)


class SignerStatusEventOut(BaseModel):
    id: str
    signer_id: str
    status: SignerStatus
    note: str | None
    actor_email: str
    actor_name: str
    created_at: str


class SignerOut(BaseModel):
    id: str
    name: str
    email: str
    role: str | None
    required: bool
    display_order: int
    latest_status: SignerStatus
    created_at: str
    events: list[SignerStatusEventOut] = Field(default_factory=list)


class SigningRequestOut(BaseModel):
    id: str
    workspace_id: str
    contract_id: str
    contract_title: str | None = None
    contract_version_id: str
    status: SigningRequestStatus
    active: bool
    created_by: str
    created_at: str
    closed_at: str | None = None
    signers: list[SignerOut] = Field(default_factory=list)


class SigningSummary(BaseModel):
    active_request_id: str | None = None
    status: SigningRequestStatus | None = None
    required_signed: int = 0
    required_total: int = 0
    signer_total: int = 0
