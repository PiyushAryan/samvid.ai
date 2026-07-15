from __future__ import annotations

from pathlib import Path
from typing import Protocol

from contractmate.schemas.documents import ParsedDocument


class DocumentParser(Protocol):
    def parse(self, file_path: Path, *, document_id: str, sha256: str, mime_type: str) -> ParsedDocument:
        ...
