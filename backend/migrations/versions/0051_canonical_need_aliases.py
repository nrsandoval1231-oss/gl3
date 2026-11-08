"""Add a reversible evidence-backed overlay for equivalent power needs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0051_canonical_need_aliases"
down_revision = "0050_commercial_pursuits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "need_alias_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alias_need_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_need_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("package_scope", sa.String(240), nullable=False),
        sa.Column("basis", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["alias_need_id"], ["power_needs.id"]),
        sa.ForeignKeyConstraint(["canonical_need_id"], ["power_needs.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.CheckConstraint("alias_need_id <> canonical_need_id", name="ck_need_alias_not_self"),
        sa.CheckConstraint(
            "state IN ('current','retracted','conflicted','superseded')",
            name="ck_need_alias_state",
        ),
        sa.UniqueConstraint("alias_need_id", "version", name="uq_need_alias_version"),
    )
    op.create_index(
        "uq_need_alias_current",
        "need_alias_assertions",
        ["alias_need_id"],
        unique=True,
        postgresql_where=sa.text("state = 'current'"),
    )
    op.create_index("ix_need_alias_canonical", "need_alias_assertions", ["canonical_need_id"])


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM need_alias_assertions"))
    if count:
        raise RuntimeError(
            "Refusing to drop retained need-alias assertion history; preserve the table for recovery"
        )
    op.drop_table("need_alias_assertions")
