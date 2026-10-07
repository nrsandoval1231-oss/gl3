"""Deterministic asset lifecycle classification and timing.

This module interprets evidence; it never changes commercial qualification tiers.
Reported dates are inputs and estimated windows are explicitly derived values.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class AssetType(StrEnum):
    UNKNOWN = "unknown"
    DATA_CENTER = "data_center"
    UPSTREAM_WELL = "upstream_well"
    COMPRESSOR_STATION = "compressor_station"
    GAS_PROCESSING_PLANT = "gas_processing_plant"
    CRYOGENIC_PLANT = "cryogenic_plant"
    SWD_FACILITY = "swd_facility"
    PRODUCED_WATER = "produced_water_infrastructure"
    GATHERING_SYSTEM = "gathering_system"
    PIPELINE = "pipeline_infrastructure"
    PIPELINE_PUMP_COMPRESSOR = "pipeline_pump_compressor_facility"
    TREATMENT_FACILITY = "treatment_facility"
    TERMINAL = "terminal"
    FIELD_ELECTRIFICATION = "field_electrification_project"


class DataCenterState(StrEnum):
    FORMATION = "project_formation"
    PLANNING = "site_control_planning"
    PERMITTING = "permitting"
    CONSTRUCTION = "construction"
    ELECTRICAL = "electrical_buildout"
    COMMISSIONING = "commissioning"
    ENERGIZATION = "utility_energization"
    OPERATION = "operation"


class UpstreamState(StrEnum):
    PRE_PERMIT = "pre_permit_development"
    PERMIT = "drilling_permit"
    SPUD = "spud"
    DRILLING = "drilling"
    COMPLETION = "completion"
    PRODUCTION = "first_production"
    ELECTRIFICATION = "electrification_production_power"


class FixedInfrastructureState(StrEnum):
    FORMATION = "project_formation"
    APPLICATION = "regulatory_environmental_application"
    PERMIT = "permit"
    EPC = "epc_procurement"
    CONSTRUCTION = "construction"
    COMMISSIONING = "commissioning_startup"
    OPERATION = "operation"


FIXED_ASSETS = frozenset(AssetType) - {
    AssetType.UNKNOWN,
    AssetType.DATA_CENTER,
    AssetType.UPSTREAM_WELL,
}

LIFECYCLE_ORDER: dict[AssetType, tuple[str, ...]] = {
    AssetType.DATA_CENTER: tuple(state.value for state in DataCenterState),
    AssetType.UPSTREAM_WELL: tuple(state.value for state in UpstreamState),
    **{asset: tuple(state.value for state in FixedInfrastructureState) for asset in FIXED_ASSETS},
}


def lifecycle_rank(asset_type: AssetType, state: str) -> int:
    return LIFECYCLE_ORDER[asset_type].index(state)


@dataclass(frozen=True)
class Classification:
    asset_type: AssetType
    event_type: str
    state: str
    expected_next_milestone: str | None
    expected_power_event: str
    monitoring_requirements: tuple[str, ...]


@dataclass(frozen=True)
class ProductionEstimate:
    window_start: date
    window_end: date
    estimated_days: tuple[int, int]
    basis: tuple[str, ...]
    confidence: str
    rule_version: str
    missing_evidence: tuple[str, ...]
    next_milestone: str
    value_kind: str = "derived"


_ASSETS = (
    (AssetType.DATA_CENTER, r"data cent(?:er|re)|server campus|hyperscale"),
    (AssetType.CRYOGENIC_PLANT, r"cryogenic plant"),
    (AssetType.GAS_PROCESSING_PLANT, r"gas processing plant"),
    (AssetType.COMPRESSOR_STATION, r"compressor station"),
    (AssetType.SWD_FACILITY, r"saltwater disposal|\bswd\b"),
    (AssetType.PRODUCED_WATER, r"produced.water"),
    (AssetType.GATHERING_SYSTEM, r"gathering (?:system|line)"),
    (AssetType.PIPELINE_PUMP_COMPRESSOR, r"pipeline (?:pump|compressor)"),
    (AssetType.PIPELINE, r"\bpipeline\b"),
    (AssetType.TREATMENT_FACILITY, r"treatment facilit"),
    (AssetType.TERMINAL, r"\bterminal\b"),
    (AssetType.FIELD_ELECTRIFICATION, r"field electrification"),
    (
        AssetType.UPSTREAM_WELL,
        r"drilling permit|well permit|\bspud(?:ded)?\b|well completion|first production",
    ),
)


def classify_event(
    title: str,
    abstract: str | None = None,
    *,
    project_name: str | None = None,
    project_identity_key: str | None = None,
    require_achieved_milestone: bool = False,
) -> Classification | None:
    text = f"{title} {abstract or ''}".casefold()
    if not requires_scoped_lifecycle_evidence(title, abstract):
        return _classify_scope(
            text,
            allow_formation_fallback=not require_achieved_milestone,
            require_achieved_milestone=require_achieved_milestone,
        )

    # In mixed reports, classify each separated clause on its own. A facility
    # or procedural clause cannot lend its milestone to the campus, while a
    # separately stated campus event remains usable.
    title_has_data_center = bool(re.search(_ASSETS[0][1], title, re.IGNORECASE))
    candidates = []
    for part in _split_lifecycle_clauses(title, abstract):
        if (project_name or project_identity_key) and not _mentions_project(
            part, project_name, project_identity_key
        ):
            continue
        explicit_campus = bool(re.search(_ASSETS[0][1], part, re.IGNORECASE))
        campus_reference = bool(re.search(r"\bcampus\b|\bdata center site\b", part))
        adjacent_facility = bool(re.search(r"\bmicrogrid\b|\bair[ -]permit\b", part))
        if explicit_campus and not adjacent_facility:
            candidates.append(part)
        elif title_has_data_center and campus_reference and not adjacent_facility:
            candidates.append(f"data center {part}")
    classifications = [
        event
        for part in candidates
        if (
            event := _classify_scope(
                part,
                allow_formation_fallback=False,
                require_achieved_milestone=require_achieved_milestone,
            )
        )
    ]
    return classifications[-1] if classifications else None


def _mentions_project(
    text: str, project_name: str | None, project_identity_key: str | None
) -> bool:
    generic = {
        "a",
        "an",
        "and",
        "campus",
        "center",
        "data",
        "dc",
        "facility",
        "for",
        "inc",
        "llc",
        "project",
        "site",
        "the",
    }
    normalized_text = set(re.findall(r"[a-z0-9]+", text.casefold()))
    for value in (project_name, project_identity_key):
        if not value:
            continue
        terms = set(re.findall(r"[a-z0-9]+", value.casefold())) - generic
        if terms and terms.issubset(normalized_text):
            return True
    return False


def requires_scoped_lifecycle_evidence(title: str, abstract: str | None = None) -> bool:
    """Whether this data-center report contains a separate asset or procedural track."""
    text = f"{title} {abstract or ''}".casefold()
    return bool(
        re.search(_ASSETS[0][1], text)
        and re.search(r"\bmicrogrid\b|\bair[ -]permit\b|\bforce[\s-]+majeure\b", text)
    )


def _split_lifecycle_clauses(title: str, abstract: str | None) -> list[str]:
    text = f"{title}. {abstract or ''}".casefold()
    parts = re.split(
        r"(?<=[.!?])\s+|;\s*|\s+\b(?:while|whereas|but|however)\b\s+|"
        r",\s*(?=(?:the\s+)?(?:adjacent|separate|nearby)\s+(?:microgrid|air[ -]permit)\b)",
        text,
    )
    return [part.strip(" ,:-") for part in parts if part.strip(" ,:-")]


def _classify_scope(
    text: str,
    *,
    allow_formation_fallback: bool = True,
    require_achieved_milestone: bool = False,
) -> Classification | None:
    asset = next((kind for kind, pattern in _ASSETS if re.search(pattern, text)), AssetType.UNKNOWN)
    if asset == AssetType.UNKNOWN:
        return None
    rules: list[tuple[str, str, StrEnum, str | None]]
    if asset == AssetType.DATA_CENTER:
        rules = [
            (
                r"energiz|utility service",
                "utility_service",
                DataCenterState.ENERGIZATION,
                "operation",
            ),
            (
                r"commissioning agent|load bank|ups commissioning|generator testing|"
                r"switchgear testing",
                "commissioning",
                DataCenterState.COMMISSIONING,
                "utility energization",
            ),
            (
                r"substation|transformer|switchgear|electrical permit",
                "electrical_buildout",
                DataCenterState.ELECTRICAL,
                "commissioning",
            ),
            (
                (
                    r"grading (?:has )?(?:begun|started)|(?:began|started) grading|"
                    r"building permit(?: was)? (?:issued|approved|received)|"
                    r"received (?:its )?building permit|groundbreak|site work (?:has )?begun|"
                    r"construction (?:has )?(?:begun|started)|(?:began|started) construction|"
                    r"under construction|mobiliz"
                    if require_achieved_milestone
                    else r"grading|building permit|construct|groundbreak|site work|mobiliz"
                ),
                "construction",
                DataCenterState.CONSTRUCTION,
                "electrical buildout",
            ),
            (
                (
                    r"rezon|planning application|development agreement|land acqui|tax incentive|"
                    r"economic development"
                    if allow_formation_fallback
                    else r"(?!)"
                ),
                "project_formation",
                DataCenterState.PLANNING,
                "permitting",
            ),
            (
                r"announc|financ|capital commitment|preconstruction|contractor award|"
                r"equipment procurement",
                "project_formation",
                DataCenterState.FORMATION,
                "site control / planning",
            ),
        ]
        expected = (
            "construction, commissioning, bridge, or utility power (activity not yet established)"
        )
    elif asset == AssetType.UPSTREAM_WELL:
        rules = [
            (
                r"first production|producing",
                "first_production",
                UpstreamState.PRODUCTION,
                "electrification / production power",
            ),
            (r"complet", "completion", UpstreamState.COMPLETION, "first production"),
            (r"drilling permit|well permit", "drilling_permit", UpstreamState.PERMIT, "spud"),
            (r"drilling|drilled", "drilling", UpstreamState.DRILLING, "completion"),
            (r"spud", "spud", UpstreamState.SPUD, "drilling"),
            (r"permit", "drilling_permit", UpstreamState.PERMIT, "spud"),
        ]
        expected = "production / electrification power"
    else:
        rules = [
            (
                r"operation|in service|startup complete",
                "operation",
                FixedInfrastructureState.OPERATION,
                None,
            ),
            (
                r"commission|startup",
                "commissioning_startup",
                FixedInfrastructureState.COMMISSIONING,
                "operation",
            ),
            (
                r"construct",
                "construction",
                FixedInfrastructureState.CONSTRUCTION,
                "commissioning / startup",
            ),
            (
                r"epc|procurement|contractor award",
                "epc_procurement",
                FixedInfrastructureState.EPC,
                "construction",
            ),
            (
                r"permit issued|approved permit",
                "permit",
                FixedInfrastructureState.PERMIT,
                "EPC / procurement",
            ),
            (
                r"application|environmental|permit",
                "regulatory_application",
                FixedInfrastructureState.APPLICATION,
                "permit",
            ),
        ]
        expected = (
            "construction, commissioning/startup, or operating power (activity not yet established)"
        )
    match: tuple[str, str, str | None] | None = next(
        (
            (event, state.value, nxt)
            for pattern, event, state, nxt in rules
            if re.search(pattern, text)
        ),
        None,
    )
    if match is None and not allow_formation_fallback:
        return None
    if match is None:
        initial_state = (
            DataCenterState.FORMATION
            if asset == AssetType.DATA_CENTER
            else UpstreamState.PRE_PERMIT
            if asset == AssetType.UPSTREAM_WELL
            else FixedInfrastructureState.FORMATION
        )
        match = ("project_formation", initial_state.value, None)
    else:
        milestone_terms = {
            "drilling_permit": r"permit|well permit",
            "spud": r"spud",
            "drilling": r"drilling|drilled",
            "completion": r"complet",
            "first_production": r"production|producing",
            "construction": r"construction|grading|building permit",
            "electrical_buildout": r"substation|transformer|switchgear|electrical permit",
            "commissioning": r"commission|load bank|testing",
            "utility_service": r"energiz\w*|utility service",
        }.get(match[0], re.escape(match[0].replace("_", " ")))
        caveats = (
            r"will|plans? to|planned to|expects? to|expected to|scheduled to|proposed|pending|"
            r"delayed|stayed|paused|halted|suspended|stopped|conditional|future|potential|possible|"
            r"awaiting|requested|not yet|proposes? to|"
            r"did not|has not|never|may|could|subject to|seeks?"
        )
        if re.search(
            rf"\b(?:{caveats})\b[^.;,]{{0,80}}\b(?:{milestone_terms})\b",
            text,
        ) or re.search(
            rf"\b(?:{milestone_terms})\b[^.;,]{{0,60}}\b(?:{caveats}|has not occurred|"
            rf"not started|not begun|not yet occurred|not issued)\b",
            text,
        ):
            return None
    event, state_value, nxt = match
    return Classification(
        asset,
        event,
        state_value,
        nxt,
        expected,
        (f"Watch for {nxt}" if nxt else "Verify operating status",),
    )


def estimate_first_production(
    *,
    permit_date: date,
    spud_date: date | None = None,
    drilling_state: str | None = None,
    completion_date: date | None = None,
    operator: str | None = None,
    basin: str | None = None,
    county: str | None = None,
    well_id: str | None = None,
    well_count: int | None = None,
) -> ProductionEstimate:
    """Auditable v1 clock; future distributions can replace constants by keyed rules."""
    if completion_date:
        anchor, days, next_step, confidence = (
            completion_date,
            (15, 90),
            "first production",
            "medium",
        )
        basis = ["reported completion date", "v1 completion-to-production range: 15-90 days"]
    elif spud_date:
        anchor, days, next_step, confidence = spud_date, (60, 240), "completion", "medium"
        basis = ["reported spud date", "v1 spud-to-production range: 60-240 days"]
    else:
        anchor, days, next_step, confidence = permit_date, (180, 540), "spud", "low"
        basis = ["reported drilling permit date", "v1 permit-to-production range: 180-540 days"]
    if drilling_state:
        basis.append(f"reported drilling state: {drilling_state}")
    known = {
        "operator": operator,
        "basin": basin,
        "county": county,
        "well/pad identity": well_id,
        "well count": well_count,
    }
    missing = tuple(name for name, value in known.items() if value is None)
    return ProductionEstimate(
        anchor + timedelta(days=days[0]),
        anchor + timedelta(days=days[1]),
        days,
        tuple(basis),
        confidence,
        "upstream-production-v1",
        missing,
        next_step,
    )
