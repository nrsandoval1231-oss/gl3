"""Deterministic, bounded commercial questions. No retrieval or state writes."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

POLICY_VERSION = "autonomous-pursuit-research-v4"
ACTIVE = ("QUEUED", "SEARCHING", "REVIEWING_EVIDENCE")
ROUTES = {
    "identity": ("owner-projects", "official-company", "municipal-records"),
    "duration": ("contractor-schedules", "owner-updates", "utility-filings"),
    "suitability": ("engineering-drawings", "equipment-schedules", "public-bids"),
    "fuel": ("fuel-supply-records", "owner-projects", "public-bids"),
    "voltage": ("electrical-permits", "engineering-drawings", "equipment-schedules"),
    "load_profile": ("engineering-drawings", "equipment-schedules", "public-bids"),
    "procurement": ("public-bids", "owner-projects", "contractor-updates"),
    "utility_obstacle": ("utility-filings", "interconnection-documents", "municipal-records"),
    "power_need": (
        "temporary-service-permits",
        "public-bids",
        "contractor-projects",
        "owner-projects",
        "public-web",
    ),
    "facility_demand": ("owner-projects", "utility-filings", "regulatory-filings"),
    "phase": (
        "inspections",
        "active-permits",
        "contractor-updates",
        "owner-updates",
        "municipal-records",
        "bid-notices",
        "recent-reporting",
    ),
    "buyer": (
        "retained-permits",
        "permit-organizations",
        "owner-projects",
        "gc-projects",
        "electrical-contractors",
        "public-bids",
        "municipal-records",
        "public-web",
    ),
    "timing": ("contractor-schedules", "owner-updates", "inspections", "public-bids", "public-web"),
    "load": (
        "activity-electrical-permits",
        "temporary-service-permits",
        "equipment-schedules",
        "engineering-drawings",
        "service-details",
        "commissioning-test-power",
        "regulatory-filings",
    ),
    "supply": (
        "utility-filings",
        "interconnection-documents",
        "utility-planning",
        "municipal-records",
        "inspections",
        "project-announcements",
        "construction-updates",
        "public-web",
    ),
    "commissioning": (
        "electrical-testing-permits",
        "commissioning-contractors",
        "energization-records",
        "contractor-schedules",
        "owner-updates",
        "phase-milestones",
    ),
    "conflict": ("original-cited-sources", "official-corrections", "public-web"),
}
QUESTIONS = {
    "identity": "Which source identifies the end-user owner/operator of this exact project?",
    "duration": "What dated evidence establishes this activity-specific power duration?",
    "suitability": "What source establishes fuel, voltage and load-profile constraints?",
    "fuel": "What current source states whether fuel is available for this activity?",
    "voltage": "What source gives the exact activity voltage and phase requirement?",
    "load_profile": "What source states the electrical load profile for this activity?",
    "procurement": "What source reports this activity's temporary-power procurement status?",
    "utility_obstacle": "What source reports this activity's utility interconnection obstacle?",
    "power_need": (
        "Is a temporary-power requirement documented for this exact activity, "
        "separately from its supply adequacy?"
    ),
    "facility_demand": (
        "What source states exact planned electrical demand for the whole facility, "
        "separately from activity or campus capacity?"
    ),
    "phase": (
        "Is this project currently under construction, delayed, paused, completed, or cancelled?"
    ),
    "buyer": "Find a current public project contact at the electrical contractor, GC, or owner.",
    "timing": "What dated source establishes when power is needed for this exact activity?",
    "load": (
        "Find an activity-specific electrical load sufficient to evaluate "
        "the 300 kW commercial floor."
    ),
    "supply": (
        "Is permanent utility service energized and sufficient for this activity, or still pending?"
    ),
    "commissioning": (
        "What dated evidence establishes commissioning or electrical "
        "testing for this exact project activity?"
    ),
    "conflict": (
        "Which current source resolves the conflicting evidence for this exact project activity?"
    ),
}
WHY = {
    "identity": "Identify the customer without treating a contractor as the end user.",
    "duration": "Establish the bounded bridge-power window without inferring from facility life.",
    "suitability": "Confirm deployment constraints without assuming fuel or voltage compatibility.",
    "fuel": (
        "Confirm fuel availability without inferring it from generator equipment or nearby "
        "infrastructure."
    ),
    "voltage": "Confirm the activity's stated voltage and phase requirement.",
    "load_profile": (
        "Confirm the stated operating profile without inferring it from facility type."
    ),
    "procurement": (
        "Establish a reported procurement milestone without treating a permit as procurement."
    ),
    "utility_obstacle": (
        "Establish an explicit utility obstacle without inferring one from project stage."
    ),
    "power_need": "Establish whether a real unresolved commercial power requirement exists.",
    "facility_demand": (
        "Distinguish stated facility electrical demand from capacity, generator ratings, "
        "and temporary activity load."
    ),
    "phase": "Determine whether this is an active commercial window or work to watch or reject.",
    "buyer": "Establish a reachable discovery-call path without assigning purchasing authority.",
    "timing": "Determine whether the supported activity falls in a useful power window.",
    "load": "Evaluate activity-specific size; exclude campus totals and equipment nameplate.",
    "supply": "Determine whether suitable supply already removes the commercial need.",
    "commissioning": "Establish commissioning separately from construction or permitting.",
    "conflict": "Prevent commercial action based on unresolved contradictory evidence.",
}
FRESHNESS_HOURS = {
    "identity": 168,
    "duration": 168,
    "suitability": 168,
    "fuel": 168,
    "voltage": 168,
    "load_profile": 168,
    "procurement": 168,
    "utility_obstacle": 24,
    "power_need": 168,
    "facility_demand": 168,
    "phase": 24,
    "buyer": 168,
    "timing": 72,
    "load": 168,
    "supply": 24,
    "commissioning": 24,
    "conflict": 24,
}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def explicit_temporary_scope(facts: list[dict[str, Any]]) -> bool:
    """Cited affirmative activity scope, never a company's service offering."""
    for fact in facts:
        text = str(fact.get("text") or "")
        if not fact.get("evidence_id") or not re.search(
            r"\btemporary (?:power|service|generation)|\bconstruction power|\bbridge power",
            text,
            re.I,
        ):
            continue
        if re.search(
            r"\b(?:no|not|unknown|possible|potential|may|might|could|would|if|"
            r"offers?|customers?|capabilities|brochure|hypothetical|example|historical)\b|"
            r"to be (?:determined|confirmed)|under (?:review|consideration)",
            text,
            re.I,
        ):
            continue
        if re.search(r"\b(?:whether|optional|alternative|investigating|considering)\b", text, re.I):
            continue
        temporary = r"(?:temporary (?:power|service|generation)|construction power|bridge power)"
        bare_scope = temporary + (
            r"(?: for (?:this |the )?(?:construction|commissioning|electrical construction)"
            r"(?: activity)?)?[.!]?"
        )
        affirmative = (
            r"\b(?:install|installing|installation of|requires|needs)\s+(?:new )?"
            + temporary
            + r"\b|\b"
            + temporary
            + r"\s+(?:is required|is needed|is being installed)\b"
        )
        if re.fullmatch(bare_scope, text.strip(), re.I) or re.search(affirmative, text, re.I):
            return True
    return False


def blocker_resolved(category: str, card: dict, context: dict | None = None) -> bool:
    """A positive cited answer can resolve a question without qualifying the need."""
    state = card.get("research_state", {})

    def supported(field: str) -> bool:
        item = state.get(field, {})
        return item.get("status") == "SUPPORTED" and bool(item.get("claims"))

    if category == "conflict":
        fields = (context or {}).get("conflict_fields", [])
        native = (context or {}).get("native_qualification_conflict") is True
        if card.get("conflict_state") in {"CONFLICT", "conflict", "unresolved conflict"}:
            return False
        return (
            bool(fields or native)
            and all(supported(field) for field in fields)
            and (not native or card.get("qualification_conflict") is False)
        )
    if category == "identity":
        return (
            bool(card.get("owner_organizations"))
            or bool(card.get("organization"))
            and card.get("organization_role")
            in {
                "owner_developer",
                "asset_operator",
                "owner_construction",
                "owner_energy",
            }
        )
    if category == "duration":
        return bool(card.get("duration"))
    if category == "suitability":
        return all(supported(field) for field in ("fuel_availability", "voltage", "load_profile"))
    if category in {"fuel", "voltage", "load_profile", "procurement", "utility_obstacle"}:
        fields = {
            "fuel": ("fuel_availability",),
            "voltage": ("voltage",),
            "load_profile": ("load_profile",),
            "procurement": ("procurement_status",),
            "utility_obstacle": ("utility_obstacle",),
        }[category]
        return all(supported(field) for field in fields)
    if category == "facility_demand":
        return supported("facility_demand_mw")
    if category == "buyer":
        return any(
            c.get("value") and re.search(r"phone|telephone|email", str(c.get("kind", "")), re.I)
            for c in card.get("contacts", [])
        )
    if category == "load":
        return bool(card.get("required_mw")) or supported("activity_load_mw")
    if category == "timing":
        return bool(card.get("start_window")) or supported("activity_start")
    if category == "supply":
        # Energization alone does not establish sufficient supply for the activity.
        return supported("permanent_service") and supported("supply_adequacy")
    if category == "power_need":
        return explicit_temporary_scope(card.get("facts", []))
    if category in {"phase", "commissioning"}:
        if supported("phase"):
            return category == "phase" or state["phase"]["value"] == "commissioning"
        if state.get("phase", {}).get("status") == "CONFLICT":
            return False
        stage = card.get("stage", {})
        accepted = {
            "construction",
            "construction_active",
            "electrical_buildout",
            "commissioning",
            "operating",
            "completed",
            "cancelled",
            "paused",
        }
        if category == "commissioning":
            accepted = {"commissioning"}
        return stage.get("stage") in accepted and bool(stage.get("evidence_id"))
    return False


def plan_questions(
    card: dict[str, Any], *, resolved_categories: set[str] | None = None, enrich: bool = False
) -> list[dict[str, Any]]:
    """At most two independently answerable blockers; known fields are excluded."""
    if card["disposition"] not in (
        {"RESEARCH", "WATCH", "ACTION NOW"} if enrich else {"RESEARCH", "WATCH"}
    ):
        return []
    categories = []
    if card.get("conflict_state") in {"CONFLICT", "conflict", "unresolved conflict"}:
        categories.append("conflict")
    if enrich and not blocker_resolved("identity", card):
        categories.append("identity")
    if not explicit_temporary_scope(card.get("facts", [])):
        categories.append("power_need")
    stage = str((card.get("stage") or {}).get("stage") or "unknown").casefold()
    if (
        stage in {"unknown", "permitting", "project_formation", "planning", "permit_issued"}
        or "not confirmed" in stage
        or "not established" in stage
        or "permitting evidence" in stage
    ):
        categories.append("phase")
    reachable = any(
        c.get("value") and re.search(r"phone|telephone|email", str(c.get("kind") or ""), re.I)
        for c in card.get("contacts", [])
    )
    if not reachable:
        categories.append("buyer")
    if "commission" in str(card.get("activity", "")).casefold() and "commission" not in stage:
        categories.append("commissioning")
    if not card.get("start_window"):
        categories.append("timing")
    if not card.get("required_mw"):
        categories.append("load")
    if enrich and not blocker_resolved("facility_demand", card):
        categories.append("facility_demand")
    if card.get("supply") in {None, "Unknown"}:
        categories.append("supply")
    if enrich:
        for category in (
            "fuel",
            "voltage",
            "load_profile",
            "procurement",
            "utility_obstacle",
        ):
            if not blocker_resolved(category, card):
                categories.append(category)
    if enrich and not card.get("duration"):
        categories.append("duration")
    if enrich:
        priority = {
            name: rank
            for rank, name in enumerate(
                (
                    "conflict",
                    "identity",
                    "power_need",
                    "load",
                    "facility_demand",
                    "timing",
                    "buyer",
                    "supply",
                    "duration",
                    "commissioning",
                    "phase",
                    "utility_obstacle",
                    "procurement",
                    "fuel",
                    "voltage",
                    "load_profile",
                )
            )
        }
        categories.sort(key=lambda category: priority[category])
    categories = [
        category
        for category in categories
        if category not in (resolved_categories or set()) and not blocker_resolved(category, card)
    ]
    return [
        {
            "category": category,
            "native_qualification_conflict": category == "conflict"
            and card.get("qualification_conflict") is True,
            "conflict_fields": sorted(
                field
                for field, value in card.get("research_state", {}).items()
                if value.get("status") == "CONFLICT"
            )
            if category == "conflict"
            else [],
            "question": QUESTIONS[category],
            "why": WHY[category],
            "source_families": list(ROUTES[category]),
            "freshness_hours": FRESHNESS_HOURS[category],
        }
        for category in categories[:2]
    ]


def targeted_queries(context: dict[str, Any], category: str) -> list[str]:
    """Exact site/identifiers first; no unbounded broadening or model query calls."""
    site = str(context.get("site_address") or context.get("name") or "").strip()[:180]
    site = site.replace('"', "")
    if not site:
        return []
    terms = {
        "identity": [
            "project owner operator",
            "official project announcement",
            "developer project",
        ],
        "duration": ["temporary power duration", "energization schedule", "construction schedule"],
        "suitability": [
            "power fuel voltage requirements",
            "electrical specifications",
            "power procurement",
        ],
        "fuel": ["fuel availability", "fuel supply for temporary power", "site fuel connection"],
        "voltage": ["temporary power voltage phase", "electrical service voltage"],
        "load_profile": ["electrical load profile", "hourly demand profile"],
        "procurement": ["temporary power procurement", "power package bid award"],
        "utility_obstacle": ["utility interconnection delay", "service upgrade obstacle"],
        "power_need": ["temporary power", "construction power package", "temporary service"],
        "facility_demand": [
            "planned facility electrical demand MW",
            "facility load utility filing",
        ],
        "phase": ["construction update", "inspection", "project status"],
        "buyer": [
            "electrical contractor project contact",
            "general contractor",
            "project owner contact",
        ],
        "timing": ["construction schedule", "power required", "energization schedule"],
        "load": [
            "temporary service electrical permit",
            "commissioning test power",
            "electrical load",
        ],
        "supply": ["utility energized", "permanent service schedule", "interconnection delay"],
        "commissioning": ["electrical commissioning", "load bank testing", "energization schedule"],
        "conflict": ["project update", "official correction", "permit status"],
    }[category]
    family_selectors = {
        "buyer": ["permit", "contractor project contact", "owner project contact"],
        "supply": [
            "utility filing interconnection",
            "site:gov utility service",
            "energization update",
        ],
        "phase": ["site:gov inspection", "contractor construction update", "owner project update"],
        "commissioning": [
            "site:gov electrical testing permit",
            "commissioning contractor",
            "energization schedule",
        ],
        "load": [
            "site:gov temporary electrical permit",
            "equipment schedule engineering drawing",
            "commissioning test power",
        ],
    }
    terms = family_selectors.get(category, terms)
    queries = [f'"{site}" {term}' for term in terms]
    organizations = context.get("organization_names", [])
    if category == "buyer" and organizations:
        organization = str(organizations[0]).replace('"', "")[:100]
        queries[1] = f'"{site}" "{organization}" project contact'
    identifiers = context.get("stable_identifiers", [])
    if identifiers:
        queries[-1] = f'"{str(identifiers[0])[:120].replace(chr(34), "")}" {terms[0]}'
    return list(dict.fromkeys(queries))


def targeted_query_plan(context: dict[str, Any], category: str) -> list[dict[str, str]]:
    """Map actual targeted queries to preferred families; unused routes remain explicit."""
    families = {
        "buyer": ["retained-permits", "electrical-contractors", "owner-projects"],
        "supply": ["utility-filings", "municipal-records", "construction-updates"],
        "phase": ["inspections", "contractor-updates", "owner-updates"],
        "commissioning": [
            "electrical-testing-permits",
            "commissioning-contractors",
            "energization-records",
        ],
        "load": ["activity-electrical-permits", "equipment-schedules", "commissioning-test-power"],
        "facility_demand": ["owner-projects", "utility-filings", "regulatory-filings"],
        "fuel": ["fuel-supply-records", "owner-projects", "public-bids"],
        "voltage": ["electrical-permits", "engineering-drawings", "equipment-schedules"],
        "load_profile": ["engineering-drawings", "equipment-schedules", "public-bids"],
        "procurement": ["public-bids", "owner-projects", "contractor-updates"],
        "utility_obstacle": ["utility-filings", "interconnection-documents", "municipal-records"],
    }.get(category, list(ROUTES[category][:3]))
    if context.get("stable_identifiers"):
        families[-1] = families[0]
    return [
        {"query": query, "family": families[index]}
        for index, query in enumerate(targeted_queries(context, category))
    ]
