"""Prepare canonical browse generations ahead of their exact clock boundary."""

from alembic import op

revision = "0022_browse_clock_transitions"
down_revision = "0021_saved_browse"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE browse_state ADD COLUMN prepared_generation_id UUID")
    op.execute("ALTER TABLE browse_generations ADD COLUMN valid_from TIMESTAMPTZ DEFAULT now()")
    op.execute("UPDATE browse_generations SET valid_from = built_at")
    op.execute("ALTER TABLE browse_generations ALTER COLUMN valid_from SET NOT NULL")
    op.execute("""
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
""")


def downgrade():
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
    op.execute("ALTER TABLE browse_state DROP COLUMN prepared_generation_id")
    op.execute("ALTER TABLE browse_generations DROP COLUMN valid_from")
