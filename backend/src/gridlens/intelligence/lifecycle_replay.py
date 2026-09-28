"""Idempotently attach version-bound accepted evidence to lifecycle history."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.lifecycle_service import apply_lifecycle_observation
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)


def replay_accepted_lifecycle(session: Session) -> dict[str, int]:
    counts = {"accepted": 0, "events_added": 0, "unbound": 0, "unresolved_project": 0}
    rows = session.execute(
        select(Interpretation, Observation)
        .join(Observation, Interpretation.observation_id == Observation.id)
        .where(Interpretation.status == "accepted")
        .order_by(Observation.first_seen_at, Observation.id)
    ).all()
    for interpretation, observation in rows:
        counts["accepted"] += 1
        assessment = interpretation.assessment or {}
        evidence_hash = assessment.get("evidence_hash")
        if not isinstance(evidence_hash, str):
            counts["unbound"] += 1
            continue
        evidence = session.scalar(
            select(Evidence).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == evidence_hash,
            )
        )
        if evidence is None:
            counts["unbound"] += 1
            continue
        identity_key = assessment.get("project_identity_key")
        project = (
            session.scalar(select(Project).where(Project.identity_key == identity_key))
            if isinstance(identity_key, str)
            else None
        )
        if project is None:
            projects = session.scalars(
                select(Project)
                .join(PowerNeed, PowerNeed.project_id == Project.id)
                .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                .where(NeedObservation.observation_id == observation.id)
                .distinct()
            ).all()
            if len(projects) == 1:
                project = projects[0]
        if project is None:
            project = session.scalar(
                select(Project).where(
                    Project.identity_key == f"{observation.source_id}:{observation.external_id}"
                )
            )
        if project is None:
            counts["unresolved_project"] += 1
            continue
        counts["events_added"] += int(
            apply_lifecycle_observation(session, project, observation, evidence)
        )
    session.flush()
    return counts
