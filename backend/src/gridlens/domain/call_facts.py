"""Typed, exact-need operator facts and deterministic current qualification inputs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.domain.commercial_presentation import exact_mw_interval
from gridlens.domain.power_qualification import VERSION as POWER_QUALIFICATION_VERSION

FACT_TYPES = frozenset(
    {"demand", "unsuitable_supply", "suitable_supply", "timing", "buyer", "closure"}
)
MAX_CURRENT_OPERATOR_FACTS_PER_NEED = 50
MAX_CURRENT_OPERATOR_FACT_BYTES_PER_NEED = 512 * 1024


class CurrentOperatorInputBoundExceeded(RuntimeError):
    """Raised rather than truncating a need's current accepted fact set."""


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_fact(fact_type: str, value: dict[str, Any]) -> dict[str, Any]:
    """Validate typed fields without turning an unsupported report into evidence."""
    if fact_type not in FACT_TYPES:
        raise ValueError("Unsupported fact type")
    if not isinstance(value, dict) or not value:
        raise ValueError("Fact value must be a non-empty object")
    fields_by_type = {
        "demand": {"mw", "mw_min", "mw_max"},
        "unsuitable_supply": {"mw"},
        "suitable_supply": {"mw", "mw_min", "mw_max", "quality"},
        "timing": {"start_date", "end_date", "duration_days"},
        "buyer": {"organization", "role"},
        "closure": {"state"},
    }
    allowed = fields_by_type[fact_type] | {"basis", "source_quote"}
    if set(value) - allowed:
        raise ValueError("Fact value contains unsupported fields")
    clean: dict[str, Any] = {}
    if fact_type in {"demand", "unsuitable_supply", "suitable_supply"}:
        if fact_type == "suitable_supply" and value.get("quality") not in {
            "suitable",
            "unsuitable",
            "unknown",
        }:
            raise ValueError("suitable supply requires an explicit quality")
        if fact_type == "unsuitable_supply":
            interval = _fact_mw_interval(value, allow_zero=False)
            if interval is None or interval[0] != interval[1]:
                raise ValueError("mw must be a positive numeric value")
        else:
            interval = _fact_mw_interval(
                value,
                allow_zero=fact_type == "suitable_supply",
            )
            if interval is None:
                raise ValueError(
                    "mw must be positive or an exact bounded range within the supported range"
                )
        low, high = interval
        if high > Decimal("1000000"):
            raise ValueError("mw must be within the supported range")
        if low == high:
            clean["mw"] = _format_mw(low)
        else:
            clean["mw_min"] = _format_mw(low)
            clean["mw_max"] = _format_mw(high)
        if "quality" in value:
            clean["quality"] = value["quality"]
    elif fact_type == "timing":
        start = value.get("start_date")
        end = value.get("end_date")
        duration = value.get("duration_days")
        try:
            first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        except ValueError:
            raise ValueError("timing requires ISO start_date and end_date") from None
        if first > last or not isinstance(duration, int) or not 1 <= duration <= 36500:
            raise ValueError("timing range or duration is invalid")
        clean = {
            "start_date": first.isoformat(),
            "end_date": last.isoformat(),
            "duration_days": duration,
        }
    elif fact_type == "buyer":
        organization = value.get("organization")
        role = value.get("role")
        if not isinstance(organization, str) or len(organization.strip()) < 2:
            raise ValueError("buyer organization is required")
        if not isinstance(role, str) or role.strip().lower() not in {
            "project owner",
            "electrical contractor",
            "general contractor",
            "energy manager",
        }:
            raise ValueError("buyer role must identify an authorized buying organization role")
        clean = {"organization": organization.strip(), "role": role.strip().lower()}
    elif fact_type == "closure":
        if value.get("state") not in {"adequate_supply", "cancelled", "completed"}:
            raise ValueError("closure state is unsupported")
        clean = {"state": value["state"]}
    for key, item in value.items():
        if key not in clean and key in {"basis", "source_quote"}:
            if not isinstance(item, str) or not item.strip() or len(item) > 2000:
                raise ValueError(f"{key} must contain 1 to 2000 characters")
            clean[key] = item.strip()
    return clean


def _format_mw(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fact_mw_interval(
    value: dict[str, Any], *, allow_zero: bool
) -> tuple[Decimal, Decimal] | None:
    """Read one exact point or bounded interval from typed fact fields."""
    has_min = "mw_min" in value
    has_max = "mw_max" in value
    if has_min != has_max or (has_min and "mw" in value):
        return None
    if has_min:
        raw_low, raw_high = value.get("mw_min"), value.get("mw_max")
        if any(isinstance(raw, str) and len(raw) > 128 for raw in (raw_low, raw_high)):
            return None
        try:
            low, high = Decimal(str(raw_low)), Decimal(str(raw_high))
        except (InvalidOperation, TypeError, ValueError):
            return None
    else:
        amount = value.get("mw")
        if isinstance(amount, bool):
            return None
        if isinstance(amount, str):
            parsed = exact_mw_interval(amount)
            if parsed is not None:
                low, high = parsed
            else:
                if len(amount) > 128:
                    return None
                try:
                    low = high = Decimal(amount)
                except (InvalidOperation, TypeError, ValueError):
                    return None
        else:
            try:
                low = high = Decimal(str(amount))
            except (InvalidOperation, TypeError, ValueError):
                return None
    if (
        not low.is_finite()
        or not high.is_finite()
        or low < 0
        or (not allow_zero and low == 0)
        or high < low
        or high > Decimal("1000000")
    ):
        return None
    return low, high


def _mw_presentation(interval: tuple[Decimal, Decimal]) -> str:
    low, high = interval
    if low == high:
        return f"{_format_mw(low)} MW"
    return f"{_format_mw(low)} to {_format_mw(high)} MW"


def validate_timezone(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(UTC)


def current_accepted_facts(
    versions: list[Any], decisions: list[Any], *, now: datetime | None = None
) -> list[Any]:
    """Select latest decision per immutable version, then filter to live accepted facts."""
    current = now or datetime.now(UTC)
    by_fact: dict[str, Any] = {}
    for event in decisions:
        key = str(event.fact_version_id)
        if key not in by_fact or event.version > by_fact[key].version:
            by_fact[key] = event
    version_by_id = {str(row.id): row for row in versions}
    accepted = []
    for key, decision in by_fact.items():
        row = version_by_id.get(key)
        if row is None or decision.decision not in {"accepted", "corrected"}:
            continue
        start = row.effective_from
        end = row.effective_until
        if start <= current and (end is None or current < end):
            accepted.append(row)
    return sorted(accepted, key=lambda row: (row.fact_type, row.content_hash, str(row.id)))


def _activity_interval(value: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Return the full possible activity interval using a half-open UTC range."""
    try:
        first = date.fromisoformat(str(value["start_date"]))
        last_start = date.fromisoformat(str(value["end_date"]))
        duration = value["duration_days"]
        if first > last_start or not isinstance(duration, int) or duration <= 0:
            return None
        # The last date is an inclusive possible start date; add the activity
        # duration to obtain its exclusive end boundary.
        exclusive_end = last_start + timedelta(days=duration)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return (
        datetime.combine(first, time.min, UTC),
        datetime.combine(exclusive_end, time.min, UTC),
    )


def _source_lead_activity_interval(claim: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Replay the already-qualified official Lead's complete possible activity window."""
    start_window = claim.get("start_window")
    duration = claim.get("duration")
    if not isinstance(start_window, str) or not isinstance(duration, str):
        return None
    starts = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", start_window)
    duration_match = re.fullmatch(r"(\d{1,6})(?: to (\d{1,6}))? days", duration)
    if starts is None or duration_match is None:
        return None
    try:
        max_days = int(duration_match[2] or duration_match[1])
        return _activity_interval(
            {
                "start_date": starts[1],
                "end_date": starts[2],
                "duration_days": max_days,
            }
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _fact_covers_interval(row: Any, interval: tuple[datetime, datetime]) -> bool:
    """Fail closed unless an accepted version covers the whole activity interval."""
    if not hasattr(row, "effective_from") or not hasattr(row, "effective_until"):
        return False
    starts_at = getattr(row, "effective_from", None)
    ends_at = getattr(row, "effective_until", None)
    if (
        not isinstance(starts_at, datetime)
        or starts_at.tzinfo is None
        or starts_at.utcoffset() is None
    ):
        return False
    if ends_at is not None and (
        not isinstance(ends_at, datetime)
        or ends_at.tzinfo is None
        or ends_at.utcoffset() is None
    ):
        return False
    start, end = interval
    starts_at = starts_at.astimezone(UTC)
    ends_at = ends_at.astimezone(UTC) if ends_at is not None else None
    return starts_at <= start and (ends_at is None or ends_at >= end)


def qualification_from_facts(
    base: dict[str, Any] | None,
    facts: list[Any],
    *,
    need: Any,
    project: Any,
) -> dict[str, Any] | None:
    """Augment only a live public-source claim; facts alone never create qualification."""
    if not base:
        return None
    if any(
        row.project_id != need.project_id
        or row.activity_key != need.activity_key
        or row.facility_scope.strip().casefold() != (project.location or "").strip().casefold()
        for row in facts
    ):
        return {
            **base,
            "tier": "Signal",
            "qualification_conflict": True,
            "reason": "Accepted operator fact is bound to a different activity or facility.",
        }
    fields: dict[str, list[Any]] = {}
    rows_by_type: dict[str, list[Any]] = {}
    for row in facts:
        fields.setdefault(row.fact_type, []).append(row.value)
        rows_by_type.setdefault(row.fact_type, []).append(row)
    for fact_type, values in fields.items():
        if len({canonical_hash(value) for value in values}) > 1:
            return {
                **base,
                "tier": "Signal",
                "qualification_conflict": True,
                "reason": f"Accepted {fact_type} facts conflict for this need.",
            }
    if fields.get("closure"):
        return {
            **base,
            "tier": "Signal",
            "required_mw": None,
            "closed_by_fact": True,
            "reason": "Accepted exact-need closure fact removes current qualification.",
        }
    demand = fields.get("demand", [])
    unsuitable = fields.get("unsuitable_supply", [])
    source_value = base.get("demand_mw") or base.get("required_mw")
    source_interval = exact_mw_interval(source_value)
    fact_interval = _fact_mw_interval(demand[0], allow_zero=False) if demand else None
    base_tier = base.get("tier")
    calculation_demand: tuple[Decimal, Decimal] | None = None
    if source_interval is not None:
        calculation_demand = source_interval
        if fact_interval is not None:
            overlap = (
                max(source_interval[0], fact_interval[0]),
                min(source_interval[1], fact_interval[1]),
            )
            if overlap[0] > overlap[1]:
                return {
                    **base,
                    "tier": "Signal",
                    "qualification_conflict": True,
                    "reason": (
                        "Accepted operator demand conflicts with current public source support."
                    ),
                }
            calculation_demand = overlap

    if base_tier not in {"Signal", "Prospect", "Lead"}:
        return base

    suitable = fields.get("suitable_supply", [])
    suitable_rows = rows_by_type.get("suitable_supply", [])
    timing = fields.get("timing", [])
    timing_rows = rows_by_type.get("timing", [])
    if base_tier == "Signal":
        closure_demand = fact_interval
        closure_has_shortage_support = bool(closure_demand and unsuitable)
    else:
        closure_demand = calculation_demand
        closure_has_shortage_support = bool(
            closure_demand and source_interval is not None and base.get("supply_quote")
        )
    closure_activity_interval = (
        _activity_interval(timing[0])
        if timing
        else _source_lead_activity_interval(base)
        if base_tier == "Lead"
        else None
    )
    closure_rows = list(suitable_rows[:1])
    if timing_rows:
        closure_rows.append(timing_rows[0])
    if demand and (base_tier == "Signal" or fact_interval is not None):
        closure_rows.append(rows_by_type["demand"][0])
    if base_tier == "Signal" and unsuitable:
        closure_rows.append(rows_by_type["unsuitable_supply"][0])
    closure_supply_interval = (
        _fact_mw_interval(suitable[0], allow_zero=True)
        if suitable
        else None
    )
    if (
        closure_has_shortage_support
        and suitable
        and suitable[0].get("quality") == "suitable"
        and closure_supply_interval is not None
        and closure_activity_interval is not None
        and closure_rows
        and all(_fact_covers_interval(row, closure_activity_interval) for row in closure_rows)
        and closure_demand is not None
        and closure_supply_interval[0] >= closure_demand[1]
    ):
        supply_row = suitable_rows[0]
        source_semantic_hash = base.get("semantic_hash")
        source_evidence_hash = base.get("evidence_hash")
        basis = {
            "kind": "confirmed_adequate_supply",
            "required_mw": _mw_presentation(closure_demand),
            "suitable_supply_mw": _mw_presentation(closure_supply_interval),
            "remaining_mw_min": "0",
            "remaining_mw_max": "0",
            "calculation": "[max(0, required_min - suitable_max), "
            "max(0, required_max - suitable_min)]",
            "version": POWER_QUALIFICATION_VERSION,
            "activity_interval_start": closure_activity_interval[0].isoformat(),
            "activity_interval_end_exclusive": closure_activity_interval[1].isoformat(),
            "suitable_supply_fact_id": str(supply_row.id),
            "suitable_supply_fact_hash": supply_row.content_hash,
            "source_semantic_hash": source_semantic_hash,
            "source_evidence_hash": source_evidence_hash,
            "source_qualification_version": base.get("qualification_version"),
            "source_reported_supply_quote": base.get("supply_quote"),
        }
        if demand:
            demand_row = rows_by_type["demand"][0]
            basis["demand_fact_id"] = str(demand_row.id)
            basis["demand_fact_hash"] = demand_row.content_hash
        rationale = (
            f"Confirmed suitable supply {_mw_presentation(closure_supply_interval)} covers "
            f"the full activity interval and {_mw_presentation(closure_demand)} requirement; "
            f"accepted fact {supply_row.id} ({supply_row.content_hash}) supersedes the current "
            f"reported open-supply basis. Source semantic hash {source_semantic_hash}; "
            f"evidence hash {source_evidence_hash}."
        )
        closed = {
            **base,
            "tier": "Signal",
            "demand_mw": None,
            "required_mw": None,
            "closed_by_fact": True,
            "closure_basis": basis,
            "reason": rationale,
        }
        for key in (
            "start_window",
            "duration",
            "qualified_remaining_gap",
            "qualification_next_action",
            "buying_role",
            "fact_derived_required_mw",
        ):
            closed.pop(key, None)
        return closed

    # A source-supported Prospect already establishes activity-specific demand
    # and unsuitable supply. Signal needs compatible exact-need facts for both.
    if base_tier in {"Prospect", "Lead"}:
        required_interval = calculation_demand
    else:
        required_interval = fact_interval
    has_unsuitable = (
        bool(unsuitable)
        if base_tier == "Signal"
        else bool(base.get("supply_quote"))
    )
    if required_interval is None or not has_unsuitable:
        return base

    # An already replayed official Lead carries its own source-supported time
    # and buyer gates. Reconcile a newly accepted suitable-supply fact against
    # those gates without requiring duplicate operator timing or buyer facts.
    if (
        base_tier == "Lead"
        and suitable
        and suitable[0].get("quality") == "suitable"
        and closure_supply_interval is not None
        and closure_activity_interval is not None
        and all(_fact_covers_interval(row, closure_activity_interval) for row in closure_rows)
    ):
        required_low, required_high = required_interval
        available_low, available_high = closure_supply_interval
        remaining_low = max(Decimal(0), required_low - available_high)
        remaining_high = max(Decimal(0), required_high - available_low)
        supply_row = suitable_rows[0]
        fact_intersection = bool(
            demand and source_interval is not None and fact_interval is not None
        )
        ranged = (
            required_low != required_high or available_low != available_high or fact_intersection
        )
        if remaining_low == 0:
            result = {
                **base,
                "tier": "Prospect",
                "reason": (
                    "Accepted full-window suitable supply leaves a possible remaining gap "
                    f"of 0 to {_format_mw(remaining_high)} MW; retain an active Prospect "
                    "until the interval is resolved."
                ),
                "closed_by_fact": False,
            }
            for key in (
                "start_window",
                "duration",
                "qualified_remaining_gap",
                "qualification_next_action",
                "buying_role",
            ):
                result.pop(key, None)
            if fact_intersection:
                result["fact_derived_required_mw"] = _mw_presentation(required_interval)
            return result

        gap = {
            "required_mw": (
                _mw_presentation(required_interval)
                if ranged
                else _format_mw(required_low)
            ),
            "available_mw": (
                _mw_presentation(closure_supply_interval)
                if ranged
                else _format_mw(available_low)
            ),
            "value_kind": "Derived",
            "suitable_supply_basis": "User-confirmed",
            "suitable_supply_fact_id": str(supply_row.id),
            "suitable_supply_fact_hash": supply_row.content_hash,
            "source_semantic_hash": base.get("semantic_hash"),
            "source_evidence_hash": base.get("evidence_hash"),
            "source_reported_supply_quote": base.get("supply_quote"),
        }
        if ranged:
            gap.update(
                {
                    "required_mw_min": _format_mw(required_low),
                    "required_mw_max": _format_mw(required_high),
                    "available_mw_min": _format_mw(available_low),
                    "available_mw_max": _format_mw(available_high),
                    "remaining_mw_min": _format_mw(remaining_low),
                    "remaining_mw_max": _format_mw(remaining_high),
                    "calculation": "[max(0, required_min - suitable_max), "
                    "max(0, required_max - suitable_min)]",
                    "version": POWER_QUALIFICATION_VERSION,
                }
            )
            if remaining_low == remaining_high:
                gap["remaining_mw"] = _format_mw(remaining_low)
        else:
            gap["remaining_mw"] = _format_mw(remaining_low)
        result = {
            **base,
            "tier": "Lead",
            "qualified_remaining_gap": gap,
            "reason": (
                "Current official Lead support plus accepted full-window suitable supply "
                f"leaves a derived {_format_mw(remaining_low)} to "
                f"{_format_mw(remaining_high)} MW gap."
            ),
            "closed_by_fact": False,
        }
        if fact_intersection:
            assert fact_interval is not None
            result["fact_derived_required_mw"] = _mw_presentation(required_interval)
            demand_row = rows_by_type["demand"][0]
            gap["required_mw_basis"] = "User-confirmed intersection"
            gap["source_demand_mw"] = str(source_value)
            gap["user_confirmed_demand_mw"] = _mw_presentation(fact_interval)
            gap["demand_fact_id"] = str(demand_row.id)
            gap["demand_fact_hash"] = demand_row.content_hash
        return result

    if base_tier == "Lead":
        # A partial, unknown-quality, or otherwise unbound supply fact cannot
        # retract the already source-supported Lead calculation.
        return base

    result = dict(base)
    result.update(
        tier="Prospect",
        required_mw=_mw_presentation(required_interval),
        demand_mw=(
            base.get("demand_mw") or _mw_presentation(required_interval)
            if base_tier == "Prospect"
            else _mw_presentation(required_interval)
        ),
        reason=(
            "Current public support plus compatible accepted exact-need facts establish "
            "demand and unsuitable supply."
            if base_tier == "Signal"
            else base.get("reason")
        ),
    )
    timing = fields.get("timing", [])
    suitable = fields.get("suitable_supply", [])
    buyer = fields.get("buyer", [])
    timing_rows = rows_by_type.get("timing", [])
    suitable_rows = rows_by_type.get("suitable_supply", [])
    buyer_rows = rows_by_type.get("buyer", [])
    if not (timing and suitable and buyer):
        return result

    interval = _activity_interval(timing[0])
    if interval is None:
        return result
    lead_facts = [timing_rows[0], suitable_rows[0], buyer_rows[0]]
    if base_tier == "Signal":
        lead_facts.extend(
            (rows_by_type["demand"][0], rows_by_type["unsuitable_supply"][0])
        )
    elif demand:
        # A fact that narrows a public interval is a calculation input and must
        # cover the same complete activity window as timing and suitable supply.
        lead_facts.append(rows_by_type["demand"][0])
    if any(not _fact_covers_interval(row, interval) for row in lead_facts):
        return result

    available_interval = _fact_mw_interval(suitable[0], allow_zero=True)
    if suitable[0].get("quality") != "suitable" or available_interval is None:
        return result
    required_low, required_high = required_interval
    available_low, available_high = available_interval
    remaining_low = max(Decimal(0), required_low - available_high)
    remaining_high = max(Decimal(0), required_high - available_low)
    if remaining_low <= 0 or remaining_high <= 0:
        return result
    fact_intersection = (
        base_tier == "Prospect"
        and bool(demand)
        and source_interval is not None
        and fact_interval is not None
    )
    ranged = (
        required_low != required_high or available_low != available_high or fact_intersection
    )
    gap = {
        "required_mw": (
            _mw_presentation(required_interval) if ranged else _format_mw(required_low)
        ),
        "available_mw": (
            _mw_presentation(available_interval) if ranged else _format_mw(available_low)
        ),
        "value_kind": "Derived",
        "suitable_supply_basis": "User-confirmed",
        "suitable_supply_fact_id": str(suitable_rows[0].id),
        "suitable_supply_fact_hash": suitable_rows[0].content_hash,
        "source_semantic_hash": base.get("semantic_hash"),
        "source_evidence_hash": base.get("evidence_hash"),
        "source_reported_supply_quote": base.get("supply_quote"),
    }
    if (
        base_tier == "Prospect"
        and demand
        and source_interval is not None
        and fact_interval is not None
    ):
        demand_row = rows_by_type["demand"][0]
        gap.update(
            {
                "required_mw_basis": "User-confirmed intersection",
                "source_demand_mw": str(source_value),
                "user_confirmed_demand_mw": _mw_presentation(fact_interval),
                "demand_fact_id": str(demand_row.id),
                "demand_fact_hash": demand_row.content_hash,
            }
        )
    if ranged:
        gap.update(
            {
                "required_mw_min": _format_mw(required_low),
                "required_mw_max": _format_mw(required_high),
                "available_mw_min": _format_mw(available_low),
                "available_mw_max": _format_mw(available_high),
                "remaining_mw_min": _format_mw(remaining_low),
                "remaining_mw_max": _format_mw(remaining_high),
                "calculation": "[max(0, required_min - available_max), "
                "max(0, required_max - available_min)]",
                "version": POWER_QUALIFICATION_VERSION,
            }
        )
        if remaining_low == remaining_high:
            gap["remaining_mw"] = _format_mw(remaining_low)
    else:
        gap["remaining_mw"] = _format_mw(remaining_low)
    result.update(
        tier="Lead",
        start_window=f"{timing[0]['start_date']} to {timing[0]['end_date']}",
        duration=f"{timing[0]['duration_days']} days",
        supply="Constrained",
        qualification_next_action=(
            f"Contact {buyer[0]['organization']} to verify the open power package."
        ),
        qualified_remaining_gap=gap,
    )
    if fact_intersection:
        result["fact_derived_required_mw"] = _mw_presentation(required_interval)
    return result


def fact_digest(facts: list[Any]) -> str:
    return canonical_hash({"facts": [[str(row.id), row.content_hash] for row in facts]})
