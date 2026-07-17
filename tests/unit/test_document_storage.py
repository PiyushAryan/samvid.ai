from pathlib import Path
from types import SimpleNamespace

from contractmate.tools.document_storage import VercelBlobDocumentStorage


class FakeBlobClient:
    objects: dict[str, bytes] = {}

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def upload_file(self, local_path, object_key, **options):
        self.objects[object_key] = Path(local_path).read_bytes()
        return SimpleNamespace(pathname=object_key)

    def get(self, object_key, **options):
        return SimpleNamespace(content=self.objects[object_key])

    def download_file(self, object_key, destination, **options):
        Path(destination).write_bytes(self.objects[object_key])

    def head(self, object_key):
        return SimpleNamespace(pathname=object_key, size=len(self.objects[object_key]), content_type="text/plain")

    def delete(self, object_key):
        self.objects.pop(object_key, None)

    def list_objects(self, **options):
        return SimpleNamespace(blobs=[])


def test_vercel_blob_storage_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("vercel.blob.BlobClient", FakeBlobClient)
    source = tmp_path / "agreement.txt"
    source.write_text("contract terms", encoding="utf-8")
    storage = VercelBlobDocumentStorage(token="blob-token")

    stored = storage.store_contract_file(source, workspace_id="workspace", sha256="ab" * 32)
    destination = tmp_path / "downloaded.txt"
    storage.download_contract_file(stored.object_key, destination)
    metadata = storage.stat_contract_file(stored.object_key)
    storage.check_ready()

    assert stored.object_key == f"contracts/workspace/ab/{'ab' * 32}.txt"
    assert storage.read_contract_file(stored.object_key) == b"contract terms"
    assert destination.read_bytes() == b"contract terms"
    assert metadata.size_bytes == len(b"contract terms")
    assert metadata.content_type == "text/plain"
