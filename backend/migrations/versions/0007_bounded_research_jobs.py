"""Add bounded research jobs and source-bound project roles.

Revision ID: 0007_bounded_research_jobs
Revises: 0006_lifecycle_identity_versions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_bounded_research_jobs"
down_revision = "0006_lifecycle_identity_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("kind", sa.String(20), server_default="ingestion", nullable=False)
    )
    op.alter_column("jobs", "source_id", existing_type=sa.String(100), nullable=True)
    op.create_check_constraint(
        "ck_jobs_kind_source",
        "jobs",
        "(kind = 'ingestion' AND source_id IS NOT NULL) "
        "OR (kind = 'research' AND source_id IS NULL)",
    )
    op.create_table(
        "research_jobs",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column("target_fact", sa.String(60), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("max_sources", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_requests", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_seconds", sa.Integer(), server_default="20", nullable=False),
        sa.Column("max_spend_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("history", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("unresolved_reason", sa.Text()),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("need_id", "target_fact", name="uq_research_need_fact"),
        sa.CheckConstraint(
            "max_sources = 1 AND max_requests = 1 AND max_seconds BETWEEN 1 AND 20 "
            "AND max_spend_cents = 0",
            name="ck_research_job_limits",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'unresolved')",
            name="ck_research_job_status",
        ),
    )
    op.create_table(
        "research_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_jobs.job_id"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("source_date", sa.Date()),
        sa.Column(
            "retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("extraction_location", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("relationship", sa.String(40)),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_research_evidence_version"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False, unique=True),
    )
    op.create_table(
        "project_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column(
            "evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_evidence.id"),
            nullable=False,
        ),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.UniqueConstraint(
            "project_id",
            "need_id",
            "organization_id",
            "role",
            "evidence_id",
            name="uq_project_role_evidence",
        ),
    )


def downgrade() -> None:
    op.drop_table("project_roles")
    op.drop_table("organizations")
    op.drop_table("research_evidence")
    op.drop_table("research_jobs")
    op.drop_constraint("ck_jobs_kind_source", "jobs", type_="check")
    op.alter_column("jobs", "source_id", existing_type=sa.String(100), nullable=False)
    op.drop_column("jobs", "kind")
