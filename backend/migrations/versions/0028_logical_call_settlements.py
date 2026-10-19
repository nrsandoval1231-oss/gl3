"""Append-only late billing and token usage receipts."""

from alembic import op

revision = "0028_logical_call_settlements"
down_revision = "0027_intelligence_review"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE logical_call_settlements (
            id UUID PRIMARY KEY,
            call_id UUID NOT NULL REFERENCES logical_calls(id),
            actor VARCHAR(120) NOT NULL CHECK (length(trim(actor)) > 0),
            receipt_ref VARCHAR(200) NOT NULL CHECK (length(trim(receipt_ref)) > 0),
            settled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            actual_cost_usd NUMERIC(14,6) CHECK
                (actual_cost_usd >= 0 AND actual_cost_usd <= 1000000),
            input_tokens BIGINT CHECK (input_tokens >= 0),
            output_tokens BIGINT CHECK (output_tokens >= 0),
            CONSTRAINT uq_call_settlement_receipt UNIQUE(call_id, receipt_ref),
            CONSTRAINT ck_call_settlement_has_measurement CHECK
                (actual_cost_usd IS NOT NULL OR input_tokens IS NOT NULL OR output_tokens IS NOT NULL)
        );
        CREATE INDEX ix_logical_call_settlements_call_id ON logical_call_settlements(call_id);
        CREATE FUNCTION reject_logical_call_settlement_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'logical call settlements are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_logical_call_settlements_append_only
            BEFORE UPDATE OR DELETE ON logical_call_settlements
            FOR EACH ROW EXECUTE FUNCTION reject_logical_call_settlement_mutation();
    """)


def downgrade():
    op.execute("""
        DROP TABLE logical_call_settlements;
        DROP FUNCTION IF EXISTS reject_logical_call_settlement_mutation();
    """)
