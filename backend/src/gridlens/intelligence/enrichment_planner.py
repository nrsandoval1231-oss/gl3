"""Deterministic ranking and refresh decisions for bounded company research."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.domain.pursuit_research import fingerprint

REFRESH_AFTER = timedelta(days=30)
STANDARD_RESEARCH_PROFILE = "contact-depth-v1:standard"
DEEP_RESEARCH_PROFILE = "contact-depth-v1:deep"


@dataclass(frozen=True)
class ResearchCandidate:
    company_id: Any
    projects: tuple[Any, ...]
    needs: tuple[Any, ...]
    latest_evidence_at: datetime | None
    completed_at: datetime | None
    prior_digest: str | None
    source_digest: str = ""
    missing_buyer_relevant_method: bool = False
    missing_contact_method: bool = False
    research_profile: str = STANDARD_RESEARCH_PROFILE


def _missing(need: Any) -> list[str]:
    """Only actionable contact gaps affect company-contact research depth."""
    return []


def _supported_start(value: Any) -> date | None:
    """Parse only explicit ISO dates and calendar-quarter windows."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{4})-?Q([1-4])", text, re.I)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
        try:
            return date(year, (quarter - 1) * 3 + 1, 1)
        except ValueError:
            return None
    return None


def _demand_mw(value: Any) -> Decimal | None:
    """Read explicit MW values for explanation only; never infer rental priority."""
    text = str(value or "").strip()
    matches = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*MW\b", text, re.I)
    if not matches:
        return None
    try:
        values = [Decimal(number) for number in matches]
    except InvalidOperation:
        return None
    return max(values) if all(value.is_finite() for value in values) else None


def rank_candidate(candidate: ResearchCandidate, *, now: datetime) -> dict[str, Any]:
    """Rank research work heuristically; this is not commercial or evidence confidence."""
    needs = candidate.needs
    if not needs:
        return {
            "score": 0,
            "contact_depth_score": 0,
            "reasons": ["no_active_power_need"],
            "missing_facts": [],
        }
    # Facility demand, timing and supply are not commercial utility for a
    # company-contact pass. Contact depth is justified only by observed gaps.
    demand_values = [value for n in needs if (value := _demand_mw(n.required_mw)) is not None]
    commercial = 0
    missing = sorted({fact for need in needs for fact in _missing(need)})
    starts = [start for n in needs if (start := _supported_start(n.start_window)) is not None]
    days_to_start = min(((start - now.date()).days for start in starts), default=None)
    urgency = 0
    # Contact research utility is represented once by contact_gap below.
    utility = 0
    resolvability = 8 if candidate.projects and candidate.source_digest else 0
    cost = -5  # Existing capped public retrieval remains the only planned action.
    freshness = (
        8
        if candidate.latest_evidence_at and now - candidate.latest_evidence_at <= timedelta(days=30)
        else 0
    )
    contact_gap = (
        12
        if candidate.missing_buyer_relevant_method
        else 6
        if candidate.missing_contact_method
        else 0
    )
    contact_depth_score = (
        commercial + utility + resolvability + contact_gap
    )
    score = (
        commercial
        + urgency
        + utility
        + resolvability
        + cost
        + freshness
        + contact_gap
    )
    reasons = [
        f"commercial_value:{commercial}",
        f"urgency:{urgency}",
        f"missing_fact_utility:{utility}",
        f"resolvability:{resolvability}",
        f"stable_contact_depth_score:{contact_depth_score}",
        f"bounded_public_research_cost:{cost}",
        f"freshness:{freshness}",
        "known_demand_mw:unknown" if not demand_values else "known_demand_mw:observed_not_scored",
        (
            "days_to_supported_start:unknown"
            if days_to_start is None
            else "days_to_supported_start:observed_not_scored"
        ),
    ]
    if missing:
        reasons.append("missing_facts:" + ",".join(missing))
    if candidate.missing_buyer_relevant_method:
        reasons.append("missing_buyer_relevant_contact_method:12")
    elif candidate.missing_contact_method:
        reasons.append("missing_contact_method:6")
    return {
        "score": score,
        "contact_depth_score": contact_depth_score,
        "reasons": reasons,
        "missing_facts": missing,
    }


def select_research_profile(candidate: ResearchCandidate, *, now: datetime) -> str:
    """Choose a stable bounded depth profile from opportunity evidence and contact gaps."""
    rank = rank_candidate(candidate, now=now)
    if candidate.missing_buyer_relevant_method and rank.get("contact_depth_score", 0) >= 38:
        return DEEP_RESEARCH_PROFILE
    return STANDARD_RESEARCH_PROFILE


def research_digest(candidate: ResearchCandidate) -> str:
    """Digest project/need and source-version inputs that make a queued job stale."""
    return fingerprint(
        {
            "company_id": str(candidate.company_id),
            "projects": sorted(str(p.id) for p in candidate.projects),
            "needs": sorted(
                (str(n.id), n.tier, n.required_mw, n.start_window, n.duration, n.supply, n.active)
                for n in candidate.needs
            ),
            "evidence_at": candidate.latest_evidence_at,
            "source_digest": candidate.source_digest,
            "missing_buyer_relevant_method": candidate.missing_buyer_relevant_method,
            "missing_contact_method": candidate.missing_contact_method,
            "research_profile": candidate.research_profile,
        }
    )


def should_schedule(
    candidate: ResearchCandidate, *, now: datetime, digest: str
) -> tuple[bool, str]:
    if candidate.prior_digest != digest:
        return True, "project_or_evidence_changed"
    if candidate.completed_at is None:
        return True, "never_completed"
    completed = candidate.completed_at
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=UTC)
    if now - completed >= REFRESH_AFTER:
        return True, "stale_refresh_due"
    return False, "recent_unchanged_research"
