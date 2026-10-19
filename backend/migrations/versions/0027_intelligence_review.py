"""Store attributed owner review metadata on existing pursuit notes."""

from alembic import op

revision = "0027_intelligence_review"
down_revision = "0026_watch_sets"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE pursuit_call_notes ADD COLUMN intelligence_review JSONB NULL")


def downgrade():
    op.execute("ALTER TABLE pursuit_call_notes DROP COLUMN intelligence_review")
