"""Transactional project-scoped ingestion browse publication."""

from alembic import op

revision = "0030_browse_ingestion"
down_revision = "0029_source_collection_progress"
branch_labels = None
depends_on = None

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

PREVIOUS_DIRTY_SQL = """
    CREATE OR REPLACE FUNCTION dirty_browse_project() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; pid uuid; next_revision bigint;
    BEGIN
        SELECT input_revision + 1 INTO next_revision FROM browse_state WHERE id = 1 FOR UPDATE;
        FOR payload IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP = 'INSERT' THEN jsonb_build_array(to_jsonb(NEW))
                 WHEN TG_OP = 'DELETE' THEN jsonb_build_array(to_jsonb(OLD))
                 ELSE jsonb_build_array(to_jsonb(OLD), to_jsonb(NEW)) END)
        LOOP
            IF TG_TABLE_NAME = 'power_needs' THEN
                pid := (payload->>'project_id')::uuid;
            ELSE
                SELECT project_id INTO pid FROM power_needs WHERE id = (payload->>'need_id')::uuid;
            END IF;
            IF pid IS NULL THEN
                UPDATE browse_state SET full_revision = next_revision WHERE id = 1;
            ELSE
                INSERT INTO browse_dirty_projects(project_id, revision) VALUES(pid, next_revision)
                ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;
            END IF;
        END LOOP;
        RETURN NULL;
    END $$
"""

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
)
PREVIOUS_SCOPED_TABLES = (
    "power_needs",
    "call_fact_versions",
    "call_fact_decisions",
    "need_workflow_status_events",
)


def _replace_scopes(scoped):
    for table in SCOPED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS dirty_browse ON {table}")
        op.execute(f"DROP TRIGGER invalidate_browse ON {table}")
        scope = "scoped" if table in scoped else "full"
        op.execute(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('{scope}')
        """)
        if table in scoped:
            op.execute(f"""
                CREATE TRIGGER dirty_browse AFTER INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
            """)


def upgrade():
    op.execute(DIRTY_SQL)
    op.execute(SOURCE_HEALTH_SQL)
    _replace_scopes(SCOPED_TABLES)
    op.execute("DROP TRIGGER invalidate_browse ON sources")
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER INSERT OR DELETE OR TRUNCATE ON sources
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full');
        CREATE TRIGGER invalidate_browse_source_update AFTER UPDATE ON sources
        REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
        EXECUTE FUNCTION invalidate_browse_source_update();
    """)
    # Force one full publication under the new dependency policy.
    op.execute(
        "UPDATE browse_state SET prepared_generation_id = NULL, "
        "full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1"
    )


def downgrade():
    _replace_scopes(PREVIOUS_SCOPED_TABLES)
    op.execute(PREVIOUS_DIRTY_SQL)
    op.execute("DROP TRIGGER invalidate_browse_source_update ON sources")
    op.execute("DROP FUNCTION invalidate_browse_source_update()")
    op.execute("DROP FUNCTION browse_observation_projects(uuid, uuid, text, text)")
    op.execute("DROP TRIGGER invalidate_browse ON sources")
    op.execute("""
        CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON sources
        FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')
    """)
    op.execute(
        "UPDATE browse_state SET prepared_generation_id = NULL, "
        "full_revision = input_revision + 1, input_revision = input_revision + 1 WHERE id = 1"
    )
