import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, error_responses
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import ChatSession, ChatSessionDocument, Document, Message
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    MessageList,
    SessionCreate,
    SessionDocument,
    SessionList,
    SessionOut,
    SessionUpdate,
)
from app.services.chat import (
    DEFAULT_TITLE,
    PreparedAsk,
    answer_events,
    ask_json,
    message_out,
    prepare_ask,
    usage_by_message,
)
from app.services.status import is_chat_ready

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])
DB = Annotated[AsyncSession, Depends(get_db)]

# Streaming pipelines run as tasks independent of the HTTP connection (see ask_stream).
_background: set[asyncio.Task] = set()

_NOT_READY = error_responses(404, 409, 422)


async def _session_or_404(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    chat = await db.get(ChatSession, session_id)
    if chat is None:
        raise NotFoundError("Chat session not found.", details={"session_id": str(session_id)})
    return chat


async def _require_documents(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    found = set((await db.scalars(select(Document.id).where(Document.id.in_(ids)))).all())
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise NotFoundError("Some documents do not exist.", details={"document_ids": missing})


async def _session_out(db: AsyncSession, chat: ChatSession) -> SessionOut:
    await db.refresh(chat, ["document_links"])
    docs = {}
    ids = [link.document_id for link in chat.document_links]
    if ids:
        docs = {d.id: d for d in await db.scalars(select(Document).where(Document.id.in_(ids)))}
    count = await db.scalar(select(func.count()).where(Message.session_id == chat.id))
    return SessionOut(
        id=chat.id,
        title=chat.title,
        scope_mode=chat.scope_mode,
        documents=[
            SessionDocument(
                id=link.document_id,
                filename=docs[link.document_id].filename,
                status=docs[link.document_id].status,
                chat_ready=is_chat_ready(docs[link.document_id]),
                added_at=link.added_at,
            )
            for link in chat.document_links
            if link.document_id in docs
        ],
        message_count=count or 0,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


@router.post(
    "/sessions",
    status_code=201,
    response_model=SessionOut,
    summary="Start a chat session",
    responses=error_responses(404, 422),
)
async def create_session(body: SessionCreate, db: DB):
    """Documents do not need to be ready yet: asking a question checks readiness
    (`409 DOCUMENTS_NOT_READY`)."""
    ids = list(dict.fromkeys(body.document_ids))
    await _require_documents(db, ids)
    chat = ChatSession(
        title=body.title or DEFAULT_TITLE,
        title_is_custom=body.title is not None,
        scope_mode=body.scope_mode,
        document_links=[ChatSessionDocument(document_id=i) for i in ids],
    )
    db.add(chat)
    await db.commit()
    return await _session_out(db, chat)


@router.get("/sessions", response_model=SessionList, summary="List chat sessions (recent first)")
async def list_sessions(db: DB, limit: Limit = 20, offset: Offset = 0):
    total = await db.scalar(select(func.count()).select_from(ChatSession))
    chats = (
        await db.scalars(
            select(ChatSession)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [await _session_out(db, c) for c in chats]
    return SessionList(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="Chat session detail",
    responses=error_responses(404),
)
async def get_session(session_id: uuid.UUID, db: DB):
    return await _session_out(db, await _session_or_404(db, session_id))


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="Rename, add/remove documents, change scope",
    responses=error_responses(404, 422),
)
async def update_session(session_id: uuid.UUID, body: SessionUpdate, db: DB):
    """Each message stores the scope it actually used (`scope_document_ids`), so changing the
    scope never rewrites history."""
    chat = await _session_or_404(db, session_id)
    if body.title is not None:
        chat.title, chat.title_is_custom = body.title, True
    if body.scope_mode is not None:
        chat.scope_mode = body.scope_mode
    await _require_documents(db, body.add_document_ids)
    linked = {link.document_id for link in chat.document_links}
    for doc_id in dict.fromkeys(body.add_document_ids):
        if doc_id not in linked:
            chat.document_links.append(ChatSessionDocument(document_id=doc_id))
    remove = set(body.remove_document_ids)
    chat.document_links = [link for link in chat.document_links if link.document_id not in remove]
    await db.commit()
    return await _session_out(db, chat)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete a chat session and its messages",
    responses=error_responses(404),
)
async def delete_session(session_id: uuid.UUID, db: DB):
    chat = await _session_or_404(db, session_id)
    await db.delete(chat)
    await db.commit()


@router.get(
    "/sessions/{session_id}/messages",
    response_model=MessageList,
    summary="Chat history (oldest first), with citations",
    responses=error_responses(404),
)
async def list_messages(session_id: uuid.UUID, db: DB, limit: Limit = 20, offset: Offset = 0):
    await _session_or_404(db, session_id)
    total = await db.scalar(select(func.count()).where(Message.session_id == session_id))
    msgs = (
        await db.scalars(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at, Message.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    usage = await usage_by_message(db, [m.id for m in msgs])
    return MessageList(
        items=[message_out(m, usage.get(m.id)) for m in msgs],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def _prepare(session_id: uuid.UUID, body: AskRequest, db: DB) -> PreparedAsk:
    """Runs before any response is sent, so scope errors are normal HTTP errors."""
    return await prepare_ask(db, session_id, body.content)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=AskResponse,
    summary="Ask a question (complete JSON answer)",
    responses=error_responses(
        404,
        409,
        422,
        429,
        503,
    ),
)
async def ask(prep: Annotated[PreparedAsk, Depends(_prepare)]):
    """Runs the full RAG pipeline and returns the user message plus the assistant message with
    server-validated citations. `answer_status`: `answered` (≥ 1 valid citation), `not_found`
    (the model said the sources don't contain the answer), `unsupported` (an answer without any
    valid citation). AI failures return the error envelope (e.g. `429 AI_BUDGET_EXCEEDED`); the
    failed attempt is kept in history with `answer_status: error`."""
    user, assistant = await ask_json(prep)
    return AskResponse(
        session_id=prep.session_id,
        ai_mode=get_settings().ai_mode,
        user_message=user,
        assistant_message=assistant,
    )


_STREAM_DOC = """Server-Sent Events, in order:

- `meta`: `{session_id, user_message_id, assistant_message_id, standalone_query,
  scope_document_ids, ai_mode}`
- `token` (repeated): `{delta}`
- `citations`: `{citations: [...]}` (validated; same shape as in the message)
- `done`: `{message, answer_status, interrupted, usage, latency_ms}`; `message.content` is the
  final text with invalid markers removed (replace the streamed text with it)
- `error` (instead of the rest): `{code, message, status, details, message_id}`

Comment lines `: ping` are sent every 15 s while idle. Scope errors (404/409/422) are returned
as normal JSON errors before the stream starts. If the client disconnects, generation stops at
the next token and the partial answer is saved with `interrupted: true`."""


@router.post(
    "/sessions/{session_id}/messages/stream",
    response_class=EventSourceResponse,
    summary="Ask a question (streamed over SSE)",
    description=_STREAM_DOC,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: meta\ndata: {"assistant_message_id": "…"}\n\n'
                    'event: token\ndata: {"delta": "The budget is "}\n\n'
                    'event: token\ndata: {"delta": "$4.2M [S1]."}\n\n'
                    'event: citations\ndata: {"citations": [{"marker": "S1", "…": "…"}]}\n\n'
                    'event: done\ndata: {"answer_status": "answered", "…": "…"}\n\n'
                }
            }
        },
        **_NOT_READY,
    },
)
async def ask_stream(
    prep: Annotated[PreparedAsk, Depends(_prepare)],
) -> AsyncIterator[ServerSentEvent]:
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    stop = asyncio.Event()

    async def run() -> None:
        # Owned by the event loop, not the request: a disconnect cancels the response
        # generator below but this task keeps going long enough to save the partial answer.
        try:
            async for event in answer_events(prep, stop):
                await queue.put(event)
        except Exception:
            log.exception("stream pipeline crashed")
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred.",
                        "status": 500,
                        "details": {},
                        "message_id": None,
                    },
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)
    try:
        while (event := await queue.get()) is not None:
            yield ServerSentEvent(event=event["event"], data=event["data"])
    finally:
        stop.set()
