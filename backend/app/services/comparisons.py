"""Comparative analysis of 2–4 documents (or versions of one document).

Each document is labelled D1…Dn (oldest upload first, so versions read old → new) and sent with
its page/section markers. The model's output is validated like insights: every cited
(document, marker) pair must exist in what the prompt contained; a similarity needs sources in at
least two documents, and a difference needs at least one cited position. Results are stored per
(document set, focus, prompt version, model), so repeating a comparison costs nothing.
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import async_ai
from app.ai.schemas import ComparisonLLM, ComparisonV2LLM
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.models import Document, DocumentComparison
from app.prompts import load_prompt
from app.services.grounding import contains_passage
from app.services.insights import Validation, ref_fields, render
from app.services.selection import select_parts
from app.services.summaries import load_parts, normalise_focus

VERSION = "compare.v2"
MAX_OUTPUT_TOKENS = 1600
MAX_SIMILARITIES, MAX_DIFFERENCES = 6, 8
NOT_ADDRESSED = "Not addressed"
UNCITED = "No source was cited for this document's position."
NO_POSITION = "No position given."


def params_key(document_ids: list[uuid.UUID], focus: str | None) -> str:
    raw = json.dumps(
        {"ids": sorted(str(i) for i in document_ids), "focus": (focus or "").lower()},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _escape(text: str) -> str:
    return text.replace("</document", "&lt;/document").replace("<document", "&lt;document")


async def load_documents(db: AsyncSession, ids: list[uuid.UUID]) -> list[Document]:
    docs = (await db.scalars(select(Document).where(Document.id.in_(ids)))).all()
    missing = sorted({str(i) for i in ids} - {str(d.id) for d in docs})
    if missing:
        raise NotFoundError("Some documents do not exist.", details={"document_ids": missing})
    not_ready = [
        {"id": str(d.id), "filename": d.filename, "status": d.status}
        for d in docs
        if d.extract_status != "succeeded"
    ]
    if not_ready:
        raise ConflictError(
            "Some documents' text is not available yet.",
            code="DOCUMENT_NOT_EXTRACTED",
            details={"documents": not_ready},
        )
    return sorted(docs, key=lambda d: (d.created_at, str(d.id)))


def _positions_valid(
    raw: ComparisonLLM | ComparisonV2LLM,
    labels: dict[str, dict[str, Any]],
    valid_refs: dict[str, set[int]],
    *,
    source_text: dict[str, dict[int, str]] | None = None,
    focus: str | None = None,
    partial: set[str] | None = None,
) -> tuple[list[dict], list[dict], Validation]:
    v = Validation()

    def refs_for(label: str, refs: list[int]) -> list[int]:
        allowed = valid_refs.get(label, set())
        kept = sorted({r for r in refs if r in allowed})
        v.dropped_refs += len(set(refs)) - len(kept)
        return kept

    similarities = []
    for sim in raw.similarities:
        if source_text is not None and (
            len(sim.text.split()) < 3 or not sim.text.rstrip().endswith((".", "!", "?"))
        ):
            v.dropped_key_points += 1  # shared headings/keywords are not factual sentences
            continue
        if focus and not getattr(sim, "relevant_to_focus", True):
            v.dropped_key_points += 1
            continue
        sources = []
        for src in sim.sources:
            label = src.document.strip().upper()
            if label not in labels:
                v.dropped_refs += len(src.refs) or 1
                continue
            refs = refs_for(label, src.refs)
            if source_text is not None:
                supported = [
                    ref
                    for ref in refs
                    if contains_passage(source_text.get(label, {}).get(ref, ""), sim.text)
                ]
                v.dropped_refs += len(refs) - len(supported)
                refs = supported
            if refs and all(s["label"] != label for s in sources):
                sources.append({**_public(labels[label]), **ref_fields(refs, labels[label]["pdf"])})
        if len(sources) < 2 or not sim.text.strip():
            v.dropped_key_points += 1  # a similarity must be stated in two documents
            continue
        similarities.append({"text": sim.text.strip(), "sources": sources})
    if len(similarities) > MAX_SIMILARITIES:
        v.truncated_fields.append("similarities")
        similarities = similarities[:MAX_SIMILARITIES]

    differences = []
    for diff in raw.differences:
        if focus and not getattr(diff, "relevant_to_focus", True):
            v.dropped_key_points += 1
            continue
        positions: dict[str, dict] = {}
        for pos in diff.positions:
            label = pos.document.strip().upper()
            if label not in labels or label in positions:
                v.dropped_refs += 1
                continue
            refs = refs_for(label, pos.refs)
            statement = pos.statement.strip()
            if not refs:  # an uncited claim is never shown as the document's position
                said_not_addressed = statement.lower().startswith(NOT_ADDRESSED.lower())
                statement = NOT_ADDRESSED if said_not_addressed else UNCITED
                if label in (partial or set()) and (
                    said_not_addressed
                    or pos.statement.strip().lower().startswith("not found in the selected parts")
                ):
                    statement = "Not found in the selected parts."
            positions[label] = {
                **_public(labels[label]),
                "statement": statement,
                "addressed": bool(refs),
                **ref_fields(refs, labels[label]["pdf"]),
            }
        if not any(p["addressed"] for p in positions.values()) or not diff.aspect.strip():
            v.dropped_key_points += 1
            continue
        # Every document says the same thing: not a difference. The real model padded its list
        # this way in the first live check (identical contractor and fund statements).
        if (
            len(positions) == len(labels)
            and all(p["addressed"] for p in positions.values())
            and len({_normalise(p["statement"]) for p in positions.values()}) == 1
        ):
            v.dropped_key_points += 1
            continue
        for label, info in labels.items():  # one row per document, in label order
            positions.setdefault(
                label,
                {
                    **_public(info),
                    "statement": NO_POSITION,
                    "addressed": False,
                    **ref_fields([], info["pdf"]),
                },
            )
        differences.append(
            {"aspect": diff.aspect.strip()[:120], "positions": [positions[k] for k in labels]}
        )
    if len(differences) > MAX_DIFFERENCES:
        v.truncated_fields.append("differences")
        differences = differences[:MAX_DIFFERENCES]
    return similarities, differences, v


def _normalise(statement: str) -> str:
    return " ".join(statement.lower().split()).rstrip(".")


def _public(info: dict[str, Any]) -> dict[str, Any]:
    return {"label": info["label"], "document_id": info["document_id"]}


async def get_or_create_comparison(
    db: AsyncSession, document_ids: list[uuid.UUID], focus: str | None
) -> tuple[DocumentComparison, bool]:
    """Returns (comparison, cached)."""
    ids = list(dict.fromkeys(document_ids))
    focus = normalise_focus(focus)
    docs = await load_documents(db, ids)
    ai = async_ai()
    key = params_key(ids, focus)
    existing = await db.scalar(
        select(DocumentComparison).where(
            DocumentComparison.params_key == key,
            DocumentComparison.prompt_version == VERSION,
            DocumentComparison.model == ai.chat.name,
        )
    )
    if existing is not None:
        return existing, True

    budget = get_settings().on_demand_max_input_tokens // len(docs)
    labels: dict[str, dict[str, Any]] = {}
    snapshot, blocks, coverage, valid_refs, source_text = [], [], {}, {}, {}
    for n, doc in enumerate(docs, start=1):
        label = f"D{n}"
        pdf = doc.file_type == "pdf"
        chosen, cov = select_parts(await load_parts(db, doc), budget, focus)
        labels[label] = {"label": label, "document_id": str(doc.id), "pdf": pdf}
        valid_refs[label] = {p.ref for p in chosen}
        source_text[label] = {p.ref: p.text for p in chosen}
        coverage[label] = cov
        snapshot.append(
            {
                "label": label,
                "id": str(doc.id),
                "filename": doc.filename,
                "file_type": doc.file_type,
                "version": doc.version,
                "version_group_id": str(doc.version_group_id),
            }
        )
        markers = "[Page N]" if pdf else "[Section N: heading]"
        name = doc.filename.replace('"', "'")
        blocks.append(
            f'<document label="{label}" name="{name}" version="{doc.version}" '
            f'markers="{markers}">\n{_escape(render(chosen))}\n</document>'
        )
    await db.commit()  # no transaction stays open during the AI call

    partial = [lbl for lbl, c in coverage.items() if not c["complete"]]
    same_group = len({d.version_group_id for d in docs}) == 1
    document_list = "; ".join(
        f"{s['label']} = {s['filename']} (version {s['version']})" for s in snapshot
    )
    if same_group:
        document_list += ". These are versions of the same document, oldest first."
    raw, _ = await ai.structured(
        ComparisonV2LLM,
        load_prompt(VERSION).messages(
            document_list=document_list,
            coverage_note="every document is included in full."
            if not partial
            else f"{', '.join(partial)} are too long and only partly included; the rest are "
            "complete.",
            focus_rule="compare only what concerns the topic inside <focus>; set focus_covered "
            "to false if no document addresses it."
            if focus
            else "none requested (the <focus> block is empty): compare the documents as a whole; "
            "set focus_covered to true.",
            focus=focus or "",
            documents="\n\n".join(blocks),
        ),
        purpose="compare",
        prompt_version=VERSION,
        document_id=None,
        max_tokens=MAX_OUTPUT_TOKENS,
    )

    similarities, differences, v = _positions_valid(
        raw, labels, valid_refs, source_text=source_text, focus=focus, partial=set(partial)
    )
    overview = (
        f"Compared {len(docs)} documents: {len(similarities)} shared "
        f"{'passage' if len(similarities) == 1 else 'passages'} and "
        f"{len(differences)} {'difference' if len(differences) == 1 else 'differences'}."
    )
    if partial:
        overview += f" {', '.join(partial)} use selected parts only."
    result = {
        "overview": overview,
        "focus_covered": raw.focus_covered if focus else None,
        "similarities": similarities,
        "differences": differences,
        "same_document_versions": same_group,
    }
    values = {
        "id": uuid.uuid4(),
        "document_ids": [d.id for d in docs],
        "documents": snapshot,
        "params_key": key,
        "focus": focus,
        "prompt_version": VERSION,
        "model": ai.chat.name,
        "result": result,
        "coverage": {"documents": coverage, "validation": v.as_dict()},
    }
    stmt = insert(DocumentComparison).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["params_key", "prompt_version", "model"],
        set_={k: stmt.excluded[k] for k in ("result", "coverage", "documents")},
    ).returning(DocumentComparison)
    row = (await db.scalars(stmt)).one()
    await db.commit()
    return row, False
