"""SSE chat stream: event order, persistence, scope errors before streaming, disconnects."""

import asyncio
import json
import uuid

from sqlalchemy import select

from app.ai.fakes import FakeChatModel
from app.db.session import sync_session
from app.models import AICall, Message
from tests import fixtures
from tests.conftest import run_queued

BUDGET_Q = "What is the approved budget for Project Falcon?"


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


async def _ready_session(client, enqueued):
    r = await client.post(
        "/documents", files=[("files", ("plan.pdf", fixtures.five_page_pdf(), "application/pdf"))]
    )
    doc = r.json()["results"][0]["document"]["id"]
    run_queued(enqueued)
    r = await client.post("/chat/sessions", json={"document_ids": [doc]})
    return r.json()["id"], doc


async def test_stream_event_order_and_persistence(client, enqueued):
    sid, doc = await _ready_session(client, enqueued)
    r = await client.post(f"/chat/sessions/{sid}/messages/stream", json={"content": BUDGET_Q})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [n for n, _ in events]
    assert names[0] == "meta" and names[-2:] == ["citations", "done"]
    assert set(names[1:-2]) == {"token"} and len(names) > 4

    meta = events[0][1]
    assert meta["ai_mode"] == "fake" and meta["standalone_query"] == BUDGET_Q
    streamed = "".join(d["delta"] for n, d in events if n == "token")
    done = events[-1][1]
    assert done["answer_status"] == "answered" and done["interrupted"] is False
    assert done["message"]["id"] == meta["assistant_message_id"]
    assert done["message"]["content"] == streamed.strip()
    assert events[-2][1]["citations"][0]["locator"] == {"type": "page", "page": 3}

    history = (await client.get(f"/chat/sessions/{sid}/messages")).json()["items"]
    assert [m["id"] for m in history] == [meta["user_message_id"], meta["assistant_message_id"]]
    assert history[1]["citations"][0]["excerpt"] == events[-2][1]["citations"][0]["excerpt"]
    assert history[1]["latency_ms"]["first_token"] is not None


async def test_stream_scope_error_is_plain_json_before_streaming(client, enqueued):
    r = await client.post("/chat/sessions", json={"document_ids": []})
    sid = r.json()["id"]
    r = await client.post(f"/chat/sessions/{sid}/messages/stream", json={"content": "hi"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "NO_DOCUMENTS_IN_SCOPE"
    missing = await client.post(
        f"/chat/sessions/{uuid.uuid4()}/messages/stream", json={"content": "hi"}
    )
    assert missing.status_code == 404


async def test_stream_ai_error_event(client, enqueued, fake_chat):
    from app.ai.errors import AIProviderUnavailable

    sid, _ = await _ready_session(client, enqueued)
    fake_chat.push(AIProviderUnavailable("OpenAI timed out"))
    r = await client.post(f"/chat/sessions/{sid}/messages/stream", json={"content": BUDGET_Q})
    events = parse_sse(r.text)
    assert [n for n, _ in events] == ["meta", "error"]
    err = events[-1][1]
    assert err["code"] == "AI_PROVIDER_UNAVAILABLE" and err["status"] == 503
    history = (await client.get(f"/chat/sessions/{sid}/messages")).json()["items"]
    assert history[-1]["answer_status"] == "error"


async def test_client_disconnect_stops_generation_and_saves_partial(client, enqueued):
    """Closing the response stream (what FastAPI does when the client goes away) sets the stop
    flag; the pipeline task stops at the next token and saves what it produced."""
    from app.ai import registry
    from app.api import chat as chat_api
    from app.db.session import async_session_factory
    from app.services.chat import prepare_ask

    sid, _ = await _ready_session(client, enqueued)
    words = " ".join(f"word{i}" for i in range(200))
    slow = FakeChatModel(script=[f"{words} [S1]."], delay=0.01)
    registry.set_overrides(chat=slow)

    async with async_session_factory()() as db:
        prep = await prepare_ask(db, uuid.UUID(sid), BUDGET_Q)
    stream = chat_api.ask_stream(prep)  # the endpoint's async generator, driven directly
    received = []
    async for sse in stream:
        received.append(sse.event)
        if received.count("token") == 5:
            break
    await stream.aclose()  # client disconnected
    await asyncio.wait_for(asyncio.gather(*list(chat_api._background)), timeout=10)

    with sync_session() as s:
        msg = s.scalars(
            select(Message).where(Message.session_id == uuid.UUID(sid), Message.role == "assistant")
        ).one()
        assert msg.interrupted is True
        assert 0 < len(msg.content.split()) < 200  # partial, not the full scripted answer
        assert msg.answer_status == "unsupported"  # the [S1] marker was never produced
        call = s.scalars(
            select(AICall).where(AICall.message_id == msg.id, AICall.purpose == "answer")
        ).one()
        assert call.status == "interrupted" and call.output_tokens > 0
