"""Canonical commercial group/priority scalars in existing saved generations."""

from alembic import op

revision = "0023_browse_commercial_selection"
down_revision = "0022_browse_clock_transitions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE browse_rows ADD COLUMN commercial_group TEXT,
            ADD COLUMN commercial_segment INTEGER,
            ADD COLUMN commercial_geography INTEGER,
            ADD COLUMN commercial_date INTEGER;
        CREATE INDEX ix_browse_commercial ON browse_rows
            (generation_id, tier, commercial_group, commercial_segment,
             commercial_geography, commercial_date, project_id, need_id)
    """)


def downgrade():
    op.execute("""
        DROP INDEX ix_browse_commercial;
        ALTER TABLE browse_rows DROP COLUMN commercial_group,
            DROP COLUMN commercial_segment, DROP COLUMN commercial_geography,
            DROP COLUMN commercial_date
    """)
