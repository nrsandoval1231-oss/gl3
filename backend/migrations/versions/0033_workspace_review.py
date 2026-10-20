"""Persist the workspace review baseline and exact displayed acknowledgments."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_workspace_review"
down_revision = "0032_power_need_titles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_change_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_identity", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_token", sa.String(64), nullable=True),
        sa.Column("last_receipt", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_workspace_change_baseline_singleton"),
    )
    op.create_table(
        "workspace_change_acknowledgments",
        sa.Column("event_key", sa.String(64), primary_key=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_token", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_workspace_change_ack_reviewed_at",
        "workspace_change_acknowledgments",
        ["reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_change_ack_reviewed_at",
        table_name="workspace_change_acknowledgments",
    )
    op.drop_table("workspace_change_acknowledgments")
    op.drop_table("workspace_change_baselines")
