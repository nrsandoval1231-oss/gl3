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

from sqlalchemy.orm import Session

from gridlens.persistence.models import Source

HEALTH_KEY = "document_stage"
MAX_RUNS = 60
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
    summary: dict[str, Any] = {
        "at": at.astimezone(UTC).isoformat(),
        "mode": mode,
        **{
            key: _int(counts.get(key))
            for key in (
                "in_scope",
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


def record_run(session: Session, source_id: str, summary: dict[str, Any]) -> None:
    """Append ``summary`` to the source's bounded run history (caller commits)."""
    source = session.get(Source, source_id)
    if source is None:
        return
    health = dict(source.health or {})
    block = health.get(HEALTH_KEY)
    runs = list(block.get("runs", [])) if isinstance(block, dict) else []
    runs.append(summary)
    health[HEALTH_KEY] = {"runs": runs[-MAX_RUNS:]}
    source.health = health
