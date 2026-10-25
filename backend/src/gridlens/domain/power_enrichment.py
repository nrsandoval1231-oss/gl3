"""Evidence-safe, non-qualifying power scenarios for project enrichment."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gridlens.domain.power_schedule import PowerScheduleProjection, project_schedule

ActivityKind = Literal[
    "facility_demand", "construction", "commissioning", "bridge", "backup", "other"
]


class PowerEnrichmentSource(BaseModel):
    """A dated reference to a fact used in a scenario."""

    model_config = ConfigDict(extra="forbid")

    fact_version_id: str | None = None
    content_hash: str | None = None
    authority: str | None = None
    source_reference: str | None = None
    source_date: str | None = None
    source_quote: str | None = None
    confirmed_at: str | None = None
    reporter_name: str | None = None
    reporter_organization: str | None = None
    reporter_role: str | None = None


class RentalValueEstimate(BaseModel):
    """Transparent arithmetic from an explicit, sourced rental rate."""

    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"] = "USD"
    minimum: str
    maximum: str
    rate_min_usd_per_mw_day: str
    rate_max_usd_per_mw_day: str
    rate_source_reference: str
    rate_source_date: str
    duration_days: int
    formula: str = "residual MW × duration days × sourced USD/MW/day rate"
    status: Literal["estimate"] = "estimate"


class PowerScenario(BaseModel):
    """One independently scoped phase and one base or alternative schedule."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    need_id: str
    activity_key: str
    activity_kind: ActivityKind
    facility_scope: str
    phase_id: str
    scenario: Literal["base", "alternative"]
    evidence_status: Literal["fact", "estimate", "hypothesis", "conflict"]
    start_date: str
    end_date: str
    duration_days_min: int
    duration_days_max: int
    demand_mw_min: str
    demand_mw_max: str
    supply_mw_min: str | None
    supply_mw_max: str | None
    residual_mw_min: str | None
    residual_mw_max: str | None
    supply_status: Literal["supported", "unknown", "conflict"]
    fuel_status: Literal["unknown"] = "unknown"
    demand_basis: str
    supply_basis: list[str] = Field(default_factory=list)
    sources: list[PowerEnrichmentSource] = Field(default_factory=list)
    basis: str
    rental_value: RentalValueEstimate | None = None


class PowerEnrichment(BaseModel):
    """Read-only evidence projection; this model does not assign qualification."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUPPORTED", "UNRESOLVED", "CONFLICT", "NO_EVIDENCE"]
    scenarios: list[PowerScenario] = Field(default_factory=list)
    basis: str


_ACTIVITY_KIND: dict[str, ActivityKind] = {
    "facility-demand": "facility_demand",
    "facility_demand": "facility_demand",
    "facility-load": "facility_demand",
    "facility_load": "facility_demand",
    "construction": "construction",
    "facility-expansion": "construction",
    "commissioning": "commissioning",
    "bridge": "bridge",
    "bridge-temporary": "bridge",
    "bridge_temporary": "bridge",
    "backup": "backup",
    "backup-power": "backup",
    "backup_power": "backup",
}

_ESTIMATE_MARKERS = (
    "estimate",
    "estimated",
    "projection",
    "projected",
    "forecast",
    "budgetary",
    "planning range",
)
_HYPOTHESIS_MARKERS = ("hypothesis", "hypothetical", "assumption", "illustrative")


def _evidence_status(*bases: str) -> Literal["fact", "estimate", "hypothesis"]:
    searchable = " ".join(bases).casefold()
    if any(marker in searchable for marker in _HYPOTHESIS_MARKERS):
        return "hypothesis"
    if any(marker in searchable for marker in _ESTIMATE_MARKERS):
        return "estimate"
    return "fact"


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite nonnegative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a finite nonnegative number") from None
    if not number.is_finite() or number < 0 or number > 1_000_000:
        raise ValueError(f"{field} must be within the supported range")
    return number


def _rental_value(
    *,
    residual_min: str | None,
    residual_max: str | None,
    duration_days: int,
    rate: dict[str, Any] | None,
) -> RentalValueEstimate | None:
    if rate is None or residual_min is None or residual_max is None:
        return None
    required = {
        "rate_min_usd_per_mw_day",
        "rate_max_usd_per_mw_day",
        "source_reference",
        "source_date",
    }
    if set(rate) != required:
        raise ValueError("rental rate requires bounded rates and dated source provenance")
    source_ref = rate["source_reference"]
    source_date = rate["source_date"]
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("rental rate requires a source reference")
    if not isinstance(source_date, str):
        raise ValueError("rental rate source_date must be an ISO date")
    try:
        date.fromisoformat(source_date)
    except ValueError:
        raise ValueError("rental rate source_date must be a real ISO date") from None
    rate_min = _decimal(rate["rate_min_usd_per_mw_day"], "minimum rental rate")
    rate_max = _decimal(rate["rate_max_usd_per_mw_day"], "maximum rental rate")
    residual_low = _decimal(residual_min, "minimum residual demand")
    residual_high = _decimal(residual_max, "maximum residual demand")
    if rate_max < rate_min or residual_high < residual_low:
        raise ValueError("rental rate and residual intervals must be ordered")
    return RentalValueEstimate(
        minimum=str(residual_low * duration_days * rate_min),
        maximum=str(residual_high * duration_days * rate_max),
        rate_min_usd_per_mw_day=str(rate_min),
        rate_max_usd_per_mw_day=str(rate_max),
        rate_source_reference=source_ref.strip(),
        rate_source_date=source_date,
        duration_days=duration_days,
    )


def build_power_enrichment(
    *,
    project: dict[str, Any],
    needs: list[dict[str, Any]],
    operator_facts: list[dict[str, Any]],
    rental_rate: dict[str, Any] | None = None,
) -> PowerEnrichment:
    """Build exact-scope scenarios from accepted facts without changing qualification.

    `needs` is the caller's canonical need projection. Each schedule fact is accepted
    only when its project, need, activity and facility scope match exactly. Unknown or
    incomplete supply stays null through the existing power schedule projector.
    """
    project_id = str(project.get("id") or "").strip()
    if not project_id:
        raise ValueError("project requires an id")
    if not isinstance(needs, list) or not isinstance(operator_facts, list):
        raise ValueError("needs and operator_facts must be lists")

    scenarios: list[PowerScenario] = []
    unresolved = False
    conflict = False
    for need in needs:
        if not isinstance(need, dict):
            raise ValueError("each need must be an object")
        need_id = str(need.get("id") or "").strip()
        activity_key = str(need.get("activity_key") or "").strip()
        facility_scope = " ".join(str(need.get("facility_scope") or "").split())
        if not need_id or not activity_key or not facility_scope:
            continue
        if str(need.get("project_id") or project_id) != project_id:
            continue
        schedule_facts = [
            fact
            for fact in operator_facts
            if isinstance(fact, dict)
            and fact.get("fact_type") == "power_schedule"
            and str(fact.get("project_id") or "") == project_id
            and str(fact.get("need_id") or "") == need_id
            and str(fact.get("activity_key") or "") == activity_key
            and " ".join(str(fact.get("facility_scope") or "").split()).casefold()
            == facility_scope.casefold()
        ]
        projected: PowerScheduleProjection | None = project_schedule(schedule_facts)
        if projected is None:
            continue
        if projected.status == "CONFLICT":
            conflict = True
            unresolved = True
            continue
        unresolved |= projected.status == "UNRESOLVED"
        activity_kind = _ACTIVITY_KIND.get(activity_key.casefold(), "other")
        fact_dates = {
            str(fact.get("fact_version_id")): fact.get("source_date") for fact in schedule_facts
        }
        source_refs = [
            PowerEnrichmentSource.model_validate(
                {
                    **ref.model_dump(),
                    "source_date": fact_dates.get(str(ref.fact_version_id)),
                }
            )
            for ref in projected.fact_refs
        ]
        for segment in projected.segments:
            start = date.fromisoformat(segment.start_date)
            end = date.fromisoformat(segment.end_date)
            duration_days = (end - start).days
            is_hypothesis = segment.scenario == "alternative"
            supply_status: Literal["supported", "unknown", "conflict"] = (
                "unknown"
                if segment.supply_min_mw is None or segment.supply_max_mw is None
                else "supported"
            )
            value = _rental_value(
                residual_min=segment.residual_min_mw,
                residual_max=segment.residual_max_mw,
                duration_days=duration_days,
                rate=rental_rate,
            )
            phase_assumptions = [
                str(phase.get("coverage_reason") or "")
                for fact in schedule_facts
                for phase in fact.get("value", {}).get("phases", [])
                if phase.get("phase_id") == segment.phase_id
            ]
            zero_supply_assumptions = [
                str(fact.get("value", {}).get("zero_supply_basis") or "")
                for fact in schedule_facts
                if fact.get("value", {}).get("zero_supply_basis")
            ]
            scenarios.append(
                PowerScenario(
                    project_id=project_id,
                    need_id=need_id,
                    activity_key=activity_key,
                    activity_kind=activity_kind,
                    facility_scope=facility_scope,
                    phase_id=segment.phase_id,
                    scenario=segment.scenario,
                    evidence_status=(
                        "hypothesis"
                        if is_hypothesis
                        else _evidence_status(
                            segment.demand_basis,
                            *segment.supply_basis,
                            *(phase_assumptions),
                            *(zero_supply_assumptions),
                            segment.unresolved_reason or "",
                            projected.basis,
                            *(ref.source_quote or "" for ref in projected.fact_refs),
                        )
                    ),
                    start_date=segment.start_date,
                    end_date=segment.end_date,
                    duration_days_min=duration_days,
                    duration_days_max=duration_days,
                    demand_mw_min=segment.demand_min_mw,
                    demand_mw_max=segment.demand_max_mw,
                    supply_mw_min=segment.supply_min_mw,
                    supply_mw_max=segment.supply_max_mw,
                    residual_mw_min=segment.residual_min_mw,
                    residual_mw_max=segment.residual_max_mw,
                    supply_status=supply_status,
                    demand_basis=segment.demand_basis,
                    supply_basis=segment.supply_basis,
                    sources=source_refs,
                    basis=projected.basis,
                    rental_value=value,
                )
            )

    if conflict:
        status: Literal["SUPPORTED", "UNRESOLVED", "CONFLICT", "NO_EVIDENCE"] = "CONFLICT"
    elif unresolved:
        status = "UNRESOLVED"
    elif scenarios:
        status = "SUPPORTED"
    else:
        status = "NO_EVIDENCE"
    return PowerEnrichment(
        status=status,
        scenarios=scenarios,
        basis=(
            "Activity-specific evidence is projected independently; facility totals are not "
            "used as activity demand. Qualification remains governed by existing rules."
        ),
    )
