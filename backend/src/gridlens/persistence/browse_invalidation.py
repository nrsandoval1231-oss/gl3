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
    "pursuits",
    "pursuit_documents",
    "pursuit_call_notes",
    "interconnection_fact_versions",
    "editorial_decisions",
    "editorial_assessments",
    "change_events",
    "project_material_states",
)


# Only these tables have a proven project-local dependency boundary. All other
# mutations (including source/evidence corrections) conservatively require a full build.
SCOPED_TABLES = (
    "power_needs",
    "call_fact_versions",
    "call_fact_decisions",
    "need_workflow_status_events",
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
DIRTY_SQL = """
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


def install(connection):
    connection.exec_driver_sql("INSERT INTO browse_state (id) VALUES (1) ON CONFLICT DO NOTHING")
    connection.exec_driver_sql(INVALIDATE_SQL)
    connection.exec_driver_sql(DIRTY_SQL)
    for table in INPUT_TABLES:
        scope = "scoped" if table in SCOPED_TABLES else "full"
        connection.exec_driver_sql(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('{scope}')
        """)
        if table in SCOPED_TABLES:
            connection.exec_driver_sql(f"""
                CREATE TRIGGER dirty_browse AFTER INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()
            """)
