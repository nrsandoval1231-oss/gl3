"""Add append-only exact-need fact and workflow-status events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_call_fact_versions"
down_revision = "0016_operational_schedule"
branch_labels = None
depends_on = None


def _immutable_trigger(table: str) -> None:
    op.execute(
        f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()"""
    )


def upgrade() -> None:
    op.execute(
        """CREATE FUNCTION reject_immutable_history_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'append-only history cannot be updated or deleted'; END;
        $$ LANGUAGE plpgsql"""
    )
    op.create_table(
        "call_fact_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pursuits.id")),
        sa.Column("predecessor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_key", sa.String(100), nullable=False),
        sa.Column("facility_scope", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(40), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("reporter_name", sa.String(160), nullable=False),
        sa.Column("reporter_organization", sa.String(200)),
        sa.Column("reporter_role", sa.String(160)),
        sa.Column("confirmation_channel", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("source_date", sa.Date()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("need_id", "client_id", name="uq_call_fact_version_request"),
    )
    op.create_index("ix_call_fact_version_scope", "call_fact_versions", ["need_id", "created_at"])
    _immutable_trigger("call_fact_versions")
    op.create_table(
        "call_fact_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column(
            "fact_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_fact_versions.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("need_id", "version", name="uq_call_fact_decision_version"),
        sa.UniqueConstraint("need_id", "client_id", name="uq_call_fact_decision_request"),
    )
    op.create_index("ix_call_fact_decision_need", "call_fact_decisions", ["need_id", "version"])
    _immutable_trigger("call_fact_decisions")
    op.create_table(
        "need_workflow_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pursuits.id")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("previous_status", sa.String(24)),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("need_id", "version", name="uq_need_workflow_status_version"),
        sa.UniqueConstraint("need_id", "client_id", name="uq_need_workflow_status_request"),
    )
    op.create_index(
        "ix_need_workflow_status_need", "need_workflow_status_events", ["need_id", "version"]
    )
    _immutable_trigger("need_workflow_status_events")


def downgrade() -> None:
    for table in ("need_workflow_status_events", "call_fact_decisions", "call_fact_versions"):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.drop_table(table)
    op.execute("DROP FUNCTION reject_immutable_history_mutation()")
