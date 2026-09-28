"""allow unknown publication dates and label source event dates"""

import sqlalchemy as sa
from alembic import op

revision = "0004_unknown_publication_dates"
down_revision = "0003_news_assessments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("observations", "published_at", existing_type=sa.Date(), nullable=True)
    op.alter_column("evidence", "published_at", existing_type=sa.Date(), nullable=True)
    op.add_column("evidence", sa.Column("event_date_label", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "event_date_label")
    op.alter_column("evidence", "published_at", existing_type=sa.Date(), nullable=False)
    op.alter_column("observations", "published_at", existing_type=sa.Date(), nullable=False)
