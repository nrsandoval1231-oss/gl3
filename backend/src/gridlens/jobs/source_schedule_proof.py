"""Pure validation for digest-bound scheduled source success receipts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEDULE_PROOF_VERSION = 1


def receipt_digest_valid(check_counts: Any, digest: str) -> bool:
    try:
        canonical = json.dumps(check_counts, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return False
    return hashlib.sha256(canonical.encode()).hexdigest() == digest


def verified_schedule_success(
    *,
    due: Any,
    receipt: Any,
    job: Any,
    next_scheduled_for: datetime | None,
) -> bool:
    """Check association, fence, digest and real acquisition interval timestamps."""
    if not (
        due
        and receipt
        and job
        and receipt.disposition == "succeeded"
        and job.status == "succeeded"
        and job.kind == "ingestion"
        and job.source_id == due.source_id
        and due.job_id == job.id == receipt.job_id
        and receipt.due_key == due.due_key
        and receipt.fence == job.fence
        and job.fence >= 1
        and job.lease_owner is None
        and job.lease_until is None
        and receipt_digest_valid(receipt.check_counts, receipt.digest)
    ):
        return False
    counts = receipt.check_counts
    if (
        not isinstance(counts, dict)
        or counts.get("schedule_proof_version") != SCHEDULE_PROOF_VERSION
    ):
        return False
    if any(
        type(counts.get(field)) is not int or counts[field] < 0
        for field in ("new", "changed", "unchanged")
    ):
        return False
    timestamps: list[datetime] = []
    try:
        for key in ("acquisition_started_at", "acquisition_completed_at"):
            value = datetime.fromisoformat(counts[key])
            if value.tzinfo is None or value.utcoffset() is None:
                return False
            timestamps.append(value.astimezone(UTC))
        scheduled = due.scheduled_for
        recorded = receipt.recorded_at
        if scheduled.tzinfo is None or recorded.tzinfo is None:
            return False
        scheduled, recorded = scheduled.astimezone(UTC), recorded.astimezone(UTC)
        started, completed = timestamps
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False
    if next_scheduled_for is None:
        return False
    if next_scheduled_for.tzinfo is None or next_scheduled_for.utcoffset() is None:
        return False
    next_due = next_scheduled_for.astimezone(UTC)
    return scheduled <= started <= completed <= recorded < next_due
