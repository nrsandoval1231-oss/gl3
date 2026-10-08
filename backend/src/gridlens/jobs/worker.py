import hashlib
import json
import os
import socket
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.jobs.queue import assert_fence, lease_one
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Job,
    PlannerState,
    PowerNeedBrief,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
    WorkerHeartbeat,
)
from gridlens.settings import settings

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
SCHEDULE_ZONE = "America/Chicago"
DAILY_ANCHOR = day_time(3, 0)
_SOURCE_CONFIGURATION_FIELDS = (
    "publisher",
    "endpoint",
    "family",
    "geography",
    "industries",
    "retrieval_method",
    "cadence_hours",
)
_REGISTRY_CONFIGURATION_FIELDS = (
    *_SOURCE_CONFIGURATION_FIELDS,
    "schedule_mode",
    "timezone",
    "schedule_anchor_time",
)
_MISSING_CONFIGURATION = object()
_PLANNER_RETRY_MONOTONIC: dict[str, float] = {}
_PLANNER_FAILURES: dict[str, int] = {}


def _effective_enabled(source: Source) -> bool:
    return source.enabled and source.registry_enabled


def _source_configuration(item: dict) -> dict:
    configuration = {
        key: item[key]
        for key in (
            "publisher",
            "endpoint",
            "family",
            "geography",
            "industries",
            "retrieval_method",
            "cadence_hours",
            "schedule_mode",
            "timezone",
            "schedule_anchor_time",
        )
        if key in item
    }
    configuration["cadence_hours"] = item.get("cadence_hours", 24)
    configuration["schedule_mode"] = item.get(
        "schedule_mode", "utc_hourly" if configuration["cadence_hours"] < 24 else "local_daily"
    )
    configuration["timezone"] = item.get("timezone", SCHEDULE_ZONE)
    configuration["schedule_anchor_time"] = item.get(
        "schedule_anchor_time", DAILY_ANCHOR.isoformat()
    )
    return configuration


def _normalized_registry_configuration(item: dict) -> dict:
    return _source_configuration(item)


def _source_storage_configuration(item: dict) -> dict:
    declaration = _normalized_registry_configuration(item)
    configuration = {
        field: declaration[field]
        for field in _SOURCE_CONFIGURATION_FIELDS
        if field in declaration
    }
    configuration["industries"] = item.get("industries", [])
    return configuration


def _epoch_configuration(epoch: SourceScheduleEpoch) -> dict:
    configuration = dict(epoch.configuration or {})
    configuration.setdefault("cadence_hours", epoch.cadence_hours)
    configuration.setdefault("schedule_mode", epoch.schedule_mode)
    configuration.setdefault("timezone", epoch.timezone)
    if isinstance(epoch.anchor, dict) and "local_time" in epoch.anchor:
        configuration.setdefault("schedule_anchor_time", epoch.anchor["local_time"])
    return configuration


def _normalized_configuration_values(configuration: dict, fields: tuple[str, ...]) -> tuple:
    values = []
    for field in fields:
        value = configuration.get(field, _MISSING_CONFIGURATION)
        if field == "schedule_anchor_time" and value is not _MISSING_CONFIGURATION:
            value = day_time.fromisoformat(value).isoformat()
        values.append((field, value))
    return tuple(values)


def _configuration_differs(left: dict, right: dict, fields: tuple[str, ...]) -> bool:
    return _normalized_configuration_values(left, fields) != _normalized_configuration_values(
        right, fields
    )


def _source_registry_drift(
    item: dict, source: Source, epoch: SourceScheduleEpoch | None
) -> bool:
    live_configuration = _normalized_registry_configuration(item)
    storage_configuration = _source_storage_configuration(item)
    persisted_configuration = {
        field: getattr(source, field, _MISSING_CONFIGURATION)
        for field in _SOURCE_CONFIGURATION_FIELDS
    }
    changed = (
        source.registry_enabled != bool(item["enabled"])
        or _configuration_differs(
            storage_configuration, persisted_configuration, _SOURCE_CONFIGURATION_FIELDS
        )
    )
    if epoch is not None:
        changed = changed or epoch.registry_enabled != bool(item["enabled"])
        changed = changed or _configuration_differs(
            live_configuration,
            _epoch_configuration(epoch),
            _REGISTRY_CONFIGURATION_FIELDS,
        )
    return changed


def _sync_source_configuration(source: Source, item: dict) -> None:
    for field, value in _source_storage_configuration(item).items():
        setattr(source, field, value)
    source.registry_enabled = bool(item["enabled"])


def _append_epoch(
    session, source: Source, item: dict, now: datetime, *, transition_known: bool = False
) -> None:
    current = session.scalar(
        select(SourceScheduleEpoch)
        .where(
            SourceScheduleEpoch.source_id == source.id,
            SourceScheduleEpoch.effective_until.is_(None),
        )
        .with_for_update()
        .order_by(SourceScheduleEpoch.effective_from.desc())
        .limit(1)
    )
    registry_enabled = bool(item["enabled"])
    config = _source_configuration(item)
    mode = item.get("schedule_mode", "utc_hourly" if source.cadence_hours < 24 else "local_daily")
    timezone = item.get("timezone", SCHEDULE_ZONE)
    if mode == "utc_hourly":
        anchor = {"utc": now.isoformat()}
    else:
        anchor = {
            "local_date": now.astimezone(ZoneInfo(timezone)).date().isoformat(),
            "local_time": item.get("schedule_anchor_time", DAILY_ANCHOR.isoformat()),
        }
    signature = (
        registry_enabled,
        source.enabled,
        source.cadence_hours,
        mode,
        timezone,
        anchor if not current else None,
        config,
    )
    if current:
        old_signature = (
            current.registry_enabled,
            current.operator_enabled,
            current.cadence_hours,
            current.schedule_mode,
            current.timezone,
            None,
            _epoch_configuration(current),
        )
        # The anchor is immutable within an epoch; ignore its generated value
        # while deciding whether the source's declared scheduling config changed.
        signature = signature[:5] + (None, signature[-1])
        if signature == old_signature:
            return
        if not transition_known:
            current.history_known = False
        current.effective_until = now
    session.add(
        SourceScheduleEpoch(
            source_id=source.id,
            registry_enabled=registry_enabled,
            operator_enabled=source.enabled,
            effective_from=now,
            cadence_hours=source.cadence_hours,
            schedule_mode=mode,
            timezone=timezone,
            anchor=anchor,
            configuration=config,
            history_known=True,
        )
    )


def _due_key(epoch: SourceScheduleEpoch, scheduled_for: datetime) -> str:
    key_material = f"{epoch.source_id}|{epoch.id}|{scheduled_for.isoformat()}"
    return hashlib.sha256(key_material.encode()).hexdigest()


def _scheduled_instants(
    epoch: SourceScheduleEpoch, now: datetime, *, not_before: datetime | None = None
):
    if type(epoch.cadence_hours) is not int or epoch.cadence_hours <= 0:
        raise ValueError("Schedule cadence must be a positive integer")
    if epoch.schedule_mode not in {"utc_hourly", "local_daily"}:
        raise ValueError("Schedule mode is invalid")
    if epoch.effective_from.tzinfo is None or now.tzinfo is None:
        raise ValueError("Schedule interval timestamps must be timezone-aware")
    if not_before is not None and not_before.tzinfo is None:
        raise ValueError("Schedule lower bound must be timezone-aware")
    if epoch.effective_until is not None and epoch.effective_until.tzinfo is None:
        raise ValueError("Schedule interval timestamps must be timezone-aware")
    if epoch.effective_until is not None and epoch.effective_until < epoch.effective_from:
        raise ValueError("Schedule interval end precedes its start")
    start = max(epoch.effective_from, not_before) if not_before else epoch.effective_from
    end = min(epoch.effective_until, now) if epoch.effective_until else now
    if end <= start:
        return
    if epoch.schedule_mode == "utc_hourly":
        if epoch.cadence_hours >= 24:
            raise ValueError("UTC-hourly schedule cadence must be less than one day")
        anchor_value = epoch.anchor["utc"]
        if not isinstance(anchor_value, str):
            raise ValueError("UTC-hourly schedule anchor must be an ISO timestamp")
        anchor = datetime.fromisoformat(anchor_value)
        if anchor.tzinfo is None:
            raise ValueError("UTC-hourly schedule anchor must be timezone-aware")
        interval = timedelta(hours=epoch.cadence_hours)
        elapsed = max(0, int((start - anchor).total_seconds() // interval.total_seconds()))
        due = anchor + interval * elapsed
        while due < start:
            due += interval
        while due < end:
            yield due
            due += interval
        return
    if epoch.cadence_hours % 24 != 0:
        raise ValueError("Local-daily schedule cadence must be a whole number of days")
    zone = ZoneInfo(epoch.timezone)
    local_date = epoch.anchor["local_date"]
    local_time = epoch.anchor["local_time"]
    if not isinstance(local_date, str) or not isinstance(local_time, str):
        raise ValueError("Local-daily schedule anchor must contain an ISO date and time")
    first_day = date.fromisoformat(local_date)
    anchor_time = day_time.fromisoformat(local_time)
    if anchor_time.tzinfo is not None:
        raise ValueError("Local-daily schedule anchor must not carry a timezone")
    day_step = max(1, epoch.cadence_hours // 24)
    candidate_day = max(first_day, start.astimezone(zone).date())
    days_since_anchor = (candidate_day - first_day).days
    step_count = (days_since_anchor + day_step - 1) // day_step
    cursor = first_day + timedelta(days=step_count * day_step)
    while True:
        local_due = datetime.combine(cursor, anchor_time, tzinfo=zone)
        round_trip = local_due.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) != local_due.replace(tzinfo=None):
            # Nonexistent spring-forward wall times resolve to the first valid
            # local time after the gap. Ambiguous fall-back times use fold=0.
            local_due = round_trip
        due = local_due.astimezone(UTC)
        if due >= end:
            break
        if due >= start:
            yield due
        cursor += timedelta(days=day_step)


def _reconcile_due(session, now: datetime) -> int:
    created = 0
    epochs = session.scalars(
        select(SourceScheduleEpoch)
        .order_by(SourceScheduleEpoch.source_id, SourceScheduleEpoch.effective_from)
        .with_for_update(skip_locked=True)
    ).all()
    for epoch in epochs:
        if not (epoch.history_known and epoch.registry_enabled and epoch.operator_enabled):
            continue
        for scheduled_for in _scheduled_instants(epoch, now):
            due_key = _due_key(epoch, scheduled_for)
            if session.get(SourceDueCheck, due_key):
                continue
            session.add(
                SourceDueCheck(
                    due_key=due_key,
                    source_id=epoch.source_id,
                    epoch_id=epoch.id,
                    scheduled_for=scheduled_for,
                    local_day=scheduled_for.astimezone(ZoneInfo(SCHEDULE_ZONE)).date(),
                    configuration=epoch.configuration,
                )
            )
            created += 1
    session.flush()
    return created


def _assign_due_jobs(session) -> int:
    from gridlens.jobs.queue import enqueue

    assigned = 0
    rows = session.scalars(
        select(SourceDueCheck)
        .where(SourceDueCheck.job_id.is_(None))
        .order_by(SourceDueCheck.scheduled_for, SourceDueCheck.source_id)
        .with_for_update(skip_locked=True)
    ).all()
    for due in rows:
        source = session.scalar(select(Source).where(Source.id == due.source_id).with_for_update())
        if source is None or not _effective_enabled(source):
            continue
        job_id = enqueue(session, due.source_id)
        already_linked = session.scalar(
            select(SourceDueCheck.due_key).where(SourceDueCheck.job_id == job_id)
        )
        if already_linked is None:
            due.job_id = job_id
            assigned += 1
    return assigned


def _park_if_disabled(session, job: Job, source: Source, definition: dict | None) -> bool:
    if job.kind != "ingestion":
        return False
    if source.enabled and source.registry_enabled and definition and definition.get("enabled"):
        return False
    job.status = "queued"
    job.attempts = max(0, job.attempts - 1)
    job.available_at = datetime.now(UTC) + timedelta(minutes=5)
    job.error = "Source disabled before acquisition; no provider request was made"
    job.lease_owner, job.lease_until = None, None
    source.health = {**source.health, "status": "Disabled", "error": job.error}
    return True


def _defer_registry_unavailable(job: Job, source: Source, error: Exception) -> None:
    job.status = "queued"
    job.attempts = max(0, job.attempts - 1)
    job.available_at = datetime.now(UTC) + timedelta(minutes=5)
    job.error = (
        "Source registry unavailable; no provider request was made ("
        f"{type(error).__name__})"
    )
    job.lease_owner, job.lease_until = None, None
    source.health = {
        **source.health,
        "status": "RegistryUnavailable",
        "error": job.error,
    }


def _append_attempt_receipt(session, job: Job, fence: int, disposition: str, counts: dict) -> None:
    due = session.scalar(select(SourceDueCheck).where(SourceDueCheck.job_id == job.id))
    if due is None:
        return
    canonical = json.dumps(counts, sort_keys=True, separators=(",", ":"), default=str)
    session.add(
        SourceCheckReceipt(
            due_key=due.due_key,
            job_id=job.id,
            fence=fence,
            disposition=disposition,
            check_counts=counts,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
        )
    )


def _acquire_dispatch_lock(source_id: str):
    """Hold a PostgreSQL session lock across provider work and internal commits."""
    connection = SessionLocal.kw["bind"].connect()
    connection.execute(
        text("SELECT pg_advisory_lock(hashtextextended(:source_id, 0))"),
        {"source_id": source_id},
    )
    connection.commit()
    return connection


def _release_dispatch_lock(connection, source_id: str) -> None:
    connection.execute(
        text("SELECT pg_advisory_unlock(hashtextextended(:source_id, 0))"),
        {"source_id": source_id},
    )
    connection.commit()
    connection.close()


def sync_registry() -> list[dict]:
    definitions = load_registry()
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        for item in definitions:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:source_id, 0))"),
                {"source_id": item["id"]},
            )
            row = session.scalar(
                select(Source).where(Source.id == item["id"]).with_for_update()
            )
            values = _source_storage_configuration(item)
            if row is None:
                row = Source(
                    id=item["id"],
                    **values,
                    enabled=True,
                    registry_enabled=bool(item["enabled"]),
                    health={"status": "Overdue"},
                )
                session.add(row)
            else:
                _sync_source_configuration(row, item)
            session.flush()
            _append_epoch(session, row, item, now)
    return definitions


def refresh_due() -> int:
    sync_registry()
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        _reconcile_due(session, now)
        return _assign_due_jobs(session)


def set_source_enabled(source_id: str, enabled: bool) -> None:
    """Perform an explicit operator enable/disable transition with its epoch."""
    with SessionLocal.begin() as session:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:source_id, 0))"),
            {"source_id": source_id},
        )
        definitions = {item["id"]: item for item in load_registry()}
        item = definitions.get(source_id)
        if item is None:
            raise ValueError("Source is not present in the registry")
        now = datetime.now(UTC)
        source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
        if source is None:
            raise ValueError("Source must be reconciled before an operator transition")
        current = session.scalar(
            select(SourceScheduleEpoch)
            .where(
                SourceScheduleEpoch.source_id == source_id,
                SourceScheduleEpoch.effective_until.is_(None),
            )
            .with_for_update()
            .order_by(SourceScheduleEpoch.effective_from.desc())
            .limit(1)
        )
        if _source_registry_drift(item, source, current) and current is not None:
            current.history_known = False
        _sync_source_configuration(source, item)
        source.enabled = enabled
        _append_epoch(session, source, item, now, transition_known=True)


def run_one(definitions: dict[str, dict], *, job_ids: list[UUID] | None = None) -> bool:
    dispatch_connection = None
    with SessionLocal.begin() as session:
        leased = lease_one(session, WORKER_ID, lease_seconds=600, job_ids=job_ids)
        if leased is None:
            return False
        job, fence = leased
        job_id, source_id, kind = job.id, job.source_id, job.kind
        source = session.get(Source, source_id)
        if source and kind == "ingestion":
            try:
                current_definitions = {item["id"]: item for item in load_registry()}
            except Exception as exc:
                _defer_registry_unavailable(job, source, exc)
                return True
            if _park_if_disabled(session, job, source, current_definitions.get(source_id)):
                return True
        if source and kind == "ingestion":
            source.health = {
                **source.health,
                "status": "Running",
                "last_attempt": datetime.now(UTC).isoformat(),
            }
    attempted = datetime.now(UTC).isoformat()
    try:
        if kind == "pursuit_question":
            from gridlens.intelligence.autonomous_research import (
                _retry_deadline,
                process_question_job,
            )
            from gridlens.persistence.models import PursuitResearchQuestion

            try:
                process_question_job(job_id, WORKER_ID, fence)
            except Exception as exc:
                with SessionLocal.begin() as session:
                    question_job = assert_fence(session, job_id, WORKER_ID, fence)
                    question = session.get(PursuitResearchQuestion, question_job.target_id)
                    if question:
                        question.status = "FAILED"
                        question.completed_at = datetime.now(UTC)
                        retry_after = _retry_deadline(question, question.completed_at)
                        question.retry_after = retry_after or (
                            question.completed_at + timedelta(hours=24)
                        )
                        question.receipt = {
                            **question.receipt,
                            "error": type(exc).__name__,
                            "result_disposition": "FAILED",
                            "reevaluation_status": "FAILED",
                            "retry_class": "UNKNOWN_EFFECT"
                            if question.receipt.get("inflight_url")
                            or question.receipt.get("ambiguous_effects")
                            else "BOUNDED_TRANSIENT"
                            if retry_after is not None
                            else "RETRIES_EXHAUSTED",
                        }
                    question_job.status, question_job.error = "failed", type(exc).__name__
                    question_job.lease_owner, question_job.lease_until = None, None
            return True
        if kind == "pursuit_research":
            from gridlens.intelligence.pursuits import process_research_job

            process_research_job(job_id, WORKER_ID, fence)
            return True
        if kind == "power_need_brief":
            from gridlens.intelligence.briefs import process_brief_job

            try:
                process_brief_job(job_id, WORKER_ID, fence)
            except Exception as exc:
                # Brief jobs may have reached a billable provider request. Any
                # unexpected failure is terminal; retry requires an owner action.
                with SessionLocal.begin() as session:
                    failed = session.get(Job, job_id)
                    valid = bool(
                        failed
                        and failed.status == "running"
                        and failed.lease_owner == WORKER_ID
                        and failed.fence == fence
                    )
                    if valid and failed:
                        brief = (
                            session.get(PowerNeedBrief, failed.target_id)
                            if failed.target_id
                            else None
                        )
                        if brief and brief.status == "pending":
                            brief.status = "failed"
                            brief.error = (
                                "ambiguous_prior_request"
                                if failed.checkpoint and '"reserved": true' in failed.checkpoint
                                else "worker_failed"
                            )
                        failed.status, failed.error = "failed", type(exc).__name__
                        failed.lease_owner, failed.lease_until = None, None
            return True
        with SessionLocal() as session:
            dispatch_connection = _acquire_dispatch_lock(source_id)
            source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
            finished_job = session.get(Job, job_id)
            if source is None or finished_job is None:
                raise RuntimeError("Leased ingestion source disappeared")
            try:
                definition = next(
                    (item for item in load_registry() if item["id"] == source_id), None
                )
            except Exception as exc:
                _defer_registry_unavailable(finished_job, source, exc)
                session.commit()
                _release_dispatch_lock(dispatch_connection, source_id)
                dispatch_connection = None
                return True
            if definition is None:
                _park_if_disabled(session, finished_job, source, None)
                session.commit()
                _release_dispatch_lock(dispatch_connection, source_id)
                dispatch_connection = None
                return True
            if _park_if_disabled(session, finished_job, source, definition):
                session.commit()
                _release_dispatch_lock(dispatch_connection, source_id)
                dispatch_connection = None
                return True
            counts = process_job(session, job_id, WORKER_ID, fence, definition)
            assert finished_job and source
            assert_fence(session, job_id, WORKER_ID, fence)
            (
                finished_job.status,
                finished_job.lease_until,
                finished_job.lease_owner,
                finished_job.error,
            ) = "succeeded", None, None, None
            source.health = {
                **source.health,
                "status": "Updated" if counts["new"] or counts["changed"] else "Checked—No Change",
                "last_attempt": attempted,
                "last_success": attempted,
                "new_records": counts["new"],
                "changed_records": counts["changed"],
                "unchanged_records": counts["unchanged"],
                "parse_failures": 0,
                "error": None,
                "latest_publication_date": counts["latest_publication_date"],
                "collection_scope": definition.get("collection_scope"),
                "coverage_limitation": definition.get("coverage_limitation"),
                **{
                    key: counts[key]
                    for key in (
                        "retrieved_records",
                        "parsed_records",
                        "snapshot_item_count",
                        "snapshot_oldest_publication_date",
                        "snapshot_newest_publication_date",
                        "latest_permit_issue_date",
                        "latest_public_comment_deadline",
                        "earliest_public_comment_deadline",
                        "records_scanned",
                        "permit_accepted",
                        "permit_rejected",
                        "documents_extracted",
                        "unextracted_public_notice_references",
                        "generator_facts",
                        "generator_excerpts_omitted",
                        "missing_application_documents",
                    )
                    if key in counts
                },
                "pdf_candidates": counts.get("pdf_candidates", 0),
                "pdf_eligible": counts.get("pdf_eligible", 0),
                "pdf_enriched": counts.get("pdf_enriched", 0),
                "pdf_skipped_not_signal": counts.get("pdf_skipped_not_signal", 0),
                "pdf_skipped_limit": counts.get("pdf_skipped_limit", 0),
            }
            disposition = (
                "partial" if counts.get("parse_failures") or counts.get("partial") else "succeeded"
            )
            _append_attempt_receipt(session, finished_job, fence, disposition, counts)
            if source_id in {
                "austin-building-permits",
                "texas-rrc-drilling-permits",
                "houston-weekly-permits",
                "dallas-monthly-permits",
                "el-paso-new-commercial-permits",
                "boston-building-permits",
            }:
                from gridlens.jobs.queue import enqueue

                research_anchor = session.get(Source, "austin-building-permits")
                if research_anchor and research_anchor.enabled:
                    enqueue(session, research_anchor.id, kind="pursuit_research")
            session.commit()
            _release_dispatch_lock(dispatch_connection, source_id)
            dispatch_connection = None
    except Exception as exc:
        with SessionLocal.begin() as session:
            failed_job = session.get(Job, job_id)
            source = session.get(Source, source_id)
            valid_owner = bool(
                failed_job
                and failed_job.fence == fence
                and failed_job.status == "running"
                and failed_job.lease_owner == WORKER_ID
                and failed_job.lease_until
                and failed_job.lease_until > datetime.now(UTC)
            )
            if failed_job and valid_owner:
                failed_job.status = "queued" if failed_job.attempts < 5 else "failed"
                failed_job.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(3600, 30 * (2**failed_job.attempts))
                )
                failed_job.lease_until, failed_job.lease_owner = None, None
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                failed_job.error = (
                    str(exc)[:250] if isinstance(exc, SourceParseError) else type(exc).__name__
                )
                if kind == "ingestion":
                    from gridlens.ingestion.adapters.federal_register import SourceParseError

                    _append_attempt_receipt(
                        session,
                        failed_job,
                        fence,
                        "failed" if isinstance(exc, SourceParseError) else "unknown",
                        {"error_class": type(exc).__name__},
                    )
            if source and valid_owner and kind == "ingestion":
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                is_parse_error = isinstance(exc, SourceParseError)
                source.health = {
                    **source.health,
                    "status": "Failed",
                    "last_attempt": attempted,
                    "parse_failures": int(source.health.get("parse_failures", 0))
                    + int(is_parse_error),
                    "error": str(exc)[:250] if is_parse_error else type(exc).__name__,
                }
    finally:
        if dispatch_connection is not None:
            try:
                _release_dispatch_lock(dispatch_connection, source_id)
            except Exception:
                dispatch_connection.close()
    return True


def main() -> None:
    next_heartbeat = 0.0
    definitions = {row["id"]: row for row in load_registry()}
    while True:
        if settings.worker_auto_refresh:
            _run_planner("sources", refresh_due)
            _run_planner("pursuit_questions", plan_pursuit_questions)
        if time.monotonic() >= next_heartbeat:
            try:
                with SessionLocal.begin() as session:
                    heartbeat = session.get(WorkerHeartbeat, WORKER_ID)
                    if heartbeat is None:
                        session.add(
                            WorkerHeartbeat(worker_id=WORKER_ID, last_seen_at=datetime.now(UTC))
                        )
                    else:
                        heartbeat.last_seen_at = datetime.now(UTC)
            except Exception:
                # API readiness reports database unavailability separately.
                pass
            next_heartbeat = time.monotonic() + 10
        try:
            did_work = run_one(definitions)
        except Exception:
            did_work = False
        if not did_work:
            time.sleep(2)


def _run_planner(planner_key: str, action) -> bool:
    now = datetime.now(UTC)
    if time.monotonic() < _PLANNER_RETRY_MONOTONIC.get(planner_key, 0):
        return False
    try:
        with SessionLocal() as session:
            state = session.get(PlannerState, planner_key)
            if state and state.next_retry_at and state.next_retry_at > now:
                return False
        action()
        with SessionLocal.begin() as session:
            state = session.get(PlannerState, planner_key)
            if state is None:
                state = PlannerState(planner_key=planner_key, consecutive_failures=0)
                session.add(state)
            state.last_attempt_at = now
            state.last_success_at = now
            state.consecutive_failures = 0
            state.next_retry_at = now + timedelta(hours=1)
            state.error_class = None
        _PLANNER_RETRY_MONOTONIC.pop(planner_key, None)
        _PLANNER_FAILURES.pop(planner_key, None)
    except Exception as exc:
        failures = _PLANNER_FAILURES.get(planner_key, 0) + 1
        _PLANNER_FAILURES[planner_key] = failures
        delay = min(3600, 30 * (2 ** min(failures - 1, 7)))
        _PLANNER_RETRY_MONOTONIC[planner_key] = time.monotonic() + delay
        try:
            with SessionLocal.begin() as session:
                state = session.get(PlannerState, planner_key)
                if state is None:
                    state = PlannerState(planner_key=planner_key, consecutive_failures=failures - 1)
                    session.add(state)
                state.last_attempt_at = now
                state.consecutive_failures += 1
                state.error_class = type(exc).__name__
                delay = min(3600, 30 * (2 ** min(state.consecutive_failures - 1, 7)))
                state.next_retry_at = now + timedelta(seconds=delay)
                _PLANNER_FAILURES[planner_key] = state.consecutive_failures
        except Exception:
            pass
        return False
    return True


def plan_pursuit_questions() -> int:
    if not settings.autonomous_research_enabled:
        return 0
    from gridlens.intelligence.autonomous_research import planning_cards
    from gridlens.intelligence.pursuit_questions import schedule_questions

    cards = planning_cards()
    with SessionLocal.begin() as session:
        return len(schedule_questions(session, cards, grouped=True))


if __name__ == "__main__":
    main()
