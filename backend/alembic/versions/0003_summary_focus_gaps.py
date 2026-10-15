"""document_summaries.focus_not_addressed (summary.custom.v2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_summaries",
        sa.Column(
            "focus_not_addressed",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_summaries", "focus_not_addressed")
