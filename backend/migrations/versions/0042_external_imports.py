"""Retain immutable external workbook rows and reversible staging history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042_external_imports"
down_revision = "0041_evidence_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash", name="uq_external_import_content_hash"),
    )
    op.create_table(
        "external_import_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sheet", sa.String(120), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_kind", sa.String(20), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("match_status", sa.String(16), nullable=False),
        sa.Column("company_match", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("project_match", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "match_status IN ('matched', 'ambiguous', 'unmatched', 'invalid', 'ignored')",
            name="ck_external_import_match_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["external_import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "sheet", "row_number", name="uq_external_import_row"),
    )
    op.create_index(
        "ix_external_import_rows_batch", "external_import_rows", ["batch_id", "sheet", "row_number"]
    )
    op.create_table(
        "external_import_activations",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("changed_by", sa.String(120), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["row_id"], ["external_import_rows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("row_id"),
    )
    op.create_table(
        "external_import_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('staged', 'rolled_back')", name="ck_external_import_event_action"
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["external_import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "action", name="uq_external_import_event_batch_action"),
    )
    op.create_index(
        "ix_external_import_events_batch", "external_import_events", ["batch_id", "created_at"]
    )

    # These tables are the raw, original evidence and audit ledger. Corrections
    # belong in the separate activation projection and must never rewrite them.
    op.execute(
        """
        CREATE FUNCTION reject_external_import_immutable_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'external import source rows and events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER external_import_rows_immutable
            BEFORE UPDATE OR DELETE ON external_import_rows
            FOR EACH ROW EXECUTE FUNCTION reject_external_import_immutable_mutation();
        CREATE TRIGGER external_import_events_immutable
            BEFORE UPDATE OR DELETE ON external_import_events
            FOR EACH ROW EXECUTE FUNCTION reject_external_import_immutable_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS external_import_events_immutable ON external_import_events")
    op.execute("DROP TRIGGER IF EXISTS external_import_rows_immutable ON external_import_rows")
    op.execute("DROP FUNCTION IF EXISTS reject_external_import_immutable_mutation()")
    op.drop_index("ix_external_import_events_batch", table_name="external_import_events")
    op.drop_table("external_import_events")
    op.drop_table("external_import_activations")
    op.drop_index("ix_external_import_rows_batch", table_name="external_import_rows")
    op.drop_table("external_import_rows")
    op.drop_table("external_import_batches")
