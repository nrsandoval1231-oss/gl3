"""Append-only operator corrections for project-scoped buying-chain claims."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_buying_chain_corrections"
down_revision = "0035_reconciled_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buying_chain_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buying_chain_claims.id"),
            nullable=False,
        ),
        sa.Column("expected_version", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column(
            "values", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "source_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buying_chain_evidence.id"),
        ),
        sa.Column("source_version_hash", sa.String(64)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("action IN ('correct', 'retract')", name="ck_buying_correction_action"),
        sa.UniqueConstraint("claim_id", "idempotency_key", name="uq_buying_correction_idempotency"),
    )
    op.create_index(
        "ix_buying_correction_project_claim",
        "buying_chain_corrections",
        ["project_id", "claim_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_buying_correction_project_claim", table_name="buying_chain_corrections")
    op.drop_table("buying_chain_corrections")
