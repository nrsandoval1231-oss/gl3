"""Make browse dirty-project invalidation index-driven and statement-level.

The row-level dirty_browse trigger called dirty_browse_project() once per written row, locking
browse_state each time and scanning projects/evidence tables without an index for observation
writes. Statement-level triggers with transition tables lock browse_state once per statement and
record every affected project in one set-based insert. Trigger names (dirty_browse_*) sort before
invalidate_browse*, so each statement still reads input_revision + 1 before
invalidate_browse_generation advances it.
"""

from alembic import op

revision = "0056_statement_dirty_projects"
down_revision = "0055_project_match_keys"
branch_labels = None
depends_on = None

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

# Frozen copy of the function and trigger definitions installed by migrations 0030-0054, restored
# verbatim by downgrade().
OLD_DIRTY_SQL = """
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


# Frozen copy of the statement-level definitions (kept in parity with
# gridlens.persistence.browse_invalidation by tests/integration/test_dirty_statement_triggers.py).
# Index-driven: each branch resolves its keys once and uses an index (projects by
# (source_id, external_id), need/lifecycle/evidence rows by their observation or evidence
# columns). The result set equals the earlier single-OR formulation for every input.
OBSERVATION_PROJECTS_SQL = """
    CREATE OR REPLACE FUNCTION browse_observation_projects(
        oid uuid, eid uuid, source_key text, external_key text
    ) RETURNS TABLE(project_id uuid) LANGUAGE sql STABLE AS $$
        SELECT n.project_id FROM need_observations l
            JOIN power_needs n ON n.id = l.need_id WHERE l.observation_id = oid
        UNION
        SELECT p.id FROM projects p
            WHERE p.source_id = source_key AND p.external_id = external_key
        UNION
        SELECT p.id FROM observations o
            JOIN projects p ON p.source_id = o.source_id AND p.external_id = o.external_id
            WHERE o.id = oid
        UNION
        SELECT l.project_id FROM lifecycle_events l WHERE l.observation_id = oid
        UNION
        SELECT l.project_id FROM lifecycle_events l WHERE l.evidence_id = eid
        UNION
        SELECT l.project_id FROM evidence e
            JOIN lifecycle_events l ON l.evidence_id = e.id WHERE e.observation_id = oid
        UNION
        SELECT b.project_id FROM buying_chain_evidence b WHERE b.retained_evidence_id = eid
        UNION
        SELECT b.project_id FROM evidence e
            JOIN buying_chain_evidence b ON b.retained_evidence_id = e.id
            WHERE e.observation_id = oid
        UNION
        SELECT f.project_id FROM interconnection_fact_versions f WHERE f.evidence_id = eid
        UNION
        SELECT f.project_id FROM evidence e
            JOIN interconnection_fact_versions f ON f.evidence_id = e.id
            WHERE e.observation_id = oid
        UNION
        SELECT m.candidate_project_id FROM project_match_decisions m
            WHERE m.observation_id = oid AND m.candidate_project_id IS NOT NULL
    $$
"""

# Statement-level dirty-project recording (PostgreSQL allows transition tables only on
# single-event triggers, hence one function per operation). Trigger names sort before
# invalidate_browse*, so next_revision is read before invalidate_browse_generation
# increments input_revision, exactly as the row-level triggers it replaced.
_DIRTY_PROJECT_ID_TABLES = (
    "power_needs",
    "project_lifecycles",
    "lifecycle_events",
    "project_material_states",
    "buying_chain_evidence",
    "buying_chain_claims",
    "buying_chain_runs",
    "interconnection_fact_versions",
)
_DIRTY_NEED_TABLES = (
    "call_fact_versions",
    "call_fact_decisions",
    "need_workflow_status_events",
    "need_observations",
    "power_need_briefs",
    "power_need_brief_versions",
)
# table -> (observation id, evidence id, direct project id, source key, external key)
_DIRTY_OBSERVATION_TABLES = {
    "observations": ("r.id", "NULL::uuid", None, "r.source_id", "r.external_id"),
    "evidence": ("r.observation_id", "r.id", None, "NULL::text", "NULL::text"),
    "interpretations": ("r.observation_id", "NULL::uuid", None, "NULL::text", "NULL::text"),
    "signal_decisions": ("r.observation_id", "NULL::uuid", None, "NULL::text", "NULL::text"),
    "change_events": ("r.observation_id", "NULL::uuid", "r.project_id", "NULL::text", "NULL::text"),
    "project_match_decisions": (
        "r.observation_id",
        "NULL::uuid",
        "r.candidate_project_id",
        "NULL::text",
        "NULL::text",
    ),
}


def _dirty_insert(select):
    return (
        "INSERT INTO browse_dirty_projects(project_id, revision) "
        + select
        + " ON CONFLICT (project_id) DO UPDATE SET revision = EXCLUDED.revision;"
    )


def _dirty_statement_function(operation):
    rows = {
        "insert": "new_rows",
        "delete": "old_rows",
        "update": "(SELECT * FROM old_rows UNION ALL SELECT * FROM new_rows)",
    }[operation]
    full = "UPDATE browse_state SET full_revision = next_revision WHERE id = 1;"
    id_list = ", ".join(f"'{t}'" for t in _DIRTY_PROJECT_ID_TABLES)
    need_list = ", ".join(f"'{t}'" for t in _DIRTY_NEED_TABLES)
    projects = _dirty_insert(
        f"SELECT DISTINCT r.id, next_revision FROM {rows} r WHERE r.id IS NOT NULL"
    )
    owned = _dirty_insert(
        f"SELECT DISTINCT r.project_id, next_revision FROM {rows} r WHERE r.project_id IS NOT NULL"
    )
    needs = _dirty_insert(
        f"SELECT DISTINCT n.project_id, next_revision FROM {rows} r"
        " JOIN power_needs n ON n.id = r.need_id WHERE n.project_id IS NOT NULL"
    )
    branches = [
        f"IF TG_TABLE_NAME = 'projects' THEN\n            {projects}",
        f"ELSIF TG_TABLE_NAME IN ({id_list}) THEN\n            {owned}",
        f"""ELSIF TG_TABLE_NAME IN ({need_list}) THEN
            IF EXISTS (SELECT 1 FROM {rows} r WHERE NOT EXISTS (
                SELECT 1 FROM power_needs n WHERE n.id = r.need_id AND n.project_id IS NOT NULL
            )) THEN
                {full}
            END IF;
            {needs}""",
        f"""ELSIF TG_TABLE_NAME = 'pursuit_documents' THEN
            FOR pursuit IN SELECT DISTINCT r.pursuit_id FROM {rows} r LOOP
                IF NOT scope_browse_pursuit(
                    (SELECT to_jsonb(p) FROM pursuits p WHERE p.id = pursuit), next_revision
                ) THEN
                    {full}
                END IF;
            END LOOP;""",
    ]
    for table, (oid, eid, pid, source, external) in _DIRTY_OBSERVATION_TABLES.items():
        direct = f"SELECT {pid} AS project_id FROM {rows} r UNION ALL " if pid else ""
        # A known unlinked observation has no browse consumer yet. Its later
        # link/direct project insertion will invalidate that owner.
        linked = _dirty_insert(
            f"SELECT DISTINCT s.project_id, next_revision FROM ({direct}"
            f"SELECT a.project_id FROM {rows} r CROSS JOIN LATERAL"
            f" browse_observation_projects({oid}, {eid}, {source}, {external}) a"
            f" WHERE {oid} IS NOT NULL) s WHERE s.project_id IS NOT NULL"
        )
        branches.append(f"ELSIF TG_TABLE_NAME = '{table}' THEN\n            {linked}")
    branches.append(f"ELSE\n            {full}\n        END IF;")
    body = "\n        ".join(branches)
    return f"""
    CREATE OR REPLACE FUNCTION dirty_browse_project_{operation}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE next_revision bigint; pursuit uuid;
    BEGIN
        -- Statements that touched no rows never dirtied or fenced anything.
        IF NOT EXISTS (SELECT 1 FROM {rows} r) THEN RETURN NULL; END IF;
        PERFORM set_config('gridlens.browse_dirty', '1', true);
        -- Acquire the writer/publication fence BEFORE scanning dependencies, once per
        -- statement. Separate statements see dependencies committed while waiting on it.
        SELECT input_revision + 1 INTO next_revision FROM browse_state WHERE id = 1 FOR UPDATE;
        {body}
        RETURN NULL;
    END $$
"""


DIRTY_FUNCTIONS = tuple(
    _dirty_statement_function(operation) for operation in ("insert", "update", "delete")
)
DIRTY_SQL = OBSERVATION_PROJECTS_SQL + ";\n" + ";\n".join(DIRTY_FUNCTIONS)

DIRTY_TRIGGER_OPERATIONS = (
    ("insert", "INSERT", "REFERENCING NEW TABLE AS new_rows"),
    ("update", "UPDATE", "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows"),
    ("delete", "DELETE", "REFERENCING OLD TABLE AS old_rows"),
)
# Initial fact versions/decisions are drafted by their own insert triggers.
DIRTY_NO_INSERT_TABLES = ("call_fact_versions", "call_fact_decisions")


def _create_row_trigger(table: str) -> None:
    operations = (
        "UPDATE OR DELETE" if table in DIRTY_NO_INSERT_TABLES else "INSERT OR UPDATE OR DELETE"
    )
    op.execute(f"""
        CREATE TRIGGER dirty_browse AFTER {operations} ON {table}
        FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
    """)


def upgrade() -> None:
    # Fail fast rather than queue behind (and deadlock with) live ingestion transactions.
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in SCOPED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS dirty_browse ON {table}")
    op.execute(DIRTY_SQL)
    for table in SCOPED_TABLES:
        for name, operation, transition in DIRTY_TRIGGER_OPERATIONS:
            if name == "insert" and table in DIRTY_NO_INSERT_TABLES:
                continue
            op.execute(f"""
                CREATE TRIGGER dirty_browse_{name} AFTER {operation} ON {table}
                {transition} FOR EACH STATEMENT EXECUTE FUNCTION dirty_browse_project_{name}()
            """)
    op.execute("DROP FUNCTION IF EXISTS dirty_browse_project()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in SCOPED_TABLES:
        for name, _operation, _transition in DIRTY_TRIGGER_OPERATIONS:
            op.execute(f"DROP TRIGGER IF EXISTS dirty_browse_{name} ON {table}")
    op.execute(OLD_DIRTY_SQL)
    for table in SCOPED_TABLES:
        _create_row_trigger(table)
    for name, _operation, _transition in DIRTY_TRIGGER_OPERATIONS:
        op.execute(f"DROP FUNCTION IF EXISTS dirty_browse_project_{name}()")
