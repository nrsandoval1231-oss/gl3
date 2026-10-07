"""Persist source operation epochs, due occurrences, receipts and worker health."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_operational_schedule"
down_revision = "0015_revocable_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("registry_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_table(
        "source_schedule_epochs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("registry_enabled", sa.Boolean(), nullable=False),
        sa.Column("operator_enabled", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
        sa.Column("schedule_mode", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("anchor", postgresql.JSONB(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("history_known", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index("ix_source_schedule_epochs_source_id", "source_schedule_epochs", ["source_id"])
    op.create_index(
        "ix_source_schedule_epochs_effective_from", "source_schedule_epochs", ["effective_from"]
    )
    op.create_index(
        "uq_source_schedule_epoch_current",
        "source_schedule_epochs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("effective_until IS NULL"),
    )
    op.create_table(
        "source_due_checks",
        sa.Column("due_key", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column(
            "epoch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_schedule_epochs.id"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id")),
        sa.UniqueConstraint("job_id", name="uq_source_due_checks_job"),
    )
    op.create_index("ix_source_due_checks_source_id", "source_due_checks", ["source_id"])
    op.create_index("ix_source_due_checks_epoch_id", "source_due_checks", ["epoch_id"])
    op.create_table(
        "source_check_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "due_key", sa.String(64), sa.ForeignKey("source_due_checks.due_key"), nullable=False
        ),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False
        ),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(20), nullable=False),
        sa.Column("check_counts", postgresql.JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("job_id", "fence", name="uq_source_check_receipt_attempt"),
    )
    op.create_index("ix_source_check_receipts_due_key", "source_check_receipts", ["due_key"])
    op.create_table(
        "planner_states",
        sa.Column("planner_key", sa.String(40), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_class", sa.String(80)),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(160), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_last_seen_at", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_table("planner_states")
    op.drop_index("ix_source_check_receipts_due_key", table_name="source_check_receipts")
    op.drop_table("source_check_receipts")
    op.drop_index("ix_source_due_checks_epoch_id", table_name="source_due_checks")
    op.drop_index("ix_source_due_checks_source_id", table_name="source_due_checks")
    op.drop_table("source_due_checks")
    op.drop_index("ix_source_schedule_epochs_effective_from", table_name="source_schedule_epochs")
    op.drop_index("uq_source_schedule_epoch_current", table_name="source_schedule_epochs")
    op.drop_index("ix_source_schedule_epochs_source_id", table_name="source_schedule_epochs")
    op.drop_table("source_schedule_epochs")
    op.drop_column("sources", "registry_enabled")
