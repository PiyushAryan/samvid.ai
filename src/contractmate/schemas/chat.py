from __future__ import annotations

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=180)
    contract_id: str | None = Field(default=None, max_length=128)


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
