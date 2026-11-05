"""Durable monthly archive segments for bounded RRC drilling catch-up."""

from __future__ import annotations

import hashlib
import json
import time
from calendar import monthrange
from datetime import date
from typing import Any

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_drilling import (
    MONTHLY_PORTAL,
    PORTAL,
    SOURCE_ID,
    _download_listing_file,
    parse_snapshot,
    records_from_snapshots,
    retrieve,
    source_today,
)

MAX_SEGMENT_DAYS = 31
MAX_RECORDS_PER_SEGMENT = 1000


def _month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=monthrange(day.year, day.month)[1])


def _page(records: list[dict[str, Any]], cursor: dict[str, Any], digest: str):
    if cursor and set(cursor) != {"archive_sha256", "offset"}:
        raise SourceParseError("RRC drilling cursor must bind an offset to a snapshot digest")
    offset = cursor.get("offset", 0)
    if type(offset) is not int or offset < 0:
        raise SourceParseError("RRC drilling history cursor offset is invalid")
    if cursor.get("archive_sha256", digest) != digest:
        return None
    if offset > len(records):
        raise SourceParseError("RRC drilling cursor exceeds snapshot record count")
    batch = records[offset : offset + MAX_RECORDS_PER_SEGMENT]
    next_offset = offset + len(batch)
    complete = next_offset >= len(records)
    next_cursor = {} if complete else {"archive_sha256": digest, "offset": next_offset}
    return batch, next_cursor, complete


def retrieve_collection_segment(
    source: dict[str, Any],
    lane: str,
    start: date,
    end: date,
    cursor: dict[str, Any],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one bounded segment; history is exactly one official month archive.

    A monthly archive is a snapshot of records then known, not an authoritative
    complete current-state listing. Callers must not reconcile departures from it.
    """
    if (
        source.get("id") != SOURCE_ID
        or source.get("endpoint") != PORTAL
        or lane not in {"issue_recent", "issue_history"}
        or not isinstance(cursor, dict)
        or start > end
        or (end - start).days >= MAX_SEGMENT_DAYS
    ):
        raise SourceParseError("Invalid RRC drilling collection segment")
    if lane == "issue_recent":
        records = retrieve(source, client)
        digest = hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        page = _page(records, cursor, digest)
        if page is None:
            return {
                "records": [],
                "cursor": {},
                "partial": True,
                "window_complete": False,
                "error_class": "RrcSnapshotChanged",
                "historical_snapshot": False,
            }
        batch, next_cursor, complete = page
        return {
            "records": batch,
            "cursor": next_cursor,
            "partial": False,
            "window_complete": complete,
            "expected_count": len(records),
            "observed_count": len(batch),
            "historical_snapshot": False,
        }
    else:
        if set(cursor) - {"archive_sha256", "offset"}:
            raise SourceParseError("RRC drilling history cursor has unknown fields")
        month_start, month_end = _month_bounds(start)
        if start != month_start or end != month_end:
            raise SourceParseError("RRC drilling history segment must cover one full month")
        today = source_today()
        if end >= today.replace(day=1):
            raise SourceParseError("RRC drilling history segment is not a closed month")
        filename = "daf420.dat." + month_end.strftime("%m-%d-%Y")
        http = client or httpx.Client(timeout=20, follow_redirects=False)
        try:
            body, _modified = _download_listing_file(
                http,
                MONTHLY_PORTAL,
                filename,
                today,
                time.monotonic() + 120,
                archive_date=month_end,
            )
            snapshot = parse_snapshot(
                body, filename=filename, today=today, source_url=MONTHLY_PORTAL
            )
            records = records_from_snapshots([snapshot])
            archive_digest = hashlib.sha256(body).hexdigest()
            page = _page(records, cursor, archive_digest)
            if page is None:
                return {
                    "records": [],
                    "cursor": {},
                    "partial": True,
                    "window_complete": False,
                    "error_class": "RrcSnapshotChanged",
                    "historical_snapshot": True,
                }
            batch, next_cursor, complete = page
        finally:
            if client is None:
                http.close()
        expected_count = len(records)
        records = batch
        return {
            "records": records,
            "cursor": next_cursor,
            "partial": False,
            "window_complete": complete,
            "expected_count": expected_count,
            "observed_count": len(records),
            "historical_snapshot": True,
        }
