"""Read-only, evidence-version-bound current state for one project."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import _accepted_version, buying_chain_view
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


def _conflict(values: list[tuple[Any, Evidence]]) -> dict[str, Any]:
    if not values:
        return _unknown()
    if len({str(value) for value, _ in values}) == 1:
        return _supported(values[-1][0], [values[-1][1]])
    return {
        "value": None,
        "status": "CONFLICT",
        "claims": [
            {"value": value, "evidence": _provenance(evidence)} for value, evidence in values
        ],
    }


def _accepted_need_evidence(session: Session, project_id: UUID) -> dict[UUID, list[Evidence]]:
    rows = session.execute(
        select(NeedObservation.need_id, Evidence, Interpretation)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
        .where(PowerNeed.project_id == project_id)
        .order_by(Evidence.observed_at, Evidence.id)
    ).all()
    result: dict[UUID, list[Evidence]] = defaultdict(list)
    for need_id, evidence, interpretation in rows:
        if _accepted_version(interpretation, evidence):
            result[need_id].append(evidence)
    return result


def _need_fields(need: PowerNeed, evidence: list[Evidence]) -> dict[str, Any]:
    """Keep each commercial input independently inspectable and explicitly unknown."""
    return {
        "activity": _supported(need.activity_key, evidence),
        "tier": _supported(need.tier, evidence),
        "mw": _supported(need.required_mw, evidence) if need.required_mw else _unknown(),
        "timing": _supported(need.start_window, evidence) if need.start_window else _unknown(),
        "duration": _supported(need.duration, evidence) if need.duration else _unknown(),
        "supply": _supported(need.supply, evidence)
        if need.supply and need.supply.casefold() != "unknown"
        else _unknown(),
    }


def project_state(session: Session, project_id: UUID) -> dict[str, Any] | None:
    project = session.get(Project, project_id)
    if project is None:
        return None
    need_evidence = _accepted_need_evidence(session, project_id)
    needs = session.scalars(
        select(PowerNeed).where(PowerNeed.project_id == project_id).order_by(PowerNeed.activity_key)
    ).all()
    all_evidence = [e for rows in need_evidence.values() for e in rows]
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
        if evidence and _accepted_version(interpretation, evidence):
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
        if event.occurred_on
        and ("utility" in event.event_type or "energiz" in event.event_type)
    ]
    active_needs = [n for n in needs if n.active and need_evidence.get(n.id)]
    state: dict[str, Any] = {
        "identity": _supported(project.name, all_evidence),
        "site": _supported(project.location, all_evidence) if project.location else _unknown(),
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
            [e for n in active_needs for e in need_evidence[n.id]],
        )
        if active_needs
        else _unknown(),
        "power_need": _supported(
            [_need_fields(n, need_evidence[n.id]) for n in active_needs],
            [e for n in active_needs for e in need_evidence[n.id]],
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
