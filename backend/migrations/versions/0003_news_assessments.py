"""retain version-bound structured RSS project assessments"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_news_assessments"
down_revision = "0002_interpretations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interpretations", sa.Column("evaluator_version", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "interpretations",
        sa.Column("assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interpretations", "assessment")
    op.drop_column("interpretations", "evaluator_version")
