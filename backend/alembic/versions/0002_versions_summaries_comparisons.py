"""document versions, custom summaries, document comparisons.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing documents become version 1 of their own group.
    op.add_column("documents", sa.Column("version_group_id", sa.UUID(), nullable=True))
    op.execute("UPDATE documents SET version_group_id = id")
    op.alter_column("documents", "version_group_id", nullable=False)
    op.add_column(
        "documents", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "documents", sa.Column("is_latest", sa.Boolean(), server_default="true", nullable=False)
    )
    op.create_index("ix_documents_version_group_id", "documents", ["version_group_id"])
    op.create_unique_constraint(
        "uq_documents_group_version", "documents", ["version_group_id", "version"]
    )
    op.create_index(
        "uq_documents_group_latest",
        "documents",
        ["version_group_id"],
        unique=True,
        postgresql_where=sa.text("is_latest"),
    )

    op.create_table(
        "document_summaries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("params_key", sa.String(length=64), nullable=False),
        sa.Column("length", sa.String(length=16), nullable=False),
        sa.Column("tone", sa.String(length=16), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("focus_covered", sa.Boolean(), nullable=True),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "params_key", "prompt_version", "model"),
    )
    op.create_index(
        op.f("ix_document_summaries_document_id"), "document_summaries", ["document_id"]
    )

    op.create_table(
        "document_comparisons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("documents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params_key", sa.String(length=64), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("params_key", "prompt_version", "model"),
    )
    op.create_index(
        "ix_document_comparisons_document_ids",
        "document_comparisons",
        ["document_ids"],
        postgresql_using="gin",
    )
    op.create_index("ix_document_comparisons_created_at", "document_comparisons", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_comparisons_created_at", table_name="document_comparisons")
    op.drop_index(
        "ix_document_comparisons_document_ids",
        table_name="document_comparisons",
        postgresql_using="gin",
    )
    op.drop_table("document_comparisons")
    op.drop_index(op.f("ix_document_summaries_document_id"), table_name="document_summaries")
    op.drop_table("document_summaries")
    op.drop_index("uq_documents_group_latest", table_name="documents")
    op.drop_constraint("uq_documents_group_version", "documents", type_="unique")
    op.drop_index("ix_documents_version_group_id", table_name="documents")
    op.drop_column("documents", "is_latest")
    op.drop_column("documents", "version")
    op.drop_column("documents", "version_group_id")
