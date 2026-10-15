"""Question pipeline shared by the JSON and SSE endpoints.

prepare_ask (request scope; raises client errors before anything streams)
  1. resolve and validate scope (409 DOCUMENTS_NOT_READY lists the documents)
  2. persist the user message
answer_events (async generator of events; owns its own DB sessions)
  3. condense the follow-up with the last 6 messages (only when history exists)
  4. embed the standalone query (Redis cache)
  5. hybrid retrieval restricted to the scope
  6. build the prompt with [S1]..[Sn] sources
  7. generate (streamed); stop early if asked (client disconnect)
  8. validate citations and map them to stored chunks
  9. persist the assistant message, citations, retrieval trace and latencies
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIError
from app.ai.providers import StreamResult
from app.ai.registry import async_ai
from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.session import async_session_factory
from app.models import AICall, ChatSession, Document, Message, MessageCitation
from app.prompts import load_prompt
from app.schemas.chat import CitationOut, Latency, MessageOut, UsageOut
from app.services.cache import cached_query_embedding
from app.services.citations import best_excerpt, check_citations
from app.services.locators import locator_label
from app.services.retrieval import Candidate, retrieve

log = logging.getLogger(__name__)

DEFAULT_TITLE = "New chat"
HISTORY_MESSAGES = 6
CONDENSE_VERSION = "chat.condense.v2"  # v1 kept for history; see docs/PROMPTS.md
ANSWER_VERSION = "chat.answer.v1"
ANSWER_MAX_TOKENS = 800
CONDENSE_MAX_TOKENS = 200
HISTORY_CHARS = 600


def _now() -> datetime:
    return datetime.now(UTC)


def _ai_mode(model: str | None) -> str | None:
    if model is None:
        return None
    return "fake" if model == "fake" else "openai"


# ---------------------------------------------------------------- serialization


async def usage_by_message(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, UsageOut]:
    if not ids:
        return {}
    rows = await db.execute(
        select(
            AICall.message_id,
            func.sum(AICall.input_tokens),
            func.sum(AICall.output_tokens),
            func.sum(AICall.estimated_cost_usd),
        )
        .where(AICall.message_id.in_(ids))
        .group_by(AICall.message_id)
    )
    return {
        mid: UsageOut(
            input_tokens=int(i or 0), output_tokens=int(o or 0), estimated_cost_usd=float(c or 0)
        )
        for mid, i, o, c in rows.all()
    }


def message_out(msg: Message, usage: UsageOut | None = None) -> MessageOut:
    return MessageOut(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        answer_status=msg.answer_status,
        interrupted=msg.interrupted,
        error_code=msg.error_code,
        standalone_query=msg.standalone_query,
        scope_document_ids=msg.scope_document_ids or [],
        citations=[
            CitationOut(
                marker=c.marker,
                document_id=c.document_id,
                document_name=c.document_name,
                locator=c.locator,
                location=locator_label(c.locator),
                excerpt=c.excerpt,
                chunk_id=c.chunk_id,
                score=c.score,
            )
            for c in msg.citations
        ],
        model=msg.model,
        prompt_version=msg.prompt_version,
        ai_mode=_ai_mode(msg.model) if msg.role == "assistant" else None,
        latency_ms=Latency(first_token=msg.first_token_ms, total=msg.total_ms),
        usage=usage or UsageOut(),
        created_at=msg.created_at,
    )


# ---------------------------------------------------------------- scope + preparation


@dataclass
class PreparedAsk:
    session_id: uuid.UUID
    user_message_id: uuid.UUID
    question: str
    scope_ids: list[uuid.UUID]
    vault_wide: bool
    document_names: dict[uuid.UUID, str]
    history: list[tuple[str, str]] = field(default_factory=list)


async def resolve_scope(
    db: AsyncSession, chat: ChatSession
) -> tuple[list[uuid.UUID], dict[uuid.UUID, str], bool]:
    model = get_settings().embedding_model_name
    if chat.scope_mode == "all":
        docs = (
            await db.scalars(
                select(Document).where(
                    Document.index_status == "succeeded", Document.embedding_model == model
                )
            )
        ).all()
        if not docs:
            raise ConflictError(
                "No document in the vault is chat-ready yet.",
                code="DOCUMENTS_NOT_READY",
                details={"document_ids": [], "documents": []},
            )
        return [d.id for d in docs], {d.id: d.filename for d in docs}, True

    ids = [link.document_id for link in chat.document_links]
    if not ids:
        raise AppError(
            "This chat has no documents. Attach documents or switch scope_mode to 'all'.",
            code="NO_DOCUMENTS_IN_SCOPE",
            status_code=422,
        )
    docs = (await db.scalars(select(Document).where(Document.id.in_(ids)))).all()
    not_ready = []
    for d in docs:
        if d.index_status != "succeeded":
            reason = "INDEX_FAILED" if d.index_status == "failed" else "PROCESSING"
            if d.extract_status == "failed":
                reason = "EXTRACTION_FAILED"
            not_ready.append(
                {"id": str(d.id), "filename": d.filename, "status": d.status, "reason": reason}
            )
        elif d.embedding_model != model:
            not_ready.append(
                {
                    "id": str(d.id),
                    "filename": d.filename,
                    "status": d.status,
                    "reason": "EMBEDDING_MODEL_MISMATCH",
                }
            )
    if not_ready:
        raise ConflictError(
            "Some documents in this chat are not chat-ready yet.",
            code="DOCUMENTS_NOT_READY",
            details={"document_ids": [d["id"] for d in not_ready], "documents": not_ready},
        )
    return [d.id for d in docs], {d.id: d.filename for d in docs}, False


async def prepare_ask(db: AsyncSession, session_id: uuid.UUID, content: str) -> PreparedAsk:
    chat = await db.get(ChatSession, session_id)
    if chat is None:
        raise NotFoundError("Chat session not found.", details={"session_id": str(session_id)})
    question = content.strip()
    if not question:
        raise AppError("The question is empty.", code="VALIDATION_ERROR", status_code=422)
    scope_ids, names, vault_wide = await resolve_scope(db, chat)

    previous = (
        await db.scalars(
            select(Message)
            .where(
                Message.session_id == session_id, Message.answer_status.is_distinct_from("error")
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(HISTORY_MESSAGES)
        )
    ).all()
    history = [(m.role, m.content) for m in reversed(previous)]

    user_msg = Message(
        session_id=session_id,
        role="user",
        content=question,
        scope_document_ids=scope_ids,
        created_at=_now(),
    )
    db.add(user_msg)
    if not chat.title_is_custom and not previous and chat.title == DEFAULT_TITLE:
        one_line = " ".join(question.split())
        chat.title = one_line[:60] + ("…" if len(one_line) > 60 else "")
    chat.updated_at = _now()
    await db.commit()
    return PreparedAsk(
        session_id=session_id,
        user_message_id=user_msg.id,
        question=question,
        scope_ids=scope_ids,
        vault_wide=vault_wide,
        document_names=names,
        history=history,
    )


# ---------------------------------------------------------------- prompt building


def _escape(text: str) -> str:
    """Keep chunk text from closing or opening our delimiters."""
    for tag in ("</sources", "<sources", "</source", "<source"):
        text = text.replace(tag, tag.replace("<", "&lt;"))
    return text


def format_sources(chunks: list[Candidate]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        # Attribute values must not contain double quotes (section labels do: section "Intro").
        name = c.document_name.replace('"', "'")
        location = locator_label(c.locator).replace('"', "'")
        blocks.append(
            f'<source id="S{i}" document="{name}" location="{location}">\n'
            f"{_escape(c.text)}\n</source>"
        )
    return "\n".join(blocks)


def format_history(history: list[tuple[str, str]]) -> str:
    lines = []
    for role, content in history:
        text = " ".join(content.split())[:HISTORY_CHARS]
        lines.append(f"{'User' if role == 'user' else 'Assistant'}: {text}")
    return "\n".join(lines)


def _clean_condensed(text: str, fallback: str) -> str:
    line = text.strip().strip('"').strip()
    if line.lower().startswith("standalone question:"):
        line = line.split(":", 1)[1].strip()
    return line[:1000] or fallback


# ---------------------------------------------------------------- pipeline


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}


async def _persist_assistant(
    *,
    message_id: uuid.UUID,
    prep: PreparedAsk,
    content: str,
    answer_status: str,
    standalone: str | None,
    retrieval: dict[str, Any] | None,
    citations: list[MessageCitation],
    model: str | None,
    first_token_ms: int | None,
    total_ms: int,
    interrupted: bool = False,
    error_code: str | None = None,
) -> MessageOut:
    async with async_session_factory()() as db:
        msg = Message(
            id=message_id,
            session_id=prep.session_id,
            role="assistant",
            content=content,
            answer_status=answer_status,
            interrupted=interrupted,
            error_code=error_code,
            standalone_query=standalone,
            scope_document_ids=prep.scope_ids,
            retrieval=retrieval,
            model=model,
            prompt_version=ANSWER_VERSION,
            first_token_ms=first_token_ms,
            total_ms=total_ms,
            created_at=_now(),
            citations=citations,
        )
        db.add(msg)
        chat = await db.get(ChatSession, prep.session_id)
        if chat is not None:
            chat.updated_at = _now()
        user_msg = await db.get(Message, prep.user_message_id)
        if user_msg is not None and standalone:
            user_msg.standalone_query = standalone
        await db.commit()
        usage = (await usage_by_message(db, [message_id])).get(message_id)
        return message_out(msg, usage)


async def answer_events(
    prep: PreparedAsk, stop: asyncio.Event | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Yields `meta`, `token`*, `citations`, then `done` (or `error`). Always persists the
    assistant message, also when stopped early (flagged `interrupted`) or on AI errors."""
    settings = get_settings()
    started = time.perf_counter()
    message_id = uuid.uuid4()
    standalone: str | None = None
    retrieval_trace: dict[str, Any] | None = None
    first_token_ms: int | None = None
    stream = StreamResult()
    model: str | None = None

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        ai = async_ai()
        model = ai.chat.name
        standalone = prep.question
        if prep.history:
            condensed, _ = await ai.complete(
                load_prompt(CONDENSE_VERSION).messages(
                    history=format_history(prep.history), question=prep.question
                ),
                purpose="condense",
                prompt_version=CONDENSE_VERSION,
                message_id=message_id,
                max_tokens=CONDENSE_MAX_TOKENS,
            )
            standalone = _clean_condensed(condensed, prep.question)

        yield _event(
            "meta",
            {
                "session_id": str(prep.session_id),
                "user_message_id": str(prep.user_message_id),
                "assistant_message_id": str(message_id),
                "standalone_query": standalone,
                "scope_document_ids": [str(i) for i in prep.scope_ids],
                "ai_mode": settings.ai_mode,
            },
        )

        def stopped() -> bool:
            return stop is not None and stop.is_set()

        # Stop is honoured between steps too, so an early Stop skips the remaining AI calls
        # (found in the real-mode dry run: Stop before the first token still paid for them).
        sources: list[Candidate] = []
        retrieval_trace = {}
        interrupted = stopped()
        if not interrupted:
            vector, cache_hit = await cached_query_embedding(ai, standalone, message_id=message_id)
            result = await retrieve(
                standalone,
                vector,
                prep.scope_ids,
                vault_wide=prep.vault_wide,
                embedding_model=ai.embeddings.name,
                top_k=settings.retrieval_top_k,
            )
            sources = result.chunks
            retrieval_trace = {**result.trace, "query_embedding_cache_hit": cache_hit}
            interrupted = stopped()
        if interrupted:
            retrieval_trace["stopped_before_generation"] = True
        else:
            names = sorted({c.document_name for c in sources} or set(prep.document_names.values()))
            messages = load_prompt(ANSWER_VERSION).messages(
                document_names=", ".join(names),
                sources=format_sources(sources),
                question=standalone,
            )
            agen = ai.stream(
                messages,
                purpose="answer",
                prompt_version=ANSWER_VERSION,
                message_id=message_id,
                max_tokens=ANSWER_MAX_TOKENS,
                result=stream,
            )
            try:
                async for delta in agen:
                    if first_token_ms is None:
                        first_token_ms = elapsed_ms()
                    yield _event("token", {"delta": delta})
                    if stopped():
                        interrupted = True
                        break
            finally:
                await agen.aclose()  # records the ledger row (interrupted or not)

        check = check_citations(stream.text, len(sources))
        citations = []
        for number in check.valid:
            chunk = sources[number - 1]
            focus = " ".join([standalone, *check.sentences_by_marker.get(number, [])])
            citations.append(
                MessageCitation(
                    marker=f"S{number}",
                    marker_index=number,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    locator=chunk.locator,
                    excerpt=best_excerpt(chunk.text, focus),
                    score=None if chunk.similarity is None else round(chunk.similarity, 4),
                )
            )
        retrieval_trace["sources"] = [
            {"marker": f"S{i}", "chunk_id": str(c.chunk_id)} for i, c in enumerate(sources, 1)
        ]
        retrieval_trace["invalid_citations"] = check.invalid
        saved = await _persist_assistant(
            message_id=message_id,
            prep=prep,
            content=check.content,
            answer_status=check.answer_status,
            standalone=standalone,
            retrieval=retrieval_trace,
            citations=citations,
            model=model,
            first_token_ms=first_token_ms,
            total_ms=elapsed_ms(),
            interrupted=interrupted,
        )
        yield _event(
            "citations",
            {"citations": [c.model_dump(mode="json") for c in saved.citations]},
        )
        yield _event(
            "done",
            {
                "message": saved.model_dump(mode="json"),
                "answer_status": saved.answer_status,
                "interrupted": interrupted,
                "usage": saved.usage.model_dump(),
                "latency_ms": saved.latency_ms.model_dump(),
            },
        )
    except AIError as exc:
        log.warning("answer failed", extra={"error_code": exc.code})
        saved = await _persist_assistant(
            message_id=message_id,
            prep=prep,
            content=stream.text or exc.message,
            answer_status="error",
            standalone=standalone,
            retrieval=retrieval_trace,
            citations=[],
            model=model,
            first_token_ms=first_token_ms,
            total_ms=elapsed_ms(),
            error_code=exc.code,
        )
        yield _event(
            "error",
            {
                "code": exc.code,
                "message": exc.message,
                "status": exc.status_code,
                "details": exc.details,
                "message_id": str(saved.id),
            },
        )


async def ask_json(prep: PreparedAsk) -> tuple[MessageOut, MessageOut]:
    """Run the pipeline to completion (no streaming) and return both messages."""
    done: dict[str, Any] | None = None
    async for event in answer_events(prep):
        if event["event"] == "error":
            data = event["data"]
            raise AppError(
                data["message"],
                code=data["code"],
                status_code=data["status"],
                details={**data["details"], "message_id": data["message_id"]},
            )
        if event["event"] == "done":
            done = event["data"]
    assert done is not None
    async with async_session_factory()() as db:
        user_msg = await db.get(Message, prep.user_message_id)
        assert user_msg is not None
        user = message_out(user_msg)
    return user, MessageOut.model_validate(done["message"])
