import json
import logging

import redis

from app.core.config import get_settings
from app.core.logging import JsonFormatter
from app.core.redis import HEARTBEAT_KEY


async def test_liveness_and_request_id_header(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert len(r.headers["x-request-id"]) == 32

    r = await client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/nope", headers={"X-Request-ID": "abc"})
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["request_id"] == "abc"
    assert set(body["error"]) == {"code", "message", "details"}


async def test_ready_degraded_without_worker_heartbeat(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] and body["checks"]["redis"]["ok"]
    assert body["checks"]["worker"]["ok"] is False
    assert body["checks"]["ai"]["ai_mode"] == "fake"


async def test_ready_when_worker_heartbeat_present(client):
    redis.Redis.from_url(get_settings().cache_redis_url).set(HEARTBEAT_KEY, "w:1@1", ex=30)
    r = await client.get("/health/ready")
    assert r.json()["status"] == "ready"
    assert r.json()["checks"]["worker"]["worker"] == "w:1"


async def test_ready_fails_when_redis_down(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(settings, "cache_redis_url", "redis://127.0.0.1:1/1")
    r = await client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"
    assert r.json()["checks"]["redis"]["ok"] is False


async def test_ready_reports_ai_not_configured(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    body = (await client.get("/health/ready")).json()
    assert body["checks"]["ai"]["ok"] is False
    assert body["checks"]["ai"]["error"] == "AI_NOT_CONFIGURED"
    assert body["status"] == "degraded"


def test_json_formatter_emits_ids_and_no_unknown_extras():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "stage done", None, None)
    record.document_id = "d1"
    record.stage = "extract"
    record.duration_ms = 12
    record.secret_text = "should not appear"
    line = json.loads(JsonFormatter().format(record))
    assert line["document_id"] == "d1" and line["stage"] == "extract"
    assert "secret_text" not in line
