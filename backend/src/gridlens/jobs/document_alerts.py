"""Typed document-source health findings for the daily owner alert.

Inputs are the bounded per-run summaries in ``Source.health["document_stage"]`` (see
``ingestion/document_health.py``) and ``Observation.first_seen_at``. Every finding has a code,
the source, a plain message and the numbers behind it; nothing is skipped silently. Thresholds
are settings with safe defaults (``DOC_ALERT_*``). Spend near cap is not repeated here: it is
the existing ``spend_report`` in ``jobs/alerts.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from gridlens.settings import settings

WRONG_CONTENT_TYPE = "wrong_content_type"
EMPTY_TEXT_LAYER = "empty_text_layer"
YIELD_DROP = "extraction_yield_drop"
ZERO_NEW_RECORDS = "zero_new_records"
LISTING_SHRINK = "listing_shrink"
OVERDUE = "overdue"
REJECTION_SPIKE = "verifier_rejection_spike"
RECENT_RUNS = 3  # runs that count as "now"; earlier ones are the baseline


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    source_id: str
    message: str
    values: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        return f"Document source {self.source_id}: {self.code} - {self.message}"


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_baseline_docs: int = 5
    yield_drop_ratio: float = 0.5
    empty_text_ratio: float = 0.5
    listing_shrink_ratio: float = 0.5
    zero_new_days: int = 14
    overdue_multiplier: float = 2.5
    rejection_spike_ratio: float = 0.6
    rejection_min_rows: int = 10

    @classmethod
    def from_settings(cls) -> Thresholds:
        return cls(
            min_baseline_docs=settings.doc_alert_min_baseline_docs,
            yield_drop_ratio=settings.doc_alert_yield_drop_ratio,
            empty_text_ratio=settings.doc_alert_empty_text_ratio,
            listing_shrink_ratio=settings.doc_alert_listing_shrink_ratio,
            zero_new_days=settings.doc_alert_zero_new_days,
            overdue_multiplier=settings.doc_alert_overdue_multiplier,
            rejection_spike_ratio=settings.doc_alert_rejection_spike_ratio,
            rejection_min_rows=settings.doc_alert_rejection_min_rows,
        )


def _n(run: dict[str, Any], key: str) -> int:
    value = run.get(key)
    return value if type(value) is int and value >= 0 else 0


def _code_count(run: dict[str, Any], bucket: str, code: str) -> int:
    codes = run.get(bucket)
    return _n(codes, code) if isinstance(codes, dict) else 0


def _split(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(baseline, recent): the last RECENT_RUNS runs that extracted documents are 'recent'."""
    active = [i for i, run in enumerate(runs) if _n(run, "docs") > 0]
    if len(active) <= RECENT_RUNS:
        return [], [runs[i] for i in active]
    cut = active[-RECENT_RUNS]
    return [r for r in runs[:cut] if _n(r, "docs") > 0], [runs[i] for i in active[-RECENT_RUNS:]]


def parse_time(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def evaluate(
    source_id: str,
    runs: list[dict[str, Any]],
    *,
    cadence_hours: int,
    now: datetime,
    thresholds: Thresholds | None = None,
    new_observations_recent: int | None = None,
    observations_total: int = 0,
) -> list[Finding]:
    """Findings for one document source. ``runs`` is oldest-first."""
    limit = thresholds or Thresholds.from_settings()
    findings: list[Finding] = []
    if not runs:
        return findings
    latest = runs[-1]

    wrong = _code_count(latest, "failures", "js_shell") + _code_count(
        latest, "failures", WRONG_CONTENT_TYPE
    )
    if wrong:
        findings.append(
            Finding(
                WRONG_CONTENT_TYPE,
                source_id,
                f"{wrong} document(s) answered with a web page or other non-PDF type in the "
                "latest run (the publisher may have put a script shell in front of the PDFs)",
                {"count": wrong},
            )
        )

    baseline, recent = _split(runs)
    empty_failures = sum(_code_count(r, "failures", EMPTY_TEXT_LAYER) for r in recent)
    # Documents that failed as empty never reach 'docs', so count both in the denominator.
    empty_docs = sum(_n(r, "empty_text_docs") for r in recent) + empty_failures
    attempted = sum(_n(r, "docs") for r in recent) + empty_failures
    if attempted >= 3 and empty_docs / attempted >= limit.empty_text_ratio:
        findings.append(
            Finding(
                EMPTY_TEXT_LAYER,
                source_id,
                f"{empty_docs} of {attempted} recent document(s) have no text layer "
                "(scanned or image-only); no rows can be read without OCR",
                {"empty": empty_docs, "documents": attempted},
            )
        )

    base_docs = sum(_n(r, "docs") for r in baseline)
    recent_docs = sum(_n(r, "docs") for r in recent)
    if base_docs >= limit.min_baseline_docs and recent_docs >= 3:
        base_avg = sum(_n(r, "verified_rows") for r in baseline) / base_docs
        recent_avg = sum(_n(r, "verified_rows") for r in recent) / recent_docs
        if base_avg > 0 and recent_avg <= base_avg * (1 - limit.yield_drop_ratio):
            findings.append(
                Finding(
                    YIELD_DROP,
                    source_id,
                    f"verified rows per document fell from {base_avg:.1f} to {recent_avg:.1f}",
                    {"baseline": round(base_avg, 2), "recent": round(recent_avg, 2)},
                )
            )

    verified = sum(_n(r, "verified_rows") for r in recent)
    rejected = sum(_n(r, "rejected_rows") for r in recent)
    if verified + rejected >= limit.rejection_min_rows:
        share = rejected / (verified + rejected)
        if share >= limit.rejection_spike_ratio:
            findings.append(
                Finding(
                    REJECTION_SPIKE,
                    source_id,
                    f"the verifier rejected {rejected} of {verified + rejected} candidate "
                    f"row(s) ({share:.0%}) in recent documents",
                    {"rejected": rejected, "verified": verified},
                )
            )

    earlier_scope = max((_n(r, "in_scope") for r in runs[:-1]), default=0)
    shrink_notice = _code_count(latest, "notices", LISTING_SHRINK)
    now_scope = _n(latest, "in_scope")
    if shrink_notice or (
        earlier_scope >= 4
        and "in_scope" in latest
        and now_scope < earlier_scope * limit.listing_shrink_ratio
    ):
        findings.append(
            Finding(
                LISTING_SHRINK,
                source_id,
                f"the listing now shows {now_scope} in-scope filing(s), earlier runs up to "
                f"{earlier_scope}",
                {"in_scope": now_scope, "earlier_max": earlier_scope},
            )
        )

    last_run = parse_time(latest.get("at"))
    if last_run is not None and now - last_run > timedelta(
        hours=cadence_hours * limit.overdue_multiplier
    ):
        findings.append(
            Finding(
                OVERDUE,
                source_id,
                f"no document-stage run since {last_run.isoformat()} (cadence {cadence_hours} h)",
                {"last_run": last_run.isoformat()},
            )
        )

    if new_observations_recent == 0 and observations_total > 0:
        findings.append(
            Finding(
                ZERO_NEW_RECORDS,
                source_id,
                f"no new record in the last {limit.zero_new_days} day(s) "
                f"({observations_total} retained)",
                {"days": limit.zero_new_days, "retained": observations_total},
            )
        )
    return findings


def document_report(now: datetime | None = None) -> list[Finding]:
    """Read-only findings for every enabled source that reports document-stage runs."""
    from sqlalchemy import func, select

    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Observation, Source

    now = now or datetime.now(UTC)
    limit = Thresholds.from_settings()
    findings: list[Finding] = []
    with SessionLocal() as session:
        for source in session.scalars(select(Source).where(Source.enabled.is_(True))):
            block = (source.health or {}).get("document_stage")
            runs = block.get("runs") if isinstance(block, dict) else None
            if not isinstance(runs, list) or not runs:
                continue
            total = session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.source_id == source.id)
            )
            recent = session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(
                    Observation.source_id == source.id,
                    Observation.first_seen_at >= now - timedelta(days=limit.zero_new_days),
                )
            )
            findings.extend(
                evaluate(
                    source.id,
                    [run for run in runs if isinstance(run, dict)],
                    cadence_hours=source.cadence_hours,
                    now=now,
                    thresholds=limit,
                    new_observations_recent=int(recent or 0),
                    observations_total=int(total or 0),
                )
            )
    return findings
