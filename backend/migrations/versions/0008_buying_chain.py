"""Project-scoped immutable buying-chain evidence, claims and bounded run results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008_buying_chain"
down_revision = "0007_signal_decisions"
branch_labels = None
depends_on = None


def project_id():
    return sa.Column(
        "project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "buying_chain_evidence",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        project_id(),
        sa.Column("retained_evidence_id", pg.UUID(as_uuid=True), sa.ForeignKey("evidence.id")),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("extraction_location", sa.String(100), nullable=False),
        sa.Column("published_at", sa.Date()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_match_reason", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "url", "content_hash", name="uq_buying_evidence_version"),
    )
    op.create_table(
        "buying_chain_claims",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        project_id(),
        sa.Column("entity_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("organization", sa.Text(), nullable=False),
        sa.Column("person_name", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("organization_relationship", sa.String(20), nullable=False),
        sa.Column("person_organization_relationship", sa.String(20), nullable=False),
        sa.Column("person_project_relationship", sa.String(20), nullable=False),
        sa.Column("evidence_strength", sa.String(10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("citations", pg.JSONB(), nullable=False),
        sa.Column("public_contacts", pg.JSONB(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "fingerprint", name="uq_buying_claim_replay"),
    )
    op.create_table(
        "buying_chain_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        project_id(),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("evidence_ids", pg.JSONB(), nullable=False),
        sa.Column("claim_ids", pg.JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("documents_checked", sa.Integer(), nullable=False),
        sa.Column("candidates_added", sa.Integer(), nullable=False),
        sa.Column("unresolved", pg.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("buying_chain_runs")
    op.drop_table("buying_chain_claims")
    op.drop_table("buying_chain_evidence")
