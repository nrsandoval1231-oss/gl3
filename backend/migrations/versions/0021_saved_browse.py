"""Versioned retained-data browse generations and transactional invalidation."""

from alembic import op

revision = "0021_saved_browse"
down_revision = "0020_evidence_source_provenance"
branch_labels = None
depends_on = None

# Frozen migration definitions; do not import mutable runtime models/table lists.
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


def upgrade():
    op.execute(
        """
        CREATE TABLE browse_state (
            id SERIAL NOT NULL,
            input_revision BIGINT DEFAULT '0' NOT NULL,
            generation_id UUID,
            full_revision BIGINT DEFAULT '0' NOT NULL,
            PRIMARY KEY (id)
        )
    """
    )
    op.execute(
        """
        CREATE TABLE browse_generations (
            id UUID NOT NULL,
            input_revision BIGINT NOT NULL,
            policy_version VARCHAR(100) NOT NULL,
            built_at TIMESTAMP WITH TIME ZONE NOT NULL,
            valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
            row_count INTEGER NOT NULL,
            digest VARCHAR(64) NOT NULL,
            counts JSONB NOT NULL,
            PRIMARY KEY (id)
        )
    """
    )
    op.execute(
        """
        CREATE TABLE browse_rows (
            generation_id UUID NOT NULL,
            need_id UUID NOT NULL,
            project_id UUID NOT NULL,
            tier VARCHAR(20) NOT NULL,
            location TEXT NOT NULL,
            industry TEXT NOT NULL,
            activity TEXT NOT NULL,
            has_timing BOOLEAN NOT NULL,
            mw_low NUMERIC,
            mw_high NUMERIC,
            priority_segment INTEGER NOT NULL,
            workflow_status VARCHAR(30) NOT NULL,
            signal_decision VARCHAR(10) NOT NULL,
            project_group VARCHAR(43) NOT NULL,
            single_group VARCHAR(43) NOT NULL,
            rank_score INTEGER NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            search_text TEXT NOT NULL,
            display_title TEXT NOT NULL,
            summary JSONB NOT NULL,
            compact JSONB NOT NULL,
            PRIMARY KEY (generation_id, need_id),
            FOREIGN KEY(generation_id) REFERENCES browse_generations (id) ON DELETE CASCADE
        )
    """
    )
    op.execute(
        """
        CREATE INDEX ix_browse_dimensions ON browse_rows (generation_id, location, industry, activity)
    """
    )
    op.execute(
        """
        CREATE INDEX ix_browse_global_rank ON browse_rows (generation_id, rank_score DESC, updated_at DESC, need_id)
    """
    )
    op.execute("""
        CREATE INDEX ix_browse_project ON browse_rows (generation_id, project_id, tier)
    """)
    op.execute(
        """
        CREATE INDEX ix_browse_rank ON browse_rows (generation_id, tier, rank_score DESC, updated_at DESC, need_id)
    """
    )
    op.execute(
        """
        CREATE INDEX ix_browse_updated ON browse_rows (generation_id, tier, updated_at DESC, need_id)
    """
    )
    op.execute(
        "CREATE TABLE browse_dirty_projects (project_id UUID PRIMARY KEY, revision BIGINT NOT NULL)"
    )
    op.execute("INSERT INTO browse_state (id) VALUES (1)")
    op.execute("""
    CREATE OR REPLACE FUNCTION invalidate_browse_generation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        UPDATE browse_state SET
            full_revision = CASE WHEN TG_OP = 'TRUNCATE' OR TG_ARGV[0] = 'full'
                THEN input_revision + 1 ELSE full_revision END,
            input_revision = input_revision + 1 WHERE id = 1;
        RETURN NULL;
    END $$
""")
    op.execute("""
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
""")
    for table in INPUT_TABLES:
        scope = (
            "scoped"
            if table
            in (
                "power_needs",
                "call_fact_versions",
                "call_fact_decisions",
                "need_workflow_status_events",
            )
            else "full"
        )
        op.execute(
            f"CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('{scope}')"
        )
        if scope == "scoped":
            op.execute(
                f"CREATE TRIGGER dirty_browse AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION dirty_browse_project()"
            )


def downgrade():
    for table in INPUT_TABLES:
        op.execute(f"DROP TRIGGER invalidate_browse ON {table}")
        if table in (
            "power_needs",
            "call_fact_versions",
            "call_fact_decisions",
            "need_workflow_status_events",
        ):
            op.execute(f"DROP TRIGGER dirty_browse ON {table}")
    op.execute("DROP FUNCTION dirty_browse_project()")
    op.execute("DROP FUNCTION invalidate_browse_generation()")
    op.drop_table("browse_dirty_projects")
    op.drop_table("browse_rows")
    op.drop_table("browse_generations")
    op.drop_table("browse_state")
