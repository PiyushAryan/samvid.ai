from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


@dataclass(frozen=True)
class FileValidationResult:
    ok: bool
    sha256: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0
    error_code: str | None = None
    message: str | None = None


def validate_uploaded_file(file_path: Path, *, declared_mime_type: str | None, max_size_mb: int) -> FileValidationResult:
    if not file_path.exists() or not file_path.is_file():
        return FileValidationResult(False, error_code="FILE_NOT_FOUND", message="Uploaded file was not found.")

    data = file_path.read_bytes()
    size_bytes = len(data)
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        return FileValidationResult(
            False,
            size_bytes=size_bytes,
            error_code="FILE_TOO_LARGE",
            message=f"File exceeds the {max_size_mb} MB limit.",
        )

    sniffed_mime_type = sniff_mime_type(data, file_path)
    if sniffed_mime_type not in SUPPORTED_MIME_TYPES:
        return FileValidationResult(
            False,
            mime_type=sniffed_mime_type,
            size_bytes=size_bytes,
            error_code="UNSUPPORTED_FILE_TYPE",
            message="Only PDF, DOCX and plain text files are supported.",
        )

    if declared_mime_type and declared_mime_type in SUPPORTED_MIME_TYPES and declared_mime_type != sniffed_mime_type:
        return FileValidationResult(
            False,
            mime_type=sniffed_mime_type,
            size_bytes=size_bytes,
            error_code="MIME_MISMATCH",
            message="Declared file type does not match the uploaded file contents.",
        )

    return FileValidationResult(
        True,
        sha256=hashlib.sha256(data).hexdigest(),
        mime_type=sniffed_mime_type,
        size_bytes=size_bytes,
    )


def sniff_mime_type(data: bytes, file_path: Path) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04") and file_path.suffix.lower() == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if _looks_like_text(data):
        return "text/plain"
    return "application/octet-stream"


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:4096]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    control = sum(1 for byte in sample if byte < 32 and byte not in {9, 10, 13})
    return control / max(len(sample), 1) < 0.05
