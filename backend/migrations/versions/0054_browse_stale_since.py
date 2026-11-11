"""Record when the published browse generation first fell behind, to bound serve-stale."""

import sqlalchemy as sa
from alembic import op

revision = "0054_browse_stale_since"
down_revision = "0053_browse_structural_fence"
branch_labels = None
depends_on = None

# Runs inside the single UPDATE of browse_state that every invalidation, publication and
# promotion already performs, so it cannot be skipped by any writer path.
STALE_SINCE_SQL = """
    CREATE OR REPLACE FUNCTION track_browse_stale_since() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE published_revision bigint; previous_revision bigint;
    BEGIN
        SELECT input_revision INTO published_revision
            FROM browse_generations WHERE id = NEW.generation_id;
        IF published_revision IS NOT NULL AND published_revision = NEW.input_revision THEN
            NEW.stale_since := NULL;  -- the published generation is current
        ELSIF published_revision IS NOT NULL AND published_revision < NEW.input_revision
            AND NEW.stale_since IS NULL THEN
            -- Behind with no recorded start. Record one only when it fell behind in this very
            -- write (the previously published generation was current); a state that was
            -- already behind keeps an unknown start (NULL = pending), and a started window is
            -- never reset, so a rebase that moves the pointer and restores it cannot extend it.
            SELECT input_revision INTO previous_revision
                FROM browse_generations WHERE id = OLD.generation_id;
            IF previous_revision IS NOT NULL AND previous_revision = OLD.input_revision THEN
                NEW.stale_since := clock_timestamp();
            END IF;
        END IF;
        RETURN NEW;
    END $$
"""


def upgrade() -> None:
    # Fail fast rather than queue behind (and deadlock with) live ingestion transactions.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("browse_state", sa.Column("stale_since", sa.DateTime(timezone=True)))
    # Backfill: when the state is already behind at upgrade time its start is unknown, so
    # stale_since stays NULL and reads are pending until the next publication (never servable
    # on a guess). A current state needs no value.
    op.execute("UPDATE browse_state SET stale_since = NULL")
    op.execute(STALE_SINCE_SQL)
    op.execute("""
        CREATE TRIGGER zz_browse_stale_since BEFORE UPDATE ON browse_state
        FOR EACH ROW EXECUTE FUNCTION track_browse_stale_since()
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TRIGGER IF EXISTS zz_browse_stale_since ON browse_state")
    op.execute("DROP FUNCTION IF EXISTS track_browse_stale_since()")
    op.drop_column("browse_state", "stale_since")
