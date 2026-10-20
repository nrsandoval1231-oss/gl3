"""Durable, bounded progress for structured permit source collection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.domain.news_interpretation import EVALUATOR_VERSION
from gridlens.domain.signal_admission import POLICY_VERSION as ADMISSION_POLICY_VERSION
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.socrata_permits import MAPS
from gridlens.persistence.models import SourceCollectionProgress

PARSER_POLICY_VERSION = "structured-permits-resume-v1"
WINDOW_DAYS = 7
MAX_CURSOR_BYTES = 8192


def collection_lanes(source: dict[str, Any]) -> tuple[str, ...]:
    method = source.get("retrieval_method")
    if method == "socrata-permits":
        source_id = source.get("id")
        lanes = ["issue_recent", "issue_history"]
        if isinstance(source_id, str) and MAPS.get(source_id, {}).get("modified_date"):
            lanes.extend(("modified_recent", "modified_history"))
        backfill = (source.get("query") or {}).get("data_center_backfill")
        if source_id == "austin-building-permits" and isinstance(backfill, dict):
            lanes.append("issue_backfill")
        return tuple(lanes)
    if method == "boston-ckan-permits":
        return ("issue_recent", "issue_history")
    return ()


def collection_policy_digest(source: dict[str, Any]) -> str:
    policy = {
        "source_id": source.get("id"),
        "endpoint": source.get("endpoint"),
        "retrieval_method": source.get("retrieval_method"),
        "query": source.get("query"),
        "lane_policy": collection_lanes(source),
        "parser_policy_version": PARSER_POLICY_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }
    payload = json.dumps(policy, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _midnight(day: date) -> datetime:
    # Date-only source fields stay date-only; UTC midnight is only the TIMESTAMPTZ
    # carrier representation and is not asserted to be the source's local zone.
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _date(value: datetime | None) -> date | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(UTC).date()


def _new_window(
    lane: str, today: date, lookback_days: int, source: dict[str, Any]
) -> tuple[date, date]:
    if lane == "issue_backfill":
        backfill = source["query"]["data_center_backfill"]
        start, end = date.fromisoformat(backfill["start"]), date.fromisoformat(backfill["end"])
        return start, min(end, start + timedelta(days=WINDOW_DAYS - 1))
    if lane.endswith("recent"):
        start = today - timedelta(days=WINDOW_DAYS - 1)
    elif lane == "modified_history":
        modified_window = max(1, int(source["query"].get("modified_window_days", 7)))
        start = today - timedelta(days=modified_window - 1)
    else:
        start = today - timedelta(days=max(1, lookback_days) - 1)
    return start, min(today, start + timedelta(days=WINDOW_DAYS - 1))


def _reset_window(
    row: SourceCollectionProgress,
    lane: str,
    today: date,
    lookback: int,
    source: dict[str, Any],
) -> None:
    start, end = _new_window(lane, today, lookback, source)
    row.window_start, row.window_end = _midnight(start), _midnight(end)
    row.cursor = {}
    row.status = "incomplete"
    row.error_class = None


def prepare_collection_progress(
    session: Session, source: dict[str, Any], *, today: date | None = None
) -> tuple[SourceCollectionProgress, str, tuple[str, ...]]:
    """Create/fairly select one current lane and lock it for checkpointing."""
    lanes = collection_lanes(source)
    if not lanes:
        raise SourceParseError("Source has no structured collection lanes")
    source_id = str(source["id"])
    digest = collection_policy_digest(source)
    current_day = today or datetime.now(UTC).date()
    query = source.get("query") or {}
    lookback = int(query.get("window_days", 90))
    rows = session.scalars(
        select(SourceCollectionProgress)
        .where(
            SourceCollectionProgress.source_id == source_id,
            SourceCollectionProgress.policy_digest == digest,
        )
        .order_by(SourceCollectionProgress.lane)
        .with_for_update()
    ).all()
    by_lane = {row.lane: row for row in rows}
    for lane in lanes:
        row = by_lane.get(lane)
        if row is None:
            row = SourceCollectionProgress(
                source_id=source_id,
                lane=lane,
                policy_digest=digest,
                cursor={},
                status="incomplete",
            )
            _reset_window(row, lane, current_day, lookback, source)
            session.add(row)
            by_lane[lane] = row
            continue
        through = _date(row.completed_through)
        if lane.endswith("recent") and row.status == "complete":
            if _date(row.window_end) != current_day:
                _reset_window(row, lane, current_day, lookback, source)
        elif lane.endswith("history") and row.status == "complete":
            if through is not None and through < current_day:
                start = through + timedelta(days=1)
                row.window_start = _midnight(start)
                row.window_end = _midnight(
                    min(current_day, start + timedelta(days=WINDOW_DAYS - 1))
                )
                row.cursor = {}
                row.status = "incomplete"
                row.error_class = None
        elif lane == "issue_backfill" and row.status == "complete":
            backfill_end = date.fromisoformat(query["data_center_backfill"]["end"])
            if through is not None and through < backfill_end:
                start = through + timedelta(days=1)
                row.window_start = _midnight(start)
                row.window_end = _midnight(
                    min(backfill_end, start + timedelta(days=WINDOW_DAYS - 1))
                )
                row.cursor = {}
                row.status = "incomplete"
                row.error_class = None
    session.flush()
    pending = [
        by_lane[lane]
        for lane in lanes
        if by_lane[lane].status in {"incomplete", "partial", "error"}
    ]
    if not pending:
        # A same-day duplicate job repeats the recent lane idempotently; normal
        # schedule planning ensures later days get a fresh rolling overlap.
        lane = "issue_recent"
        row = by_lane[lane]
        _reset_window(row, lane, current_day, lookback, source)
        row.last_attempt_at = None
        pending = [row]
    lane_priority = {name: index for index, name in enumerate(lanes)}
    selected = min(
        pending,
        key=lambda row: (
            row.last_attempt_at or datetime.min.replace(tzinfo=UTC),
            lane_priority[row.lane],
        ),
    )
    if selected.window_start is None or selected.window_end is None:
        raise SourceParseError("Collection progress has no bounded date window")
    selected.last_attempt_at = session.scalar(text("SELECT clock_timestamp()"))
    selected.updated_at = selected.last_attempt_at
    session.flush()
    return selected, digest, lanes


def cursor_bytes(cursor: dict[str, Any]) -> int:
    try:
        return len(
            json.dumps(cursor, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
    except (TypeError, ValueError) as exc:
        raise SourceParseError("Collection cursor is not serializable") from exc


def assert_cursor_bounded(cursor: dict[str, Any]) -> None:
    if cursor_bytes(cursor) > MAX_CURSOR_BYTES:
        raise SourceParseError("Collection cursor exceeds its 8192-byte service bound")


def apply_segment_result(
    progress: SourceCollectionProgress,
    result: dict[str, Any],
    *,
    now: datetime,
) -> None:
    cursor = result.get("cursor", progress.cursor or {})
    if not isinstance(cursor, dict):
        raise SourceParseError("Collection segment returned an invalid cursor")
    assert_cursor_bounded(cursor)
    progress.cursor = cursor
    progress.error_class = result.get("error_class")
    if result.get("partial"):
        progress.status = "partial"
    elif result.get("window_complete"):
        progress.status = "complete"
        progress.completed_through = progress.window_end
        progress.last_completed_at = now
        progress.cursor = {}
    else:
        progress.status = "incomplete"
    progress.updated_at = now


def collection_status(
    session: Session,
    source_id: str,
    digest: str,
    lanes: tuple[str, ...],
    *,
    today: date | None = None,
) -> tuple[bool, bool]:
    """Return (current_overlap_complete, all_lanes_current)."""
    current_day = today or datetime.now(UTC).date()
    rows = session.scalars(
        select(SourceCollectionProgress).where(
            SourceCollectionProgress.source_id == source_id,
            SourceCollectionProgress.policy_digest == digest,
        )
    ).all()
    by_lane = {row.lane: row for row in rows}
    recent = [lane for lane in lanes if lane.endswith("recent")]
    current_complete = bool(recent) and all(
        by_lane.get(lane)
        and by_lane[lane].status == "complete"
        and _date(by_lane[lane].completed_through) == current_day
        for lane in recent
    )
    all_complete = current_complete and all(
        by_lane.get(lane)
        and by_lane[lane].status == "complete"
        and (lane == "issue_backfill" or _date(by_lane[lane].completed_through) == current_day)
        for lane in lanes
    )
    return current_complete, all_complete


def collection_continuation_needed(
    session: Session,
    source_id: str,
    digest: str,
    lanes: tuple[str, ...],
    *,
    source: dict[str, Any],
    today: date | None = None,
) -> bool:
    """Whether another bounded segment can advance a lane without waiting."""
    current_day = today or datetime.now(UTC).date()
    rows = session.scalars(
        select(SourceCollectionProgress).where(
            SourceCollectionProgress.source_id == source_id,
            SourceCollectionProgress.policy_digest == digest,
        )
    ).all()
    by_lane = {row.lane: row for row in rows}
    for lane in lanes:
        row = by_lane.get(lane)
        if row is None or row.status in {"incomplete", "partial", "error"}:
            return True
        through = _date(row.completed_through)
        if lane.endswith("recent") and through != current_day:
            return True
        if lane.endswith("history") and (through is None or through < current_day):
            return True
        if lane == "issue_backfill":
            end = date.fromisoformat(source["query"]["data_center_backfill"]["end"])
            if through is None or through < end:
                return True
    return False
