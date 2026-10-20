"""Retained, accepted evidence boundary for advisory large-load request state."""

from copy import deepcopy
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.large_load_interconnection import VERSION, interconnection_state
from gridlens.persistence.models import (
    Evidence,
    InterconnectionFactVersion,
    Interpretation,
    Observation,
    Project,
    Source,
)


def _current(
    project: Project, observation: Observation, evidence: Evidence, interpretation: Interpretation
) -> bool:
    assessment = interpretation.assessment or {}
    return (
        interpretation.status == "accepted"
        and observation.id == evidence.observation_id == interpretation.observation_id
        and observation.content_hash == interpretation.content_hash
        and assessment.get("semantic_hash") == observation.content_hash
        and assessment.get("evidence_hash") == evidence.content_hash
        and assessment.get("project_identity_key") == project.identity_key
    )


def _record(evidence: Evidence, source: Source, payload: dict) -> dict:
    return {
        "request_id": payload.get("request_id"),
        "facts": payload.get("facts", []),
        "text": evidence.abstract or "",
        "evidence": {
            "id": str(evidence.id),
            "hash": evidence.content_hash,
            "url": evidence.url,
            "source_id": source.id,
            "publisher": source.publisher,
            "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
            "retrieved_at": evidence.observed_at.isoformat(),
            "event_date": evidence.event_date.isoformat() if evidence.event_date else None,
            "extraction_location": evidence.extraction_location,
        },
    }


def attach_interconnection_facts(
    session: Session,
    project_id: UUID,
    evidence_id: UUID,
    *,
    request_id: str,
    facts: list[dict],
    today: date,
) -> None:
    """Attach reviewed source facts to existing accepted evidence, never admit a project.

    Caller owns the transaction. Replaying the same payload is a no-op; changing
    an accepted payload at the same evidence version is refused. Corrections must
    enter through normal evidence/version admission to preserve accepted history.
    """
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    evidence = session.get(Evidence, evidence_id)
    if project is None or evidence is None:
        raise ValueError("Project or retained evidence unavailable")
    observation = session.get(Observation, evidence.observation_id)
    interpretation = session.scalar(
        select(Interpretation)
        .where(Interpretation.observation_id == evidence.observation_id)
        .with_for_update()
    )
    if (
        observation is None
        or interpretation is None
        or not _current(project, observation, evidence, interpretation)
    ):
        raise ValueError("Current accepted project-bound evidence required")
    source = session.get(Source, observation.source_id)
    if source is None:
        raise ValueError("Source provenance unavailable")
    payload = {
        "version": VERSION,
        "project_identity_key": project.identity_key,
        "evidence_id": str(evidence.id),
        "evidence_hash": evidence.content_hash,
        "request_id": request_id,
        "facts": deepcopy(facts),
    }
    view = interconnection_state([_record(evidence, source, payload)], today=today)
    if not facts or not view["requests"] or view["requests"][0]["limitations"]:
        raise ValueError("Dated, quoted, typed source facts required")
    previous = session.scalar(
        select(InterconnectionFactVersion).where(
            InterconnectionFactVersion.project_id == project.id,
            InterconnectionFactVersion.evidence_id == evidence.id,
        )
    )
    if previous is not None:
        if previous.payload != payload:
            raise ValueError("Retained interconnection facts cannot be overwritten")
        return
    session.add(
        InterconnectionFactVersion(project_id=project.id, evidence_id=evidence.id, payload=payload)
    )
    session.flush()


def current_interconnection_state(session: Session, project_id: UUID, *, today: date) -> dict:
    """Current request facts; old/rejected/mismatched evidence remains historical."""
    project = session.get(Project, project_id)
    if project is None:
        return interconnection_state([], today=today)
    query = (
        select(Observation, Evidence, Interpretation, Source, InterconnectionFactVersion)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .join(InterconnectionFactVersion, InterconnectionFactVersion.evidence_id == Evidence.id)
        .where(InterconnectionFactVersion.project_id == project.id)
        .order_by(Evidence.observed_at, Evidence.id)
    )
    records = []
    for observation, evidence, interpretation, source, version in session.execute(query):
        payload = version.payload
        if not isinstance(payload, dict) or not _current(
            project, observation, evidence, interpretation
        ):
            continue
        if not (
            payload.get("version") == VERSION
            and payload.get("project_identity_key") == project.identity_key
            and payload.get("evidence_id") == str(evidence.id)
            and payload.get("evidence_hash") == evidence.content_hash
        ):
            continue
        records.append(_record(evidence, source, payload))
    return interconnection_state(records, today=today)
