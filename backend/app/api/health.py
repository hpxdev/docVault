import asyncio
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.redis import HEARTBEAT_KEY, async_broker, async_cache
from app.db.session import get_async_engine

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def health() -> dict[str, str]:
    """Returns 200 while the API process is running. Does not check dependencies."""
    return {"status": "ok"}


async def _timed(coro: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout=3)
        result: dict[str, Any] = {"ok": True}
        if isinstance(detail, dict):
            result.update(detail)
    except Exception as exc:  # report, never raise: this is a diagnostics endpoint
        result = {"ok": False, "error": type(exc).__name__}
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


async def _check_db() -> dict[str, Any]:
    async with get_async_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
        version = await conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
    return {"pgvector": version}


async def _check_redis() -> None:
    await async_broker().ping()
    await async_cache().ping()


async def _check_worker() -> dict[str, Any]:
    value = await async_cache().get(HEARTBEAT_KEY)
    if not value:
        raise RuntimeError("no heartbeat")
    ident, _, ts = value.rpartition("@")
    return {"worker": ident, "last_heartbeat_age_s": max(0, int(time.time()) - int(ts))}


_READY_EXAMPLE = {
    "status": "ready",
    "checks": {
        "database": {"ok": True, "pgvector": "0.8.7", "latency_ms": 2.1},
        "redis": {"ok": True, "latency_ms": 0.9},
        "worker": {"ok": True, "worker": "a1b2c3:7", "last_heartbeat_age_s": 4},
        "ai": {
            "ok": True,
            "provider": "openai",
            "ai_mode": "openai",
            "chat_model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small",
            "key_present": True,
        },
    },
}


@router.get(
    "/health/ready",
    summary="Readiness: database, Redis, worker heartbeat, AI configuration",
    responses={
        200: {"content": {"application/json": {"example": _READY_EXAMPLE}}},
        503: {"description": "Database or Redis unavailable"},
    },
)
async def ready() -> JSONResponse:
    """`status` is `ready` when everything is healthy, `degraded` when the database and Redis are
    up but the worker heartbeat is missing or AI is not configured (`AI_NOT_CONFIGURED`), and
    `unavailable` (HTTP 503) when the database or Redis is down."""
    settings = get_settings()
    db, rds, worker = await asyncio.gather(
        _timed(_check_db()), _timed(_check_redis()), _timed(_check_worker())
    )
    ai: dict[str, Any] = {
        "ok": settings.ai_configured,
        "provider": settings.ai_provider,
        "ai_mode": settings.ai_mode,
        "chat_model": settings.chat_model_name,
        "embedding_model": settings.embedding_model_name,
        "key_present": settings.openai_api_key is not None,
    }
    if not settings.ai_configured:
        ai["error"] = "AI_NOT_CONFIGURED"
    checks = {"database": db, "redis": rds, "worker": worker, "ai": ai}
    if not (db["ok"] and rds["ok"]):
        status, code = "unavailable", 503
    elif not (worker["ok"] and ai["ok"]):
        status, code = "degraded", 200
    else:
        status, code = "ready", 200
    return JSONResponse(status_code=code, content={"status": status, "checks": checks})
