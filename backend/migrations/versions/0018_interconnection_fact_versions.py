"""Preserve reviewed interconnection facts independently of mutable interpretations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_interconnection_facts"
down_revision = "0017_call_fact_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interconnection_fact_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"), nullable=False,
        ),
        sa.Column(
            "evidence_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.id"), nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("project_id", "evidence_id", name="uq_interconnection_fact_evidence"),
    )
    op.execute(
        """CREATE TRIGGER interconnection_fact_versions_immutable
        BEFORE UPDATE OR DELETE ON interconnection_fact_versions
        FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()"""
    )


def downgrade() -> None:
    op.drop_table("interconnection_fact_versions")
