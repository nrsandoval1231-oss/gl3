"""Represent explicit financial policy and nullable maximum on logical calls."""

import sqlalchemy as sa
from alembic import op

revision = "0039_call_financial_policy"
down_revision = "0038_customer_evidence_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "logical_calls",
        "estimated_cost_usd",
        existing_type=sa.Numeric(12, 6),
        nullable=True,
    )
    op.alter_column(
        "logical_calls",
        "max_cost_usd",
        existing_type=sa.Numeric(12, 6),
        nullable=True,
    )
    op.add_column(
        "logical_calls",
        sa.Column("financial_budget_mode", sa.String(24), nullable=False, server_default="finite"),
    )
    op.add_column(
        "logical_calls",
        sa.Column("financial_authorization_ref", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_unlimited_or_unknown = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM logical_calls "
            "WHERE financial_budget_mode = 'owner_unlimited' "
            "OR estimated_cost_usd IS NULL OR max_cost_usd IS NULL)"
        )
    ).scalar()
    if has_unlimited_or_unknown:
        raise RuntimeError("cannot downgrade while unlimited or unknown financial rows exist")
    op.drop_column("logical_calls", "financial_authorization_ref")
    op.drop_column("logical_calls", "financial_budget_mode")
    op.alter_column(
        "logical_calls",
        "max_cost_usd",
        existing_type=sa.Numeric(12, 6),
        nullable=False,
    )
    op.alter_column(
        "logical_calls",
        "estimated_cost_usd",
        existing_type=sa.Numeric(12, 6),
        nullable=False,
    )
