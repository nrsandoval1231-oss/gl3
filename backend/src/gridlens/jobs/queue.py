from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from gridlens.persistence.models import Job, Source


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


def lease_one(
    session: Session,
    worker_id: str,
    lease_seconds: int = 90,
    *,
    job_ids: list[UUID] | None = None,
) -> tuple[Job, int] | None:
    now = datetime.now(UTC)
    scope = [] if job_ids is None else [Job.id.in_(job_ids)]
    abandoned = session.scalars(
        select(Job)
        .where(Job.status == "running", Job.lease_until < now, Job.attempts >= 5, *scope)
        .with_for_update(skip_locked=True)
    ).all()
    for expired in abandoned:
        expired.status, expired.error, expired.lease_owner, expired.lease_until = (
            "failed",
            "Lease expired after maximum attempts",
            None,
            None,
        )
        source = session.get(Source, expired.source_id)
        if source:
            source.health = {
                **source.health,
                "status": "Failed",
                "error": "Lease expired after maximum attempts",
            }
    job = session.scalar(
        select(Job)
        .where(
            *scope,
            Job.attempts < 5,
            Job.available_at <= now,
            ((Job.status == "queued") | ((Job.status == "running") & (Job.lease_until < now))),
        )
        # Permit jobs lead recent work, while a one-day age bucket guarantees
        # old news jobs advance even during sustained permit refresh activity.
        .order_by(
            case(
                (Job.created_at < now - timedelta(days=1), 0),
                (Source.family == "construction-permits", 1),
                else_=2,
            ).asc(),
            Job.created_at,
        )
        .join(Source, Source.id == Job.source_id)
        .with_for_update(skip_locked=True)
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
