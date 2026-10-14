"""Explainable opportunity ranking (PRD Requirement 27).

DRAFT weights, pending owner approval. The score orders active needs for attention; it is
not a probability, a confidence, or a qualification. Tier gates stay authoritative and
are never changed by rank. Weights are published in docs/product/ranking-weights.md.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from gridlens.domain.buying_chain import Category
from gridlens.domain.commercial_triage import _priority

RANKING_VERSION = "ranking-draft-v1"

# Points per factor. They sum to 100.
WEIGHTS = {
    "product_fit": 25,
    "timing": 20,
    "evidence": 20,
    "recent_change": 15,
    "buyer_access": 10,
    "geography": 10,
}

# Activity priority from the October 1 owner amendment, via the canonical segment.
_FIT_BY_SEGMENT = {
    1: (1.0, "Data-center commissioning with phase evidence"),
    0: (0.95, "Data-center construction phase"),
    3: (0.9, "Explicit temporary, construction or bridge power scope"),
    4: (0.8, "Data-center commissioning evidence"),
    5: (0.75, "Data-center construction evidence"),
    2: (0.7, "Producing oil and gas asset"),
    6: (0.6, "Data-center project, phase not yet established"),
    7: (0.5, "Oil and gas activity"),
    8: (0.3, "Other industry"),
}
_PRIORITY_METROS = (
    (r"dallas|fort worth|dfw|plano|irving|arlington|midlothian", "DFW"),
    (r"austin", "Austin"),
    (r"houston", "Houston"),
    (r"el paso", "El Paso"),
    (r"california|, ca\b", "California"),
)
# Direct users and responsible contractors (Req 28); rental intermediaries are excluded.
_BUYER_CATEGORIES = {category.value for category in Category} - {"unknown"}


def _latest_evidence_date(item: dict[str, Any]) -> date | None:
    latest: date | None = None
    for evidence in item.get("evidence") or []:
        for key in ("event_date", "published_at"):
            value = evidence.get(key)
            if not value:
                continue
            try:
                parsed = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
            latest = parsed if latest is None or parsed > latest else latest
    return latest


def rank_opportunity(
    item: dict[str, Any], chain: dict[str, Any] | None, today: date
) -> dict[str, Any]:
    """Return {rank_score, rank_reasons, rank_version}; reasons explain the largest parts."""
    parts: list[tuple[float, str]] = []

    segment = _priority(item)[0]
    fit, fit_reason = _FIT_BY_SEGMENT.get(segment, _FIT_BY_SEGMENT[8])
    parts.append((WEIGHTS["product_fit"] * fit, fit_reason))

    lifecycle = str(item.get("lifecycle_state") or "")
    if item.get("start_window"):
        timing, timing_reason = 1.0, f"Start window supported: {item['start_window']}"
    elif re.search(r"construction|commissioning|electrical_buildout", lifecycle):
        timing, timing_reason = 0.7, "Project is in a construction or commissioning phase"
    elif item.get("time_to_power_window"):
        timing, timing_reason = 0.4, "Derived lifecycle window (estimate, not a reported date)"
    else:
        timing, timing_reason = 0.1, "Timing unknown"
    parts.append((WEIGHTS["timing"] * timing, timing_reason))

    tier = item.get("tier")
    if item.get("conflict_state") == "CONFLICT":
        evidence, evidence_reason = 0.1, "Unresolved evidence conflict"
    elif item.get("signal_evidence_state") not in (None, "active_evidence"):
        evidence, evidence_reason = 0.25, "Source status needs review"
    elif tier == "Lead":
        evidence, evidence_reason = 1.0, "Lead: MW, start, duration and gap supported"
    elif tier == "Prospect":
        evidence, evidence_reason = 0.7, "Prospect: power requirement and supply concern supported"
    else:
        evidence, evidence_reason = 0.4, "Signal: dated official or published source"
    parts.append((WEIGHTS["evidence"] * evidence, evidence_reason))

    latest = _latest_evidence_date(item)
    age = (today - latest).days if latest else None
    if age is not None and 0 <= age <= 30:
        recent, recent_reason = 1.0, f"New or changed evidence {age} days ago"
    elif age is not None and 0 <= age <= 90:
        recent, recent_reason = 0.5, f"Evidence from the last 90 days ({age} days ago)"
    else:
        recent, recent_reason = 0.0, "No evidence in the last 90 days"
    parts.append((WEIGHTS["recent_change"] * recent, recent_reason))

    candidates = (chain or {}).get("candidates") or []
    direct = [
        candidate
        for candidate in candidates
        if candidate.get("category") in _BUYER_CATEGORIES
        and candidate.get("organization_relationship") == "DIRECT"
    ]
    if direct:
        access, access_reason = 1.0, (
            f"Responsible party identified: {direct[0].get('organization')}"
        )
    elif item.get("title_company"):
        access, access_reason = 0.5, f"Project company known: {item['title_company']}"
    else:
        access, access_reason = 0.0, "Buying party unknown"
    parts.append((WEIGHTS["buyer_access"] * access, access_reason))

    location = str(item.get("location") or "").casefold()
    metro = next((name for pattern, name in _PRIORITY_METROS if re.search(pattern, location)), None)
    if metro:
        parts.append((WEIGHTS["geography"], f"Priority geography: {metro}"))
    elif re.search(r"\btexas\b|, tx\b", location):
        parts.append((WEIGHTS["geography"] * 0.5, "Texas outside priority metros"))
    else:
        parts.append((0.0, "Outside priority geographies"))

    score = round(sum(points for points, _ in parts))
    reasons = [reason for points, reason in sorted(parts, key=lambda p: -p[0]) if points > 0][:3]
    return {"rank_score": score, "rank_reasons": reasons, "rank_version": RANKING_VERSION}
