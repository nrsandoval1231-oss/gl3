"""Project scoped material changes and advisory EvidenceJudge shadow records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_evidence_graph_jev_shadow"
down_revision = "0011_power_need_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_events", sa.Column("project_id", postgresql.UUID(), nullable=True))
    op.add_column("change_events", sa.Column("evidence_id", postgresql.UUID(), nullable=True))
    op.add_column(
        "change_events",
        sa.Column("buying_chain_evidence_id", postgresql.UUID(), nullable=True),
    )
    op.add_column("change_events", sa.Column("field_name", sa.String(100), nullable=True))
    op.add_column("change_events", sa.Column("prior_state", postgresql.JSONB(), nullable=True))
    op.add_column("change_events", sa.Column("new_state", postgresql.JSONB(), nullable=True))
    op.add_column(
        "change_events",
        sa.Column("material", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("change_events", sa.Column("source_date", sa.Date(), nullable=True))
    op.add_column("change_events", sa.Column("replay_key", sa.String(64), nullable=True))
    op.create_foreign_key("fk_change_project", "change_events", "projects", ["project_id"], ["id"])
    op.create_foreign_key(
        "fk_change_evidence", "change_events", "evidence", ["evidence_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_change_buying_evidence",
        "change_events",
        "buying_chain_evidence",
        ["buying_chain_evidence_id"],
        ["id"],
    )
    op.create_index(
        "uq_change_replay_key",
        "change_events",
        ["replay_key"],
        unique=True,
        postgresql_where=sa.text("replay_key IS NOT NULL"),
    )
    op.create_index(
        "ix_change_project_material", "change_events", ["project_id", "material", "created_at"]
    )
    op.create_table(
        "project_material_states",
        sa.Column("project_id", postgresql.UUID(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column(
            "state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_project_change_revision",
        "change_events",
        ["project_id", "field_name", "replay_key"],
        unique=True,
        postgresql_where=sa.text("material IS TRUE AND replay_key IS NOT NULL"),
    )
    op.create_table(
        "evidence_judge_runs",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("project_id", postgresql.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(), sa.ForeignKey("evidence.id"), nullable=False),
        sa.Column("candidate_project_id", postgresql.UUID(), sa.ForeignKey("projects.id")),
        sa.Column("input_key", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("deterministic", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error_class", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.UniqueConstraint("input_key", name="uq_evidence_judge_input"),
    )
    op.create_index("ix_evidence_judge_status", "evidence_judge_runs", ["status", "started_at"])


def downgrade() -> None:
    op.drop_index("uq_project_change_revision", table_name="change_events")
    op.drop_table("project_material_states")
    op.drop_index("ix_evidence_judge_status", table_name="evidence_judge_runs")
    op.drop_table("evidence_judge_runs")
    op.drop_index("ix_change_project_material", table_name="change_events")
    op.drop_index("uq_change_replay_key", table_name="change_events")
    op.drop_constraint("fk_change_evidence", "change_events", type_="foreignkey")
    op.execute("ALTER TABLE change_events DROP CONSTRAINT IF EXISTS fk_change_buying_evidence")
    op.execute("ALTER TABLE change_events DROP COLUMN IF EXISTS buying_chain_evidence_id")
    op.drop_constraint("fk_change_project", "change_events", type_="foreignkey")
    for name in (
        "replay_key",
        "source_date",
        "material",
        "new_state",
        "prior_state",
        "field_name",
        "evidence_id",
        "project_id",
    ):
        op.drop_column("change_events", name)
