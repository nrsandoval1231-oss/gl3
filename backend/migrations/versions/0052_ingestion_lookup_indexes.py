"""Index ingestion and browse-invalidation lookups that previously scanned whole tables."""

from alembic import op

revision = "0052_ingestion_lookup_indexes"
down_revision = "0051_canonical_need_aliases"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_projects_source_external", "projects", "source_id, external_id"),
    ("ix_need_observations_observation", "need_observations", "observation_id"),
    ("ix_lifecycle_events_observation", "lifecycle_events", "observation_id"),
    ("ix_lifecycle_events_evidence", "lifecycle_events", "evidence_id"),
    ("ix_buying_chain_evidence_retained", "buying_chain_evidence", "retained_evidence_id"),
    ("ix_interconnection_fact_evidence", "interconnection_fact_versions", "evidence_id"),
)


def upgrade() -> None:
    # Built concurrently so retained ingestion writes are not blocked during deployment.
    with op.get_context().autocommit_block():
        for name, table, columns in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _table, _columns in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
