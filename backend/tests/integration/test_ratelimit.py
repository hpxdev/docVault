"""Per-client rate limits: headers, 429 envelope, groups, window reset, fail-open."""

import pytest
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.core import ratelimit
from app.core.config import get_settings
from app.db.session import sync_session
from app.models import Message
from tests import fixtures
from tests.conftest import run_queued


@pytest.fixture
def limits(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    def set_limits(ai: int = 20, upload: int = 30) -> None:
        monkeypatch.setattr(settings, "rate_limit_ai_per_minute", ai)
        monkeypatch.setattr(settings, "rate_limit_upload_per_minute", upload)

    return set_limits


async def _chat(client, enqueued):
    r = await client.post(
        "/documents", files=[("files", ("plan.pdf", fixtures.five_page_pdf(), "application/pdf"))]
    )
    doc = r.json()["results"][0]["document"]["id"]
    run_queued(enqueued)
    return (await client.post("/chat/sessions", json={"document_ids": [doc]})).json()["id"]


def _messages() -> int:
    with sync_session() as s:
        return s.scalar(select(func.count()).select_from(Message))


async def test_ai_limit_returns_429_before_anything_is_stored(client, enqueued, limits):
    limits(ai=2)
    sid = await _chat(client, enqueued)
    ask = {"content": "What is the approved budget?"}

    first = await client.post(f"/chat/sessions/{sid}/messages", json=ask)
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    second = await client.post(f"/chat/sessions/{sid}/messages/stream", json=ask)
    assert second.status_code == 200  # the streaming endpoint shares the "ai" group
    stored = _messages()

    third = await client.post(f"/chat/sessions/{sid}/messages", json=ask)
    assert third.status_code == 429
    error = third.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["details"]["group"] == "ai" and error["details"]["limit"] == 2
    assert 1 <= int(third.headers["retry-after"]) <= 60
    assert third.headers["x-ratelimit-remaining"] == "0"
    assert _messages() == stored  # rejected before the user message was saved

    # Other groups and read endpoints are unaffected.
    assert (await client.get(f"/chat/sessions/{sid}/messages")).status_code == 200
    up = await client.post("/documents", files=[("files", ("n.txt", b"notes", "text/plain"))])
    assert up.status_code == 202


async def test_upload_limit_and_window_reset(client, enqueued, limits, monkeypatch):
    limits(upload=1)
    now = 1_000_000_040.0  # 20 s into a one-minute window
    monkeypatch.setattr(ratelimit.time, "time", lambda: now)

    files = [("files", ("a.txt", b"first file", "text/plain"))]
    assert (await client.post("/documents", files=files)).status_code == 202
    blocked = await client.post(
        "/documents", files=[("files", ("b.txt", b"second file", "text/plain"))]
    )
    assert blocked.status_code == 429 and blocked.json()["error"]["details"]["group"] == "upload"
    assert blocked.headers["retry-after"] == "40"  # 20 s into the minute

    now += 40  # next window
    assert (
        await client.post("/documents", files=[("files", ("b.txt", b"second", "text/plain"))])
    ).status_code == 202


async def test_zero_or_disabled_means_no_limit(client, enqueued, limits, monkeypatch):
    limits(upload=0)
    for i in range(3):
        r = await client.post(
            "/documents", files=[("files", (f"{i}.txt", f"f{i}".encode(), "text/plain"))]
        )
        assert r.status_code == 202 and "x-ratelimit-limit" not in r.headers
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    limits(upload=1)
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    for i in range(3, 5):
        r = await client.post(
            "/documents", files=[("files", (f"{i}.txt", f"f{i}".encode(), "text/plain"))]
        )
        assert r.status_code == 202


async def test_redis_failure_allows_the_request(client, enqueued, limits, monkeypatch):
    limits(upload=1)

    class Broken:
        async def eval(self, *args, **kwargs):
            raise RedisError("down")

    monkeypatch.setattr(ratelimit, "async_cache", lambda: Broken())
    for i in range(3):
        r = await client.post(
            "/documents", files=[("files", (f"{i}.txt", f"f{i}".encode(), "text/plain"))]
        )
        assert r.status_code == 202
