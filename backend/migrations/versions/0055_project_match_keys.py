"""Persist project identity-match keys so candidate lookup no longer scans every project."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055_project_match_keys"
down_revision = "0054_browse_stale_since"
branch_labels = None
depends_on = None

BATCH = 1000
BROWSE_TRIGGERS = ("dirty_browse", "invalidate_browse")
INDEXES = (
    ("ix_projects_match_keys", "USING gin (match_keys)"),
    ("ix_projects_match_keys_unset", "(id) WHERE match_keys IS NULL"),
)


GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION projects_match_keys_guard() RETURNS trigger AS $fn$
BEGIN
  IF coalesce(current_setting('gridlens.match_keys_managed', true), '') <> 'on' THEN
    NEW.match_keys := NULL;
  END IF;
  RETURN NEW;
END
$fn$ LANGUAGE plpgsql
"""
GUARD_TRIGGER = (
    "CREATE TRIGGER projects_match_keys_guard BEFORE UPDATE OF name, location, identity_facts "
    "ON projects FOR EACH ROW EXECUTE FUNCTION projects_match_keys_guard()"
)


def upgrade() -> None:
    # Idempotent end to end: env.py runs all revisions in one transaction but the
    # autocommit block below commits the column, keys and trigger before the concurrent
    # index builds, so a failed index build leaves alembic_version at 0054 with this work
    # already committed. A rerun must therefore succeed (and resume the backfill).
    #
    # Locking: ADD COLUMN takes ACCESS EXCLUSIVE on projects and DISABLE TRIGGER takes
    # SHARE ROW EXCLUSIVE; the stronger lock is held until the first commit, i.e. for the
    # whole backfill, blocking every read and write of projects. Run this migration with the
    # ingestion worker and API stopped. lock_timeout only bounds the wait to acquire it.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS match_keys text[]")
    # The keys are a derived lookup column that no browse output reads: rewriting them must
    # not mark every project dirty or advance the browse input revision, so the two
    # invalidation triggers are off for this transaction only (transactional DDL; both are
    # restored before commit, and a failure rolls everything back).
    for trigger in BROWSE_TRIGGERS:
        op.execute(f"ALTER TABLE projects DISABLE TRIGGER {trigger}")
    # Keys come from the matcher's own functions (never re-implemented in SQL). If the
    # normalization ever changes, a later migration must recompute them the same way.
    from gridlens.intelligence.project_identity import project_match_keys

    bind = op.get_bind()
    last = None
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT id, name, location, identity_facts FROM projects "
                "WHERE match_keys IS NULL "
                "AND (CAST(:last AS uuid) IS NULL OR id > CAST(:last AS uuid)) "
                "ORDER BY id LIMIT :n"
            ),
            {"last": last, "n": BATCH},
        ).fetchall()
        if not rows:
            break
        # Rows whose keys come back NULL (unexpected shape) stay NULL = always a candidate.
        bind.execute(
            sa.text("UPDATE projects SET match_keys = :keys WHERE id = :id").bindparams(
                sa.bindparam("keys", type_=postgresql.ARRAY(sa.Text()))
            ),
            [
                {"id": r.id, "keys": project_match_keys(r.name, r.location, r.identity_facts)}
                for r in rows
            ],
        )
        last = str(rows[-1].id)
    for trigger in BROWSE_TRIGGERS:
        op.execute(f"ALTER TABLE projects ENABLE TRIGGER {trigger}")
    # From the commit on, any writer that changes name/location/identity_facts without
    # recomputing keys (an older app version still running, raw SQL) nulls them instead of
    # leaving stale ones. Created after the backfill so the backfill is unaffected.
    op.execute(GUARD_FUNCTION)
    op.execute("DROP TRIGGER IF EXISTS projects_match_keys_guard ON projects")
    op.execute(GUARD_TRIGGER)
    # Built concurrently so retained ingestion writes are not blocked during deployment.
    with op.get_context().autocommit_block():
        for name, definition in INDEXES:
            # A failed CONCURRENTLY build leaves an INVALID index that IF NOT EXISTS would
            # silently keep; drop only invalid leftovers so a retry rebuilds it.
            op.execute(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                    WHERE c.relname = '{name}' AND NOT i.indisvalid
                  ) THEN
                    EXECUTE 'DROP INDEX {name}';
                  END IF;
                END $$
                """
            )
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON projects {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _definition in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TRIGGER IF EXISTS projects_match_keys_guard ON projects")
    op.execute("DROP FUNCTION IF EXISTS projects_match_keys_guard()")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS match_keys")
