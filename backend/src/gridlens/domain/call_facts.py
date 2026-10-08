"""Typed, exact-need operator facts and deterministic current qualification inputs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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
        "demand": {"mw"},
        "unsuitable_supply": {"mw"},
        "suitable_supply": {"mw", "quality"},
        "timing": {"start_date", "end_date", "duration_days"},
        "buyer": {"organization", "role"},
        "closure": {"state"},
    }
    allowed = fields_by_type[fact_type] | {"basis", "source_quote"}
    if set(value) - allowed:
        raise ValueError("Fact value contains unsupported fields")
    clean: dict[str, Any] = {}
    if fact_type in {"demand", "unsuitable_supply", "suitable_supply"}:
        amount = value.get("mw")
        try:
            number = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            raise ValueError("mw must be a positive numeric value") from None
        if not number.is_finite() or number <= 0 or number > Decimal("1000000"):
            raise ValueError("mw must be positive and within the supported range")
        clean["mw"] = format(number.normalize(), "f")
        if fact_type == "suitable_supply" and value.get("quality") not in {
            "suitable",
            "unsuitable",
            "unknown",
        }:
            raise ValueError("suitable supply requires an explicit quality")
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
    for row in facts:
        fields.setdefault(row.fact_type, []).append(row.value)
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
    if demand and (base.get("demand_mw") or base.get("required_mw")):
        retained = str(base.get("demand_mw") or base.get("required_mw") or "")
        found = re.search(r"\d+(?:\.\d+)?", retained)
        if found and Decimal(found.group()) != Decimal(demand[0]["mw"]):
            return {
                **base,
                "tier": "Signal",
                "qualification_conflict": True,
                "reason": "Accepted operator demand conflicts with current public source support.",
            }
    if demand and unsuitable:
        # Current public evidence is the mandatory base; exact typed facts fill only
        # fields that the canonical source assessment does not already establish.
        if base.get("tier") == "Signal":
            result = {
                **base,
                "tier": "Prospect",
                "required_mw": f"{demand[0]['mw']} MW",
                "demand_mw": f"{demand[0]['mw']} MW",
                "reason": (
                    "Current public support plus compatible accepted exact-need facts establish "
                    "demand and unsuitable supply."
                ),
            }
            timing = fields.get("timing", [])
            suitable = fields.get("suitable_supply", [])
            buyer = fields.get("buyer", [])
            if timing and suitable and buyer:
                available = Decimal(suitable[0]["mw"])
                required = Decimal(demand[0]["mw"])
                if suitable[0].get("quality") == "suitable" and available < required:
                    result.update(
                        tier="Lead",
                        start_window=f"{timing[0]['start_date']} to {timing[0]['end_date']}",
                        duration=f"{timing[0]['duration_days']} days",
                        supply="Constrained",
                        qualification_next_action=(
                            f"Contact {buyer[0]['organization']} to verify the open power package."
                        ),
                        qualified_remaining_gap={
                            "required_mw": str(required),
                            "available_mw": str(available),
                            "remaining_mw": str(required - available),
                            "value_kind": "Derived",
                        },
                    )
            return result
    return base


def fact_digest(facts: list[Any]) -> str:
    return canonical_hash({"facts": [[str(row.id), row.content_hash] for row in facts]})
