"""Persist an explicit evidence-backed project region decision."""

import sqlalchemy as sa
from alembic import op

revision = "0040_project_region_policy"
down_revision = "0039_call_financial_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("region_status", sa.String(12), nullable=False, server_default="HOLD")
    )
    op.add_column("projects", sa.Column("region_state", sa.String(2), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "region_reason",
            sa.String(80),
            nullable=False,
            server_default="project_site_state_unknown",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "region_provenance",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_projects_region_status", "projects", ["region_status"])
    op.create_index("ix_projects_region_state", "projects", ["region_state"])
    from gridlens.domain.regional_scope import classify_project_region

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, location, identity_facts, source_id, external_id FROM projects")
    ).mappings()
    for row in rows:
        # This migration is a frozen v1 backfill even if the live registry later expands.
        decision = classify_project_region(
            row["location"],
            row["identity_facts"],
            eligible_states=("TX", "OK", "NM"),
            policy_version="regional-project-scope-v1",
        )
        provenance = {
            **decision.provenance,
            "project_identity": {
                "source_id": row["source_id"],
                "external_id": row["external_id"],
            },
        }
        bind.execute(
            sa.text(
                "UPDATE projects SET region_status=:status, region_state=:state, region_reason=:reason, region_provenance=CAST(:provenance AS jsonb) WHERE id=:id"
            ),
            {
                "id": row["id"],
                "status": decision.status,
                "state": decision.state,
                "reason": decision.reason,
                "provenance": __import__("json").dumps(provenance),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_projects_region_state", table_name="projects")
    op.drop_index("ix_projects_region_status", table_name="projects")
    op.drop_column("projects", "region_provenance")
    op.drop_column("projects", "region_reason")
    op.drop_column("projects", "region_state")
    op.drop_column("projects", "region_status")
