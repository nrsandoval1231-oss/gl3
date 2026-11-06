"""Add owner-managed commercial pursuits, follow-up tasks and activity."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_commercial_pursuits"
down_revision = "0049_scoped_identity_browse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_pursuits",
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
        sa.Column("stage", sa.String(20), nullable=False, server_default="New"),
        sa.Column("owner", sa.String(100)),
        sa.Column(
            "stage_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("need_id", name="uq_commercial_pursuit_need"),
        sa.CheckConstraint(
            "stage IN ('New','Contacted','Engaged','Proposal','Won','Lost')",
            name="ck_commercial_pursuit_stage",
        ),
    )
    op.create_table(
        "pursuit_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pursuit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commercial_pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_pursuit_tasks_pursuit_open", "pursuit_tasks", ["pursuit_id", "completed_at"]
    )
    op.create_table(
        "pursuit_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pursuit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commercial_pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", postgresql.UUID(as_uuid=True)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("pursuit_id", "client_id", name="uq_pursuit_activity_client"),
    )
    op.create_index(
        "ix_pursuit_activity_pursuit_time", "pursuit_activity", ["pursuit_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_table("pursuit_activity")
    op.drop_table("pursuit_tasks")
    op.drop_table("commercial_pursuits")
