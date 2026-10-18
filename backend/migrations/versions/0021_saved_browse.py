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
    op.execute("INSERT INTO browse_state (id) VALUES (1)")
    op.execute("""CREATE FUNCTION invalidate_browse_generation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        UPDATE browse_state SET input_revision = input_revision + 1 WHERE id = 1;
        RETURN NULL; END $$""")
    for table in INPUT_TABLES:
        op.execute(
            f"CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation()"
        )


def downgrade():
    for table in INPUT_TABLES:
        op.execute(f"DROP TRIGGER invalidate_browse ON {table}")
    op.execute("DROP FUNCTION invalidate_browse_generation()")
    op.drop_table("browse_rows")
    op.drop_table("browse_generations")
    op.drop_table("browse_state")
