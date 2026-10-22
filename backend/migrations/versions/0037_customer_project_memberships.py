"""Add versioned source-backed company-to-project memberships."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_customer_memberships"
down_revision = "0036_buying_chain_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_identities",
        sa.Column("rrc_operator_number", sa.String(6), nullable=True, unique=True),
    )
    op.create_table(
        "company_project_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_identities.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("organization_name", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column(
            "source_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.id"),
            nullable=False,
        ),
        sa.Column("source_version_hash", sa.String(64), nullable=False),
        sa.Column("decision_basis", sa.String(80), nullable=False),
        sa.Column("operator_number", sa.String(6), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="current"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role <> ''", name="ck_company_project_membership_role"),
        sa.CheckConstraint(
            "state IN ('current', 'superseded', 'retracted', 'conflicted')",
            name="ck_company_project_membership_state",
        ),
    )
    op.create_index(
        "ix_company_project_membership_current",
        "company_project_memberships",
        ["company_identity_id", "state"],
    )
    op.create_index(
        "uq_company_project_membership_source_current",
        "company_project_memberships",
        ["project_id", "source_id", "role"],
        unique=True,
        postgresql_where=sa.text("state = 'current'"),
    )
    op.create_table(
        "company_project_membership_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_project_memberships.id"),
            nullable=False,
        ),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "membership_id", "idempotency_key", name="uq_membership_correction_idem"
        ),
        sa.CheckConstraint("action = 'retracted'", name="ck_membership_correction_action"),
    )
    op.create_table(
        "browse_customer_memberships",
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("browse_generations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("company_identity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["company_identity_id"], ["company_identities.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index(
        "ix_browse_customer_project", "browse_customer_memberships", ["generation_id", "project_id"]
    )
    op.create_table(
        "browse_unresolved_customers",
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("browse_generations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_name", sa.Text(), primary_key=True),
        sa.Column("role", sa.String(40), primary_key=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index(
        "ix_browse_unresolved_project",
        "browse_unresolved_customers",
        ["generation_id", "project_id"],
    )
    for table in (
        "company_identities",
        "company_project_memberships",
        "company_project_membership_corrections",
        "identity_identifiers",
        "buying_chain_identity_links",
    ):
        op.execute(
            f"CREATE TRIGGER invalidate_browse AFTER INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')"
        )
        op.execute(
            f"CREATE TRIGGER invalidate_browse_truncate AFTER TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION invalidate_browse_generation('full')"
        )


def downgrade() -> None:
    for table in (
        "company_identities",
        "company_project_memberships",
        "company_project_membership_corrections",
        "identity_identifiers",
        "buying_chain_identity_links",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS invalidate_browse_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS invalidate_browse ON {table}")
    op.execute("DROP INDEX IF EXISTS uq_company_project_membership_source_current")
    op.execute("DROP INDEX IF EXISTS ix_company_project_membership_current")
    op.execute("DROP TABLE IF EXISTS company_project_membership_corrections")
    op.execute("DROP INDEX IF EXISTS ix_browse_unresolved_project")
    op.execute("DROP TABLE IF EXISTS browse_unresolved_customers")
    op.execute("DROP INDEX IF EXISTS ix_browse_customer_project")
    op.execute("DROP TABLE IF EXISTS browse_customer_memberships")
    op.drop_table("company_project_memberships")
    op.drop_column("company_identities", "rrc_operator_number")
