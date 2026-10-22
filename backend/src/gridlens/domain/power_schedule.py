"""Pure validation and projection for attributed, dated power schedules."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PowerScheduleSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_id: str
    start_date: str
    end_date: str
    demand_min_mw: str
    demand_max_mw: str
    demand_basis: str
    supply_min_mw: str | None
    supply_max_mw: str | None
    residual_min_mw: str | None
    residual_max_mw: str | None
    supply_ids: list[str] = Field(default_factory=list)
    unresolved_supply_ids: list[str] = Field(default_factory=list)
    supply_basis: list[str] = Field(default_factory=list)
    unresolved_reason: str | None = None
    scenario: Literal["base", "alternative"] = "base"


class PowerScheduleFactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_version_id: str | None = None
    content_hash: str | None = None
    authority: str | None = None
    source_reference: str | None = None
    source_quote: str | None = None
    confirmed_at: str | None = None
    reporter_name: str | None = None
    reporter_organization: str | None = None
    reporter_role: str | None = None


class PowerScheduleSupply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supply_id: str
    start_date: str
    end_date: str
    mw_min: str
    mw_max: str
    state: Literal["operating", "committed", "proposed", "hypothetical"]
    suitability: Literal["suitable", "unsuitable", "unknown"]
    source_kind: Literal["utility_grid", "onsite", "other"] = "other"
    service_ready_date: str | None = None
    date_basis: str
    basis: str
    source_reference: str | None = None


class PowerScheduleProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["SUPPORTED_SCENARIO", "UNRESOLVED", "CONFLICT"]
    basis: str
    fact_refs: list[PowerScheduleFactReference]
    supplies: list[PowerScheduleSupply] = Field(default_factory=list)
    segments: list[PowerScheduleSegment]


def _text(value: Any, field: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} must contain 1 to {limit} characters")
    return value.strip()


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be a real ISO date") from None


def _mw(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite MW")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be finite MW") from None
    if not result.is_finite() or result < 0 or result > 1_000_000:
        raise ValueError(f"{field} must be within the supported MW range")
    return result


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


def validate_schedule(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 65_536:
        raise ValueError("power schedule must be at most 65536 bytes")
    if set(value) - {"phases", "supplies", "basis", "zero_supply_basis", "source_quote"}:
        raise ValueError("power schedule contains unsupported fields")
    basis = _text(value.get("basis"), "schedule basis", 2000)
    source_quote = value.get("source_quote")
    if source_quote is not None:
        source_quote = _text(source_quote, "source quote", 2000)
    phases, supplies = value.get("phases"), value.get("supplies")
    if not isinstance(phases, list) or not 1 <= len(phases) <= 12:
        raise ValueError("power schedule requires 1 to 12 demand phases")
    if not isinstance(supplies, list) or len(supplies) > 24:
        raise ValueError("power schedule allows at most 24 supply entries")
    clean_phases = []
    phase_ids: set[str] = set()
    for phase in phases:
        if not isinstance(phase, dict) or set(phase) != {
            "phase_id",
            "start_date",
            "end_date",
            "mw_min",
            "mw_max",
            "basis",
            "supply_coverage",
            "coverage_reason",
        }:
            raise ValueError("demand phase has missing or unsupported fields")
        phase_id = _text(phase["phase_id"], "phase ID", 80)
        if phase_id in phase_ids:
            raise ValueError("demand phase IDs must be unique")
        phase_ids.add(phase_id)
        start, end = (
            _date(phase["start_date"], "phase start"),
            _date(phase["end_date"], "phase end"),
        )
        low, high = _mw(phase["mw_min"], "phase demand"), _mw(phase["mw_max"], "phase demand")
        if start >= end or low <= 0 or high < low:
            raise ValueError("demand phase dates or MW interval are invalid")
        coverage = phase["supply_coverage"]
        if coverage not in {"confirmed_complete", "partial", "unknown"}:
            raise ValueError("supply coverage must be confirmed_complete, partial, or unknown")
        clean_phases.append(
            {
                "phase_id": phase_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mw_min": _fmt(low),
                "mw_max": _fmt(high),
                "basis": _text(phase["basis"], "phase basis", 2000),
                "supply_coverage": coverage,
                "coverage_reason": _text(phase["coverage_reason"], "coverage reason", 500),
                "_start": start,
                "_end": end,
            }
        )
    ordered = sorted(clean_phases, key=lambda phase: phase["_start"])
    overlaps = any(
        left["_end"] > right["_start"] for left, right in zip(ordered, ordered[1:], strict=False)
    )
    if overlaps:
        raise ValueError("demand phases may not overlap")
    clean_supplies = []
    supply_ids: set[str] = set()
    source_windows: dict[str, list[tuple[date, date]]] = {}
    for supply in supplies:
        required = {
            "supply_id",
            "start_date",
            "end_date",
            "mw_min",
            "mw_max",
            "state",
            "suitability",
            "date_basis",
            "basis",
        }
        if (
            not isinstance(supply, dict)
            or set(supply) - (required | {"service_ready_date", "source_reference", "source_kind"})
            or not required.issubset(supply)
        ):
            raise ValueError("supply entry has missing or unsupported fields")
        supply_id = _text(supply["supply_id"], "supply ID", 80)
        if supply_id in supply_ids:
            raise ValueError("supply IDs must be unique")
        supply_ids.add(supply_id)
        start, end = (
            _date(supply["start_date"], "supply start"),
            _date(supply["end_date"], "supply end"),
        )
        low, high = _mw(supply["mw_min"], "supply MW"), _mw(supply["mw_max"], "supply MW")
        if start >= end or high < low:
            raise ValueError("supply dates or MW interval are invalid")
        if supply["state"] not in {"operating", "committed", "proposed", "hypothetical"}:
            raise ValueError("supply state is unsupported")
        if supply["suitability"] not in {"suitable", "unsuitable", "unknown"}:
            raise ValueError("supply suitability must be explicit")
        source_kind = supply.get("source_kind", "other")
        if source_kind not in {"utility_grid", "onsite", "other"}:
            raise ValueError("supply source kind is unsupported")
        ready = supply.get("service_ready_date")
        if supply["state"] == "committed":
            if ready is None or _date(ready, "committed service-ready date") > start:
                raise ValueError(
                    "committed supply requires a service-ready date no later than start"
                )
        elif ready is not None:
            ready_date = _date(ready, "service-ready date")
            if ready_date >= end:
                raise ValueError("service-ready date must precede supply end")
            ready = ready_date.isoformat()
        source_ref = supply.get("source_reference")
        if source_ref is not None:
            source_ref = _text(source_ref, "supply source reference", 500)
            source_windows.setdefault(source_ref, []).append((start, end))
        clean_supplies.append(
            {
                "supply_id": supply_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mw_min": _fmt(low),
                "mw_max": _fmt(high),
                "state": supply["state"],
                "suitability": supply["suitability"],
                "source_kind": source_kind,
                "date_basis": _text(supply["date_basis"], "date basis", 500),
                "basis": _text(supply["basis"], "supply basis", 2000),
                "service_ready_date": ready,
                **({"source_reference": source_ref} if source_ref else {}),
                "_start": start,
                "_end": end,
            }
        )
    for windows in source_windows.values():
        windows.sort()
        if any(left[1] > right[0] for left, right in zip(windows, windows[1:], strict=False)):
            raise ValueError("overlapping supply entries cannot claim the same source reference")
    zero_basis = value.get("zero_supply_basis")
    if zero_basis is not None:
        zero_basis = _text(zero_basis, "zero-supply basis", 2000)
    if (
        any(p["supply_coverage"] == "confirmed_complete" for p in phases)
        and not clean_supplies
        and not zero_basis
    ):
        raise ValueError("confirmed zero supply requires an explicit attributed zero-supply basis")
    for item in clean_phases + clean_supplies:
        item.pop("_start", None)
        item.pop("_end", None)
    return {
        "basis": basis,
        "phases": clean_phases,
        "supplies": clean_supplies,
        **({"zero_supply_basis": zero_basis} if zero_basis else {}),
        **({"source_quote": source_quote} if source_quote else {}),
    }


def project_schedule(facts: list[dict[str, Any]]) -> PowerScheduleProjection | None:
    if not facts:
        return None
    refs = []
    for fact in facts:
        confirmed_at = fact.get("confirmed_at")
        refs.append(
            PowerScheduleFactReference(
                fact_version_id=fact.get("fact_version_id"),
                content_hash=fact.get("content_hash"),
                authority=fact.get("authority"),
                source_reference=fact.get("source_reference"),
                source_quote=fact.get("value", {}).get("source_quote"),
                confirmed_at=(
                    confirmed_at.isoformat()
                    if confirmed_at is not None and hasattr(confirmed_at, "isoformat")
                    else confirmed_at
                ),
                reporter_name=fact.get("reporter_name"),
                reporter_organization=fact.get("reporter_organization"),
                reporter_role=fact.get("reporter_role"),
            )
        )
    if len(facts) > 1:
        return PowerScheduleProjection(
            status="CONFLICT",
            basis="Multiple current accepted schedules are unsuperseded.",
            fact_refs=refs,
            supplies=[],
            segments=[],
        )
    value = facts[0]["value"]
    supply_summaries = [PowerScheduleSupply.model_validate(supply) for supply in value["supplies"]]
    segments: list[PowerScheduleSegment] = []
    unresolved = False
    for phase in value["phases"]:
        start, end = date.fromisoformat(phase["start_date"]), date.fromisoformat(phase["end_date"])
        boundaries = {start, end}
        for supply in value["supplies"]:
            ss, se = (
                date.fromisoformat(supply["start_date"]),
                date.fromisoformat(supply["end_date"]),
            )
            if supply.get("service_ready_date"):
                ss = max(ss, date.fromisoformat(supply["service_ready_date"]))
            if ss < end and se > start:
                boundaries.update((max(start, ss), min(end, se)))
        points = sorted(boundaries)
        for left, right in zip(points, points[1:], strict=False):
            active = [
                s
                for s in value["supplies"]
                if max(
                    date.fromisoformat(s["start_date"]),
                    date.fromisoformat(s["service_ready_date"])
                    if s.get("service_ready_date")
                    else date.fromisoformat(s["start_date"]),
                )
                <= left
                and date.fromisoformat(s["end_date"]) >= right
            ]
            known = [
                s
                for s in active
                if s["state"] in {"operating", "committed"} and s["suitability"] == "suitable"
            ]
            unknown = [
                s
                for s in active
                if s["state"] in {"operating", "committed"} and s["suitability"] == "unknown"
            ]
            incomplete = phase["supply_coverage"] != "confirmed_complete" or bool(unknown)
            unresolved |= incomplete
            supply_min = sum((_mw(s["mw_min"], "supply") for s in known), Decimal(0))
            supply_max = sum((_mw(s["mw_max"], "supply") for s in known), Decimal(0))
            demand_min, demand_max = _mw(phase["mw_min"], "demand"), _mw(phase["mw_max"], "demand")
            segments.append(
                PowerScheduleSegment(
                    phase_id=phase["phase_id"],
                    start_date=left.isoformat(),
                    end_date=right.isoformat(),
                    demand_min_mw=_fmt(demand_min),
                    demand_max_mw=_fmt(demand_max),
                    demand_basis=phase["basis"],
                    supply_min_mw=_fmt(supply_min) if not incomplete else None,
                    supply_max_mw=_fmt(supply_max) if not incomplete else None,
                    residual_min_mw=_fmt(max(Decimal(0), demand_min - supply_max))
                    if not incomplete
                    else None,
                    residual_max_mw=_fmt(max(Decimal(0), demand_max - supply_min))
                    if not incomplete
                    else None,
                    supply_ids=[s["supply_id"] for s in known],
                    unresolved_supply_ids=[s["supply_id"] for s in unknown],
                    supply_basis=[
                        f"{s['supply_id']}: {s['basis']} ({s['date_basis']})"
                        for s in active
                        if s["state"] in {"operating", "committed"}
                    ],
                    unresolved_reason=phase["coverage_reason"] if incomplete else None,
                )
            )
            for alternative in (
                s
                for s in active
                if s["state"] in {"proposed", "hypothetical"} and s["suitability"] == "suitable"
            ):
                alternative_min = supply_min + _mw(alternative["mw_min"], "supply")
                alternative_max = supply_max + _mw(alternative["mw_max"], "supply")
                segments.append(
                    PowerScheduleSegment(
                        phase_id=phase["phase_id"],
                        start_date=left.isoformat(),
                        end_date=right.isoformat(),
                        demand_min_mw=_fmt(demand_min),
                        demand_max_mw=_fmt(demand_max),
                        demand_basis=phase["basis"],
                        supply_min_mw=_fmt(alternative_min) if not incomplete else None,
                        supply_max_mw=_fmt(alternative_max) if not incomplete else None,
                        residual_min_mw=_fmt(max(Decimal(0), demand_min - alternative_max))
                        if not incomplete
                        else None,
                        residual_max_mw=_fmt(max(Decimal(0), demand_max - alternative_min))
                        if not incomplete
                        else None,
                        supply_ids=[s["supply_id"] for s in known] + [alternative["supply_id"]],
                        unresolved_supply_ids=[s["supply_id"] for s in unknown],
                        supply_basis=[
                            f"{s['supply_id']}: {s['basis']} ({s['date_basis']})"
                            for s in active
                            if s["state"] in {"operating", "committed"}
                        ]
                        + [
                            f"{alternative['supply_id']}: {alternative['basis']} "
                            f"({alternative['date_basis']})"
                        ],
                        unresolved_reason=(
                            "Operating or committed supply suitability is unknown."
                            if unknown
                            else phase["coverage_reason"]
                        )
                        if incomplete
                        else None,
                        scenario="alternative",
                    )
                )
    return PowerScheduleProjection(
        status="UNRESOLVED" if unresolved else "SUPPORTED_SCENARIO",
        basis=value["basis"],
        fact_refs=refs,
        supplies=supply_summaries,
        segments=segments,
    )
