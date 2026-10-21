"""Need-level deterministic commercial triage; never qualifies or promotes a need."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

POLICY_VERSION = "commercial-triage-v2.1"
MAX_CARDS = 50


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def surfaced_on(prior: dict[str, Any], card: dict[str, Any], today: str) -> str | None:
    """Count only a newly eligible or materially changed ACTION NOW card as surfaced."""
    if card.get("disposition") == "ACTION NOW" and (
        prior.get("input_hash") != card.get("input_hash")
        or prior.get("disposition") != "ACTION NOW"
    ):
        return today
    return prior.get("surfaced_on")


def _supporting_evidence(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        evidence
        for evidence in item.get("evidence", [])
        if evidence.get("assessment_current", True)
    ]


def _phase_flags(item: dict[str, Any], evidence_texts: list[str]) -> tuple[bool, bool, bool, bool]:
    data_center = item.get("asset_type") == "data_center" or bool(
        re.search(r"data[ -]cent(?:er|re)", str(item.get("name", "")).casefold())
    )
    lifecycle_state = str(item.get("lifecycle_state") or "").casefold()
    current_events = [event for event in item.get("lifecycle_timeline", []) if event.get("current")]
    current_lifecycle = (
        lifecycle_state
        + " "
        + " ".join(
            str(event.get("event_type") or "") + " " + str(event.get("state") or "")
            for event in current_events
        ).casefold()
    )
    formation_or_backup = data_center and (
        "formation" in lifecycle_state or item.get("activity") == "backup-power"
    )
    specific_action = str(item.get("supported_action") or "").casefold()
    phase_specific = (
        data_center
        and not formation_or_backup
        and bool(
            re.search(
                r"construct|electrical|transformer|substation|switchgear|commission|expand",
                specific_action,
            )
            or re.search(r"electrical_buildout|construction|commissioning", current_lifecycle)
        )
    )
    producing = bool(
        re.search(
            r"oil|gas|well|pipeline|compressor",
            " ".join(
                [str(item.get("activity", "")), str(item.get("name", "")), *evidence_texts]
            ).casefold(),
        )
        and re.search(
            r"production|producing|completion|workover|spud|startup|operating",
            current_lifecycle,
        )
    )
    return data_center, formation_or_backup, phase_specific, producing


def _is_rental_intermediary(category: Any, organization: Any, reason: Any = "") -> bool:
    return str(category or "").casefold() == "rental_intermediary" or bool(
        re.search(
            r"\b(?:re[ -]?rent(?:er|al|ing)?|equipment rentals?|generator rentals?|"
            r"rental intermediary)\b",
            f"{organization or ''} {reason or ''}",
            re.I,
        )
    )


def _f17_stack_service_conflict(item: dict[str, Any]) -> bool:
    """Require both exact, current retained STACK sources and their native site cues."""
    location = re.sub(r"\s+", " ", str(item.get("location") or "")).casefold()
    name = str(item.get("name") or "").casefold()
    if "1200 memorex drive" not in location or "santa clara" not in location:
        return False
    if "svy02a" not in name or "memorex junction" not in name:
        return False

    from gridlens.ingestion.adapters.retained_document import SOURCES

    by_id = {
        str(e.get("source_id") or ""): e
        for e in item.get("evidence", [])
        if e.get("assessment_current") is True
    }
    city = by_id.get("f17-stack-city-claim")
    cec = by_id.get("f17-stack-cec-filing")
    for source_id, evidence in (
        ("f17-stack-city-claim", city),
        ("f17-stack-cec-filing", cec),
    ):
        policy = SOURCES[source_id]
        if (
            evidence is None
            or evidence.get("url") != policy["url"]
            or evidence.get("content_hash") != policy["sha256"]
            or not evidence.get("id")
        ):
            return False
        text = re.sub(r"\s+", " ", str(evidence.get("abstract") or "")).casefold()
        text = re.sub(r"(\d)\s*m\s*v\s*a\b", r"\1 mva", text)
        if "1200 memorex drive" not in text or "santa clara" not in text:
            return False
        if source_id.endswith("city-claim"):
            if not all(term in text for term in ("18 mva", "2028", "28 mva", "31 mva")):
                return False
        elif not all(term in text for term in ("draft", "table e1", "mva", "28", "31")):
            return False
    return True


class PriorityInputAccumulator:
    """Compact the exact text predicates used by canonical browse priority."""

    def __init__(self, lifecycle_state: str | None = None) -> None:
        self.lifecycle_state = str(lifecycle_state or "").casefold()
        self.latest_date = "0000-00-00"
        self.evidence_scope = False
        self.evidence_commissioning = False
        self.evidence_construction = False
        self.evidence_oil_gas = False
        self.lifecycle_phase = bool(
            re.search(r"electrical_buildout|construction|commissioning", self.lifecycle_state)
        )
        self.lifecycle_producing = bool(
            re.search(
                r"production|producing|completion|workover|spud|startup|operating",
                self.lifecycle_state,
            )
        )

    def add_evidence(
        self,
        *,
        title: Any = "",
        abstract: Any = "",
        published_at: Any = None,
        event_date: Any = None,
        supporting: bool = True,
    ) -> None:
        retained_date = published_at or event_date
        if retained_date is not None:
            value = (
                retained_date.isoformat()
                if hasattr(retained_date, "isoformat")
                else str(retained_date)
            )
            if re.match(r"^\d{4}-\d{2}-\d{2}", value):
                self.latest_date = max(self.latest_date, value[:10])
        if not supporting:
            return
        text = f"{title} {abstract}".casefold()
        scope_pattern = (
            r"temporary (?:service|power)|construction power|bridge power|load bank|"
            r"commissioning.{0,40}(?:power|generator|load bank)"
        )
        self.evidence_scope = self.evidence_scope or bool(re.search(scope_pattern, text))
        self.evidence_commissioning = self.evidence_commissioning or bool(
            re.search(r"commission|load bank", text)
        )
        self.evidence_construction = self.evidence_construction or bool(
            re.search(r"construct|building permit|substation|transformer", text)
        )
        self.evidence_oil_gas = self.evidence_oil_gas or bool(
            re.search(r"oil|gas|well|pipeline|compressor", text)
        )

    def add_lifecycle(self, event_type: Any, state: Any) -> None:
        text = f"{event_type or ''} {state or ''}".casefold()
        self.lifecycle_phase = self.lifecycle_phase or bool(
            re.search(r"electrical_buildout|construction|commissioning", text)
        )
        self.lifecycle_producing = self.lifecycle_producing or bool(
            re.search(r"production|producing|completion|workover|spud|startup|operating", text)
        )

    def merge_supporting_evidence(self, other: PriorityInputAccumulator) -> None:
        self.evidence_scope = self.evidence_scope or other.evidence_scope
        self.evidence_commissioning = self.evidence_commissioning or other.evidence_commissioning
        self.evidence_construction = self.evidence_construction or other.evidence_construction
        self.evidence_oil_gas = self.evidence_oil_gas or other.evidence_oil_gas
        self.latest_date = max(self.latest_date, other.latest_date)

    def snapshot(self) -> dict[str, Any]:
        return {
            "latest_date": self.latest_date,
            "lifecycle_state": self.lifecycle_state,
            "evidence_scope": self.evidence_scope,
            "evidence_commissioning": self.evidence_commissioning,
            "evidence_construction": self.evidence_construction,
            "evidence_oil_gas": self.evidence_oil_gas,
            "lifecycle_phase": self.lifecycle_phase,
            "lifecycle_producing": self.lifecycle_producing,
        }


def _priority(item: dict[str, Any]) -> tuple[int, int, int, str, str]:
    features = item.get("_priority_features")
    if not isinstance(features, dict):
        accumulator = PriorityInputAccumulator(item.get("lifecycle_state"))
        for evidence in item.get("evidence", []):
            accumulator.add_evidence(
                title=evidence.get("title", ""),
                abstract=evidence.get("abstract", ""),
                published_at=evidence.get("published_at"),
                event_date=evidence.get("event_date"),
                supporting=evidence.get("assessment_current", True),
            )
        for event in item.get("lifecycle_timeline", []):
            if event.get("current"):
                accumulator.add_lifecycle(event.get("event_type"), event.get("state"))
        features = accumulator.snapshot()

    lifecycle_state = str(features.get("lifecycle_state") or "").casefold()
    data_center = item.get("asset_type") == "data_center" or bool(
        re.search(r"data[ -]cent(?:er|re)", str(item.get("name", "")).casefold())
    )
    project_formation_or_backup = data_center and (
        "formation" in lifecycle_state or item.get("activity") == "backup-power"
    )
    specific_action = str(item.get("supported_action") or "").casefold()
    dc_project_phase = (
        data_center
        and not project_formation_or_backup
        and bool(
            re.search(
                r"construct|electrical|transformer|substation|switchgear|commission|expand",
                specific_action,
            )
            or features.get("lifecycle_phase")
        )
    )
    producing_asset = bool(
        re.search(
            r"oil|gas|well|pipeline|compressor",
            " ".join(
                [
                    str(item.get("activity", "")),
                    str(item.get("name", "")),
                    str(item.get("supported_action") or ""),
                ]
            ).casefold(),
        )
        or features.get("evidence_oil_gas")
    ) and bool(features.get("lifecycle_producing"))
    scope_pattern = (
        r"temporary (?:service|power)|construction power|bridge power|load bank|"
        r"commissioning.{0,40}(?:power|generator|load bank)"
    )
    explicit_scope = bool(
        re.search(scope_pattern, str(item.get("supported_action") or "").casefold())
        if data_center
        else features.get("evidence_scope")
    )
    commissioning = bool(features.get("evidence_commissioning"))
    construction = bool(features.get("evidence_construction"))
    if dc_project_phase and commissioning:
        segment = 1
    elif dc_project_phase:
        segment = 0
    elif producing_asset:
        segment = 2
    elif explicit_scope:
        segment = 3
    elif data_center and not project_formation_or_backup and commissioning:
        segment = 4
    elif data_center and not project_formation_or_backup and construction:
        segment = 5
    elif data_center:
        segment = 6
    elif re.search(
        r"oil|gas|drill|well|pipeline|compressor",
        " ".join(
            [
                str(item.get("activity", "")),
                str(item.get("name", "")),
                str(item.get("supported_action") or ""),
            ]
        ).casefold(),
    ) or features.get("evidence_oil_gas"):
        segment = 7
    else:
        segment = 8
    location = str(item.get("location") or "").casefold()
    geography = (
        0
        if re.search(r"dallas|fort worth|dfw", location)
        else 1
        if "austin" in location
        else 2
        if "houston" in location
        else 3
        if "el paso" in location
        else 4
        if re.search(r"california|\bca\b", location)
        else 5
    )
    latest = str(features.get("latest_date") or "0000-00-00")
    return segment, geography, -int(latest.replace("-", "")), item["project_id"].hex, item["id"].hex


def _current_stage(item: dict[str, Any]) -> dict[str, Any]:
    phase = item.get("research_state", {}).get("phase", {})
    if phase.get("status") == "CONFLICT":
        return {
            "stage": "conflicting phase evidence",
            "date": None,
            "source_url": None,
            "evidence_id": None,
        }
    if phase.get("status") == "SUPPORTED" and phase.get("claims"):
        claim = phase["claims"][0]
        return {
            "stage": phase["value"],
            "date": claim["as_of"],
            "source_url": claim.get("evidence", {}).get("url"),
            "evidence_id": claim["evidence_id"],
        }
    active = [event for event in item.get("lifecycle_timeline", []) if event.get("current")]
    latest = max(active, key=lambda event: event.get("date") or "", default=None)
    if latest:
        event_type = str(latest.get("event_type") or "").casefold()
        if "permit" in event_type or "application" in event_type:
            stage = "permitting evidence"
        elif "commission" in event_type:
            stage = "commissioning-related source evidence; actual activity not confirmed"
        elif "construction" in event_type or "electrical" in event_type:
            stage = "construction-related source evidence; work underway not confirmed"
        else:
            stage = str(latest.get("state") or event_type or "Project milestone")
        matching: dict[str, Any] = next(
            (e for e in item.get("evidence", []) if e.get("url") == latest.get("evidence_url")), {}
        )
        return {
            "stage": stage,
            "date": _iso(latest.get("date")),
            "source_url": latest.get("evidence_url"),
            "evidence_id": str(matching["id"]) if matching.get("id") else None,
        }
    permit = next(
        (
            e
            for e in item.get("evidence", [])
            if "permit" in (str(e.get("source_id", "")) + " " + str(e.get("title", ""))).casefold()
        ),
        None,
    )
    if permit:
        return {
            "stage": "permitting evidence; construction not established",
            "date": _iso(permit.get("event_date")),
            "source_url": permit.get("url"),
            "evidence_id": str(permit.get("id")),
        }
    return {"stage": "unknown", "date": None, "source_url": None, "evidence_id": None}


def build_card(item: dict[str, Any], chain: dict[str, Any] | None, today: date) -> dict[str, Any]:
    chain = chain or {"candidates": [], "permit_summaries": []}
    evidence = _supporting_evidence(item)
    evidence_texts = [
        (str(e.get("title") or "") + " " + str(e.get("abstract") or "")).casefold()
        for e in evidence
    ]
    data_center, project_formation_or_backup, phase_specific_scope, producing_asset = _phase_flags(
        item, evidence_texts
    )
    facts = [
        {
            "text": e.get("title"),
            "evidence_id": str(e.get("id")),
            "url": e.get("url"),
            "hash": e.get("content_hash"),
            "date": _iso(e.get("event_date") or e.get("published_at")),
        }
        for e in evidence
    ]
    research_state = item.get("research_state", {})
    research_conflict = any(field.get("status") == "CONFLICT" for field in research_state.values())
    for field in research_state.values():
        for claim in field.get("claims", []):
            facts.append(
                {
                    "text": claim["quote"],
                    "evidence_id": claim["evidence_id"],
                    "url": claim.get("evidence", {}).get("url"),
                    "hash": claim["evidence_hash"],
                    "date": claim["as_of"],
                }
            )
    action = item.get("supported_action")
    action_source = next(
        (
            e
            for e in evidence
            if action and action.casefold() in str(e.get("abstract") or "").casefold()
        ),
        None,
    )
    if action_source:
        facts.insert(
            0,
            {
                "text": action,
                "evidence_id": str(action_source.get("id")),
                "url": action_source.get("url"),
                "hash": action_source.get("content_hash"),
                "date": _iso(action_source.get("event_date") or action_source.get("published_at")),
            },
        )
    relationships = [c for c in chain.get("candidates", []) if not c.get("stale")]
    direct = [c for c in relationships if c.get("organization_relationship") == "DIRECT"]
    direct_owners = [
        c
        for c in direct
        if not _is_rental_intermediary(c.get("category"), c.get("organization"), c.get("reason"))
    ]
    contacts = [
        {
            "organization": c.get("organization"),
            "person": c.get("person_name"),
            "role": c.get("title") or c.get("category"),
            "kind": contact.get("kind"),
            "value": contact.get("value"),
            "source_url": contact.get("source_url"),
            "evidence_ids": [str(e.get("id")) for e in c.get("evidence", [])],
        }
        for c in direct_owners
        for contact in c.get("public_contacts", [])
    ]
    summary_intermediary = False
    for summary in chain.get("permit_summaries", []):
        summary_facts = summary.get("facts", [])
        listed_org = next(
            (
                fact
                for fact in summary_facts
                if re.search(
                    r"owner company|owner organization|operator company|"
                    r"owner / occupant company|company name|contractor organization",
                    fact.get("label", ""),
                    re.I,
                )
            ),
            None,
        )
        listed_person = next(
            (
                fact
                for fact in summary_facts
                if re.search(
                    r"contractor name|applicant name|contact name", fact.get("label", ""), re.I
                )
            ),
            None,
        )
        listed_trade = next(
            (
                fact
                for fact in summary_facts
                if re.search(r"contractor trade|trade as listed", fact.get("label", ""), re.I)
            ),
            None,
        )
        listed_contact = next(
            (
                fact
                for fact in summary_facts
                if re.search(r"contractor.*(?:phone|telephone|email)", fact.get("label", ""), re.I)
                and fact.get("value")
            ),
            None,
        )
        listed_summary_intermediary = listed_org and _is_rental_intermediary(
            None, listed_org.get("value")
        )
        summary_intermediary = summary_intermediary or bool(listed_summary_intermediary)
        if listed_summary_intermediary:
            continue
        if listed_contact or listed_trade or listed_person:
            listed_value = (
                listed_contact.get("value")
                if listed_contact
                else listed_org.get("value")
                if listed_org
                else listed_person.get("value")
                if listed_person
                else listed_trade.get("value")
                if listed_trade
                else None
            )
            contacts.append(
                {
                    "organization": listed_org.get("value") if listed_org else None,
                    "person": listed_person.get("value") if listed_person else None,
                    "role": (listed_trade.get("value") + " (trade as listed; authority unverified)")
                    if listed_trade
                    else (
                        listed_person.get("label")
                        if listed_person
                        else (listed_org.get("label") if listed_org else "Permit-listed contact")
                    )
                    + " (authority unverified)",
                    "kind": listed_contact.get("label") if listed_contact else "role only",
                    "value": listed_value,
                    "source_url": summary.get("url"),
                    "evidence_ids": [str(summary.get("evidence_id"))],
                }
            )
    intermediary_only = not direct_owners and (
        summary_intermediary
        or any(
            _is_rental_intermediary(
                candidate.get("category"), candidate.get("organization"), candidate.get("reason")
            )
            for candidate in relationships
        )
    )
    stage = _current_stage(item)
    if stage["stage"] in {
        "construction_active",
        "electrical_buildout",
        "commissioning",
        "drilling_completed",
        "production_infrastructure_under_construction",
        "production_started",
    }:
        # Actual dated activity changes the commercial window; it does not prove demand.
        project_formation_or_backup = False
    unknowns = list(dict.fromkeys(item.get("missing_facts", [])))
    if not item.get("required_mw"):
        unknowns.append("Need-specific MW remains unknown.")
    if item.get("supply") in {None, "Unknown"}:
        unknowns.append("Need-specific suitable supply and any shortfall remain unknown.")
    blockers = [
        q
        for q in unknowns
        if re.search(
            r"buyer|organization|contact|power requirement|supply|start|duration|commission",
            q,
            re.I,
        )
    ][:2]
    credible_scope = any(
        re.search(
            r"temporary service|temporary power|construction power|bridge power|"
            r"commissioning.{0,40}(?:power|generator|load bank)|generator rental|rental generator",
            str(e.get("abstract") or "") + " " + str(e.get("title") or ""),
            re.I,
        )
        for e in evidence
    )
    if data_center:
        credible_scope = phase_specific_scope or bool(
            re.search(
                r"temporary (?:service|power)|construction power|bridge power|"
                r"generator rental|rental generator",
                str(item.get("supported_action") or ""),
                re.I,
            )
        )
    credible_scope = credible_scope or phase_specific_scope or producing_asset
    current_text = "\n".join(
        str(e.get("title") or "") + " " + str(e.get("abstract") or "") for e in evidence
    ).casefold()
    permit_statuses = (
        " ".join(
            str(fact.get("value") or "")
            for summary in chain.get("permit_summaries", [])
            for fact in summary.get("facts", [])
            if re.search(r"status|disposition", str(fact.get("label") or ""), re.I)
        )
        + " "
        + " ".join(str(e.get("permit_status") or "") for e in evidence)
    )
    permit_statuses = permit_statuses.casefold()
    negative_evidence = current_text + " " + permit_statuses
    temporary_scope = r"(?:temporary (?:power|service)|construction power|bridge power)"
    no_need_pattern = (
        rf"\bno (?:separate )?{temporary_scope}(?: is| will be)? "
        r"(?:required|needed|necessary)\b|"
        rf"\b{temporary_scope}(?: is| will be)? not (?:required|needed|necessary)\b|"
        rf"\bdoes not (?:require|need) {temporary_scope}\b"
    )
    no_temporary_need = bool(re.search(no_need_pattern, negative_evidence))
    # Remove the complete negative claim before checking affirmative scope.
    scope_text = re.sub(no_need_pattern, "", negative_evidence)
    scope_text = re.sub(r"\bno (?:separate )?temporary (?:power|service)\b", "", scope_text)
    explicit_temporary = bool(
        re.search(
            r"temporary (?:power|service)|construction power|bridge power|"
            r"generator rental|rental generator|commissioning.{0,40}(?:power|generator|load bank)",
            scope_text,
        )
    )
    negative_reason = None
    if re.search(
        r"\b(?:withdrawn|cancelled|canceled|closed|completed|finaled|denied|void)\b",
        permit_statuses,
    ):
        negative_reason = (
            "Current permit status says the work is closed, withdrawn, denied, or complete."
        )
    elif no_temporary_need and not explicit_temporary:
        negative_reason = (
            "Current source explicitly states temporary power is not required for this activity."
        )
    elif not explicit_temporary and re.search(
        r"\b(?:backup|standby) generator replacement\b|"
        r"\b(?:routine|like.for.like) (?:generator )?replacement\b|"
        r"\bmaintenance.only (?:generator )?replacement\b",
        negative_evidence,
    ):
        negative_reason = (
            "Current source describes routine or backup-only generator replacement; "
            "no separate temporary-power scope is evidenced."
        )
    elif not explicit_temporary and re.search(
        r"\b(?:permanent utility supply|permanent power supply|utility service)\b"
        r".{0,60}\b(?:adequate|sufficient|fully serves|meets (?:the )?load)\b|"
        r"\b(?:adequate|sufficient)\b.{0,60}"
        r"\b(?:permanent utility supply|permanent power supply|utility service)\b",
        negative_evidence,
    ):
        negative_reason = (
            "Current source states permanent utility supply is adequate; "
            "no separate temporary-power need is evidenced."
        )
    reachable_contacts = [
        contact
        for contact in contacts
        if contact.get("value")
        and re.search(r"phone|telephone|email", str(contact.get("kind") or ""), re.I)
    ]
    if item.get("canonical_inactive"):
        disposition, reason = (
            "REJECT",
            "The canonical power need is inactive; no active supported scope remains.",
        )
    elif research_conflict:
        disposition, reason = (
            "RESEARCH",
            "Resolve the cited conflicting current project/activity reports "
            "before commercial action.",
        )
    elif stage["stage"] in {"completed", "cancelled"}:
        disposition, reason = (
            "REJECT",
            "Current dated project evidence reports the project completed or cancelled.",
        )
    elif (
        research_state.get("supply_adequacy", {}).get("status") == "SUPPORTED"
        and research_state["supply_adequacy"]["value"] == "adequate"
    ):
        disposition, reason = (
            "REJECT",
            "Current exact-activity evidence reports sufficient suitable supply; "
            "no remaining gap is supported.",
        )
    elif stage["stage"] == "paused":
        disposition, reason = (
            "WATCH",
            "Current dated project evidence reports work paused; wait for a supported restart.",
        )
    elif item.get("commercial_size_status") == "below_floor":
        disposition, reason = (
            "REJECT",
            "Current activity-specific evidence places this need below 300 kW.",
        )
    elif negative_reason:
        disposition, reason = "REJECT", negative_reason
    elif item.get("signal_display_decision") == "HOLD":
        disposition, reason = (
            "RESEARCH",
            item.get("signal_display_reason")
            or "Resolve the retained hold reason before commercial action.",
        )
    elif item.get("conflict_state") and str(item.get("conflict_state")).casefold() in {
        "conflict",
        "unresolved conflict",
    }:
        disposition, reason = (
            "RESEARCH",
            "Resolve the cited evidence conflict before selecting a commercial action.",
        )
    elif intermediary_only:
        disposition, reason = (
            "REJECT",
            "Retained project relationships identify a source-supported rental intermediary; "
            "no direct owner or operator is established.",
        )
    elif no_temporary_need and explicit_temporary:
        disposition, reason = (
            "RESEARCH",
            "Resolve the cited affirmative and negative temporary-power scope "
            "before commercial action.",
        )
    elif reachable_contacts and credible_scope:
        disposition, reason = (
            "ACTION NOW",
            "A source-cited project contact path and specific power activity support a "
            "discovery call; confirm need size and purchasing authority on the call.",
        )
    elif project_formation_or_backup:
        disposition, reason = (
            "WATCH",
            "Current data-center evidence is formation or standby-generation scope; "
            "wait for a dated construction-mobilization or electrical-package award.",
        )
    elif blockers and len(blockers) <= 2:
        disposition, reason = (
            (
                "RESEARCH",
                "A bounded evidence question can address the highest-priority "
                "missing commercial fact.",
            )
            if credible_scope or item.get("asset_type") == "data_center"
            else (
                "WATCH",
                "Retain this source-backed project for a dated lifecycle event "
                "before spending research effort.",
            )
        )
    else:
        disposition, reason = (
            "WATCH",
            "Wait for the cited next project milestone; current evidence does not "
            "support a stronger commercial action.",
        )
    retained_stack_conflict = disposition == "WATCH" and _f17_stack_service_conflict(item)
    if retained_stack_conflict:
        reason = (
            "STACK's June 24, 2024 city claim reports an earlier 28 MVA (2026) / "
            "31 MVA (2027) schedule, and says SVP told STACK on March 14, 2024 "
            "that service would be capped at 18 MVA or less until at least 2028 "
            "at this Memorex site. The September 2021 draft Substation Agreement "
            "is attached to STACK's February 2025 CEC filing. These are attributed "
            "claims, not an adjudicated current-service determination; actual "
            "temporary-power need remains UNKNOWN."
        )
    if item.get("asset_type") == "data_center" and phase_specific_scope:
        question = (
            "Who is supplying temporary construction or commissioning power, and "
            "what dated source states when permanent utility energization is expected?"
        )
    elif producing_asset:
        question = (
            "Which organization owns power for this production or fixed-asset activity, "
            "and what dated source states startup timing and utility or gas availability?"
        )
    elif disposition == "ACTION NOW":
        question = (
            "Which project contact can identify who supplies temporary power, "
            "and what dated source states when permanent utility energization is expected?"
        )
    elif not blockers or re.search(r"buyer|organization|contact", blockers[0], re.I):
        question = (
            "Which organization owns the next project decision, and what dated "
            "evidence supports that role?"
        )
    elif re.search(r"power requirement", blockers[0], re.I):
        question = (
            "What is the need-specific MW range for this project activity, separate "
            "from campus or equipment capacity?"
        )
    elif re.search(r"supply", blockers[0], re.I):
        question = (
            "What suitable utility supply is committed to this specific activity, "
            "and what evidence identifies any shortfall?"
        )
    elif re.search(r"start|commission", blockers[0], re.I):
        question = "What dated evidence establishes when this specific project activity will start?"
    else:
        question = "What source establishes the expected duration of this specific activity?"
    if disposition == "RESEARCH":
        next_action = f"Research this exact question: {question}"
    elif disposition == "ACTION NOW":
        next_action = (
            "Call the cited public project contact to confirm stage, need-specific MW, "
            "timing, duration, and purchasing role."
        )
    elif retained_stack_conflict:
        next_action = (
            "Verify the current utility delivery schedule and any temporary-power "
            "scope with the utility; use the dated STACK city claim and attached "
            "draft Substation Agreement as the source history."
        )
    else:
        next_action = reason
    watch = None
    if disposition == "WATCH":
        deadline = next(
            (
                fact
                for summary in chain.get("permit_summaries", [])
                for fact in summary.get("facts", [])
                if "deadline" in fact.get("label", "").casefold() and fact.get("value")
            ),
            None,
        )
        future_deadline = None
        if deadline:
            try:
                deadline_date = date.fromisoformat(str(deadline["value"])[:10])
                if deadline_date > today:
                    future_deadline = deadline
            except ValueError:
                pass
        if future_deadline:
            watch = {
                "event": "Public comment deadline",
                "date": _iso(future_deadline["value"]),
                "source_url": next(
                    (
                        summary["url"]
                        for summary in chain.get("permit_summaries", [])
                        if future_deadline in summary.get("facts", [])
                    ),
                    None,
                ),
            }
        else:
            expected = item.get("expected_next_milestone")
            if expected:
                trigger = f"Observe evidence for the expected next milestone: {expected}"
            elif item.get("asset_type") == "data_center":
                state = str(item.get("lifecycle_state") or "").casefold()
                trigger = (
                    "Observe a dated load-bank test, generator startup, or "
                    "utility-energization record"
                    if "electrical" in state or "commission" in state
                    else "Observe a dated construction-mobilization or "
                    "electrical-package award record"
                )
            elif item.get("asset_type") == "upstream_well":
                trigger = (
                    "Observe the next named-well spud record; drilling-permit issuance "
                    "alone does not establish a start"
                )
            else:
                trigger = (
                    "Observe a dated EPC award, construction-mobilization, or "
                    "commissioning-start record for this asset"
                )
            title = facts[0]["text"] if facts else "Current retained project evidence"
            watch = {
                "event": f"{trigger}; current cited evidence: {title}",
                "date": None,
                "source_url": facts[0]["url"] if facts else None,
            }
    sources = facts + [
        {
            "text": e.get("quote"),
            "evidence_id": str(e.get("id")),
            "url": e.get("url"),
            "hash": e.get("content_hash"),
            "date": _iso(e.get("published_at")),
        }
        for c in relationships
        for e in c.get("evidence", [])
    ]
    if phase_specific_scope:
        hypothesis = (
            "Hypothesis: this data-center construction or commissioning phase may need "
            "temporary service or staged load before permanent utility energization. "
            "Timing, supply gap, and rental demand remain UNKNOWN."
        )
    elif producing_asset:
        hypothesis = (
            "Hypothesis: this supported production or fixed-asset stage may precede "
            "utility buildout. Gas fuel, utility scope, and temporary-power need remain UNKNOWN."
        )
    elif explicit_temporary:
        hypothesis = (
            "Hypothesis: the cited temporary service may need supplemental generation only "
            "if that service is insufficient. Service adequacy and rental demand remain UNKNOWN."
        )
    elif project_formation_or_backup:
        hypothesis = (
            "Hypothesis: a later construction or commissioning phase may involve temporary "
            "service. Actual construction stage, need-specific MW, and rental demand "
            "remain UNKNOWN."
        )
    else:
        hypothesis = (
            f"Hypothesis: retained evidence describes "
            f"{item.get('activity') or 'project activity'}; "
            "no temporary-power need or utility shortfall is established. MW remains UNKNOWN."
        )
    card = {
        "id": str(item["id"]),
        "project_id": str(item["project_id"]),
        "related_project_ids": [str(item["project_id"])],
        "name": item.get("name"),
        "location": item.get("location"),
        "tier": item.get("tier"),
        "activity": item.get("activity"),
        "industry": item.get("asset_type") or "unknown",
        "disposition": disposition,
        "reason": reason,
        "required_mw": item.get("required_mw"),
        "start_window": item.get("start_window"),
        "duration": item.get("duration"),
        "supply": item.get("supply") or "Unknown",
        "stage": stage,
        "lifecycle_timeline": item.get("lifecycle_timeline", []),
        "organization": direct_owners[0].get("organization")
        if direct_owners
        else item.get("title_company"),
        "owner_organizations": sorted(
            {
                c["organization"]
                for c in direct_owners
                if c.get("organization")
                and c.get("category")
                in {"owner_developer", "asset_operator", "owner_construction", "owner_energy"}
            }
        ),
        "organization_role": direct_owners[0].get("category")
        if direct_owners
        else item.get("title_company_role"),
        "contacts": contacts,
        "facts": facts,
        "hypothesis": hypothesis,
        "unknowns": list(dict.fromkeys(unknowns)),
        "blockers": blockers,
        "next_question": question,
        "next_action": next_action,
        "watch": watch,
        "sources": sources,
        "conflict_state": "CONFLICT" if research_conflict else item.get("conflict_state"),
        "qualification_conflict": item.get("qualification_conflict"),
        "research_state": research_state,
    }
    operator_fact_refs = item.get("operator_fact_refs")
    if operator_fact_refs:
        card["operator_fact_refs"] = sorted(
            {
                (
                    str(reference["need_id"]),
                    str(reference["fact_version_id"]),
                    str(reference["content_hash"]),
                ): {
                    key: value
                    for key, value in reference.items()
                    if key in {"need_id", "fact_version_id", "content_hash", "authority"}
                }
                for reference in operator_fact_refs
            }.values(),
            key=lambda reference: (
                str(reference["need_id"]),
                str(reference["fact_version_id"]),
                str(reference["content_hash"]),
            ),
        )
    # Schedules enrich the intelligence card, but they do not change the saved
    # commercial research question. Filter from the typed projection before its
    # compatibility shape has discarded fact_type.
    semantic_input = dict(card)
    typed_refs = [
        reference
        for reference in (operator_fact_refs or [])
        if reference.get("fact_type") != "power_schedule"
    ]
    if operator_fact_refs:
        if typed_refs:
            semantic_input["operator_fact_refs"] = [
                {
                    key: reference[key]
                    for key in ("need_id", "fact_version_id", "content_hash", "authority")
                    if key in reference
                }
                for reference in typed_refs
            ]
        else:
            semantic_input.pop("operator_fact_refs", None)
    card["input_hash"] = hashlib.sha256(
        json.dumps(
            [POLICY_VERSION, _semantic_card(semantic_input)], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    return card


def _semantic_card(card: dict) -> dict:
    """Keep additive display provenance out of the established research fingerprint.

    Owner and fact changes are already represented in canonical chain/source hashes.
    Rolling out card presentation must not restart unchanged paid research.
    """
    result = {
        k: v
        for k, v in card.items()
        if k not in {"input_hash", "owner_organizations", "intelligence_card"}
    }
    if result.get("operator_fact_refs"):
        result["operator_fact_refs"] = [
            {
                k: v
                for k, v in reference.items()
                if k in {"need_id", "fact_version_id", "content_hash", "authority"}
            }
            for reference in result["operator_fact_refs"]
        ]
    return result


def cards(
    items: list[dict[str, Any]],
    chains: dict[str, dict[str, Any]],
    today: date,
    limit: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    return group_cards(items, chains, today, limit=max(1, min(limit, MAX_CARDS)))


def grouped_need_ids(items: list[dict[str, Any]], limit: int | None = None) -> list[list[str]]:
    """Return canonical work groups in first priority encounter order."""
    groups = grouped_need_groups(items)
    return (
        [need_ids for _identity, need_ids in groups[:limit]]
        if limit is not None
        else [need_ids for _identity, need_ids in groups]
    )


def work_group_identity(item: dict[str, Any]) -> str:
    """Canonical commercial identity from the first current supporting evidence."""
    from gridlens.domain.pursuit_screening import work_identity

    supporting = _supporting_evidence(item)
    first = supporting[0] if supporting else {}
    return work_identity(
        str(first.get("source_id") or ""),
        str(first.get("document_number") or first.get("id") or ""),
        str(item.get("location") or ""),
    )


def grouped_need_groups(items: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """Return canonical work identities and members in canonical priority order."""
    prepared = sorted(items, key=lambda item: (_priority(item), str(item["id"])))
    grouped: dict[str, list[str]] = {}
    for item in prepared:
        identity = work_group_identity(item)
        grouped.setdefault(identity, []).append(str(item["id"]))
    return [(identity, sorted(need_ids)) for identity, need_ids in grouped.items()]


def group_cards(
    items: list[dict[str, Any]],
    chains: dict[str, dict[str, Any]],
    today: date,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Build canonical work-identity groups without applying the UI shortlist cap."""
    by_id = {str(item["id"]): item for item in items}

    def state_for(card: dict[str, Any]) -> dict[str, Any]:
        item = by_id[card["id"]]
        raw_conflict = str(item.get("conflict_state") or "")
        conflict_state = raw_conflict if "conflict" in raw_conflict.casefold() else None
        return {
            "need_id": card["id"],
            "project_id": card["project_id"],
            "disposition": card["disposition"],
            "reason": card["reason"],
            "held": item.get("signal_display_decision") == "HOLD",
            "conflict_state": conflict_state,
            "closed": card["disposition"] == "REJECT"
            and "permit status says" in card["reason"].casefold(),
        }

    unique: list[dict[str, Any]] = []
    for need_ids in grouped_need_ids(items, limit):
        group = [
            build_card(by_id[need_id], chains.get(str(by_id[need_id]["project_id"])), today)
            for need_id in need_ids
        ]
        merged = group[0]
        states = [state_for(card) for card in group]
        merged["related_need_ids"] = sorted({state["need_id"] for state in states})
        merged["related_project_ids"] = sorted({state["project_id"] for state in states})
        merged["related_need_states"] = states
        if len(group) > 1:
            merged["contacts"] = sorted(
                {
                    json.dumps(contact, sort_keys=True): contact
                    for card in group
                    for contact in card["contacts"]
                }.values(),
                key=lambda value: json.dumps(value, sort_keys=True),
            )
            merged["lifecycle_timeline"] = sorted(
                {
                    json.dumps(event, sort_keys=True, default=str): event
                    for card in group
                    for event in card["lifecycle_timeline"]
                }.values(),
                key=lambda value: json.dumps(value, sort_keys=True, default=str),
            )
            merged["facts"] = sorted(
                {fact["evidence_id"]: fact for card in group for fact in card["facts"]}.values(),
                key=lambda value: value["evidence_id"],
            )
            merged["sources"] = sorted(
                {
                    source["evidence_id"]: source for card in group for source in card["sources"]
                }.values(),
                key=lambda value: value["evidence_id"],
            )
            operator_fact_refs = [
                reference for card in group for reference in card.get("operator_fact_refs", [])
            ]
            if operator_fact_refs:
                merged["operator_fact_refs"] = sorted(
                    {
                        (
                            str(reference["need_id"]),
                            str(reference["fact_version_id"]),
                            str(reference["content_hash"]),
                        ): reference
                        for reference in operator_fact_refs
                    }.values(),
                    key=lambda reference: (
                        str(reference["need_id"]),
                        str(reference["fact_version_id"]),
                        str(reference["content_hash"]),
                    ),
                )

            state_signatures = {
                (
                    state["disposition"],
                    state["held"],
                    str(state["conflict_state"] or "").casefold(),
                    state["closed"],
                )
                for state in states
            }
            dispositions = {state["disposition"] for state in states}
            if len(state_signatures) > 1:
                state_summary = "; ".join(
                    f"{state['need_id']}: {state['disposition']}"
                    + (" (held)" if state["held"] else "")
                    + (f" (conflict: {state['conflict_state']})" if state["conflict_state"] else "")
                    + (" (closed/withdrawn)" if state["closed"] else "")
                    for state in sorted(states, key=lambda value: value["need_id"])
                )
                merged["reason"] = (
                    "Related need records for this exact work scope have different states: "
                    f"{state_summary}. Reconcile the cited sources before acting."
                )
                merged["unknowns"] = sorted(
                    set(merged["unknowns"])
                    | {"Current status is contradictory across related needs; reconcile sources."}
                )
                if len(dispositions) > 1:
                    merged["disposition"] = "RESEARCH"
                    merged["blockers"] = list(
                        dict.fromkeys(
                            merged["blockers"]
                            + ["Resolve conflicting same-work need states before action."]
                        )
                    )[:2]
                    merged["next_question"] = (
                        "Which cited source confirms whether this exact work scope is open, "
                        "and what stage does that source establish?"
                    )
                    merged["next_action"] = (
                        "Reconcile contradictory same-work need states and source status before "
                        "any commercial action."
                    )
                    merged["conflict_state"] = "contradictory same-work need states"
        merged["input_hash"] = hashlib.sha256(
            json.dumps(
                [
                    POLICY_VERSION,
                    _semantic_card(merged),
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        unique.append(merged)
    return unique
