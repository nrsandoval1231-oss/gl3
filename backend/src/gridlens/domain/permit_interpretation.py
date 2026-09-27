"""Conservative rule assessment for official city building permit rows."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

EVALUATOR_VERSION = "permit-project-v7"
MISSING = [
    "buyer or responsible operator",
    "activity-specific power requirement",
    "start window",
    "duration",
    "suitable supply",
]
_ELIGIBLE_STATUS = re.compile(r"^(active|issued|approved)$", re.I)
_INELIGIBLE_STATUS = re.compile(
    r"\b(?:final|void|withdrawn|completed|complete|expired|cancelled|canceled)\b", re.I
)
_RESIDENTIAL = re.compile(
    r"\b(?:residential|residence|single[- ]family|duplex|dwelling|house|home|multi[- ]dwelling|[0-9]+\s*(?:du|d\.u\.))\b",  # noqa: E501
    re.I,
)
_NEGATED = re.compile(
    r"\b(?:no (?:temporary|rental|backup|generator|emergency) power(?: is)? needed|"
    r"temporary power (?:is )?not (?:needed|required)|"
    r"no (?:electrical|generator|temporary-power) work authorized)\b",
    re.I,
)
_NEGATED_FACILITY = re.compile(
    r"\b(?:does not authorize any construction|no construction|not for construction|maintenance only|no new construction|without construction|occupancy only|code compliant|code compliance|evaluate .*? compliant)\b",  # noqa: E501
    re.I,
)
_SECURED = re.compile(
    r"\b(?:temporary|rental|backup|generator) power (?:is )?(?:provided|available|secured|in place)|"  # noqa: E501
    r"(?:provided|secured|in place) (?:temporary|rental|backup|generator) power\b|"
    r"\brental generators? already secured\b|\ball temporary power needs? supplied\b|"
    r"\b(?:temporary|rental) (?:generator|genset)\s+(?:(?:is|was|has been)\s+)?"
    r"(?:already\s+)?(?:operational|operating)\b|"
    r"\b(?:temporary|rental) (?:generator|genset)\s+(?:already\s+)?installed\s+"
    r"and\s+(?:operational|operating|supplying)\b",
    re.I,
)
_NEGATED_TEMPORARY_NEED = re.compile(
    r"\b(?:no|not)\s+(?:(?:additional|separate|unserved)\s+)?"
    r"(?:temporary|rental|construction)\s+(?:power|generator|load)\b[^.;|]{0,80}\b"
    r"(?:needed|required)\b|"
    r"\b(?:temporary|rental|construction)\s+(?:power|generator|load)\b[^.;|]{0,80}\b"
    r"(?:no longer|not)\s+(?:needed|required)\b",
    re.I,
)
_CLAUSE_BOUNDARY = re.compile(r"[.;\n]+")
_DISTINCT_ACTIVITY = re.compile(r"\b(?:additional|separate|unserved)\b", re.I)
_REQUIREMENT = re.compile(r"\b(?:needed|required|requires?)\b", re.I)
_FULFILLED_TEMPORARY_NEED = re.compile(
    r"\b(?:already\s+)?(?:supplied|provided|secured|fulfilled|in place)\b|"
    r"\b(?:is|was|has been)\s+(?:already\s+)?(?:supplied|provided|secured|fulfilled)\b",
    re.I,
)
_GENERATOR_CHANGE = re.compile(
    r"\b(?:replace|changeout|change[- ]out|upgrade)\s+(?:(?:the|existing|natural gas|gas|backup|emergency)\s+)*(?:generator|genset|automatic transfer switch|ATS|switchgear|transformer)\b|\b(?:generator|genset|automatic transfer switch|ATS|switchgear|transformer)\b.{0,50}\b(?:replacement|changeout|change[- ]out|will be replaced|will be upgraded)\b",  # noqa: E501
    re.I,
)
_TEMP_POWER = re.compile(
    r"\b(?:temporary|rental|rented|mobile|portable) (?:power|electric(?:al)?|generator|generation)|\b(?:construction power|temporary generator|rental generator|mobile generator|portable generator)\b",  # noqa: E501
    re.I,
)
_BRIDGE = re.compile(
    r"\b(?:bridge|temporary|backup) power\b.{0,100}\b(?:utility|energization|service|outage|delay|interruption)|\b(?:utility|energization|service)\b.{0,100}\b(?:bridge power|temporary power|power (?:is )?(?:needed|required)|outage|interruption)\b",  # noqa: E501
    re.I,
)
_EVENT = re.compile(
    r"\b(?:concert|festival|fair|performance|event|stages?|music stage|food vendors?)\b", re.I
)
_POWERED_EVENT = re.compile(
    r"\b(?:stages?|sound|audio|lighting|food vendors?|concessions?|catering|production|temporary electrical|power distribution|generators?|electrical service)\b",  # noqa: E501
    re.I,
)
_EVENT_ACTIVITY = re.compile(
    r"\b(?:stages?|temporary electrical|power distribution|generators?|electrical service|food vendors?|concessions?|catering|sound|audio|production)\b",  # noqa: E501
    re.I,
)
_NEGATED_EVENT_TRIGGER = re.compile(
    r"\b(?:will not (?:be|have)|not (?:be|have)|no|without)\b[^.;|]{0,80}\b(?:(?:dj\s+)?stages?(?:\s+or\s+(?:amplified|live)\s+sound)?|(?:amplified|live)\s+sound)\b",  # noqa: E501
    re.I,
)
_NEGATED_ACTION = re.compile(
    r"\b(?:no (?:new )?(?:generator|switchgear|transformer|electrical work|temporary power)|(?:generator|switchgear|transformer) (?:not installed|not replaced)|lighting only|light bulbs?(?:\s+only)?|no electrical work)\b",  # noqa: E501
    re.I,
)
_MISLEADING_SCOPE = re.compile(
    r"\b(?:sign|advertis\w*|paint|roof|roofing|reroof|repair|light bulbs?)\b.{0,60}\b(?:rental generators?|generators?|transformer|switchgear)\b|\b(?:utility generation station|power generation plant|permanent generator)\b",  # noqa: E501
    re.I,
)
_ADVERTISING_ONLY = re.compile(
    r"\b(?:sign|advertis\w*)\b.{0,60}\b(?:rental generators?|generators?|temporary power)\b", re.I
)
_ORDINARY_TARGET = re.compile(
    r"\b(?:to|into|for)\s+(?:an?\s+)?(?:restaurant|retail|office(?:s| space)?|tenant space|coffee shop|bar|daycare|child care|medical office|clinic|dental office|adult care|drinking establishment)\b",  # noqa: E501
    re.I,
)
_DATA_OR_LAB = re.compile(r"\b(?:data cent(?:er|re)|laborator(?:y|ies)|lab support)\b", re.I)
_MANUFACTURING = re.compile(r"\b(?:manufactur\w*|factory|plant|industrial processing)\b", re.I)
_WAREHOUSE = re.compile(r"\b(?:warehouse|distribution|cold storage)\b", re.I)
_WAREHOUSE_CONSTRUCTION = re.compile(
    r"\b(?:construct|build)(?:ing)?\s+(?:new\s+)?(?:warehouse|distribution|cold storage)\b", re.I
)
_HOSPITAL = re.compile(r"\b(?:hospital|medical center)\b", re.I)
_HOSPITAL_CONTINUITY = re.compile(
    r"\b(?:surgery|surgical|operating room|\bOR\b|PACU|intensive care|\bICU\b|emergency department)\b",  # noqa: E501
    re.I,
)
_CONSTRUCTION = re.compile(
    r"\b(?:new construction|construction of|construct(?:ing)?|new building|build(?:ing)?|erect(?:ing|ion)?|foundation|addition|expand(?:ing|ed|sion)?)\b",  # noqa: E501
    re.I,
)
_SUBSTANTIVE_CONSTRUCTION = re.compile(
    r"\b(?:new construction|construction of|new building|foundation|addition|expand(?:ing|ed|sion)?)\b",  # noqa: E501
    re.I,
)
_CONVERSION = re.compile(r"\b(?:convert(?:ing|ed|sion)?|change(?:\s+of)?\s+use)\b", re.I)
_FACILITY_REMODEL = re.compile(r"\b(?:remodel\w*|renovat\w*|alteration\w*)\b", re.I)
_MEP_SCOPE = re.compile(
    r"\b(?:mechanical|electrical|plumbing|mep|cooling|power)\b.{0,120}\b(?:upgrade|new|replace)\b|\b(?:upgrade|new)\b.{0,120}\b(?:mechanical|electrical|plumbing|mep|cooling|power)\b",
    re.I,
)
_MAJOR_REMODEL = re.compile(r"\b(?:major|complete|full|phase\s*[0-9]+)\b", re.I)
_ROUTINE = re.compile(
    r"\b(?:reroof|roofing|roof replacement|grease interceptor|lighting(?:\s+only)?|light bulbs?|racking(?:\s+system)?|floor striping|weight scales?|plumbing changes? only|inspection only|office paint|paint office)\b",  # noqa: E501
    re.I,
)
_SQUARE_FEET = re.compile(r"\b([0-9][0-9,]*)\s*(?:sf|sq\.?\s*ft\.?|square\s*feet)\b", re.I)
_NUMERIC_DATES = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2})/(?P<month1>\d{1,2})/(?P<day1>\d{1,2})|(?P<month2>\d{1,2})/(?P<day2>\d{1,2})/(?P<year2>20\d{2}))(?!\d)"
)


def _explicit_event_end(description: str) -> date | None:
    """Read explicit full-year dates from event text; permit expiry is not event timing."""
    text = re.sub(
        r"\bpermit expires?(?: on)?\s+\d{1,2}/\d{1,2}/20\d{2}", " ", description, flags=re.I
    )
    values: list[date] = []
    for match in _NUMERIC_DATES.finditer(text):
        year = int(match.group("year") or match.group("year2"))
        month = int(match.group("month1") or match.group("month2"))
        day = int(match.group("day1") or match.group("day2"))
        try:
            values.append(date(year, month, day))
        except ValueError:
            continue
    months = (
        "January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|"
        "August|Aug|September|Sept|Sep|October|Oct|November|Nov|December|Dec"
    )
    month_pattern = re.compile(
        rf"\b(?P<month>(?:{months}))\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s*[-–]\s*(?P<end>\d{{1,2}})(?:st|nd|rd|th)?)?(?:\s*,?\s*(?P<year>20\d{{2}}))?",
        re.I,
    )
    for match in month_pattern.finditer(text):
        year_text = match.group("year")
        if not year_text:
            tail = text[match.end() : match.end() + 32]
            year_match = re.search(r"\b(20\d{2})\b", tail)
            year_text = year_match.group(1) if year_match else None
        if not year_text:
            continue
        month = datetime.strptime(match.group("month")[:3], "%b").month
        day = int(match.group("end") or match.group("day"))
        try:
            values.append(date(int(year_text), month, day))
        except ValueError:
            continue
    return max(values) if values else None


def _large_stated_scope(description: str) -> bool:
    return any(int(value.replace(",", "")) >= 10_000 for value in _SQUARE_FEET.findall(description))


def _facility_activity(description: str) -> bool:
    data_or_lab = bool(_DATA_OR_LAB.search(description))
    manufacturing = bool(_MANUFACTURING.search(description))
    warehouse = bool(_WAREHOUSE.search(description))
    hospital = bool(_HOSPITAL.search(description))
    construction = bool(_CONSTRUCTION.search(description))
    substantive = bool(_SUBSTANTIVE_CONSTRUCTION.search(description))
    conversion = bool(_CONVERSION.search(description))
    remodel = bool(_FACILITY_REMODEL.search(description))
    return bool(
        data_or_lab
        and (
            (conversion and re.search(r"\b(?:to|into)\b", description, re.I))
            or construction
            or (remodel and _MEP_SCOPE.search(description))
        )
        or manufacturing
        and (
            substantive
            or remodel
            and (_MAJOR_REMODEL.search(description) or _large_stated_scope(description))
        )
        or warehouse
        and (substantive or _WAREHOUSE_CONSTRUCTION.search(description))
        or hospital
        and substantive
    )


def _has_powered_event_activity(description: str) -> bool:
    searchable = _NEGATED_EVENT_TRIGGER.sub(" ", description)
    return bool(_POWERED_EVENT.search(searchable) and _EVENT_ACTIVITY.search(searchable))


def _distinct_open_temporary_clause(description: str) -> str | None:
    """Return one explicit remaining temporary-power clause, if it is still open."""
    for raw_clause in _CLAUSE_BOUNDARY.split(description):
        clause = raw_clause.strip()
        if not (
            clause
            and _TEMP_POWER.search(clause)
            and _DISTINCT_ACTIVITY.search(clause)
            and _REQUIREMENT.search(clause)
        ):
            continue
        if (
            _NEGATED.search(clause)
            or _NEGATED_TEMPORARY_NEED.search(clause)
            or _SECURED.search(clause)
            or _FULFILLED_TEMPORARY_NEED.search(clause)
        ):
            continue
        return clause
    return None


def assess_permit(record: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    permit = record.get("permit")
    if not isinstance(permit, dict):
        raise ValueError("Permit fields are missing")
    description = str(permit.get("description") or "")
    as_of = as_of or date.today()
    event_end = _explicit_event_end(description)
    status = str(permit.get("status") or "")
    address, city, state = (str(permit.get(key) or "") for key in ("address", "city", "state"))
    location = ", ".join(part for part in (address, city, state) if part)
    activity = None
    reason = "Permit does not establish a qualifying project activity."

    # Explicit no-work/secured-supply claims take precedence unless a separate
    # clause identifies a still-open temporary-power activity.
    remaining_clause = _distinct_open_temporary_clause(description)
    if _SECURED.search(description) and remaining_clause is None:
        activity, category = None, "secured_supply"
        reason = "Permit reports temporary power as provided or secured; no open rental need is asserted."  # noqa: E501
    elif _SECURED.search(description) and remaining_clause:
        activity, category = "temporary-power", "temporary_power"
        reason = (
            f"Permit reports a distinct remaining power activity: {remaining_clause} "
            "Rental relevance is inferred; suitable supply for this activity remains unknown."
        )
    elif _NEGATED_ACTION.search(description) or re.search(
        r"\b(?:cancelled|canceled|withdrawn)\b.{0,80}\b(?:generator|switchgear|transformer|temporary power)\b|\b(?:generator|switchgear|transformer)\b.{0,80}\b(?:cancelled|canceled|not authorized)\b",  # noqa: E501
        description,
        re.I,
    ):
        activity, category = None, "negated_action"
        reason = "Permit explicitly negates the apparent electrical or temporary-power work."
    elif _ADVERTISING_ONLY.search(description):
        activity, category = None, "incidental_advertising"
        reason = "Permit mentions rental equipment only as signage or advertising, not as site power activity."  # noqa: E501
    elif (
        _EVENT.search(description)
        and event_end
        and event_end < as_of
        and (_has_powered_event_activity(description) or _TEMP_POWER.search(description))
    ):
        activity, category = None, "past_event"
        reason = "The explicitly dated powered event has ended; the permit issue date and permit expiry do not make it a current rental-power opportunity."  # noqa: E501
    elif _MISLEADING_SCOPE.search(description) and not (
        _TEMP_POWER.search(description)
        or _BRIDGE.search(description)
        or _GENERATOR_CHANGE.search(description)
    ):
        activity, category = None, "incidental_or_permanent_generation"
        reason = "Permit mentions power equipment only as incidental signage, building repair, or permanent generation without a supported load-side activity."  # noqa: E501
    elif _GENERATOR_CHANGE.search(description) and not _NEGATED.search(description):
        activity, category = "backup-power", "equipment_continuity"
        reason = "Permit reports a generator, transfer-switch, switchgear, or transformer change; continuity power is an inferred rental question, not a reported outage or need."  # noqa: E501
    elif _TEMP_POWER.search(description) and not _NEGATED.search(description):
        activity, category = "temporary-power", "temporary_power"
        reason = "Permit reports temporary, rental, mobile, portable, or construction power activity; rental relevance is inferred and supply remains unknown."  # noqa: E501
    elif _BRIDGE.search(description) and not _NEGATED.search(description):
        activity, category = "bridge-power", "bridge_power"
        reason = "Permit reports a utility, service, or energization delay tied to bridge power; a rental requirement is inferred, with available supply unknown."  # noqa: E501
    elif (
        _EVENT.search(description)
        and _has_powered_event_activity(description)
        and not _NEGATED.search(description)
        and event_end
        and event_end >= as_of
    ):
        activity, category = "event-power", "powered_event"
        reason = "Permit reports a dated powered event activity; a temporary rental-power question is inferred, not a confirmed shortage."  # noqa: E501
    elif (
        _HOSPITAL.search(description)
        and _FACILITY_REMODEL.search(description)
        and _HOSPITAL_CONTINUITY.search(description)
    ):
        activity, category = "backup-power", "healthcare_continuity"
        reason = "Permit reports remodel or electrical work in interruption-sensitive hospital activity; continuity power is an inferred review question, not a reported outage."  # noqa: E501
    elif (
        _facility_activity(description)
        and not _NEGATED.search(description)
        and not _NEGATED_FACILITY.search(description)
        and not _ROUTINE.search(description)
    ):
        activity, category = "facility-expansion", "facility_activity"
        reason = "Official dated permit identifies concrete facility construction, conversion, or remodel; investigate construction or commissioning power. Permit issuance does not prove work start, load, or a power gap."  # noqa: E501
    else:
        category = "none"
        if not _ELIGIBLE_STATUS.fullmatch(status.strip()) or _INELIGIBLE_STATUS.search(status):
            reason = f"Permit status is {status or 'unknown'}; it does not establish currently issued work."  # noqa: E501
        elif not permit.get("row_id") or not record.get("event_date") or not record.get("html_url"):
            reason = "An official dated permit row and source citation are required."
        elif not address:
            reason = "The permit does not identify a project site."
        elif _NEGATED.search(description):
            reason = "Permit text does not authorize a current construction activity."
        elif _RESIDENTIAL.search(description):
            reason = "Permit is residential work, not an identified commercial or industrial facility project."  # noqa: E501
        elif _ORDINARY_TARGET.search(description) and not _DATA_OR_LAB.search(description):
            reason = "Permit converts or builds out ordinary office, restaurant, retail, or tenant space."  # noqa: E501
        else:
            reason = "Permit does not show a supported temporary-power, continuity-power, powered-event, or facility activity."  # noqa: E501

    gates_ok = bool(
        permit.get("row_id")
        and record.get("event_date")
        and record.get("html_url")
        and address
        and _ELIGIBLE_STATUS.fullmatch(status.strip())
        and not _INELIGIBLE_STATUS.search(status)
        and not _RESIDENTIAL.search(description)
    )
    decision = "accepted" if activity and gates_ok else "rejected"
    if activity and not gates_ok:
        reason = "A dated active/issued/approved commercial permit, identified site, and source citation are required."  # noqa: E501
    return {
        "schema_version": 1,
        "decision": decision,
        "tier": "Signal" if decision == "accepted" else None,
        "reason": reason,
        "subject": f"{city} permit {permit.get('row_id')}" if decision == "accepted" else None,
        "action": description if decision == "accepted" else None,
        "location": location or None,
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": status,
        "issue_date": record.get("event_date"),
        "issue_date_label": "Official permit issue date; source publication date unknown",
        "project_hint": permit.get("project") or None,
        "power_activity": activity or "facility-expansion",
        "rental_category": category,
        "reported_claim": description if decision == "accepted" else None,
        "rental_hypothesis": "Inferred; permit text does not establish rental requirement, MW, buyer, suitable supply, start, or duration."  # noqa: E501
        if decision == "accepted"
        else None,
        "activity_end_date": event_end.isoformat() if event_end else None,
        "review_after": event_end.isoformat() if event_end and decision == "accepted" else None,
    }
