"""Need-level deterministic commercial triage; never qualifies or promotes a need."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

POLICY_VERSION = "commercial-triage-v1"
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


def _priority(item: dict[str, Any]) -> tuple[int, int, int, str, str]:
    evidence_texts = [
        (str(e.get("title", "")) + " " + str(e.get("abstract", ""))).casefold()
        for e in _supporting_evidence(item)
    ]
    text = " ".join(
        [
            str(item.get("activity", "")),
            str(item.get("name", "")),
            str(item.get("supported_action", "")),
            *evidence_texts,
        ]
    ).casefold()
    data_center, project_formation_or_backup, dc_project_phase, producing_asset = _phase_flags(
        item, evidence_texts
    )
    scope_pattern = (
        r"temporary (?:service|power)|construction power|bridge power|load bank|"
        r"commissioning.{0,40}(?:power|generator|load bank)"
    )
    explicit_scope = bool(
        re.search(scope_pattern, str(item.get("supported_action") or "").casefold())
        if data_center
        else any(re.search(scope_pattern, source) for source in evidence_texts)
    )
    commissioning = any(re.search(r"commission|load bank", source) for source in evidence_texts)
    construction = any(
        re.search(r"construct|building permit|substation|transformer", source)
        for source in evidence_texts
    )
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
    elif re.search(r"oil|gas|drill|well|pipeline|compressor", text):
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
    dates = [
        str(e.get("published_at") or e.get("event_date") or "") for e in item.get("evidence", [])
    ]
    latest = max(
        (d[:10] for d in dates if re.match(r"^\d{4}-\d{2}-\d{2}", d)), default="0000-00-00"
    )
    return segment, geography, -int(latest.replace("-", "")), item["project_id"].hex, item["id"].hex


def _current_stage(item: dict[str, Any]) -> dict[str, Any]:
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
    scope_text = re.sub(r"\bno (?:separate )?temporary (?:power|service)\b", "", negative_evidence)
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
    if negative_reason:
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
        "conflict_state": item.get("conflict_state"),
    }
    card["input_hash"] = hashlib.sha256(
        json.dumps([POLICY_VERSION, card], sort_keys=True, default=str).encode()
    ).hexdigest()
    return card


def cards(
    items: list[dict[str, Any]],
    chains: dict[str, dict[str, Any]],
    today: date,
    limit: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    prepared = [build_card(item, chains.get(str(item["project_id"])), today) for item in items]
    by_id = {str(item["id"]): item for item in items}
    prepared.sort(key=lambda card: (_priority(by_id[card["id"]]), card["id"]))
    from gridlens.domain.pursuit_screening import work_identity

    grouped: dict[str, list[dict[str, Any]]] = {}
    for card in prepared:
        item = by_id[card["id"]]
        supporting = _supporting_evidence(item)
        first = supporting[0] if supporting else {}
        identity = work_identity(
            str(first.get("source_id") or ""),
            str(first.get("document_number") or first.get("id") or ""),
            str(item.get("location") or ""),
        )
        grouped.setdefault(identity, []).append(card)

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
    for group in grouped.values():
        # This order is independent of input iteration and UUID priority sorting.
        group = sorted(group, key=lambda card: card["id"])
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
                {
                    fact["evidence_id"]: fact
                    for card in group
                    for fact in card["facts"]
                }.values(),
                key=lambda value: value["evidence_id"],
            )
            merged["sources"] = sorted(
                {
                    source["evidence_id"]: source
                    for card in group
                    for source in card["sources"]
                }.values(),
                key=lambda value: value["evidence_id"],
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
                    {key: value for key, value in merged.items() if key != "input_hash"},
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        unique.append(merged)
    return unique[: max(1, min(limit, MAX_CARDS))]
