"""Monitoring aggregates. Every rate carries its numerator and denominator so it can be checked;
percentiles use Postgres `percentile_cont`. Cost figures are estimates from `ai_calls`."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import async_broker, async_cache
from app.models import (
    AICall,
    Chunk,
    Document,
    DocumentInsights,
    Message,
    MessageCitation,
    ProcessingRun,
)
from app.services.cache import METRICS_PREFIX, METRICS_TTL_S
from app.services.status import STAGES

log = logging.getLogger(__name__)

WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "all": None,
}
QUEUES = ("ingest", "ai")


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else None
    return {"value": value, "numerator": numerator, "denominator": denominator}


def _pct(column, q: float):
    return func.percentile_cont(q).within_group(column)


def _ms(value: Any) -> float | None:
    return None if value is None else round(float(value), 1)


async def _cached(key: str, build) -> dict[str, Any]:
    cache = async_cache()
    try:
        hit = await cache.get(key)
    except Exception:
        hit = None
    if hit:
        return {**json.loads(hit), "cached": True}
    body = await build()
    try:
        await cache.set(key, json.dumps(body, default=str), ex=METRICS_TTL_S)
    except Exception:
        log.warning("metrics cache write failed")
    return {**body, "cached": False}


# ---------------------------------------------------------------- documents


async def document_metrics(db: AsyncSession) -> dict[str, Any]:
    return await _cached(f"{METRICS_PREFIX}documents", lambda: _document_metrics(db))


async def _document_metrics(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    by_status = dict(
        (await db.execute(select(Document.status, func.count()).group_by(Document.status))).all()
    )
    by_type = dict(
        (
            await db.execute(select(Document.file_type, func.count()).group_by(Document.file_type))
        ).all()
    )
    totals = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Document.index_status == "succeeded"),
                func.coalesce(func.sum(Document.size_bytes), 0),
                func.coalesce(func.sum(Document.page_count), 0),
                func.count(Document.page_count),
            )
        )
    ).one()
    total, chat_ready, total_bytes, total_pages, docs_with_pages = totals
    total_chunks = await db.scalar(select(func.count()).select_from(Chunk))

    start_day = (now - timedelta(days=13)).date()
    day = func.date(func.timezone("UTC", Document.created_at))
    rows = (
        await db.execute(
            select(day, func.count())
            .where(Document.created_at >= datetime.combine(start_day, datetime.min.time(), UTC))
            .group_by(day)
        )
    ).all()
    per_day = {d: n for d, n in rows}
    uploads = [
        {
            "date": (start_day + timedelta(days=i)).isoformat(),
            "count": per_day.get(start_day + timedelta(days=i), 0),
        }
        for i in range(14)
    ]

    newest_first = func.row_number().over(
        partition_by=DocumentInsights.document_id, order_by=DocumentInsights.created_at.desc()
    )
    ranked = select(
        DocumentInsights.category, DocumentInsights.tags, newest_first.label("rn")
    ).subquery()
    latest = select(ranked.c.category, ranked.c.tags).where(ranked.c.rn == 1).subquery()
    categories = (
        await db.execute(
            select(latest.c.category, func.count())
            .group_by(latest.c.category)
            .order_by(func.count().desc(), latest.c.category)
            .limit(10)
        )
    ).all()
    tag = func.unnest(latest.c.tags).label("tag")
    tag_rows = (
        await db.execute(
            select(tag, func.count())
            .select_from(latest)
            .group_by(tag)
            .order_by(func.count().desc(), tag)
            .limit(10)
        )
    ).all()

    return {
        "generated_at": now.isoformat(),
        "documents": {
            "total": total,
            "by_status": by_status,
            "by_file_type": by_type,
            "chat_ready": chat_ready,
        },
        "content": {
            "total_pages": int(total_pages),
            "total_chunks": total_chunks or 0,
            "total_bytes": int(total_bytes),
            "average_pages": rate(int(total_pages), docs_with_pages),
        },
        "uploads_per_day": uploads,
        "top_categories": [{"category": c, "count": n} for c, n in categories],
        "top_tags": [{"tag": t, "count": n} for t, n in tag_rows],
        "notes": {
            "average_pages": "Over documents with pages (PDF); DOCX/TXT/MD have no pages.",
        },
    }


# ---------------------------------------------------------------- processing / AI / chat


async def processing_metrics(db: AsyncSession, window: str) -> dict[str, Any]:
    return await _cached(f"{METRICS_PREFIX}processing:{window}", lambda: _processing(db, window))


async def _queue_depths() -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for q in QUEUES:
        try:
            out[q] = int(await async_broker().llen(q))
        except Exception:
            out[q] = None
    return out


async def _processing(db: AsyncSession, window: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    span = WINDOWS[window]
    since = now - span if span else None

    def in_window(column):
        return column >= since if since is not None else True

    stages: dict[str, Any] = {}
    run_rows = (
        await db.execute(
            select(
                ProcessingRun.stage,
                func.count(),
                func.count().filter(ProcessingRun.status == "succeeded"),
                func.count().filter(ProcessingRun.status == "failed"),
                func.count().filter(ProcessingRun.status == "retrying"),
                func.count().filter(ProcessingRun.status == "running"),
                func.count().filter(ProcessingRun.attempt > 1),
                _pct(ProcessingRun.duration_ms, 0.5).filter(ProcessingRun.finished_at.is_not(None)),
                _pct(ProcessingRun.duration_ms, 0.95).filter(
                    ProcessingRun.finished_at.is_not(None)
                ),
                func.count(ProcessingRun.duration_ms),
            )
            .where(in_window(ProcessingRun.started_at))
            .group_by(ProcessingRun.stage)
        )
    ).all()
    failure_rows = (
        await db.execute(
            select(ProcessingRun.stage, ProcessingRun.error_code, func.count())
            .where(in_window(ProcessingRun.started_at), ProcessingRun.status == "failed")
            .group_by(ProcessingRun.stage, ProcessingRun.error_code)
        )
    ).all()
    by_stage = {r[0]: r for r in run_rows}
    for stage in STAGES:
        r = by_stage.get(stage)
        started, ok, failed, retrying, running, retries, p50, p95, n = (
            r[1:] if r else (0, 0, 0, 0, 0, 0, None, None, 0)
        )
        stages[stage] = {
            "started": started,
            "succeeded": ok,
            "failed": failed,
            "retry_scheduled": retrying,
            "running": running,
            "success_rate": rate(ok, ok + failed),
            "duration_ms": {"p50": _ms(p50), "p95": _ms(p95), "count": n},
            "retries": retries,
            "failures_by_code": {
                code or "UNKNOWN": cnt for s, code, cnt in failure_rows if s == stage
            },
        }

    ready_ms = func.extract("epoch", Document.chat_ready_at - Document.created_at) * 1000
    e2e = (
        await db.execute(
            select(_pct(ready_ms, 0.5), _pct(ready_ms, 0.95), func.count()).where(
                Document.chat_ready_at.is_not(None), in_window(Document.chat_ready_at)
            )
        )
    ).one()

    ai_rows = (
        await db.execute(
            select(
                AICall.purpose,
                AICall.model,
                func.count(),
                func.count().filter(AICall.status == "failed"),
                func.coalesce(func.sum(AICall.input_tokens), 0),
                func.coalesce(func.sum(AICall.output_tokens), 0),
                func.coalesce(func.sum(AICall.estimated_cost_usd), 0),
            )
            .where(in_window(AICall.created_at))
            .group_by(AICall.purpose, AICall.model)
            .order_by(AICall.purpose, AICall.model)
        )
    ).all()
    calls = sum(r[2] for r in ai_rows)
    errors = sum(r[3] for r in ai_rows)
    all_time_spend = await db.scalar(select(func.coalesce(func.sum(AICall.estimated_cost_usd), 0)))

    chat_row = (
        await db.execute(
            select(
                func.count().filter(Message.role == "user"),
                func.count().filter(Message.role == "assistant"),
                func.count().filter(Message.answer_status == "answered"),
                func.count().filter(Message.answer_status == "not_found"),
                func.count().filter(Message.answer_status == "unsupported"),
                func.count().filter(Message.answer_status == "error"),
                func.count().filter(Message.interrupted.is_(True)),
            ).where(in_window(Message.created_at))
        )
    ).one()
    questions, assistant, answered, not_found, unsupported, errored, interrupted = chat_row
    lat = (
        await db.execute(
            select(
                _pct(Message.first_token_ms, 0.5),
                _pct(Message.first_token_ms, 0.95),
                func.count(Message.first_token_ms),
                _pct(Message.total_ms, 0.5),
                _pct(Message.total_ms, 0.95),
                func.count(Message.total_ms),
            ).where(
                Message.role == "assistant",
                Message.answer_status != "error",
                in_window(Message.created_at),
            )
        )
    ).one()
    citation_count = await _citations_in_answers(db, since)

    return {
        "window": window,
        "since": since.isoformat() if since else None,
        "generated_at": now.isoformat(),
        "stages": stages,
        "upload_to_chat_ready_ms": {"p50": _ms(e2e[0]), "p95": _ms(e2e[1]), "count": e2e[2]},
        "queues": await _queue_depths(),
        "ai": {
            "calls": calls,
            "errors": errors,
            "error_rate": rate(errors, calls),
            "input_tokens": int(sum(r[4] for r in ai_rows)),
            "output_tokens": int(sum(r[5] for r in ai_rows)),
            "estimated_cost_usd": float(sum(r[6] for r in ai_rows)),
            "by_purpose_and_model": [
                {
                    "purpose": r[0],
                    "model": r[1],
                    "calls": r[2],
                    "errors": r[3],
                    "input_tokens": int(r[4]),
                    "output_tokens": int(r[5]),
                    "estimated_cost_usd": float(r[6]),
                }
                for r in ai_rows
            ],
            "spend_limit_usd": get_settings().ai_spend_limit_usd,
            "estimated_spend_all_time_usd": float(all_time_spend or 0),
            "note": "Costs are estimates from token counts and app/ai/pricing.py, not invoices.",
        },
        "chat": {
            "questions": questions,
            "assistant_messages": assistant,
            "answered": answered,
            "not_found_rate": rate(not_found, assistant),
            "unsupported_rate": rate(unsupported, assistant),
            "error_rate": rate(errored, assistant),
            "interrupted": interrupted,
            "first_token_ms": {"p50": _ms(lat[0]), "p95": _ms(lat[1]), "count": lat[2]},
            "total_ms": {"p50": _ms(lat[3]), "p95": _ms(lat[4]), "count": lat[5]},
            "avg_citations_per_answer": rate(citation_count, answered),
        },
    }


async def _citations_in_answers(db: AsyncSession, since: datetime | None) -> int:
    stmt = (
        select(func.count())
        .select_from(MessageCitation)
        .join(Message, Message.id == MessageCitation.message_id)
        .where(Message.answer_status == "answered")
    )
    if since is not None:
        stmt = stmt.where(Message.created_at >= since)
    return int(await db.scalar(stmt) or 0)
