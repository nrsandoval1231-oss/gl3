"""Transparent rules for owner-managed commercial pursuits (no speculative urgency)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from gridlens.persistence.commercial_pursuit_models import CLOSED_STAGES, STAGES

FOLLOW_UP_WINDOW_DAYS = 2
POWER_TIMING_WINDOW_DAYS = 30
_ISO_DAY = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")

REASON_LABELS = {
    "overdue_follow_up": "Follow-up overdue",
    "follow_up_due_soon": "Follow-up due soon",
    "missing_contact": "No usable contact method",
    "power_timing_near": "Source-reported power timing within 30 days",
}


@dataclass(frozen=True)
class OpenTask:
    id: str
    due_date: date | None


def valid_stage(value: str) -> bool:
    return value in STAGES


def parse_power_day(start_window: str | None) -> date | None:
    """Only a full ISO calendar day counts; ranges, quarters and prose never do."""
    match = _ISO_DAY.match(start_window or "")
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def attention_reasons(
    *,
    stage: str,
    open_tasks: list[OpenTask],
    has_usable_contact: bool | None,
    start_window: str | None,
    today: date,
) -> list[str]:
    """Reasons a pursuit needs attention; closed pursuits never qualify.

    ``has_usable_contact`` is None when contact evidence could not be read; an
    unknown is never reported as missing.
    """
    if stage in CLOSED_STAGES:
        return []
    reasons: list[str] = []
    dated = [task.due_date for task in open_tasks if task.due_date is not None]
    if any(day < today for day in dated):
        reasons.append("overdue_follow_up")
    elif any(day <= today + timedelta(days=FOLLOW_UP_WINDOW_DAYS) for day in dated):
        reasons.append("follow_up_due_soon")
    if has_usable_contact is False:
        reasons.append("missing_contact")
    power_day = parse_power_day(start_window)
    if power_day is not None and today <= power_day <= today + timedelta(
        days=POWER_TIMING_WINDOW_DAYS
    ):
        reasons.append("power_timing_near")
    return reasons
