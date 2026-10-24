from collections.abc import Sequence
from copy import copy

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.lifecycle import (
    AssetType,
    classify_event,
    estimate_first_production,
    lifecycle_rank,
)
from gridlens.ingestion.adapters.project_asset_classification import (
    TDLR_TABS_SOURCE,
    classify_project_asset,
)
from gridlens.ingestion.adapters.retained_permits import (
    reported_permit_event_type,
    requires_achieved_lifecycle_milestone,
)
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    LifecycleEvent,
    Observation,
    Project,
    ProjectLifecycle,
    ProjectMatchDecision,
)


def _assessment_evidence_id_matches(assessment: dict, evidence: Evidence) -> bool:
    recorded_ids = [assessment.get("evidence_id")]
    evidence_claim = assessment.get("evidence")
    if isinstance(evidence_claim, dict):
        recorded_ids.append(evidence_claim.get("id"))
    return all(
        recorded_id is None or str(recorded_id) == str(evidence.id) for recorded_id in recorded_ids
    )


def lifecycle_event_supported(
    event_type: str,
    evidence: Evidence | None,
    interpretation: Interpretation | None,
    project: Project,
    event_state: str | None = None,
    *,
    event: LifecycleEvent | None = None,
) -> bool:
    """Return whether an event retains valid evidence-bound accepted support."""
    if evidence is None or interpretation is None or not interpretation.assessment:
        return False
    assessment = interpretation.assessment
    observation = evidence.observation
    if (
        observation is None
        or interpretation.observation_id != observation.id
        or evidence.observation_id != interpretation.observation_id
        or observation.content_hash != interpretation.content_hash
        or assessment.get("semantic_hash") != observation.content_hash
        or assessment.get("evidence_hash") != evidence.content_hash
    ):
        return False
    if not _assessment_evidence_id_matches(assessment, evidence):
        return False
    if event is not None and (
        event.project_id != project.id
        or event.observation_id != interpretation.observation_id
        or event.evidence_id != evidence.id
        or event.event_type != event_type
        or (event_state is not None and event.state != event_state)
    ):
        return False
    bound_project = assessment.get("project_identity_key")
    if (
        not isinstance(bound_project, str)
        or not bound_project
        or bound_project != project.identity_key
    ):
        return False
    if event_type == "planning_application_withdrawn":
        if event_state is not None and event_state != event_type:
            return False
    else:
        observation = evidence.observation
        is_rrc = observation.source_id == "texas-rrc-drilling-permits"
        classification = classify_event(
            "Drilling permit" if is_rrc else evidence.title,
            None if is_rrc else evidence.abstract,
            project_name=project.name,
            project_identity_key=project.identity_key,
            project_asset_type=project.asset_type,
            reported_permit_event=reported_permit_event_type(
                observation.source_id,
                evidence.title,
                evidence.abstract,
                evidence.event_date,
                evidence.event_date_label,
            ),
            require_achieved_milestone=requires_achieved_lifecycle_milestone(observation.source_id),
        )
        if (
            classification is None
            or classification.event_type != event_type
            or (event_state is not None and classification.state != event_state)
            or project.asset_type not in {"unknown", classification.asset_type.value}
        ):
            return False
    accepted = interpretation.status == "accepted" or (
        interpretation.status in {"failed", "pending"} and assessment.get("decision") == "accepted"
    )
    if event_type == "planning_application_withdrawn":
        return assessment.get("withdrawal_supported") is True
    return accepted


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
        or interpretation.observation_id != observation.id
        or evidence.observation_id != interpretation.observation_id
        or observation.content_hash != interpretation.content_hash
        or assessment.get("semantic_hash") != observation.content_hash
        or assessment.get("evidence_hash") != evidence.content_hash
        or assessment.get("project_identity_key") != project.identity_key
        or not _assessment_evidence_id_matches(assessment, evidence)
    ):
        _rebuild_projection(session, project)
        return False
    if observation.source_id == "texas-rrc-drilling-permits":
        from gridlens.ingestion.adapters.retained_permits import fields

        project.asset_type = AssetType.UPSTREAM_WELL.value
        kind = fields(observation.source_id, evidence.abstract or "").get("application_type")
        if not kind or kind[0] != "01":
            # An approved recompletion/transfer/reclass filing does not report
            # completed work or a new drilling phase. Keep the well's phase unknown.
            _rebuild_projection(session, project)
            project.asset_type = AssetType.UPSTREAM_WELL.value
            return False
    classification = classify_event(
        "Drilling permit"
        if observation.source_id == "texas-rrc-drilling-permits"
        else evidence.title,
        None if observation.source_id == "texas-rrc-drilling-permits" else evidence.abstract,
        project_name=project.name,
        project_identity_key=project.identity_key,
        project_asset_type=project.asset_type,
        reported_permit_event=reported_permit_event_type(
            observation.source_id,
            evidence.title,
            evidence.abstract,
            evidence.event_date,
            evidence.event_date_label,
        ),
        require_achieved_milestone=requires_achieved_lifecycle_milestone(observation.source_id),
    )
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
        "building_permit_issued": ("permit",),
        "electrical_permit_issued": ("permit",),
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


def _current_project_asset_types(session: Session, project: Project) -> set[str]:
    """Read explicit asset classifications from currently accepted, linked evidence."""
    linked = session.scalars(
        select(ProjectMatchDecision).where(
            ProjectMatchDecision.candidate_project_id == project.id,
            ProjectMatchDecision.decision == "matched",
            ProjectMatchDecision.evidence_id.is_not(None),
        )
    ).all()
    direct_observation = None
    if project.source_id == "texas-tdlr-tabs-data-centers":
        direct_observation = session.scalar(
            select(Observation).where(
                Observation.source_id == project.source_id,
                Observation.external_id == project.external_id,
            )
        )
    observation_ids = {row.observation_id for row in linked}
    if direct_observation is not None:
        observation_ids.add(direct_observation.id)
    if not observation_ids:
        return set()
    decisions = session.scalars(
        select(ProjectMatchDecision)
        .where(ProjectMatchDecision.observation_id.in_(observation_ids))
        .order_by(ProjectMatchDecision.decided_at, ProjectMatchDecision.id)
    ).all()
    latest_by_candidate = {
        (decision.observation_id, decision.evidence_id, decision.candidate_project_id): decision
        for decision in decisions
        if decision.evidence_id is not None
    }
    candidates = {
        (decision.observation_id, decision.evidence_id)
        for decision in latest_by_candidate.values()
        if decision.candidate_project_id == project.id and decision.decision == "matched"
    }
    if direct_observation is not None:
        for direct_evidence in session.scalars(
            select(Evidence).where(Evidence.observation_id == direct_observation.id)
        ).all():
            own_decision = latest_by_candidate.get(
                (direct_observation.id, direct_evidence.id, project.id)
            )
            separate_decision = latest_by_candidate.get(
                (direct_observation.id, direct_evidence.id, None)
            )
            # A newly ingested TDLR primary record is retained as a separate
            # project when no existing candidate matches. That null-candidate
            # decision does not invalidate the project's own exact source ID.
            # A decision explicitly about this project is authoritative and a
            # current unmatched/separate decision must retract its support.
            if (own_decision and own_decision.decision == "matched") or (
                own_decision is None
                and (separate_decision is None or separate_decision.decision == "separate")
            ):
                candidates.add((direct_observation.id, direct_evidence.id))

    asset_types: set[str] = set()
    for observation_id, evidence_id in candidates:
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, observation_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        )
        assessment = interpretation.assessment if interpretation else None
        if (
            evidence is None
            or observation is None
            or interpretation is None
            or not assessment
            or evidence.observation_id != observation.id
            or observation.content_hash != interpretation.content_hash
            or evidence.content_hash != assessment.get("evidence_hash")
            or observation.content_hash != assessment.get("semantic_hash")
            or assessment.get("project_identity_key") != project.identity_key
            or not _assessment_evidence_id_matches(assessment, evidence)
            or not (
                interpretation.status == "accepted"
                or (
                    interpretation.status in {"failed", "pending"}
                    and assessment.get("decision") == "accepted"
                )
            )
        ):
            continue
        asset_type = classify_project_asset(
            observation.source_id, evidence.title, evidence.abstract
        )
        if asset_type:
            asset_types.add(asset_type)
    return asset_types


def refresh_project_asset_type(
    session: Session, project: Project, *, events: Sequence[LifecycleEvent] | None = None
) -> tuple[str, str]:
    """Recompute a TDLR-origin project's industry from current accepted evidence.

    Safe for bounded existing-record correction: it changes no lifecycle, need,
    qualification, date, MW, or workflow fields and performs no writes itself.
    Other sources retain their established lifecycle classification path.
    Callers can inspect the returned before/after values and commit or roll back.
    """
    if project.source_id != TDLR_TABS_SOURCE:
        return project.asset_type, project.asset_type
    current_events = events
    if current_events is None:
        current_events = session.scalars(
            select(LifecycleEvent).where(LifecycleEvent.project_id == project.id)
        ).all()
    asset_types = _current_project_asset_types(session, project)
    for event in current_events:
        evidence = session.get(Evidence, event.evidence_id)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == event.observation_id)
        )
        candidate = copy(project)
        candidate.asset_type = "unknown"
        if (
            not lifecycle_event_supported(
                event.event_type, evidence, interpretation, candidate, event.state, event=event
            )
            or evidence is None
        ):
            continue
        observation = session.get(Observation, event.observation_id)
        if observation is None:
            continue
        classification = classify_event(
            "Drilling permit"
            if observation.source_id == "texas-rrc-drilling-permits"
            else evidence.title,
            None if observation.source_id == "texas-rrc-drilling-permits" else evidence.abstract,
            project_name=project.name,
            project_identity_key=project.identity_key,
            project_asset_type="unknown",
            reported_permit_event=reported_permit_event_type(
                observation.source_id,
                evidence.title,
                evidence.abstract,
                evidence.event_date,
                evidence.event_date_label,
            ),
            require_achieved_milestone=requires_achieved_lifecycle_milestone(observation.source_id),
        )
        if classification is not None and classification.event_type == event.event_type:
            asset_types.add(classification.asset_type.value)
    before = project.asset_type
    project.asset_type = next(iter(asset_types)) if len(asset_types) == 1 else "unknown"
    return before, project.asset_type


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
    if project.source_id == TDLR_TABS_SOURCE:
        refresh_project_asset_type(session, project, events=events)
    accepted_events = []
    for event in events:
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == event.observation_id)
        )
        evidence = session.get(Evidence, event.evidence_id)
        if lifecycle_event_supported(
            event.event_type, evidence, interpretation, project, event.state, event=event
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
        if project.source_id != TDLR_TABS_SOURCE:
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
    if project.asset_type == AssetType.UNKNOWN.value:
        if projection is not None:
            session.delete(projection)
        return
    current.sort(
        key=lambda item: (
            lifecycle_rank(AssetType(project.asset_type), item.state),
            item.occurred_on or item.recorded_at.date(),
        )
    )
    event = current[-1]
    evidence = session.get(Evidence, event.evidence_id)
    assert evidence is not None
    source_observation = session.get(Observation, evidence.observation_id)
    is_rrc = bool(
        source_observation and source_observation.source_id == "texas-rrc-drilling-permits"
    )
    classification = classify_event(
        "Drilling permit" if is_rrc else evidence.title,
        None if is_rrc else evidence.abstract,
        project_name=project.name,
        project_identity_key=project.identity_key,
        project_asset_type=project.asset_type,
        reported_permit_event=reported_permit_event_type(
            source_observation.source_id,
            evidence.title,
            evidence.abstract,
            evidence.event_date,
            evidence.event_date_label,
        )
        if source_observation
        else None,
        require_achieved_milestone=bool(
            source_observation
            and requires_achieved_lifecycle_milestone(source_observation.source_id)
        ),
    )
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
        and not is_rrc
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
