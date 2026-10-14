import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.documents import Page

SESSION_ID = "3d5e7f9a-1b2c-4d6e-8f0a-2b4c6d8e0f1a"
DOC_ID = "6f1c2a9e-3b7d-4c2e-9a51-0d8e4b7f2c10"


class SessionCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"document_ids": [DOC_ID], "scope_mode": "documents", "title": "Falcon budget"},
                {"scope_mode": "all"},
            ]
        }
    )

    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    scope_mode: Literal["documents", "all"] = Field(
        default="documents",
        description="`documents`: only the session's documents; `all`: every chat-ready document",
    )
    title: str | None = Field(default=None, min_length=1, max_length=200)


class SessionUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"title": "Renamed", "add_document_ids": [DOC_ID], "remove_document_ids": []}
        }
    )

    title: str | None = Field(default=None, min_length=1, max_length=200)
    scope_mode: Literal["documents", "all"] | None = None
    add_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    remove_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class SessionDocument(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    chat_ready: bool
    added_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": SESSION_ID,
                "title": "What is the approved budget?",
                "scope_mode": "documents",
                "documents": [
                    {
                        "id": DOC_ID,
                        "filename": "falcon-plan.pdf",
                        "status": "ready",
                        "chat_ready": True,
                        "added_at": "2026-10-15T09:13:00Z",
                    }
                ],
                "message_count": 4,
                "created_at": "2026-10-15T09:13:00Z",
                "updated_at": "2026-10-15T09:15:41Z",
            }
        }
    )

    id: uuid.UUID
    title: str
    scope_mode: str
    documents: list[SessionDocument]
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionList(Page):
    items: list[SessionOut]


class CitationOut(BaseModel):
    marker: str = Field(description="Marker used in the answer text, e.g. S1")
    document_id: uuid.UUID | None = Field(description="Null if the document was deleted later")
    document_name: str
    locator: dict[str, Any] = Field(description='e.g. {"type":"page","page":3}')
    location: str = Field(description='Human-readable locator, e.g. "page 3"')
    excerpt: str = Field(description="Original stored text of the cited chunk (not model text)")
    chunk_id: uuid.UUID | None
    score: float | None = Field(description="Cosine similarity of the chunk (null if FTS-only)")


class Latency(BaseModel):
    first_token: int | None = None
    total: int | None = None


class UsageOut(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class MessageOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
                "session_id": SESSION_ID,
                "role": "assistant",
                "content": "The total approved budget for Project Falcon is $4.2M [S1].",
                "answer_status": "answered",
                "interrupted": False,
                "error_code": None,
                "standalone_query": "What is the approved budget for Project Falcon?",
                "scope_document_ids": [DOC_ID],
                "citations": [
                    {
                        "marker": "S1",
                        "document_id": DOC_ID,
                        "document_name": "falcon-plan.pdf",
                        "locator": {"type": "page", "page": 3},
                        "location": "page 3",
                        "excerpt": "The total approved budget for Project Falcon is 4.2 million…",
                        "chunk_id": "1f2e3d4c-5b6a-4978-8a9b-0c1d2e3f4a5b",
                        "score": 0.82,
                    }
                ],
                "model": "gpt-4o-mini",
                "prompt_version": "chat.answer.v1",
                "ai_mode": "openai",
                "latency_ms": {"first_token": 640, "total": 2310},
                "usage": {
                    "input_tokens": 3120,
                    "output_tokens": 180,
                    "estimated_cost_usd": 0.00058,
                },
                "created_at": "2026-10-15T09:15:41Z",
            }
        }
    )

    id: uuid.UUID
    session_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    answer_status: str | None = Field(
        description="assistant only: answered | not_found | unsupported | error"
    )
    interrupted: bool
    error_code: str | None
    standalone_query: str | None
    scope_document_ids: list[uuid.UUID]
    citations: list[CitationOut]
    model: str | None
    prompt_version: str | None
    ai_mode: Literal["openai", "fake"] | None
    latency_ms: Latency
    usage: UsageOut
    created_at: datetime


class MessageList(Page):
    items: list[MessageOut]


class AskRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"content": "What is the approved budget?"}}
    )

    content: str = Field(min_length=1, max_length=4000)


class AskResponse(BaseModel):
    session_id: uuid.UUID
    ai_mode: Literal["openai", "fake"]
    user_message: MessageOut
    assistant_message: MessageOut
