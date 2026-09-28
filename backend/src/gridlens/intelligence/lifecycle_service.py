from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.lifecycle import (
    AssetType,
    classify_event,
    estimate_first_production,
    lifecycle_rank,
)
from gridlens.persistence.models import (
    Evidence,
    LifecycleEvent,
    Observation,
    Project,
    ProjectLifecycle,
)


def apply_lifecycle_observation(
    session: Session, project: Project, observation: Observation, evidence: Evidence
) -> bool:
    """Attach one evidence-backed event and refresh the projection; safe on replay."""
    classification = classify_event(evidence.title, evidence.abstract)
    if classification is None:
        return False
    if project.asset_type not in {"unknown", classification.asset_type.value}:
        return False
    existing = session.scalar(
        select(LifecycleEvent.id).where(
            LifecycleEvent.project_id == project.id,
            LifecycleEvent.observation_id == observation.id,
            LifecycleEvent.event_type == classification.event_type,
            LifecycleEvent.state == classification.state,
        )
    )
    if existing is not None:
        return False
    project.asset_type = classification.asset_type.value
    session.add(
        LifecycleEvent(
            project_id=project.id,
            observation_id=observation.id,
            evidence_id=evidence.id,
            event_type=classification.event_type,
            state=classification.state,
            value_kind="reported",
            occurred_on=evidence.event_date or evidence.published_at,
        )
    )
    projection = session.get(ProjectLifecycle, project.id)
    if projection is None:
        projection = ProjectLifecycle(project_id=project.id, current_state=classification.state)
        session.add(projection)
    advances = projection.current_state == classification.state or lifecycle_rank(
        classification.asset_type, classification.state
    ) >= lifecycle_rank(classification.asset_type, projection.current_state)
    if not advances:
        session.flush()
        return True
    projection.current_state = classification.state
    projection.expected_next_milestone = classification.expected_next_milestone
    projection.expected_power_event = classification.expected_power_event
    projection.monitoring_requirements = list(classification.monitoring_requirements)
    projection.open_questions = []
    projection.time_to_power_start = projection.time_to_power_end = None
    projection.estimate_basis = None
    projection.estimate_version = None
    if classification.asset_type == AssetType.UPSTREAM_WELL and classification.event_type in {
        "drilling_permit",
        "spud",
        "completion",
    }:
        anchor = evidence.event_date or evidence.published_at
        if anchor:
            estimate = estimate_first_production(
                permit_date=anchor,
                spud_date=anchor if classification.event_type == "spud" else None,
                completion_date=anchor if classification.event_type == "completion" else None,
            )
            projection.time_to_power_start = estimate.window_start
            projection.time_to_power_end = estimate.window_end
            projection.estimate_basis = {
                "value_kind": estimate.value_kind,
                "confidence": estimate.confidence,
                "inputs": {f"{classification.event_type}_date": anchor.isoformat()},
                "rules": list(estimate.basis),
            }
            projection.estimate_version = estimate.rule_version
            projection.open_questions = list(estimate.missing_evidence)
            projection.expected_next_milestone = estimate.next_milestone
    session.flush()
    return True
