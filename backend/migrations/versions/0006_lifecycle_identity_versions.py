"""Retain version-bound identity rationale and lifecycle corrections.

Revision ID: 0006_lifecycle_identity_versions
Revises: 0005_asset_lifecycles
"""
# SQL predicates below intentionally retain database-side multiline review structure.
# ruff: noqa: E501

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_lifecycle_identity_versions"
down_revision = "0005_asset_lifecycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0005 used publication dates as lifecycle event dates. Clear only unsupported
    # dates; retain source-event dates and reset affected projections for bound replay.
    op.execute(
        """DELETE FROM project_lifecycles AS pl WHERE EXISTS (
            SELECT 1 FROM lifecycle_events AS le JOIN evidence AS e ON e.id = le.evidence_id
            WHERE le.project_id = pl.project_id AND le.occurred_on IS NOT NULL AND (
                e.event_date IS NULL OR (
                    e.event_date_label IS NOT NULL AND NOT CASE le.event_type
                        WHEN 'drilling_permit' THEN e.event_date_label ILIKE '%permit%'
                        WHEN 'spud' THEN e.event_date_label ILIKE '%spud%'
                        WHEN 'completion' THEN e.event_date_label ILIKE '%completion%'
                        WHEN 'first_production' THEN e.event_date_label ILIKE '%production%'
                        WHEN 'construction' THEN e.event_date_label ILIKE '%construction%' OR e.event_date_label ILIKE '%grading%'
                        WHEN 'electrical_buildout' THEN e.event_date_label ILIKE '%electrical%' OR e.event_date_label ILIKE '%substation%' OR e.event_date_label ILIKE '%transformer%'
                        WHEN 'commissioning' THEN e.event_date_label ILIKE '%commission%'
                        WHEN 'utility_service' THEN e.event_date_label ILIKE '%utility%' OR e.event_date_label ILIKE '%service%' OR e.event_date_label ILIKE '%energiz%'
                        WHEN 'permit' THEN e.event_date_label ILIKE '%permit%'
                        WHEN 'regulatory_application' THEN e.event_date_label ILIKE '%application%' OR e.event_date_label ILIKE '%environmental%' OR e.event_date_label ILIKE '%permit%'
                        WHEN 'epc_procurement' THEN e.event_date_label ILIKE '%epc%' OR e.event_date_label ILIKE '%procurement%' OR e.event_date_label ILIKE '%contractor%'
                        WHEN 'commissioning_startup' THEN e.event_date_label ILIKE '%commission%' OR e.event_date_label ILIKE '%startup%'
                        WHEN 'operation' THEN e.event_date_label ILIKE '%operation%' OR e.event_date_label ILIKE '%in service%'
                        ELSE false
                    END
                ) OR (le.event_type NOT IN (
                    'drilling_permit', 'permit', 'regulatory_application'
                ) AND EXISTS (
                    SELECT 1 FROM observations AS o
                    WHERE o.id = e.observation_id AND o.source_id LIKE '%-building-permits'
                ))
            )
        )"""
    )
    op.execute(
        """UPDATE lifecycle_events AS le SET occurred_on = NULL
        FROM evidence AS e
        WHERE le.evidence_id = e.id AND le.occurred_on IS NOT NULL AND (
            e.event_date IS NULL OR (
                e.event_date_label IS NOT NULL AND NOT CASE le.event_type
                    WHEN 'drilling_permit' THEN e.event_date_label ILIKE '%permit%'
                    WHEN 'spud' THEN e.event_date_label ILIKE '%spud%'
                    WHEN 'completion' THEN e.event_date_label ILIKE '%completion%'
                    WHEN 'first_production' THEN e.event_date_label ILIKE '%production%'
                    WHEN 'construction' THEN e.event_date_label ILIKE '%construction%' OR e.event_date_label ILIKE '%grading%'
                    WHEN 'electrical_buildout' THEN e.event_date_label ILIKE '%electrical%' OR e.event_date_label ILIKE '%substation%' OR e.event_date_label ILIKE '%transformer%'
                    WHEN 'commissioning' THEN e.event_date_label ILIKE '%commission%'
                    WHEN 'utility_service' THEN e.event_date_label ILIKE '%utility%' OR e.event_date_label ILIKE '%service%' OR e.event_date_label ILIKE '%energiz%'
                    WHEN 'permit' THEN e.event_date_label ILIKE '%permit%'
                    WHEN 'regulatory_application' THEN e.event_date_label ILIKE '%application%' OR e.event_date_label ILIKE '%environmental%' OR e.event_date_label ILIKE '%permit%'
                    WHEN 'epc_procurement' THEN e.event_date_label ILIKE '%epc%' OR e.event_date_label ILIKE '%procurement%' OR e.event_date_label ILIKE '%contractor%'
                    WHEN 'commissioning_startup' THEN e.event_date_label ILIKE '%commission%' OR e.event_date_label ILIKE '%startup%'
                    WHEN 'operation' THEN e.event_date_label ILIKE '%operation%' OR e.event_date_label ILIKE '%in service%'
                    ELSE false
                END
            ) OR (le.event_type NOT IN (
                'drilling_permit', 'permit', 'regulatory_application'
            ) AND EXISTS (
                SELECT 1 FROM observations AS o
                WHERE o.id = e.observation_id AND o.source_id LIKE '%-building-permits'
            ))
        )"""
    )
    op.add_column(
        "projects",
        sa.Column("identity_facts", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("project_match_decisions", sa.Column("evidence_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_match_decision_evidence", "project_match_decisions", "evidence", ["evidence_id"], ["id"]
    )
    op.add_column(
        "project_match_decisions",
        sa.Column("identity_facts", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.drop_constraint("uq_project_match_candidate", "project_match_decisions", type_="unique")
    op.alter_column("project_match_decisions", "candidate_project_id", nullable=True)
    op.create_unique_constraint(
        "uq_project_match_candidate_version",
        "project_match_decisions",
        ["observation_id", "candidate_project_id", "evidence_id"],
    )
    op.drop_constraint("uq_lifecycle_event_replay", "lifecycle_events", type_="unique")
    op.create_unique_constraint(
        "uq_lifecycle_event_replay",
        "lifecycle_events",
        ["project_id", "observation_id", "evidence_id", "event_type", "state"],
    )


def downgrade() -> None:
    op.drop_column("projects", "identity_facts")
    op.drop_constraint(
        "uq_project_match_candidate_version", "project_match_decisions", type_="unique"
    )
    op.execute("DELETE FROM project_match_decisions WHERE candidate_project_id IS NULL")
    op.alter_column("project_match_decisions", "candidate_project_id", nullable=False)
    op.create_unique_constraint(
        "uq_project_match_candidate",
        "project_match_decisions",
        ["observation_id", "candidate_project_id"],
    )
    op.drop_constraint("uq_lifecycle_event_replay", "lifecycle_events", type_="unique")
    op.create_unique_constraint(
        "uq_lifecycle_event_replay",
        "lifecycle_events",
        ["project_id", "observation_id", "event_type", "state"],
    )
    op.drop_column("project_match_decisions", "identity_facts")
    op.drop_constraint("fk_match_decision_evidence", "project_match_decisions", type_="foreignkey")
    op.drop_column("project_match_decisions", "evidence_id")
