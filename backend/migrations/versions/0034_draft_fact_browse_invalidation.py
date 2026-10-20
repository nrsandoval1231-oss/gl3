"""Avoid publishing browse generations for initial fact drafts."""

from alembic import op

revision = "0034_fact_draft_browse"
down_revision = "0033_workspace_review"
branch_labels = None
depends_on = None

FACT_DECISION_INSERT_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_fact_decision_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE initial_drafts_only boolean;
    BEGIN
        SELECT bool_and(
            n.decision = 'draft' AND n.version = 1 AND n.expected_version = 0
            AND NOT EXISTS (
                SELECT 1 FROM call_fact_decisions prior
                WHERE prior.need_id = n.need_id AND prior.id <> n.id
            )
        ) INTO initial_drafts_only FROM new_rows n;
        IF initial_drafts_only IS TRUE THEN
            RETURN NULL;
        END IF;
        UPDATE browse_state s SET
            generation_id = CASE WHEN EXISTS (
                SELECT 1 FROM browse_generations g WHERE g.id = s.prepared_generation_id
                AND g.input_revision = s.input_revision
                AND g.valid_from <= clock_timestamp() AND g.valid_until > clock_timestamp()
            ) THEN prepared_generation_id ELSE generation_id END,
            prepared_generation_id = NULL,
            input_revision = input_revision + 1 WHERE id = 1;
        RETURN NULL;
    END $$;

    CREATE OR REPLACE FUNCTION dirty_browse_fact_decision_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE next_revision bigint; owner uuid;
    BEGIN
        IF NEW.decision = 'draft' AND NEW.version = 1 AND NEW.expected_version = 0
            AND NOT EXISTS (
                SELECT 1 FROM call_fact_decisions prior
                WHERE prior.need_id = NEW.need_id AND prior.id <> NEW.id
            ) THEN
            RETURN NULL;
        END IF;
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        SELECT input_revision + 1 INTO next_revision
            FROM browse_state WHERE id = 1 FOR UPDATE;
        SELECT project_id INTO owner FROM power_needs WHERE id = NEW.need_id;
        IF owner IS NULL THEN
            UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
        ELSE
            INSERT INTO browse_dirty_projects(project_id, revision)
                VALUES (owner, next_revision)
            ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
        END IF;
        RETURN NULL;
    END $$
"""


def _create_fact_triggers() -> None:
    op.execute(FACT_DECISION_INSERT_SQL)
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse ON call_fact_versions")
    op.execute("DROP TRIGGER IF EXISTS dirty_browse ON call_fact_versions")
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse ON call_fact_decisions")
    op.execute("DROP TRIGGER IF EXISTS dirty_browse ON call_fact_decisions")
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER UPDATE OR DELETE OR TRUNCATE
        ON call_fact_versions FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_generation('scoped')
    """)
    op.execute("""
        CREATE TRIGGER dirty_browse AFTER UPDATE OR DELETE ON call_fact_versions
        FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER UPDATE OR DELETE OR TRUNCATE
        ON call_fact_decisions FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_generation('scoped')
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse_fact_decision_insert AFTER INSERT
        ON call_fact_decisions REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_fact_decision_insert()
    """)
    op.execute("""
        CREATE TRIGGER dirty_browse AFTER UPDATE OR DELETE ON call_fact_decisions
        FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
    """)
    op.execute("""
        CREATE TRIGGER dirty_browse_fact_decision_insert AFTER INSERT
        ON call_fact_decisions FOR EACH ROW
        EXECUTE FUNCTION dirty_browse_fact_decision_insert()
    """)


def upgrade() -> None:
    _create_fact_triggers()
    op.execute(
        "UPDATE browse_state SET prepared_generation_id = NULL, "
        "full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS dirty_browse_fact_decision_insert ON call_fact_decisions")
    op.execute(
        "DROP TRIGGER IF EXISTS invalidate_browse_fact_decision_insert ON call_fact_decisions"
    )
    op.execute("DROP TRIGGER IF EXISTS dirty_browse ON call_fact_versions")
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse ON call_fact_versions")
    op.execute("DROP TRIGGER IF EXISTS dirty_browse ON call_fact_decisions")
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse ON call_fact_decisions")
    for table in ("call_fact_versions", "call_fact_decisions"):
        op.execute(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT
            EXECUTE FUNCTION invalidate_browse_generation('scoped')
        """)
        op.execute(f"""
            CREATE TRIGGER dirty_browse AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
        """)
    op.execute("DROP FUNCTION dirty_browse_fact_decision_insert()")
    op.execute("DROP FUNCTION invalidate_browse_fact_decision_insert()")
    op.execute(
        "UPDATE browse_state SET prepared_generation_id = NULL, "
        "full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1"
    )
