"""initial schema: documents, segments, chunks (pgvector HNSW + GIN tsv), insights,
processing runs, chat sessions/messages/citations, AI call ledger.

Revision ID: 0001
Revises:
Create Date: 2026-10-14 19:58:15.310714
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_calls_created_at", "ai_calls", ["created_at"], unique=False)
    op.create_index(op.f("ix_ai_calls_document_id"), "ai_calls", ["document_id"], unique=False)
    op.create_index(op.f("ix_ai_calls_message_id"), "ai_calls", ["message_id"], unique=False)
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("title_is_custom", sa.Boolean(), nullable=False),
        sa.Column("scope_mode", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("extract_status", sa.String(length=16), nullable=False),
        sa.Column("index_status", sa.String(length=16), nullable=False),
        sa.Column("insights_status", sa.String(length=16), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chat_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_table(
        "chat_session_documents",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "document_id"),
    )
    op.create_table(
        "document_insights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("summary_short", sa.Text(), nullable=False),
        sa.Column("summary_detailed", sa.Text(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("topics", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("sentiment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("suggested_questions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "prompt_version"),
    )
    op.create_table(
        "document_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "ordinal"),
    )
    op.create_index(
        op.f("ix_document_segments_document_id"), "document_segments", ["document_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer_status", sa.String(length=16), nullable=True),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("standalone_query", sa.Text(), nullable=True),
        sa.Column("scope_document_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("retrieval", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_session_created", "messages", ["session_id", "created_at"], unique=False
    )
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_processing_runs_document_id"), "processing_runs", ["document_id"], unique=False
    )
    op.create_index(
        "ix_processing_runs_started_at", "processing_runs", ["started_at"], unique=False
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["document_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_page_number", "chunks", ["page_number"], unique=False)
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "message_citations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("marker", sa.String(length=16), nullable=False),
        sa.Column("marker_index", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("document_name", sa.String(length=512), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("score", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_message_citations_message_id"), "message_citations", ["message_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_message_citations_message_id"), table_name="message_citations")
    op.drop_table("message_citations")
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_page_number", table_name="chunks")
    op.drop_index(
        "ix_chunks_embedding_hnsw",
        table_name="chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_processing_runs_started_at", table_name="processing_runs")
    op.drop_index(op.f("ix_processing_runs_document_id"), table_name="processing_runs")
    op.drop_table("processing_runs")
    op.drop_index("ix_messages_session_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_document_segments_document_id"), table_name="document_segments")
    op.drop_table("document_segments")
    op.drop_table("document_insights")
    op.drop_table("chat_session_documents")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_table("chat_sessions")
    op.drop_index(op.f("ix_ai_calls_message_id"), table_name="ai_calls")
    op.drop_index(op.f("ix_ai_calls_document_id"), table_name="ai_calls")
    op.drop_index("ix_ai_calls_created_at", table_name="ai_calls")
    op.drop_table("ai_calls")
    # The vector extension is left installed: other database objects may depend on it.
