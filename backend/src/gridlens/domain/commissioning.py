"""Conservative commissioning test-plan arithmetic; never a campus-MW multiplier.

This pure model consumes admitted, project-scoped evidence. It cannot establish
source truth or customer rental demand and does no research or persistence.
"""

from __future__ import annotations

import json
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext
from hashlib import sha256
from typing import Any

MODEL_VERSION = "commissioning-test-plan-v1.0.0"
_CONTEXT = Context(prec=40, rounding=ROUND_HALF_EVEN)
_DEFAULT_CONFIG = {"decimal_places": 6, "max_blocks": 1000}
_LIMITATIONS = [
    "Engineering scenario, not verified customer demand or a temporary/bridge-power "
    "rental requirement.",
    "Scope is the supplied test plan; installed capacity and campus capacity are not "
    "commissioning demand.",
    "No allowance for unreported auxiliaries, transients, power quality, cabling or "
    "redundant test banks.",
    "Supply source and customer procurement intent are unknown unless independently verified.",
]


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _decimal(value: Any, field: str, *, maximum: str, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ValueError(f"{field}: a finite decimal is required")
    text = str(value)
    if len(text) > 100:
        raise ValueError(f"{field}: numeric input exceeds supported length")
    try:
        number = Decimal(text)
    except ArithmeticError as exc:
        raise ValueError(f"{field}: a finite decimal is required") from exc
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise ValueError(
            f"{field}: a finite {'nonnegative' if allow_zero else 'positive'} decimal is required"
        )
    if number > Decimal(maximum):
        raise ValueError(f"{field}: value exceeds supported bound")
    return number


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError(f"{field}: a bounded explicit scope is required")
    return value.strip()


def _count(value: Any, installed: int, field: str) -> int:
    if type(value) is not int or value < 1 or value > installed:
        raise ValueError(f"{field}: count must be an integer between 1 and installed_units")
    return value


def _evidence(value: Any, field: str, project_id: str) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError(f"{field}: project-specific input evidence is required")
    for reference in value:
        if not isinstance(reference, dict) or not any(
            isinstance(reference.get(key), str) and reference[key].strip()
            for key in ("url", "source_url", "document_ref", "evidence_id")
        ):
            raise ValueError(f"{field}: source URL or document/evidence reference is required")
        if reference.get("project_id") != project_id:
            raise ValueError(f"{field}: evidence belongs to another project")
    return value


def _format(value: Decimal, places: int, rounding: str = ROUND_HALF_EVEN) -> str:
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=rounding)
    return format(rounded, "f").rstrip("0").rstrip(".") if places else format(rounded, "f")


def estimate_commissioning(inputs: list[dict], *, config: dict | None = None) -> dict:
    """Return a source-bound electrical test scenario or explicit abstention.

    Concurrent blocks share ``sequence_stage``. Stages are sequential. Distinct
    ``load_scope_id`` values must describe proven disjoint electrical loads;
    upstream and downstream tests of one load use the SAME scope ID.
    All blocks must belong to one project. Callers admit evidence and ensure the
    plan is complete for its stated scope before invoking this calculation.
    """
    effective = dict(_DEFAULT_CONFIG)
    if config is not None:
        if not isinstance(config, dict) or set(config) - set(effective):
            raise ValueError("Unsupported commissioning configuration")
        effective.update(config)
    if type(effective["decimal_places"]) is not int or not 0 <= effective["decimal_places"] <= 9:
        raise ValueError("decimal_places must be an integer from 0 through 9")
    if type(effective["max_blocks"]) is not int or not 1 <= effective["max_blocks"] <= 10000:
        raise ValueError("max_blocks must be an integer from 1 through 10000")
    result: dict = {
        "status": "insufficient_data",
        "low_mw": None,
        "base_mw": None,
        "high_mw": None,
        "confidence": "insufficient",
        "demand_class": "engineering_scenario",
        "verified_customer_demand": False,
        "calculation_version": MODEL_VERSION,
        "config": effective,
        "config_digest": _digest(effective),
        "input_digest": _digest(sorted(inputs, key=_digest)) if isinstance(inputs, list) else None,
        "input_evidence": [],
        "assumptions": [],
        "limitations": list(_LIMITATIONS),
        "stage_demands": [],
    }
    if not isinstance(inputs, list) or not inputs or len(inputs) > effective["max_blocks"]:
        result["limitations"].append(
            "A nonempty bounded, project-specific commissioning test plan is required."
        )
        return result
    try:
        with localcontext(_CONTEXT):
            stages: dict[str, dict[str, Decimal]] = {}
            seen_blocks: set[str] = set()
            seen_loads: set[tuple[str, str]] = set()
            projects: set[str] = set()
            refs: dict[str, dict] = {}
            has_scenarios = any(
                isinstance(item, dict) and item.get("scenarios") is not None for item in inputs
            )
            for item in inputs:
                if not isinstance(item, dict):
                    raise ValueError("Every test block must be a structured record")
                project = _name(item.get("project_id"), "project_id")
                projects.add(project)
                if len(projects) != 1:
                    raise ValueError(
                        "Independent projects cannot be assumed to commission concurrently"
                    )
                block = _name(item.get("block_id"), "block_id")
                if block in seen_blocks:
                    raise ValueError("Duplicate test block identity; cannot double count")
                seen_blocks.add(block)
                stage = _name(item.get("sequence_stage"), "sequence_stage")
                load = _name(item.get("load_scope_id"), "load_scope_id")
                if (stage, load) in seen_loads:
                    raise ValueError(
                        "Duplicate load scope within a stage; upstream/downstream loads "
                        "cannot be added"
                    )
                seen_loads.add((stage, load))
                evidence = item.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("rating, test_fraction and sequence evidence is required")
                for field in ("rating", "test_fraction", "sequence"):
                    for ref in _evidence(evidence.get(field), field, project):
                        refs[_digest(ref)] = ref
                if item.get("rating_basis") not in ("electrical_input", "electrical_output"):
                    raise ValueError(
                        "rating_basis: explicit electrical input/output basis is required"
                    )
                rating = _decimal(item.get("rating"), "rating", maximum="1000000000")
                unit = item.get("unit")
                if unit == "MW":
                    rating_mw = rating
                elif unit in ("kW", "kVA"):
                    rating_mw = rating / Decimal(1000)
                    if unit == "kVA":
                        power_factor = _decimal(
                            item.get("power_factor"), "power_factor", maximum="1"
                        )
                        for ref in _evidence(evidence.get("power_factor"), "power_factor", project):
                            refs[_digest(ref)] = ref
                        rating_mw *= power_factor
                else:
                    raise ValueError(
                        "unit: only electrical MW, kW or evidenced-power-factor kVA is supported"
                    )
                installed = item.get("installed_units")
                if type(installed) is not int or not 1 <= installed <= 100000:
                    raise ValueError("installed_units: a positive bounded integer is required")
                fraction = _decimal(
                    item.get("test_fraction"), "test_fraction", maximum="1", allow_zero=True
                )
                concurrent = _count(item.get("concurrent_units"), installed, "concurrent_units")
                demands = {"base": rating_mw * fraction * concurrent}
                if has_scenarios:
                    scenarios = item.get("scenarios")
                    if not isinstance(scenarios, dict) or set(scenarios) != {"low", "high"}:
                        raise ValueError(
                            "All blocks require both low/high scenarios to publish a range"
                        )
                    for ref in _evidence(evidence.get("scenarios"), "scenarios", project):
                        refs[_digest(ref)] = ref
                    for scenario in ("low", "high"):
                        spec = scenarios[scenario]
                        if not isinstance(spec, dict):
                            raise ValueError(
                                "Scenario must define test_fraction and concurrent_units"
                            )
                        scenario_fraction = _decimal(
                            spec.get("test_fraction"),
                            f"{scenario}.test_fraction",
                            maximum="1",
                            allow_zero=True,
                        )
                        scenario_count = _count(
                            spec.get("concurrent_units"), installed, f"{scenario}.concurrent_units"
                        )
                        demands[scenario] = rating_mw * scenario_fraction * scenario_count
                    if not demands["low"] <= demands["base"] <= demands["high"]:
                        raise ValueError(
                            "Scenario range must bound the base demand for every block"
                        )
                subtotal = stages.setdefault(stage, {key: Decimal(0) for key in demands})
                for scenario, demand in demands.items():
                    subtotal[scenario] += demand
            places = effective["decimal_places"]
            peak = max(value["base"] for value in stages.values())
            reported_peak = _format(peak, places)
            if peak > 0 and Decimal(reported_peak) == 0:
                raise ValueError("Positive scenario is below configured reporting precision")
            result.update(
                status="estimated",
                confidence="medium"
                if all(ref.get("verification_status") == "verified" for ref in refs.values())
                else "low",
                base_mw=reported_peak,
                input_evidence=[refs[key] for key in sorted(refs)],
                stage_demands=[
                    {
                        "sequence_stage": stage,
                        **{
                            f"{key}_mw": _format(value, places)
                            for key, value in sorted(stages[stage].items())
                        },
                    }
                    for stage in sorted(stages)
                ],
                assumptions=[
                    "Evidence-admitted electrical ratings, loading fractions and concurrent "
                    "unit counts apply to the stated project test scope.",
                    "Distinct load scopes in a stage are electrically disjoint; stages are "
                    "sequential, so the scenario is their peak rather than their sum.",
                    "Ratings use active electrical MW; kVA is converted only with an "
                    "evidenced power factor.",
                    f"Decimal output uses {places} places as a calculation reporting limit, "
                    "not a claim of source precision.",
                ],
            )
            if has_scenarios:
                result["low_mw"] = _format(
                    max(value["low"] for value in stages.values()), places, ROUND_FLOOR
                )
                result["high_mw"] = _format(
                    max(value["high"] for value in stages.values()), places, ROUND_CEILING
                )
    except (ValueError, ArithmeticError) as exc:
        result["limitations"].append(str(exc))
    return result
