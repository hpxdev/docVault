"""Document status derivation and the status-event payload shared by the worker and the API."""

from typing import Any

from app.models import Document

STAGES = ("extract", "index", "insights")
STAGE_COLUMN = {"extract": "extract_status", "index": "index_status", "insights": "insights_status"}

# Stage statuses: pending | running | retrying | succeeded | failed
ACTIVE = ("pending", "running", "retrying")


def derive_status(extract: str, index: str, insights: str) -> str:
    """Overall document status (MASTER_PROMPT §4 "Readiness").

    - failed: extraction failed, or both index and insights failed
    - queued: nothing has started
    - processing: any stage pending or running
    - ready: index and insights both succeeded
    - partial: one of index/insights succeeded and the other failed
    """
    if extract == "failed":
        return "failed"
    if extract == "pending" and index == "pending" and insights == "pending":
        return "queued"
    if extract in ACTIVE or index in ACTIVE or insights in ACTIVE:
        return "processing"
    if index == "succeeded" and insights == "succeeded":
        return "ready"
    if index == "failed" and insights == "failed":
        return "failed"
    return "partial"


def recompute(doc: Document) -> None:
    doc.status = derive_status(doc.extract_status, doc.index_status, doc.insights_status)


def is_chat_ready(doc: Document) -> bool:
    return doc.index_status == "succeeded"


def status_payload(doc: Document) -> dict[str, Any]:
    """Compact snapshot published on `doc:{id}` and sent by the status SSE stream."""
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status,
        "stages": {
            "extract": doc.extract_status,
            "index": doc.index_status,
            "insights": doc.insights_status,
        },
        "chat_ready": is_chat_ready(doc),
        "page_count": doc.page_count,
        "warnings": doc.warnings or [],
        "error": (
            {"code": doc.error_code, "message": doc.error_message} if doc.error_code else None
        ),
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def channel(document_id: object) -> str:
    return f"doc:{document_id}"
