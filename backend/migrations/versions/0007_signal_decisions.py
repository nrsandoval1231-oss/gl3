"""Persist versioned Signal display decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_signal_decisions"
down_revision = "0006_lifecycle_identity_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=True),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "adjudicated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("signal_decisions")
