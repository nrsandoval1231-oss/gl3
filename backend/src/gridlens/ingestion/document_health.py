"""Compact per-run summaries of the document stages, kept in source health for alerting.

Each listing run (in-line or discovery) and each extraction job appends one small summary to
``Source.health["document_stage"]["runs"]`` (bounded). The daily alert (``jobs/document_alerts.py``)
reads only these summaries and ``Observation.first_seen_at``; nothing here changes evidence,
hashes or collection status. Codes and small integers only: exception text and response content
are untrusted and never stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.persistence.models import Source

HEALTH_KEY = "document_stage"
MAX_RUNS_PER_MODE = 30  # listing (inline/discovery) and job runs are capped separately
MAX_CODES = 20


def _int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def summarize_states(states: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Extraction metrics over the document states produced (fetched) in one run."""
    out: dict[str, Any] = {
        "docs": 0,
        "pages": 0,
        "scanned_pages": 0,
        "empty_text_docs": 0,
        "verified_rows": 0,
        "rejected_rows": 0,
        "proposer": {},
        "ocr": {},
    }
    for state in states:
        document = state.get("document") if isinstance(state, dict) else None
        extraction = document.get("extraction") if isinstance(document, dict) else None
        if not isinstance(extraction, dict):
            continue
        out["docs"] += 1
        pages, scanned = _int(extraction.get("pages")), _int(extraction.get("scanned_pages"))
        out["pages"] += pages
        out["scanned_pages"] += scanned
        out["empty_text_docs"] += int(bool(pages) and scanned >= pages)
        out["verified_rows"] += _int(extraction.get("verified_rows"))
        out["rejected_rows"] += _int(extraction.get("rejected_rows"))
        for name in ("proposer", "ocr"):
            detail = extraction.get(name)
            status = detail.get("status") if isinstance(detail, dict) else None
            if isinstance(status, str):
                bucket = out[name]
                bucket[status[:30]] = bucket.get(status[:30], 0) + 1
    return out


def build_run_summary(
    mode: str, counts: dict[str, int], states: Iterable[dict[str, Any]], *, at: datetime
) -> dict[str, Any]:
    """One run: stage counters (``failure_*`` / ``notice_*`` split out) plus state metrics."""
    failures = {
        key.removeprefix("failure_")[:40]: _int(value)
        for key, value in counts.items()
        if key.startswith("failure_")
    }
    notices = {
        key.removeprefix("notice_")[:40]: _int(value)
        for key, value in counts.items()
        if key.startswith("notice_")
    }
    # A single-document job has no listing: it reports no in_scope rather than 0.
    listing_keys = () if mode == "document_extraction" else ("in_scope",)
    summary: dict[str, Any] = {
        "at": at.astimezone(UTC).isoformat(),
        "mode": mode,
        **{
            key: _int(counts.get(key))
            for key in (
                *listing_keys,
                "checked",
                "new",
                "updated",
                "unchanged",
                "unchanged_by_hash",
                "downloads",
                "enqueued",
                "already_queued",
                "deferred_enqueue_budget",
            )
        },
        "failures": dict(list(failures.items())[:MAX_CODES]),
        "notices": dict(list(notices.items())[:MAX_CODES]),
        **summarize_states(states),
    }
    return summary


def locked_source(session: Session, source_id: str) -> Source | None:
    """The source row, locked and refreshed, for a read-modify-write of ``health``.

    Pending changes are flushed first so the refresh cannot discard them.
    """
    session.flush()
    return session.scalar(
        select(Source)
        .where(Source.id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def record_run(session: Session, source_id: str, summary: dict[str, Any]) -> None:
    """Append ``summary`` to the source's bounded run history (caller commits)."""
    source = locked_source(session, source_id)
    if source is None:
        return
    health = dict(source.health or {})
    block = health.get(HEALTH_KEY)
    runs = list(block.get("runs", [])) if isinstance(block, dict) else []
    runs.append(summary)
    kept: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for run in reversed(runs):  # newest first, so the cap drops the oldest of each kind
        kind = "job" if run.get("mode") == "document_extraction" else "listing"
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] <= MAX_RUNS_PER_MODE:
            kept.append(run)
    health[HEALTH_KEY] = {"runs": kept[::-1]}
    source.health = health
