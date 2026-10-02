"""Durable bounded-scan position for shadow EvidenceJudge traversal."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_jev_scan"
down_revision = "0012_evidence_graph_jev_shadow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_judge_scan_checkpoints",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("evidence_id", postgresql.UUID(), sa.ForeignKey("evidence.id")),
        sa.Column("project_id", postgresql.UUID(), sa.ForeignKey("projects.id")),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("evidence_judge_scan_checkpoints")
