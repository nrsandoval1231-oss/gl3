"""Allow append-only parser metadata receipts on an unchanged staged workbook."""

import sqlalchemy as sa
from alembic import op

revision = "0046_import_meta_reparse"
down_revision = "0045_contact_suppressions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_external_import_event_action",
        "external_import_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_external_import_event_action",
        "external_import_events",
        "action IN ('staged', 'metadata_reparsed', 'rolled_back') AND ("
        "action <> 'metadata_reparsed' OR ("
        "COALESCE(jsonb_typeof(details) = 'object', false) AND "
        "COALESCE(details ->> 'kind' = 'metadata_reparse', false) AND "
        "COALESCE(jsonb_typeof(details -> 'parser_revision') = 'string', false) AND "
        "COALESCE(length(btrim(details ->> 'parser_revision')) BETWEEN 1 AND 120, false) AND "
        "COALESCE(jsonb_typeof(details -> 'metadata_fingerprint') = 'string', false) AND "
        "COALESCE(details ->> 'metadata_fingerprint' ~ '^[0-9a-f]{64}$', false) AND "
        "COALESCE(jsonb_typeof(details -> 'source_content_hash') = 'string', false) AND "
        "COALESCE(details ->> 'source_content_hash' ~ '^[0-9a-f]{64}$', false) AND "
        "COALESCE(jsonb_typeof(details -> 'hyperlink_hints') = 'array', false) AND "
        "COALESCE(CASE WHEN jsonb_typeof(details -> 'hyperlink_hints') = 'array' "
        "THEN jsonb_array_length(details -> 'hyperlink_hints')::text = "
        "details ->> 'target_count' ELSE false END, false) AND "
        "COALESCE(jsonb_typeof(details -> 'target_count') = 'number', false) AND "
        "COALESCE(details ->> 'target_count' ~ '^[1-9][0-9]{0,5}$' AND ("
        "length(details ->> 'target_count') < 6 OR details ->> 'target_count' <= '100000'), false)"
        "))",
    )
    op.drop_constraint(
        "uq_external_import_event_batch_action",
        "external_import_events",
        type_="unique",
    )
    op.create_index(
        "uq_external_import_event_batch_lifecycle",
        "external_import_events",
        ["batch_id", "action"],
        unique=True,
        postgresql_where=sa.text("action IN ('staged', 'rolled_back')"),
    )
    op.create_index(
        "uq_external_import_event_batch_metadata_revision",
        "external_import_events",
        ["batch_id", sa.text("(details ->> 'parser_revision')")],
        unique=True,
        postgresql_where=sa.text(
            "action = 'metadata_reparsed'"
        ),
    )
    op.create_index(
        "uq_external_import_event_batch_metadata_fingerprint",
        "external_import_events",
        ["batch_id", sa.text("(details ->> 'metadata_fingerprint')")],
        unique=True,
        postgresql_where=sa.text("action = 'metadata_reparsed'"),
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM external_import_events "
            "WHERE action = 'metadata_reparsed'"
        )
    )
    if count:
        raise RuntimeError(
            "metadata receipts are immutable; retain this schema for application rollback or "
            "restore a verified pre-reparse backup"
        )
    op.drop_index(
        "uq_external_import_event_batch_metadata_fingerprint", table_name="external_import_events"
    )
    op.drop_index(
        "uq_external_import_event_batch_metadata_revision", table_name="external_import_events"
    )
    op.drop_index(
        "uq_external_import_event_batch_lifecycle", table_name="external_import_events"
    )
    op.create_unique_constraint(
        "uq_external_import_event_batch_action",
        "external_import_events",
        ["batch_id", "action"],
    )
    op.drop_constraint(
        "ck_external_import_event_action", "external_import_events", type_="check"
    )
    op.create_check_constraint(
        "ck_external_import_event_action",
        "external_import_events",
        "action IN ('staged', 'rolled_back')",
    )
