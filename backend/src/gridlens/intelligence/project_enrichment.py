"""Read-only project power enrichment over canonical needs and accepted facts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.power_enrichment import PowerEnrichment, build_power_enrichment
from gridlens.persistence.models import PowerNeed, Project


def project_power_enrichment(session: Session, project_id: UUID | str) -> PowerEnrichment | None:
    """Project exact-scope accepted schedules for one eligible project.

    This is a read-only projection. It uses the canonical project site, active power
    needs, and the same current accepted-fact loader used by qualification. Imported
    rows and raw retained source observations are never read here.
    """
    try:
        canonical_id = project_id if isinstance(project_id, UUID) else UUID(str(project_id))
    except (ValueError, TypeError, AttributeError):
        return None

    project = session.get(Project, canonical_id)
    if (
        project is None
        or project.region_status != "ELIGIBLE"
        or not isinstance(project.location, str)
        or not project.location.strip()
    ):
        return None

    needs = session.scalars(
        select(PowerNeed)
        .where(PowerNeed.project_id == canonical_id, PowerNeed.active.is_(True))
        .order_by(PowerNeed.activity_key, PowerNeed.id)
    ).all()
    if not needs:
        return build_power_enrichment(project={"id": str(project.id)}, needs=[], operator_facts=[])

    # Import locally because ingestion.service also imports several intelligence
    # helpers. This avoids making its module graph depend on this read projection.
    from gridlens.ingestion.service import load_current_need_operator_inputs

    facts_by_need, _statuses = load_current_need_operator_inputs(
        session, [need.id for need in needs]
    )
    need_inputs = []
    fact_inputs = []
    canonical_scope = " ".join(project.location.split())
    for need in needs:
        need_inputs.append(
            {
                "id": str(need.id),
                "project_id": str(project.id),
                "activity_key": need.activity_key,
                "facility_scope": canonical_scope,
            }
        )
        for fact in facts_by_need.get(need.id, []):
            if (
                fact.project_id != project.id
                or fact.need_id != need.id
                or fact.activity_key != need.activity_key
                or " ".join(fact.facility_scope.split()).casefold() != canonical_scope.casefold()
            ):
                continue
            fact_inputs.append(
                {
                    "fact_version_id": str(fact.id),
                    "fact_type": fact.fact_type,
                    "project_id": str(fact.project_id),
                    "need_id": str(fact.need_id),
                    "activity_key": fact.activity_key,
                    "facility_scope": " ".join(fact.facility_scope.split()),
                    "value": fact.value,
                    "content_hash": fact.content_hash,
                    "authority": fact.confirmation_channel,
                    "source_reference": fact.source_reference,
                    "source_date": (
                        fact.source_date.isoformat() if fact.source_date is not None else None
                    ),
                    "confirmed_at": fact.confirmed_at,
                    "reporter_name": fact.reporter_name,
                    "reporter_organization": fact.reporter_organization,
                    "reporter_role": fact.reporter_role,
                }
            )

    return build_power_enrichment(
        project={"id": str(project.id)},
        needs=need_inputs,
        operator_facts=fact_inputs,
    )
