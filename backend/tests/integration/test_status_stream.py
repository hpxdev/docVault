"""Document status SSE: snapshot first, then live changes from the worker, then close."""

import asyncio
import uuid

from tests import fixtures
from tests.conftest import run_queued
from tests.integration.test_chat_stream import parse_sse


async def test_snapshot_then_live_events_until_settled(client, enqueued):
    r = await client.post(
        "/documents",
        files=[("files", ("plan.pdf", fixtures.five_page_pdf(), "application/pdf"))],
    )
    doc_id = r.json()["results"][0]["document"]["id"]
    missing = str(uuid.uuid4())

    request = asyncio.create_task(
        client.get(
            "/documents/events",
            params={"ids": f"{doc_id},{missing}", "close_when_settled": "true"},
        )
    )
    await asyncio.sleep(0.3)  # let the stream subscribe before the worker runs
    await asyncio.to_thread(run_queued, enqueued)  # worker publishes from another thread
    response = await asyncio.wait_for(request, timeout=15)

    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [n for n, _ in events]
    assert names[0] == "snapshot" and events[0][1]["status"] == "queued"
    assert ("not_found", {"id": missing}) in events
    statuses = [d for n, d in events if n == "status"]
    assert statuses, names
    assert statuses[0]["stages"]["extract"] == "running"
    assert statuses[-1]["status"] == "ready" and statuses[-1]["chat_ready"] is True
    seen = {(s["stages"]["index"], s["stages"]["insights"]) for s in statuses}
    assert ("succeeded", "succeeded") in seen


async def test_settled_documents_close_immediately_and_bad_ids_rejected(client, enqueued):
    r = await client.post(
        "/documents", files=[("files", ("bad.pdf", b"%PDF-1.4 broken", "application/pdf"))]
    )
    doc_id = r.json()["results"][0]["document"]["id"]
    run_queued(enqueued)
    response = await asyncio.wait_for(
        client.get("/documents/events", params={"ids": doc_id, "close_when_settled": "true"}),
        timeout=10,
    )
    events = parse_sse(response.text)
    assert [n for n, _ in events] == ["snapshot"]
    assert events[0][1]["error"]["code"] == "CORRUPT_DOCUMENT"

    r = await client.get("/documents/events", params={"ids": "not-a-uuid"})
    assert r.status_code == 422
