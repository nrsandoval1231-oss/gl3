"""Persist advisory evidence-grounded power-need titles."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_power_need_titles"
down_revision = "0031_research_browse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "power_need_titles",
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            primary_key=True,
        ),
        sa.Column("requested_fingerprint", sa.String(64)),
        sa.Column("generated_fingerprint", sa.String(64)),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="unavailable"),
        sa.Column("result", postgresql.JSONB),
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("error", sa.String(80)),
    )
    op.create_table(
        "power_need_title_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=False),
        sa.Column("citations", postgresql.JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
    )
    op.create_index(
        "ix_power_need_title_versions_need_id", "power_need_title_versions", ["need_id"]
    )
    # A title policy change requires the canonical browse generation to be rebuilt.
    op.execute("UPDATE browse_state SET input_revision = input_revision + 1 WHERE id = 1")


def downgrade() -> None:
    op.drop_index("ix_power_need_title_versions_need_id", table_name="power_need_title_versions")
    op.drop_table("power_need_title_versions")
    op.drop_table("power_need_titles")
