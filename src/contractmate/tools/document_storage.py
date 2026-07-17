from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredDocument:
    object_key: str
    file_path: Path


@dataclass(frozen=True)
class DocumentMetadata:
    object_key: str
    size_bytes: int
    content_type: str | None


class DocumentStorage(Protocol):
    def store_contract_file(self, source_path: Path, *, workspace_id: str, sha256: str) -> StoredDocument: ...

    def read_contract_file(self, object_key: str) -> bytes: ...

    def download_contract_file(self, object_key: str, destination: Path) -> None: ...

    def stat_contract_file(self, object_key: str) -> DocumentMetadata: ...

    def delete_contract_file(self, object_key: str) -> None: ...

    def check_ready(self) -> None: ...


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def store_contract_file(self, source_path: Path, *, workspace_id: str, sha256: str) -> StoredDocument:
        destination_dir = self.root / workspace_id / sha256[:2]
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{sha256}{source_path.suffix.lower()}"
        if not destination.exists():
            shutil.copy2(source_path, destination)
        object_key = str(destination.relative_to(self.root))
        return StoredDocument(object_key=object_key, file_path=destination)

    def read_contract_file(self, object_key: str) -> bytes:
        path = self._resolve_object_key(object_key)
        return path.read_bytes()

    def download_contract_file(self, object_key: str, destination: Path) -> None:
        source = self._resolve_object_key(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def stat_contract_file(self, object_key: str) -> DocumentMetadata:
        path = self._resolve_object_key(object_key)
        return DocumentMetadata(object_key=object_key, size_bytes=path.stat().st_size, content_type=None)

    def delete_contract_file(self, object_key: str) -> None:
        self._resolve_object_key(object_key).unlink(missing_ok=True)

    def check_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.root / ".samvid-ready"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)

    def _resolve_object_key(self, object_key: str) -> Path:
        root = self.root.resolve()
        path = (root / object_key).resolve()
        if path != root and root not in path.parents:
            raise FileNotFoundError(object_key)
        if not path.is_file():
            raise FileNotFoundError(object_key)
        return path


class VercelBlobDocumentStorage:
    def __init__(self, token: str | None = None) -> None:
        from vercel.blob import BlobClient

        self.client = BlobClient(token=token)

    def store_contract_file(self, source_path: Path, *, workspace_id: str, sha256: str) -> StoredDocument:
        suffix = source_path.suffix.lower()
        object_key = f"contracts/{workspace_id}/{sha256[:2]}/{sha256}{suffix}"
        result = self.client.upload_file(
            source_path,
            object_key,
            access="private",
            overwrite=True,
            multipart=source_path.stat().st_size > 5 * 1024 * 1024,
        )
        return StoredDocument(object_key=result.pathname, file_path=source_path)

    def read_contract_file(self, object_key: str) -> bytes:
        return self.client.get(object_key, access="private", timeout=60).content

    def download_contract_file(self, object_key: str, destination: Path) -> None:
        self.client.download_file(
            object_key,
            destination,
            access="private",
            timeout=60,
            overwrite=True,
            create_parents=True,
        )

    def stat_contract_file(self, object_key: str) -> DocumentMetadata:
        result = self.client.head(object_key)
        return DocumentMetadata(
            object_key=result.pathname,
            size_bytes=result.size,
            content_type=result.content_type,
        )

    def delete_contract_file(self, object_key: str) -> None:
        self.client.delete(object_key)

    def check_ready(self) -> None:
        self.client.list_objects(limit=1)


def document_storage_from_settings(settings) -> DocumentStorage:
    if settings.document_storage_backend == "vercel_blob":
        return VercelBlobDocumentStorage(token=settings.blob_read_write_token)
    return LocalDocumentStorage(settings.local_storage_dir)
