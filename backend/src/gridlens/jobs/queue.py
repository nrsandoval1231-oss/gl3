from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, Integer, and_, case, cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from gridlens.domain.pursuit_research import ACTIVE
from gridlens.persistence.models import Job, PursuitResearchQuestion, Source
from gridlens.settings import settings


def enqueue(session: Session, source_id: str, *, kind: str = "ingestion") -> UUID:
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None or not source.enabled or not source.registry_enabled:
        raise ValueError("Source is missing or disabled")
    active = session.scalar(
        select(Job.id)
        .where(Job.source_id == source_id, Job.kind == kind, Job.status.in_(["queued", "running"]))
        .limit(1)
    )
    if active:
        return active
    available_at = datetime.now(UTC)
    if kind == "ingestion":
        health = source.health if isinstance(source.health, dict) else {}
        hold_until = _source_retry_hold_until(health)
        if hold_until is not None:
            available_at = max(available_at, hold_until)
    job = Job(source_id=source_id, kind=kind, available_at=available_at)
    session.add(job)
    session.flush()
    return job.id


def _source_retry_hold_until(health: dict) -> datetime | None:
    retry_state = health.get("retry_state")
    if retry_state == "operator_review":
        return datetime.max.replace(tzinfo=UTC)
    raw_retry_at = health.get("retry_at")
    if retry_state == "scheduled" and not isinstance(raw_retry_at, str):
        return datetime.max.replace(tzinfo=UTC)
    if not isinstance(raw_retry_at, str):
        return None
    try:
        retry_at = datetime.fromisoformat(raw_retry_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    if retry_at.tzinfo is None:
        return datetime.max.replace(tzinfo=UTC)
    return retry_at.astimezone(UTC)


def lease_one(
    session: Session,
    worker_id: str,
    lease_seconds: int = 90,
    *,
    job_ids: list[UUID] | None = None,
) -> tuple[Job, int] | None:
    now = datetime.now(UTC)
    scope = [] if job_ids is None else [Job.id.in_(job_ids)]
    retry_state = Source.health["retry_state"].as_string()
    retry_at = Source.health["retry_at"].as_string()
    valid_retry_timestamp = func.pg_input_is_valid(retry_at, literal("timestamptz"))
    retry_deadline = case(
        (valid_retry_timestamp, cast(retry_at, DateTime(timezone=True))),
        else_=None,
    )
    retry_window_clear = retry_state.is_distinct_from("operator_review") & (
        retry_state.is_distinct_from("scheduled")
        | and_(
            retry_at.is_not(None),
            valid_retry_timestamp,
            retry_deadline <= now,
        )
    )
    abandoned = session.scalars(
        select(Job)
        .join(Source, Source.id == Job.source_id)
        .where(
            Job.status == "running",
            Job.lease_until < now,
            Job.attempts >= 5,
            *scope,
            (
                (Job.kind != "ingestion")
                | (Source.enabled.is_(True) & Source.registry_enabled.is_(True))
            ),
            (Job.kind != "ingestion") | retry_window_clear,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for expired in abandoned:
        expired.status, expired.error, expired.lease_owner, expired.lease_until = (
            "failed",
            "Lease expired after maximum attempts",
            None,
            None,
        )
        if expired.kind == "pursuit_question" and expired.target_id:
            question = session.scalar(
                select(PursuitResearchQuestion)
                .where(PursuitResearchQuestion.id == expired.target_id)
                .with_for_update()
            )
            if question and question.status in ACTIVE:
                # The job lock fences the expired worker before its question is
                # terminalized in this same transaction. Preserve partial work.
                question.status = "FAILED"
                question.completed_at = now
                question.retry_after = now + timedelta(hours=24)
                question.receipt = {
                    **question.receipt,
                    "error": "lease_expired_after_maximum_attempts",
                    "result_disposition": "FAILED",
                    "reevaluation_status": "NOT_COMPLETED",
                    "retry_class": "UNKNOWN_EFFECT"
                    if question.receipt.get("inflight_url")
                    or question.receipt.get("ambiguous_effects")
                    else "RETRIES_EXHAUSTED",
                }
        source = session.get(Source, expired.source_id)
        if source and expired.kind == "ingestion":
            source.health = {
                **source.health,
                "status": "Failed",
                "error": "Lease expired after maximum attempts",
            }
    order_by = [
        case(
            (Job.created_at < now - timedelta(days=1), 0),
            (Source.family == "construction-permits", 1),
            else_=2,
        ).asc()
    ]
    routing_caps_enabled = (
        settings.intelligence_max_active_calls > 0
        and settings.intelligence_max_call_usd > 0
        and all(
            getattr(settings, f"intelligence_{scope}_{period}_calls") > 0
            and getattr(settings, f"intelligence_{scope}_{period}_usd") > 0
            for scope in ("global", "provider", "model", "source", "project")
            for period in ("daily", "monthly")
        )
    )
    if (
        settings.intelligence_mode == "bounded_routing"
        and settings.intelligence_enabled
        and settings.intelligence_research_enabled
        and (settings.intelligence_openai_enabled or settings.intelligence_typesafe_enabled)
        and settings.intelligence_routing_policy_id
        and settings.intelligence_routing_policy_evaluated
        and settings.intelligence_bounded_routing_authorized
        and routing_caps_enabled
    ):
        checkpoint_json = case(
            (
                func.pg_input_is_valid(Job.checkpoint, "jsonb"),
                cast(Job.checkpoint, JSONB),
            ),
            else_=literal("{}").cast(JSONB),
        )
        route = checkpoint_json["routing_priority"]
        raw_rank = route["rank"].as_string()
        safe_rank = case(
            (raw_rank.op("~")(literal("^[1-5]$")), cast(raw_rank, Integer)),
            else_=99,
        )
        order_by.append(
            case(
                (
                    and_(
                        Job.kind == "intelligence_process",
                        func.jsonb_typeof(route) == "object",
                        route["policy_id"].as_string() == settings.intelligence_routing_policy_id,
                        func.jsonb_typeof(route["evaluated"]) == "boolean",
                        route["evaluated"].as_string() == "true",
                        func.jsonb_typeof(route["authorized"]) == "boolean",
                        route["authorized"].as_string() == "true",
                        func.jsonb_typeof(route["rank"]) == "number",
                        safe_rank.between(1, 5),
                        func.jsonb_typeof(route["evaluation_job_id"]) == "string",
                        route["evaluation_job_id"].as_string().is_not(None),
                        func.jsonb_typeof(route["evaluation_call_id"]) == "string",
                        route["evaluation_call_id"].as_string().is_not(None),
                        func.jsonb_typeof(route["request_digest"]) == "string",
                        route["request_digest"].as_string().op("~")("^[0-9a-f]{64}$"),
                    ),
                    safe_rank,
                ),
                else_=99,
            ).asc()
        )
    order_by.append(Job.created_at.asc())
    job = session.scalar(
        select(Job)
        .where(
            *scope,
            Job.attempts < 5,
            Job.available_at <= now,
            ((Job.status == "queued") | ((Job.status == "running") & (Job.lease_until < now))),
            (
                (Job.kind != "ingestion")
                | (Source.enabled.is_(True) & Source.registry_enabled.is_(True))
            ),
            (Job.kind != "ingestion") | retry_window_clear,
        )
        # Permit jobs lead recent work, while a one-day age bucket guarantees
        # old news jobs advance even during sustained permit refresh activity.
        .order_by(*order_by)
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
