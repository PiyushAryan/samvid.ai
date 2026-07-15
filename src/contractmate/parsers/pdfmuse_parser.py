from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from contractmate.schemas.documents import DocumentPage, DocumentSpan, ParsedDocument


class PdfMuseDocumentParser:
    """pdfmuse-facing parser wrapper with deterministic local fallbacks.

    The optional pdfmuse dependency can be wired here when installed. The fallback keeps
    local development and unit tests deterministic for text-like PDFs and DOCX files.
    """

    parser_name = "pdfmuse"
    parser_version = "local-fallback-v2"
    min_machine_text_chars = 80

    def parse(self, file_path: Path, *, document_id: str, sha256: str, mime_type: str) -> ParsedDocument:
        text, warnings = self._extract_text(file_path, mime_type)
        pages = self._to_pages(text)
        requires_ocr = len("".join(page.text for page in pages).strip()) < self.min_machine_text_chars
        if requires_ocr:
            warnings.append("Insufficient machine-readable text; OCR is required.")
        return ParsedDocument(
            document_id=document_id,
            sha256=sha256,
            mime_type=mime_type,
            page_count=len(pages),
            pages=pages,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            requires_ocr=requires_ocr,
        )

    def _extract_text(self, file_path: Path, mime_type: str) -> tuple[str, list[str]]:
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._extract_docx_text(file_path), ["DOCX parsed with local XML fallback."]

        if mime_type == "application/pdf":
            try:
                text = self._extract_pdf_text(file_path)
                return text, ["PDF parsed with pypdf fallback."]
            except Exception:
                text = self._extract_pdf_literal_text(file_path.read_bytes())
                return text, ["PDF parsed with local literal-text fallback."]

        data = file_path.read_bytes()
        return data.decode("utf-8", errors="ignore"), ["Plain text fallback parser used."]

    def _extract_docx_text(self, file_path: Path) -> str:
        with zipfile.ZipFile(file_path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", namespace):
            parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
            if parts:
                paragraphs.append("".join(parts))
        return "\n".join(paragraphs)

    def _extract_pdf_literal_text(self, data: bytes) -> str:
        decoded = data.decode("latin-1", errors="ignore")
        literals = re.findall(r"\(([^()]*)\)\s*T[Jj]", decoded)
        if literals:
            return "\n".join(literals)
        return ""

    def _extract_pdf_text(self, file_path: Path) -> str:
        reader = PdfReader(str(file_path))
        return "\f".join((page.extract_text() or "").strip() for page in reader.pages)

    def _to_pages(self, text: str) -> list[DocumentPage]:
        raw_pages = re.split(r"\f|(?:\n\s*---+\s*page\s*break\s*---+\s*\n)", text, flags=re.I)
        pages: list[DocumentPage] = []
        for index, raw_page in enumerate(raw_pages or [""], start=1):
            page_text = raw_page.strip()
            pages.append(
                DocumentPage(
                    page_number=index,
                    text=page_text,
                    spans=[DocumentSpan(text=page_text, page_number=index)] if page_text else [],
                    warnings=[],
                )
            )
        return pages or [DocumentPage(page_number=1, text="", warnings=["No text extracted."])]
