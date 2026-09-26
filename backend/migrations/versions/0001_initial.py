"""Initial frozen PostgreSQL schema for structured ingestion."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("family", sa.String(50), nullable=False),
        sa.Column("geography", sa.String(100), nullable=False),
        sa.Column("industries", postgresql.JSONB(), nullable=False),
        sa.Column("retrieval_method", sa.String(50), nullable=False),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("health", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.Text()),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("error", sa.Text()),
    )
    op.create_table(
        "observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text()),
        sa.Column("published_at", sa.Date(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_id", "external_id", name="uq_observation_source_external"),
    )
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_key", sa.String(220), unique=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
    )
    op.create_table(
        "power_needs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("activity_key", sa.String(100), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("required_mw", sa.String(100)),
        sa.Column("start_window", sa.String(100)),
        sa.Column("duration", sa.String(100)),
        sa.Column("supply", sa.String(30), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "activity_key", name="uq_need_project_activity"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("extraction_location", sa.String(100), nullable=False),
        sa.Column("event_date", sa.Date()),
        sa.UniqueConstraint("observation_id", "content_hash", name="uq_evidence_version"),
    )
    op.create_table(
        "need_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "need_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("power_needs.id"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("need_id", "observation_id", name="uq_need_observation"),
    )
    op.create_table(
        "change_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("observation_id", "content_hash", name="uq_change_version"),
    )


def downgrade() -> None:
    op.drop_table("change_events")
    op.drop_table("need_observations")
    op.drop_table("evidence")
    op.drop_table("power_needs")
    op.drop_table("projects")
    op.drop_table("observations")
    op.drop_table("jobs")
    op.drop_table("sources")
