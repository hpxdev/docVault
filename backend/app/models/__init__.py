"""SQLAlchemy 2 ORM models. Postgres is the single source of truth."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIMENSIONS = 1536


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(16))  # pdf | docx | md | txt
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_path: Mapped[str] = mapped_column(String(1024))
    page_count: Mapped[int | None] = mapped_column(Integer)
    segment_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    extract_status: Mapped[str] = mapped_column(String(16), default="pending")
    index_status: Mapped[str] = mapped_column(String(16), default="pending")
    insights_status: Mapped[str] = mapped_column(String(16), default="pending")
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    chat_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Versions: every document belongs to a group (its own id for version 1); exactly one
    # document per group is the latest (partial unique index in migration 0002).
    version_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        Index("ix_documents_created_at", "created_at"),
        Index("ix_documents_version_group_id", "version_group_id"),
        UniqueConstraint("version_group_id", "version", name="uq_documents_group_version"),
        Index(
            "uq_documents_group_latest",
            "version_group_id",
            unique=True,
            postgresql_where=sql_text("is_latest"),
        ),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("version_group_id", kwargs["id"])
        super().__init__(**kwargs)


class DocumentSegment(Base):
    __tablename__ = "document_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_segments.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB)
    page_number: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str] = mapped_column(String(128))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_page_number", "page_number"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class DocumentInsights(Base):
    __tablename__ = "document_insights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    prompt_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    summary_short: Mapped[str] = mapped_column(Text)
    summary_detailed: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    entities: Mapped[dict[str, Any]] = mapped_column(JSONB)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text))
    category: Mapped[str] = mapped_column(String(32))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    sentiment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    suggested_questions: Mapped[list[str]] = mapped_column(ARRAY(Text))
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("document_id", "prompt_version"),)


class DocumentSummary(Base):
    """On-demand summary with user options (length, tone, focus). Cached by those options."""

    __tablename__ = "document_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    params_key: Mapped[str] = mapped_column(String(64))  # sha256 of the normalised options
    length: Mapped[str] = mapped_column(String(16))
    tone: Mapped[str] = mapped_column(String(16))
    focus: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    focus_covered: Mapped[bool | None] = mapped_column(Boolean)
    # Focus topics the document does not address (summary.custom.v2 onwards).
    focus_not_addressed: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("document_id", "params_key", "prompt_version", "model"),)


class DocumentComparison(Base):
    """Comparative analysis of 2–4 documents. No FKs: the document list is a snapshot; rows that
    include a deleted document are removed with it (see the delete endpoint)."""

    __tablename__ = "document_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{id, label, filename, …}]
    params_key: Mapped[str] = mapped_column(String(64))
    focus: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("params_key", "prompt_version", "model"),
        Index("ix_document_comparisons_document_ids", "document_ids", postgresql_using="gin"),
        Index("ix_document_comparisons_created_at", "created_at"),
    )


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(16))  # extract | index | insights
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # running | succeeded | failed | retrying | skipped
    status: Mapped[str] = mapped_column(String(16))
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_processing_runs_started_at", "started_at"),)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    title_is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    scope_mode: Mapped[str] = mapped_column(String(16), default="documents")  # documents | all
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document_links: Mapped[list["ChatSessionDocument"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ChatSessionDocument.added_at"
    )


class ChatSessionDocument(Base):
    __tablename__ = "chat_session_documents"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # answered | not_found | unsupported | error (assistant only)
    answer_status: Mapped[str | None] = mapped_column(String(16))
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    standalone_query: Mapped[str | None] = mapped_column(Text)
    scope_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    retrieval: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    citations: Mapped[list["MessageCitation"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="MessageCitation.marker_index"
    )

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    marker: Mapped[str] = mapped_column(String(16))  # "S1"
    marker_index: Mapped[int] = mapped_column(Integer)  # 1 (for ordering)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    # Snapshot fields: survive deletion of the document/chunk.
    document_name: Mapped[str] = mapped_column(String(512))
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB)
    excerpt: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column()


class AICall(Base):
    """Ledger of every AI provider call. No FKs: spend must survive deletions."""

    __tablename__ = "ai_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purpose: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), default=Decimal(0))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # succeeded | failed
    error_code: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    __table_args__ = (Index("ix_ai_calls_created_at", "created_at"),)
