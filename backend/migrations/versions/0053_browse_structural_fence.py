"""Record identity, membership and deletion writes so serve-stale reads keep that fence closed."""

import sqlalchemy as sa
from alembic import op

revision = "0053_browse_structural_fence"
down_revision = "0052_ingestion_lookup_indexes"
branch_labels = None
depends_on = None

TABLES = (
    ("company_identities", "UPDATE OR DELETE OR TRUNCATE"),
    ("identity_identifiers", "INSERT OR UPDATE OR DELETE OR TRUNCATE"),
    ("company_project_memberships", "INSERT OR UPDATE OR DELETE OR TRUNCATE"),
    ("buying_chain_identity_links", "INSERT OR UPDATE OR DELETE OR TRUNCATE"),
    ("power_needs", "DELETE OR TRUNCATE"),
    ("projects", "DELETE OR TRUNCATE"),
)


DEACTIVATION_SQL = """
    CREATE OR REPLACE FUNCTION mark_browse_structural_deactivation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM old_rows o JOIN new_rows n ON n.id = o.id
            WHERE o.active IS TRUE AND n.active IS NOT TRUE
        ) THEN
            UPDATE browse_state SET structural_revision = input_revision WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""


def upgrade() -> None:
    # Fail fast rather than queue behind (and deadlock with) live ingestion transactions.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(
        "browse_state",
        sa.Column("structural_revision", sa.BigInteger(), server_default="0", nullable=False),
    )
    # Writes before this upgrade were not tracked: close the fence until the next publication.
    op.execute("UPDATE browse_state SET structural_revision = input_revision")
    op.execute("""
        CREATE OR REPLACE FUNCTION mark_browse_structural_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE browse_state SET structural_revision = input_revision WHERE id = 1;
            RETURN NULL;
        END $$
    """)
    # Trigger name order places this after the invalidate_browse* triggers, so
    # input_revision already includes the current statement.
    for table, operations in TABLES:
        op.execute(f"""
            CREATE TRIGGER zz_browse_structural_fence
            AFTER {operations} ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION mark_browse_structural_fence()
        """)
    op.execute(DEACTIVATION_SQL)
    op.execute("""
        CREATE TRIGGER zz_browse_structural_deactivation AFTER UPDATE ON power_needs
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION mark_browse_structural_deactivation()
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TRIGGER IF EXISTS zz_browse_structural_deactivation ON power_needs")
    op.execute("DROP FUNCTION IF EXISTS mark_browse_structural_deactivation()")
    for table, _operations in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS zz_browse_structural_fence ON {table}")
    op.execute("DROP FUNCTION IF EXISTS mark_browse_structural_fence()")
    op.drop_column("browse_state", "structural_revision")
