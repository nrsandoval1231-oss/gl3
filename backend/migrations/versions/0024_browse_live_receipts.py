"""Keep recognized live commercial receipt/note overlays out of browse invalidation."""

from alembic import op

revision = "0024_browse_live_receipts"
down_revision = "0023_browse_commercial_selection"
branch_labels = None
depends_on = None

RECEIPT_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_receipt() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE unsafe boolean;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            SELECT EXISTS (
                SELECT 1 FROM new_rows n WHERE (
                    EXISTS (SELECT 1 FROM power_needs p
                        WHERE n.identity_key = 'commercial-need:' || p.id::text
                        AND n.project_id = p.project_id)
                    AND jsonb_typeof(n.project_ids) = 'array'
                    AND jsonb_typeof(n.snapshot) = 'object'
                    AND n.snapshot - 'commercial_triage' = '{}'::jsonb
                    AND (NOT n.snapshot ? 'commercial_triage'
                        OR jsonb_typeof(n.snapshot->'commercial_triage') = 'object')
                    AND to_jsonb(n)
                        - ARRAY['id','identity_key','project_id','project_ids','snapshot']
                        = jsonb_build_object('last_researched_at', NULL, 'last_attempt_at', NULL,
                            'research_status', 'not_researched', 'research_errors', '[]'::jsonb)
                ) IS NOT TRUE
            ) INTO unsafe;
        ELSE
            SELECT EXISTS (
                SELECT 1 FROM old_rows o FULL JOIN new_rows n USING (id) WHERE (
                    o.id IS NOT NULL AND n.id IS NOT NULL
                    AND EXISTS (SELECT 1 FROM power_needs p
                        WHERE n.identity_key = 'commercial-need:' || p.id::text
                        AND n.project_id = p.project_id)
                    AND to_jsonb(o) - ARRAY['snapshot','project_ids']
                        = to_jsonb(n) - ARRAY['snapshot','project_ids']
                    AND jsonb_typeof(n.project_ids) = 'array'
                    AND jsonb_typeof(o.snapshot) = 'object'
                    AND jsonb_typeof(n.snapshot) = 'object'
                    AND o.snapshot - 'commercial_triage' = n.snapshot - 'commercial_triage'
                    AND (NOT o.snapshot ? 'commercial_triage'
                        OR jsonb_typeof(o.snapshot->'commercial_triage') = 'object')
                    AND (NOT n.snapshot ? 'commercial_triage'
                        OR jsonb_typeof(n.snapshot->'commercial_triage') = 'object')
                ) IS NOT TRUE
            ) INTO unsafe;
        END IF;
        IF unsafe THEN
            UPDATE browse_state s SET
                generation_id = CASE WHEN EXISTS (
                    SELECT 1 FROM browse_generations g WHERE g.id = s.prepared_generation_id
                    AND g.input_revision = s.input_revision
                    AND g.valid_from <= clock_timestamp() AND g.valid_until > clock_timestamp()
                ) THEN prepared_generation_id ELSE generation_id END,
                prepared_generation_id = NULL,
                full_revision = input_revision + 1,
                input_revision = input_revision + 1 WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""


def upgrade():
    op.execute("DROP TRIGGER invalidate_browse ON pursuits")
    op.execute("DROP TRIGGER invalidate_browse ON pursuit_call_notes")
    op.execute(RECEIPT_SQL)
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER DELETE OR TRUNCATE ON pursuits
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full');
        CREATE TRIGGER invalidate_browse_receipt_insert AFTER INSERT ON pursuits
        REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_receipt();
        CREATE TRIGGER invalidate_browse_receipt_update AFTER UPDATE ON pursuits
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_receipt();
        CREATE TRIGGER invalidate_browse AFTER TRUNCATE ON pursuit_call_notes
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


def downgrade():
    op.execute("DROP TRIGGER invalidate_browse_receipt_insert ON pursuits")
    op.execute("DROP TRIGGER invalidate_browse_receipt_update ON pursuits")
    op.execute("DROP FUNCTION invalidate_browse_receipt()")
    for table in ("pursuits", "pursuit_call_notes"):
        op.execute(f"DROP TRIGGER invalidate_browse ON {table}")
        op.execute(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
        """)
