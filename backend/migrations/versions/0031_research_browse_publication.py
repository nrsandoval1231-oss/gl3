"""Scope legacy research publication without changing receipt exemptions."""

from alembic import op

revision = "0031_research_browse"
down_revision = "0030_browse_ingestion"
branch_labels = None
depends_on = None

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

PREVIOUS_DIRTY_SQL = """
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

PREVIOUS_RECEIPT_SQL = """
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


def _document_scope(scoped):
    op.execute("DROP TRIGGER IF EXISTS dirty_browse ON pursuit_documents")
    op.execute("DROP TRIGGER invalidate_browse ON pursuit_documents")
    scope = "scoped" if scoped else "full"
    op.execute(f"""
        CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
        ON pursuit_documents FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_generation('{scope}')
    """)
    if scoped:
        op.execute("""
            CREATE TRIGGER dirty_browse AFTER INSERT OR UPDATE OR DELETE ON pursuit_documents
            FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
        """)


def _invalidate():
    op.execute(
        "UPDATE browse_state SET prepared_generation_id = NULL, "
        "full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1"
    )


def upgrade():
    op.execute(PURSUIT_SCOPE_SQL)
    op.execute(DIRTY_SQL)
    op.execute(RECEIPT_SQL)
    _document_scope(True)
    _invalidate()


def downgrade():
    _document_scope(False)
    op.execute(PREVIOUS_DIRTY_SQL)
    op.execute(PREVIOUS_RECEIPT_SQL)
    op.execute("DROP FUNCTION scope_browse_pursuit(jsonb, bigint)")
    _invalidate()
