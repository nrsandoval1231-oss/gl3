"""asset-aware project lifecycle history

Revision ID: 0005_asset_lifecycles
Revises: 0004_unknown_publication_dates
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_asset_lifecycles"
down_revision = "0004_unknown_publication_dates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("asset_type", sa.String(60), server_default="unknown", nullable=False))
    op.create_table(
        "project_lifecycles",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("current_state", sa.String(80), nullable=False),
        sa.Column("expected_next_milestone", sa.Text()),
        sa.Column("expected_power_event", sa.Text()),
        sa.Column("time_to_power_start", sa.Date()), sa.Column("time_to_power_end", sa.Date()),
        sa.Column("estimate_basis", postgresql.JSONB()), sa.Column("estimate_version", sa.String(50)),
        sa.Column("open_questions", postgresql.JSONB(), nullable=False),
        sa.Column("monitoring_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "lifecycle_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("state", sa.String(80), nullable=False),
        sa.Column("value_kind", sa.String(20), server_default="reported", nullable=False),
        sa.Column("occurred_on", sa.Date()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "observation_id", "event_type", "state", name="uq_lifecycle_event_replay"),
    )
    op.create_table(
        "project_match_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("candidate_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("matched_facts", postgresql.JSONB(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("observation_id", "candidate_project_id", name="uq_project_match_candidate"),
    )


def downgrade() -> None:
    op.drop_table("project_match_decisions"); op.drop_table("lifecycle_events")
    op.drop_table("project_lifecycles"); op.drop_column("projects", "asset_type")
