import hashlib
import json
import logging
import os
import re
import signal
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text

from gridlens.ingestion.adapters.acquisition_runtime import (
    FencedLeaseRenewer,
    acquisition_deadline,
    try_public_acquisition_admission,
)
from gridlens.ingestion.adapters.diagnostics import (
    acquisition_diagnostics,
    acquisition_error_message,
)
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.jobs.queue import assert_fence, lease_one
from gridlens.jobs.source_schedule_proof import SCHEDULE_PROOF_VERSION
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Job,
    PlannerState,
    PowerNeedBrief,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
    SourceScheduleProgress,
    WorkerHeartbeat,
)
from gridlens.settings import settings

logger = logging.getLogger(__name__)
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
# Inclusive of the current job. Retries retain this budget and the existing
# five-attempt limit, so this bounds jobs, not crash/retry acquisition dispatches.
MAX_COLLECTION_CHAIN_JOBS = 8


def _collection_checkpoint(raw: str | None, parsed: object) -> dict:
    if isinstance(parsed, dict):
        return parsed
    # Older initial structured jobs stored the last external record ID directly.
    # Preserve those bounded IDs (including JSON-looking numeric IDs), without
    # treating malformed budget objects or JSON booleans/null as fresh chains.
    if (
        raw is not None
        and len(raw) <= 128
        and raw not in {"true", "false", "null"}
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*(?: [A-Za-z0-9_-]+)*", raw)
    ):
        return {"last_record_external_id": raw}
    raise ValueError("Invalid structured collection job budget")


def _collection_jobs_remaining(checkpoint: object) -> int:
    if not isinstance(checkpoint, dict):
        raise ValueError("Invalid structured collection job budget")
    remaining = checkpoint.get("collection_jobs_remaining", MAX_COLLECTION_CHAIN_JOBS)
    if type(remaining) is not int or not 1 <= remaining <= MAX_COLLECTION_CHAIN_JOBS:
        raise ValueError("Invalid structured collection job budget")
    return remaining


def _schedule_zone() -> str:
    return settings.schedule_timezone


def _daily_anchor() -> day_time:
    return day_time.fromisoformat(settings.schedule_anchor_time)


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
_HEARTBEAT_INTERVAL_SECONDS = 10
_PLANNER_POLL_SECONDS = 5
_IDLE_JOB_POLL_SECONDS = 2
_SHUTDOWN_JOIN_SECONDS = 5
_SCHEDULE_RECENT_DAYS = 7
_SCHEDULE_RECENT_CAP = 256
_SCHEDULE_HISTORY_CAP = 256
_SCHEDULE_EPOCH_CAP = 64
_DUE_ASSIGNMENT_CAP = 100
_PLANNER_SUCCESS_INTERVAL = timedelta(hours=1)


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
    configuration["timezone"] = item.get("timezone", _schedule_zone())
    configuration["schedule_anchor_time"] = item.get(
        "schedule_anchor_time", _daily_anchor().isoformat()
    )
    return configuration


def _normalized_registry_configuration(item: dict) -> dict:
    return _source_configuration(item)


def _source_storage_configuration(item: dict) -> dict:
    declaration = _normalized_registry_configuration(item)
    configuration = {
        field: declaration[field] for field in _SOURCE_CONFIGURATION_FIELDS if field in declaration
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


def _source_registry_drift(item: dict, source: Source, epoch: SourceScheduleEpoch | None) -> bool:
    live_configuration = _normalized_registry_configuration(item)
    storage_configuration = _source_storage_configuration(item)
    persisted_configuration = {
        field: getattr(source, field, _MISSING_CONFIGURATION)
        for field in _SOURCE_CONFIGURATION_FIELDS
    }
    changed = source.registry_enabled != bool(item["enabled"]) or _configuration_differs(
        storage_configuration, persisted_configuration, _SOURCE_CONFIGURATION_FIELDS
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
    timezone = item.get("timezone", _schedule_zone())
    if mode == "utc_hourly":
        anchor = {"utc": now.isoformat()}
    else:
        anchor = {
            "local_date": now.astimezone(ZoneInfo(timezone)).date().isoformat(),
            "local_time": item.get("schedule_anchor_time", _daily_anchor().isoformat()),
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


def _next_scheduled_after(epoch: SourceScheduleEpoch, scheduled_for: datetime) -> datetime | None:
    horizon = scheduled_for + timedelta(hours=epoch.cadence_hours + 25)
    return next(
        _scheduled_instants(
            epoch,
            horizon,
            not_before=scheduled_for + timedelta(microseconds=1),
        ),
        None,
    )


def _reconcile_due(session, now: datetime) -> int:
    created = 0
    last_planned = (
        select(SourceScheduleProgress.last_planned_at)
        .where(SourceScheduleProgress.epoch_id == SourceScheduleEpoch.id)
        .scalar_subquery()
    )
    epochs = session.scalars(
        select(SourceScheduleEpoch)
        .where(
            SourceScheduleEpoch.history_known.is_(True),
            SourceScheduleEpoch.registry_enabled.is_(True),
            SourceScheduleEpoch.operator_enabled.is_(True),
            SourceScheduleEpoch.effective_from < now,
        )
        .order_by(last_planned.asc().nullsfirst(), SourceScheduleEpoch.source_id)
        .with_for_update(skip_locked=True)
        .limit(_SCHEDULE_EPOCH_CAP)
    ).all()
    recent_start = now - timedelta(days=_SCHEDULE_RECENT_DAYS)
    for epoch in epochs:
        if not (epoch.history_known and epoch.registry_enabled and epoch.operator_enabled):
            continue
        progress = session.get(SourceScheduleProgress, epoch.id, with_for_update=True)
        if progress is None:
            progress = SourceScheduleProgress(epoch_id=epoch.id)
            session.add(progress)
            session.flush()
        recent_cursor = progress.recent_cursor
        # Revisit the overlap so a commit/restart race cannot lose recent obligations.
        recent_floor = max(epoch.effective_from, recent_start)
        if recent_cursor is not None:
            recent_floor = max(recent_floor, recent_cursor - timedelta(days=1))
        recent_slots = []
        for scheduled_for in _scheduled_instants(epoch, now, not_before=recent_floor):
            if scheduled_for >= now - timedelta(days=_SCHEDULE_RECENT_DAYS):
                recent_slots.append(scheduled_for)
                if len(recent_slots) >= _SCHEDULE_RECENT_CAP:
                    break
        history_slots = []
        history_ceiling = min(recent_start, epoch.effective_until or now)
        history_floor = max(epoch.effective_from, progress.history_cursor or epoch.effective_from)
        if history_floor < history_ceiling:
            for scheduled_for in _scheduled_instants(
                epoch, history_ceiling, not_before=history_floor
            ):
                history_slots.append(scheduled_for)
                if len(history_slots) >= _SCHEDULE_HISTORY_CAP:
                    break
        slots = sorted(set(recent_slots + history_slots))
        for scheduled_for in slots:
            due_key = _due_key(epoch, scheduled_for)
            existing = session.get(SourceDueCheck, due_key)
            if existing is None:
                session.add(
                    SourceDueCheck(
                        due_key=due_key,
                        source_id=epoch.source_id,
                        epoch_id=epoch.id,
                        scheduled_for=scheduled_for,
                        local_day=scheduled_for.astimezone(ZoneInfo(epoch.timezone)).date(),
                        configuration=epoch.configuration,
                    )
                )
                created += 1
        if recent_slots:
            progress.recent_cursor = max(
                progress.recent_cursor or recent_slots[-1], recent_slots[-1]
            )
        if history_slots:
            progress.history_cursor = history_slots[-1] + timedelta(microseconds=1)
        progress.last_planned_at = now
    session.flush()
    return created


def _assign_due_jobs(session) -> int:
    from gridlens.jobs.queue import enqueue

    assigned = 0
    registry = {item["id"]: item for item in load_registry()}
    eligible_registry_ids = [
        source_id for source_id, item in registry.items() if item.get("enabled") is True
    ]
    if not eligible_registry_ids:
        return 0
    now = session.scalar(text("SELECT clock_timestamp()"))
    candidates = session.scalars(
        select(Source)
        .join(SourceScheduleEpoch, SourceScheduleEpoch.source_id == Source.id)
        .where(
            Source.id.in_(eligible_registry_ids),
            Source.enabled.is_(True),
            Source.registry_enabled.is_(True),
            SourceScheduleEpoch.effective_from <= now,
            or_(
                SourceScheduleEpoch.effective_until.is_(None),
                SourceScheduleEpoch.effective_until > now,
            ),
            SourceScheduleEpoch.history_known.is_(True),
            SourceScheduleEpoch.registry_enabled.is_(True),
            SourceScheduleEpoch.operator_enabled.is_(True),
        )
        .order_by(Source.id)
    ).all()
    eligible_ids = []
    for source in candidates:
        item = registry[source.id]
        from gridlens.jobs.queue import _source_retry_hold_until

        retry_hold_until = _source_retry_hold_until(
            source.health if isinstance(source.health, dict) else {}
        )
        if retry_hold_until is not None and retry_hold_until > now:
            continue
        epoch = session.scalar(
            select(SourceScheduleEpoch)
            .where(
                SourceScheduleEpoch.source_id == source.id,
                SourceScheduleEpoch.effective_from <= now,
                or_(
                    SourceScheduleEpoch.effective_until.is_(None),
                    SourceScheduleEpoch.effective_until > now,
                ),
            )
            .order_by(SourceScheduleEpoch.effective_from.desc())
            .limit(1)
        )
        if not _source_registry_drift(item, source, epoch):
            eligible_ids.append(source.id)
    if not eligible_ids:
        return 0
    rows = session.scalars(
        select(SourceDueCheck)
        .join(SourceScheduleEpoch, SourceScheduleEpoch.id == SourceDueCheck.epoch_id)
        .join(Source, Source.id == SourceDueCheck.source_id)
        .where(
            SourceDueCheck.job_id.is_(None),
            SourceDueCheck.source_id.in_(eligible_ids),
            Source.enabled.is_(True),
            Source.registry_enabled.is_(True),
            SourceScheduleEpoch.effective_from <= now,
            or_(
                SourceScheduleEpoch.effective_until.is_(None),
                SourceScheduleEpoch.effective_until > now,
            ),
            SourceScheduleEpoch.history_known.is_(True),
            SourceScheduleEpoch.registry_enabled.is_(True),
            SourceScheduleEpoch.operator_enabled.is_(True),
            SourceDueCheck.scheduled_for <= now,
            SourceDueCheck.scheduled_for
            + (SourceScheduleEpoch.cadence_hours * text("INTERVAL '1 hour'"))
            + timedelta(hours=1)
            > now,
        )
        .order_by(SourceDueCheck.scheduled_for.desc(), SourceDueCheck.source_id)
        .with_for_update(of=SourceDueCheck, skip_locked=True)
        .limit(_DUE_ASSIGNMENT_CAP)
    ).all()
    for due in rows:
        source = session.scalar(
            select(Source).where(Source.id == due.source_id).with_for_update(skip_locked=True)
        )
        if source is None or not _effective_enabled(source):
            continue
        due_definition = registry.get(source.id)
        epoch = session.scalar(
            select(SourceScheduleEpoch)
            .where(SourceScheduleEpoch.id == due.epoch_id)
            .with_for_update(skip_locked=True)
        )
        if epoch is None or not (
            epoch.effective_from <= now
            and (epoch.effective_until is None or now < epoch.effective_until)
        ):
            continue
        # Keep the due row pending while a source configuration is held by an
        # active acquisition. Never enqueue work against a stale enabled/config.
        if (
            due_definition is None
            or epoch is None
            or _source_registry_drift(due_definition, source, epoch)
        ):
            continue
        canonical_due = next(
            _scheduled_instants(
                epoch,
                due.scheduled_for + timedelta(microseconds=1),
                not_before=due.scheduled_for,
            ),
            None,
        )
        if canonical_due != due.scheduled_for:
            continue
        next_scheduled_for = _next_scheduled_after(epoch, due.scheduled_for)
        if epoch.effective_until is not None and (
            next_scheduled_for is None or epoch.effective_until < next_scheduled_for
        ):
            next_scheduled_for = epoch.effective_until
        if next_scheduled_for is None or not (due.scheduled_for <= now < next_scheduled_for):
            continue
        job_id = enqueue(session, due.source_id)
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "queued":
            continue
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
        f"Source registry unavailable; no provider request was made ({type(error).__name__})"
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
            recorded_at=session.scalar(text("SELECT clock_timestamp()")),
        )
    )


def _acquisition_retry_class(error: BaseException, diagnostics: dict) -> str:
    """Retry only known transient transport, rate-limit, and server failures."""
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    if diagnostics.get("retry_after_unrepresentable") == 1:
        return "PERMANENT"
    if (
        diagnostics.get("retry_after_exceeds_bound") == 1
        and _retry_after_deadline(diagnostics.get("retry_after_at")) is None
    ):
        return "PERMANENT"
    status = diagnostics.get("http_status")
    if type(status) is int:
        return "TRANSIENT" if status in {408, 425, 429} or status >= 500 else "PERMANENT"
    if diagnostics.get("error_code") in {"acquisition_timeout", "network_error"}:
        return "TRANSIENT"
    if isinstance(error, SourceParseError) or diagnostics.get("error_code") == "source_parse_error":
        return "PERMANENT"
    return "BOUNDED_UNKNOWN"


def _retry_after_deadline(raw: object) -> datetime | None:
    if not isinstance(raw, str) or len(raw) > 40:
        return None
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if deadline.tzinfo is None:
        return None
    return deadline.astimezone(UTC)


def _defer_public_acquisition(job_id: UUID, worker_id: str, fence: int) -> None:
    """Requeue admission contention without charging an attempt or marking I/O."""
    from gridlens.jobs.retry import jittered_delay_seconds

    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        job.attempts = max(0, job.attempts - 1)
        job.status = "queued"
        job.available_at = now + timedelta(
            seconds=jittered_delay_seconds(
                str(job.id), job.fence, 3, ceiling_seconds=5, jitter_percent=50
            )
        )
        job.lease_owner = job.lease_until = None
        job.error = "PUBLIC_ACQUISITION_SLOT_BUSY; deferred before request"


def _release_admission(admission_context) -> None:
    if admission_context is not None:
        try:
            admission_context.__exit__(None, None, None)
        except Exception:
            logger.exception("Failed to release public acquisition admission")


def sync_registry() -> list[dict]:
    definitions = load_registry()
    now = datetime.now(UTC)
    for item in definitions:
        # Do not let one active source request stall reconciliation for every
        # other source. A busy source retains its existing epoch/configuration
        # and is reconciled on the next pass.
        try:
            with SessionLocal.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
                acquired = session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:source_id, 0))"),
                    {"source_id": item["id"]},
                )
                if not acquired:
                    logger.info(
                        "source registry synchronization deferred for active acquisition: %s; "
                        "persisted schedule epoch retained",
                        item["id"],
                    )
                    continue
                row = session.scalar(
                    select(Source).where(Source.id == item["id"]).with_for_update(skip_locked=True)
                )
                values = _source_storage_configuration(item)
                if row is None:
                    row_exists = session.scalar(select(Source.id).where(Source.id == item["id"]))
                    if row_exists is not None:
                        continue
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
        except Exception:
            logger.exception("source registry reconciliation deferred for %s", item["id"])
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
        from gridlens.domain.regional_scope import REGIONAL_DISABLED_SOURCE_IDS

        if enabled and source_id in REGIONAL_DISABLED_SOURCE_IDS:
            raise ValueError("Source is disabled by the regional registry policy")
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
    admission_context = None
    lease_renewer = None
    with SessionLocal.begin() as session:
        leased = lease_one(session, WORKER_ID, lease_seconds=600, job_ids=job_ids)
        if leased is None:
            return False
        job, fence = leased
        job_id, source_id, kind = job.id, job.source_id, job.kind
        lease_expiry = job.lease_until
        deadline = acquisition_deadline(lease_expiry) if lease_expiry is not None else None
        try:
            job_checkpoint = json.loads(job.checkpoint or "{}")
        except (ValueError, TypeError):
            job_checkpoint = None
        intelligence_task_type = (
            job_checkpoint.get("task_type") if isinstance(job_checkpoint, dict) else None
        )
        source = session.get(Source, source_id)
        if source and kind == "ingestion":
            try:
                current_definitions = {item["id"]: item for item in load_registry()}
            except Exception as exc:
                _defer_registry_unavailable(job, source, exc)
                return True
            if _park_if_disabled(session, job, source, current_definitions.get(source_id)):
                return True
    attempted = datetime.now(UTC).isoformat()
    acquisition_started_at: datetime | None = None
    try:
        public_acquisition_kinds = {
            "ingestion",
            "project_monitor",
            "pursuit_question",
            "pursuit_research",
            "buying_chain_research",
            "company_contact_discovery",
            "rrc_well_research",
        }
        uses_public_acquisition = (
            kind in public_acquisition_kinds
            and (
                kind != "buying_chain_research"
                or (
                    intelligence_task_type == "buying_chain_research"
                    and settings.buying_chain_public_research_enabled
                )
            )
            and (kind != "company_contact_discovery" or settings.company_contact_discovery_enabled)
        ) or (kind == "intelligence_process" and intelligence_task_type == "OCR_EXTRACTION")
        if uses_public_acquisition:
            if source_id is None or lease_expiry is None or deadline is None:
                raise RuntimeError("Public acquisition requires a source and finite job lease")
            admission_context = try_public_acquisition_admission(SessionLocal.kw["bind"], source_id)
            admitted = admission_context.__enter__()
            if not admitted:
                _release_admission(admission_context)
                admission_context = None
                _defer_public_acquisition(job_id, WORKER_ID, fence)
                return True
            lease_renewer = FencedLeaseRenewer(
                SessionLocal, job_id, WORKER_ID, fence, lease_expiry
            ).start()
            if kind == "ingestion":
                with SessionLocal.begin() as session:
                    source = session.get(Source, source_id)
                    if source is not None:
                        source.health = {
                            **source.health,
                            "status": "Running",
                            "last_attempt": datetime.now(UTC).isoformat(),
                        }
        if kind == "intelligence_process":
            if intelligence_task_type == "OCR_EXTRACTION":
                from gridlens.intelligence.scanned_pdf_ocr import process_scanned_pdf_ocr

                process_scanned_pdf_ocr(job_id, WORKER_ID, fence)
                return True
            from gridlens.intelligence.intelligence_jobs import process_intelligence_job

            process_intelligence_job(job_id, WORKER_ID, fence)
            return True
        if kind == "project_monitor":
            from gridlens.intelligence.monitoring import process_monitor_job

            process_monitor_job(job_id, WORKER_ID, fence, enabled=settings.monitoring_enabled)
            return True
        if kind == "rrc_well_research":
            from gridlens.intelligence.rrc_well_research import process_rrc_well_job

            process_rrc_well_job(job_id, WORKER_ID, fence, deadline=deadline)
            return True
        if kind == "signal_adjudication":
            from gridlens.intelligence.signal_adjudication import process_signal_adjudication_job

            process_signal_adjudication_job(job_id, WORKER_ID, fence)
            return True
        if kind == "evidence_shadow":
            from gridlens.intelligence.evidence_shadow import process_evidence_shadow_job

            process_evidence_shadow_job(job_id, WORKER_ID, fence)
            return True
        if kind == "buying_chain_research":
            from gridlens.intelligence.buying_chain import run_buying_chain_research

            run_buying_chain_research(
                job_id,
                WORKER_ID,
                fence,
                deadline=deadline,
                lease_expiry=lease_expiry,
            )
            return True
        if kind == "company_contact_discovery":
            from gridlens.intelligence.company_contact_discovery import (
                process_company_contact_discovery,
            )

            if not settings.company_contact_discovery_enabled:
                # An explicitly disabled provider/network policy is an unresolved
                # outcome, not a failed ingestion and never removes prior claims.
                with SessionLocal.begin() as session:
                    disabled = assert_fence(session, job_id, WORKER_ID, fence)
                    checkpoint = json.loads(disabled.checkpoint or "{}")
                    checkpoint.update(
                        status="unresolved",
                        reason="discovery_disabled",
                        completed_at=datetime.now(UTC).isoformat(),
                    )
                    disabled.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                    disabled.status, disabled.error, disabled.lease_owner, disabled.lease_until = (
                        "succeeded",
                        None,
                        None,
                        None,
                    )
                return True
            process_company_contact_discovery(job_id, WORKER_ID, fence, deadline=deadline)
            return True
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
        if kind == "power_need_title":
            from gridlens.intelligence.titles import process_title_job

            try:
                process_title_job(job_id, WORKER_ID, fence)
            except Exception as exc:
                with SessionLocal.begin() as session:
                    failed = session.get(Job, job_id)
                    if (
                        failed
                        and failed.status == "running"
                        and failed.lease_owner == WORKER_ID
                        and failed.fence == fence
                    ):
                        from gridlens.persistence.models import PowerNeedTitle

                        title = (
                            session.get(PowerNeedTitle, failed.target_id)
                            if failed.target_id
                            else None
                        )
                        if title and title.status == "pending":
                            title.status, title.error = "failed", "worker_failed"
                        failed.status, failed.error = "failed", type(exc).__name__
                        failed.lease_owner = failed.lease_until = None
            return True
        with SessionLocal() as session:
            if deadline is not None:
                session.info["browse_publication_deadline"] = deadline
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
                _release_admission(admission_context)
                admission_context = None
                return True
            if definition is None:
                _park_if_disabled(session, finished_job, source, None)
                session.commit()
                _release_admission(admission_context)
                admission_context = None
                return True
            if _park_if_disabled(session, finished_job, source, definition):
                session.commit()
                _release_admission(admission_context)
                admission_context = None
                return True
            collection_jobs_remaining = None
            if definition.get("retrieval_method") in {
                "socrata-permits",
                "boston-ckan-permits",
                "rrc-flare-exceptions",
                "rrc-drilling-permits",
            }:
                # Validate within the worker failure boundary, before acquisition.
                # Capture once: service checkpoints must never reset this chain.
                job_checkpoint = _collection_checkpoint(finished_job.checkpoint, job_checkpoint)
                collection_jobs_remaining = _collection_jobs_remaining(job_checkpoint)
                assert isinstance(job_checkpoint, dict)
                finished_job.checkpoint = json.dumps(
                    {**job_checkpoint, "collection_jobs_remaining": collection_jobs_remaining},
                    sort_keys=True,
                )
            # The dispatch advisory lock serializes this source without keeping
            # the Source row lock or a database transaction across provider HTTP.
            session.commit()
            session.expire_all()
            acquisition_started_at = session.scalar(text("SELECT clock_timestamp()"))
            counts = process_job(
                session,
                job_id,
                WORKER_ID,
                fence,
                definition,
                deadline=deadline,
                lease_expiry=lease_expiry,
            )
            # Commit retained ingestion/admission work, then reacquire fresh rows
            # before recording health so operator changes during retrieval win.
            session.commit()
            acquisition_completed_at = session.scalar(text("SELECT clock_timestamp()"))
            session.expire_all()
            source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
            finished_job = session.get(Job, job_id)
            if source is None or finished_job is None:
                raise RuntimeError("Ingestion source disappeared after processing")
            assert finished_job and source
            assert_fence(session, job_id, WORKER_ID, fence)
            try:
                current_definition = next(
                    (item for item in load_registry() if item["id"] == source_id), None
                )
            except Exception as exc:
                _defer_registry_unavailable(finished_job, source, exc)
                session.commit()
                _release_admission(admission_context)
                admission_context = None
                return True
            if current_definition is None:
                _park_if_disabled(session, finished_job, source, None)
                session.commit()
                _release_admission(admission_context)
                admission_context = None
                return True
            if _park_if_disabled(session, finished_job, source, current_definition):
                session.commit()
                _release_admission(admission_context)
                admission_context = None
                return True
            definition = current_definition
            if collection_jobs_remaining is not None:
                remaining = collection_jobs_remaining - 1
                needs_continuation = bool(counts.get("collection_continuation"))
                paused = needs_continuation and remaining == 0
                counts.update(
                    collection_jobs_remaining=remaining,
                    collection_paused_for_budget=paused,
                    collection_continuation=needs_continuation and remaining > 0,
                )
                if paused:
                    counts.update(collection_status="PARTIAL", partial=True)
            (
                finished_job.status,
                finished_job.lease_until,
                finished_job.lease_owner,
                finished_job.error,
            ) = "succeeded", None, None, None
            if counts.get("collection_status") == "PARTIAL":
                rate_limited = counts.get("source_rate_limited") is True
                retry_after_seconds = counts.get("source_retry_after_seconds")
                retry_after_exceeds_bound = counts.get("source_retry_after_exceeds_bound") is True
                retry_after_deadline = _retry_after_deadline(counts.get("source_retry_after_at"))
                retry_after_unrepresentable = (
                    counts.get("source_retry_after_unrepresentable") is True
                )
                throttle_status = counts.get("source_http_status", 429)
                retry_at = None
                if (
                    rate_limited
                    and not retry_after_unrepresentable
                    and not (retry_after_exceeds_bound and retry_after_deadline is None)
                ):
                    from gridlens.jobs.retry import jittered_delay_seconds

                    delay_seconds = jittered_delay_seconds(
                        str(finished_job.id),
                        finished_job.attempts,
                        min(3600, 30 * (2**finished_job.attempts)),
                        ceiling_seconds=3600,
                    )
                    if type(retry_after_seconds) is int:
                        delay_seconds = max(delay_seconds, retry_after_seconds)
                    retry_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                    if retry_after_deadline is not None:
                        retry_at = max(retry_at, retry_after_deadline)
                source.health = {
                    **source.health,
                    "status": "Partial",
                    "last_attempt": attempted,
                    "new_records": counts.get("new", 0),
                    "changed_records": counts.get("changed", 0),
                    "unchanged_records": counts.get("unchanged", 0),
                    **{
                        key: counts[key]
                        for key in (
                            "retrieved_records",
                            "parsed_records",
                            "records_scanned",
                            "permit_accepted",
                            "permit_rejected",
                        )
                        if key in counts
                    },
                    "parse_failures": max(
                        int(source.health.get("parse_failures", 0)),
                        int(counts.get("parse_failures", 0)),
                    ),
                    "error": (
                        "Publisher rate limit; remaining documents deferred"
                        if rate_limited
                        else counts.get("collection_error_class") or "Collection incomplete"
                    ),
                    "error_code": f"http_status_{throttle_status}"
                    if rate_limited
                    else counts.get("collection_error_code"),
                    "error_stage": counts.get("collection_error_stage"),
                    "http_status": throttle_status
                    if rate_limited
                    else counts.get("collection_http_status"),
                    "retry_class": "TRANSIENT"
                    if rate_limited
                    else source.health.get("retry_class"),
                    "retry_at": retry_at.isoformat()
                    if rate_limited and retry_at
                    else None
                    if rate_limited
                    else source.health.get("retry_at"),
                    "retry_state": (
                        "retry_after_unrepresentable"
                        if rate_limited and retry_after_unrepresentable
                        else "scheduled"
                        if rate_limited and retry_at is not None
                        else "terminal"
                        if rate_limited
                        else source.health.get("retry_state", "not_scheduled")
                    ),
                    "collection_status": "PARTIAL",
                    "collection_lane": counts.get("collection_lane"),
                    "collection_current_complete": counts.get("collection_current_complete", False),
                    "collection_window_start": counts.get("collection_window_start"),
                    "collection_window_end": counts.get("collection_window_end"),
                    "collection_scope": definition.get("collection_scope"),
                    "coverage_limitation": definition.get("coverage_limitation"),
                }
            else:
                source.health = {
                    **source.health,
                    "status": "Updated"
                    if counts["new"] or counts["changed"]
                    else "Checked—No Change",
                    "last_attempt": attempted,
                    "last_success": attempted,
                    "last_meaningful_update": (
                        attempted
                        if counts["new"] or counts["changed"]
                        else source.health.get("last_meaningful_update")
                    ),
                    "new_records": counts["new"],
                    "changed_records": counts["changed"],
                    "unchanged_records": counts["unchanged"],
                    "parse_failures": 0,
                    "retry_class": None,
                    "retry_at": None,
                    "retry_state": "not_scheduled",
                    "error": None,
                    "error_code": None,
                    "error_stage": None,
                    "http_status": None,
                    "latest_publication_date": counts["latest_publication_date"],
                    "collection_status": counts.get("collection_status"),
                    "collection_current_complete": counts.get("collection_current_complete", True),
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
                if not counts.get("partial"):
                    source.health = {
                        **source.health,
                        "last_success_counts": {
                            key: int(counts.get(source_key, 0) or 0)
                            for key, source_key in (
                                ("retrieved_records", "retrieved_records"),
                                ("parsed_records", "parsed_records"),
                                ("records_scanned", "records_scanned"),
                                ("new_records", "new"),
                                ("changed_records", "changed"),
                                ("unchanged_records", "unchanged"),
                                ("permit_accepted", "permit_accepted"),
                                ("permit_rejected", "permit_rejected"),
                            )
                        },
                    }
            if collection_jobs_remaining is not None:
                source.health = {
                    **source.health,
                    "collection_jobs_remaining": counts["collection_jobs_remaining"],
                    "collection_paused_for_budget": counts["collection_paused_for_budget"],
                }
                if counts["collection_paused_for_budget"]:
                    source.health = {
                        **source.health,
                        "error": "Collection paused at chain job budget",
                    }
            if counts.get("attempt_processed", counts.get("retrieved_records", 0)) > 0:
                source.health = {
                    **source.health,
                    "last_valid_record_at": acquisition_completed_at.isoformat(),
                }
            if counts.get("new", 0) or counts.get("changed", 0):
                source.health = {
                    **source.health,
                    "last_meaningful_update": acquisition_completed_at.isoformat(),
                }
            source.health = {
                **source.health,
                "records_rejected": counts.get("attempt_rejected", 0),
                "attempt_fetched": counts.get(
                    "attempt_fetched", counts.get("retrieved_records", 0)
                ),
                "attempt_processed": counts.get(
                    "attempt_processed", counts.get("parsed_records", 0)
                ),
                "attempt_rejected": counts.get("attempt_rejected", 0),
                "attempt_duplicate": counts.get("attempt_duplicate", 0),
                "attempt_new": counts.get("new", 0),
                "attempt_changed": counts.get("changed", 0),
                "regional_held": counts.get("regional_held", 0),
                "regional_excluded": counts.get("regional_excluded", 0),
                "last_rejected_records": counts.get("rejected_records", [])[:50],
                "retry_state": source.health.get("retry_state", "not_scheduled")
                if counts.get("source_rate_limited") is True
                else "not_scheduled",
                "retry_at": source.health.get("retry_at")
                if counts.get("source_rate_limited") is True
                else None,
                "attempts": finished_job.attempts,
                "attempt_metrics_status": "KNOWN",
                "processing_error": None,
            }
            disposition = (
                "partial" if counts.get("parse_failures") or counts.get("partial") else "succeeded"
            )
            counts = {
                **counts,
                "schedule_proof_version": SCHEDULE_PROOF_VERSION,
                "acquisition_started_at": counts.get("acquisition_started_at")
                or (acquisition_started_at.isoformat() if acquisition_started_at else None),
                "acquisition_completed_at": counts.get("acquisition_completed_at")
                or acquisition_completed_at.isoformat(),
            }
            if counts.get("rejected_records"):
                try:
                    checkpoint_value = json.loads(finished_job.checkpoint or "null")
                except (TypeError, ValueError):
                    checkpoint_value = None
                if isinstance(checkpoint_value, dict):
                    checkpoint_payload = checkpoint_value
                elif (
                    finished_job.checkpoint
                    and len(finished_job.checkpoint) <= 128
                    and re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9_-]*(?: [A-Za-z0-9_-]+)*",
                        finished_job.checkpoint,
                    )
                ):
                    checkpoint_payload = {"last_record_external_id": finished_job.checkpoint}
                else:
                    checkpoint_payload = None
                if checkpoint_payload is not None:
                    checkpoint_payload["last_acquisition_rejections"] = counts["rejected_records"][
                        :50
                    ]
                    serialized_checkpoint = json.dumps(
                        checkpoint_payload, sort_keys=True, separators=(",", ":")
                    )
                    if len(serialized_checkpoint.encode("utf-8")) <= 8_000_000:
                        finished_job.checkpoint = serialized_checkpoint
            _append_attempt_receipt(session, finished_job, fence, disposition, counts)
            if kind == "ingestion" and counts.get("collection_continuation"):
                from gridlens.jobs.queue import enqueue

                continuation_id = enqueue(session, source_id)
                if continuation_id != job_id:
                    continuation_job = session.scalar(
                        select(Job).where(Job.id == continuation_id).with_for_update()
                    )
                    if continuation_job and continuation_job.status == "queued":
                        try:
                            checkpoint = json.loads(continuation_job.checkpoint or "{}")
                        except (TypeError, ValueError) as exc:
                            raise ValueError("Invalid structured collection job budget") from exc
                        successor_remaining = min(
                            counts["collection_jobs_remaining"],
                            _collection_jobs_remaining(checkpoint),
                        )
                        continuation_job.checkpoint = json.dumps(
                            {
                                **checkpoint,
                                "collection_continuation": True,
                                "collection_jobs_remaining": successor_remaining,
                            },
                            sort_keys=True,
                        )
            if not counts.get("partial") and source_id in {
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
            _release_admission(admission_context)
            admission_context = None
    except Exception as exc:
        diagnostics = acquisition_diagnostics(exc) if kind == "ingestion" else {}
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
                retry_class = (
                    _acquisition_retry_class(exc, diagnostics)
                    if kind == "ingestion"
                    else "BOUNDED_UNKNOWN"
                )
                should_retry = retry_class != "PERMANENT" and failed_job.attempts < 5
                failed_job.status = "queued" if should_retry else "failed"
                from gridlens.jobs.retry import jittered_delay_seconds

                retry_at = None
                retry_after_seconds = diagnostics.get("retry_after_seconds")
                retry_after_deadline = _retry_after_deadline(diagnostics.get("retry_after_at"))
                retry_after_unrepresentable = diagnostics.get("retry_after_unrepresentable") == 1
                source_retry_at = retry_after_deadline
                if should_retry:
                    delay_seconds = jittered_delay_seconds(
                        str(failed_job.id),
                        failed_job.attempts,
                        min(3600, 30 * (2**failed_job.attempts)),
                        ceiling_seconds=3600,
                    )
                    if type(retry_after_seconds) is int:
                        delay_seconds = max(delay_seconds, retry_after_seconds)
                    retry_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                    if retry_after_deadline is not None:
                        retry_at = max(retry_at, retry_after_deadline)
                    failed_job.available_at = retry_at
                    source_retry_at = retry_at
                failed_job.lease_until, failed_job.lease_owner = None, None
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                failed_job.error = (
                    acquisition_error_message(exc)
                    if kind == "ingestion"
                    else str(exc)[:250]
                    if isinstance(exc, SourceParseError)
                    else type(exc).__name__
                )
                if kind == "ingestion":
                    from gridlens.ingestion.adapters.federal_register import SourceParseError

                    _append_attempt_receipt(
                        session,
                        failed_job,
                        fence,
                        "failed" if not should_retry else "unknown",
                        {
                            "error_class": type(exc).__name__,
                            "retry_class": retry_class,
                            **diagnostics,
                        },
                    )
            if source and valid_owner and kind == "ingestion":
                from gridlens.ingestion.adapters.federal_register import SourceParseError

                is_parse_error = isinstance(exc, SourceParseError)
                prior_health = source.health if isinstance(source.health, dict) else {}
                prior_success_counts = prior_health.get("last_success_counts")
                if not isinstance(prior_success_counts, dict):
                    prior_success_counts = {
                        key: prior_health[key]
                        for key in (
                            "retrieved_records",
                            "parsed_records",
                            "records_scanned",
                            "new_records",
                            "changed_records",
                            "unchanged_records",
                            "permit_accepted",
                            "permit_rejected",
                        )
                        if type(prior_health.get(key)) is int
                    }
                source.health = {
                    **prior_health,
                    "status": "Failed",
                    "last_attempt": attempted,
                    "parse_failures": int(source.health.get("parse_failures", 0))
                    + int(is_parse_error),
                    "error": acquisition_error_message(exc),
                    "error_code": None,
                    "error_stage": None,
                    "http_status": None,
                    "retry_class": retry_class,
                    "retry_at": source_retry_at.isoformat() if source_retry_at else None,
                    "retry_state": (
                        "retry_after_unrepresentable"
                        if retry_after_unrepresentable
                        else "scheduled"
                        if source_retry_at is not None and not retry_after_unrepresentable
                        else "terminal"
                    ),
                    "attempt_fetched": None,
                    "attempt_processed": None,
                    "attempt_rejected": None,
                    "attempt_new": None,
                    "attempt_changed": None,
                    "records_rejected": None,
                    "last_rejected_records": [],
                    "retrieved_records": 0,
                    "parsed_records": 0,
                    "records_scanned": 0,
                    "new_records": 0,
                    "changed_records": 0,
                    "unchanged_records": 0,
                    "permit_accepted": 0,
                    "permit_rejected": 0,
                    "regional_held": 0,
                    "regional_excluded": 0,
                    "last_success_counts": prior_success_counts,
                    "attempt_metrics_status": "UNKNOWN",
                    "processing_error": type(exc).__name__,
                    "attempts": failed_job.attempts if failed_job else None,
                    **diagnostics,
                }
    finally:
        if admission_context is not None:
            try:
                _release_admission(admission_context)
            except Exception:
                logger.exception("Failed to release public acquisition admission")
        if lease_renewer is not None:
            lease_renewer.stop()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from gridlens.intelligence.worker_browse import install_worker_publication

    install_worker_publication(SessionLocal)
    definitions = {row["id"]: row for row in load_registry()}
    stop_event = threading.Event()

    def request_shutdown(_signum, _frame) -> None:
        logger.info("worker shutdown requested")
        stop_event.set()

    previous_handlers = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        _run_worker_lanes(stop_event, definitions)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _worker_lane_specs(
    stop_event: threading.Event, definitions: dict[str, dict]
) -> list[tuple[str, Callable[..., None], tuple[object, ...]]]:
    lanes: list[tuple[str, Callable[..., None], tuple[object, ...]]] = [
        ("gridlens-heartbeat", _heartbeat_lane, (stop_event,)),
        ("gridlens-job-execution", _job_execution_lane, (stop_event, definitions)),
    ]
    if settings.worker_auto_refresh:
        lanes.append(
            ("gridlens-planner-sources", _planner_lane, (stop_event, "sources", refresh_due))
        )
        if settings.autonomous_research_enabled:
            lanes.append(
                (
                    "gridlens-planner-pursuit-questions",
                    _planner_lane,
                    (stop_event, "pursuit_questions", plan_pursuit_questions),
                )
            )
        if settings.company_contact_discovery_enabled:
            lanes.append(
                (
                    "gridlens-planner-company-contacts",
                    _planner_lane,
                    (stop_event, "company_contacts", plan_company_contact_jobs),
                )
            )
        if settings.rrc_well_research_enabled:
            lanes.append(
                (
                    "gridlens-planner-rrc-wells",
                    _planner_lane,
                    (stop_event, "rrc_wells", plan_rrc_well_jobs),
                )
            )
    if settings.monitoring_enabled:
        lanes.append(
            (
                "gridlens-planner-project-monitoring",
                _planner_lane,
                (stop_event, "project_monitoring", plan_monitoring_jobs),
            )
        )
    return lanes


def _run_worker_lanes(stop_event: threading.Event, definitions: dict[str, dict]) -> None:
    """Run fixed scheduler lanes and stop/join them within a finite bound."""
    threads = [
        threading.Thread(name=name, target=target, args=args, daemon=True)
        for name, target, args in _worker_lane_specs(stop_event, definitions)
    ]
    try:
        for thread in threads:
            thread.start()
        stop_event.wait()
    finally:
        stop_event.set()
        deadline = time.monotonic() + _SHUTDOWN_JOIN_SECONDS
        for thread in threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
            if thread.is_alive():
                logger.warning("worker lane %s did not stop before the shutdown bound", thread.name)


def _heartbeat_lane(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            with SessionLocal.begin() as session:
                heartbeat = session.get(WorkerHeartbeat, WORKER_ID)
                now = datetime.now(UTC)
                if heartbeat is None:
                    session.add(WorkerHeartbeat(worker_id=WORKER_ID, last_seen_at=now))
                else:
                    heartbeat.last_seen_at = now
        except Exception:
            logger.exception("worker heartbeat update failed")
        if stop_event.wait(_HEARTBEAT_INTERVAL_SECONDS):
            return


def _planner_lane(
    stop_event: threading.Event, planner_key: str, action: Callable[[], object]
) -> None:
    while not stop_event.is_set():
        try:
            _run_planner(planner_key, action)
        except Exception:
            # Last-resort containment: one unexpected planner or connection
            # cleanup error must not retire this scheduler lane until restart.
            logger.exception("planner lane %s cycle escaped its retry boundary", planner_key)
        if stop_event.wait(_PLANNER_POLL_SECONDS):
            return


def _job_execution_lane(stop_event: threading.Event, definitions: dict[str, dict]) -> None:
    while not stop_event.is_set():
        try:
            did_work = run_one(definitions)
        except Exception:
            logger.exception("worker job execution failed")
            did_work = False
        if not did_work and stop_event.wait(_IDLE_JOB_POLL_SECONDS):
            return


def _run_planner(planner_key: str, action) -> bool:
    now = datetime.now(UTC)
    if time.monotonic() < _PLANNER_RETRY_MONOTONIC.get(planner_key, 0):
        return False
    # A worker deployment may have several replicas. Keep the planner claim on
    # a dedicated PostgreSQL session for the full action so only one replica
    # runs a planner cycle at a time. Session advisory locks need explicit
    # release before returning a pooled connection.
    claim_connection = None
    claimed_lock = False
    cleanup_ok = True
    try:
        claim_connection = _connect_planner_claim()
        claimed = claim_connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:planner_key, 0))"),
            {"planner_key": f"gridlens:planner:{planner_key}"},
        )
        if not claimed:
            return False
        claimed_lock = True
        # End the claim query's transaction but retain the session-level lock;
        # this avoids holding a read snapshot open during a long planner run.
        claim_connection.commit()
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
            state.next_retry_at = now + _PLANNER_SUCCESS_INTERVAL
            state.error_class = None
        _PLANNER_RETRY_MONOTONIC.pop(planner_key, None)
        _PLANNER_FAILURES.pop(planner_key, None)
    except Exception as exc:
        logger.exception(
            "planner %s failed; retry state will control the next attempt", planner_key
        )
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
    finally:
        cleanup_ok = _release_planner_claim(claim_connection, planner_key, claimed_lock)
    return cleanup_ok


def _connect_planner_claim():
    engine = SessionLocal.kw.get("bind")
    if engine is None:
        raise RuntimeError("Planner claim requires a bound database engine")
    return engine.connect()


def _release_planner_claim(connection, planner_key: str, claimed_lock: bool) -> bool:
    """Release a planner lock without allowing cleanup faults to kill its lane."""
    if connection is None:
        return True
    cleanup_ok = True
    try:
        if connection.in_transaction():
            connection.rollback()
    except Exception:
        cleanup_ok = False
        logger.exception("failed to roll back planner %s claim connection", planner_key)
        try:
            connection.invalidate()
        except Exception:
            logger.exception("failed to invalidate planner %s claim connection", planner_key)
    if claimed_lock and cleanup_ok:
        try:
            released = connection.scalar(
                text("SELECT pg_advisory_unlock(hashtextextended(:planner_key, 0))"),
                {"planner_key": f"gridlens:planner:{planner_key}"},
            )
            connection.commit()
            if not released:
                cleanup_ok = False
                logger.error("planner %s claim was not held at release", planner_key)
        except Exception:
            cleanup_ok = False
            logger.exception("failed to release planner %s claim", planner_key)
            try:
                connection.invalidate()
            except Exception:
                logger.exception("failed to invalidate planner %s claim connection", planner_key)
    try:
        connection.close()
    except Exception:
        cleanup_ok = False
        logger.exception("failed to close planner %s claim connection", planner_key)
        try:
            connection.invalidate()
        except Exception:
            logger.exception("failed to invalidate planner %s claim connection", planner_key)
    return cleanup_ok


def plan_pursuit_questions() -> int:
    if not settings.autonomous_research_enabled:
        return 0
    from gridlens.intelligence.autonomous_research import planning_cards
    from gridlens.intelligence.pursuit_questions import schedule_questions

    cards = planning_cards()
    with SessionLocal.begin() as session:
        return len(schedule_questions(session, cards, grouped=True))


def plan_company_contact_jobs() -> int:
    if not settings.company_contact_discovery_enabled:
        return 0
    from gridlens.intelligence.company_contact_discovery import plan_company_contact_jobs as plan

    with SessionLocal.begin() as session:
        return plan(session)


def plan_rrc_well_jobs() -> int:
    if not settings.rrc_well_research_enabled:
        return 0
    from gridlens.intelligence.rrc_well_research import plan_rrc_well_jobs as plan

    with SessionLocal.begin() as session:
        return plan(session)


def plan_monitoring_jobs() -> int:
    """Plan explicitly configured watches independently of source auto-refresh."""
    if not settings.monitoring_enabled:
        return 0
    from gridlens.intelligence.monitoring import plan_monitoring

    with SessionLocal.begin() as session:
        return len(
            plan_monitoring(
                session,
                enabled=True,
                limit=settings.monitoring_plan_batch_limit,
                max_active_jobs=settings.monitoring_max_active_jobs,
                max_active_per_host=settings.monitoring_max_active_per_host,
                max_active_per_source=settings.monitoring_max_active_per_source,
            )
        )


if __name__ == "__main__":
    main()
