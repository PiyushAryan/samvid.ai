from __future__ import annotations

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentSpan(BaseModel):
    text: str
    page_number: int = Field(ge=1)
    bbox: BoundingBox | None = None


class DocumentPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    spans: list[DocumentSpan] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    document_id: str
    sha256: str
    mime_type: str
    page_count: int = Field(ge=0)
    pages: list[DocumentPage]
    parser_name: str
    parser_version: str
    requires_ocr: bool = False
