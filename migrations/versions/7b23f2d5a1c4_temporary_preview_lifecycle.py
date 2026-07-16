"""temporary preview lifecycle and revision tasks

Revision ID: 7b23f2d5a1c4
Revises: c62d0d7ba68b
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b23f2d5a1c4"
down_revision: str | None = "c62d0d7ba68b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("asset_versions", sa.Column("preview_delete_after", sa.DateTime(), nullable=True))
    op.add_column("asset_versions", sa.Column("preview_deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_asset_versions_preview_delete_after", "asset_versions", ["preview_delete_after"], unique=False)
    op.create_table(
        "revision_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revision_tasks_asset_id", "revision_tasks", ["asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_revision_tasks_asset_id", table_name="revision_tasks")
    op.drop_table("revision_tasks")
    op.drop_index("ix_asset_versions_preview_delete_after", table_name="asset_versions")
    op.drop_column("asset_versions", "preview_deleted_at")
    op.drop_column("asset_versions", "preview_delete_after")
    op.drop_column("assets", "approved_at")
