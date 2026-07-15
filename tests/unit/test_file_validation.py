from pathlib import Path

from contractmate.security.file_validation import validate_uploaded_file


def test_validate_uploaded_file_rejects_mime_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "contract.pdf"
    path.write_text("plain contract text", encoding="utf-8")

    result = validate_uploaded_file(path, declared_mime_type="application/pdf", max_size_mb=1)

    assert not result.ok
    assert result.error_code == "MIME_MISMATCH"


def test_validate_uploaded_file_accepts_text(tmp_path: Path) -> None:
    path = tmp_path / "contract.txt"
    path.write_text("This SaaS Agreement is between Acme Ltd and Example Inc.", encoding="utf-8")

    result = validate_uploaded_file(path, declared_mime_type=None, max_size_mb=1)

    assert result.ok
    assert result.mime_type == "text/plain"
    assert result.sha256
