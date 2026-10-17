"""Add AI-drafted market newsletter storage and its own daily request budget."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_market_newsletters"
down_revision = "0019_editorial_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_newsletters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("policy_version", sa.String(60), nullable=False),
        sa.Column("schema_version", sa.String(60), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("coverage", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_market_newsletter_live_fingerprint",
        "market_newsletters",
        ["input_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'generating', 'draft', 'approved')"),
    )
    op.create_table(
        "market_newsletter_budgets",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("reserved_requests", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("market_newsletter_budgets")
    op.drop_index("uq_market_newsletter_live_fingerprint", table_name="market_newsletters")
    op.drop_table("market_newsletters")
