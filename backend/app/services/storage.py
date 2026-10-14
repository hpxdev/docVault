"""File storage behind a small interface so S3-compatible storage can be dropped in later."""

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def save(self, document_id: uuid.UUID, ext: str, source: Path) -> str:
        """Move `source` into storage; return the storage key."""

    def open(self, key: str) -> BinaryIO: ...

    def local_path(self, key: str) -> Path:
        """Path readable by parsers (a local cache copy for remote backends)."""

    def exists(self, key: str) -> bool: ...

    def delete_document(self, document_id: uuid.UUID) -> None: ...

    def temp_dir(self) -> Path:
        """Scratch directory on the same filesystem, so `save` can be a rename."""


class LocalStorage:
    """Stores files at `{root}/{document_id}/original.{ext}`."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage key escapes the storage root")
        return path

    def save(self, document_id: uuid.UUID, ext: str, source: Path) -> str:
        key = f"{document_id}/original.{ext}"
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), dest)
        return key

    def open(self, key: str) -> BinaryIO:
        return self._resolve(key).open("rb")

    def local_path(self, key: str) -> Path:
        return self._resolve(key)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete_document(self, document_id: uuid.UUID) -> None:
        shutil.rmtree(self._resolve(str(document_id)), ignore_errors=True)

    def temp_dir(self) -> Path:
        tmp = self.root / ".tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp


def get_storage() -> Storage:
    return LocalStorage(get_settings().storage_dir)
