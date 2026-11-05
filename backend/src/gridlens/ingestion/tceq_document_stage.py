"""Database glue for the TCEQ application-document stage.

The stage itself (``adapters/tceq_application_documents.py``) never touches the database. This
module reads the retained prior state for change detection, keeps the stage's transient retry
bookkeeping in source health (so it never changes evidence hashes), and turns a stage report
into the counts the job records.

Deliberate health choice: real stage failures make the job ``partial`` and are listed in
``rejected_records`` with ``parse_failures``, but ``collection_status`` is not set. That status
drives the source's rate-limit cooldown and retry scheduling, which belong to the listing and
must not be moved by an optional document stage. Notices (``zero_verified_rows``,
``listing_shrink``) are results, not failures: they are listed under
``application_document_notices`` and never set ``partial`` or ``parse_failures``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.tceq_application_documents import MAX_BOOKKEEPING, StageReport
from gridlens.persistence.models import Evidence, Observation, Source

STATE_KEY = "application_document"
HEALTH_KEY = "application_documents_attempts"
NOT_BEFORE_KEY = "application_documents_not_before"
DEFAULT_RATE_LIMIT_REST_SECONDS = 3600  # when a 429/503 carries no usable Retry-After


def load_prior_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Latest retained document state per TCEQ project, from the newest evidence that has one."""
    rows = session.execute(
        select(Observation.external_id, Evidence.provenance)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(Observation.source_id == source_id, Evidence.provenance.op("?")(STATE_KEY))
        .distinct(Observation.external_id)
        .order_by(Observation.external_id, Evidence.observed_at.desc(), Evidence.id)
    ).all()
    states: dict[str, dict[str, Any]] = {}
    for external_id, provenance in rows:
        state = provenance.get(STATE_KEY) if isinstance(provenance, dict) else None
        project = external_id.removeprefix("TCEQ-")
        if isinstance(state, dict) and project.isdigit():
            states[project] = state
    return states


def load_bookkeeping(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    source = session.get(Source, source_id)
    stored = (source.health or {}).get(HEALTH_KEY) if source is not None else None
    if not isinstance(stored, dict):
        return {}
    return {
        str(project): dict(entry)
        for project, entry in list(stored.items())[:MAX_BOOKKEEPING]
        if isinstance(entry, dict)
    }


def save_bookkeeping(session: Session, source_id: str, book: dict[str, dict[str, Any]]) -> None:
    source = session.get(Source, source_id)
    if source is not None:
        source.health = {**(source.health or {}), HEALTH_KEY: book}


def load_not_before(session: Session, source_id: str) -> datetime | None:
    """When the publisher last asked us to wait until, if that time is still stored."""
    source = session.get(Source, source_id)
    raw = (source.health or {}).get(NOT_BEFORE_KEY) if source is not None else None
    try:
        value = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def save_not_before(session: Session, source_id: str, value: datetime | None) -> None:
    source = session.get(Source, source_id)
    if source is None:
        return
    health = {k: v for k, v in (source.health or {}).items() if k != NOT_BEFORE_KEY}
    if value is not None:
        health[NOT_BEFORE_KEY] = value.isoformat()
    if health != (source.health or {}):
        source.health = health


def rest_until(report: StageReport, now: datetime) -> datetime | None:
    """The time before which the next run must not call the publisher, after a 429/503."""
    if not report.counts.get("aborted_rate_limited"):
        return None
    seconds = report.retry_after_seconds or DEFAULT_RATE_LIMIT_REST_SECONDS
    return now + timedelta(seconds=seconds)


def merge_report(counts: dict[str, Any], report: StageReport) -> None:
    """Record the stage in the job counts. Failures make the run partial, never silent."""
    summary: dict[str, Any] = {**report.counts, "known_failed": len(report.known_failed)}
    if report.retry_after_seconds is not None:
        summary["retry_after_seconds"] = report.retry_after_seconds
    counts["application_documents"] = summary
    if report.notices:
        counts["application_document_notices"] = report.notices[:50]
    failures = len(report.rejections)
    if failures:
        counts["partial"] = True
        counts["parse_failures"] = int(counts.get("parse_failures", 0)) + failures
        counts["attempt_rejected"] = int(counts.get("attempt_rejected", 0)) + failures
        counts["rejected_records"] = [*counts.get("rejected_records", []), *report.rejections][:50]
