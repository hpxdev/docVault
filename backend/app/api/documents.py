import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, error_responses
from app.core.errors import AppError, ConflictError, NotFoundError, error_body
from app.db.session import get_db
from app.models import Document, DocumentInsights, DocumentSegment
from app.schemas.documents import (
    ContentPage,
    DocumentList,
    DocumentOut,
    ReprocessResponse,
    SegmentOut,
    UploadResponse,
)
from app.services import cache
from app.services.events import publish_deleted, publish_status
from app.services.status import STAGE_COLUMN, STAGES, recompute
from app.services.storage import Storage, get_storage
from app.services.upload import handle_upload
from app.workers import dispatch

router = APIRouter(prefix="/documents", tags=["documents"])

DB = Annotated[AsyncSession, Depends(get_db)]
StorageDep = Annotated[Storage, Depends(get_storage)]


def latest_category():
    """Category from the newest insights row of each document (correlated scalar subquery)."""
    return (
        select(DocumentInsights.category)
        .where(DocumentInsights.document_id == Document.id)
        .order_by(DocumentInsights.created_at.desc())
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )


async def get_document_or_404(session: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Document not found.", details={"document_id": str(document_id)})
    return doc


async def _category(session: AsyncSession, document_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(DocumentInsights.category)
        .where(DocumentInsights.document_id == document_id)
        .order_by(DocumentInsights.created_at.desc())
        .limit(1)
    )


@router.post(
    "",
    status_code=202,
    response_model=UploadResponse,
    summary="Upload 1–10 documents",
    responses=error_responses(400, 413, 415, 422),
)
async def upload_documents(
    session: DB,
    storage: StorageDep,
    files: list[UploadFile] = File(
        ..., description="1–10 files (PDF, DOCX, TXT, MD), ≤ MAX_UPLOAD_MB each"
    ),
):
    """Each file gets its own outcome: `accepted` (queued for processing), `duplicate` (same
    SHA-256 already in the vault: the existing document is returned and nothing is reprocessed)
    or `rejected` (with an error code). The file type is detected from the bytes, not the
    extension. Returns **202** if at least one file was accepted or deduplicated; a 4xx error
    envelope (with per-file results in `details`) only when every file is rejected."""
    results, status = await handle_upload(session, storage, files)
    body = UploadResponse(
        results=results,
        accepted=sum(r.outcome == "accepted" for r in results),
        duplicates=sum(r.outcome == "duplicate" for r in results),
        rejected=sum(r.outcome == "rejected" for r in results),
    )
    if status != 202:
        codes = {r.error.code for r in results if r.error}
        code = next(iter(codes)) if len(codes) == 1 else "UPLOAD_REJECTED"
        return JSONResponse(
            status_code=status,
            content=error_body(
                code,
                "All files were rejected.",
                {"results": body.model_dump(mode="json")["results"]},
            ),
        )
    if body.accepted:
        await cache.invalidate_metrics()
    return body


@router.get("", response_model=DocumentList, summary="List documents (newest first)")
async def list_documents(
    session: DB,
    limit: Limit = 20,
    offset: Offset = 0,
    status: Annotated[
        str | None, Query(description="queued | processing | ready | partial | failed")
    ] = None,
    q: Annotated[str | None, Query(description="Case-insensitive filename search")] = None,
    category: Annotated[str | None, Query(description="Insights category")] = None,
):
    category_col = latest_category()
    stmt = select(Document, category_col.label("category"))
    if status:
        stmt = stmt.where(Document.status == status)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Document.filename.ilike(f"%{escaped}%", escape="\\"))
    if category:
        stmt = stmt.where(category_col == category)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.execute(
        stmt.order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)
    )
    items = [DocumentOut.from_model(doc, cat) for doc, cat in rows.all()]
    return DocumentList(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/{document_id}",
    response_model=DocumentOut,
    summary="Document detail: stage statuses, chat readiness, counts, warnings, last error",
    responses=error_responses(404),
)
async def get_document(document_id: uuid.UUID, session: DB):
    doc = await get_document_or_404(session, document_id)
    return DocumentOut.from_model(doc, await _category(session, document_id))


@router.get(
    "/{document_id}/content",
    response_model=ContentPage,
    summary="Extracted original text, by page/section, with locators",
    responses=error_responses(404),
)
async def get_document_content(
    document_id: uuid.UUID, session: DB, limit: Limit = 20, offset: Offset = 0
):
    doc = await get_document_or_404(session, document_id)
    total = await session.scalar(
        select(func.count()).where(DocumentSegment.document_id == document_id)
    )
    rows = await session.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.document_id == document_id)
        .order_by(DocumentSegment.ordinal)
        .limit(limit)
        .offset(offset)
    )
    items = [
        SegmentOut(
            ordinal=s.ordinal,
            locator=s.locator,
            text=s.text,
            char_start=s.char_start,
            char_end=s.char_end,
        )
        for s in rows
    ]
    return ContentPage(
        document_id=doc.id,
        file_type=doc.file_type,
        items=items,
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}/file",
    summary="Download the original file",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}, **error_responses(404)},
)
async def download_document(document_id: uuid.UUID, session: DB, storage: StorageDep):
    doc = await get_document_or_404(session, document_id)
    path = storage.local_path(doc.storage_path)
    if not path.is_file():
        raise NotFoundError("The stored file is missing.", code="FILE_MISSING")
    return FileResponse(path, media_type=doc.mime_type, filename=doc.filename)


@router.post(
    "/{document_id}/reprocess",
    status_code=202,
    response_model=ReprocessResponse,
    summary="Re-run failed (or chosen) stages",
    responses=error_responses(
        404,
        409,
        422,
        overrides={409: ("DOCUMENT_PROCESSING", "The document is currently processing.")},
    ),
)
async def reprocess_document(
    document_id: uuid.UUID,
    session: DB,
    stages: Annotated[
        str | None,
        Query(
            description="Comma-separated subset of extract,index,insights. "
            "Default: the failed stages. `extract` re-runs the whole pipeline."
        ),
    ] = None,
):
    """Returns `409 DOCUMENT_PROCESSING` while any stage is pending/running, and
    `409 NOTHING_TO_REPROCESS` when no stage failed and none was requested."""
    doc = await session.get(Document, document_id, with_for_update=True)
    if doc is None:
        raise NotFoundError("Document not found.", details={"document_id": str(document_id)})
    if doc.status in ("queued", "processing"):
        raise ConflictError(
            "The document is currently processing.",
            code="DOCUMENT_PROCESSING",
            details={"status": doc.status},
        )
    if stages:
        requested = [s.strip() for s in stages.split(",") if s.strip()]
        invalid = [s for s in requested if s not in STAGES]
        if invalid:
            raise AppError(
                f"Unknown stage(s): {', '.join(invalid)}",
                code="VALIDATION_ERROR",
                status_code=422,
                details={"allowed": list(STAGES)},
            )
    else:
        requested = [s for s in STAGES if getattr(doc, STAGE_COLUMN[s]) == "failed"]
    if not requested:
        raise ConflictError(
            "No stage has failed; pass ?stages= to re-run specific stages.",
            code="NOTHING_TO_REPROCESS",
        )
    if "extract" in requested:
        to_run = list(STAGES)
        enqueue = ["extract"]
    else:
        if doc.extract_status != "succeeded":
            raise ConflictError(
                "Extraction has not succeeded; reprocess with stages=extract.",
                code="EXTRACTION_REQUIRED",
            )
        to_run = [s for s in STAGES if s in requested]
        enqueue = to_run
    for stage in to_run:
        setattr(doc, STAGE_COLUMN[stage], "pending")
    if "index" in to_run:
        doc.chat_ready_at = None
    doc.ready_at = None
    doc.error_code = doc.error_message = None
    recompute(doc)
    await session.commit()
    for stage in enqueue:
        await asyncio.to_thread(dispatch.enqueue_stage, stage, doc.id)
    await publish_status(doc)
    await cache.invalidate_metrics()
    return ReprocessResponse(document=DocumentOut.from_model(doc), stages=to_run)


@router.delete(
    "/{document_id}",
    status_code=204,
    summary="Delete a document and everything derived from it",
    responses=error_responses(404),
)
async def delete_document(document_id: uuid.UUID, session: DB, storage: StorageDep):
    """Deletes the file, segments, chunks, insights and session links, and clears cached metrics.
    Past chat citations keep their snapshot (document name, locator, excerpt); their `chunk_id`
    and `document_id` become null. The AI cost ledger is kept."""
    doc = await get_document_or_404(session, document_id)
    await session.delete(doc)
    await session.commit()
    storage.delete_document(document_id)
    await cache.invalidate_metrics()
    await publish_deleted(document_id)
