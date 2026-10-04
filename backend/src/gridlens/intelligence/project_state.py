"""Read-only, evidence-version-bound current state for one project."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.commercial_presentation import canonical_mw_claim
from gridlens.domain.project_research import VERSION, project_claim_state
from gridlens.domain.signal_admission import admitted_from_source
from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION
from gridlens.intelligence.buying_chain import _accepted_version, buying_chain_view
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported
from gridlens.intelligence.project_identity import canonical_site_claim, normalized_identity
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    LifecycleEvent,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectMatchDecision,
    Source,
)


def _provenance(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": str(evidence.id),
        "url": evidence.url,
        "extraction_location": evidence.extraction_location,
        "source_date": evidence.event_date or evidence.published_at,
        "retrieved_at": evidence.observed_at,
        "support": "accepted interpretation",
    }


def _unknown() -> dict[str, Any]:
    return {"value": None, "status": "UNKNOWN"}


def _supported(value: Any, evidence: list[Evidence]) -> dict[str, Any]:
    return (
        {"value": value, "status": "SUPPORTED", "evidence": [_provenance(e) for e in evidence]}
        if evidence
        else _unknown()
    )


def _conflict(values: list[tuple[Any, Evidence]], *, mw: bool = False) -> dict[str, Any]:
    if not values:
        return _unknown()
    key = canonical_mw_claim if mw else lambda value: value
    if all(key(value) == key(values[0][0]) for value, _ in values):
        return _supported(values[-1][0], list({e.id: e for _, e in values}.values()))
    return {
        "value": None,
        "status": "CONFLICT",
        "claims": [
            {"value": value, "evidence": _provenance(evidence)} for value, evidence in values
        ],
    }


def current_research_state(
    session: Session, project_id: UUID, need_id: UUID | None = None
) -> dict[str, dict]:
    """Current exact-bound typed source reports, independent of qualification.

    Immutable historical evidence is intentionally excluded when its observation
    or interpretation now represents a different version or a rejection.
    """
    project = session.get(Project, project_id)
    if project is None:
        return {}
    query = (
        select(PowerNeed, Observation, Evidence, Interpretation)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(PowerNeed.project_id == project_id)
    )
    if need_id is not None:
        query = query.where(PowerNeed.id == need_id)
    claims: dict[str, list[dict]] = defaultdict(list)
    for need, observation, evidence, interpretation in session.execute(query):
        assessment = interpretation.assessment or {}
        if not (
            interpretation.status == "accepted"
            and interpretation.evaluator_version == VERSION
            and assessment.get("acquisition_capture_version") == CAPTURE_VERSION
            and assessment.get("admission_status") == "project_research_supplement"
            and assessment.get("project_identity_key") == project.identity_key
            and assessment.get("target_need_id") == str(need.id)
            and observation.content_hash == evidence.content_hash == interpretation.content_hash
            and assessment.get("evidence_hash") == evidence.content_hash
        ):
            continue
        for claim in assessment.get("research_claims", []):
            if not (
                claim.get("project_id") == str(project.id)
                and claim.get("need_id") == str(need.id)
                and claim.get("activity_key") == need.activity_key
                and claim.get("evidence_id") == str(evidence.id)
                and claim.get("evidence_hash") == evidence.content_hash
                and claim.get("quote")
                and claim["quote"] in (evidence.abstract or "")
            ):
                continue
            claims[str(need.id)].append({**claim, "evidence": _provenance(evidence)})
    return {key: project_claim_state(rows, today=date.today()) for key, rows in claims.items()}


def _accepted_need_evidence(
    session: Session, project: Project
) -> dict[UUID, dict[str, list[tuple[Any, Evidence]]]]:
    rows = session.execute(
        select(NeedObservation.need_id, PowerNeed, Evidence, Interpretation, Observation, Source)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
        .join(Source, Source.id == Observation.source_id)
        .where(PowerNeed.project_id == project.id)
        .order_by(Evidence.observed_at, Evidence.id)
    ).all()
    result: dict[UUID, dict[str, list[tuple[Any, Evidence]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for need_id, need, evidence, interpretation, _observation, source in rows:
        assessment = interpretation.assessment or {}
        if not (
            _accepted_version(interpretation, evidence)
            and assessment.get("project_identity_key") == project.identity_key
            and (assessment.get("power_activity") or assessment.get("activity_key"))
            == need.activity_key
            and admitted_from_source(source, assessment, evidence).admitted
        ):
            continue
        result[need_id]["activity"].append((need.activity_key, evidence))
        for field, assessment_key in (("identity", "subject"), ("site", "location")):
            value = assessment.get(assessment_key)
            if isinstance(value, str) and value.strip():
                result[need_id][field].append((value, evidence))
        for field, assessment_key in (
            ("tier", "tier"),
            ("mw", "demand_mw"),
            ("timing", "start_window"),
            ("duration", "duration"),
            ("qualified_remaining_gap", "qualified_remaining_gap"),
        ):
            value = assessment.get(assessment_key)
            if value is not None and value != "":
                result[need_id][field].append((value, evidence))
        if assessment.get("tier") in {"Prospect", "Lead"}:
            result[need_id]["supply"].append(("Reported constraint", evidence))
    return result


def _projected_claim(
    value: Any, claims: list[tuple[Any, Evidence]], *, mw: bool = False
) -> dict[str, Any]:
    """Show eligible contradictions, but do not attest an unsupported mutable value."""
    if not claims:
        return _unknown()
    key = canonical_mw_claim if mw else lambda item: item
    if any(key(claim) != key(claims[0][0]) for claim, _ in claims):
        return _conflict(claims, mw=mw)
    if value is None or value == "" or key(claims[0][0]) != key(value):
        return _unknown()
    return _conflict(claims, mw=mw)


def _need_fields(
    need: PowerNeed, evidence: dict[str, list[tuple[Any, Evidence]]]
) -> dict[str, Any]:
    """Keep each commercial input independently inspectable and explicitly unknown."""
    return {
        "activity": _projected_claim(need.activity_key, evidence["activity"]),
        "tier": _projected_claim(need.tier, evidence["tier"]),
        "mw": _projected_claim(need.required_mw, evidence["mw"], mw=True),
        "timing": _projected_claim(need.start_window, evidence["timing"]),
        "duration": _projected_claim(need.duration, evidence["duration"]),
        "supply": _projected_claim(need.supply, evidence["supply"]),
        **(
            {"qualified_remaining_gap": _conflict(evidence["qualified_remaining_gap"])}
            if need.tier == "Lead"
            else {}
        ),
    }


def _project_field_claim(
    value: str | None, claims: list[tuple[str, Evidence]], *, site: bool = False
) -> dict[str, Any]:
    """Attest a stored project field only from its own current claim."""
    if not claims:
        return _unknown()

    key = canonical_site_claim if site else normalized_identity

    def equivalent(left: str, right: str) -> bool:
        return key(left) == key(right)

    first = claims[0][0]
    if any(not equivalent(first, claim) for claim, _ in claims):
        return {
            "value": None,
            "status": "CONFLICT",
            "claims": [
                {"value": claim, "evidence": _provenance(evidence)} for claim, evidence in claims
            ],
        }
    if not value or not equivalent(value, first):
        return _unknown()
    return _supported(value, list({evidence.id: evidence for _, evidence in claims}.values()))


def project_state(session: Session, project_id: UUID) -> dict[str, Any] | None:
    project = session.get(Project, project_id)
    if project is None:
        return None
    need_evidence = _accepted_need_evidence(session, project)
    needs = session.scalars(
        select(PowerNeed).where(PowerNeed.project_id == project_id).order_by(PowerNeed.activity_key)
    ).all()
    all_evidence = list(
        {
            evidence.id: evidence
            for fields in need_evidence.values()
            for rows in fields.values()
            for _, evidence in rows
        }.values()
    )
    lifecycle_events = session.scalars(
        select(LifecycleEvent)
        .where(LifecycleEvent.project_id == project_id)
        .order_by(LifecycleEvent.recorded_at, LifecycleEvent.id)
    ).all()
    accepted_lifecycle: list[tuple[LifecycleEvent, Evidence]] = []
    for event in lifecycle_events:
        evidence = session.get(Evidence, event.evidence_id)
        interpretation = (
            session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == evidence.observation_id
                )
            )
            if evidence
            else None
        )
        if evidence and lifecycle_event_supported(
            event.event_type, evidence, interpretation, project
        ):
            accepted_lifecycle.append((event, evidence))
    # ProjectLifecycle is the current projection. Earlier accepted lifecycle
    # events document progression; they are not contradictory current claims.
    current_projection = session.get(ProjectLifecycle, project_id)
    lifecycle_values = [
        (event.state, evidence)
        for event, evidence in accepted_lifecycle
        if current_projection and event.state == current_projection.current_state
    ]
    utility_values = [
        (event.occurred_on, evidence)
        for event, evidence in accepted_lifecycle
        if event.occurred_on and ("utility" in event.event_type or "energiz" in event.event_type)
    ]
    active_needs = [n for n in needs if n.active and need_evidence[n.id].get("activity")]
    identity_claims = [
        claim for need in active_needs for claim in need_evidence[need.id]["identity"]
    ]
    site_claims = [claim for need in active_needs for claim in need_evidence[need.id]["site"]]
    state: dict[str, Any] = {
        "identity": _project_field_claim(project.name, identity_claims),
        "site": _project_field_claim(project.location, site_claims, site=True),
        "lifecycle": _supported(
            {
                "state": current_projection.current_state,
                "value_kinds": sorted({event.value_kind for event, _ in accepted_lifecycle}),
                "basis": "current lifecycle projection; source event labels retained below",
            },
            [evidence for _, evidence in lifecycle_values],
        )
        if current_projection
        else _unknown(),
        "activity": _supported(
            [n.activity_key for n in active_needs],
            [e for n in active_needs for _, e in need_evidence[n.id]["activity"]],
        )
        if active_needs
        else _unknown(),
        "power_need": _supported(
            [_need_fields(n, need_evidence[n.id]) for n in active_needs],
            [e for n in active_needs for _, e in need_evidence[n.id]["activity"]],
        )
        if active_needs
        else _unknown(),
        "utility_service": _conflict(utility_values),
        "commissioning": _unknown(),
        "temporary_power_demand": _unknown(),
        "buyer_authority": _unknown(),
    }
    chain = buying_chain_view(session, project_id)
    parties = [
        {
            "organization": c["organization"],
            "person": c.get("person_name"),
            "title": c.get("title"),
            "category": c.get("category"),
            "organization_relationship": c["organization_relationship"],
            "person_project_relationship": c["person_project_relationship"],
            "status": "SUPPORTED",
            "citations": c["evidence"],
            "public_contacts": c["public_contacts"],
        }
        for c in chain["candidates"]
        if not c.get("stale")
    ]
    decisions = session.scalars(
        select(ProjectMatchDecision)
        .where(ProjectMatchDecision.candidate_project_id == project_id)
        .order_by(ProjectMatchDecision.decided_at.desc(), ProjectMatchDecision.id.desc())
    ).all()
    return {
        "project_id": str(project.id),
        "identity_key": project.identity_key,
        "state": state,
        "research_state": current_research_state(session, project_id),
        "organizations_and_roles": parties,
        "lifecycle_events": [
            {
                "state": e.state,
                "event_type": e.event_type,
                "value_kind": e.value_kind,
                "date": e.occurred_on,
                "evidence_id": str(e.evidence_id),
            }
            for e in lifecycle_events
        ],
        "evidence": [
            {**_provenance(e), "title": e.title, "hash": e.content_hash, "current": True}
            for e in all_evidence
        ],
        "candidate_matches": [
            {
                "candidate_project_id": str(d.candidate_project_id)
                if d.candidate_project_id
                else None,
                "evidence_id": str(d.evidence_id) if d.evidence_id else None,
                "decision": d.decision,
                "reason": d.reason,
                "matched_facts": d.matched_facts,
            }
            for d in decisions
        ],
        "unresolved": chain["unresolved"],
        "disclosure": (
            "Only accepted current evidence supports facts; "
            "conflicting and unavailable facts remain explicit."
        ),
    }
