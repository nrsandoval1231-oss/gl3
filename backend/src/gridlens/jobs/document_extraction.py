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

from sqlalchemy import case, cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters import tceq_application_documents as tceq
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Evidence, Job, Observation, Source
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
    allow_create: bool = True,
) -> tuple[UUID | None, str]:
    """Queue the extraction of one document version.

    Returns (job id, 'created' | 'existing'). With ``allow_create`` false a version that has
    no job yet is not queued and the result is (None, 'deferred').
    """
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
    if any(job.status in {"queued", "running"} for job in existing):
        return next(j.id for j in existing if j.status in {"queued", "running"}), "existing"
    if existing and _blocks_requeue(existing[0], now):
        return existing[0].id, "existing"
    if not allow_create:
        return None, "deferred"
    job = Job(
        source_id=source_id,
        kind=KIND,
        target_id=key,
        available_at=max(now, not_before) if not_before else now,
        checkpoint=_canonical(
            {
                "v": 1,
                "stage": "tceq",
                "permit_document_stage_enabled": True,
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


def _blocks_requeue(job: Job, now: datetime) -> bool:
    """Whether the newest finished job for a version still stands in for a new one.

    A decided success (the stage settled the version: unchanged, known-failed or a new
    state) blocks for as long as its state can still be loaded (``PENDING_DAYS``). A failed
    job, or a success that decided nothing (backed off, deferred by the deadline, disabled),
    only rests: ``rest_hours`` after it ended, the version can be queued again.
    """
    try:
        body = json.loads(job.checkpoint or "{}")
    except ValueError:
        body = {}
    created = job.created_at or now
    if job.status == "succeeded" and body.get("decided", True):
        return created > now - timedelta(days=PENDING_DAYS)
    rest = timedelta(
        hours=float(body.get("rest_hours", settings.document_extraction_failed_retry_hours))
    )
    ended = _parse_time(body.get("finished_at")) or created
    return now < ended + rest


def _parse_time(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _checkpoint_json() -> Any:
    return case(
        (func.pg_input_is_valid(Job.checkpoint, "jsonb"), cast(Job.checkpoint, JSONB)),
        else_=literal("{}").cast(JSONB),
    )


def load_pending_states(
    session: Session, source_id: str
) -> dict[str, tuple[dict[str, Any], datetime]]:
    """Newest finished extraction state per project: (state, job end time). One row each."""
    since = datetime.now(UTC) - timedelta(days=PENDING_DAYS)
    body = _checkpoint_json()
    project = body["project"].as_string()
    rows = session.execute(
        select(project, body["state"], body["finished_at"].as_string(), Job.created_at)
        .where(
            Job.kind == KIND,
            Job.source_id == source_id,
            Job.status == "succeeded",
            Job.created_at >= since,
            body.op("?")("state"),
        )
        .distinct(project)
        .order_by(project, Job.created_at.desc())
    ).all()
    states: dict[str, tuple[dict[str, Any], datetime]] = {}
    for name, state, finished, created in rows:
        if isinstance(name, str) and isinstance(state, dict):
            states[name] = (state, _parse_time(finished) or created)
    return states


def load_evidence_times(session: Session, source_id: str) -> dict[str, datetime]:
    """When the newest evidence that carries a document state was recorded, per project."""
    rows = session.execute(
        select(Observation.external_id, Evidence.observed_at)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(
            Observation.source_id == source_id,
            Evidence.provenance.op("?")(tceq_stage_key()),
        )
        .distinct(Observation.external_id)
        .order_by(Observation.external_id, Evidence.observed_at.desc())
    ).all()
    return {external.removeprefix("TCEQ-"): observed for external, observed in rows}


def tceq_stage_key() -> str:
    from gridlens.ingestion.tceq_document_stage import STATE_KEY

    return STATE_KEY


def merge_pending(
    prior: dict[str, dict[str, Any]],
    pending: dict[str, tuple[dict[str, Any], datetime]],
    evidence_times: dict[str, datetime] | None = None,
) -> tuple[dict[str, dict[str, Any]], int]:
    """A finished job's state replaces the retained one when it ended after that evidence.

    Ordering is by completion, not by the state's own fetch time: an unchanged-bytes check
    with refreshed validators, or a failed attempt on an accepted document, carries the old
    fetch time but is still the newer decision. A state equal to the retained one is skipped.
    """
    merged, taken = dict(prior), 0
    times = evidence_times or {}
    for project, (state, ended) in pending.items():
        retained = merged.get(project)
        if retained is not None and tceq.state_digest(retained) == tceq.state_digest(state):
            continue
        seen = times.get(project)
        if retained is None or seen is None or ended > seen:
            merged[project] = state
            taken += 1
    return merged, taken


def discovery_callback(
    session: Session, source_id: str, report: tceq.StageReport, *, limit: int
) -> Callable[[tceq.ApplicationLink, dict[str, Any] | None], None]:
    """The ``on_changed`` callback for ``run_stage``: queue one job per changed document.

    ``limit`` bounds the jobs this run creates; versions that already have a job do not
    spend it.
    """

    def callback(link: tceq.ApplicationLink, validators: dict[str, Any] | None) -> None:
        _job_id, outcome = enqueue_document_extraction(
            session,
            source_id,
            link=link,
            validators=validators,
            allow_create=report.counts.get("enqueued", 0) < limit,
        )
        report.bump(
            {
                "created": "enqueued",
                "existing": "already_queued",
                "deferred": "deferred_enqueue_budget",
            }[outcome]
        )
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
        body["finished_at"] = datetime.now(UTC).isoformat()
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
            or body.get("permit_document_stage_enabled") is not True
            or not isinstance(record, dict)
        ):
            session.rollback()
            _finish(job_id, worker_id, fence, _undecided("disabled"))
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
        prior, _ = merge_pending(
            prior,
            load_pending_states(session, source_id),
            load_evidence_times(session, source_id),
        )
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
        check_shrink=False,  # one record is not a listing
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
        from gridlens.ingestion.service import _fetched_since

        fresh = (
            [state]
            if changed and isinstance(state, dict) and _fetched_since(state, started)
            else []
        )
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
    counts = report.counts
    decided = bool(changed) or any(
        counts.get(key) for key in ("unchanged", "unchanged_by_hash", "known_failed")
    )
    if not decided:
        # Nothing was settled (backed off, deferred by the deadline, ...): not a result.
        reason = next(
            (
                key
                for key in ("backed_off", "deferred_deadline", "deferred_check_budget")
                if counts.get(key)
            ),
            "no_decision",
        )
        _finish(
            job_id,
            worker_id,
            fence,
            {
                **_undecided(reason),
                "counts": counts,
                "rejections": report.rejections[:5],
            },
        )
        return
    update: dict[str, Any] = {
        "outcome": "extracted" if changed else "unchanged",
        "decided": True,
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
        _request_refresh(source_id, job_id)


def _undecided(reason: str) -> dict[str, Any]:
    """A finished job that settled nothing: the version may be queued again after a rest."""
    rest = tceq.RETRY_BACKOFF_DAYS * 24 if reason == "backed_off" else None
    out: dict[str, Any] = {
        "outcome": f"undecided_{reason}",
        "decided": False,
        "extracted": False,
    }
    out["rest_hours"] = (
        rest if rest is not None else settings.document_extraction_failed_retry_hours
    )
    return out


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


def _request_refresh(source_id: str, job_id: UUID) -> None:
    """Queue (or reuse) the listing job that folds finished states into evidence.

    Coalesced: skipped while another extraction job for the source is still queued or
    running, because that job will request the refresh when it finishes.
    """
    from gridlens.jobs.queue import enqueue

    try:
        with SessionLocal.begin() as session:
            others = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.kind == KIND,
                    Job.source_id == source_id,
                    Job.id != job_id,
                    Job.status.in_(("queued", "running")),
                )
            )
            if not others:
                enqueue(session, source_id)
    except ValueError:
        pass  # source disabled meanwhile: the state stays pending, nothing is lost
