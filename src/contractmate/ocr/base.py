from __future__ import annotations

from pathlib import Path
from typing import Protocol

from contractmate.schemas.documents import ParsedDocument


class OCRProcessingError(RuntimeError):
    """Raised when an OCR provider cannot produce a complete document."""


class OCRBackend(Protocol):
    def supports(self, mime_type: str) -> bool:
        ...

    def extract(self, file_path: Path, *, parsed_document: ParsedDocument) -> ParsedDocument:
        ...
