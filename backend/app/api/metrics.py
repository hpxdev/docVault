from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.metrics import document_metrics, processing_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])
DB = Annotated[AsyncSession, Depends(get_db)]

_DOC_EXAMPLE = {
    "generated_at": "2026-10-15T10:00:00+00:00",
    "cached": False,
    "documents": {
        "total": 12,
        "by_status": {"ready": 9, "failed": 2, "partial": 1},
        "by_file_type": {"pdf": 8, "docx": 2, "md": 1, "txt": 1},
        "chat_ready": 10,
    },
    "content": {
        "total_pages": 640,
        "total_chunks": 702,
        "total_bytes": 18350412,
        "average_pages": {"value": 80.0, "numerator": 640, "denominator": 8},
    },
    "uploads_per_day": [{"date": "2026-10-15", "count": 12}],
    "top_categories": [{"category": "report", "count": 5}],
    "top_tags": [{"tag": "budget", "count": 3}],
}

_PROC_EXAMPLE = {
    "window": "24h",
    "cached": False,
    "stages": {
        "extract": {
            "started": 12,
            "succeeded": 10,
            "failed": 2,
            "retry_scheduled": 0,
            "running": 0,
            "success_rate": {"value": 0.8333, "numerator": 10, "denominator": 12},
            "duration_ms": {"p50": 120.0, "p95": 840.5, "count": 12},
            "retries": 0,
            "failures_by_code": {"ENCRYPTED_DOCUMENT": 1, "NO_EXTRACTABLE_TEXT": 1},
        }
    },
    "upload_to_chat_ready_ms": {"p50": 4200.0, "p95": 15800.0, "count": 10},
    "queues": {"ingest": 0, "ai": 0},
    "ai": {
        "calls": 58,
        "errors": 1,
        "error_rate": {"value": 0.0172, "numerator": 1, "denominator": 58},
        "estimated_cost_usd": 0.0213,
        "by_purpose_and_model": [{"purpose": "answer", "model": "gpt-4o-mini", "calls": 9}],
    },
    "chat": {
        "questions": 9,
        "not_found_rate": {"value": 0.1111, "numerator": 1, "denominator": 9},
        "first_token_ms": {"p50": 650.0, "p95": 1400.0, "count": 9},
        "avg_citations_per_answer": {"value": 1.75, "numerator": 14, "denominator": 8},
    },
}


@router.get(
    "/documents",
    summary="Document statistics",
    responses={200: {"content": {"application/json": {"example": _DOC_EXAMPLE}}}},
)
async def get_document_metrics(db: DB):
    """Counts by status and type, chat-ready count, pages/chunks/bytes, uploads per day (last 14
    days, UTC), top categories and tags. Cached for 15 s (`cached: true`)."""
    return await document_metrics(db)


@router.get(
    "/processing",
    summary="Processing, AI usage and chat metrics",
    responses={200: {"content": {"application/json": {"example": _PROC_EXAMPLE}}}},
)
async def get_processing_metrics(
    db: DB,
    window: Annotated[Literal["1h", "24h", "7d", "all"], Query()] = "24h",
):
    """Per stage: started/succeeded/failed, `success_rate = succeeded / (succeeded + failed)`
    (running and retry-scheduled runs reported separately), p50/p95 duration, retries (runs with
    attempt > 1), failures by code. Also p50/p95 upload → chat-ready time, queue depth, AI calls,
    tokens and **estimated** cost by purpose and model, and chat answer rates and latencies.
    Every rate includes numerator and denominator. Cached for 15 s."""
    return await processing_metrics(db, window)
