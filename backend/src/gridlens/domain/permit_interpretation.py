"""Conservative rule assessment for official city building permit rows."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from gridlens.domain.evaluation_clock import evaluation_today
from gridlens.domain.regional_scope import classify_project_region

EVALUATOR_VERSION = "permit-project-v8"
GEORGIA_AIR_EVALUATOR_VERSION = "georgia-air-discovery-v2"
MISSING = [
    "buyer or responsible operator",
    "activity-specific power requirement",
    "start window",
    "duration",
    "suitable supply",
]
_ELIGIBLE_STATUS = re.compile(r"^(active|issued|approved)$", re.I)
_INELIGIBLE_STATUS = re.compile(
    r"\b(?:final|void|withdrawn|completed|complete|expired|cancelled|canceled|closed)\b", re.I
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
    r"\btemporary\s+\d[\d,.]*\s*(?:amp(?:ere)?s?\s+(?:electrical\s+)?service|(?:kW|MW)\s+(?:diesel\s+|gas\s+)?generator)\b|"
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
    r"\b(?:to|into|for)\s+(?:an?\s+)?(?:restaurant|retail|office(?:s| space)?|tenant space|commercial tenant|coffee shop|bar|daycare|child care|medical office|clinic|dental office|adult care|drinking establishment)\b",  # noqa: E501
    re.I,
)
_DATA_OR_LAB = re.compile(r"\b(?:data cent(?:er|re)|laborator(?:y|ies)|lab support)\b", re.I)
_MANUFACTURING = re.compile(r"\b(?:manufactur\w*|factory|plant|industrial processing)\b", re.I)
_WAREHOUSE = re.compile(r"\b(?:warehouse|distribution|cold storage)\b", re.I)
_WAREHOUSE_CONSTRUCTION = re.compile(
    r"\b(?:new construction|construct(?:ing)?|build(?:ing)?)\b.{0,100}\b"
    r"(?:warehouse|distribution|cold storage)\b",
    re.I,
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
_AIR_FACILITY_ACTIVITY = re.compile(
    r"\b(?:greenfield project|new (?:data cent(?:er|re)|industrial|manufacturing|"
    r"processing|energy) facility|new quarry|"
    r"proposed (?:new )?data cent(?:er|re)|construction (?:of|and operation of) "
    r"(?:(?:a|the) )?(?:new )?"
    r"(?:data cent(?:er|re)|facility|campus)|(?:construct|build)(?:ing)? (?:a )?(?:new )?"
    r"(?:data cent(?:er|re)|facility|campus)|(?:expand|expansion|addition) of (?:the )?"
    r"(?:facility|campus|data cent(?:er|re))|major facility (?:modification|expansion)|"
    r"(?:construct|build)(?:ing)?\b.{0,120}\b(?:facility|plant|campus|quarry|"
    r"processing unit|data cent(?:er|re))|"
    r"(?:replace(?:ment)?|replacing|install(?:ation|ing)?|add(?:s|ed|ing)?|"
    r"addition\s+of|"
    r"modif(?:y|ication|ying)|upgrade|increase(?:d|ing)?)\b.{0,100}\b"
    r"(?:dryer|baghouse|crusher|processing plant|generator|turbine|boiler|kiln|furnace|"
    r"compressor|engine|equipment|production line|processing unit|production rate|"
    r"production capacity|throughput|permitted capacity)|"
    r"update(?:d|ing)?\b.{0,100}\b(?:equipment list|capacity|production rate|throughput))\b",
    re.I,
)
_AIR_GENERATION_ACTIVITY = re.compile(
    r"\b(?:proposed|new|additional|install(?:ation|ed)?|adding|added)\b.{0,100}\b"
    r"(?:emergency |critical |house |backup )?generators?\b|"
    r"\b(?:generator|turbine) (?:addition|installation|replacement|modification)\b",
    re.I,
)
_AIR_WITHDRAWN = re.compile(
    r"\bapplication (?:has been |was )?withdrawn\b|\bwithdrawn application\b", re.I
)
_AIR_COMPLETED = re.compile(
    r"\b(?:project (?:is |has been )?completed|construction (?:is |has been )?completed)\b",
    re.I,
)
_AIR_NEW_ACTIVITY = re.compile(
    r"\b(?:proposed|planned|new|additional|phase\s*[2-9]|install(?:ation|ed)?|adding|added|"
    r"expansion|expanding|construction|greenfield)\b.{0,100}\b(?:facility|campus|"
    r"data cent(?:er|re)|generator|turbine|unit|building|phase)\b",
    re.I,
)
_AIR_POWER_CONTEXT = re.compile(
    r"\b(?:campus|data cent(?:er|re))\b.{0,180}\b(?:\d[\d,.]*\s*MW|utility|"
    r"service|energiz|bridge|capacity|power allocation)\b|"
    r"\b(?:utility service|available service|partial service|power allocation|energization delay|"
    r"bridge power)\b.{0,180}\b\d[\d,.]*\s*MW\b",
    re.I,
)
_REPORTED_MW = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*MW\b", re.I)
_BOSTON_TEMP_GENERATOR = re.compile(
    r"\btemporary\b.{0,180}\bgenerators?\b|\bgenerators?\b.{0,180}\btemporary\b",
    re.I,
)
_BOSTON_KW_MW = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:kW|MW)\b", re.I)
BOSTON_PERMIT_EVALUATOR_VERSION = "boston-permit-power-facts-v1"


def evaluator_version(record: dict[str, Any]) -> str:
    permit = record.get("permit")
    if isinstance(permit, dict) and permit.get("source_type") == "ma-ccc-cultivation-applications":
        return "ma-cultivation-application-v1"
    if isinstance(permit, dict) and permit.get("source_type") in {
        "dallas-monthly-permits",
        "el-paso-new-commercial-permits",
        "houston-weekly-permits",
    }:
        return "city-permit-event-v1"
    if isinstance(permit, dict) and permit.get("source_type") == "texas-rrc-drilling-permits":
        return "rrc-permit-v1"
    if isinstance(permit, dict) and permit.get("source_type") == "texas-rrc-flare-vent-exceptions":
        return "rrc-flare-application-evidence-v1"
    if isinstance(permit, dict) and permit.get("source_type") == "georgia-air-draft-title-v":
        return GEORGIA_AIR_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "texas-tceq-nsr-pending":
        return TCEQ_NSR_EVALUATOR_VERSION
    if (
        isinstance(permit, dict)
        and permit.get("source_type") == "texas-tceq-temporary-batch-plants"
    ):
        return TCEQ_BATCH_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "california-ceqanet-data-centers":
        return CEQA_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "fort-worth-development-permits":
        return FORT_WORTH_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "san-antonio-development-permits":
        return SAN_ANTONIO_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "texas-tdlr-tabs-data-centers":
        return TABS_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") == "boston-building-permits":
        return BOSTON_PERMIT_EVALUATOR_VERSION
    if isinstance(permit, dict) and permit.get("source_type") in _REGIONAL_POWER_SOURCE_TYPES:
        return REGIONAL_POWER_EVALUATOR_VERSION
    return EVALUATOR_VERSION


def _reported_mw_facts(text: str) -> list[str]:
    facts = []
    for match in _REPORTED_MW.finditer(text):
        left = max(text.rfind(delimiter, 0, match.start()) for delimiter in (".", ";", "\n"))
        right_candidates = [
            position
            for delimiter in (".", ";", "\n")
            if (position := text.find(delimiter, match.end())) >= 0
        ]
        right = min(right_candidates) if right_candidates else len(text)
        clause = text[left + 1 : right]
        local_end = min(len(clause), match.end() - (left + 1) + 60)
        suffix = " ".join(clause[match.end() - (left + 1) : local_end].split())
        quote = " ".join(part for part in (match.group(0), suffix) if part)
        if quote and quote not in facts:
            facts.append(quote[:240])
    return facts[:12]


def _reported_boston_generator_facts(text: str) -> list[str]:
    """Retain exact temporary-generator rating context without deriving site load."""
    for scope in re.split(r"(?<=[.;\n])\s+", text):
        if _BOSTON_TEMP_GENERATOR.search(scope) and _BOSTON_KW_MW.search(scope):
            # Keep the entire official description, including campus/nameplate and
            # standby-scope qualifiers used downstream to avoid misreading capacity.
            return [text]
    return []


def _assess_georgia_air(
    record: dict[str, Any], permit: dict[str, Any], description: str, as_of: date
) -> dict[str, Any]:
    facility = str(record.get("title") or permit.get("facility") or "").strip()
    location_value = str(permit.get("address") or permit.get("city") or "").strip()
    location = ", ".join(
        part for part in (location_value, "Georgia" if location_value else "") if part
    )
    current_scope = str(permit.get("current_scope") or "")
    has_site_activity = bool(_AIR_FACILITY_ACTIVITY.search(current_scope))
    has_generation_activity = bool(_AIR_GENERATION_ACTIVITY.search(current_scope))
    has_power_context = bool(_AIR_POWER_CONTEXT.search(current_scope))
    has_distinct_new_activity = bool(_AIR_NEW_ACTIVITY.search(current_scope))
    withdrawn = bool(_AIR_WITHDRAWN.search(current_scope))
    completed = bool(_AIR_COMPLETED.search(current_scope)) and not has_distinct_new_activity
    withdrawn_or_done = withdrawn or completed
    citation_ok = bool(record.get("html_url") and permit.get("row_id") and permit.get("record_id"))
    date_value = record.get("event_date")
    date_label = record.get("event_date_label")
    has_dated_source = bool(date_value and date_label)
    activity = "facility-expansion" if has_site_activity else "backup-power"
    accepted = bool(
        facility
        and location_value
        and citation_ok
        and has_dated_source
        and (has_site_activity or has_generation_activity or has_power_context)
        and not withdrawn_or_done
    )
    if accepted:
        event_description = (
            "named facility construction or expansion"
            if has_site_activity
            else (
                "proposed onsite generator addition, partial utility service, or "
                "power-related campus activity"
            )
        )
        reason = (
            f"Georgia EPD's current draft-permit listing and linked narrative report a concrete "
            f"{event_description} at {facility} ({location}). This is a discovery Signal. "
            "Any reported campus, utility-service, or equipment values remain source facts; a "
            "possible construction/commissioning or bridge-power question is inferred. The "
            "filing does not establish rental MW, an unmet requirement, suitable supply, buyer, "
            "energization date, or project completion."
        )
    elif withdrawn_or_done:
        reason = (
            "Current Georgia application-purpose text explicitly reports withdrawal, "
            "completion, or operation; "
            "retain it as history, not an open project Signal."
        )
    elif not facility or not location_value:
        reason = "Georgia filing does not identify both a named facility and site location."
    elif not has_dated_source or not citation_ok:
        reason = (
            "Georgia listing lacks a dated source event or stable application/document citation."
        )
    else:
        reason = (
            "Georgia filing is listed, but its current application-purpose excerpt "
            "does not establish concrete "
            "facility construction/expansion or proposed generator activity; routine renewals "
            "remain evidence only."
        )
    reported_facts = _reported_mw_facts(current_scope)
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": facility if accepted else None,
        "action": current_scope if accepted else None,
        "location": location or None,
        "missing_facts": MISSING,
        "source_field_citations": {
            **permit.get("source_fields", {}),
            "current_scope_pages": permit.get("current_scope_pages", []),
        },
        "stable_row_id": permit.get("application_number") or permit.get("row_id"),
        "permit_status": permit.get("status"),
        "event_date": date_value,
        "event_date_label": date_label,
        "issue_date": None,
        "issue_date_label": None,
        "public_comment_deadline": permit.get("public_comment_deadline"),
        "application_received_date": permit.get("application_received_date"),
        "project_hint": facility or None,
        "power_activity": activity,
        "rental_category": "air-permit-discovery",
        "reported_claim": current_scope if accepted else None,
        "reported_power_facts": reported_facts
        + [
            f"Generator document context, page {fact['page']}: {fact['quote'][:220]}"
            + ("…" if len(fact["quote"]) > 220 else "")
            + " [scope/history unassigned; not rental demand]"
            for fact in permit.get("generator_facts", [])
            if fact.get("power_quantities")
            and all(q.get("basis") != "regulatory context" for q in fact["power_quantities"])
        ][:2],
        "generator_facts": permit.get("generator_facts", []),
        "generator_excerpts_omitted": permit.get("generator_excerpts_omitted", 0),
        "application_document_available": permit.get("application_document_available", False),
        "rental_hypothesis": (
            "Inferred review question only. Reported campus, available-service, and generator "
            "values remain separate source claims; no rental MW is calculated."
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "document_hashes": permit.get("document_hashes", {}),
    }


TCEQ_NSR_EVALUATOR_VERSION = "tceq-nsr-pending-v1"
REGIONAL_POWER_EVALUATOR_VERSION = "regional-power-record-v1"
_REGIONAL_POWER_SOURCE_TYPES = {
    "oklahoma-deq-public-review",
    "spp-thermal-interconnection",
    "albuquerque-building-permits",
}
_REGIONAL_DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)
_TCEQ_DATA_CENTER = re.compile(r"\bdata\s*centers?\b|\bhyperscale\b", re.IGNORECASE)
_TCEQ_ONSITE_LOAD = re.compile(
    r"onsite consumption|on-site consumption|behind[- ]the[- ]meter|"
    r"serve (?:the )?(?:onsite|on-site)|on-site data center|does not sell power to the grid",
    re.IGNORECASE,
)
_TCEQ_GENERATION = re.compile(
    r"generat\w* electricity|power generation|electric generating|generating units?|turbines?|"
    r"reciprocating engines?",
    re.IGNORECASE,
)
_TCEQ_CONSTRUCTION = re.compile(r"\btemporary\b.*\bbatch plant\b|\bconcrete batch\b", re.IGNORECASE)


def _assess_tceq_nsr(record: dict[str, Any], permit: dict[str, Any], as_of: date) -> dict[str, Any]:
    facility = str(permit.get("facility") or "").strip()
    applicant = str(permit.get("applicant") or "").strip()
    purpose = str(permit.get("purpose") or "")
    names = f"{applicant} {facility}"
    context = f"{names} {purpose}"
    data_center = bool(_TCEQ_DATA_CENTER.search(context))
    onsite_load = bool(_TCEQ_ONSITE_LOAD.search(purpose))
    generation = bool(_TCEQ_GENERATION.search(context))
    construction = bool(_TCEQ_CONSTRUCTION.search(facility))
    location = permit.get("location")
    citation_ok = bool(record.get("html_url") and permit.get("row_id"))
    dated = bool(record.get("event_date"))
    renewal = bool(permit.get("renewal_without_change"))
    accepted = bool(
        facility
        and location
        and citation_ok
        and dated
        and (data_center or onsite_load)
        and not renewal
    )
    # One recognized activity key; the specific event stays in the Signal text.
    activity = "facility-expansion"
    if construction and data_center:
        event = "a temporary construction batch plant serving a data-center project"
    elif generation and (data_center or onsite_load):
        event = "proposed onsite power generation for on-site load"
    else:
        event = "a data-center facility air permit application"
    if accepted:
        reason = (
            f"TCEQ lists a pending air permit application ({permit.get('application_stage')}) "
            f"from {applicant} for {facility} ({location}) describing {event}. "
            "Proposed onsite generation is proposed supply, not proof of adequate power: it is "
            "not yet authorized, and its timing relative to construction, commissioning and "
            "utility service is UNKNOWN. This is a discovery Signal; required temporary MW, "
            "start window, duration, buyer and authority remain unknown."
        )
    elif renewal:
        reason = (
            "Renewal of an existing air permit with no stated change; existing equipment is "
            "retained as evidence, not a new construction or power Signal."
        )
    elif not (data_center or onsite_load):
        reason = (
            "TCEQ air application without stated data-center or on-site load context; retained "
            "as evidence. A generating asset alone is not a load-side rental opportunity."
        )
    elif not location:
        reason = (
            "Data-center or on-site-load filing, but the plain-language summary did not yield a "
            "site; retained until a location is established."
        )
    else:
        reason = "TCEQ listing row lacks a dated event or stable citation."
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": (applicant or facility) if accepted else None,
        "action": event if accepted else None,
        "location": location,
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": permit.get("application_stage"),
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "application_received_date": record.get("event_date"),
        "project_hint": facility or None,
        "power_activity": activity,
        "rental_category": "air-permit-discovery",
        "reported_claim": purpose or None,
        "reported_power_facts": [],
        "rental_hypothesis": (
            "Inferred review question only: does construction or commissioning need temporary "
            "power before permitted onsite generation or utility service is available?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "coordinates": (
            [permit["latitude"], permit["longitude"]]
            if permit.get("latitude") is not None
            else None
        ),
    }


TCEQ_BATCH_EVALUATOR_VERSION = "tceq-temporary-batch-v1"
_NAMED_PROJECT = re.compile(r"\bPROJECT\s+[A-Z0-9][A-Z0-9-]+", re.IGNORECASE)


def _assess_tceq_batch(
    record: dict[str, Any], permit: dict[str, Any], as_of: date
) -> dict[str, Any]:
    facility = str(permit.get("facility") or "").strip()
    applicant = str(permit.get("applicant") or "").strip()
    location = permit.get("location")
    data_center = bool(_TCEQ_DATA_CENTER.search(facility))
    named_project = bool(_NAMED_PROJECT.search(facility))
    dated = bool(record.get("event_date"))
    accepted = bool(
        facility
        and location
        and dated
        and record.get("html_url")
        and (data_center or named_project)
    )
    subject = "a data-center project" if data_center else f"named project ({facility})"
    if accepted:
        reason = (
            f"TCEQ lists a pending temporary concrete batch plant registration "
            f"({permit.get('registration')}) by {applicant} serving {subject} at {location}, "
            f"submitted {record.get('event_date')}. A proposed temporary batch plant indicates "
            "planned heavy construction at the site; the registration is pending and does not "
            "show that construction has started. The construction-power question is inferred: "
            "required MW, duration, utility service date and the buyer are unknown, and the "
            "batch plant supplier is not the project owner or GC."
        )
    elif not (data_center or named_project):
        reason = (
            "Temporary batch plant without a named data-center or project site; retained as "
            "evidence."
        )
    else:
        reason = "Temporary batch plant notice lacks a dated event or site."
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": facility if accepted else None,
        "action": (
            "proposed temporary concrete batch plant for planned construction" if accepted else None
        ),
        "location": location,
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": permit.get("status"),
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "project_hint": facility or None,
        "power_activity": "facility-expansion",
        "rental_category": "construction-activity-discovery",
        "reported_claim": facility if accepted else None,
        "reported_power_facts": [],
        "rental_hypothesis": (
            "Inferred review question only: who carries temporary construction power on this "
            "site, and when is permanent service expected?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "coordinates": (
            [permit["latitude"], permit["longitude"]]
            if permit.get("latitude") is not None
            else None
        ),
    }


FORT_WORTH_EVALUATOR_VERSION = "fort-worth-data-center-permit-v1"
_RENOVATION = re.compile(r"\b(?:remodel|renovat\w*|interior finish|tenant finish)\b", re.IGNORECASE)


SAN_ANTONIO_EVALUATOR_VERSION = "san-antonio-data-center-permit-v1"
TABS_EVALUATOR_VERSION = "tdlr-tabs-data-center-v1"
_TABS_IN_SCOPE = {"new construction", "additions to existing building"}
_TABS_TERMINAL = re.compile(r"\bproject closed\b|\binspection complete(?:d)?\b", re.IGNORECASE)


def _assess_tabs(record: dict[str, Any], permit: dict[str, Any], as_of: date) -> dict[str, Any]:
    facility = str(permit.get("facility") or "").strip()
    description = str(permit.get("description") or "")
    work = str(permit.get("subtype") or "")
    status = str(permit.get("status") or "unknown")
    completion = permit.get("reported_completion")
    start = permit.get("reported_start")
    named = bool(_TCEQ_DATA_CENTER.search(description))
    in_scope = work.casefold() in _TABS_IN_SCOPE
    terminal = bool(_TABS_TERMINAL.search(status))
    finished = bool(completion and completion < as_of.isoformat())
    accepted = bool(
        named
        and in_scope
        and not terminal
        and not finished
        and record.get("event_date")
        and permit.get("location")
    )
    if accepted:
        reason = (
            f"TDLR TABS registration {permit.get('row_id', '')[5:]} ({work}) for a data center "
            f"({facility}) at {permit.get('location')}, registered {record.get('event_date')}; "
            f"owner {permit.get('applicant') or 'not stated'}. The developer reported a start of "
            f"{start or 'unknown'} and completion of {completion or 'unknown'}; these are the "
            "registrant's estimates, not confirmed construction dates. Estimated cost is the "
            "registrant's figure. MW, utility service date and the buyer are unknown unless "
            "stated in the scope."
        )
    elif not named:
        reason = "TABS registration does not name a data center."
    elif not in_scope:
        reason = f"{work or 'Unstated'} work, not new construction or an addition; not a new load."
    elif terminal:
        reason = f"TABS status is {status}; the project is closed or already inspected."
    elif finished:
        reason = f"Reported completion {completion} has passed; not a forward-looking need."
    else:
        reason = "TABS registration lacks a registration date or location."
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": facility if accepted else None,
        "action": "data-center construction registered with TDLR" if accepted else None,
        "location": permit.get("location"),
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": status,
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "project_hint": facility or None,
        "power_activity": "facility-expansion",
        "rental_category": "construction-activity-discovery",
        "reported_claim": facility if accepted else None,
        "reported_power_facts": _reported_mw_facts(description) if accepted else [],
        "rental_hypothesis": (
            "Inferred review question only: will permanent utility service be energized by "
            "the reported completion date?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "coordinates": None,
    }


def _assess_fort_worth(
    record: dict[str, Any], permit: dict[str, Any], as_of: date
) -> dict[str, Any]:
    """City data-center permit rule, shared by Fort Worth and San Antonio."""
    facility = str(permit.get("facility") or "").strip()
    description = str(permit.get("description") or "")
    subtype = str(permit.get("subtype") or "")
    status = str(permit.get("status") or "unknown")
    named = bool(_TCEQ_DATA_CENTER.search(description))
    substation = bool(re.search(r"\bsubstation\b", description, re.IGNORECASE))
    # Only new or added floor area, or a substation, is a new load; other subtypes are not.
    in_scope = subtype.casefold() in {"new", "addition"} or substation
    renovation = not in_scope or bool(_RENOVATION.search(subtype))
    terminal = bool(_INELIGIBLE_STATUS.search(status)) or bool(
        re.search(r"\b(?:denied|rejected)\b", status, re.IGNORECASE)
    )
    accepted = bool(
        named
        and not renovation
        and not terminal
        and record.get("event_date")
        and permit.get("location")
    )
    if accepted:
        subject = "a data-center substation" if substation else "a new or expanded data center"
        issued = status.casefold() == "issued"
        stage = (
            "An issued permit authorizes the work but does not show that construction has started."
            if issued
            else "A filed permit is not an issued permit and does not show that construction "
            "has started."
        )
        reason = (
            f"{permit.get('city')} {permit.get('permit_type')} {permit.get('row_id', '')[4:]} "
            f"for {subject} ({facility}) at {permit.get('location')}; "
            f"{record.get('event_date_label')}: {record.get('event_date')}; current status "
            f"{status}. {stage} Declared value is the applicant's estimate. MW, schedule, "
            "utility service date and the buyer are unknown unless stated in the description."
        )
    elif terminal and named:
        reason = f"Permit status is {status}; a closed or cancelled permit is not an active need."
    elif renovation:
        reason = (
            f"{subtype or 'Unstated'} permit, not new or added data-center floor area or a "
            "substation; retained as evidence, not a new load."
        )
    elif not named:
        reason = "Permit does not name a data center."
    else:
        reason = "Permit lacks a filed date or site."
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": facility if accepted else None,
        "action": (
            ("data-center substation permit" if substation else "data-center building permit")
            if accepted
            else None
        ),
        "location": permit.get("location"),
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": status,
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "project_hint": facility or None,
        "power_activity": "facility-expansion",
        "rental_category": "construction-activity-discovery",
        "reported_claim": facility if accepted else None,
        "reported_power_facts": _reported_mw_facts(description) if accepted else [],
        "rental_hypothesis": (
            "Inferred review question only: will permanent utility service be energized when "
            "construction or commissioning needs power?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "coordinates": (
            [permit["latitude"], permit["longitude"]]
            if permit.get("latitude") is not None
            else None
        ),
    }


CEQA_EVALUATOR_VERSION = "ceqanet-data-center-v1"
_CEQA_POLICY_ONLY = re.compile(
    r"\bmoratori|\bordinance\b|zoning (?:code|text) amendment|general plan update",
    re.IGNORECASE,
)


def _assess_ceqa(record: dict[str, Any], permit: dict[str, Any], as_of: date) -> dict[str, Any]:
    title = str(permit.get("facility") or "").strip()
    description = str(permit.get("description") or "")
    location = permit.get("location")
    in_title = bool(permit.get("title_names_data_center"))
    named = in_title or bool(_TCEQ_DATA_CENTER.search(description))
    policy_only = bool(_CEQA_POLICY_ONLY.search(title))
    accepted = bool(
        named
        and not policy_only
        and location
        and record.get("event_date")
        and record.get("html_url")
    )
    if accepted:
        mention = (
            "names a data center in its title"
            if in_title
            else "names a data center only in its description (it may be one design option)"
        )
        reason = (
            f"A CEQA {permit.get('document_type')} from lead agency {permit.get('lead_agency')} "
            f"({record.get('event_date_label')}: {record.get('event_date')}) {mention}, at "
            f"{location}. The site is in environmental "
            "review, not under construction; MW, schedule, utility service date and the buyer "
            "are unknown."
        )
    elif policy_only:
        reason = "CEQA filing is a policy, ordinance or moratorium action, not a project site."
    elif not named:
        reason = "CEQA filing does not name a data center."
    else:
        reason = "CEQA filing lacks a dated event, link or stated city or county."
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": title if accepted else None,
        "action": "data-center project in CEQA environmental review" if accepted else None,
        "location": location,
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": permit.get("status"),
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "project_hint": title or None,
        "power_activity": "facility-expansion",
        "rental_category": "construction-activity-discovery",
        "reported_claim": title if accepted else None,
        "reported_power_facts": _reported_mw_facts(description) if accepted else [],
        "rental_hypothesis": (
            "Inferred review question only: will utility service be ready when construction "
            "ends, and who would carry construction or bridge power?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
        "coordinates": (
            [permit["latitude"], permit["longitude"]]
            if permit.get("latitude") is not None
            else None
        ),
    }


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


def _assess_regional_power(
    record: dict[str, Any], permit: dict[str, Any], as_of: date
) -> dict[str, Any]:
    """Admit a dated in-region site only when the source text names the load mode."""
    facility = str(permit.get("facility") or "").strip()
    applicant = str(permit.get("applicant") or "").strip()
    description = str(permit.get("description") or "")
    location = permit.get("location") if isinstance(permit.get("location"), str) else None
    raw_tags = permit.get("power_signals")
    tags = (
        [tag for tag in raw_tags if tag in {"btm", "bridge", "temporary"}]
        if isinstance(raw_tags, list)
        else []
    )
    text = f"{applicant} {facility} {description}"
    data_center = bool(_REGIONAL_DATA_CENTER.search(text)) or bool(permit.get("data_center"))
    region = classify_project_region(location)
    event_date = record.get("event_date")
    try:
        event_day = date.fromisoformat(str(event_date)) if event_date else None
    except ValueError:
        event_day = None
    dated = bool(event_day and event_day <= as_of)
    citation = bool(record.get("html_url") and permit.get("row_id"))
    explicit_mode = bool(tags)
    accepted = bool(
        (facility or applicant)
        and location
        and region.status == "ELIGIBLE"
        and dated
        and citation
        and (data_center or explicit_mode)
    )
    if "temporary" in tags and not data_center:
        activity = "temporary-power"
    elif "bridge" in tags and not data_center:
        activity = "bridge-power"
    else:
        activity = "facility-expansion"
    if accepted and data_center:
        reason = (
            f"Official record names a data-center project at {location}. "
            "Required MW, start, duration, buyer, and utility service remain unknown. "
            f"Source power-signal tags: {', '.join(tags) or 'none'}."
        )
    elif accepted:
        reason = (
            f"Official record states {' / '.join(tags)} power at {location}. "
            "That tag is copied from the source text. It does not establish MW, "
            "a buyer, or that temporary supply is still required."
        )
    elif not dated:
        reason = (
            "The source row does not state an event date, so it stays evidence. "
            "No date was inferred from retrieval time."
        )
    elif region.status != "ELIGIBLE":
        reason = (
            "The stated site is outside TX/OK/NM or is not an explicit place, "
            "so the row stays evidence."
        )
    else:
        reason = (
            "Generation, interconnection, or generator text without a data center "
            "or an explicit behind-the-meter, bridge, or temporary power statement "
            "stays evidence. Queue or nameplate MW is not site load."
        )
    return {
        "schema_version": 1,
        "decision": "accepted" if accepted else "rejected",
        "tier": "Signal" if accepted else None,
        "reason": reason,
        "subject": (applicant or facility) if accepted else None,
        "action": description if accepted else None,
        "location": location,
        "missing_facts": MISSING,
        "source_field_citations": permit.get("source_fields", {}),
        "stable_row_id": permit.get("row_id"),
        "permit_status": permit.get("status"),
        "event_date": event_date,
        "event_date_label": record.get("event_date_label"),
        "issue_date": None,
        "issue_date_label": None,
        "project_hint": facility or None,
        "power_activity": activity if accepted else None,
        "power_signals": tags,
        "rental_category": "regional-power-discovery" if accepted else None,
        "reported_claim": description if accepted else None,
        "reported_power_facts": [],
        "rental_hypothesis": (
            "Inferred review question only: does the stated site need temporary or bridge "
            "power before utility service or on-site generation is available?"
            if accepted
            else None
        ),
        "activity_end_date": None,
        "review_after": None,
        "as_of_date": as_of.isoformat(),
        "document_links": permit.get("document_links", {}),
    }


def assess_permit(record: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    permit = record.get("permit")
    if not isinstance(permit, dict):
        raise ValueError("Permit fields are missing")
    description = str(permit.get("description") or "")
    as_of = as_of or evaluation_today(date.today())
    if permit.get("source_type") == "ma-ccc-cultivation-applications":
        status = str(permit.get("application_status") or "").strip().upper()
        license_status = str(permit.get("license_status") or "").strip().upper()
        active_application = status in {"PENDING", "REOPENED"}
        already_licensed_or_operating = bool(
            permit.get("commence_operations_date")
            or permit.get("license_start_date")
            or permit.get("license_original_start_date")
            or permit.get("license_expiration_date")
            or permit.get("final_licensure_date")
            or permit.get("license_revocation_date")
            or permit.get("license_surrendered_date")
            or permit.get("license_suspended_start_date")
            or license_status in {"ACTIVE", "EXPIRED", "SURRENDERED", "REVOKED", "SUSPENDED"}
        )
        applicant = str(permit.get("applicant_org") or permit.get("business_name") or "").strip()
        address = str(permit.get("address") or "").strip()
        city = str(permit.get("city") or "").strip()
        state = str(permit.get("state") or "").strip().upper()
        location = ", ".join(part for part in (address, city, state, permit.get("zip")) if part)
        event_date = record.get("event_date")
        try:
            event_day = date.fromisoformat(str(event_date)) if event_date else None
        except ValueError:
            event_day = None
        site_ok = bool(address and city and state == "MA")
        citation_ok = bool(
            permit.get("application_number") or permit.get("license_number")
        ) and str(record.get("html_url") or "").startswith(
            "https://masscannabiscontrol.com/resource/"
        )
        accepted = bool(
            applicant
            and site_ok
            and citation_ok
            and event_day
            and event_day <= as_of
            and (as_of - event_day).days <= 120
            and active_application
            and not already_licensed_or_operating
        )
        if accepted:
            reason = (
                f"The CCC snapshot records a dated {status.lower()} cultivation-license "
                f"application for applicant {applicant} at {location}. This is an early "
                "investigation Signal "
                "about an application event only; construction, operations, load, rental need, "
                "buyer, and authority are UNKNOWN."
            )
        elif already_licensed_or_operating:
            reason = (
                "CCC lifecycle facts indicate an issued, operating, or closed license; "
                "retain as history, not a new-facility Signal."
            )
        elif not active_application:
            reason = (
                "Only pending or explicitly reopened cultivation applications qualify "
                "for this application-event Signal."
            )
        elif not site_ok:
            reason = (
                "CCC application does not identify a complete physical Massachusetts "
                "establishment site."
            )
        elif not event_day or event_day > as_of or not citation_ok:
            reason = "A valid dated application event and official source citation are required."
        else:
            reason = "CCC cultivation application lacks an identifiable applicant organization."
        return {
            "schema_version": 1,
            "decision": "accepted" if accepted else "rejected",
            "tier": "Signal" if accepted else None,
            "reason": reason,
            "subject": applicant if accepted else None,
            "action": f"{status.title()} cultivation-license application" if accepted else None,
            "location": location or None,
            "missing_facts": [
                "construction status",
                "load",
                "rental need",
                "buyer",
                "buying authority",
            ],
            "source_field_citations": permit.get("source_fields", {}),
            "stable_row_id": permit.get("application_number") or permit.get("license_number"),
            "permit_status": status or None,
            "event_date": event_date,
            "event_date_label": record.get("event_date_label"),
            "issue_date": None,
            "issue_date_label": None,
            "project_hint": applicant or None,
            "power_activity": "cultivation-license-application",
            "rental_category": "cultivation-application-discovery",
            "reported_claim": record.get("event_date_label") if accepted else None,
            "reported_power_facts": [],
            "rental_hypothesis": None,
            "activity_end_date": None,
            "review_after": None,
            "as_of_date": as_of.isoformat(),
        }
    if permit.get("source_type") == "texas-tceq-nsr-pending":
        return _assess_tceq_nsr(record, permit, as_of)
    if permit.get("source_type") == "texas-tceq-temporary-batch-plants":
        return _assess_tceq_batch(record, permit, as_of)
    if permit.get("source_type") in _REGIONAL_POWER_SOURCE_TYPES:
        return _assess_regional_power(record, permit, as_of)
    if permit.get("source_type") == "california-ceqanet-data-centers":
        return _assess_ceqa(record, permit, as_of)
    if permit.get("source_type") == "texas-tdlr-tabs-data-centers":
        return _assess_tabs(record, permit, as_of)
    if permit.get("source_type") in {
        "fort-worth-development-permits",
        "san-antonio-development-permits",
    }:
        return _assess_fort_worth(record, permit, as_of)
    if permit.get("source_type") == "georgia-air-draft-title-v":
        return _assess_georgia_air(record, permit, str(permit.get("current_scope") or ""), as_of)
    if permit.get("source_type") == "texas-rrc-drilling-permits":
        accepted = bool(
            permit.get("row_id")
            and permit.get("lease")
            and permit.get("well")
            and permit.get("status") == "Approved"
            and permit.get("application_type") in {"01", "07", "14"}
            and record.get("event_date")
            and record.get("html_url")
        )
        return {
            "schema_version": 1,
            "decision": "accepted" if accepted else "rejected",
            "tier": "Signal" if accepted else None,
            "reason": (
                "Official drilling permit is an early production Signal; no power gap is required."
                if permit.get("application_type") == "01"
                else (
                    "Approved well reentry/recompletion may lead to field power activity; "
                    "current phase is UNKNOWN."
                )
            )
            if accepted
            else (
                "A dated approved drill/reentry/recompletion permit and identified well are "
                "required; administrative field-transfer/reclass records remain evidence."
            ),
            "subject": f"Texas W-1 permit {permit.get('row_id')}" if accepted else None,
            "action": description if accepted else None,
            "location": permit.get("location"),
            "missing_facts": [
                "production date",
                "load",
                "fuel suitability",
                "suitable supply",
                "buyer",
            ],
            "stable_row_id": permit.get("row_id"),
            "permit_status": permit.get("status"),
            "issue_date": record.get("event_date"),
            "issue_date_label": record.get("event_date_label"),
            "project_hint": permit.get("project"),
            "power_activity": "drilling"
            if permit.get("application_type") == "01"
            else "well-permit",
            "rental_category": "early_production"
            if permit.get("application_type") == "01"
            else "well_permit_activity",
            "reported_claim": description if accepted else None,
            "rental_hypothesis": (
                "Authorized drilling or well rework may precede production power; "
                "it does not prove work started/completed. Rental demand, production date, "
                "load and fuel suitability remain UNKNOWN."
            )
            if accepted
            else None,
        }
    if permit.get("source_type") == "texas-rrc-flare-vent-exceptions":
        return {
            "schema_version": 1,
            "decision": "rejected",
            "tier": None,
            "reason": (
                "Evidence only: the RRC public result row identifies an exception application, "
                "operator and property label but provides no verified physical flare/vent or well "
                "location and no actual flaring. The application alone does not establish a "
                "power activity or Signal."
            ),
            "subject": None,
            "action": None,
            "location": None,
            "missing_facts": [
                "physical flare/vent or well location",
                "actual flaring or venting",
                "gas availability and composition",
                "continuous gas flow",
                "generator fit",
                "MW",
                "rental demand",
                "buyer",
                "buying authority",
            ],
            "stable_row_id": permit.get("row_id"),
            "permit_status": permit.get("status"),
            "application_submittal_date": permit.get("submittal_date"),
            "authorized_effective_date": permit.get("authorized_effective_date"),
            "authorized_expiration_date": permit.get("authorized_expiration_date"),
            "operator": permit.get("operator"),
            "property_label": permit.get("property"),
            "power_activity": None,
            "rental_hypothesis": None,
        }
    event_end = _explicit_event_end(description)
    status = str(permit.get("status") or "")
    source_type = str(permit.get("source_type") or "")
    permit_event = str(permit.get("issuance_event") or "")
    event_supports_permit = bool(
        source_type
        in {
            "dallas-monthly-permits",
            "el-paso-new-commercial-permits",
            "houston-weekly-permits",
        }
        and permit_event in {"issued", "sold"}
        and not _INELIGIBLE_STATUS.search(status)
    )
    status_supports_permit = bool(
        _ELIGIBLE_STATUS.fullmatch(status.strip())
        or (source_type == "boston-building-permits" and status.strip().casefold() == "open")
        or event_supports_permit
    )
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
        and not (_ORDINARY_TARGET.search(description) and not _DATA_OR_LAB.search(description))
        and not re.search(r"\b(?:mini[- ]?warehouse|self[- ]storage)\b", description, re.I)
        and not _NEGATED.search(description)
        and not _NEGATED_FACILITY.search(description)
        and not _ROUTINE.search(description)
    ):
        activity, category = "facility-expansion", "facility_activity"
        reason = "Official dated permit identifies concrete facility construction, conversion, or remodel; investigate construction or commissioning power. Permit issuance does not prove work start, load, or a power gap."  # noqa: E501
    else:
        category = "none"
        if not status_supports_permit or _INELIGIBLE_STATUS.search(status):
            reason = f"Permit application/lifecycle status is {status or 'unknown'}; no supported current permit event establishes the work."  # noqa: E501
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
        and status_supports_permit
        and not _INELIGIBLE_STATUS.search(status)
        and not _RESIDENTIAL.search(description)
    )
    decision = "accepted" if activity and gates_ok else "rejected"
    if activity and not gates_ok:
        reason = "A dated eligible permit state or supported source-specific sold/issued event, identified site, and source citation are required."  # noqa: E501
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
        **(
            {
                "source_row_id": permit.get("raw_source_row_id"),
                "applicant": permit.get("applicant"),
                "applicant_role": "applicant",
                "buyer_role": "UNKNOWN",
            }
            if source_type == "boston-building-permits"
            else {}
        ),
        "stable_row_id": permit.get("row_id"),
        "permit_status": status,
        "permit_event": permit_event or None,
        "permit_status_label": (
            "Permit application status"
            if source_type == "el-paso-new-commercial-permits"
            else "Boston permit status"
            if source_type == "boston-building-permits"
            else "Current permit lifecycle status"
        ),
        "issue_date": None if source_type == "houston-weekly-permits" else record.get("event_date"),
        "issue_date_label": None
        if source_type == "houston-weekly-permits"
        else (
            "Permit Issued Date (published monthly report)"
            if source_type == "dallas-monthly-permits"
            else "ISSUEDATE (official layer issue-event field)"
            if source_type == "el-paso-new-commercial-permits"
            else "Official permit issue date; source publication date unknown"
        ),
        "event_date": record.get("event_date"),
        "event_date_label": record.get("event_date_label"),
        "project_hint": permit.get("project") or None,
        "power_activity": activity or "facility-expansion",
        "rental_category": category,
        "reported_claim": description if decision == "accepted" else None,
        "reported_power_facts": (
            _reported_boston_generator_facts(description)
            if source_type == "boston-building-permits"
            else []
        ),
        "rental_hypothesis": "Inferred; permit text does not establish rental requirement, MW, buyer, suitable supply, start, or duration."  # noqa: E501
        if decision == "accepted"
        else None,
        "activity_end_date": event_end.isoformat() if event_end else None,
        "review_after": event_end.isoformat() if event_end and decision == "accepted" else None,
    }
