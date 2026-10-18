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


def install(connection):
    connection.exec_driver_sql("INSERT INTO browse_state (id) VALUES (1) ON CONFLICT DO NOTHING")
    connection.exec_driver_sql("""
        CREATE OR REPLACE FUNCTION invalidate_browse_generation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE browse_state SET input_revision = input_revision + 1 WHERE id = 1;
            RETURN NULL;
        END $$
    """)
    for table in INPUT_TABLES:
        connection.exec_driver_sql(f"""
            CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation()
        """)
