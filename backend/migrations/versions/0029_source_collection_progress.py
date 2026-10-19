"""Bounded source schedule and collection checkpoints."""

from alembic import op

revision = "0029_source_collection_progress"
down_revision = "0028_logical_call_settlements"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE source_schedule_progress (
            epoch_id UUID PRIMARY KEY REFERENCES source_schedule_epochs(id) ON DELETE CASCADE,
            recent_cursor TIMESTAMPTZ,
            history_cursor TIMESTAMPTZ,
            last_planned_at TIMESTAMPTZ
        );
        CREATE TABLE source_collection_progress (
            id UUID PRIMARY KEY,
            source_id VARCHAR(100) NOT NULL REFERENCES sources(id),
            lane VARCHAR(80) NOT NULL,
            policy_digest VARCHAR(64) NOT NULL CHECK (length(policy_digest) = 64),
            window_start TIMESTAMPTZ,
            window_end TIMESTAMPTZ,
            cursor JSONB NOT NULL DEFAULT '{}'::jsonb
                CHECK (length(CAST(cursor AS TEXT)) <= 8192),
            completed_through TIMESTAMPTZ,
            status VARCHAR(20) NOT NULL DEFAULT 'incomplete'
                CHECK (status IN ('incomplete', 'complete', 'partial', 'error')),
            error_class VARCHAR(80),
            last_attempt_at TIMESTAMPTZ,
            last_completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_source_collection_progress_key UNIQUE(source_id, lane, policy_digest)
        );
        CREATE INDEX ix_source_collection_progress_source_id
            ON source_collection_progress(source_id);
    """)


def downgrade():
    op.execute("""
        DROP TABLE source_collection_progress;
        DROP TABLE source_schedule_progress;
    """)
