"""Append-only privacy suppressions for stable contact subjects and methods."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_contact_suppressions"
down_revision = "0044_enrichment_planner_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("subject_key", sa.String(64), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('company', 'person', 'method')", name="ck_contact_suppression_scope"),
        sa.CheckConstraint("action IN ('suppress', 'reinstate')", name="ck_contact_suppression_action"),
        sa.CheckConstraint("version = expected_version + 1", name="ck_contact_suppression_version"),
        sa.UniqueConstraint("scope", "subject_key", "idempotency_key", name="uq_contact_suppression_idempotency"),
        sa.UniqueConstraint("scope", "subject_key", "version", name="uq_contact_suppression_version"),
    )
    op.create_index("ix_contact_suppression_subject", "contact_suppressions", ["scope", "subject_key", "version"])


def downgrade() -> None:
    op.drop_index("ix_contact_suppression_subject", table_name="contact_suppressions")
    op.drop_table("contact_suppressions")
