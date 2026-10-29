"""Scope identity reconciliation input invalidation to referencing projects."""

from alembic import op

revision = "0049_scoped_identity_browse"
down_revision = "0048_browse_recovery_stages"
branch_labels = None
depends_on = None

IDENTITY_ENTITY_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_identity_entities(
        affected jsonb, entity_table text
    )
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; company_ids uuid[] := ARRAY[]::uuid[];
            person_ids uuid[] := ARRAY[]::uuid[]; project_ids uuid[] := ARRAY[]::uuid[];
            full_scope boolean := false; next_revision bigint;
    BEGIN
        IF affected IS NULL OR jsonb_array_length(affected) = 0 THEN RETURN; END IF;
        FOR payload IN SELECT value FROM jsonb_array_elements(affected) LOOP
            IF entity_table = 'company_identities' THEN
                IF payload->>'id' IS NULL THEN
                    full_scope := true;
                ELSE
                    company_ids := array_append(company_ids, (payload->>'id')::uuid);
                END IF;
            ELSIF payload->>'entity_type' = 'company'
                AND payload->>'company_identity_id' IS NOT NULL
                AND payload->>'person_identity_id' IS NULL THEN
                company_ids := array_append(company_ids,
                    (payload->>'company_identity_id')::uuid);
            ELSIF payload->>'entity_type' = 'person'
                AND payload->>'person_identity_id' IS NOT NULL
                AND payload->>'company_identity_id' IS NULL THEN
                person_ids := array_append(person_ids,
                    (payload->>'person_identity_id')::uuid);
            ELSE
                full_scope := true;
            END IF;
        END LOOP;
        -- Fence dependency lookup against link/membership mutations, as in the
        -- canonical observation invalidation path.
        SELECT input_revision + 1 INTO next_revision
            FROM browse_state WHERE id = 1 FOR UPDATE;
        SELECT array_agg(DISTINCT impacted.project_id) INTO project_ids FROM (
                SELECT c.project_id FROM buying_chain_identity_links l
                JOIN buying_chain_claims c ON c.id = l.claim_id
                WHERE cardinality(company_ids) > 0
                    AND l.company_identity_id = ANY(company_ids)
                UNION
                SELECT m.project_id FROM company_project_memberships m
                WHERE cardinality(company_ids) > 0
                    AND m.company_identity_id = ANY(company_ids)
                UNION
                SELECT bcm.project_id FROM browse_customer_memberships bcm
                WHERE cardinality(company_ids) > 0
                    AND bcm.company_identity_id = ANY(company_ids)
                UNION
                SELECT c.project_id FROM buying_chain_identity_links l
                JOIN buying_chain_claims c ON c.id = l.claim_id
                WHERE cardinality(person_ids) > 0
                    AND l.person_identity_id = ANY(person_ids)
            ) impacted;
        IF NOT full_scope AND cardinality(project_ids) IS NULL THEN
            -- New/unreferenced identities and identifiers are only reconciliation
            -- inputs; no saved browse projection can consume them yet.
            RETURN;
        END IF;
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        IF cardinality(project_ids) > 0 THEN
            INSERT INTO browse_dirty_projects(project_id, revision)
            SELECT unnest(project_ids), next_revision
            ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
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
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        UPDATE browse_state SET prepared_generation_id = NULL,
            full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1;
    END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_entity_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(n)) INTO rows FROM new_rows n;
        PERFORM invalidate_browse_identity_entities(rows, TG_ARGV[0]); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_entity_delete() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(o)) INTO rows FROM old_rows o;
        PERFORM invalidate_browse_identity_entities(rows, TG_ARGV[0]); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_identity_entity_update() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb; old_payloads jsonb; new_payloads jsonb;
    BEGIN
        SELECT jsonb_agg(to_jsonb(o)) INTO old_payloads FROM old_rows o
            FULL JOIN new_rows n USING (id)
            WHERE n.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        SELECT jsonb_agg(to_jsonb(n)) INTO new_payloads FROM new_rows n
            FULL JOIN old_rows o USING (id)
            WHERE o.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        rows := coalesce(old_payloads, '[]'::jsonb) || coalesce(new_payloads, '[]'::jsonb);
        PERFORM invalidate_browse_identity_entities(rows, TG_ARGV[0]); RETURN NULL; END $$;

"""

COMPANY_MEMBERSHIP_SCOPE_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_company_membership_rows(affected jsonb)
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; project_ids uuid[] := ARRAY[]::uuid[];
            full_scope boolean := false; next_revision bigint;
    BEGIN
        IF affected IS NULL OR jsonb_array_length(affected) = 0 THEN RETURN; END IF;
        FOR payload IN SELECT value FROM jsonb_array_elements(affected) LOOP
            IF payload->>'project_id' IS NULL THEN
                full_scope := true;
            ELSE
                project_ids := array_append(project_ids, (payload->>'project_id')::uuid);
            END IF;
        END LOOP;
        IF cardinality(project_ids) IS NULL AND NOT full_scope THEN
            full_scope := true;
        END IF;
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        SELECT input_revision + 1 INTO next_revision
            FROM browse_state WHERE id = 1 FOR UPDATE;
        IF cardinality(project_ids) > 0 THEN
            INSERT INTO browse_dirty_projects(project_id, revision)
            SELECT DISTINCT unnest(project_ids), next_revision
            ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
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
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        UPDATE browse_state SET prepared_generation_id = NULL,
            full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1;
    END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_company_membership_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(n)) INTO rows FROM new_rows n;
        PERFORM invalidate_browse_company_membership_rows(rows); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_company_membership_delete() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb;
    BEGIN SELECT jsonb_agg(to_jsonb(o)) INTO rows FROM old_rows o;
        PERFORM invalidate_browse_company_membership_rows(rows); RETURN NULL; END $$;

    CREATE OR REPLACE FUNCTION invalidate_browse_company_membership_update() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE rows jsonb; old_payloads jsonb; new_payloads jsonb;
    BEGIN
        SELECT jsonb_agg(to_jsonb(o)) INTO old_payloads FROM old_rows o
            FULL JOIN new_rows n USING (id)
            WHERE n.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        SELECT jsonb_agg(to_jsonb(n)) INTO new_payloads FROM new_rows n
            FULL JOIN old_rows o USING (id)
            WHERE o.id IS NULL OR to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
        rows := coalesce(old_payloads, '[]'::jsonb) || coalesce(new_payloads, '[]'::jsonb);
        PERFORM invalidate_browse_company_membership_rows(rows); RETURN NULL; END $$;
"""


def upgrade() -> None:
    for table in ("company_identities", "identity_identifiers"):
        op.execute(f"DROP TRIGGER IF EXISTS invalidate_browse ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS invalidate_browse_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS dirty_browse ON {table}")
    op.execute(IDENTITY_ENTITY_SQL)
    for table in ("company_identities", "identity_identifiers"):
        for operation, trigger, transition in (
            ("INSERT", "invalidate_browse_identity_entity_insert", "NEW TABLE AS new_rows"),
            (
                "UPDATE",
                "invalidate_browse_identity_entity_update",
                "OLD TABLE AS old_rows NEW TABLE AS new_rows",
            ),
            ("DELETE", "invalidate_browse_identity_entity_delete", "OLD TABLE AS old_rows"),
        ):
            op.execute(f"""
                CREATE TRIGGER {trigger} AFTER {operation} ON {table}
                REFERENCING {transition} FOR EACH STATEMENT
                EXECUTE FUNCTION {trigger}('{table}')
            """)
        op.execute(f"""
            CREATE TRIGGER invalidate_browse_identity_entity_truncate AFTER TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
        """)
    table = "company_project_memberships"
    for trigger in ("invalidate_browse", "invalidate_browse_truncate", "dirty_browse"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute(COMPANY_MEMBERSHIP_SCOPE_SQL)
    for operation, trigger, transition in (
        ("INSERT", "invalidate_browse_company_membership_insert", "NEW TABLE AS new_rows"),
        (
            "UPDATE",
            "invalidate_browse_company_membership_update",
            "OLD TABLE AS old_rows NEW TABLE AS new_rows",
        ),
        ("DELETE", "invalidate_browse_company_membership_delete", "OLD TABLE AS old_rows"),
    ):
        op.execute(f"""
            CREATE TRIGGER {trigger} AFTER {operation} ON {table}
            REFERENCING {transition} FOR EACH STATEMENT
            EXECUTE FUNCTION {trigger}()
        """)
    op.execute(f"""
        CREATE TRIGGER invalidate_browse_company_membership_truncate AFTER TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


def downgrade() -> None:
    table = "company_project_memberships"
    for trigger in (
        "invalidate_browse_company_membership_insert",
        "invalidate_browse_company_membership_update",
        "invalidate_browse_company_membership_delete",
        "invalidate_browse_company_membership_truncate",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute(f"DROP TRIGGER IF EXISTS invalidate_browse ON {table}")
    op.execute(f"""
        CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
        ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)
    for function in (
        "invalidate_browse_company_membership_insert()",
        "invalidate_browse_company_membership_update()",
        "invalidate_browse_company_membership_delete()",
        "invalidate_browse_company_membership_rows(jsonb)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    for table in ("company_identities", "identity_identifiers"):
        for trigger in (
            "invalidate_browse_identity_entity_insert",
            "invalidate_browse_identity_entity_update",
            "invalidate_browse_identity_entity_delete",
            "invalidate_browse_identity_entity_truncate",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
        """)
    for function in (
        "invalidate_browse_identity_entity_insert()",
        "invalidate_browse_identity_entity_update()",
        "invalidate_browse_identity_entity_delete()",
        "invalidate_browse_identity_entities(jsonb, text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
