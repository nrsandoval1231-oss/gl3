from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectRole,
    ResearchJob,
    Source,
)


def enqueue(session: Session, source_id: str) -> UUID:
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None or not source.enabled:
        raise ValueError("Source is missing or disabled")
    active = session.scalar(
        select(Job.id)
        .where(Job.source_id == source_id, Job.status.in_(["queued", "running"]))
        .limit(1)
    )
    if active:
        return active
    job = Job(source_id=source_id)
    session.add(job)
    session.flush()
    return job.id


def owner_research_ineligibility(session: Session, need_id: UUID) -> str | None:
    """Return a specific reason when this Signal cannot enter the bounded planner."""
    need = session.get(PowerNeed, need_id)
    if need is None or not need.active or need.tier != "Signal":
        return "Research requires an active Signal need"
    project = session.get(Project, need.project_id)
    if project is None:
        return "Signal project is missing"
    identity_facts = project.identity_facts or {}
    if any(
        identity_facts.get(key) for key in ("owner", "developer", "owner_name", "developer_name")
    ):
        return "Owner/developer relationship is already present in project facts"
    known = session.scalar(
        select(ProjectRole.id)
        .where(
            ProjectRole.project_id == project.id,
            ProjectRole.role.in_(["Owner", "Developer"]),
        )
        .limit(1)
    )
    if known:
        return "Owner/developer relationship is already known"
    identity_evidence = session.scalar(
        select(Evidence.id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            NeedObservation.need_id == need.id,
            Observation.source_id == "taylor-development-newsflash",
            Observation.external_id == "2032",
            Interpretation.status == "accepted",
            Interpretation.assessment["decision"].as_string() == "accepted",
            Interpretation.assessment["semantic_hash"].as_string() == Observation.content_hash,
            Interpretation.assessment["evidence_hash"].as_string() == Evidence.content_hash,
            Evidence.abstract.ilike("%data center%1051 CR 401%"),
        )
        .limit(1)
    )
    if project.name.casefold().find("comal") < 0 or identity_evidence is None:
        return "No accepted identity-linked official Project Comal article 2032 evidence"
    return None


def enqueue_owner_research(session: Session, need_id: UUID) -> UUID:
    """Queue the one supported missing-fact question for an eligible Signal."""
    reason = owner_research_ineligibility(session, need_id)
    if reason is not None:
        raise ValueError(reason)
    need = session.get(PowerNeed, need_id, with_for_update=True)
    assert need is not None
    existing = session.scalar(
        select(ResearchJob)
        .where(
            ResearchJob.need_id == need.id,
            ResearchJob.target_fact == "developer",
        )
        .with_for_update()
    )
    if existing:
        existing_job = session.get(Job, existing.job_id, with_for_update=True)
        if (
            existing.status == "unresolved"
            and existing_job is not None
            and existing_job.status in {"succeeded", "failed"}
        ):
            if existing_job.attempts >= 5:
                raise ValueError("Research retry limit reached; preserve the unresolved result")
            existing.history = [
                *existing.history,
                {
                    "status": existing.status,
                    "result": existing.result,
                    "unresolved_reason": existing.unresolved_reason,
                    "completed_at": (
                        existing.completed_at.isoformat() if existing.completed_at else None
                    ),
                },
            ]
            existing.status = "queued"
            existing.result = {}
            existing.unresolved_reason = None
            existing.started_at = None
            existing.completed_at = None
            existing_job.status = "queued"
            existing_job.error = None
            existing_job.available_at = datetime.now(UTC)
        return existing.job_id

    job = Job(kind="research", source_id=None)
    session.add(job)
    session.flush()
    session.add(
        ResearchJob(
            job_id=job.id,
            need_id=need.id,
            target_fact="developer",
            question=(
                "Which organization is the documented developer of Project Comal at 1051 CR 401?"
            ),
            source_url="https://taylortx.gov/1383/KDC-Project-Comal",
            max_sources=1,
            max_requests=1,
            max_seconds=20,
            max_spend_cents=0,
            status="queued",
            next_action=(
                "Research the official City of Taylor project page; keep the "
                "developer UNKNOWN if it does not support the relationship."
            ),
        )
    )
    return job.id


def enqueue_owner_research_if_eligible(session: Session, need_id: UUID) -> UUID | None:
    """Queue a newly accepted eligible Signal; unsupported Signals remain unqueued."""
    if owner_research_ineligibility(session, need_id) is not None:
        return None
    existing_id = session.scalar(
        select(ResearchJob.job_id).where(
            ResearchJob.need_id == need_id,
            ResearchJob.target_fact == "developer",
        )
    )
    if existing_id is not None:
        return existing_id
    return enqueue_owner_research(session, need_id)


def lease_one(session: Session, worker_id: str, lease_seconds: int = 90) -> tuple[Job, int] | None:
    now = datetime.now(UTC)
    abandoned = session.scalars(
        select(Job)
        .where(Job.status == "running", Job.lease_until < now, Job.attempts >= 5)
        .with_for_update(of=Job, skip_locked=True)
    ).all()
    for expired in abandoned:
        expired.status, expired.error, expired.lease_owner, expired.lease_until = (
            "failed",
            "Lease expired after maximum attempts",
            None,
            None,
        )
        source = session.get(Source, expired.source_id) if expired.source_id else None
        if source:
            source.health = {
                **source.health,
                "status": "Failed",
                "error": "Lease expired after maximum attempts",
            }
        elif expired.kind == "research":
            research = session.get(ResearchJob, expired.id)
            if research:
                research.status = "unresolved"
                research.unresolved_reason = "Research worker lease expired after maximum attempts"
                research.next_action = (
                    "Review the saved research job and retry after checking the worker failure."
                )
                research.completed_at = now
    job = session.scalar(
        select(Job)
        .where(
            Job.attempts < 5,
            Job.available_at <= now,
            ((Job.status == "queued") | ((Job.status == "running") & (Job.lease_until < now))),
        )
        # Permit jobs lead recent work, while a one-day age bucket guarantees
        # old news jobs advance even during sustained permit refresh activity.
        .order_by(
            case(
                (Job.created_at < now - timedelta(days=1), 0),
                (Job.kind == "research", 3),
                (Source.family == "construction-permits", 1),
                else_=2,
            ).asc(),
            Job.created_at,
        )
        .outerjoin(Source, Source.id == Job.source_id)
        .with_for_update(of=Job, skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    job.lease_owner = worker_id
    job.fence += 1
    job.attempts += 1
    job.lease_until = now + timedelta(seconds=lease_seconds)
    session.flush()
    return job, job.fence


def assert_fence(session: Session, job_id: UUID, worker_id: str, fence: int) -> Job:
    job = session.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or job.status != "running"
        or job.lease_owner != worker_id
        or job.fence != fence
        or job.lease_until is None
        or job.lease_until <= datetime.now(UTC)
    ):
        raise RuntimeError("Worker lease fence lost")
    return job
