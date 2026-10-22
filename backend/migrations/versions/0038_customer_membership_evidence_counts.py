"""Add generation-bound distinct customer evidence summary fields."""

from alembic import op

revision = "0038_customer_evidence_counts"
down_revision = "0037_customer_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE browse_customer_memberships "
        "ADD COLUMN IF NOT EXISTS supporting_evidence_count integer NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE browse_customer_memberships "
        "ADD COLUMN IF NOT EXISTS last_evidence_update timestamptz"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE browse_customer_memberships DROP COLUMN IF EXISTS last_evidence_update")
    op.execute(
        "ALTER TABLE browse_customer_memberships DROP COLUMN IF EXISTS supporting_evidence_count"
    )
