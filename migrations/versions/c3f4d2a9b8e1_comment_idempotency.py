"""add idempotency keys to comments

Revision ID: c3f4d2a9b8e1
Revises: ab314f2c908e
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f4d2a9b8e1"
down_revision: str | None = "ab314f2c908e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("comments") as batch_op:
        batch_op.add_column(sa.Column("client_request_id", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_comments_asset_client_request",
            ["asset_id", "client_request_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("comments") as batch_op:
        batch_op.drop_constraint("uq_comments_asset_client_request", type_="unique")
        batch_op.drop_column("client_request_id")
