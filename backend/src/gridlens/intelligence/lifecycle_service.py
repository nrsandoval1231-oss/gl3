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
    Interpretation,
    LifecycleEvent,
    Observation,
    Project,
    ProjectLifecycle,
)


def apply_lifecycle_observation(
    session: Session, project: Project, observation: Observation, evidence: Evidence
) -> bool:
    """Append a version-bound reported event and rebuild the current projection."""
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    assessment = interpretation.assessment if interpretation else None
    if (
        interpretation is None
        or interpretation.status != "accepted"
        or not assessment
        or assessment.get("evidence_hash") != evidence.content_hash
    ):
        _rebuild_projection(session, project)
        return False
    classification = classify_event(evidence.title, evidence.abstract)
    if classification is None:
        _rebuild_projection(session, project)
        return False
    if project.asset_type not in {"unknown", classification.asset_type.value}:
        _rebuild_projection(session, project)
        return False
    project.asset_type = classification.asset_type.value
    existing = session.scalar(
        select(LifecycleEvent).where(
            LifecycleEvent.project_id == project.id,
            LifecycleEvent.observation_id == observation.id,
            LifecycleEvent.evidence_id == evidence.id,
            LifecycleEvent.event_type == classification.event_type,
            LifecycleEvent.state == classification.state,
        )
    )
    if existing is None:
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type=classification.event_type,
                state=classification.state,
                value_kind="reported",
                occurred_on=_supported_event_date(evidence, classification.event_type),
            )
        )
    else:
        existing.occurred_on = _supported_event_date(evidence, classification.event_type)
    _rebuild_projection(session, project)
    return existing is None


def apply_planning_withdrawal(
    session: Session, project: Project, observation: Observation, evidence: Evidence
) -> bool:
    """Retain an official linked application withdrawal and update its projection."""
    existing = session.scalar(
        select(LifecycleEvent).where(
            LifecycleEvent.project_id == project.id,
            LifecycleEvent.observation_id == observation.id,
            LifecycleEvent.evidence_id == evidence.id,
            LifecycleEvent.event_type == "planning_application_withdrawn",
        )
    )
    if existing is None:
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="planning_application_withdrawn",
                state="planning_application_withdrawn",
                value_kind="reported",
                occurred_on=evidence.published_at,
            )
        )
    _rebuild_projection(session, project)
    return existing is None


def refresh_lifecycle_projection(session: Session, project: Project) -> None:
    """Recompute current state after an interpretation correction."""
    _rebuild_projection(session, project)


def _supported_event_date(evidence: Evidence, event_type: str):
    if evidence.event_date is None:
        return None
    label = (evidence.event_date_label or "").casefold()
    if not label:
        return evidence.event_date
    aliases = {
        "drilling_permit": ("permit",),
        "spud": ("spud",),
        "completion": ("completion",),
        "first_production": ("production",),
        "construction": ("construction", "grading"),
        "electrical_buildout": ("electrical", "substation", "transformer"),
        "commissioning": ("commission",),
        "utility_service": ("utility", "service", "energiz"),
        "permit": ("permit",),
        "regulatory_application": ("application", "environmental", "permit"),
        "epc_procurement": ("epc", "procurement", "contractor"),
        "commissioning_startup": ("commission", "startup"),
        "operation": ("operation", "in service"),
    }
    return (
        evidence.event_date
        if any(term in label for term in aliases.get(event_type, (event_type,)))
        else None
    )


def _rebuild_projection(session: Session, project: Project) -> None:
    # A correction supersedes only that observation's earlier interpretation.
    events = session.scalars(
        select(LifecycleEvent)
        .join(Evidence, LifecycleEvent.evidence_id == Evidence.id)
        .where(LifecycleEvent.project_id == project.id)
        .order_by(
            Evidence.observed_at,
            Evidence.content_hash,
            LifecycleEvent.recorded_at,
            LifecycleEvent.id,
        )
    ).all()
    accepted_events = []
    for event in events:
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == event.observation_id)
        )
        evidence = session.get(Evidence, event.evidence_id)
        supported_withdrawal = (
            evidence is not None
            and event.event_type == "planning_application_withdrawn"
            and interpretation is not None
            and interpretation.assessment is not None
            and interpretation.assessment.get("withdrawal_supported") is True
            and interpretation.assessment.get("evidence_hash") == evidence.content_hash
        )
        if supported_withdrawal or (
            evidence is not None
            and interpretation is not None
            and interpretation.status == "accepted"
            and interpretation.assessment is not None
            and interpretation.assessment.get("evidence_hash") == evidence.content_hash
        ):
            accepted_events.append(event)
    # Filter to the currently bound accepted version first: an A→B→A correction
    # must reactivate retained A evidence even though B was recorded later.
    current_by_observation: dict[object, LifecycleEvent] = {}
    for event in accepted_events:
        current_by_observation[event.observation_id] = event
    current = list(current_by_observation.values())
    projection = session.get(ProjectLifecycle, project.id)
    if not current:
        if projection is not None:
            session.delete(projection)
        project.asset_type = "unknown"
        return
    withdrawal_events = [
        item for item in current if item.event_type == "planning_application_withdrawn"
    ]
    if withdrawal_events:
        withdrawal = max(
            withdrawal_events,
            key=lambda item: (item.occurred_on or item.recorded_at.date(), item.recorded_at),
        )
        withdrawal_evidence = session.get(Evidence, withdrawal.evidence_id)
        later_positive = any(
            item.event_type != "planning_application_withdrawn"
            and (positive_evidence := session.get(Evidence, item.evidence_id)) is not None
            and withdrawal_evidence is not None
            and positive_evidence.published_at is not None
            and withdrawal_evidence.published_at is not None
            and positive_evidence.published_at > withdrawal_evidence.published_at
            for item in current
        )
        if not later_positive:
            if projection is None:
                projection = ProjectLifecycle(project_id=project.id, current_state=withdrawal.state)
                session.add(projection)
            projection.current_state = withdrawal.state
            projection.expected_next_milestone = None
            projection.expected_power_event = None
            projection.monitoring_requirements = [
                "Check for a new application or official project-status update."
            ]
            projection.open_questions = ["Project status after withdrawal is UNKNOWN."]
            projection.time_to_power_start = projection.time_to_power_end = None
            projection.estimate_basis = None
            projection.estimate_version = None
            session.flush()
            return
        current = [item for item in current if item.event_type != "planning_application_withdrawn"]
    current.sort(
        key=lambda item: (
            lifecycle_rank(AssetType(project.asset_type), item.state),
            item.occurred_on or item.recorded_at.date(),
        )
    )
    event = current[-1]
    evidence = session.get(Evidence, event.evidence_id)
    assert evidence is not None
    classification = classify_event(evidence.title, evidence.abstract)
    assert classification is not None
    if projection is None:
        projection = ProjectLifecycle(project_id=project.id, current_state=event.state)
        session.add(projection)
    projection.current_state = event.state
    projection.expected_next_milestone = classification.expected_next_milestone
    projection.expected_power_event = classification.expected_power_event
    projection.monitoring_requirements = list(classification.monitoring_requirements)
    projection.open_questions = []
    projection.time_to_power_start = projection.time_to_power_end = None
    projection.estimate_basis = None
    projection.estimate_version = None
    if (
        classification.asset_type == AssetType.UPSTREAM_WELL
        and event.event_type in {"drilling_permit", "spud", "completion"}
        and event.occurred_on
    ):
        estimate = estimate_first_production(
            permit_date=event.occurred_on,
            spud_date=event.occurred_on if event.event_type == "spud" else None,
            completion_date=event.occurred_on if event.event_type == "completion" else None,
        )
        projection.time_to_power_start, projection.time_to_power_end = (
            estimate.window_start,
            estimate.window_end,
        )
        projection.estimate_basis = {
            "value_kind": estimate.value_kind,
            "confidence": estimate.confidence,
            "inputs": {f"{event.event_type}_date": event.occurred_on.isoformat()},
            "rules": list(estimate.basis),
        }
        projection.estimate_version = estimate.rule_version
        projection.open_questions = list(estimate.missing_evidence)
        projection.expected_next_milestone = estimate.next_milestone
    session.flush()
