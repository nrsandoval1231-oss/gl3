"""Scope buying-chain identity-link browse invalidation by owning project."""

from alembic import op

revision = "0047_scoped_identity_link_browse"
down_revision = "0046_import_meta_reparse"
branch_labels = None
depends_on = None

IDENTITY_LINK_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_identity_links(affected jsonb)
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; next_revision bigint; company_ids uuid[] := ARRAY[]::uuid[];
            full_scope boolean := false; owner uuid;
    BEGIN
        IF affected IS NULL OR jsonb_array_length(affected) = 0 THEN RETURN; END IF;
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        SELECT input_revision + 1 INTO next_revision FROM browse_state WHERE id = 1 FOR UPDATE;
        FOR payload IN SELECT value FROM jsonb_array_elements(affected) LOOP
            owner := NULL;
            SELECT project_id INTO owner FROM buying_chain_claims
                WHERE id = (payload->>'claim_id')::uuid;
            IF owner IS NULL THEN
                full_scope := true;
            ELSE
                INSERT INTO browse_dirty_projects(project_id, revision)
                VALUES (owner, next_revision)
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
            END IF;
            IF payload->>'company_identity_id' IS NOT NULL THEN
                company_ids := array_append(company_ids,
                    (payload->>'company_identity_id')::uuid);
            END IF;
        END LOOP;
        IF cardinality(company_ids) > 0 THEN
            FOR owner IN
                SELECT impacted.project_id FROM (
                    SELECT DISTINCT c.project_id FROM buying_chain_identity_links l
                    JOIN buying_chain_claims c ON c.id = l.claim_id
                    WHERE l.state = 'current' AND l.company_identity_id = ANY(company_ids)
                    UNION
                    SELECT DISTINCT m.project_id FROM company_project_memberships m
                    WHERE m.state = 'current' AND m.company_identity_id = ANY(company_ids)
                ) impacted
            LOOP
                INSERT INTO browse_dirty_projects(project_id, revision)
                VALUES (owner, next_revision)
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
            END LOOP;
        END IF;
        UPDATE browse_state s SET
            generation_id = CASE WHEN EXISTS (
                SELECT 1 FROM browse_generations g WHERE g.id = s.prepared_generation_id
                AND g.input_revision = s.input_revision
                AND g.valid_from <= clock_timestamp() AND g.valid_until > clock_timestamp()
            ) THEN prepared_generation_id ELSE generation_id END,
            prepared_generation_id = NULL,
            full_revision = CASE WHEN full_scope THEN input_revision + 1 ELSE full_revision END,
            input_revision = input_revision + 1 WHERE id = 1;
    EXCEPTION WHEN invalid_text_representation THEN
        UPDATE browse_state SET prepared_generation_id = NULL,
            full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1;
    END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_link_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(n)) INTO rows FROM new_rows n;
        PERFORM invalidate_browse_identity_links(rows); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_link_delete() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(o)) INTO rows FROM old_rows o;
        PERFORM invalidate_browse_identity_links(rows); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_link_update() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb; old_payloads jsonb; new_payloads jsonb;
    BEGIN
        SELECT jsonb_agg(to_jsonb(o)) INTO old_payloads FROM old_rows o
            FULL JOIN new_rows n USING (id)
            WHERE n.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        SELECT jsonb_agg(to_jsonb(n)) INTO new_payloads FROM new_rows n
            FULL JOIN old_rows o USING (id)
            WHERE o.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        rows := coalesce(old_payloads, '[]'::jsonb) || coalesce(new_payloads, '[]'::jsonb);
        PERFORM invalidate_browse_identity_links(rows); RETURN NULL;
    END $$;
"""


def upgrade() -> None:
    # Migration 0037 installed full-rebuild statement triggers. Replace only
    # the identity-link triggers; company account and identifier edits remain
    # global because they can affect every project identity resolution.
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse ON buying_chain_identity_links")
    op.execute("DROP TRIGGER IF EXISTS invalidate_browse_truncate ON buying_chain_identity_links")
    op.execute(IDENTITY_LINK_SQL)
    op.execute("""
        CREATE TRIGGER invalidate_browse_identity_link_insert AFTER INSERT
        ON buying_chain_identity_links REFERENCING NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_insert()
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse_identity_link_update AFTER UPDATE
        ON buying_chain_identity_links REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_update()
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse_identity_link_delete AFTER DELETE
        ON buying_chain_identity_links REFERENCING OLD TABLE AS old_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_delete()
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse_identity_link_truncate AFTER TRUNCATE
        ON buying_chain_identity_links FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


def downgrade() -> None:
    for trigger in (
        "invalidate_browse_identity_link_insert",
        "invalidate_browse_identity_link_update",
        "invalidate_browse_identity_link_delete",
        "invalidate_browse_identity_link_truncate",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON buying_chain_identity_links")
    op.execute("DROP FUNCTION IF EXISTS invalidate_browse_identity_link_insert()")
    op.execute("DROP FUNCTION IF EXISTS invalidate_browse_identity_link_update()")
    op.execute("DROP FUNCTION IF EXISTS invalidate_browse_identity_link_delete()")
    op.execute("DROP FUNCTION IF EXISTS invalidate_browse_identity_links(jsonb)")
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE ON buying_chain_identity_links
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)
    op.execute("""
        CREATE TRIGGER invalidate_browse_truncate AFTER TRUNCATE ON buying_chain_identity_links
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)
