"""Small, explicit monitoring watch sets; discovery remains independently scheduled."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.buying_chain_public import validate_public_url
from gridlens.ingestion.adapters.pursuit_acquisition import (
    SUPPORTED_SOURCES,
    acquire_registered_record,
)
from gridlens.ingestion.registry import load_registry
from gridlens.intelligence.question_contracts import QUESTION_CONTRACTS, question_contract
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.persistence.watch_models import ProjectMonitorWatch, ProjectMonitorWatchSource

MAX_PLAN_BATCH = 100
MAX_ACTIVE_MONITOR_JOBS = 8
MAX_ACTIVE_MONITOR_JOBS_PER_HOST = 2
MAX_CONSECUTIVE_FAILURES = 5
MAX_DOCUMENTS = 5
MAX_DOCUMENT_BYTES = 750_000
MAX_RUNTIME_SECONDS = 180
RETRY_HOURS = (1, 6, 24)
MONITOR_INTERVAL_HOURS = 24
MONITORING_ENABLED = False
_REGISTRY_BY_ID: dict[str, dict[str, Any]] | None = None


def _policy_snapshot(source_id: str, definition: dict[str, Any]) -> dict[str, Any]:
    policy = {
        "source_id": source_id,
        "registry_definition": definition,
        "acquisition": "acquire_registered_record-v1",
        "retention": "retain_registered_record-allow_model_false-v1",
        "max_documents": MAX_DOCUMENTS,
        "max_document_bytes": MAX_DOCUMENT_BYTES,
        "question_contracts": QUESTION_CONTRACTS,
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), default=str)
    return {"digest": hashlib.sha256(encoded.encode()).hexdigest(), **policy}


def _registry_source(source_id: str) -> dict[str, Any]:
    global _REGISTRY_BY_ID
    if _REGISTRY_BY_ID is None:
        _REGISTRY_BY_ID = {item["id"]: item for item in load_registry()}
    definition = _REGISTRY_BY_ID.get(source_id)
    if source_id not in SUPPORTED_SOURCES or definition is None:
        raise ValueError("Monitoring source is not an existing reviewed retrieval source")
    return definition


def _checkpoint_version(checkpoint: str | None, marker: str, fallback: int) -> int:
    if checkpoint is None:
        return fallback
    try:
        return int(checkpoint.rsplit(marker, 1)[1].split(":", 1)[0])
    except (AttributeError, IndexError, ValueError):
        return fallback


def configure_watch(
    session: Session,
    need_id: UUID,
    *,
    sources: list[dict[str, Any]],
    question_ids: list[str] | None = None,
    enabled: bool = True,
    reprocess_revision: str | None = None,
) -> ProjectMonitorWatch:
    """Create/update one explicit need watch. URLs are operator-supplied exact targets."""
    if not sources or len(sources) > 12:
        raise ValueError("A watch requires 1 to 12 explicit sources")
    ids = question_ids if question_ids is not None else list(QUESTION_CONTRACTS)
    if not ids or len(ids) != len(set(ids)) or any(item not in QUESTION_CONTRACTS for item in ids):
        raise ValueError("Watch question IDs must be unique registered contracts")
    if reprocess_revision is not None and (
        not isinstance(reprocess_revision, str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", reprocess_revision)
    ):
        raise ValueError("Reprocess revision must be a short stable policy identifier")
    need = session.get(PowerNeed, need_id)
    if need is None:
        raise ValueError("Monitoring target need does not exist")
    if session.get(Project, need.project_id) is None:
        raise ValueError("Monitoring target project does not exist")

    normalized: dict[str, dict[str, Any]] = {}
    initial_refs: list[dict[str, Any]] = []
    for item in sources:
        source_id = str(item.get("source_id", ""))
        definition = _registry_source(source_id)
        source = session.get(Source, source_id)
        if source is None or not source.enabled or not source.registry_enabled:
            raise ValueError("Monitoring source is missing or disabled")
        if source.endpoint != definition["endpoint"]:
            raise ValueError("Monitoring source differs from its reviewed registry endpoint")
        urls = item.get("allowed_urls")
        if not isinstance(urls, list) or not urls or len(urls) > 20:
            raise ValueError("Each source requires 1 to 20 exact allowed URLs")
        checked = sorted({str(validate_public_url(url)) for url in urls})
        record_ids = item.get("record_ids", [])
        if (
            not isinstance(record_ids, list)
            or len(record_ids) > MAX_DOCUMENTS
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z0-9 /_.-]{1,100}", value)
                for value in record_ids
            )
            or len(record_ids) != len(set(record_ids))
        ):
            raise ValueError("Record IDs must be unique stable IDs within the document bound")
        for external_id in record_ids:
            retained = session.execute(
                select(Evidence.id, Evidence.content_hash)
                .select_from(Observation)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .join(Interpretation, Interpretation.observation_id == Observation.id)
                .join(Evidence, Evidence.observation_id == Observation.id)
                .where(
                    NeedObservation.need_id == need_id,
                    Observation.source_id == source_id,
                    Observation.external_id == external_id,
                    Observation.url.in_(checked),
                    Observation.content_hash == Evidence.content_hash,
                    Interpretation.status == "accepted",
                    Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
                )
                .limit(1)
            ).first()
            if retained is None:
                raise ValueError("Record ID is not accepted evidence linked to this need and URL")
            initial_refs.append(
                {
                    "source_id": source_id,
                    "external_id": external_id,
                    "evidence_id": str(retained.id),
                    "content_hash": retained.content_hash,
                }
            )
        normalized[source_id] = {
            "allowed_urls": checked,
            "record_ids": record_ids,
            "policy_snapshot": _policy_snapshot(source_id, definition),
        }
    if len(normalized) != len(sources):
        raise ValueError("A source may appear only once per watch")

    watch = session.scalar(
        select(ProjectMonitorWatch).where(ProjectMonitorWatch.need_id == need_id).with_for_update()
    )
    now = datetime.now(UTC)
    new_watch = watch is None
    effective_reprocess_revision = (
        reprocess_revision
        or (watch.reprocess_revision if watch is not None else "watch-policy-v1")
    )
    if watch is None:
        watch = ProjectMonitorWatch(
            need_id=need_id,
            version=1,
            enabled=enabled,
            question_ids=ids,
            reprocess_revision=effective_reprocess_revision,
            unresolved_questions=ids.copy(),
            last_good_evidence_refs=initial_refs,
            status="idle",
            updated_at=now,
        )
        session.add(watch)
        session.flush()
        existing: dict[str, ProjectMonitorWatchSource] = {}
    else:
        existing = {
            row.source_id: row
            for row in session.scalars(
                select(ProjectMonitorWatchSource)
                .where(ProjectMonitorWatchSource.watch_id == watch.id)
                .with_for_update()
            )
        }

    changed_sources = any(
        source_id not in existing
        or not existing[source_id].enabled
        or existing[source_id].allowed_urls != policy["allowed_urls"]
        or existing[source_id].record_ids != policy["record_ids"]
        or existing[source_id].policy_snapshot != policy["policy_snapshot"]
        for source_id, policy in normalized.items()
    ) or any(source_id not in normalized and row.enabled for source_id, row in existing.items())
    watch_changed = not new_watch and (
        watch.enabled != enabled
        or watch.question_ids != ids
        or changed_sources
        or watch.reprocess_revision != effective_reprocess_revision
    )
    if watch_changed:
        watch.revision_history = [
            *watch.revision_history,
            {
                "version": watch.version,
                "enabled": watch.enabled,
                "question_ids": watch.question_ids,
                "reprocess_revision": watch.reprocess_revision,
                "sources": [
                    {
                        "source_id": row.source_id,
                        "enabled": row.enabled,
                        "allowed_urls": row.allowed_urls,
                        "record_ids": row.record_ids,
                        "policy_snapshot": row.policy_snapshot,
                        "applied_version": row.applied_version,
                        "cursor": row.cursor,
                        "etag": row.etag,
                        "last_modified": row.last_modified,
                        "status": row.status,
                        "error_class": row.error_class,
                        "consecutive_failures": row.consecutive_failures,
                        "next_due_at": row.next_due_at.isoformat(),
                        "last_attempt_at": row.last_attempt_at.isoformat()
                        if row.last_attempt_at
                        else None,
                        "last_success_at": row.last_success_at.isoformat()
                        if row.last_success_at
                        else None,
                        "checkpoint": row.checkpoint,
                    }
                    for row in existing.values()
                ],
                "last_good_facts": watch.last_good_facts,
                "last_good_evidence_refs": watch.last_good_evidence_refs,
                "checkpoint": watch.checkpoint,
                "fresh_at": watch.fresh_at.isoformat() if watch.fresh_at else None,
                "recorded_at": now.isoformat(),
            },
        ]
        watch.version += 1
        watch.enabled = enabled
        watch.question_ids = ids
        watch.reprocess_revision = effective_reprocess_revision
        watch.unresolved_questions = ids.copy()
        watch.updated_at = now
        for prior_source in existing.values():
            if prior_source.enabled:
                prior_source.status = "idle"
                prior_source.consecutive_failures = 0
                prior_source.next_due_at = now

    for source_id, policy in normalized.items():
        urls = policy["allowed_urls"]
        record_ids = policy["record_ids"]
        row = existing.get(source_id)
        if row is None:
            session.add(
                ProjectMonitorWatchSource(
                    watch_id=watch.id,
                    source_id=source_id,
                    allowed_urls=urls,
                    record_ids=record_ids,
                    policy_snapshot=policy["policy_snapshot"],
                    applied_version=0,
                    next_due_at=now,
                    status="idle",
                )
            )
            changed_sources = True
        elif (
            not row.enabled
            or row.allowed_urls != urls
            or row.record_ids != record_ids
            or row.policy_snapshot != policy["policy_snapshot"]
        ):
            row.enabled = True
            row.allowed_urls = urls
            row.record_ids = record_ids
            row.policy_snapshot = policy["policy_snapshot"]
            row.status = "idle"
            changed_sources = True
    for source_id, row in existing.items():
        if source_id not in normalized and row.enabled:
            row.enabled = False
            row.status = "disabled"
            changed_sources = True
    session.flush()
    return watch


def upsert_watch(
    session: Session,
    need_id: UUID,
    *,
    sources: list[dict[str, Any]],
    question_ids: list[str] | None = None,
    enabled: bool = True,
    reprocess_revision: str | None = None,
) -> ProjectMonitorWatch:
    """API-facing name for the versioned per-need watch upsert."""
    return configure_watch(
        session,
        need_id,
        sources=sources,
        question_ids=question_ids,
        enabled=enabled,
        reprocess_revision=reprocess_revision,
    )


def watch_view(session: Session, need_id: UUID) -> dict[str, Any] | None:
    """Return the bounded current watch and source cursors for authenticated API use."""
    watch = session.scalar(
        select(ProjectMonitorWatch).where(ProjectMonitorWatch.need_id == need_id)
    )
    if watch is None:
        return None
    sources = session.scalars(
        select(ProjectMonitorWatchSource)
        .where(ProjectMonitorWatchSource.watch_id == watch.id)
        .order_by(ProjectMonitorWatchSource.source_id)
        .limit(12)
    ).all()
    return {
        "id": str(watch.id),
        "need_id": str(watch.need_id),
        "version": watch.version,
        "enabled": watch.enabled,
        "question_ids": list(watch.question_ids),
        "reprocess_revision": watch.reprocess_revision,
        "unresolved_questions": list(watch.unresolved_questions),
        "last_good_facts": list(watch.last_good_facts),
        "last_good_evidence_refs": list(watch.last_good_evidence_refs),
        "status": watch.status,
        "checkpoint": dict(watch.checkpoint),
        "fresh_at": watch.fresh_at,
        "revision_history": list(watch.revision_history),
        "sources": [
            {
                "source_id": row.source_id,
                "enabled": row.enabled,
                "allowed_urls": list(row.allowed_urls),
                "record_ids": list(row.record_ids),
                "policy_snapshot": dict(row.policy_snapshot),
                "applied_version": row.applied_version,
                "cursor": dict(row.cursor),
                "etag": row.etag,
                "last_modified": row.last_modified,
                "next_due_at": row.next_due_at,
                "last_attempt_at": row.last_attempt_at,
                "last_success_at": row.last_success_at,
                "consecutive_failures": row.consecutive_failures,
                "status": row.status,
                "error_class": row.error_class,
                "checkpoint": row.checkpoint,
            }
            for row in sources
        ],
    }


def provision_watch_from_evidence(
    session: Session,
    need_id: UUID,
    *,
    question_ids: list[str] | None = None,
    enabled: bool = False,
) -> ProjectMonitorWatch | None:
    """Create a bounded watch from current accepted records already linked to one active need."""
    need = session.get(PowerNeed, need_id)
    if need is None or not need.active:
        return None
    """Find at most twelve enabled registered sources already accepted for this need."""
    configured_sources = _registered_watch_sources(session, need_id)
    if not configured_sources:
        return None
    return upsert_watch(
        session,
        need_id,
        sources=configured_sources,
        question_ids=question_ids,
        enabled=enabled,
    )


def _provision_missing_watch_page(session: Session, limit: int) -> int:
    """Provision a small keyset page from exact accepted evidence only."""
    cursor = session.scalar(
        select(ProjectMonitorWatch.need_id)
        .order_by(ProjectMonitorWatch.need_id.desc())
        .limit(1)
    )
    has_current_registered_evidence = exists(
        select(1)
        .select_from(Observation)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(
            NeedObservation.need_id == PowerNeed.id,
            Source.enabled.is_(True),
            Source.registry_enabled.is_(True),
            Source.id.in_(SUPPORTED_SOURCES),
            Source.endpoint.in_(
                [
                    _registry_source(source_id)["endpoint"]
                    for source_id in sorted(SUPPORTED_SOURCES)
                ]
            ),
            Interpretation.status == "accepted",
            Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            Observation.content_hash == Evidence.content_hash,
        )
    )
    unconfigured = ~exists(
        select(1).where(ProjectMonitorWatch.need_id == PowerNeed.id)
    )

    def next_page(after):
        statement = select(PowerNeed.id).where(
            PowerNeed.active.is_(True),
            has_current_registered_evidence,
            unconfigured,
        )
        if after is not None:
            statement = statement.where(PowerNeed.id > after)
        return list(
            session.scalars(statement.order_by(PowerNeed.id).limit(limit))
        )

    need_ids = next_page(cursor)
    if not need_ids and cursor is not None:
        # Wrap once so newly eligible older UUIDs are eventually visited.
        need_ids = next_page(None)
    provisioned = 0
    for need_id in need_ids:
        if provision_watch_from_evidence(session, need_id, enabled=True) is not None:
            provisioned += 1
    return provisioned


def _registered_watch_sources(session: Session, need_id: UUID) -> list[dict[str, Any]]:
    source_ids = list(
        session.scalars(
            select(Source.id)
            .join(Observation, Observation.source_id == Source.id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .where(
                NeedObservation.need_id == need_id,
                Source.enabled.is_(True),
                Source.registry_enabled.is_(True),
                Source.id.in_(SUPPORTED_SOURCES),
                Interpretation.status == "accepted",
                Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            )
            .distinct()
            .order_by(Source.id)
            .limit(12)
        )
    )
    configured = []
    for source_id in source_ids:
        definition = _registry_source(source_id)
        source = session.get(Source, source_id)
        if source is None or source.endpoint != definition["endpoint"]:
            continue
        rows = session.execute(
            select(Observation.external_id, Observation.url)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .where(
                NeedObservation.need_id == need_id,
                Observation.source_id == source_id,
                Interpretation.status == "accepted",
                Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            )
            .order_by(Observation.external_id, Evidence.observed_at.desc())
            .distinct(Observation.external_id)
            .limit(MAX_DOCUMENTS)
        ).all()
        if rows:
            configured.append(
                {
                    "source_id": source_id,
                    "allowed_urls": sorted({url for _, url in rows}),
                    "record_ids": list(dict.fromkeys(external_id for external_id, _ in rows)),
                }
            )
    return configured


def plan_monitoring(
    session: Session,
    enabled: bool = False,
    limit: int = 20,
    now: datetime | None = None,
    max_active_jobs: int = MAX_ACTIVE_MONITOR_JOBS,
    max_active_per_host: int = MAX_ACTIVE_MONITOR_JOBS_PER_HOST,
    max_active_per_source: int | None = None,
) -> list[UUID]:
    """Queue due watch targets using indexed key order and row locks; never performs I/O."""
    if not enabled:
        return []
    if not 1 <= limit <= MAX_PLAN_BATCH:
        raise ValueError(f"Monitoring batch must be between 1 and {MAX_PLAN_BATCH}")
    if not 1 <= max_active_jobs <= MAX_PLAN_BATCH:
        raise ValueError(f"Active monitor cap must be between 1 and {MAX_PLAN_BATCH}")
    if not 1 <= max_active_per_host <= max_active_jobs:
        raise ValueError("Per-host monitor cap must be within the global active cap")
    if max_active_per_source is not None and not 1 <= max_active_per_source <= max_active_jobs:
        raise ValueError("Per-source monitor cap must be within the global active cap")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    # Serialize schedulers, then read at most the global active cap. A full
    # result means no capacity; a shorter result is the complete active set.
    session.execute(select(func.pg_advisory_xact_lock(0x474C334D4F4E)))
    active = session.execute(
        select(Job.source_id, Source.endpoint)
        .join(Source, Source.id == Job.source_id)
        .where(Job.kind == "project_monitor", Job.status.in_(["queued", "running"]))
        .limit(max_active_jobs)
    ).all()
    if len(active) >= max_active_jobs:
        return []
    host_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for _source_id, endpoint in active:
        host = urlsplit(endpoint).hostname or ""
        host_counts[host] = host_counts.get(host, 0) + 1
        source_counts[_source_id] = source_counts.get(_source_id, 0) + 1
    active_capacity = max_active_jobs - len(active)
    _provision_missing_watch_page(session, min(limit, 20))
    active_job = exists(
        select(Job.id).where(
            Job.kind == "project_monitor",
            Job.target_id == ProjectMonitorWatchSource.watch_id,
            Job.source_id == ProjectMonitorWatchSource.source_id,
            Job.status.in_(["queued", "running"]),
        )
    )
    rows = session.execute(
        select(ProjectMonitorWatchSource, ProjectMonitorWatch, Source)
        .join(ProjectMonitorWatch, ProjectMonitorWatch.id == ProjectMonitorWatchSource.watch_id)
        .join(Source, Source.id == ProjectMonitorWatchSource.source_id)
        .join(PowerNeed, PowerNeed.id == ProjectMonitorWatch.need_id)
        .where(
            ProjectMonitorWatch.enabled.is_(True),
            ProjectMonitorWatchSource.enabled.is_(True),
            ProjectMonitorWatchSource.status != "quarantined",
            Source.enabled.is_(True),
            Source.registry_enabled.is_(True),
            PowerNeed.active.is_(True),
            (ProjectMonitorWatchSource.next_due_at <= now)
            | (ProjectMonitorWatchSource.applied_version < ProjectMonitorWatch.version),
            ~active_job,
        )
        .order_by(
            ProjectMonitorWatchSource.applied_version,
            ProjectMonitorWatchSource.next_due_at,
            ProjectMonitorWatchSource.id,
        )
        .with_for_update(skip_locked=True, of=ProjectMonitorWatchSource)
        .limit(MAX_PLAN_BATCH)
    ).all()
    queued: list[UUID] = []
    for cursor, watch, source in rows:
        if len(queued) >= min(limit, active_capacity):
            break
        host = urlsplit(source.endpoint).hostname or ""
        if host_counts.get(host, 0) >= max_active_per_host:
            continue
        if (
            max_active_per_source is not None
            and source_counts.get(source.id, 0) >= max_active_per_source
        ):
            continue
        # Defense in depth in case source state changed since configuration.
        if source.id not in SUPPORTED_SOURCES:
            cursor.status = "blocked"
            cursor.error_class = "SOURCE_NOT_REVIEWED"
            continue
        job = Job(
            source_id=source.id,
            kind="project_monitor",
            target_id=watch.id,
            status="queued",
            available_at=now,
            checkpoint=f"watch:{watch.id}:v{watch.version}:source:{source.id}",
        )
        session.add(job)
        session.flush()
        cursor.status = "queued"
        cursor.last_attempt_at = now
        cursor.next_due_at = now + timedelta(hours=MONITOR_INTERVAL_HOURS)
        cursor.checkpoint = f"job:{job.id}:version:{watch.version}"
        watch.status = "queued"
        watch.checkpoint = {
            "job_id": str(job.id),
            "watch_version": watch.version,
            "source_id": source.id,
        }
        watch.updated_at = now
        queued.append(job.id)
        host_counts[host] = host_counts.get(host, 0) + 1
        source_counts[source.id] = source_counts.get(source.id, 0) + 1
    return queued


def record_monitor_outcome(
    session: Session,
    *,
    job_id: UUID,
    worker_id: str,
    fence: int,
    disposition: str,
    now: datetime | None = None,
    cursor: dict[str, Any] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    facts: list[dict[str, Any]] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    unresolved_questions: list[str] | None = None,
    error_class: str | None = None,
    enqueue_changed_questions: bool = False,
) -> None:
    """Persist a fenced attempt; only complete changed results replace last-good facts."""
    allowed = {"updated", "checked_no_change", "partial", "failed", "blocked", "cancelled"}
    if disposition not in allowed:
        raise ValueError("Unknown monitoring disposition")
    now = now or datetime.now(UTC)
    job = assert_fence(session, job_id, worker_id, fence)
    if job.kind != "project_monitor" or job.target_id is None:
        raise ValueError("Job is not a project-monitor attempt")
    source = session.get(Source, job.source_id)
    watch = session.scalar(
        select(ProjectMonitorWatch).where(ProjectMonitorWatch.id == job.target_id).with_for_update()
    )
    source_cursor = session.scalar(
        select(ProjectMonitorWatchSource)
        .where(
            ProjectMonitorWatchSource.watch_id == job.target_id,
            ProjectMonitorWatchSource.source_id == job.source_id,
        )
        .with_for_update()
    )
    if watch is None or source_cursor is None:
        raise ValueError("Monitor target is missing")
    if (
        not watch.enabled
        or not source_cursor.enabled
        or source is None
        or not source.enabled
        or not source.registry_enabled
    ):
        disposition, error_class = "blocked", "SOURCE_DISABLED"
    attempted_version = _checkpoint_version(source_cursor.checkpoint, ":version:", watch.version)
    if attempted_version != watch.version:
        disposition, error_class = "blocked", "WATCH_VERSION_CHANGED"
    source_cursor.last_attempt_at = now
    source_cursor.status = disposition
    source_cursor.error_class = error_class
    source_cursor.checkpoint = f"job:{job.id}:fence:{fence}:version:{watch.version}"
    if cursor is not None and disposition in {"updated", "checked_no_change"}:
        source_cursor.cursor = cursor
    job.status = (
        "completed"
        if disposition in {"updated", "checked_no_change", "partial"}
        else ("cancelled" if disposition == "cancelled" else "failed")
    )
    job.error = error_class
    job.lease_owner = None
    job.lease_until = None
    if disposition in {"updated", "checked_no_change"}:
        if etag is not None:
            source_cursor.etag = etag[:500]
        if last_modified is not None:
            source_cursor.last_modified = last_modified[:500]
        source_cursor.consecutive_failures = 0
        source_cursor.last_success_at = now
        source_cursor.applied_version = watch.version
        source_cursor.next_due_at = now + timedelta(hours=MONITOR_INTERVAL_HOURS)
        watch.fresh_at = now
        watch.status = "fresh"
        if disposition == "updated":
            prior_hashes = {
                (ref.get("source_id"), ref.get("external_id"), ref.get("content_hash"))
                for ref in watch.last_good_evidence_refs
                if ref.get("source_id") == source_cursor.source_id
            }
            changed_evidence = bool(
                evidence_refs
                and any(
                    (
                        ref.get("source_id"),
                        ref.get("external_id"),
                        ref.get("content_hash"),
                    )
                    not in prior_hashes
                    for ref in evidence_refs
                )
            )
            if changed_evidence:
                watch.revision_history = [
                    *watch.revision_history,
                    {
                        "event": "last_good_evidence_changed",
                        "version": watch.version,
                        "last_good_facts": watch.last_good_facts,
                        "last_good_evidence_refs": watch.last_good_evidence_refs,
                        "recorded_at": now.isoformat(),
                    },
                ]
            if evidence_refs is not None:
                _validate_evidence_refs(
                    session,
                    evidence_refs,
                    source_cursor.source_id,
                    watch.need_id,
                    source_cursor.allowed_urls,
                )
                watch.last_good_evidence_refs = [
                    ref
                    for ref in watch.last_good_evidence_refs
                    if ref.get("source_id") != source_cursor.source_id
                ] + evidence_refs
            if facts is not None:
                if facts and not evidence_refs:
                    raise ValueError("Updated facts require retained evidence references")
                watch.last_good_facts = facts
            if changed_evidence and enqueue_changed_questions:
                from gridlens.intelligence.intelligence_jobs import enqueue_missing_intelligence

                enqueue_missing_intelligence(
                    session,
                    need_id=watch.need_id,
                    question_ids=watch.unresolved_questions,
                    origin="monitoring",
                )
        if unresolved_questions is not None:
            for item in unresolved_questions:
                question_contract(item)
            watch.unresolved_questions = unresolved_questions
    elif disposition in {"failed", "blocked", "partial"}:
        source_cursor.consecutive_failures += 1
        delay_index = min(max(source_cursor.consecutive_failures - 1, 0), len(RETRY_HOURS) - 1)
        source_cursor.next_due_at = now + timedelta(hours=RETRY_HOURS[delay_index])
        if source_cursor.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            source_cursor.status = "quarantined"
            source_cursor.error_class = error_class or "REPEATED_MONITOR_FAILURE"
            watch.status = "quarantined"
        else:
            watch.status = disposition
    else:
        watch.status = "cancelled"
        source_cursor.next_due_at = now + timedelta(hours=MONITOR_INTERVAL_HOURS)
    watch.updated_at = now


@dataclass(frozen=True)
class MonitorRequest:
    job_id: UUID
    worker_id: str
    fence: int
    watch_id: UUID
    watch_version: int
    need_id: UUID
    project_id: UUID
    source_id: str
    allowed_urls: tuple[str, ...]
    record_ids: tuple[str, ...]
    question_ids: tuple[str, ...]
    last_good_evidence_refs: tuple[dict[str, Any], ...]
    cursor: dict[str, Any]
    etag: str | None
    last_modified: str | None
    deadline_monotonic: float
    max_documents: int = MAX_DOCUMENTS
    max_document_bytes: int = MAX_DOCUMENT_BYTES
    timeout_seconds: int = MAX_RUNTIME_SECONDS


def process_monitor_job(
    job_id: UUID,
    worker_id: str,
    fence: int,
    *,
    enabled: bool = False,
    retrieve=None,
    session_factory=None,
) -> str:
    """Read/prepare, retrieve outside a transaction, then persist through the job fence.

    The default uses exact registered-record acquisition and canonical evidence
    admission. `retrieve` exists only for deterministic tests and local harnesses.
    """
    factory = session_factory or SessionLocal
    with factory.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        if job.kind != "project_monitor" or job.target_id is None:
            raise ValueError("Job is not a project-monitor attempt")
        if not enabled:
            record_monitor_outcome(
                session,
                job_id=job_id,
                worker_id=worker_id,
                fence=fence,
                disposition="blocked",
                error_class="MONITORING_DISABLED",
            )
            return "blocked"
        source = session.get(Source, job.source_id)
        watch = session.scalar(
            select(ProjectMonitorWatch)
            .where(ProjectMonitorWatch.id == job.target_id)
            .with_for_update(read=True)
        )
        watch_source = session.scalar(
            select(ProjectMonitorWatchSource).where(
                ProjectMonitorWatchSource.watch_id == job.target_id,
                ProjectMonitorWatchSource.source_id == job.source_id,
            )
        )
        need = session.get(PowerNeed, watch.need_id) if watch else None
        project = session.get(Project, need.project_id) if need else None
        if (
            source is None
            or not source.enabled
            or not source.registry_enabled
            or watch is None
            or not watch.enabled
            or watch_source is None
            or not watch_source.enabled
            or need is None
            or not need.active
            or project is None
        ):
            record_monitor_outcome(
                session,
                job_id=job_id,
                worker_id=worker_id,
                fence=fence,
                disposition="blocked",
                error_class="SOURCE_OR_TARGET_DISABLED",
            )
            return "blocked"
        definition = _registry_source(source.id)
        if source.endpoint != definition["endpoint"] or not watch_source.allowed_urls:
            record_monitor_outcome(
                session,
                job_id=job_id,
                worker_id=worker_id,
                fence=fence,
                disposition="blocked",
                error_class="SOURCE_POLICY_INVALID",
            )
            return "blocked"
        request = MonitorRequest(
            job_id=job.id,
            worker_id=worker_id,
            fence=fence,
            watch_id=watch.id,
            watch_version=_checkpoint_version(job.checkpoint, ":v", watch.version),
            need_id=need.id,
            project_id=project.id,
            source_id=source.id,
            allowed_urls=tuple(validate_public_url(url) for url in watch_source.allowed_urls),
            record_ids=tuple(watch_source.record_ids),
            question_ids=tuple(watch.question_ids),
            last_good_evidence_refs=tuple(watch.last_good_evidence_refs),
            cursor=dict(watch_source.cursor),
            etag=watch_source.etag,
            last_modified=watch_source.last_modified,
            deadline_monotonic=time.monotonic() + MAX_RUNTIME_SECONDS,
        )
    started = time.monotonic()
    try:
        result = (
            retrieve(request)
            if retrieve is not None
            else _retrieve_registered_records(request, factory)
        )
        if time.monotonic() - started > MAX_RUNTIME_SECONDS:
            raise TimeoutError("Monitoring retrieval exceeded its hard runtime budget")
        if not isinstance(result, dict):
            raise ValueError("Monitoring retrieval returned no result object")
    except Exception as exc:
        result = {"disposition": "failed", "error_class": type(exc).__name__}
    disposition = result.get("disposition", "failed")
    with factory.begin() as session:
        record_monitor_outcome(
            session,
            job_id=job_id,
            worker_id=worker_id,
            fence=fence,
            disposition=disposition,
            cursor=result.get("cursor"),
            etag=result.get("etag"),
            last_modified=result.get("last_modified"),
            facts=result.get("facts"),
            evidence_refs=result.get("evidence_refs"),
            unresolved_questions=result.get("unresolved_questions"),
            error_class=result.get("error_class"),
            enqueue_changed_questions=enabled,
        )
    return disposition


def _retrieve_registered_records(request: MonitorRequest, factory) -> dict[str, Any]:
    """Refresh only exact accepted stable records through existing safe source/admission paths."""
    if not request.record_ids or len(request.record_ids) > MAX_DOCUMENTS:
        return {"disposition": "blocked", "error_class": "NO_LINKED_STABLE_RECORDS"}
    from gridlens.intelligence.research_evidence import retain_registered_record

    definition = _registry_source(request.source_id)
    allowed_urls = set(request.allowed_urls)
    accepted_refs: list[dict[str, Any]] = []
    partial = False
    for external_id in request.record_ids:
        if time.monotonic() >= request.deadline_monotonic:
            partial = True
            break

        def check_request_url(url: str) -> None:
            requested = validate_public_url(url)
            expected_origin = definition["endpoint"].split("/", 3)[:3]
            requested_origin = requested.split("/", 3)[:3]
            if requested_origin != expected_origin:
                raise ValueError("Registered adapter attempted a URL outside its exact source host")

        _source_definition, record = acquire_registered_record(
            request.source_id,
            external_id,
            deadline=request.deadline_monotonic,
            before_request=check_request_url,
            max_bytes=MAX_DOCUMENT_BYTES,
        )
        record_url = validate_public_url(record["html_url"])
        if record_url not in allowed_urls:
            partial = True
            continue
        with factory.begin() as session:
            job = assert_fence(session, request.job_id, request.worker_id, request.fence)
            if job.status != "running" or job.target_id != request.watch_id:
                raise RuntimeError("Monitoring job fence changed before retained-record admission")
            watch = session.get(ProjectMonitorWatch, request.watch_id)
            source = session.get(Source, request.source_id)
            watch_source = session.scalar(
                select(ProjectMonitorWatchSource).where(
                    ProjectMonitorWatchSource.watch_id == request.watch_id,
                    ProjectMonitorWatchSource.source_id == request.source_id,
                )
            )
            need = session.get(PowerNeed, request.need_id)
            project = session.get(Project, request.project_id)
            if (
                watch is None
                or not watch.enabled
                or watch.version != request.watch_version
                or source is None
                or not source.enabled
                or not source.registry_enabled
                or source.endpoint != definition["endpoint"]
                or watch_source is None
                or not watch_source.enabled
                or record_url not in watch_source.allowed_urls
                or need is None
                or not need.active
                or project is None
            ):
                raise RuntimeError("Monitoring source, need, or policy changed during retrieval")
            receipt = retain_registered_record(
                session,
                project,
                need,
                definition,
                record,
                job_id=request.job_id,
                worker_id=request.worker_id,
                fence=request.fence,
            )
            if receipt.get("disposition") != "ACCEPTED" or not receipt.get("evidence_id"):
                partial = True
                continue
            evidence = session.get(Evidence, UUID(str(receipt["evidence_id"])))
            if evidence is None:
                partial = True
                continue
            accepted_refs.append(
                {
                    "source_id": request.source_id,
                    "external_id": external_id,
                    "evidence_id": str(evidence.id),
                    "content_hash": evidence.content_hash,
                }
            )
    if partial or len(accepted_refs) != len(request.record_ids):
        return {"disposition": "partial", "error_class": "PARTIAL_REGISTERED_REFRESH"}
    if not accepted_refs:
        return {"disposition": "partial", "error_class": "NO_ACCEPTED_EVIDENCE"}
    prior = {
        (item.get("source_id"), item.get("external_id"), item.get("content_hash"))
        for item in request.last_good_evidence_refs
        if item.get("source_id") == request.source_id
    }
    changed = any(
        (item["source_id"], item["external_id"], item["content_hash"]) not in prior
        for item in accepted_refs
    )
    return {
        "disposition": "updated" if changed else "checked_no_change",
        "cursor": {
            "record_hashes": {
                item["external_id"]: item["content_hash"] for item in accepted_refs
            }
        },
        "evidence_refs": accepted_refs,
        "unresolved_questions": list(request.question_ids),
    }


def _validate_evidence_refs(
    session: Session,
    refs: list[dict[str, Any]],
    source_id: str,
    need_id: UUID,
    allowed_urls: list[str],
) -> None:
    if len(refs) > MAX_DOCUMENTS:
        raise ValueError("Monitoring evidence exceeds the document bound")
    for ref in refs:
        try:
            evidence_id = UUID(str(ref.get("evidence_id", "")))
        except ValueError as exc:
            raise ValueError("Evidence references require a retained evidence UUID") from exc
        if ref.get("source_id") != source_id or not ref.get("content_hash"):
            raise ValueError(
                "Evidence references require exact source, evidence ID, and content hash"
            )
        retained = session.execute(
            select(Evidence.url)
            .join(Observation, Observation.id == Evidence.observation_id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(
                Evidence.id == evidence_id,
                Evidence.content_hash == ref["content_hash"],
                Observation.source_id == source_id,
                NeedObservation.need_id == need_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if retained is None:
            raise ValueError("Evidence reference is not retained for this need and source")
        if retained not in allowed_urls:
            raise ValueError("Retained evidence URL is outside the exact watch allowlist")
