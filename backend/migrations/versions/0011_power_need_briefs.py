"""Persist per-need advisory brief state and bounded request budget."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_power_need_briefs"
down_revision = "0010_power_pursuits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("target_id", postgresql.UUID(), nullable=True))
    op.create_table(
        "power_need_briefs",
        sa.Column("need_id", postgresql.UUID(), sa.ForeignKey("power_needs.id"), primary_key=True),
        sa.Column("requested_fingerprint", sa.String(64), nullable=True),
        sa.Column("generated_fingerprint", sa.String(64), nullable=True),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(80), nullable=True),
    )
    op.create_table(
        "power_need_brief_versions",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("need_id", postgresql.UUID(), sa.ForeignKey("power_needs.id"), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
    )
    op.create_table(
        "brief_daily_budgets",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("reserved_requests", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("brief_daily_budgets")
    op.drop_table("power_need_brief_versions")
    op.drop_table("power_need_briefs")
    op.drop_column("jobs", "target_id")
