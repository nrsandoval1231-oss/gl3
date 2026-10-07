"""Conservative PRD qualification from exact scoped official permit clauses.

This parser does not confer source authority. Callers must independently require
current accepted official evidence and the exact project/activity binding.
Unsupported wording remains unknown; no cross-document completion or inference.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from gridlens.domain.news_interpretation import prospect_power_activity, validated_demand_mw

VERSION = "official-power-qualification-v2"
_PHASES = {
    "facility-expansion": "construction",
    "construction": "construction",
    "commissioning": "commissioning",
    "manufacturing": "manufacturing",
    "production": "production",
    "operations": "operations",
}
# Conservative conflict guard: a contradictory/secured/qualified clause anywhere
# in this one exact permit scope prevents qualification, rather than guessing
# whether it concerns another package.
_UNSAFE = re.compile(
    r"\b(?:not|unknown|possible|possibly|might|may|could|approximately|about|"
    r"adequate|sufficient|awarded|secured|cancelled|canceled|completed|"
    r"campus capacity|nameplate|at least|up to|in service|fully served|"
    r"hypothetical|example|examples|template|sample|illustrative|fictional|synthetic|"
    r"historical|historic|history|previous|prior|formerly|archived|quotation|quoted|"
    r"conditional|assuming|assume|if|would|draft|proposed)\b",
    re.I,
)
_NUMBER = r"(?:[1-9]\d{0,8}(?:\.\d{1,9})?|0\.\d{0,8}[1-9]\d{0,8})"
_DATE = r"\d{4}-\d{2}-\d{2}"


def qualify_official_power(
    *, text: str, site: str, activity_key: str, location: str | None
) -> dict[str, Any]:
    """Return source-quoted Prospect/Lead fields, or no qualification.

    The Lead subset handles explicitly scoped aggregate supply intervals. It never treats
    pending permanent service alone as proof that temporary supply is absent.
    """
    phase = _PHASES.get(activity_key)
    site = " ".join(site.split())
    if not phase or not site or not location or _UNSAFE.search(text):
        return {}
    if any(marker in text for marker in ('"', "`", "“", "”")):
        return {}
    clauses = [c.strip() for c in re.split(r"(?<=[.!?])\s+", text) if c.strip()]
    # A dated historical header cannot lend present authority to exact clauses
    # below it. The explicit start-window clause is checked separately for Lead.
    year = datetime.now(UTC).year
    if any(
        any(int(value) < year for value in re.findall(r"\b(?:19|20)\d{2}\b", clause))
        for clause in clauses
        if " starts between " not in clause.lower()
    ):
        return {}
    scope = re.escape(site) + r"\s+" + phase
    demands = [
        (
            clause,
            re.fullmatch(
                rf"{scope}\s+requires\s+({_NUMBER})(?:\s+to\s+({_NUMBER}))?\s+MW[.]?", clause, re.I
            ),
        )
        for clause in clauses
    ]
    demands = [(quote, match) for quote, match in demands if match]
    supplies = [
        clause
        for clause in clauses
        if re.fullmatch(
            rf"Power supply for {scope} is (?:delayed|insufficient|unavailable)[.]?", clause, re.I
        )
    ]
    if len(demands) != 1 or len(supplies) != 1:
        return {}
    if any(
        re.search(
            rf"(?:power supply|utility service|temporary supply) for {scope} "
            r"(?:is|now is|is now|remains) (?:available|adequate|sufficient|energized|secured)",
            clause,
            re.I,
        )
        for clause in clauses
    ):
        return {}
    demand_quote, match = demands[0]
    assert match is not None
    low, high = Decimal(match[1]), Decimal(match[2] or match[1])
    if low <= 0 or high < low:
        return {}
    if match[2] is None:
        # Preserve the established exact-site/activity Prospect checks unchanged.
        if (
            prospect_power_activity(site, demand_quote, supplies[0]) != phase
            or validated_demand_mw(site, demand_quote, phase) is None
        ):
            return {}
    demand_mw = f"{low} to {high} MW" if low != high else f"{low} MW"
    result: dict[str, Any] = {
        "tier": "Prospect",
        "demand_mw": demand_mw,
        "demand_quote": demand_quote,
        "supply_quote": supplies[0],
        "qualification_version": VERSION,
        "qualification_scope": {"site": site, "activity": phase},
        "reason": "Current official scope explicitly binds activity-specific demand and "
        "a separate unsuitable-supply statement to this exact site and activity.",
    }

    def only(pattern: str):
        matches = [(clause, re.fullmatch(pattern, clause, re.I)) for clause in clauses]
        found = [(quote, match) for quote, match in matches if match]
        return found[0] if len(found) == 1 else (None, None)

    start_quote, start = only(rf"{scope} starts between ({_DATE}) and ({_DATE})[.]?")
    duration_quote, duration = only(rf"{scope} lasts ([1-9]\d{{0,5}}) to ([1-9]\d{{0,5}}) days[.]?")
    gap_quote, gap = only(
        rf"No suitable power supply is available for {scope} throughout this start window "
        r"and duration[.]?"
    )
    available_quote, available = only(
        rf"Total suitable power supply available for {scope} is "
        rf"(0|{_NUMBER})(?: to (0|{_NUMBER}))? MW throughout this start window and duration[.]?"
    )
    # One aggregate explicitly suitable supply statement, never component sums.
    # Two alternatives or zero/nonzero statements cannot resolve one interval.
    candidates = [
        clause
        for clause in clauses
        if re.search(
            r"(?:No suitable power supply|Total suitable power supply available)", clause, re.I
        )
    ]
    if len(candidates) != 1:
        return result

    def supply_conflict() -> dict[str, Any]:
        return {
            "tier": "Signal",
            "demand_mw": None,
            "qualified_remaining_gap": None,
            "start_window": None,
            "duration": None,
            "qualification_version": VERSION,
            "qualification_conflict": True,
            "reason": "Conflicting official suitable-supply statements "
            "for the same activity interval",
        }

    available_low = available_high = Decimal(0)
    if available:
        available_low = Decimal(available[1])
        available_high = Decimal(available[2] or available[1])
        if available_high < available_low:
            return result
        if available_high > 0 and "unavailable" in supplies[0].lower():
            return supply_conflict()
        gap_quote = available_quote
    remaining_low = max(Decimal(0), low - available_high)
    remaining_high = max(Decimal(0), high - available_low)
    if available and remaining_high == 0:
        # The numeric supply contradicts the separate reported open constraint.
        return supply_conflict()
    buyer_quote, buyer = only(
        rf"The (electrical contractor|general contractor|project owner) is responsible for "
        rf"power procurement for {scope}[.]?"
    )
    if not (start and duration and (gap or available) and buyer) or remaining_low == 0:
        return result
    try:
        first, last = date.fromisoformat(start[1]), date.fromisoformat(start[2])
    except ValueError:
        return result
    if first > last or int(duration[1]) > int(duration[2]):
        return result
    try:
        latest_end = last + timedelta(days=int(duration[2]))
    except (OverflowError, ValueError):
        return result
    if latest_end < datetime.now(UTC).date():
        return result
    start_window = f"{first.isoformat()} to {last.isoformat()}"
    duration_range = f"{duration[1]} to {duration[2]} days"
    result.update(
        tier="Lead",
        start_window=start_window,
        duration=duration_range,
        start_quote=start_quote,
        duration_quote=duration_quote,
        buyer_quote=buyer_quote,
        buying_role=buyer[1].lower(),
        qualification_next_action=(
            f"Contact the {buyer[1].lower()} to verify the open power package."
        ),
        qualified_remaining_gap={
            "required_mw_min": str(low),
            "required_mw_max": str(high),
            "available_mw_min": str(available_low),
            "available_mw_max": str(available_high),
            "remaining_mw_min": str(remaining_low),
            "remaining_mw_max": str(remaining_high),
            "start_window": start_window,
            "duration": duration_range,
            "basis_quote": gap_quote,
            "value_kind": "Derived",
            "calculation": "[max(0, required_min - available_max), "
            "max(0, required_max - available_min)]",
            "version": VERSION,
        },
        reason="Current official scope supports the exact activity/site, MW range, start window, "
        "duration range, aggregate suitable supply throughout that interval, and buying role.",
    )
    return result


def qualify_retained_official(text: str, activity_key: str, location: str | None) -> dict[str, Any]:
    """Read only unambiguous native fields, never arbitrary page claims."""
    fields = {}
    for key in ("description", "address"):
        found = re.findall(rf"^{key}: ([^\n]+)$", text, re.M)
        if len(found) != 1:
            return {}
        fields[key] = found[0]
    return qualify_official_power(
        text=fields["description"],
        site=fields["address"],
        activity_key=activity_key,
        location=location,
    )
