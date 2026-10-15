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
from app.ai.schemas import CustomSummaryV3LLM
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

# v1 invented a "risks" point in the first real check; v2 stopped that but left its optional
# gap list empty; v3 asks for a verdict per focus topic. See docs/PROMPTS.md.
VERSION = "summary.custom.v3"
MAX_TOPICS = 5
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


# (focus rule, no-focus rule) per prompt version, so every stored version stays reproducible.
FOCUS_RULES = {
    "summary.custom.v1": (
        "concentrate on the topic inside <focus>; leave out unrelated content. If the document "
        "says nothing about it, set focus_covered to false and say so in one sentence instead of "
        "summarising other content.",
        "none requested (the <focus> block is empty): cover the whole text you were given; set "
        "focus_covered to true.",
    ),
    "summary.custom.v2": (
        'the focus inside <focus> may name several topics (for example "budget and schedule"); '
        "treat each topic separately. Summarise only what the document states about the topics "
        "it addresses and leave out unrelated content. Put every topic the document does not "
        "address in `focus_not_addressed`, in the reader's words, and end the summary with one "
        "sentence saying the document does not address it; never fill a missing topic with "
        "inferred content. Set focus_covered to false only if the document addresses none of the "
        "topics, and then write one sentence saying so instead of summarising other content.",
        "none requested (the <focus> block is empty): cover the whole text you were given; set "
        "focus_covered to true and focus_not_addressed to [].",
    ),
    "summary.custom.v3": (
        'split the focus inside <focus> into its topics (for example "budget and risks" has two '
        'topics, "budget" and "risks") and return one `focus_topics` entry per topic, in order, '
        "in the reader's words, with `addressed` true only if the document states something "
        "about that topic. Summarise only what the document states about the addressed topics "
        "and leave out unrelated content. For the topics with `addressed: false`, end the "
        "summary with one sentence saying the document does not address them; never fill them "
        "with inferred content. If no topic is addressed, the summary is only that sentence and "
        "there are no key points.",
        "none requested (the <focus> block is empty): cover the whole text you were given; "
        "return `focus_topics` as [].",
    ),
}


def focus_verdicts(
    raw_topics: list, focus: str | None
) -> tuple[list[dict[str, object]], list[str], bool | None]:
    """(topics, not addressed, covered) from the model's per-topic verdicts. Without a focus
    everything is ignored; with a focus but no verdicts, coverage is unknown (None)."""
    if not focus:
        return [], [], None
    topics: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw_topics:
        name = " ".join(item.topic.split())[:100]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            topics.append({"topic": name, "addressed": bool(item.addressed)})
    topics = topics[:MAX_TOPICS]
    if not topics:
        return [], [], None
    missing = [str(t["topic"]) for t in topics if not t["addressed"]]
    return topics, missing, any(t["addressed"] for t in topics)


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
        CustomSummaryV3LLM,
        prompt.messages(
            filename=filename,
            marker_kind="[Page N] = physical page N" if pdf else "[Section N: heading] = section N",
            coverage_note=coverage_note(coverage),
            length_rule=f"the summary has at most {rules['words']} words; give at most "
            f"{rules['points']} key points.",
            tone_rule=TONES[tone],
            focus_rule=FOCUS_RULES[VERSION][0 if focus else 1],
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
    topics, missing, covered = focus_verdicts(raw.focus_topics, focus)
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
        "focus_covered": covered,
        "focus_not_addressed": missing,
        "coverage": {**coverage, "focus_topics": topics, "validation": v.as_dict()},
    }
    stmt = insert(DocumentSummary).values(**values)
    # A concurrent identical request may have stored the same options first: keep the newest.
    stmt = stmt.on_conflict_do_update(
        index_elements=["document_id", "params_key", "prompt_version", "model"],
        set_={
            k: stmt.excluded[k]
            for k in ("summary", "key_points", "focus_covered", "focus_not_addressed", "coverage")
        },
    ).returning(DocumentSummary)
    row = (await db.scalars(stmt)).one()
    await db.commit()
    return row, False
