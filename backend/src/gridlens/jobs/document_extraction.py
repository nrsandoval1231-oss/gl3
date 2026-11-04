"""Leased ``document_extraction`` jobs: discovery in the listing job, extraction in its own job.

Off by default (``DOCUMENT_EXTRACTION_JOBS_ENABLED``). Then the TCEQ listing job only discovers
(HEAD plus validator comparison) and queues one extraction job per new or changed document; the
extraction job downloads that one PDF, runs the permit_docs pipeline in the isolated child with
the stage sub-deadline and persist reserve, and is the leased context in which the optional
model passes (``configured_proposer`` / ``configured_stage_ocr``, both off by default) are
passed to the pipeline. The finished state is kept in the job's checkpoint; the next listing
run folds it onto the NSR record, so evidence, hashes and the state contract are exactly the
in-line stage's.

Idempotency: ``target_id`` is a UUIDv5 over (source, project, url, validator digest), so one
document version has at most one live or finished job. A re-download that yields the same
content hash is recorded as unchanged and produces no new state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters import tceq_application_documents as tceq
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Job, Source
from gridlens.settings import settings

KIND = "document_extraction"
_NAMESPACE = UUID("6f1c2f0e-6c0b-4d2f-9a53-0d6f1a7e5b11")
PENDING_DAYS = 30
MAX_PENDING_ROWS = 500


class DocumentExtractionRetry(Exception):
    """A retryable document failure; the worker's generic backoff schedules the next attempt."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def validators_digest(validators: dict[str, Any] | None, today: str) -> str:
    """Digest of the publisher's validators; with none, one extraction per day at most."""
    material = _canonical(validators) if validators else f"novalidators:{today}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def document_job_key(source_id: str, project: str, url: str, digest: str) -> UUID:
    return uuid5(_NAMESPACE, f"{source_id}|{project}|{url}|{digest}")


def job_record(link: tceq.ApplicationLink) -> dict[str, Any]:
    """The smallest NSR listing row the stage needs to rediscover this one document."""
    return {
        "permit": {
            "project": link.project,
            "applicant": link.applicant,
            "facility": link.facility,
            "permit_numbers": list(link.permits),
            "document_links": {"application": link.url},
        },
        "event_date": link.received.isoformat(),
    }


def enqueue_document_extraction(
    session: Session,
    source_id: str,
    *,
    link: tceq.ApplicationLink,
    validators: dict[str, Any] | None,
    now: datetime | None = None,
    not_before: datetime | None = None,
) -> tuple[UUID, str]:
    """Queue the extraction of one document version. Returns (job id, 'created' | 'existing')."""
    now = now or datetime.now(UTC)
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None or not source.enabled or not source.registry_enabled:
        raise ValueError("Source is missing or disabled")
    digest = validators_digest(validators, now.date().isoformat())
    key = document_job_key(source_id, link.project, link.url, digest)
    existing = session.scalars(
        select(Job)
        .where(Job.kind == KIND, Job.source_id == source_id, Job.target_id == key)
        .order_by(Job.created_at.desc())
    ).all()
    rest = timedelta(hours=settings.document_extraction_failed_retry_hours)
    for job in existing:
        if job.status in {"queued", "running", "succeeded"}:
            return job.id, "existing"
        if job.created_at is not None and job.created_at > now - rest:
            return job.id, "existing"  # a failed version rests before it is tried again
    job = Job(
        source_id=source_id,
        kind=KIND,
        target_id=key,
        available_at=max(now, not_before) if not_before else now,
        checkpoint=_canonical(
            {
                "v": 1,
                "stage": "tceq",
                "project": link.project,
                "url": link.url,
                "validators_digest": digest,
                "enqueued_at": now.isoformat(),
                "record": job_record(link),
            }
        ),
    )
    session.add(job)
    session.flush()
    return job.id, "created"


def _state_time(state: dict[str, Any]) -> datetime | None:
    document = state.get("document")
    attempt = state.get("last_attempt")
    raw = (document.get("fetched_at") if isinstance(document, dict) else None) or (
        attempt.get("at") if isinstance(attempt, dict) else None
    )
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def load_pending_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Newest finished extraction state per project, from succeeded jobs (bounded)."""
    since = datetime.now(UTC) - timedelta(days=PENDING_DAYS)
    rows = session.scalars(
        select(Job.checkpoint)
        .where(
            Job.kind == KIND,
            Job.source_id == source_id,
            Job.status == "succeeded",
            Job.created_at >= since,
            Job.checkpoint.like('%"state":%'),
        )
        .order_by(Job.created_at.desc())
        .limit(MAX_PENDING_ROWS)
    ).all()
    states: dict[str, dict[str, Any]] = {}
    for raw in rows:
        try:
            body = json.loads(raw or "{}")
        except ValueError:
            continue
        project, state = body.get("project"), body.get("state")
        if isinstance(project, str) and isinstance(state, dict) and project not in states:
            states[project] = state
    return states


def merge_pending(
    prior: dict[str, dict[str, Any]], pending: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], int]:
    """Pending states that are strictly newer than the retained state replace it."""
    merged, taken = dict(prior), 0
    for project, state in pending.items():
        retained = merged.get(project)
        if retained is not None and tceq.state_digest(retained) == tceq.state_digest(state):
            continue
        new_time, old_time = _state_time(state), _state_time(retained or {})
        if retained is None or (new_time is not None and (old_time is None or new_time > old_time)):
            merged[project] = state
            taken += 1
    return merged, taken


def discovery_callback(
    session: Session, source_id: str, report: tceq.StageReport
) -> Callable[[tceq.ApplicationLink, dict[str, Any] | None], None]:
    """The ``on_changed`` callback for ``run_stage``: queue one job per changed document."""
    limit = settings.document_extraction_max_enqueue_per_run

    def callback(link: tceq.ApplicationLink, validators: dict[str, Any] | None) -> None:
        if report.counts.get("enqueued", 0) + report.counts.get("already_queued", 0) >= limit:
            report.bump("deferred_enqueue_budget")
            return
        _job_id, outcome = enqueue_document_extraction(
            session, source_id, link=link, validators=validators
        )
        report.bump("enqueued" if outcome == "created" else "already_queued")
        session.commit()  # release the source row lock before the next network call

    return callback


# --------------------------------------------------------------------------- the job


def _cap_fields(extraction: dict[str, Any]) -> dict[str, Any]:
    """Capped-out visibility from the proposer / OCR pass results, in the shared job shape."""
    for name in ("proposer", "ocr"):
        detail = extraction.get(name)
        if isinstance(detail, dict) and detail.get("status") == "capped_out":
            return {
                "capped_out": True,
                "cap_state": detail.get("cap_state", "CAPPED_OUT"),
                "cap_scope": detail.get("cap_scope"),
                "cap_period": detail.get("cap_period"),
                "cap_reason": detail.get("cap_reason"),
                "cap_pass": name,
            }
    return {}


def _finish(
    job_id: UUID,
    worker_id: str,
    fence: int,
    update: dict[str, Any],
    *,
    requeue_at: datetime | None = None,
) -> None:
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        body = json.loads(job.checkpoint or "{}")
        body.update(update)
        job.checkpoint = _canonical(body)
        job.lease_owner, job.lease_until, job.error = None, None, None
        if requeue_at is not None:
            # Deferred, not failed: the attempt is not spent waiting for a publisher.
            job.status, job.available_at = "queued", requeue_at
            job.attempts = max(0, job.attempts - 1)
        else:
            job.status = "succeeded"


def process_document_extraction_job(
    job_id: UUID, worker_id: str, fence: int, *, deadline: float | None = None
) -> None:
    """Extract one document version. Raises ``DocumentExtractionRetry`` to use worker backoff."""
    from gridlens.ingestion.document_health import build_run_summary, record_run
    from gridlens.ingestion.tceq_document_stage import (
        load_bookkeeping,
        load_not_before,
        load_prior_states,
        rest_until,
        save_bookkeeping,
        save_not_before,
    )

    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        body = json.loads(job.checkpoint or "{}")
        source_id = job.source_id
        source = session.get(Source, source_id)
        definition = _definition(source_id)
        config = tceq.config_from_source(definition) if definition else None
        project, record = str(body.get("project")), body.get("record")
        if (
            not settings.document_extraction_jobs_enabled
            or source is None
            or not source.enabled
            or not source.registry_enabled
            or config is None
            or not isinstance(record, dict)
        ):
            session.rollback()
            _finish(job_id, worker_id, fence, {"outcome": "disabled", "extracted": False})
            return
        not_before = load_not_before(session, source_id)
        if not_before is not None and datetime.now(UTC) < not_before:
            session.rollback()
            _finish(
                job_id,
                worker_id,
                fence,
                {"outcome": "deferred_retry_after", "extracted": False},
                requeue_at=not_before,
            )
            return
        prior = load_prior_states(session, source_id)
        prior, _ = merge_pending(prior, load_pending_states(session, source_id))
        book = load_bookkeeping(session, source_id)
        session.rollback()

    started = datetime.now(UTC)
    hooks = tceq.ExtractionHooks(
        proposer=lambda: _proposer(source_id, job_id, worker_id, fence),
        ocr=lambda path, url: _ocr(path, url, source_id, job_id, worker_id, fence),
    )
    # One document, one download; the stage keeps its own sub-deadline and persist reserve.
    one = tceq.StageConfig(
        max_downloads=1,
        max_checks=1,
        extract_seconds=config.extract_seconds,
        isolate=config.isolate,
    )
    report = tceq.run_stage(
        [record],
        prior,
        client=None,
        config=one,
        deadline=deadline,
        bookkeeping=book,
        hooks=hooks,
    )
    state = record.get("application_document")
    changed = isinstance(state, dict) and (
        prior.get(project) is None or tceq.state_digest(state) != tceq.state_digest(prior[project])
    )
    with SessionLocal.begin() as session:
        assert_fence(session, job_id, worker_id, fence)
        if report.bookkeeping != book:
            save_bookkeeping(session, source_id, report.bookkeeping)
        rest = rest_until(report, datetime.now(UTC))
        save_not_before(session, source_id, rest)
        fresh = [state] if changed and isinstance(state, dict) else []
        record_run(session, source_id, build_run_summary(KIND, report.counts, fresh, at=started))
    if rest is not None:
        _finish(
            job_id,
            worker_id,
            fence,
            {"outcome": "rate_limited", "extracted": False, "counts": report.counts},
            requeue_at=rest,
        )
        return
    retryable = [r for r in report.rejections if _retryable(r.get("error_code"))]
    if retryable and not changed:
        raise DocumentExtractionRetry(str(retryable[0].get("error_code"))[:60])
    update: dict[str, Any] = {
        "outcome": "extracted" if changed else "unchanged",
        "extracted": bool(changed),
        "counts": report.counts,
        "rejections": report.rejections[:5],
        "notices": report.notices[:5],
    }
    if changed and isinstance(state, dict):
        document = state.get("document") or {}
        update["state"] = state
        update["content_sha256"] = document.get("sha256")
        update.update(_cap_fields(document.get("extraction") or {}))
    _finish(job_id, worker_id, fence, update)
    if changed:
        _request_refresh(source_id)


def _retryable(code: Any) -> bool:
    return isinstance(code, str) and tceq.DocumentFailure(code).retryable


def _definition(source_id: str) -> dict[str, Any] | None:
    from gridlens.ingestion.registry import load_registry

    return next((item for item in load_registry() if item["id"] == source_id), None)


def _proposer(source_id: str, job_id: UUID, worker_id: str, fence: int) -> Any:
    from gridlens.intelligence.equipment_proposer import configured_proposer

    return configured_proposer(
        source_id=source_id, job_id=job_id, worker_id=worker_id, fence_token=fence
    )


def _ocr(path: str, url: str, source_id: str, job_id: UUID, worker_id: str, fence: int) -> Any:
    from gridlens.intelligence.permit_page_ocr import configured_stage_ocr

    return configured_stage_ocr(
        pdf_path=path,
        source_url=url,
        source_id=source_id,
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence,
    )


def _request_refresh(source_id: str) -> None:
    """Queue (or reuse) the listing job that folds the finished state into evidence."""
    from gridlens.jobs.queue import enqueue

    try:
        with SessionLocal.begin() as session:
            enqueue(session, source_id)
    except ValueError:
        pass  # source disabled meanwhile: the state stays pending, nothing is lost
