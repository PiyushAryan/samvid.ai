from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredDocument:
    object_key: str
    file_path: Path


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
