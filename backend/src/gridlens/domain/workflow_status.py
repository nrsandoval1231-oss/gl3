"""Append-only exact-need operator workflow status contract."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

WORKFLOW_STATUSES = frozenset(
    {"New", "Investigating", "Contacted", "Qualified", "Won", "Lost", "Closed"}
)


class StatusEvent(Protocol):
    status: str
    version: int


def status_content_hash(status: str, reason: str) -> str:
    raw = json.dumps(
        {"status": status, "reason": reason.strip()}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def status_view(events: list[StatusEvent]) -> dict[str, object]:
    if not events:
        return {"status": "UNKNOWN", "version": 0, "events": []}
    ordered = sorted(events, key=lambda event: event.version)
    latest = ordered[-1]
    return {"status": latest.status, "version": latest.version, "events": ordered}
