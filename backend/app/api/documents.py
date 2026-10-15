import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, error_responses
from app.core.errors import AppError, ConflictError, NotFoundError, error_body
from app.core.ratelimit import RATE_LIMITED_EXAMPLE, rate_limit
from app.core.redis import async_cache
from app.db.session import get_db
from app.models import (
    Document,
    DocumentComparison,
    DocumentInsights,
    DocumentSegment,
    DocumentSummary,
)
from app.schemas.analysis import SummaryList, SummaryOut, SummaryRequest
from app.schemas.documents import (
    ContentPage,
    DocumentList,
    DocumentOut,
    InsightsOut,
    ReprocessResponse,
    SegmentOut,
    UploadResponse,
    VersionList,
)
from app.services import cache
from app.services.events import publish_deleted, publish_status
from app.services.status import STAGE_COLUMN, STAGES, channel, recompute, status_payload
from app.services.storage import Storage, get_storage
from app.services.summaries import get_or_create_summary
from app.services.upload import handle_new_version, handle_upload
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
    responses=error_responses(400, 413, 415, 422, 429, overrides={429: RATE_LIMITED_EXAMPLE}),
    dependencies=[rate_limit("upload")],
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
    all_versions: Annotated[
        bool, Query(description="Include older versions (default: latest version only)")
    ] = False,
):
    category_col = latest_category()
    stmt = select(Document, category_col.label("category"))
    if not all_versions:
        stmt = stmt.where(Document.is_latest.is_(True))
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


def _parse_ids(
    ids: Annotated[str | None, Query(description="Comma-separated document IDs (max 50)")] = None,
) -> list[uuid.UUID]:
    """Dependency: validated before the stream starts, so errors are normal JSON responses."""
    if not ids:
        return []
    try:
        wanted = list(dict.fromkeys(uuid.UUID(x.strip()) for x in ids.split(",") if x.strip()))
    except ValueError as exc:
        raise AppError(
            "ids must be comma-separated UUIDs.", code="VALIDATION_ERROR", status_code=422
        ) from exc
    if len(wanted) > 50:
        raise AppError("At most 50 ids.", code="VALIDATION_ERROR", status_code=422)
    return wanted


_EVENTS_DOC = """Server-Sent Events with document status.

1. `snapshot` for each requested document (current state; `not_found` for unknown IDs),
2. then `status` on every change (stage started/finished/retrying/failed) and `deleted`,
3. `: ping` comments every 15 s while idle (heartbeat).

`ids` limits the stream to those documents (max 50); without it, all documents are watched
(snapshot of the 50 newest). With `close_when_settled=true` the stream ends once every requested
document is no longer `queued`/`processing` (useful for scripts: `curl -N`)."""


@router.get(
    "/events",
    response_class=EventSourceResponse,
    summary="Live document status (SSE)",
    description=_EVENTS_DOC,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: snapshot\ndata: {"id": "…", "status": "queued"}\n\n'
                    'event: status\ndata: {"id": "…", "status": "processing"}\n\n'
                }
            }
        },
        **error_responses(422),
    },
)
async def document_events(
    session: DB,
    wanted: Annotated[list[uuid.UUID], Depends(_parse_ids)],
    close_when_settled: bool = False,
) -> AsyncIterator[ServerSentEvent]:
    pubsub = async_cache().pubsub()
    # Subscribe before reading the snapshot so no change can fall between the two.
    if wanted:
        await pubsub.subscribe(*[channel(i) for i in wanted])
    else:
        await pubsub.psubscribe("doc:*")
    try:
        stmt = select(Document)
        stmt = (
            stmt.where(Document.id.in_(wanted))
            if wanted
            else stmt.order_by(Document.created_at.desc()).limit(50)
        )
        docs = (await session.scalars(stmt)).all()
        await session.commit()  # don't hold a transaction open for the stream's lifetime
        pending: set[str] = set()
        for doc in docs:
            payload = status_payload(doc)
            if doc.status in ("queued", "processing"):
                pending.add(payload["id"])
            yield ServerSentEvent(event="snapshot", data=payload)
        for missing in {str(i) for i in wanted} - {str(d.id) for d in docs}:
            yield ServerSentEvent(event="not_found", data={"id": missing})
        if close_when_settled and wanted and not pending:
            return
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message is None:
                continue
            data = json.loads(message["data"])
            if data.get("deleted"):
                pending.discard(data["id"])
                yield ServerSentEvent(event="deleted", data=data)
            else:
                if data.get("status") in ("queued", "processing"):
                    pending.add(data["id"])
                else:
                    pending.discard(data["id"])
                yield ServerSentEvent(event="status", data=data)
            if close_when_settled and wanted and not pending:
                return
    finally:
        await pubsub.aclose()


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


@router.get(
    "/{document_id}/insights",
    response_model=InsightsOut,
    summary="AI insights: summaries, key points with source pages, entities, tags, sentiment",
    responses=error_responses(
        404,
        overrides={404: ("INSIGHTS_NOT_READY", "Insights are not available yet.")},
    ),
)
async def get_document_insights(document_id: uuid.UUID, session: DB):
    """`404 INSIGHTS_NOT_READY` (with the current insights status in `details`) while the stage is
    pending/running or after it failed. `ai_mode: fake` marks output from the test double."""
    doc = await get_document_or_404(session, document_id)
    row = await session.scalar(
        select(DocumentInsights)
        .where(DocumentInsights.document_id == document_id)
        .order_by(DocumentInsights.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise NotFoundError(
            "Insights are not available yet.",
            code="INSIGHTS_NOT_READY",
            details={
                "status": doc.status,
                "insights_status": doc.insights_status,
                "error": {"code": doc.error_code, "message": doc.error_message}
                if doc.insights_status == "failed"
                else None,
            },
        )
    return InsightsOut(
        document_id=row.document_id,
        ai_mode="fake" if row.model == "fake" else "openai",
        model=row.model,
        prompt_version=row.prompt_version,
        summary_short=row.summary_short,
        summary_detailed=row.summary_detailed,
        key_points=row.key_points,
        entities=row.entities,
        topics=row.topics,
        category=row.category,
        tags=row.tags,
        sentiment=row.sentiment,
        suggested_questions=row.suggested_questions,
        coverage=row.coverage,
        created_at=row.created_at,
    )


@router.post(
    "/{document_id}/versions",
    status_code=202,
    response_model=DocumentOut,
    summary="Upload a new version of a document",
    responses=error_responses(
        400,
        404,
        409,
        413,
        415,
        422,
        429,
        overrides={
            409: ("VERSION_UNCHANGED", "This file is identical to version 1 of the document."),
            429: RATE_LIMITED_EXAMPLE,
        },
    ),
    dependencies=[rate_limit("upload")],
)
async def upload_version(
    document_id: uuid.UUID,
    session: DB,
    storage: StorageDep,
    file: UploadFile = File(..., description="One file (PDF, DOCX, TXT, MD), ≤ MAX_UPLOAD_MB"),
):
    """The file becomes version N+1 of the document's version group and is processed like a new
    upload; `document_id` may be any version of the group. Older versions are kept with their
    insights and chat citations (`is_latest: false`); vault-wide chat and the default document
    list use the latest version only, while chats that were attached to an older version keep
    it. The new version may have a different file type or name.

    `409 VERSION_UNCHANGED`: the file is byte-identical to a version of this document;
    `409 DUPLICATE_CONTENT`: it is identical to a different document."""
    current = await get_document_or_404(session, document_id)
    doc = await handle_new_version(session, storage, current, file)
    await cache.invalidate_metrics()
    return doc


@router.get(
    "/{document_id}/versions",
    response_model=VersionList,
    summary="All versions of a document (newest first)",
    responses=error_responses(404),
)
async def list_versions(document_id: uuid.UUID, session: DB):
    doc = await get_document_or_404(session, document_id)
    category_col = latest_category()
    rows = await session.execute(
        select(Document, category_col.label("category"))
        .where(Document.version_group_id == doc.version_group_id)
        .order_by(Document.version.desc())
    )
    items = [DocumentOut.from_model(d, cat) for d, cat in rows.all()]
    latest = next((i for i in items if i.is_latest), items[0])
    return VersionList(version_group_id=doc.version_group_id, latest_id=latest.id, items=items)


@router.post(
    "/{document_id}/summaries",
    response_model=SummaryOut,
    summary="Custom summary: choose length, tone and focus",
    responses=error_responses(
        404,
        409,
        422,
        429,
        503,
        overrides={
            409: ("DOCUMENT_NOT_EXTRACTED", "The document text is not available yet."),
            429: RATE_LIMITED_EXAMPLE,
        },
    ),
    dependencies=[rate_limit("ai")],
)
async def create_summary(document_id: uuid.UUID, body: SummaryRequest, session: DB):
    """Summarises the document's extracted text with the chosen options. Key points cite their
    pages (PDF) or sections, validated on the server. An identical request (same document,
    options and model; the focus is compared case- and whitespace-insensitively) returns the
    stored summary with `cached: true` and no AI cost. A document longer than
    `ON_DEMAND_MAX_INPUT_TOKENS` is summarised from selected parts (those matching the focus
    first); `coverage.complete` is then false. `focus_covered: false` means the document does
    not address the focus. Also `429 AI_BUDGET_EXCEEDED` (spend cap) and `503` (provider)."""
    doc = await get_document_or_404(session, document_id)
    row, cached = await get_or_create_summary(
        session, doc, length=body.length, tone=body.tone, focus=body.focus
    )
    if not cached:
        await cache.invalidate_metrics()
    return SummaryOut.from_model(row, cached)


@router.get(
    "/{document_id}/summaries",
    response_model=SummaryList,
    summary="Custom summaries generated for this document (newest first)",
    responses=error_responses(404),
)
async def list_summaries(document_id: uuid.UUID, session: DB):
    await get_document_or_404(session, document_id)
    rows = await session.scalars(
        select(DocumentSummary)
        .where(DocumentSummary.document_id == document_id)
        .order_by(DocumentSummary.created_at.desc())
        .limit(50)
    )
    return SummaryList(items=[SummaryOut.from_model(r, cached=True) for r in rows])


@router.post(
    "/{document_id}/reprocess",
    status_code=202,
    response_model=ReprocessResponse,
    summary="Re-run failed (or chosen) stages",
    responses=error_responses(
        404,
        409,
        422,
        429,
        overrides={
            409: ("DOCUMENT_PROCESSING", "The document is currently processing."),
            429: RATE_LIMITED_EXAMPLE,
        },
    ),
    dependencies=[rate_limit("upload")],
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
    """Deletes the file, segments, chunks, insights, custom summaries, comparisons that include
    it and session links, and clears cached metrics. Past chat citations keep their snapshot
    (document name, locator, excerpt); their `chunk_id` and `document_id` become null. The AI
    cost ledger is kept. Only this version is deleted: if it was the latest, the newest remaining
    version becomes the latest."""
    doc = await get_document_or_404(session, document_id)
    # Lock the version group so a concurrent new-version upload cannot interleave.
    await session.execute(
        select(Document.id)
        .where(Document.version_group_id == doc.version_group_id)
        .with_for_update()
    )
    group_id, was_latest = doc.version_group_id, doc.is_latest
    await session.execute(
        delete(DocumentComparison).where(DocumentComparison.document_ids.contains([document_id]))
    )
    await session.delete(doc)
    await session.flush()
    if was_latest:
        newest = await session.scalar(
            select(Document)
            .where(Document.version_group_id == group_id)
            .order_by(Document.version.desc())
            .limit(1)
        )
        if newest is not None:
            newest.is_latest = True
    await session.commit()
    storage.delete_document(document_id)
    await cache.invalidate_metrics()
    await publish_deleted(document_id)
