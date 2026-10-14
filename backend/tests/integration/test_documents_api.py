import uuid

from sqlalchemy import func, select

from app.db.session import sync_session
from app.models import Chunk, Document, DocumentSegment
from app.services import pipeline
from tests import fixtures
from tests.conftest import run_queued


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]["id"]


async def test_list_filters_and_pagination(client, enqueued):
    a = await _upload(client, "alpha-report.pdf", fixtures.five_page_pdf())
    b = await _upload(client, "beta_notes.txt", b"beta notes content here")
    c = await _upload(client, "gamma.md", fixtures.MARKDOWN.encode())
    pipeline.execute_stage("extract", b)
    with sync_session() as s:  # make one failed document
        d = s.get(Document, uuid.UUID(c))
        d.status, d.extract_status = "failed", "failed"
        s.commit()

    r = await client.get("/documents")
    body = r.json()
    assert body["total"] == 3 and body["limit"] == 20 and body["offset"] == 0
    assert [x["id"] for x in body["items"]] == [c, b, a]  # newest first

    page = (await client.get("/documents", params={"limit": 1, "offset": 1})).json()
    assert [x["id"] for x in page["items"]] == [b] and page["total"] == 3

    failed = (await client.get("/documents", params={"status": "failed"})).json()
    assert [x["id"] for x in failed["items"]] == [c]
    q = (await client.get("/documents", params={"q": "_NOTES"})).json()
    assert [x["id"] for x in q["items"]] == [b]  # case-insensitive; "_" matched literally
    assert (await client.get("/documents", params={"q": "%"})).json()["total"] == 0

    assert (await client.get("/documents", params={"limit": 101})).status_code == 422


async def test_detail_content_and_file(client, enqueued):
    pdf = fixtures.five_page_pdf()
    doc_id = await _upload(client, "plan.pdf", pdf)
    run_queued(enqueued)
    detail = (await client.get(f"/documents/{doc_id}")).json()
    assert detail["stages"]["extract"] == "succeeded"
    assert detail["stages"]["index"] == "succeeded"
    assert detail["chat_ready"] is True and detail["page_count"] == 5

    content = await client.get(f"/documents/{doc_id}/content", params={"limit": 2, "offset": 2})
    body = content.json()
    assert body["total"] == 5 and len(body["items"]) == 2
    assert body["items"][0]["locator"] == {"type": "page", "page": 3}
    assert "4.2 million" in body["items"][0]["text"]

    f = await client.get(f"/documents/{doc_id}/file")
    assert f.status_code == 200 and f.content == pdf
    assert f.headers["content-type"] == "application/pdf"
    assert "plan.pdf" in f.headers["content-disposition"]


async def test_unknown_document_is_404_envelope(client):
    missing = uuid.uuid4()
    for path in ("", "/content", "/file"):
        r = await client.get(f"/documents/{missing}{path}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert (await client.get("/documents/not-a-uuid")).status_code == 422


async def test_reprocess_rules(client, enqueued):
    doc_id = await _upload(client, "notes.txt", b"plain text for reprocessing tests")
    r = await client.post(f"/documents/{doc_id}/reprocess")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_PROCESSING"

    with sync_session() as s:  # simulate: extract ok, index failed, insights ok
        d = s.get(Document, uuid.UUID(doc_id))
        d.extract_status, d.index_status, d.insights_status = "succeeded", "failed", "succeeded"
        d.status, d.error_code = "partial", "AI_PROVIDER_UNAVAILABLE"
        s.commit()
    enqueued.clear()
    r = await client.post(f"/documents/{doc_id}/reprocess")
    assert r.status_code == 202
    assert r.json()["stages"] == ["index"]
    assert r.json()["document"]["stages"] == {
        "extract": "succeeded",
        "index": "pending",
        "insights": "succeeded",
    }
    assert r.json()["document"]["error"] is None
    assert enqueued == [("index", doc_id)]

    with sync_session() as s:
        d = s.get(Document, uuid.UUID(doc_id))
        d.index_status, d.status = "succeeded", "ready"
        s.commit()
    r = await client.post(f"/documents/{doc_id}/reprocess")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTHING_TO_REPROCESS"
    r = await client.post(f"/documents/{doc_id}/reprocess", params={"stages": "bogus"})
    assert r.status_code == 422
    enqueued.clear()
    r = await client.post(f"/documents/{doc_id}/reprocess", params={"stages": "extract"})
    assert r.json()["stages"] == ["extract", "index", "insights"]
    assert enqueued == [("extract", doc_id)]


async def test_delete_removes_file_segments_and_chunks(client, enqueued):
    from app.services.storage import get_storage

    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    with sync_session() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        key = doc.storage_path
    assert get_storage().exists(key)

    r = await client.delete(f"/documents/{doc_id}")
    assert r.status_code == 204
    assert not get_storage().exists(key)
    with sync_session() as s:
        for model in (DocumentSegment, Chunk):
            n = s.scalar(select(func.count()).where(model.document_id == uuid.UUID(doc_id)))
            assert n == 0
    assert (await client.get(f"/documents/{doc_id}")).status_code == 404
    assert (await client.delete(f"/documents/{doc_id}")).status_code == 404
