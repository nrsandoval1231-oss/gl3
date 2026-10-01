"""Persist bounded power-pursuit research and private call outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_power_pursuits"
down_revision = "0009_signal_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("kind", sa.String(30), nullable=False, server_default="ingestion")
    )
    op.create_table(
        "pursuits",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("identity_key", sa.String(length=220), nullable=False),
        sa.Column("project_id", postgresql.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("project_ids", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("last_researched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("research_status", sa.String(length=30), nullable=False),
        sa.Column("research_errors", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("identity_key", name=None),
    )
    op.create_table(
        "pursuit_documents",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(), sa.ForeignKey("pursuits.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "pursuit_id", "url", "content_hash", name="uq_pursuit_document_version"
        ),
    )
    op.create_table(
        "pursuit_research_runs",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(), sa.ForeignKey("pursuits.id"), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("fetch_count", sa.Integer(), nullable=False),
        sa.Column("model_count", sa.Integer(), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "pursuit_call_notes",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(), sa.ForeignKey("pursuits.id"), nullable=False),
        sa.Column("client_id", postgresql.UUID(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("follow_up", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("pursuit_id", "client_id", name="uq_pursuit_note_request"),
    )


def downgrade() -> None:
    op.drop_table("pursuit_call_notes")
    op.drop_table("pursuit_research_runs")
    op.drop_table("pursuit_documents")
    op.drop_table("pursuits")
    op.drop_column("jobs", "kind")
