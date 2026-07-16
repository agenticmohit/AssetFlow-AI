"""persist AI request rate limits

Revision ID: ab314f2c908e
Revises: 7b23f2d5a1c4
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab314f2c908e"
down_revision: str | None = "7b23f2d5a1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_request_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_request_logs_action", "ai_request_logs", ["action"], unique=False)
    op.create_index("ix_ai_request_logs_asset_id", "ai_request_logs", ["asset_id"], unique=False)
    op.create_index("ix_ai_request_logs_created_at", "ai_request_logs", ["created_at"], unique=False)
    op.create_index("ix_ai_request_logs_user_id", "ai_request_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_request_logs_user_id", table_name="ai_request_logs")
    op.drop_index("ix_ai_request_logs_created_at", table_name="ai_request_logs")
    op.drop_index("ix_ai_request_logs_asset_id", table_name="ai_request_logs")
    op.drop_index("ix_ai_request_logs_action", table_name="ai_request_logs")
    op.drop_table("ai_request_logs")
