"""Track structural writes and time-spent-stale so serve-stale reads can keep fences closed."""

import sqlalchemy as sa
from alembic import op

revision = "0053_browse_structural_fence"
down_revision = "0052_ingestion_lookup_indexes"
branch_labels = None
depends_on = None

# (table, operations, cause column group)
TABLES = (
    ("company_identities", "UPDATE OR DELETE OR TRUNCATE", "identity"),
    ("identity_identifiers", "INSERT OR UPDATE OR DELETE OR TRUNCATE", "identity"),
    ("company_project_memberships", "UPDATE OR DELETE OR TRUNCATE", "identity"),
    ("buying_chain_identity_links", "INSERT OR UPDATE OR DELETE OR TRUNCATE", "identity"),
    ("power_needs", "DELETE OR TRUNCATE", "deletion"),
    ("projects", "DELETE OR TRUNCATE", "deletion"),
)

FENCE_SQL = """
    CREATE OR REPLACE FUNCTION mark_browse_structural_fence() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        UPDATE browse_state SET
            identity_revision = CASE WHEN TG_ARGV[0] = 'identity'
                THEN input_revision ELSE identity_revision END,
            deletion_revision = CASE WHEN TG_ARGV[0] = 'deletion'
                THEN input_revision ELSE deletion_revision END
        WHERE id = 1;
        RETURN NULL;
    END $$
"""

# Ingestion retracts a need by clearing power_needs.active, not by deleting it.
DEACTIVATION_SQL = """
    CREATE OR REPLACE FUNCTION mark_browse_structural_deactivation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM old_rows o JOIN new_rows n ON n.id = o.id
            WHERE o.active IS TRUE AND n.active IS NOT TRUE
        ) THEN
            UPDATE browse_state SET deactivation_revision = input_revision WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""

MEMBERSHIP_INSERT_SQL = """
    CREATE OR REPLACE FUNCTION mark_browse_membership_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        -- A membership for a project the served generation does not contain cannot make
        -- that snapshot wrong; only fence when it touches a project the snapshot shows.
        IF EXISTS (
            SELECT 1 FROM new_rows n JOIN browse_state s ON s.id = 1
            JOIN browse_rows b ON b.generation_id = s.generation_id AND b.project_id = n.project_id
        ) THEN
            UPDATE browse_state SET identity_revision = input_revision WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""

STALE_SINCE_SQL = """
    CREATE OR REPLACE FUNCTION track_browse_stale_since() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.input_revision > OLD.input_revision AND NEW.stale_since IS NULL THEN
            NEW.stale_since := clock_timestamp();
        END IF;
        IF NEW.generation_id IS DISTINCT FROM OLD.generation_id AND EXISTS (
            SELECT 1 FROM browse_generations g
            WHERE g.id = NEW.generation_id AND g.input_revision = NEW.input_revision
        ) THEN
            NEW.stale_since := NULL;
        END IF;
        RETURN NEW;
    END $$
"""


def upgrade() -> None:
    # Fail fast rather than queue behind (and deadlock with) live ingestion transactions.
    op.execute("SET LOCAL lock_timeout = '10s'")
    for column in ("identity_revision", "deletion_revision", "deactivation_revision"):
        op.add_column(
            "browse_state",
            sa.Column(column, sa.BigInteger(), server_default="0", nullable=False),
        )
    op.add_column("browse_state", sa.Column("stale_since", sa.DateTime(timezone=True)))
    # Writes before this upgrade were not tracked: close the fence until the next publication.
    op.execute("UPDATE browse_state SET identity_revision = input_revision")
    op.execute(FENCE_SQL)
    op.execute(DEACTIVATION_SQL)
    op.execute(STALE_SINCE_SQL)
    op.execute(MEMBERSHIP_INSERT_SQL)
    op.execute("""
        CREATE TRIGGER zz_browse_structural_membership_insert
        AFTER INSERT ON company_project_memberships
        REFERENCING NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION mark_browse_membership_insert()
    """)
    op.execute("""
        CREATE TRIGGER track_browse_stale_since BEFORE UPDATE ON browse_state
        FOR EACH ROW EXECUTE FUNCTION track_browse_stale_since()
    """)
    # Trigger name order places the fence after the invalidate_browse* triggers, so
    # input_revision already includes the current statement.
    for table, operations, cause in TABLES:
        op.execute(f"""
            CREATE TRIGGER zz_browse_structural_fence
            AFTER {operations} ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION mark_browse_structural_fence('{cause}')
        """)
    op.execute("""
        CREATE TRIGGER zz_browse_structural_deactivation AFTER UPDATE ON power_needs
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION mark_browse_structural_deactivation()
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "DROP TRIGGER IF EXISTS zz_browse_structural_membership_insert"
        " ON company_project_memberships"
    )
    op.execute("DROP FUNCTION IF EXISTS mark_browse_membership_insert()")
    op.execute("DROP TRIGGER IF EXISTS zz_browse_structural_deactivation ON power_needs")
    op.execute("DROP FUNCTION IF EXISTS mark_browse_structural_deactivation()")
    for table, _operations, _cause in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS zz_browse_structural_fence ON {table}")
    op.execute("DROP FUNCTION IF EXISTS mark_browse_structural_fence()")
    op.execute("DROP TRIGGER IF EXISTS track_browse_stale_since ON browse_state")
    op.execute("DROP FUNCTION IF EXISTS track_browse_stale_since()")
    for column in (
        "stale_since",
        "deactivation_revision",
        "deletion_revision",
        "identity_revision",
    ):
        op.drop_column("browse_state", column)
