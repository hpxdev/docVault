import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, error_responses
from app.core.errors import AppError, NotFoundError
from app.core.ratelimit import RATE_LIMITED_EXAMPLE, rate_limit
from app.db.session import get_db
from app.models import DocumentComparison
from app.schemas.analysis import ComparisonList, ComparisonOut, ComparisonRequest
from app.services import cache
from app.services.comparisons import get_or_create_comparison

router = APIRouter(prefix="/comparisons", tags=["comparisons"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=ComparisonOut,
    summary="Compare 2–4 documents (or versions of one document)",
    responses=error_responses(
        404,
        409,
        422,
        429,
        503,
        overrides={
            409: ("DOCUMENT_NOT_EXTRACTED", "Some documents' text is not available yet."),
            429: RATE_LIMITED_EXAMPLE,
        },
    ),
    dependencies=[rate_limit("ai")],
)
async def create_comparison(body: ComparisonRequest, session: DB):
    """Documents are labelled D1… in upload order (oldest first), so two versions read as
    old → new. Returns an overview, **similarities** (each stated in at least two documents) and
    **differences** (one position per document), every statement cited to pages or sections and
    validated on the server: a position whose source could not be verified is shown as not
    addressed / uncited instead of as the document's claim. The same document set and focus
    returns the stored result with `cached: true` and no AI cost. Long documents share the
    `ON_DEMAND_MAX_INPUT_TOKENS` budget; see `coverage.documents.<label>.complete`.
    Also `429 AI_BUDGET_EXCEEDED` (spend cap) and `503` (provider)."""
    ids = list(dict.fromkeys(body.document_ids))
    if len(ids) < 2:
        raise AppError(
            "Choose at least two different documents.", code="VALIDATION_ERROR", status_code=422
        )
    row, cached = await get_or_create_comparison(session, ids, body.focus)
    if not cached:
        await cache.invalidate_metrics()
    return ComparisonOut.from_model(row, cached)


@router.get("", response_model=ComparisonList, summary="Past comparisons (newest first)")
async def list_comparisons(
    session: DB,
    limit: Limit = 20,
    offset: Offset = 0,
    document_id: Annotated[
        uuid.UUID | None, Query(description="Only comparisons that include this document")
    ] = None,
):
    stmt = select(DocumentComparison)
    if document_id is not None:
        stmt = stmt.where(DocumentComparison.document_ids.contains([document_id]))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(
        stmt.order_by(DocumentComparison.created_at.desc(), DocumentComparison.id)
        .limit(limit)
        .offset(offset)
    )
    return ComparisonList(
        items=[ComparisonOut.from_model(r, cached=True) for r in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{comparison_id}",
    response_model=ComparisonOut,
    summary="One comparison",
    responses=error_responses(404),
)
async def get_comparison(comparison_id: uuid.UUID, session: DB):
    row = await session.get(DocumentComparison, comparison_id)
    if row is None:
        raise NotFoundError("Comparison not found.", details={"comparison_id": str(comparison_id)})
    return ComparisonOut.from_model(row, cached=True)
