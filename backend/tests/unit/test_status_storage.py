import uuid

import pytest

from app.services.status import derive_status
from app.services.storage import LocalStorage


@pytest.mark.parametrize(
    ("extract", "index", "insights", "expected"),
    [
        ("pending", "pending", "pending", "queued"),
        ("running", "pending", "pending", "processing"),
        ("succeeded", "pending", "pending", "processing"),
        ("succeeded", "running", "succeeded", "processing"),
        ("succeeded", "succeeded", "succeeded", "ready"),
        ("succeeded", "succeeded", "failed", "partial"),
        ("succeeded", "failed", "succeeded", "partial"),
        ("succeeded", "failed", "failed", "failed"),
        ("failed", "pending", "pending", "failed"),
        ("succeeded", "failed", "running", "processing"),
    ],
)
def test_derive_status(extract, index, insights, expected):
    assert derive_status(extract, index, insights) == expected


def test_local_storage_round_trip(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    doc_id = uuid.uuid4()
    src = storage.temp_dir() / "incoming"
    src.write_bytes(b"hello")
    key = storage.save(doc_id, "txt", src)
    assert key == f"{doc_id}/original.txt"
    assert not src.exists()
    assert storage.exists(key)
    with storage.open(key) as f:
        assert f.read() == b"hello"
    storage.delete_document(doc_id)
    assert not storage.exists(key)


def test_local_storage_rejects_path_escape(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    with pytest.raises(ValueError):
        storage.local_path("../../etc/passwd")
