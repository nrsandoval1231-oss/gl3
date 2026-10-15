"""Retain evidence-version-bound human editorial decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_editorial_decisions"
down_revision = "0018_interconnection_facts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "editorial_decisions",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), unique=True, nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.id"),
            nullable=False,
        ),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_editorial_decisions_observation_id", "editorial_decisions", ["observation_id"]
    )
    op.execute(
        "CREATE TRIGGER editorial_decisions_immutable BEFORE UPDATE OR DELETE ON "
        "editorial_decisions "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()"
    )

    op.create_table(
        "editorial_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.id"),
            nullable=False,
        ),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_editorial_assessments_evidence_id", "editorial_assessments", ["evidence_id"]
    )


def downgrade():
    op.drop_table("editorial_assessments")
    op.drop_table("editorial_decisions")
