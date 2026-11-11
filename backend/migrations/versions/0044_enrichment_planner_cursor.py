"""Persist bounded company research scan progress without creating a new queue."""

import sqlalchemy as sa
from alembic import op

revision = "0044_enrichment_planner_cursor"
down_revision = "0043_company_graph_assertions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planner_states", sa.Column("cursor", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("planner_states", "cursor")
