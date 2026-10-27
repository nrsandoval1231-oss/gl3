"""Persist compare-and-swap receipts for unpublished browse recovery candidates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_browse_recovery_stages"
down_revision = "0047_scoped_identity_link_browse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browse_recovery_stages",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_input_revision", sa.BigInteger(), nullable=False),
        sa.Column("expected_full_revision", sa.BigInteger(), nullable=False),
        sa.Column("expected_generation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_prepared_generation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("integrity_digest", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("membership_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column(
            "staged_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["generation_id"], ["browse_generations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("generation_id"),
        sa.CheckConstraint("length(digest) = 64", name="ck_browse_recovery_digest"),
        sa.CheckConstraint(
            "length(integrity_digest) = 64", name="ck_browse_recovery_integrity_digest"
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND membership_count >= 0 AND unresolved_count >= 0",
            name="ck_browse_recovery_row_counts",
        ),
    )


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM browse_recovery_stages"))
    if count:
        raise RuntimeError("browse recovery receipts are retained; do not downgrade this migration")
    op.drop_table("browse_recovery_stages")
