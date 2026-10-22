"""Add evidence-bound cross-project buying-chain identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_reconciled_identity"
down_revision = "0034_fact_draft_browse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "person_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    owner_check = "(company_identity_id IS NOT NULL) <> (person_identity_id IS NOT NULL)"
    op.create_table(
        "identity_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(12), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('company', 'person')", name="ck_identity_identifier_entity_type"
        ),
        sa.Column(
            "company_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_identities.id"),
        ),
        sa.Column(
            "person_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("person_identities.id"),
        ),
        sa.Column("identifier_type", sa.String(40), nullable=False),
        sa.Column("normalized_value", sa.String(240), nullable=False),
        sa.Column(
            "source_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buying_chain_evidence.id"),
            nullable=False,
        ),
        sa.Column("source_version_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(owner_check, name="ck_identity_identifier_one_owner"),
        sa.UniqueConstraint(
            "entity_type",
            "identifier_type",
            "normalized_value",
            name="uq_identity_identifier_value",
        ),
    )
    op.create_table(
        "buying_chain_identity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buying_chain_claims.id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(12), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('company', 'person')", name="ck_buying_identity_link_entity_type"
        ),
        sa.Column(
            "company_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_identities.id"),
        ),
        sa.Column(
            "person_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("person_identities.id"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("basis", sa.String(24), nullable=False, server_default="strong_identifier"),
        sa.Column("reviewed_by", sa.String(120)),
        sa.Column(
            "source_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buying_chain_evidence.id"),
            nullable=False,
        ),
        sa.Column("source_version_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="current"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(owner_check, name="ck_buying_identity_link_one_owner"),
    )
    op.create_index(
        "ix_buying_identity_link_current", "buying_chain_identity_links", ["claim_id", "state"]
    )
    op.create_index(
        "uq_buying_identity_link_one_current",
        "buying_chain_identity_links",
        ["claim_id", "entity_type"],
        unique=True,
        postgresql_where=sa.text("state = 'current'"),
    )


def downgrade() -> None:
    op.drop_index("uq_buying_identity_link_one_current", table_name="buying_chain_identity_links")
    op.drop_index("ix_buying_identity_link_current", table_name="buying_chain_identity_links")
    op.drop_table("buying_chain_identity_links")
    op.drop_table("identity_identifiers")
    op.drop_table("person_identities")
    op.drop_table("company_identities")
