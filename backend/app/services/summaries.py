"""On-demand summaries with user-chosen length, tone and focus.

The result is stored per (document, normalised options, prompt version, model), so asking again
returns the stored summary without an AI call. Key points are validated like insights: every
point must cite markers that were in the prompt.
"""

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import async_ai
from app.ai.schemas import CustomSummaryLLM
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.models import Document, DocumentSegment, DocumentSummary
from app.prompts import load_prompt
from app.services.insights import (
    Validation,
    clip_words,
    marked_segments,
    render,
    validate_key_points,
)
from app.services.selection import select_parts

VERSION = "summary.custom.v1"
MAX_OUTPUT_TOKENS = 1200

LENGTHS = {
    "short": {"words": 80, "points": 3},
    "medium": {"words": 200, "points": 5},
    "long": {"words": 400, "points": 8},
}
TONES = {
    "neutral": "Neutral and factual, for a general reader.",
    "executive": "For a busy executive: lead with decisions, outcomes, figures, risks and next "
    "steps; no background unless needed.",
    "technical": "For a specialist: precise terminology, exact figures, conditions, dependencies "
    "and exceptions.",
    "plain": "Plain language for a non-expert: short sentences, everyday words, and a brief "
    "explanation of any necessary term.",
}


def normalise_focus(focus: str | None) -> str | None:
    text = " ".join((focus or "").split())
    return text or None


def params_key(length: str, tone: str, focus: str | None) -> str:
    raw = json.dumps(
        {"length": length, "tone": tone, "focus": (focus or "").lower()}, sort_keys=True
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def coverage_note(coverage: dict) -> str:
    if coverage["complete"]:
        return "the whole document is included."
    how = (
        "the parts most related to the focus"
        if coverage["selection"] == "focus"
        else "evenly spread parts"
    )
    return (
        f"the document is too long to include in full; {how} are included "
        f"({coverage['segments_included']} of {coverage['segments_total']} pages/sections)."
    )


def require_extracted(doc: Document) -> None:
    if doc.extract_status != "succeeded":
        raise ConflictError(
            "The document text is not available yet.",
            code="DOCUMENT_NOT_EXTRACTED",
            details={"document_id": str(doc.id), "status": doc.status},
        )


async def load_parts(db: AsyncSession, doc: Document):
    segments = (
        await db.scalars(
            select(DocumentSegment)
            .where(DocumentSegment.document_id == doc.id)
            .order_by(DocumentSegment.ordinal)
        )
    ).all()
    return marked_segments(doc, list(segments))


async def get_or_create_summary(
    db: AsyncSession, doc: Document, *, length: str, tone: str, focus: str | None
) -> tuple[DocumentSummary, bool]:
    """Returns (summary, cached)."""
    require_extracted(doc)
    focus = normalise_focus(focus)
    ai = async_ai()
    key = params_key(length, tone, focus)
    existing = await db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.document_id == doc.id,
            DocumentSummary.params_key == key,
            DocumentSummary.prompt_version == VERSION,
            DocumentSummary.model == ai.chat.name,
        )
    )
    if existing is not None:
        return existing, True

    parts = await load_parts(db, doc)
    pdf = doc.file_type == "pdf"
    doc_id, filename = doc.id, doc.filename
    await db.commit()  # no transaction stays open during the AI call

    budget = get_settings().on_demand_max_input_tokens
    chosen, coverage = select_parts(parts, budget, focus)
    rules = LENGTHS[length]
    prompt = load_prompt(VERSION)
    raw, _ = await ai.structured(
        CustomSummaryLLM,
        prompt.messages(
            filename=filename,
            marker_kind="[Page N] = physical page N" if pdf else "[Section N: heading] = section N",
            coverage_note=coverage_note(coverage),
            length_rule=f"the summary has at most {rules['words']} words; give at most "
            f"{rules['points']} key points.",
            tone_rule=TONES[tone],
            focus_rule="concentrate on the topic inside <focus>; leave out unrelated content. If "
            "the document says nothing about it, set focus_covered to false and say so in one "
            "sentence instead of summarising other content."
            if focus
            else "none requested (the <focus> block is empty): cover the whole text you were "
            "given; set focus_covered to true.",
            focus=focus or "",
            document_text=render(chosen),
        ),
        purpose="summary_custom",
        prompt_version=VERSION,
        document_id=doc_id,
        max_tokens=MAX_OUTPUT_TOKENS,
    )

    v = Validation()
    key_points = validate_key_points(
        raw.key_points,
        valid_refs={p.ref for p in chosen},
        pdf=pdf,
        limit=rules["points"],
        v=v,
    )
    values = {
        "id": uuid.uuid4(),
        "document_id": doc_id,
        "params_key": key,
        "length": length,
        "tone": tone,
        "focus": focus,
        "prompt_version": VERSION,
        "model": ai.chat.name,
        "summary": clip_words(raw.summary, rules["words"], "summary", v),
        "key_points": key_points,
        "focus_covered": raw.focus_covered if focus else None,
        "coverage": {**coverage, "validation": v.as_dict()},
    }
    stmt = insert(DocumentSummary).values(**values)
    # A concurrent identical request may have stored the same options first: keep the newest.
    stmt = stmt.on_conflict_do_update(
        index_elements=["document_id", "params_key", "prompt_version", "model"],
        set_={k: stmt.excluded[k] for k in ("summary", "key_points", "focus_covered", "coverage")},
    ).returning(DocumentSummary)
    row = (await db.scalars(stmt)).one()
    await db.commit()
    return row, False
