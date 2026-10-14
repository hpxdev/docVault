from app.core.config import get_settings
from tests import fixtures


def _files(*items):
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


async def test_accepts_file_and_enqueues_extract_after_commit(client, enqueued):
    r = await client.post("/documents", files=_files(("plan.pdf", fixtures.five_page_pdf())))
    assert r.status_code == 202
    body = r.json()
    assert body["accepted"] == 1
    result = body["results"][0]
    assert result["outcome"] == "accepted" and result["duplicate"] is False
    doc = result["document"]
    assert doc["status"] == "queued" and doc["file_type"] == "pdf"
    assert doc["stages"] == {"extract": "pending", "index": "pending", "insights": "pending"}
    assert enqueued == [("extract", doc["id"])]
    # The row was committed before enqueueing: it is visible to a fresh request.
    assert (await client.get(f"/documents/{doc['id']}")).status_code == 200


async def test_mixed_outcomes_and_duplicates(client, enqueued):
    pdf = fixtures.five_page_pdf()
    r = await client.post(
        "/documents",
        files=_files(
            ("plan.pdf", pdf),
            ("plan-copy.pdf", pdf),  # same bytes in the same request
            ("setup.exe", b"MZ\x90\x00" + bytes(range(256)) * 8),
            ("empty.txt", b""),
        ),
    )
    assert r.status_code == 202
    results = r.json()["results"]
    assert [x["outcome"] for x in results] == ["accepted", "duplicate", "rejected", "rejected"]
    assert results[1]["duplicate"] is True
    assert results[1]["document"]["id"] == results[0]["document"]["id"]
    assert results[2]["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert results[3]["error"]["code"] == "EMPTY_FILE"
    assert len(enqueued) == 1  # no reprocessing for the duplicate

    again = await client.post("/documents", files=_files(("again.pdf", pdf)))
    assert again.json()["results"][0]["outcome"] == "duplicate"
    assert len(enqueued) == 1


async def test_renamed_executable_is_rejected_by_content(client):
    r = await client.post("/documents", files=_files(("report.pdf", b"MZ\x90\x00" * 100)))
    assert r.status_code == 415
    body = r.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert body["error"]["details"]["results"][0]["outcome"] == "rejected"


async def test_all_rejected_with_mixed_codes_is_400(client):
    r = await client.post("/documents", files=_files(("a.txt", b""), ("b.bin", b"\x00\x01" * 50)))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UPLOAD_REJECTED"


async def test_empty_file_alone_is_400(client):
    r = await client.post("/documents", files=_files(("a.txt", b"")))
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_FILE"


async def test_file_too_large(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = b"a" * (1024 * 1024 + 10)
    r = await client.post("/documents", files=_files(("big.txt", big), ("ok.txt", b"small file")))
    assert r.status_code == 202
    outcomes = [(x["outcome"], (x["error"] or {}).get("code")) for x in r.json()["results"]]
    assert outcomes == [("rejected", "FILE_TOO_LARGE"), ("accepted", None)]

    r = await client.post("/documents", files=_files(("big.txt", big)))
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_too_many_files(client, enqueued):
    files = _files(*[(f"f{i}.txt", f"file number {i}".encode()) for i in range(11)])
    r = await client.post("/documents", files=files)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TOO_MANY_FILES"
    assert enqueued == []


async def test_missing_files_field_is_validation_error(client):
    r = await client.post("/documents", data={"x": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_filename_path_is_stripped(client):
    r = await client.post("/documents", files=_files(("../../etc/evil.txt", b"hello there")))
    assert r.json()["results"][0]["document"]["filename"] == "evil.txt"


def test_safe_filename():
    from app.services.upload import safe_filename

    assert safe_filename("..\\..\\evil\x07.txt") == "evil.txt"
    assert safe_filename("") == "upload"
    assert len(safe_filename("a" * 300 + ".txt")) == 255
