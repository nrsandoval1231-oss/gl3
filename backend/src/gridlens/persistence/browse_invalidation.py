"""Tables read by canonical browse/detail/rank evaluators.

Statement triggers cover ORM, bulk SQL, foreign-key cascades, and TRUNCATE. Queue,
auth and budget writes intentionally do not invalidate retained-data summaries.
"""

INPUT_TABLES = (
    "sources",
    "observations",
    "evidence",
    "projects",
    "power_needs",
    "need_observations",
    "interpretations",
    "project_lifecycles",
    "lifecycle_events",
    "project_match_decisions",
    "signal_decisions",
    "call_fact_versions",
    "call_fact_decisions",
    "need_workflow_status_events",
    "power_need_briefs",
    "power_need_brief_versions",
    "buying_chain_evidence",
    "buying_chain_claims",
    "buying_chain_runs",
    "buying_chain_identity_links",
    "identity_identifiers",
    "company_identities",
    "company_project_memberships",
    "pursuits",
    "pursuit_documents",
    "pursuit_call_notes",
    "interconnection_fact_versions",
    "editorial_decisions",
    "editorial_assessments",
    "change_events",
    "project_material_states",
)

IDENTITY_SCOPED_TABLES = ("identity_identifiers", "company_identities")
MEMBERSHIP_SCOPED_TABLE = "company_project_memberships"


# Scope every retained ingestion dependency, including shared observations and
# evidence used outside need links. Unknown inputs and source policy stay full.
SCOPED_TABLES = (
    "power_needs",
    "call_fact_versions",
    "call_fact_decisions",
    "need_workflow_status_events",
    "projects",
    "observations",
    "evidence",
    "need_observations",
    "interpretations",
    "project_lifecycles",
    "lifecycle_events",
    "project_match_decisions",
    "signal_decisions",
    "change_events",
    "project_material_states",
    "power_need_briefs",
    "power_need_brief_versions",
    "buying_chain_evidence",
    "buying_chain_claims",
    "buying_chain_runs",
    "interconnection_fact_versions",
    "pursuit_documents",
)

INVALIDATE_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_generation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        UPDATE browse_state s SET
            generation_id = CASE WHEN EXISTS (
                SELECT 1 FROM browse_generations g WHERE g.id = s.prepared_generation_id
                AND g.input_revision = s.input_revision
                AND g.valid_from <= clock_timestamp() AND g.valid_until > clock_timestamp()
            ) THEN prepared_generation_id ELSE generation_id END,
            prepared_generation_id = NULL,
            full_revision = CASE WHEN TG_OP = 'TRUNCATE' OR TG_ARGV[0] = 'full'
                THEN input_revision + 1 ELSE full_revision END,
            input_revision = input_revision + 1 WHERE id = 1;
        RETURN NULL;
    END $$
"""
PURSUIT_SCOPE_SQL = """
    CREATE OR REPLACE FUNCTION scope_browse_pursuit(payload jsonb, next_revision bigint)
    RETURNS boolean LANGUAGE plpgsql AS $$
    DECLARE ids uuid[]; member jsonb; owner uuid; need_owner uuid; identity text;
    BEGIN
        IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
            OR jsonb_typeof(payload->'project_ids') IS DISTINCT FROM 'array' THEN
            RETURN false;
        END IF;
        IF jsonb_array_length(payload->'project_ids') > 1000 THEN RETURN false; END IF;
        owner := (payload->>'project_id')::uuid;
        IF owner IS NULL THEN RETURN false; END IF;
        ids := ARRAY[owner];
        FOR member IN SELECT value FROM jsonb_array_elements(payload->'project_ids') LOOP
            IF jsonb_typeof(member) <> 'string' THEN RETURN false; END IF;
            ids := array_append(ids, (member #>> '{}')::uuid);
        END LOOP;
        identity := payload->>'identity_key';
        IF left(identity, 16) = 'commercial-need:' THEN
            SELECT project_id INTO need_owner FROM power_needs
                WHERE id = substring(identity FROM 17)::uuid;
            IF need_owner IS NULL OR need_owner <> owner THEN RETURN false; END IF;
        END IF;
        INSERT INTO browse_dirty_projects(project_id, revision)
            SELECT DISTINCT unnest(ids), next_revision
        ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
        RETURN true;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN false;
    END $$
"""

DIRTY_SQL = """
    CREATE OR REPLACE FUNCTION browse_observation_projects(
        oid uuid, eid uuid, source_key text, external_key text
    ) RETURNS TABLE(project_id uuid) LANGUAGE sql STABLE AS $$
        SELECT n.project_id FROM need_observations l
            JOIN power_needs n ON n.id = l.need_id WHERE l.observation_id = oid
        UNION
        SELECT p.id FROM projects p WHERE
            (p.source_id = source_key AND p.external_id = external_key)
            OR EXISTS (SELECT 1 FROM observations o WHERE o.id = oid
                AND o.source_id = p.source_id AND o.external_id = p.external_id)
        UNION
        SELECT l.project_id FROM lifecycle_events l WHERE l.observation_id = oid
            OR l.evidence_id = eid OR l.evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT b.project_id FROM buying_chain_evidence b
            WHERE b.retained_evidence_id = eid OR b.retained_evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT f.project_id FROM interconnection_fact_versions f
            WHERE f.evidence_id = eid OR f.evidence_id IN
                (SELECT e.id FROM evidence e WHERE e.observation_id = oid)
        UNION
        SELECT m.candidate_project_id FROM project_match_decisions m
            WHERE m.observation_id = oid AND m.candidate_project_id IS NOT NULL
    $$;
    CREATE OR REPLACE FUNCTION dirty_browse_project() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; pid uuid; next_revision bigint; oid uuid; eid uuid;
    BEGIN
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        -- Acquire the writer/publication fence BEFORE scanning dependencies.
        -- Separate statements see dependencies committed while waiting on it.
        SELECT input_revision + 1 INTO next_revision FROM browse_state WHERE id = 1 FOR UPDATE;
        FOR payload IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP = 'INSERT' THEN jsonb_build_array(to_jsonb(NEW))
                 WHEN TG_OP = 'DELETE' THEN jsonb_build_array(to_jsonb(OLD))
                 ELSE jsonb_build_array(to_jsonb(OLD), to_jsonb(NEW)) END)
        LOOP
            pid := NULL; oid := NULL; eid := NULL;
            IF TG_TABLE_NAME = 'projects' THEN
                pid := (payload->>'id')::uuid;
            ELSIF TG_TABLE_NAME IN (
                'power_needs', 'project_lifecycles', 'lifecycle_events',
                'project_material_states', 'buying_chain_evidence',
                'buying_chain_claims', 'buying_chain_runs', 'interconnection_fact_versions'
            ) THEN
                pid := (payload->>'project_id')::uuid;
            ELSIF TG_TABLE_NAME IN (
                'call_fact_versions', 'call_fact_decisions', 'need_workflow_status_events',
                'need_observations', 'power_need_briefs', 'power_need_brief_versions'
            ) THEN
                SELECT project_id INTO pid FROM power_needs WHERE id = (payload->>'need_id')::uuid;
                IF pid IS NULL THEN
                    UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
                END IF;
            ELSIF TG_TABLE_NAME = 'observations' THEN
                oid := (payload->>'id')::uuid;
            ELSIF TG_TABLE_NAME = 'pursuit_documents' THEN
                IF NOT scope_browse_pursuit(
                    (SELECT to_jsonb(p) FROM pursuits p
                     WHERE p.id = (payload->>'pursuit_id')::uuid), next_revision
                ) THEN
                    UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
                END IF;
            ELSIF TG_TABLE_NAME IN ('evidence', 'interpretations', 'signal_decisions',
                                   'change_events', 'project_match_decisions') THEN
                oid := (payload->>'observation_id')::uuid;
                IF TG_TABLE_NAME = 'evidence' THEN eid := (payload->>'id')::uuid; END IF;
                pid := COALESCE(payload->>'project_id', payload->>'candidate_project_id')::uuid;
            ELSE
                UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
            END IF;
            IF pid IS NOT NULL THEN
                INSERT INTO browse_dirty_projects(project_id, revision) VALUES(pid, next_revision)
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
            END IF;
            IF oid IS NOT NULL THEN
                INSERT INTO browse_dirty_projects(project_id, revision)
                SELECT affected.project_id, next_revision FROM browse_observation_projects(
                    oid, eid, payload->>'source_id', payload->>'external_id'
                ) affected WHERE affected.project_id IS NOT NULL
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
                -- A known unlinked observation has no browse consumer yet. Its
                -- later link/direct project insertion will invalidate that owner.
            END IF;
        END LOOP;
        RETURN NULL;
    END $$
"""

SOURCE_HEALTH_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_source_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        -- Health/checkpoints are live operational overlays, never qualification
        -- inputs. Any other changed or newly added column remains conservative.
        IF EXISTS (SELECT 1 FROM old_rows o FULL JOIN new_rows n USING (id)
            WHERE (to_jsonb(o) - 'health') IS DISTINCT FROM (to_jsonb(n) - 'health')) THEN
            UPDATE browse_state SET prepared_generation_id = NULL,
                full_revision = input_revision + 1, input_revision = input_revision + 1
                WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""


# Workspaces are live overlays, not qualification/ranking inputs. Exempt only
# recognized commercial receipts. Other writes retain exact owner invalidation;
# malformed or unresolvable owners still require a full rebuild.
RECEIPT_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_receipt() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE affected jsonb; payload jsonb; next_revision bigint; full_scope boolean := false;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            SELECT jsonb_agg(to_jsonb(n)) INTO affected FROM new_rows n WHERE (
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
                ) IS NOT TRUE;
        ELSE
            SELECT jsonb_agg(value.payload) INTO affected
                FROM old_rows o FULL JOIN new_rows n USING (id)
                CROSS JOIN LATERAL (VALUES (to_jsonb(o)), (to_jsonb(n))) AS value(payload)
                WHERE (
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
                ) IS NOT TRUE;
        END IF;
        IF affected IS NOT NULL THEN
            PERFORM set_config('gridlens.browse_dirty', '1', true);
            SELECT input_revision + 1 INTO next_revision
                FROM browse_state WHERE id = 1 FOR UPDATE;
            FOR payload IN SELECT value FROM jsonb_array_elements(affected) LOOP
                IF NOT scope_browse_pursuit(payload, next_revision) THEN
                    full_scope := true;
                END IF;
            END LOOP;
            UPDATE browse_state s SET
                generation_id = CASE WHEN EXISTS (
                    SELECT 1 FROM browse_generations g WHERE g.id = s.prepared_generation_id
                    AND g.input_revision = s.input_revision
                    AND g.valid_from <= clock_timestamp() AND g.valid_until > clock_timestamp()
                ) THEN prepared_generation_id ELSE generation_id END,
                prepared_generation_id = NULL,
                full_revision = CASE WHEN full_scope THEN input_revision + 1 ELSE full_revision END,
                input_revision = input_revision + 1 WHERE id = 1;
        END IF;
        RETURN NULL;
    END $$
"""

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


def install_identity_link_triggers(connection):
    # Keep the test/schema installer in parity with reviewed migration 0047.
    for trigger in (
        "invalidate_browse",
        "invalidate_browse_truncate",
        "invalidate_browse_identity_link_insert",
        "invalidate_browse_identity_link_update",
        "invalidate_browse_identity_link_delete",
        "invalidate_browse_identity_link_truncate",
    ):
        connection.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS {trigger} ON buying_chain_identity_links"
        )
    connection.exec_driver_sql(IDENTITY_LINK_SQL)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_identity_link_insert AFTER INSERT
        ON buying_chain_identity_links REFERENCING NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_insert()
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_identity_link_update AFTER UPDATE
        ON buying_chain_identity_links REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_update()
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_identity_link_delete AFTER DELETE
        ON buying_chain_identity_links REFERENCING OLD TABLE AS old_rows
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_identity_link_delete()
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_identity_link_truncate AFTER TRUNCATE
        ON buying_chain_identity_links FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


def install_identity_entity_triggers(connection):
    connection.exec_driver_sql(IDENTITY_ENTITY_SQL)
    for table in IDENTITY_SCOPED_TABLES:
        for trigger in (
            "invalidate_browse",
            "invalidate_browse_truncate",
            "dirty_browse",
            "invalidate_browse_identity_entity_insert",
            "invalidate_browse_identity_entity_update",
            "invalidate_browse_identity_entity_delete",
            "invalidate_browse_identity_entity_truncate",
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for operation, trigger, transition in (
            ("INSERT", "invalidate_browse_identity_entity_insert", "NEW TABLE AS new_rows"),
            (
                "UPDATE",
                "invalidate_browse_identity_entity_update",
                "OLD TABLE AS old_rows NEW TABLE AS new_rows",
            ),
            ("DELETE", "invalidate_browse_identity_entity_delete", "OLD TABLE AS old_rows"),
        ):
            connection.exec_driver_sql(f"""
                CREATE TRIGGER {trigger} AFTER {operation} ON {table}
                REFERENCING {transition} FOR EACH STATEMENT
                EXECUTE FUNCTION {trigger}('{table}')
            """)
        connection.exec_driver_sql(f"""
            CREATE TRIGGER invalidate_browse_identity_entity_truncate AFTER TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
        """)


def install_company_membership_triggers(connection):
    table = MEMBERSHIP_SCOPED_TABLE
    connection.exec_driver_sql(COMPANY_MEMBERSHIP_SCOPE_SQL)
    for trigger in (
        "invalidate_browse",
        "invalidate_browse_truncate",
        "dirty_browse",
        "invalidate_browse_company_membership_insert",
        "invalidate_browse_company_membership_update",
        "invalidate_browse_company_membership_delete",
        "invalidate_browse_company_membership_truncate",
    ):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for operation, trigger, transition in (
        ("INSERT", "invalidate_browse_company_membership_insert", "NEW TABLE AS new_rows"),
        (
            "UPDATE",
            "invalidate_browse_company_membership_update",
            "OLD TABLE AS old_rows NEW TABLE AS new_rows",
        ),
        ("DELETE", "invalidate_browse_company_membership_delete", "OLD TABLE AS old_rows"),
    ):
        connection.exec_driver_sql(f"""
            CREATE TRIGGER {trigger} AFTER {operation} ON {table}
            REFERENCING {transition} FOR EACH STATEMENT
            EXECUTE FUNCTION {trigger}()
        """)
    connection.exec_driver_sql(f"""
        CREATE TRIGGER invalidate_browse_company_membership_truncate AFTER TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


FACT_DECISION_INSERT_SQL = """
    CREATE OR REPLACE FUNCTION invalidate_browse_fact_decision_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE initial_drafts_only boolean;
    BEGIN
        SELECT bool_and(
            n.decision = 'draft'
            AND NOT EXISTS (
                SELECT 1 FROM call_fact_decisions prior
                WHERE prior.fact_version_id = n.fact_version_id AND prior.id <> n.id
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
        IF NEW.decision = 'draft'
            AND NOT EXISTS (
                SELECT 1 FROM call_fact_decisions prior
                WHERE prior.fact_version_id = NEW.fact_version_id AND prior.id <> NEW.id
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


def install_workspace_triggers(connection):
    connection.exec_driver_sql(RECEIPT_SQL)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse AFTER DELETE OR TRUNCATE ON pursuits
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_receipt_insert AFTER INSERT ON pursuits
        REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_receipt()
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_receipt_update AFTER UPDATE ON pursuits
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_receipt()
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse AFTER TRUNCATE ON pursuit_call_notes
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)


def install(connection):
    connection.exec_driver_sql("INSERT INTO browse_state (id) VALUES (1) ON CONFLICT DO NOTHING")
    connection.exec_driver_sql(INVALIDATE_SQL)
    connection.exec_driver_sql(PURSUIT_SCOPE_SQL)
    connection.exec_driver_sql(DIRTY_SQL)
    connection.exec_driver_sql(SOURCE_HEALTH_SQL)
    install_workspace_triggers(connection)
    connection.exec_driver_sql(FACT_DECISION_INSERT_SQL)
    for table in INPUT_TABLES:
        if (
            table == "buying_chain_identity_links"
            or table in IDENTITY_SCOPED_TABLES
            or table == MEMBERSHIP_SCOPED_TABLE
        ):
            continue
        if table in {"pursuits", "pursuit_call_notes"}:
            continue
        scope = "scoped" if table in SCOPED_TABLES else "full"
        if table == "sources":
            operations = "INSERT OR DELETE OR TRUNCATE"
        elif table == "call_fact_versions":
            operations = "UPDATE OR DELETE OR TRUNCATE"
        elif table == "call_fact_decisions":
            operations = "UPDATE OR DELETE OR TRUNCATE"
        else:
            operations = "INSERT OR UPDATE OR DELETE OR TRUNCATE"
        connection.exec_driver_sql(f"""
            CREATE TRIGGER invalidate_browse AFTER {operations}
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('{scope}')
        """)
        if table == "call_fact_decisions":
            connection.exec_driver_sql("""
                CREATE TRIGGER invalidate_browse_fact_decision_insert AFTER INSERT
                ON call_fact_decisions REFERENCING NEW TABLE AS new_rows
                FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_fact_decision_insert()
            """)
            connection.exec_driver_sql("""
                CREATE TRIGGER dirty_browse_fact_decision_insert AFTER INSERT
                ON call_fact_decisions FOR EACH ROW
                EXECUTE FUNCTION dirty_browse_fact_decision_insert()
            """)
        if table in SCOPED_TABLES:
            row_operations = (
                "UPDATE OR DELETE"
                if table in {"call_fact_versions", "call_fact_decisions"}
                else "INSERT OR UPDATE OR DELETE"
            )
            connection.exec_driver_sql(f"""
                CREATE TRIGGER dirty_browse AFTER {row_operations} ON {table}
                FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
            """)
    connection.exec_driver_sql("""
        CREATE TRIGGER invalidate_browse_source_update AFTER UPDATE ON sources
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_source_update()
    """)
    install_identity_link_triggers(connection)
    install_identity_entity_triggers(connection)
    install_company_membership_triggers(connection)
