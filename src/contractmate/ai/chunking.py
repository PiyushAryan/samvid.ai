from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class PageContent:
    page_number: int | None
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    contract_id: str
    page_number: int | None
    text: str
    start_char: int
    end_char: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        if self.page_number is None:
            return f"{self.contract_id} review"
        return f"{self.contract_id} p.{self.page_number}"


@dataclass(frozen=True)
class PageAwareChunker:
    max_chars: int = 1_200
    overlap_chars: int = 180
    min_boundary_chars: int = 360

    def __post_init__(self) -> None:
        if self.max_chars < 100:
            raise ValueError("max_chars must be at least 100.")
        if not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars must be non-negative and smaller than max_chars.")
        if not 1 <= self.min_boundary_chars <= self.max_chars:
            raise ValueError("min_boundary_chars must be between one and max_chars.")

    def chunk_pages(
        self,
        *,
        document_id: str,
        contract_id: str,
        pages: Sequence[PageContent],
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[DocumentChunk, ...]:
        if not document_id.strip() or not contract_id.strip():
            raise ValueError("document_id and contract_id are required.")
        chunks: list[DocumentChunk] = []
        base_metadata = dict(metadata or {})
        seen_pages: set[int] = set()
        for page in pages:
            if page.page_number < 1 or page.page_number in seen_pages:
                raise ValueError("Page numbers must be unique positive integers.")
            seen_pages.add(page.page_number)
            chunks.extend(
                self._chunk_page(
                    document_id=document_id,
                    contract_id=contract_id,
                    page=page,
                    metadata={**base_metadata, **dict(page.metadata)},
                )
            )
        return tuple(chunks)

    def _chunk_page(
        self,
        *,
        document_id: str,
        contract_id: str,
        page: PageContent,
        metadata: Mapping[str, Any],
    ) -> list[DocumentChunk]:
        text = page.text
        chunks: list[DocumentChunk] = []
        cursor = 0
        while cursor < len(text):
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text):
                break
            hard_end = min(len(text), cursor + self.max_chars)
            end = hard_end if hard_end == len(text) else self._boundary(text, cursor, hard_end)
            chunk_text = text[cursor:end].rstrip()
            actual_end = cursor + len(chunk_text)
            if chunk_text:
                identity = f"{document_id}:{page.page_number}:{cursor}:{actual_end}:{chunk_text}".encode()
                chunk_id = hashlib.sha256(identity).hexdigest()[:24]
                chunks.append(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=document_id,
                        contract_id=contract_id,
                        page_number=page.page_number,
                        text=chunk_text,
                        start_char=cursor,
                        end_char=actual_end,
                        metadata=dict(metadata),
                    )
                )
            if end >= len(text):
                break
            next_cursor = max(cursor + 1, end - self.overlap_chars)
            cursor = next_cursor
        return chunks

    def _boundary(self, text: str, start: int, hard_end: int) -> int:
        lower = min(hard_end, start + self.min_boundary_chars)
        window = text[lower:hard_end]
        for separator in ("\n\n", "\n", ". ", "; ", " "):
            position = window.rfind(separator)
            if position >= 0:
                return lower + position + len(separator)
        return hard_end
