"""Persist standalone-admission provenance and close legacy context-only Signals."""

# SQL predicates are kept inline so the migration remains a single reviewable update.
# ruff: noqa: E501

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009_signal_admission"
down_revision = "0008_buying_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "power_needs",
        sa.Column(
            "admission_basis", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    # Historical evidence, tiers, and needs remain queryable. Active context-only
    # opportunities are closed from the worklist with their prior state retained
    # in admission_basis.
    op.execute(
        sa.text(
            """
            UPDATE power_needs AS need
               SET active = FALSE,
                   admission_basis = jsonb_build_object(
                       'policy_version', 'signal-admission-v1',
                       'admission_status', 'closed_context',
                       'origin', 'Research context',
                       'prior_active', need.active,
                       'prior_tier', need.tier,
                       'prior_basis', need.admission_basis,
                       'reason', 'No current exact authoritative evidence link supports this opportunity.'
                   )
             WHERE need.active = TRUE
               AND NOT EXISTS (
                   SELECT 1
                     FROM need_observations AS link
                     JOIN observations AS observation ON observation.id = link.observation_id
                     JOIN sources AS source ON source.id = observation.source_id
                     JOIN interpretations AS interpretation
                       ON interpretation.observation_id = observation.id
                     JOIN evidence AS evidence
                       ON evidence.observation_id = observation.id
                      AND evidence.content_hash = interpretation.assessment->>'evidence_hash'
                     CROSS JOIN projects AS project
                    WHERE link.need_id = need.id
                      AND project.id = need.project_id
                      AND interpretation.status = 'accepted'
                      AND interpretation.content_hash = observation.content_hash
                      AND interpretation.assessment->>'decision' = 'accepted'
                      AND interpretation.assessment->>'project_identity_key' = project.identity_key
                      AND coalesce(
                          interpretation.assessment->>'power_activity',
                          interpretation.assessment->>'activity_key'
                      ) = need.activity_key
                      AND (
                          (source.family = 'construction-permits'
                           AND source.retrieval_method IN ('socrata-permits', 'georgia-air-permits'))
                          OR (source.family = 'official-utility-filings'
                              AND source.retrieval_method IN ('utility-docket', 'utility-filings')
                              AND coalesce(evidence.published_at, evidence.event_date) IS NOT NULL
                              AND evidence.url LIKE 'https://%'
                              AND interpretation.assessment->>'subject' IS NOT NULL
                              AND interpretation.assessment->>'location' IS NOT NULL
                              AND btrim(interpretation.assessment->>'subject') <> ''
                              AND btrim(interpretation.assessment->>'location') <> ''
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  LIKE '%' || lower(interpretation.assessment->>'subject') || '%'
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  LIKE '%' || lower(interpretation.assessment->>'location') || '%'
                              AND coalesce(interpretation.assessment->>'power_activity',
                                           interpretation.assessment->>'activity_key') IN
                                  ('temporary-power', 'bridge-power', 'construction',
                                   'facility-expansion', 'commissioning', 'electrical-buildout',
                                   'utility-service')
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  ~ '(utility service|energization|substation|transformer|service agreement|interconnection|load service|power allocation|bridge power)')
                          OR (source.family = 'temporary-power-procurement'
                              AND source.retrieval_method IN ('public-procurement', 'procurement-notice')
                              AND coalesce(evidence.published_at, evidence.event_date) IS NOT NULL
                              AND evidence.url LIKE 'https://%'
                              AND interpretation.assessment->>'subject' IS NOT NULL
                              AND interpretation.assessment->>'location' IS NOT NULL
                              AND btrim(interpretation.assessment->>'subject') <> ''
                              AND btrim(interpretation.assessment->>'location') <> ''
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  LIKE '%' || lower(interpretation.assessment->>'subject') || '%'
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  LIKE '%' || lower(interpretation.assessment->>'location') || '%'
                              AND coalesce(interpretation.assessment->>'power_activity',
                                           interpretation.assessment->>'activity_key') IN
                                  ('temporary-power', 'bridge-power')
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  ~ '(temporary power|temporary generator|rental generator|mobile generator|load bank|loadbank)'
                              AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                                  ~ '(request for quotation|request for proposal|solicitation|bid due|quotes due|procurement notice)')
                      )
               )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE power_needs AS need
               SET admission_basis = jsonb_build_object(
                   'policy_version', 'signal-admission-v1',
                   'origin', CASE
                       WHEN source.family = 'construction-permits' THEN 'Official permit'
                       WHEN source.family = 'official-utility-filings' THEN 'Official utility filing'
                       ELSE 'Temporary-power solicitation'
                   END,
                   'source_id', source.id,
                   'evidence_hash', interpretation.assessment->>'evidence_hash',
                   'reason', 'Existing need retained because a current accepted authoritative source supports it.'
               )
              FROM need_observations AS link
              JOIN observations AS observation ON observation.id = link.observation_id
              JOIN sources AS source ON source.id = observation.source_id
              JOIN interpretations AS interpretation ON interpretation.observation_id = observation.id
              JOIN evidence AS evidence
                ON evidence.observation_id = observation.id
               AND evidence.content_hash = interpretation.assessment->>'evidence_hash'
              CROSS JOIN projects AS project
             WHERE link.need_id = need.id
               AND project.id = need.project_id
               AND need.active = TRUE
               AND interpretation.status = 'accepted'
               AND interpretation.content_hash = observation.content_hash
               AND interpretation.assessment->>'decision' = 'accepted'
               AND interpretation.assessment->>'project_identity_key' = project.identity_key
               AND coalesce(interpretation.assessment->>'power_activity',
                            interpretation.assessment->>'activity_key') = need.activity_key
               AND (
                   (source.family = 'construction-permits'
                    AND source.retrieval_method IN ('socrata-permits', 'georgia-air-permits'))
                   OR (source.family = 'official-utility-filings'
                       AND source.retrieval_method IN ('utility-docket', 'utility-filings')
                       AND coalesce(evidence.published_at, evidence.event_date) IS NOT NULL
                       AND evidence.url LIKE 'https://%'
                       AND interpretation.assessment->>'subject' IS NOT NULL
                       AND interpretation.assessment->>'location' IS NOT NULL
                       AND btrim(interpretation.assessment->>'subject') <> ''
                       AND btrim(interpretation.assessment->>'location') <> ''
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           LIKE '%' || lower(interpretation.assessment->>'subject') || '%'
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           LIKE '%' || lower(interpretation.assessment->>'location') || '%'
                       AND coalesce(interpretation.assessment->>'power_activity',
                                    interpretation.assessment->>'activity_key') IN
                           ('temporary-power', 'bridge-power', 'construction', 'facility-expansion',
                            'commissioning', 'electrical-buildout', 'utility-service')
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           ~ '(utility service|energization|substation|transformer|service agreement|interconnection|load service|power allocation|bridge power)')
                   OR (source.family = 'temporary-power-procurement'
                       AND source.retrieval_method IN ('public-procurement', 'procurement-notice')
                       AND coalesce(evidence.published_at, evidence.event_date) IS NOT NULL
                       AND evidence.url LIKE 'https://%'
                       AND interpretation.assessment->>'subject' IS NOT NULL
                       AND interpretation.assessment->>'location' IS NOT NULL
                       AND btrim(interpretation.assessment->>'subject') <> ''
                       AND btrim(interpretation.assessment->>'location') <> ''
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           LIKE '%' || lower(interpretation.assessment->>'subject') || '%'
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           LIKE '%' || lower(interpretation.assessment->>'location') || '%'
                       AND coalesce(interpretation.assessment->>'power_activity',
                                    interpretation.assessment->>'activity_key') IN
                           ('temporary-power', 'bridge-power')
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           ~ '(temporary power|temporary generator|rental generator|mobile generator|load bank|loadbank)'
                       AND lower(evidence.title || ' ' || coalesce(evidence.abstract, ''))
                           ~ '(request for quotation|request for proposal|solicitation|bid due|quotes due|procurement notice)')
               )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("power_needs", "admission_basis")
