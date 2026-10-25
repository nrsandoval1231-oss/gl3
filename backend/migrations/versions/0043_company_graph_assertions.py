"""Evidence-bound, correctable company relationships for the canonical graph."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_company_graph_assertions"
down_revision = "0042_external_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_relationship_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(20), nullable=False),
        sa.Column("source_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "relationship_type IN ('parent', 'subsidiary', 'developer', 'operator', 'epc', 'gc', 'utility')",
            name="ck_company_relationship_type",
        ),
        sa.CheckConstraint(
            "source_company_id <> target_company_id", name="ck_company_relationship_distinct"
        ),
        sa.ForeignKeyConstraint(["source_company_id"], ["company_identities.id"]),
        sa.ForeignKeyConstraint(["target_company_id"], ["company_identities.id"]),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["buying_chain_evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_company_relationship_idempotency"),
    )
    op.create_index(
        "ix_company_relationship_source",
        "company_relationship_assertions",
        ["source_company_id", "created_at"],
    )
    op.create_index(
        "ix_company_relationship_target",
        "company_relationship_assertions",
        ["target_company_id", "created_at"],
    )
    op.create_table(
        "company_relationship_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assertion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('retract', 'suppress', 'reinstate')",
            name="ck_company_relationship_correction_action",
        ),
        sa.ForeignKeyConstraint(["assertion_id"], ["company_relationship_assertions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assertion_id", "idempotency_key", name="uq_company_relationship_correction_idempotency"
        ),
        sa.UniqueConstraint(
            "assertion_id", "version", name="uq_company_relationship_correction_version"
        ),
    )
    op.create_index(
        "ix_company_relationship_correction_history",
        "company_relationship_corrections",
        ["assertion_id", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_relationship_correction_history", table_name="company_relationship_corrections"
    )
    op.drop_table("company_relationship_corrections")
    op.drop_index("ix_company_relationship_target", table_name="company_relationship_assertions")
    op.drop_index("ix_company_relationship_source", table_name="company_relationship_assertions")
    op.drop_table("company_relationship_assertions")
