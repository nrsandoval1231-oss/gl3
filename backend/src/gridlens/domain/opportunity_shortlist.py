"""Bounded commercial relevance from immutable source text, never browse labels.

This is a discovery shortlist, not demand qualification or buyer verification.
Source publication/permit dates govern freshness; retrieval timestamps do not.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any, TypedDict

POLICY_VERSION = "source-shortlist-v1"
MAX_SOURCE_AGE_DAYS = 365


class _AcceptedSource(TypedDict):
    id: str
    date: date
    reason: str
    priority: int
    jev_show: bool
    subject: str
    scope: str
    label: str
    schedule: str
    next_step: str
    duplicate_key: str | None


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _fields(text: str) -> dict[str, str]:
    return {
        key.strip().casefold(): value.strip()
        for line in text.splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


_STRUCTURED_SOURCE_KEYS = {
    "project",
    "facility",
    "scope",
    "work description",
    "description",
    "stated purpose",
    "type of work",
    "work",
    "status",
    "tabs status",
    "permit",
    "permit type",
    "permit number",
    "permit no",
    "permit #",
    "row",
    "address",
    "contact",
    "applicant",
    "contractor",
    "owner",
    "developer",
    "phone",
    "telephone",
    "email",
    "applicant email",
    "applicant_email",
    "contractor phone",
    "contractor_phone",
    "event",
    "event date",
    "source",
    "source id",
    "source_id",
    "registration",
    "parcel",
    "title",
    # Native labels emitted by CEQAnet, TDLR, TCEQ, municipal permits,
    # RRC and utility adapters. Their values identify parties/documents/sites;
    # they are not project activity prose when a scope field is absent.
    "project applicant",
    "project name",
    "lead agency",
    "document type",
    "document",
    "addresses",
    "location",
    "physical location",
    "site location",
    "site name",
    "owner of record",
    "legal name",
    "customer",
    "design firm",
    "transmission owner",
    "sponsor as filed",
    "permittee",
    "operator",
    "operator number",
    "api number",
    "application number",
    "control number",
    "filing number",
    "interconnection number",
    "permit numbers",
    "permit/status number",
    "lease",
    "well",
}


def _has_structured_record(fields: dict[str, str]) -> bool:
    for key in fields:
        # Socrata and El Paso render underscore keys, while other adapters use
        # spaced labels. Recognize bounded party/contact variants in either
        # spelling without treating arbitrary prose before a colon as a key.
        normalized = " ".join(key.replace("_", " ").split())
        if normalized in _STRUCTURED_SOURCE_KEYS or re.fullmatch(
            r"(?:owner|contractor|applicant|developer|operator|primary contact)"
            r"(?: (?:name|full name|company name|org|trade|address|contact(?: name)?|"
            r"phone|telephone|email|contact phone|contact email))?",
            normalized,
        ):
            return True
    return False


def _has_affirmative_electrically_driven_equipment(scope: str) -> bool:
    equipment = r"(?:pumps?|compressors?|motors?)"
    electric_drive = r"(?:electric(?:al)?(?:[- ]motor[- ]driven)?|electrically[- ]driven)"
    modifier = rf"(?:{electric_drive}|motor[- ]driven)"
    # Require the modifier to describe the equipment, or a stated drive/motor
    # relationship. An electrical contractor, utility name or service elsewhere
    # in the same clause does not establish how a pump/compressor is driven.
    relationship = (
        rf"\b{modifier}[- ]+(?:(?:centrifugal|submersible|reciprocating|rotary|screw)\s+)?"
        rf"{equipment}\b(?!\s+(?:company|co\b|inc\b|llc\b|contractor|shop))|"
        rf"\b{equipment}\s+(?:(?:that\s+)?(?:is|are|will be|to be)\s+)?"
        rf"(?:electrically[- ](?:driven|powered)|motor[- ]driven)\b|"
        rf"\b{equipment}\s+(?:with|to|driven by|powered by)\s+"
        r"(?:(?:a|an|the|new)\s+){0,2}electric(?:al)?\s+(?:drive|motor)s?\b"
    )
    negated = (
        r"\b(?:non[- ](?:electric(?:al)?|motor[- ]driven)|"
        r"not\b.{0,48}\b(?:electric(?:al)?(?:ly)?|motor[- ]driven|electric model)\b|"
        r"(?:no|without)\b.{0,48}\b(?:electric(?:al)?|motor[- ]driven)\b|"
        r"(?:electric(?:al)?|motor[- ]driven)\b.{0,48}\b(?:not included|not provided|not specified|"
        r"not present|not required|not used|not installed|excluded|absent)\b)"
    )
    changed = r"\b(?:new|install\w*|expand\w*|replac\w*|upgrade\w*)\b"
    clauses = re.split(
        r"[.,;]|\b(?:but|whereas)\b|\s+and\s+|\bwith\s+(?=a?\s*new\b)",
        scope,
        flags=re.I,
    )
    return any(
        _has(relationship, clause) and _has(changed, clause) and not _has(negated, clause)
        for clause in clauses
    )


def _positive_development_scope(scope: str) -> tuple[str, bool]:
    """Remove explicit negative development clauses without erasing separate work."""
    denial = re.compile(
        r"\bno\b.{0,100}\b(?:new\s+)?(?:construction|development|expansion|"
        r"buildout|electrical work|power work)\b.{0,60}\b(?:proposed|planned|"
        r"authorized|underway|reported|occurring)\b|"
        r"\b(?:new\s+)?(?:construction|development|expansion|buildout|"
        r"electrical work|power work)\b.{0,60}\b(?:is|are|was|were)?\s*"
        r"(?:not|never)\s+(?:proposed|planned|authorized|underway|reported|occurring)\b",
        re.I,
    )
    clauses = re.split(r"[.;]|\b(?:but|whereas|however)\b", scope, flags=re.I)
    denied = [clause for clause in clauses if denial.search(clause)]
    positive = [clause for clause in clauses if not denial.search(clause)]
    return " ".join(positive), bool(denied)


def _clean(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", value)
    value = re.sub(
        r"(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)",
        "[redacted]",
        value,
    )
    return " ".join(value.split())


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _next_step(reason: str) -> str:
    if "commercial electrical buildout" in reason:
        return (
            "Confirm the electrical service installation phase, energization schedule "
            "and organization responsible for construction power."
        )
    if "energization" in reason:
        return (
            "Confirm the cited energization constraint, permanent-service date "
            "and whether interim supply is required."
        )
    if "restoration" in reason:
        return (
            "Confirm whether occupied-space repairs remain open and the "
            "temporary electrical service window."
        )
    if "replacement" in reason:
        return (
            "Confirm the generator transfer or outage schedule and whether "
            "temporary continuity power is needed."
        )
    if "temporary loads" in reason:
        return (
            "Confirm the construction load schedule and whether the cited "
            "service is utility supplied or requires temporary generation."
        )
    if "data-center" in reason:
        return (
            "Confirm the current construction milestone and identify the EPC "
            "or organization procuring construction and commissioning power."
        )
    if "equipment" in reason:
        return (
            "Confirm equipment ratings, electrical drive, installation timing "
            "and the organization responsible for the work."
        )
    return (
        "Confirm the industrial work phase, construction power "
        "arrangements and the owner or contractor responsible for "
        "procurement."
    )


def _subject(fields: dict[str, str], title: str, reason: str) -> str:
    """Prefer source names; never promote permit system identifiers to titles."""
    for candidate in (fields.get("project"), fields.get("facility")):
        if not candidate:
            continue
        name = candidate.strip()
        identifier = _has(
            r"^(?:[\d\W]+|\d{4}-\d+\s+(?:BP|EP)|"
            r"(?:TABS|PB|BP|EP|FTW|TCEQ)[-\s]?\d.*|COM-(?:NEW|ALT)-\d.*|"
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|"
            r"(?:project|permit|registration)\s*(?:no\.?|number|#)?\s*\d.*)$",
            name,
        )
        if not identifier:
            return _clean(name)[:200]
    if not fields and not _has(r"\bpermit\b", title):
        return _clean(title)[:200]
    if "restoration" in reason:
        return "Temporary electrical restoration"
    if "replacement" in reason:
        return "Generator/transfer-switch replacement"
    if "temporary loads" in reason:
        return "Construction electrical service"
    if "data-center" in reason:
        return "Data center buildout"
    if "energization" in reason:
        return "Utility energization constraint"
    if "electrically driven" in reason:
        return "Electrical equipment installation"
    if "commercial electrical buildout" in reason:
        return "Commercial electrical buildout"
    return "Industrial construction"


def _development(title: str, scope: str, fields: dict[str, str]) -> tuple[int, str] | None:
    """Interpret bounded source clauses rather than unrelated metadata keywords."""
    positive_scope, has_negated_development = _positive_development_scope(scope)
    context = (
        ""
        if has_negated_development
        else (f"{title} {fields.get('project', '')} {fields.get('facility', '')}")
    )
    work = f"{fields.get('type of work', '')} {fields.get('work', '')} {positive_scope}"
    if (
        has_negated_development
        and not _has(
            r"\b(?:new|install\w*|construct\w*|foundation\w*|expand\w*|expansion|"
            r"remodel|commission\w*|replac\w*|upgrade\w*)\b",
            work,
        )
        and not _has_affirmative_electrically_driven_equipment(work)
    ):
        return None
    text = f"{context} {work}"
    # Structured terminal statuses apply to the permit, not phrases such as
    # TABS 'Review Complete', a complete application, or a completed foundation.
    status = fields.get("status", "").split("(", 1)[0].strip().casefold()
    if status in {
        "complete",
        "completed",
        "closed",
        "cancelled",
        "canceled",
        "expired",
        "withdrawn",
    }:
        return None
    if _has(
        (
            r"\b(?:project|construction|development) (?:has been |is |was "
            r")?(?:cancelled|canceled|abandoned)\b"
        ),
        text,
    ):
        return None
    if _has(r"\bW-1\b|\bdrilling permit\b", title):
        return None
    temporary_negated = _has(
        (
            r"\b(?:no temporary (?:power|service)|temporary (?:power|service) "
            r"(?:is )?not (?:needed|required))\b"
        ),
        scope,
    )
    if _has(
        r"\b(?:dry well|condensat(?:e|ion)|chain link fence|sports light pole foundations?)\b",
        scope,
    ):
        return None
    if _has(r"\b(?:tent|product launch event|stage vendors)\b", scope):
        return None
    named_project = fields.get("project") or fields.get("facility")
    constrained = _has(
        r"\b(?:utility energization|permanent (?:utility )?service|grid connection) "
        r"(?:is |has been |will be )?(?:delayed|unavailable|deferred)\b",
        scope,
    )
    constraint_negated = _has(
        r"\bno (?:utility )?energization delay\b|"
        r"\b(?:energization|service|connection) (?:is )?not (?:delayed|unavailable)\b",
        scope,
    )
    if (
        named_project
        and not str(named_project).isdigit()
        and constrained
        and not constraint_negated
    ):
        return (
            95,
            "Source reports an energization or permanent-service constraint for the named project",
        )
    # A temporary *permit* is not temporary electrical demand. Match service
    # and actual construction loads, or explicitly described emergency work.
    if _has(
        r"\b(?:emergency[- ]temporary electrical|reenergize occupied|re-energize occupied)\b", scope
    ):
        return 95, "Source describes temporary electrical restoration pending permanent repairs"
    if _has(r"\b(?:generator|\bATS\b)\b", scope) and _has(
        r"\b(?:replac\w*|maintain emergency power)\b", scope
    ):
        return (
            90,
            (
                "Source describes generator or transfer-switch replacement; "
                "continuity needs require confirmation"
            ),
        )
    temporary_service = _has(
        r"\btemporary (?:electrical )?(?:service|power|meter loop)\b|\bconstruction power\b", scope
    )
    specific_load = _has(
        r"\b(?:\d+\s*(?:amp|a)\b|crane|hoist|school|jobsite|construction)\b", scope
    )
    if temporary_service and specific_load and not temporary_negated:
        return (
            90,
            (
                "Source describes construction electrical service or specific "
                "temporary loads; rental need remains unconfirmed"
            ),
        )
    # Material non-DC work must describe both the facility/construction scope
    # and actual electrical services or installation. Permit type alone and
    # generic civil construction at a commercial address are insufficient.
    commercial_facility = _has(
        r"\b(?:hospital|industrial warehouse|utility plant|castings? building|foundry)\b",
        scope,
    )
    construction_scope = _has(
        r"\b(?:new|addition|construct\w*|foundation\w*|expand\w*|expansion)\b", scope
    )
    electrical_scope = _has(
        r"\b(?:electrical (?:underground|distribution|service|buildout|installation)\b|"
        r"\d+(?:,\d{3})*\s*(?:amp(?:ere)?s?|a)\s+(?:electrical\s+)?services?\b)",
        scope,
    )
    if commercial_facility and construction_scope and electrical_scope:
        return (
            80,
            "Source describes material commercial electrical buildout; "
            "service ratings are not MW demand",
        )
    dc = _has(r"\bdata cent(?:er|re)s?\b|\bcolocation\b", text)
    development = _has(
        r"\b(?:new construction|new (?:data cent(?:er|re)|building)|construct(?:ion|ing)?|"
        r"to build|will build|topped out|groundbreak\w*|expand\w*|expansion|"
        r"commission\w*|finish out|fit[- ]out|substation|control house)\b",
        work + " " + title,
    )
    development = development or bool(
        _has(r"\bnew\b", fields.get("permit", ""))
        and _has(r"\b(?:data cent(?:er|re)|control house)\b", scope)
    )
    if dc and development and not _has(r"\bexisting registration\b", text):
        return (
            80,
            (
                "Source describes a specific data-center construction or "
                "electrical-buildout development"
            ),
        )
    industrial = _has(
        (
            r"\b(?:manufacturing|factory|industrial campus|compressor "
            r"station|gas processing|refinery)\b"
        ),
        text,
    )
    substantive = _has(
        r"\b(?:new|construct\w*|foundation\w*|expand\w*|expansion|remodel|commission\w*)\b",
        work + " " + title,
    )
    if industrial and substantive:
        return (
            70,
            (
                "Source describes industrial construction, expansion or equipment "
                "work; electrical requirements remain to be established"
            ),
        )
    # Equipment evidence can identify a meaningful change even at an existing
    # site. Electrical-drive evidence is required; horsepower alone is not MW.
    if _has_affirmative_electrically_driven_equipment(scope):
        return (
            80,
            (
                "Source identifies new or changed electrically driven equipment; "
                "demand amount remains source dependent"
            ),
        )
    return None


def _duplicate_key(source: dict[str, Any], fields: dict[str, str], scope: str) -> str | None:
    """Only exact native paired-permit scope or identical news coverage clusters."""
    source_id = str(source["source_id"])
    permit = fields.get("row", "")
    match = re.fullmatch(r"(\d{4}-\d+)\s+(?:BP|EP)", permit, re.I)
    address = fields.get("address")
    if match and address and scope:
        identity = [source_id, match[1], _norm(address), _norm(scope)]
    elif "news" in source_id.casefold() and source.get("title") and scope:
        # Identical headline AND abstract are required, not merely company name.
        identity = ["identical-news-development", _norm(str(source["title"])), _norm(scope)]
    else:
        return None
    return hashlib.sha256("\x1f".join(identity).encode()).hexdigest()


def shortlist_assessment(
    compact: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    """Assess exact current source versions already bound to a need by the caller.

    ``compact`` supplies only the unknown-MW display state. Eligibility, scope,
    timing, and explanatory excerpts come exclusively from retained sources.
    """
    today = as_of or now or date.today()
    accepted: list[_AcceptedSource] = []
    for source in sources:
        if not (
            source.get("id")
            and source.get("source_id")
            and source.get("assessment_current") is True
        ):
            continue
        title = str(source.get("title") or "").strip()
        body = str(source.get("text") or source.get("abstract") or "").strip()
        if not title or not body:
            continue
        event_day = _day(source.get("event_date"))
        published_day = _day(source.get("published_at"))
        if published_day and published_day > today:
            continue
        event_label = str(source.get("event_date_label") or "")
        planned_event = bool(event_day) and _has(
            r"\b(?:planned|estimated|expected|developer[- ]reported|registrant[- ]reported)\b",
            event_label,
        )
        # A published proposal may legitimately describe a future milestone.
        # Its publication establishes freshness; its estimate is never an
        # accomplished event or a reason to use retrieval time as source time.
        source_day = published_day if planned_event else event_day or published_day
        if source_day is None or not 0 <= (today - source_day).days <= MAX_SOURCE_AGE_DAYS:
            continue
        if planned_event and event_day and (event_day - today).days > 730:
            continue
        parsed_fields = _fields(body)
        structured_record = _has_structured_record(parsed_fields)
        fields = parsed_fields if structured_record else {}
        scope = next(
            (
                fields[k]
                for k in ("scope", "work description", "description", "stated purpose")
                if fields.get(k)
            ),
            None,
        )
        # Unstructured news abstracts are retained source excerpts. For other
        # structured records, do not classify contact/address/metadata lines.
        if scope is None:
            scope = "" if structured_record else body
        jev_decision = source.get("jev_decision")
        # Jev is advisory at source-version granularity: a validated HOLD can
        # remove this source from triage, while SHOW only breaks ties between
        # equally strong deterministic source assessments. REVIEW/absence
        # abstains so sparse model coverage cannot hide a project.
        if jev_decision == "HOLD":
            continue
        decision = _development(title, scope, fields)
        if decision is None:
            continue
        priority, reason = decision
        label = event_label or "Source event" if event_day and not planned_event else "Published"
        subject = _subject(fields, title, reason)
        excerpt = scope or title
        # The headline carries news events such as topped out; abstract alone
        # can omit them. Structured permit explanations use the actual scope.
        if not structured_record:
            excerpt = f"{title}. {scope}"
        schedule = (
            f"; {_clean(event_label)} {event_day.isoformat()} (estimate)"
            if planned_event and event_day
            else ""
        )
        accepted.append(
            {
                "id": str(source["id"]),
                "date": source_day,
                "reason": reason,
                "priority": priority,
                "jev_show": jev_decision == "SHOW",
                "subject": _clean(subject)[:200],
                "scope": _clean(excerpt)[:320],
                "label": _clean(label),
                "schedule": schedule,
                "next_step": _next_step(reason),
                "duplicate_key": _duplicate_key(source, fields, scope),
            }
        )
    accepted.sort(
        key=lambda item: (item["priority"], item["jev_show"], item["date"], item["id"]),
        reverse=True,
    )
    chosen = accepted[0] if accepted else None
    reasons = list(dict.fromkeys(item["reason"] for item in accepted))
    if chosen and compact.get("required_mw") is None:
        reasons.append(
            "MW unknown; source-backed development is retained without an "
            "inferred load or supply gap"
        )
    keys = {item["duplicate_key"] for item in accepted}
    return {
        "eligible": bool(chosen),
        "reasons": reasons,
        "evidence_refs": sorted({item["id"] for item in accepted}),
        "why_now": (
            f"{chosen['label']} {chosen['date'].isoformat()}: {chosen['scope']}{chosen['schedule']}"
        )
        if chosen
        else None,
        "next_step": chosen["next_step"] if chosen else None,
        "source_subject": chosen["subject"] if chosen else None,
        "scope": chosen["scope"] if chosen else None,
        "priority": chosen["priority"] if chosen else 0,
        "duplicate_key": next(iter(keys)) if len(keys) == 1 else None,
        "policy_version": POLICY_VERSION,
    }
