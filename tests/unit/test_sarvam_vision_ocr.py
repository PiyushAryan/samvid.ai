import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter

from contractmate.ocr.base import OCRProcessingError
from contractmate.ocr.sarvam_vision import SarvamVisionOCR, parse_sarvam_output_archive
from contractmate.schemas.documents import DocumentPage, ParsedDocument


def test_parse_sarvam_output_archive_normalizes_page_json(tmp_path: Path) -> None:
    archive_path = tmp_path / "output.zip"
    payload = {
        "pages": [
            {"page_number": 1, "markdown": "# Agreement\nFirst page text."},
            {"page_number": 2, "content": "Second page text.", "tables": [{"rows": [["A", "B"]]}]},
        ]
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("document.json", json.dumps(payload))

    pages = parse_sarvam_output_archive(archive_path, page_offset=10)

    assert [page.page_number for page in pages] == [11, 12]
    assert pages[0].text == "# Agreement\nFirst page text."
    assert pages[1].tables == [{"rows": [["A", "B"]]}]


def test_sarvam_ocr_splits_large_pdf_and_restores_page_numbers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned-contract.pdf"
    writer = PdfWriter()
    for _ in range(11):
        writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as output:
        writer.write(output)

    jobs: list[_FakeJob] = []

    def client_factory(**kwargs):
        assert kwargs == {"api_subscription_key": "sarvam-key"}
        return _FakeClient(jobs)

    parsed = _ocr_required_document()
    result = SarvamVisionOCR(api_key="sarvam-key", client_factory=client_factory).extract(
        pdf_path,
        parsed_document=parsed,
    )

    assert len(jobs) == 2
    assert result.page_count == 11
    assert [page.page_number for page in result.pages] == list(range(1, 12))
    assert result.pages[-1].text == "OCR text for local page 1."
    assert result.requires_ocr is False


def test_sarvam_ocr_rejects_partial_results(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned-contract.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as output:
        writer.write(output)

    job = _FakeJob(state="PartiallyCompleted")

    with pytest.raises(OCRProcessingError, match="did not complete successfully"):
        SarvamVisionOCR(
            api_key="sarvam-key",
            client_factory=lambda **kwargs: _FakeClient([job], fixed_job=job),
        ).extract(pdf_path, parsed_document=_ocr_required_document())


def test_sarvam_ocr_processes_chunks_concurrently_and_preserves_page_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned-contract.pdf"
    writer = PdfWriter()
    for _ in range(21):
        writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as output:
        writer.write(output)

    tracker = _ConcurrencyTracker()
    result = SarvamVisionOCR(
        api_key="sarvam-key",
        max_concurrency=2,
        client_factory=lambda **_kwargs: _ConcurrentFakeClient(tracker),
    ).extract(pdf_path, parsed_document=_ocr_required_document())

    assert tracker.max_active == 2
    assert [page.page_number for page in result.pages] == list(range(1, 22))


class _FakeClient:
    def __init__(self, jobs: list["_FakeJob"], *, fixed_job: "_FakeJob | None" = None) -> None:
        self.document_intelligence = self
        self.jobs = jobs
        self.fixed_job = fixed_job

    def create_job(self, *, language: str, output_format: str) -> "_FakeJob":
        assert language == "en-IN"
        assert output_format == "md"
        if self.fixed_job is not None:
            return self.fixed_job
        job = _FakeJob()
        self.jobs.append(job)
        return job


class _FakeJob:
    def __init__(self, *, state: str = "Completed") -> None:
        self.state = state
        self.page_count = 0

    def upload_file(self, file_path: str) -> None:
        self.page_count = len(PdfReader(file_path).pages)

    def start(self) -> None:
        return None

    def wait_until_complete(self, *, timeout: float):
        assert timeout == 600.0
        return SimpleNamespace(job_state=self.state, error_message="partial OCR" if self.state != "Completed" else "")

    def download_output(self, output_path: str) -> None:
        payload = {
            "pages": [
                {"page_number": page_number, "text": f"OCR text for local page {page_number}."}
                for page_number in range(1, self.page_count + 1)
            ]
        }
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.writestr("result.json", json.dumps(payload))


class _ConcurrencyTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0


class _ConcurrentFakeClient:
    def __init__(self, tracker: _ConcurrencyTracker) -> None:
        self.document_intelligence = self
        self.tracker = tracker

    def create_job(self, *, language: str, output_format: str) -> "_ConcurrentFakeJob":
        assert language == "en-IN"
        assert output_format == "md"
        return _ConcurrentFakeJob(self.tracker)


class _ConcurrentFakeJob(_FakeJob):
    def __init__(self, tracker: _ConcurrencyTracker) -> None:
        super().__init__()
        self.tracker = tracker

    def wait_until_complete(self, *, timeout: float):
        with self.tracker.lock:
            self.tracker.active += 1
            self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
        try:
            time.sleep(0.02)
        finally:
            with self.tracker.lock:
                self.tracker.active -= 1
        return super().wait_until_complete(timeout=timeout)


def _ocr_required_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="contract-1",
        sha256="abc123",
        mime_type="application/pdf",
        page_count=1,
        pages=[DocumentPage(page_number=1, text="")],
        parser_name="pdfmuse",
        parser_version="test",
        requires_ocr=True,
    )
