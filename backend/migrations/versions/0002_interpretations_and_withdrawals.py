"""retryable interpretation backlog and visible Signal withdrawal"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_interpretations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "active" not in {column["name"] for column in inspector.get_columns("power_needs")}:
        op.add_column(
            "power_needs",
            sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        )
    if "interpretations" not in inspector.get_table_names():
        op.create_table(
            "interpretations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["observation_id"], ["observations.id"]),
            sa.UniqueConstraint("observation_id", name="uq_interpretation_observation"),
        )
    if "uq_change_version" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("change_events")
    }:
        op.drop_constraint("uq_change_version", "change_events", type_="unique")


def downgrade() -> None:
    op.drop_table("interpretations")
    op.drop_column("power_needs", "active")
    op.create_unique_constraint(
        "uq_change_version", "change_events", ["observation_id", "content_hash"]
    )
