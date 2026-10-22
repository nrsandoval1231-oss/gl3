"""Typed, exact-need operator facts and deterministic current qualification inputs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.domain.commercial_presentation import exact_mw_interval
from gridlens.domain.evaluation_clock import evaluation_now
from gridlens.domain.power_qualification import VERSION as POWER_QUALIFICATION_VERSION

FACT_TYPES = frozenset(
    {
        "demand",
        "unsuitable_supply",
        "suitable_supply",
        "timing",
        "buyer",
        "closure",
        "power_schedule",
    }
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
        "timing": {
            "start_date",
            "end_date",
            "duration_days",
            "corrects_source_semantic_hash",
            "corrects_source_evidence_hash",
        },
        "buyer": {"organization", "role"},
        "closure": {"state"},
        "power_schedule": {"phases", "supplies", "basis", "zero_supply_basis", "source_quote"},
    }
    if fact_type == "power_schedule":
        from gridlens.domain.power_schedule import validate_schedule

        return validate_schedule(value)
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
        correction_keys = {
            "corrects_source_semantic_hash",
            "corrects_source_evidence_hash",
        }
        supplied_correction_keys = correction_keys.intersection(value)
        if supplied_correction_keys and supplied_correction_keys != correction_keys:
            raise ValueError("timing correction must bind both current source hashes")
        if supplied_correction_keys:
            for key in sorted(correction_keys):
                source_hash = value.get(key)
                if (
                    not isinstance(source_hash, str)
                    or re.fullmatch(r"[0-9a-fA-F]{64}", source_hash) is None
                ):
                    raise ValueError("timing correction source hashes must be SHA-256 values")
                clean[key] = source_hash.lower()
            basis = value.get("basis")
            if not isinstance(basis, str) or not basis.strip():
                raise ValueError("timing correction requires a basis reason")
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


def _fact_mw_interval(value: dict[str, Any], *, allow_zero: bool) -> tuple[Decimal, Decimal] | None:
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
    current = now or evaluation_now(datetime.now(UTC))
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


def _finalize_lead_interval(
    result: dict[str, Any],
    interval: tuple[datetime, datetime] | None,
    *,
    source_claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep the current Lead gap's displayed interval aligned with its selected interval."""
    source_gap = result.get("qualified_remaining_gap")
    if not isinstance(source_gap, dict):
        return result

    gap = dict(source_gap)
    if result.get("start_window") is not None:
        gap["start_window"] = result["start_window"]
    if result.get("duration") is not None:
        gap["duration"] = result["duration"]
    if interval is not None and (
        "selected_activity_interval_start" in gap
        or "selected_activity_interval_end_exclusive" in gap
    ):
        gap["selected_activity_interval_start"] = interval[0].isoformat()
        gap["selected_activity_interval_end_exclusive"] = interval[1].isoformat()
    if source_claim is not None and (
        result.get("start_window") != source_claim.get("start_window")
        or result.get("duration") != source_claim.get("duration")
    ):
        if source_claim.get("start_window") is not None:
            gap.setdefault("source_reported_start_window", source_claim["start_window"])
        if source_claim.get("duration") is not None:
            gap.setdefault("source_reported_duration", source_claim["duration"])
    result["qualified_remaining_gap"] = gap
    return result


def _source_lead_timing_bounds(
    claim: dict[str, Any],
) -> tuple[date, date, int, int] | None:
    """Read the already-qualified official Lead's complete source timing bounds."""
    start_window = claim.get("start_window")
    duration = claim.get("duration")
    if not isinstance(start_window, str) or not isinstance(duration, str):
        return None
    starts = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", start_window)
    duration_match = re.fullmatch(r"(\d{1,6})(?: to (\d{1,6}))? days", duration)
    if starts is None or duration_match is None:
        return None
    try:
        first_start = date.fromisoformat(starts[1])
        last_start = date.fromisoformat(starts[2])
        min_days = int(duration_match[1])
        max_days = int(duration_match[2] or duration_match[1])
        if first_start > last_start or min_days <= 0 or max_days < min_days:
            return None
        return first_start, last_start, min_days, max_days
    except (TypeError, ValueError, OverflowError):
        return None


def _source_lead_activity_interval(claim: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Replay the already-qualified official Lead's complete possible activity window."""
    bounds = _source_lead_timing_bounds(claim)
    if bounds is None:
        return None
    first_start, last_start, _, max_days = bounds
    return _activity_interval(
        {
            "start_date": first_start.isoformat(),
            "end_date": last_start.isoformat(),
            "duration_days": max_days,
        }
    )


def _timing_resolution(
    base: dict[str, Any],
    base_tier: str,
    timing: dict[str, Any] | None,
) -> tuple[tuple[datetime, datetime] | None, str, bool]:
    """Resolve an operator timing report against the current source Lead interval."""
    source_interval = _source_lead_activity_interval(base) if base_tier == "Lead" else None
    if timing is None:
        return (
            source_interval if base_tier == "Lead" else None,
            "source_reported" if source_interval is not None else "none",
            False,
        )
    operator_interval = _activity_interval(timing)
    if operator_interval is None:
        return None, "invalid_operator_timing", base_tier == "Lead"
    if base_tier != "Lead":
        return operator_interval, "operator_timing", False

    source_bounds = _source_lead_timing_bounds(base)
    semantic_hash = base.get("semantic_hash")
    evidence_hash = base.get("evidence_hash")
    corrects_semantic = timing.get("corrects_source_semantic_hash")
    corrects_evidence = timing.get("corrects_source_evidence_hash")
    has_correction_marker = corrects_semantic is not None or corrects_evidence is not None
    if has_correction_marker:
        marker_current = (
            isinstance(semantic_hash, str)
            and isinstance(evidence_hash, str)
            and corrects_semantic == semantic_hash
            and corrects_evidence == evidence_hash
            and isinstance(timing.get("basis"), str)
            and bool(timing["basis"].strip())
        )
        if marker_current and source_bounds is not None:
            return operator_interval, "explicit_source_correction", False
        return None, "stale_or_unbound_source_correction", True

    if source_bounds is None:
        # The timing fact may fill a missing Prospect-style gate, but cannot
        # identify or replace a source Lead interval that cannot be replayed.
        return operator_interval, "operator_timing_missing_source_window", False
    if source_interval is None:
        return None, "unreplayable_source_timing", True
    try:
        op_first = date.fromisoformat(str(timing["start_date"]))
        op_last = date.fromisoformat(str(timing["end_date"]))
        op_days = timing["duration_days"]
    except (KeyError, TypeError, ValueError):
        return None, "invalid_operator_timing", True
    source_first, source_last, source_min_days, source_max_days = source_bounds
    if (
        source_first <= op_first <= op_last <= source_last
        and source_min_days <= op_days <= source_max_days
    ):
        return operator_interval, "compatible_narrowing", False
    return None, "unresolved_source_timing_conflict", True


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
        not isinstance(ends_at, datetime) or ends_at.tzinfo is None or ends_at.utcoffset() is None
    ):
        return False
    start, end = interval
    starts_at = starts_at.astimezone(UTC)
    ends_at = ends_at.astimezone(UTC) if ends_at is not None else None
    return starts_at <= start and (ends_at is None or ends_at >= end)


def _demote_source_lead_for_timing_correction(
    base: dict[str, Any],
    timing: dict[str, Any],
    timing_row: Any,
    selected_interval: tuple[datetime, datetime] | None,
    timing_resolution: str,
) -> dict[str, Any]:
    covers_interval = bool(
        selected_interval is not None and _fact_covers_interval(timing_row, selected_interval)
    )
    result = {
        **base,
        "tier": "Prospect" if base.get("supply_quote") else "Signal",
        "closed_by_fact": False,
        "reason": (
            "The current source-reported Lead window "
            f"{base.get('start_window')} / {base.get('duration')} was corrected to "
            f"{timing['start_date']} / {timing['duration_days']} days by accepted "
            f"timing fact {timing_row.id} ({timing_row.content_hash}) bound to current "
            f"source hashes {base.get('semantic_hash')} / {base.get('evidence_hash')}; "
            "no supported suitable-supply assessment covers the corrected activity interval, "
            "so the prior Lead gap cannot be carried forward. Original source report and any "
            "supply quote remain preserved."
        ),
    }
    if covers_interval and selected_interval is not None:
        result["fact_derived_timing"] = {
            "start_window": f"{timing['start_date']} to {timing['end_date']}",
            "duration": f"{timing['duration_days']} days",
            "basis": "User-confirmed",
            "fact_id": str(timing_row.id),
            "fact_hash": timing_row.content_hash,
            "source_semantic_hash": base.get("semantic_hash"),
            "source_evidence_hash": base.get("evidence_hash"),
            "resolution": timing_resolution,
            "selected_interval_start": selected_interval[0].isoformat(),
            "selected_interval_end_exclusive": selected_interval[1].isoformat(),
            "reported_start_window": base.get("start_window"),
            "reported_duration": base.get("duration"),
        }
    for key in (
        "start_window",
        "duration",
        "qualified_remaining_gap",
        "qualification_next_action",
        "buying_role",
    ):
        result.pop(key, None)
    return result


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
    qualification_facts = [row for row in facts if row.fact_type != "power_schedule"]
    if any(
        row.project_id != need.project_id
        or row.activity_key != need.activity_key
        or row.facility_scope.strip().casefold() != (project.location or "").strip().casefold()
        for row in qualification_facts
    ):
        return {
            **base,
            "tier": "Signal",
            "qualification_conflict": True,
            "reason": "Accepted operator fact is bound to a different activity or facility.",
        }
    fields: dict[str, list[Any]] = {}
    rows_by_type: dict[str, list[Any]] = {}
    for row in qualification_facts:
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
    timing_row = timing_rows[0] if timing_rows else None
    resolved_activity_interval, timing_resolution, timing_conflict = _timing_resolution(
        base,
        str(base_tier),
        timing[0] if timing else None,
    )
    if timing_conflict:
        conflict = {
            **base,
            "tier": "Signal" if need.activity_key == "project-discovery" else "Prospect",
            "qualification_conflict": True,
            "closed_by_fact": False,
            "reason": (
                "Accepted timing conflicts with the current source Lead interval or does not "
                "correct its exact current source version; retain the source timing report and "
                f"leave this need active pending an attributed correction. Timing fact "
                f"{timing_rows[0].id} ({timing_rows[0].content_hash}); current source "
                f"reported window {base.get('start_window')} / {base.get('duration')}; "
                f"operator basis {timing[0].get('basis')}; semantic hash "
                f"{base.get('semantic_hash')}, evidence hash {base.get('evidence_hash')}."
            ),
        }
        for key in (
            "start_window",
            "duration",
            "qualified_remaining_gap",
            "qualification_next_action",
            "buying_role",
        ):
            conflict.pop(key, None)
        return conflict
    if base_tier == "Signal":
        closure_demand = fact_interval
        closure_has_shortage_support = bool(closure_demand and unsuitable)
    else:
        closure_demand = calculation_demand
        closure_has_shortage_support = bool(
            closure_demand and source_interval is not None and base.get("supply_quote")
        )
    closure_activity_interval = resolved_activity_interval
    closure_rows = list(suitable_rows[:1])
    if timing_rows:
        closure_rows.append(timing_rows[0])
    if demand and (base_tier == "Signal" or fact_interval is not None):
        closure_rows.append(rows_by_type["demand"][0])
    if base_tier == "Signal" and unsuitable:
        closure_rows.append(rows_by_type["unsuitable_supply"][0])
    closure_supply_interval = _fact_mw_interval(suitable[0], allow_zero=True) if suitable else None
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
        if timing_row is not None:
            basis.update(
                {
                    "timing_fact_id": str(timing_row.id),
                    "timing_fact_hash": timing_row.content_hash,
                    "timing_resolution": timing_resolution,
                    "timing_basis": timing_row.value.get("basis"),
                    "timing_source_semantic_hash": source_semantic_hash,
                    "timing_source_evidence_hash": source_evidence_hash,
                    "source_reported_start_window": base.get("start_window"),
                    "source_reported_duration": base.get("duration"),
                }
            )
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

    # Discovery records identify a site event, not a power phase. Keep the
    # accepted facts and closure/conflict handling above, but do not treat facts
    # bound to this neutral placeholder as phase-specific qualification.
    if need.activity_key == "project-discovery":
        result = {
            **base,
            "tier": "Signal",
            "demand_mw": None,
            "required_mw": None,
            "reason": "A supported power activity is required before qualification.",
        }
        for key in (
            "start_window",
            "duration",
            "qualified_remaining_gap",
            "qualification_next_action",
            "buying_role",
            "fact_derived_required_mw",
        ):
            result.pop(key, None)
        return result

    # A source-supported Prospect already establishes activity-specific demand
    # and unsuitable supply. Signal needs compatible exact-need facts for both.
    if base_tier in {"Prospect", "Lead"}:
        required_interval = calculation_demand
    else:
        required_interval = fact_interval
    has_unsuitable = bool(unsuitable) if base_tier == "Signal" else bool(base.get("supply_quote"))
    if required_interval is None or not has_unsuitable:
        if (
            base_tier == "Lead"
            and timing_resolution == "explicit_source_correction"
            and timing_row is not None
            and timing
        ):
            return _demote_source_lead_for_timing_correction(
                base, timing[0], timing_row, resolved_activity_interval, timing_resolution
            )
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
                _mw_presentation(required_interval) if ranged else _format_mw(required_low)
            ),
            "available_mw": (
                _mw_presentation(closure_supply_interval) if ranged else _format_mw(available_low)
            ),
            "value_kind": "Derived",
            "suitable_supply_basis": "User-confirmed",
            "suitable_supply_fact_id": str(supply_row.id),
            "suitable_supply_fact_hash": supply_row.content_hash,
            "source_semantic_hash": base.get("semantic_hash"),
            "source_evidence_hash": base.get("evidence_hash"),
            "source_reported_supply_quote": base.get("supply_quote"),
        }
        if timing_row is not None:
            assert resolved_activity_interval is not None
            gap.update(
                {
                    "timing_fact_id": str(timing_row.id),
                    "timing_fact_hash": timing_row.content_hash,
                    "timing_resolution": timing_resolution,
                    "timing_basis": timing_row.value.get("basis"),
                    "timing_source_semantic_hash": base.get("semantic_hash"),
                    "timing_source_evidence_hash": base.get("evidence_hash"),
                    "selected_activity_interval_start": resolved_activity_interval[0].isoformat(),
                    "selected_activity_interval_end_exclusive": resolved_activity_interval[
                        1
                    ].isoformat(),
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
            **(
                {
                    "start_window": (f"{timing[0]['start_date']} to {timing[0]['end_date']}"),
                    "duration": f"{timing[0]['duration_days']} days",
                }
                if timing_resolution in {"compatible_narrowing", "explicit_source_correction"}
                and timing
                else {}
            ),
            "qualified_remaining_gap": gap,
            "reason": (
                "Current official Lead support plus accepted full-window suitable supply "
                f"leaves a derived {_format_mw(remaining_low)} to "
                f"{_format_mw(remaining_high)} MW gap."
            ),
            "closed_by_fact": False,
        }
        if timing_row is not None and timing_resolution in {
            "compatible_narrowing",
            "explicit_source_correction",
        }:
            gap["source_reported_start_window"] = base.get("start_window")
            gap["source_reported_duration"] = base.get("duration")
        if fact_intersection:
            assert fact_interval is not None
            result["fact_derived_required_mw"] = _mw_presentation(required_interval)
            demand_row = rows_by_type["demand"][0]
            gap["required_mw_basis"] = "User-confirmed intersection"
            gap["source_demand_mw"] = str(source_value)
            gap["user_confirmed_demand_mw"] = _mw_presentation(fact_interval)
            gap["demand_fact_id"] = str(demand_row.id)
            gap["demand_fact_hash"] = demand_row.content_hash
        return _finalize_lead_interval(result, resolved_activity_interval)

    if base_tier == "Lead":
        if timing_resolution == "explicit_source_correction" and timing_row is not None:
            return _demote_source_lead_for_timing_correction(
                base, timing[0], timing_row, resolved_activity_interval, timing_resolution
            )

        if (
            timing_resolution == "compatible_narrowing"
            and timing_row is not None
            and resolved_activity_interval is not None
            and _fact_covers_interval(timing_row, resolved_activity_interval)
        ):
            result = {
                **base,
                "start_window": f"{timing[0]['start_date']} to {timing[0]['end_date']}",
                "duration": f"{timing[0]['duration_days']} days",
            }
            existing_gap = base.get("qualified_remaining_gap")
            if isinstance(existing_gap, dict):
                gap = dict(existing_gap)
                gap.update(
                    {
                        "timing_fact_id": str(timing_row.id),
                        "timing_fact_hash": timing_row.content_hash,
                        "timing_resolution": timing_resolution,
                        "timing_basis": timing_row.value.get("basis"),
                        "timing_source_semantic_hash": base.get("semantic_hash"),
                        "timing_source_evidence_hash": base.get("evidence_hash"),
                        "selected_activity_interval_start": resolved_activity_interval[
                            0
                        ].isoformat(),
                        "selected_activity_interval_end_exclusive": resolved_activity_interval[
                            1
                        ].isoformat(),
                        "source_reported_start_window": base.get("start_window"),
                        "source_reported_duration": base.get("duration"),
                    }
                )
                result["qualified_remaining_gap"] = gap
            return _finalize_lead_interval(result, resolved_activity_interval)

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
        lead_facts.extend((rows_by_type["demand"][0], rows_by_type["unsuitable_supply"][0]))
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
    ranged = required_low != required_high or available_low != available_high or fact_intersection
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
    if timing_row is not None:
        gap.update(
            {
                "timing_fact_id": str(timing_row.id),
                "timing_fact_hash": timing_row.content_hash,
                "timing_resolution": timing_resolution,
                "timing_basis": timing_row.value.get("basis"),
                "timing_source_semantic_hash": base.get("semantic_hash"),
                "timing_source_evidence_hash": base.get("evidence_hash"),
                "selected_activity_interval_start": interval[0].isoformat(),
                "selected_activity_interval_end_exclusive": interval[1].isoformat(),
            }
        )
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
    return _finalize_lead_interval(result, interval, source_claim=base)


def fact_digest(facts: list[Any]) -> str:
    return canonical_hash(
        {
            "facts": [
                [str(row.id), row.content_hash]
                for row in facts
                if row.fact_type != "power_schedule"
            ]
        }
    )
