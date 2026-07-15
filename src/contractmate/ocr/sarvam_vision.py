from __future__ import annotations

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader, PdfWriter
from sarvamai import SarvamAI

from contractmate.ocr.base import OCRProcessingError
from contractmate.schemas.documents import DocumentPage, DocumentSpan, ParsedDocument


_PAGE_COLLECTION_KEYS = {"pages", "page_data", "page_results", "page_outputs"}
_PAGE_NUMBER_KEYS = ("page_number", "page_no", "page_num", "page_index", "page")
_TEXT_KEYS = (
    "text",
    "content",
    "page_content",
    "extracted_text",
    "markdown",
    "markdown_content",
    "md",
    "raw_text",
    "predicted_text",
    "html",
)


@dataclass
class SarvamVisionOCR:
    api_key: str
    language: str = "en-IN"
    timeout_seconds: int = 600
    client_factory: Callable[..., Any] = field(default=SarvamAI, repr=False)

    parser_name = "sarvam-vision"
    parser_version = "document-digitization-v1"
    max_pages_per_job = 10

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    def extract(self, file_path: Path, *, parsed_document: ParsedDocument) -> ParsedDocument:
        if not self.supports(parsed_document.mime_type):
            raise OCRProcessingError(f"Sarvam Vision OCR does not support {parsed_document.mime_type!r} in ContractMate.")

        try:
            with tempfile.TemporaryDirectory(prefix="contractmate-sarvam-") as work_dir_value:
                work_dir = Path(work_dir_value)
                chunks = self._split_pdf(file_path, work_dir)
                pages: list[DocumentPage] = []
                for chunk_index, (chunk_path, page_offset) in enumerate(chunks, start=1):
                    archive_path = work_dir / f"sarvam-output-{chunk_index}.zip"
                    pages.extend(self._process_chunk(chunk_path, archive_path, page_offset=page_offset))
        except OCRProcessingError:
            raise
        except Exception as exc:
            raise OCRProcessingError(f"Sarvam Vision OCR failed: {exc}") from exc

        if not pages or not any(page.text.strip() for page in pages):
            raise OCRProcessingError("Sarvam Vision OCR completed without extracting readable text.")

        pages.sort(key=lambda page: page.page_number)
        return ParsedDocument(
            document_id=parsed_document.document_id,
            sha256=parsed_document.sha256,
            mime_type=parsed_document.mime_type,
            page_count=len(pages),
            pages=pages,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            requires_ocr=False,
        )

    def _process_chunk(self, chunk_path: Path, archive_path: Path, *, page_offset: int) -> list[DocumentPage]:
        client = self.client_factory(api_subscription_key=self.api_key)
        job = client.document_intelligence.create_job(language=self.language, output_format="md")
        job.upload_file(str(chunk_path))
        job.start()
        status = job.wait_until_complete(timeout=float(self.timeout_seconds))
        state = _state_value(getattr(status, "job_state", None))
        if state != "completed":
            detail = getattr(status, "error_message", None) or state or "unknown state"
            raise OCRProcessingError(f"Sarvam Vision OCR job did not complete successfully: {detail}.")
        job.download_output(str(archive_path))
        return parse_sarvam_output_archive(archive_path, page_offset=page_offset)

    def _split_pdf(self, file_path: Path, work_dir: Path) -> list[tuple[Path, int]]:
        reader = PdfReader(str(file_path))
        page_count = len(reader.pages)
        if page_count == 0:
            raise OCRProcessingError("The PDF has no pages.")
        if page_count <= self.max_pages_per_job:
            return [(file_path, 0)]

        chunks: list[tuple[Path, int]] = []
        for page_offset in range(0, page_count, self.max_pages_per_job):
            writer = PdfWriter()
            for page in reader.pages[page_offset : page_offset + self.max_pages_per_job]:
                writer.add_page(page)
            chunk_path = work_dir / f"input-pages-{page_offset + 1}-{min(page_offset + 10, page_count)}.pdf"
            with chunk_path.open("wb") as chunk_file:
                writer.write(chunk_file)
            chunks.append((chunk_path, page_offset))
        return chunks


def parse_sarvam_output_archive(archive_path: Path, *, page_offset: int = 0) -> list[DocumentPage]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            json_pages = _pages_from_json_members(archive, page_offset=page_offset)
            if json_pages:
                return json_pages
            markdown_pages = _pages_from_markdown_members(archive, page_offset=page_offset)
            if markdown_pages:
                return markdown_pages
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise OCRProcessingError(f"Could not read the Sarvam Vision output archive: {exc}") from exc
    raise OCRProcessingError("Sarvam Vision output did not contain page text in JSON or Markdown format.")


def _pages_from_json_members(archive: zipfile.ZipFile, *, page_offset: int) -> list[DocumentPage]:
    for name in sorted(item for item in archive.namelist() if item.casefold().endswith(".json")):
        payload = json.loads(archive.read(name).decode("utf-8"))
        page_items = _find_page_items(payload)
        pages = _document_pages(page_items, page_offset=page_offset)
        if pages:
            return pages
    return []


def _find_page_items(value: Any) -> list[Any]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() in _PAGE_COLLECTION_KEYS and isinstance(nested, list):
                return nested
        for nested in value.values():
            result = _find_page_items(nested)
            if result:
                return result
        if _extract_text(value):
            return [value]
    elif isinstance(value, list):
        if value and all(isinstance(item, (dict, str)) for item in value):
            return value
        for nested in value:
            result = _find_page_items(nested)
            if result:
                return result
    return []


def _document_pages(page_items: list[Any], *, page_offset: int) -> list[DocumentPage]:
    pages: list[DocumentPage] = []
    for index, item in enumerate(page_items, start=1):
        text = item.strip() if isinstance(item, str) else _extract_text(item)
        if not text:
            continue
        local_page_number = _extract_page_number(item, fallback=index)
        page_number = page_offset + local_page_number
        tables = item.get("tables", []) if isinstance(item, dict) else []
        pages.append(
            DocumentPage(
                page_number=page_number,
                text=text,
                spans=[DocumentSpan(text=text, page_number=page_number)],
                tables=[table for table in tables if isinstance(table, dict)] if isinstance(tables, list) else [],
                warnings=["Text extracted with Sarvam Vision OCR."],
            )
        )
    return pages


def _extract_page_number(item: Any, *, fallback: int) -> int:
    if not isinstance(item, dict):
        return fallback
    for key in _PAGE_NUMBER_KEYS:
        value = item.get(key)
        if isinstance(value, int) and value >= 0:
            return value + 1 if key == "page_index" else max(value, 1)
        if isinstance(value, str) and value.isdigit():
            number = int(value)
            return number + 1 if key == "page_index" else max(number, 1)
    return fallback


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_extract_text(item) for item in value))).strip()
    if not isinstance(value, dict):
        return ""

    direct = [value[key].strip() for key in _TEXT_KEYS if isinstance(value.get(key), str) and value[key].strip()]
    if direct:
        return "\n".join(dict.fromkeys(direct))

    nested_text: list[str] = []
    for key, nested in value.items():
        if key.casefold() in {"blocks", "lines", "paragraphs", "sections", "elements", "children"}:
            extracted = _extract_text(nested)
            if extracted:
                nested_text.append(extracted)
    return "\n".join(nested_text).strip()


def _pages_from_markdown_members(archive: zipfile.ZipFile, *, page_offset: int) -> list[DocumentPage]:
    names = sorted(
        name for name in archive.namelist() if name.casefold().endswith((".md", ".markdown"))
    )
    if not names:
        return []

    raw_pages: list[str] = []
    for name in names:
        markdown = archive.read(name).decode("utf-8").strip()
        if not markdown:
            continue
        raw_pages.extend(_split_markdown_pages(markdown))
    return _document_pages(raw_pages, page_offset=page_offset)


def _split_markdown_pages(markdown: str) -> list[str]:
    pages = re.split(
        r"\f|(?:^|\n)(?:<!--\s*)?(?:#{1,6}\s*)?page\s+\d+(?:\s*-->)?\s*(?:\n|$)",
        markdown,
        flags=re.IGNORECASE,
    )
    return [page.strip() for page in pages if page.strip()]


def _state_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().casefold()
