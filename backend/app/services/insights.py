"""Insights stage: whole-document coverage with single-pass or map-reduce, then server-side
validation of everything the model returned."""

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.client import SyncAI
from app.ai.schemas import (
    CATEGORIES,
    SENTIMENTS,
    DocumentInsightsLLM,
    KeyPointLLM,
    SectionNotesLLM,
)
from app.core.config import get_settings
from app.core.tokens import chat_encoding, count_chat_tokens
from app.models import Document, DocumentInsights, DocumentSegment
from app.prompts import load_prompt
from app.services.locators import locator_label

SINGLE = "insights.single.v1"
MAP = "insights.map.v1"
REDUCE = "insights.reduce.v1"
MAP_REDUCE_VERSION = f"{MAP}+{REDUCE}"

MAP_GROUP_TOKENS = 8000
SINGLE_MAX_OUTPUT = 2000
MAP_MAX_OUTPUT = 1200

LIMITS = {"summary_short": 60, "summary_detailed": 250}
MAX_KEY_POINTS, MAX_TAGS, MAX_QUESTIONS, MAX_TOPICS, MAX_ENTITIES = 10, 8, 5, 10, 20


@dataclass
class MarkedSegment:
    ref: int  # page number (PDF) or 1-based section ordinal
    marker: str
    segment_id: Any
    text: str


@dataclass
class Validation:
    dropped_refs: int = 0
    dropped_key_points: int = 0
    invalid_enums: int = 0
    truncated_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dropped_refs": self.dropped_refs,
            "dropped_key_points": self.dropped_key_points,
            "invalid_enums": self.invalid_enums,
            "truncated_fields": self.truncated_fields,
        }


def marked_segments(doc: Document, segments: list[DocumentSegment]) -> list[MarkedSegment]:
    out = []
    for seg in segments:
        if doc.file_type == "pdf":
            ref = int(seg.locator["page"])
            marker = f"[Page {ref}]"
        else:
            ref = seg.ordinal
            marker = f"[Section {ref}: {locator_label(seg.locator)}]"
        out.append(MarkedSegment(ref, marker, seg.id, seg.text))
    return out


def render(parts: list[MarkedSegment]) -> str:
    return "\n\n".join(f"{p.marker}\n{p.text or '(no text on this page)'}" for p in parts)


def split_large(parts: list[MarkedSegment], max_tokens: int) -> list[MarkedSegment]:
    """Split segments larger than `max_tokens` into token windows that keep their marker."""
    enc = chat_encoding()
    pieces: list[MarkedSegment] = []
    for p in parts:
        tokens = enc.encode(p.text, disallowed_special=())
        if len(tokens) <= max_tokens:
            pieces.append(p)
            continue
        for start in range(0, len(tokens), max_tokens):
            window = enc.decode(tokens[start : start + max_tokens])
            pieces.append(MarkedSegment(p.ref, p.marker, p.segment_id, window))
    return pieces


def piece_cost(p: MarkedSegment) -> int:
    return count_chat_tokens(p.marker) + count_chat_tokens(p.text) + 2


def group_for_map(parts: list[MarkedSegment], max_tokens: int) -> list[list[MarkedSegment]]:
    """Consecutive groups of about `max_tokens`. A segment larger than that is split into
    token windows that keep its marker, so no text is skipped."""
    pieces = split_large(parts, max_tokens)
    groups: list[list[MarkedSegment]] = []
    current: list[MarkedSegment] = []
    size = 0
    for p in pieces:
        cost = piece_cost(p)
        if current and size + cost > max_tokens:
            groups.append(current)
            current, size = [], 0
        current.append(p)
        size += cost
    if current:
        groups.append(current)
    return groups


def _range_label(group: list[MarkedSegment], pdf: bool) -> str:
    first, last = group[0].ref, group[-1].ref
    unit = "pages" if pdf else "sections"
    return f"{unit} {first}-{last}" if first != last else f"{unit[:-1]} {first}"


def _notes_block(index: int, label: str, notes: SectionNotesLLM) -> str:
    lines = [f"[Part {index}: {label}]"]
    for kp in notes.key_points:
        lines.append(f"- {kp.text} (refs: {', '.join(str(r) for r in kp.refs)})")
    e = notes.entities
    for name, values in (
        ("People", e.people),
        ("Organizations", e.organizations),
        ("Locations", e.locations),
        ("Dates", e.dates),
        ("Amounts", e.amounts),
        ("Figures", notes.figures),
    ):
        if values:
            lines.append(f"{name}: {'; '.join(values)}")
    return "\n".join(lines)


def clip_words(text: str, limit: int, name: str, v: Validation) -> str:
    words = text.split()
    if len(words) <= limit:
        return text.strip()
    v.truncated_fields.append(name)
    return " ".join(words[:limit]) + " …"


def _clean_list(
    values: list[str], limit: int, *, lower: bool = False, max_len: int = 200
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = re.sub(r"\s+", " ", value).strip()[:max_len]
        if lower:
            item = item.lower()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out[:limit]


def ref_fields(refs: list[int], pdf: bool) -> dict[str, Any]:
    """Validated marker numbers as API fields: `pages` for PDFs, `sections` otherwise."""
    return {"pages": refs} if pdf else {"pages": [], "sections": refs}


def validate_key_points(
    raw: list[KeyPointLLM], *, valid_refs: set[int], pdf: bool, limit: int, v: Validation
) -> list[dict[str, Any]]:
    key_points = []
    for kp in raw:
        refs = sorted({r for r in kp.refs if r in valid_refs})
        v.dropped_refs += len(set(kp.refs)) - len(refs)
        if not refs or not kp.text.strip():
            v.dropped_key_points += 1  # every key point must point at its source
            continue
        key_points.append({"text": kp.text.strip(), **ref_fields(refs, pdf)})
    if len(key_points) > limit:
        v.truncated_fields.append("key_points")
        key_points = key_points[:limit]
    return key_points


def validate(
    raw: DocumentInsightsLLM, *, valid_refs: set[int], pdf: bool
) -> tuple[dict[str, Any], Validation]:
    """Drop refs outside the document, invalid enum values and over-limit items; count them."""
    v = Validation()
    key_points = validate_key_points(
        raw.key_points, valid_refs=valid_refs, pdf=pdf, limit=MAX_KEY_POINTS, v=v
    )

    category = raw.category.strip().lower()
    if category not in CATEGORIES:
        v.invalid_enums += 1
        category = "other"
    label: str | None = raw.sentiment.label.strip().lower()
    if label not in SENTIMENTS:
        v.invalid_enums += 1
        label = None

    e = raw.entities
    entities = {
        "people": _clean_list(e.people, MAX_ENTITIES),
        "organizations": _clean_list(e.organizations, MAX_ENTITIES),
        "locations": _clean_list(e.locations, MAX_ENTITIES),
        "dates": _clean_list(e.dates, MAX_ENTITIES),
        "amounts": _clean_list(e.amounts, MAX_ENTITIES),
    }
    fields = {
        "summary_short": clip_words(raw.summary_short, LIMITS["summary_short"], "summary_short", v),
        "summary_detailed": clip_words(
            raw.summary_detailed, LIMITS["summary_detailed"], "summary_detailed", v
        ),
        "key_points": key_points,
        "entities": entities,
        "topics": _clean_list(raw.topics, MAX_TOPICS, max_len=60),
        "category": category,
        "tags": _clean_list(raw.tags, MAX_TAGS, lower=True, max_len=40),
        "sentiment": {"label": label, "rationale": raw.sentiment.rationale.strip()[:400]},
        "suggested_questions": _clean_list(raw.suggested_questions, MAX_QUESTIONS, max_len=300),
    }
    return fields, v


def generate_insights(session: Session, doc: Document, ai: SyncAI) -> DocumentInsights:
    settings = get_settings()
    segments = session.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.document_id == doc.id)
        .order_by(DocumentSegment.ordinal)
    ).all()
    parts = marked_segments(doc, list(segments))
    pdf = doc.file_type == "pdf"
    marker_kind = "[Page N] = physical page N" if pdf else "[Section N: heading] = section N"
    full_text = render(parts)
    covered: set[Any] = set()

    if count_chat_tokens(full_text) <= settings.insights_single_pass_max_tokens:
        method, version, groups_used = "single", SINGLE, 1
        prompt = load_prompt(SINGLE)
        raw = ai.structured(
            DocumentInsightsLLM,
            prompt.messages(
                filename=doc.filename, marker_kind=marker_kind, document_text=full_text
            ),
            purpose="insights_single",
            prompt_version=SINGLE,
            document_id=doc.id,
            max_tokens=SINGLE_MAX_OUTPUT,
        )
        covered.update(p.segment_id for p in parts)
    else:
        method, version = "map_reduce", MAP_REDUCE_VERSION
        groups = group_for_map(parts, MAP_GROUP_TOKENS)
        groups_used = len(groups)
        map_prompt = load_prompt(MAP)
        blocks = []
        for index, group in enumerate(groups, start=1):
            label = _range_label(group, pdf)
            notes = ai.structured(
                SectionNotesLLM,
                map_prompt.messages(
                    filename=doc.filename,
                    part_index=index,
                    part_total=len(groups),
                    part_range=label,
                    part_text=render(group),
                ),
                purpose="insights_map",
                prompt_version=MAP,
                document_id=doc.id,
                max_tokens=MAP_MAX_OUTPUT,
            )
            covered.update(p.segment_id for p in group)
            blocks.append(_notes_block(index, label, notes))
        reduce_prompt = load_prompt(REDUCE)
        raw = ai.structured(
            DocumentInsightsLLM,
            reduce_prompt.messages(
                filename=doc.filename, part_total=len(groups), notes="\n\n".join(blocks)
            ),
            purpose="insights_reduce",
            prompt_version=REDUCE,
            document_id=doc.id,
            max_tokens=SINGLE_MAX_OUTPUT,
        )

    valid_refs = {p.ref for p in parts}
    fields, validation = validate(raw, valid_refs=valid_refs, pdf=pdf)
    coverage = {
        "segments_total": len(parts),
        "segments_covered": len(covered),
        "method": method,
        "groups": groups_used,
        "validation": validation.as_dict(),
    }
    values = {
        "document_id": doc.id,
        "prompt_version": version,
        "model": ai.chat.name,
        "coverage": coverage,
        **fields,
    }
    stmt = insert(DocumentInsights).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["document_id", "prompt_version"],
        set_={k: stmt.excluded[k] for k in values if k not in ("document_id", "prompt_version")}
        | {"created_at": stmt.excluded.created_at},
    ).returning(DocumentInsights)
    return session.scalars(stmt).one()
