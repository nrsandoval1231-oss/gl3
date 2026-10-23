"""Persist deterministic retained-evidence packages and advisory receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041_evidence_packages"
down_revision = "0040_project_region_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_key", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("need_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("question_contract", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("processing_status", sa.String(length=24), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("logical_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "processing_status IN ('PREPARED', 'COMPLETE_ADVISORY', 'INCOMPLETE', 'BLOCKED')",
            name="ck_evidence_package_processing_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["need_id"], ["power_needs.id"]),
        sa.ForeignKeyConstraint(["logical_call_id"], ["logical_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_key", name="uq_evidence_package_key"),
    )
    op.create_index(
        "ix_evidence_package_evidence", "evidence_packages", ["evidence_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_package_evidence", table_name="evidence_packages")
    op.drop_table("evidence_packages")
