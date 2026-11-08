"""Pure source-bound commercial brief for project and need projections."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION = "commercial-brief-v1"
AMOUNT_CLASSES = {"documented", "calculated", "estimated", "inferred", "unknown"}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, str) and len(value) <= 40 and value.strip():
        return value.strip()
    return None


def _source(evidence: dict) -> dict:
    return {
        "title": evidence.get("title"),
        "url": evidence.get("url"),
        "evidence_id": str(evidence.get("id") or evidence.get("evidence_id") or "") or None,
        "date": _iso(
            evidence.get("event_date")
            or evidence.get("published_at")
            or evidence.get("source_date")
            or evidence.get("date")
        ),
        "event_date_label": evidence.get("event_date_label"),
    }


def _source_key(source: dict) -> tuple:
    return (source.get("evidence_id"), source.get("url"), source.get("date"))


def _power_references_current(references: list, current_evidence: Any) -> bool:
    if not isinstance(current_evidence, list):
        return False
    by_id = {
        str(row.get("id") or row.get("evidence_id")): row
        for row in current_evidence
        if isinstance(row, dict) and row.get("current") is True
    }
    for reference in references:
        if not isinstance(reference, dict):
            continue
        row = by_id.get(str(reference.get("id") or reference.get("evidence_id") or ""))
        if (
            row
            and reference.get("url") == row.get("url")
            and reference.get("content_hash")
            and reference.get("content_hash") == row.get("content_hash")
        ):
            return True
    return False


def _research_activity_load(item: dict, *, today: date) -> dict | None:
    """Re-run the existing exact project-research extractor over accepted claims."""
    from gridlens.domain.project_research import (
        VERSION as RESEARCH_VERSION,
    )
    from gridlens.domain.project_research import (
        extract_project_claims,
        project_claim_state,
    )
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    need_id = str(item.get("id") or "")
    project_id = str(item.get("project_id") or "")
    activity = item.get("activity") or item.get("activity_key")
    subject = item.get("name")
    if not need_id or not project_id or not isinstance(activity, str) or not activity:
        return None
    if not isinstance(subject, str) or not subject.strip():
        return None
    claims: list[dict] = []
    references: dict[str, dict] = {}
    for row in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
        if not isinstance(row, dict) or row.get("current") is not True:
            continue
        assessment = row.get("assessment")
        if not isinstance(assessment, dict):
            continue
        if (
            row.get("evaluator_version") != RESEARCH_VERSION
            or assessment.get("acquisition_capture_version") != CAPTURE_VERSION
            or assessment.get("admission_status") != "project_research_supplement"
            or assessment.get("target_need_id") != need_id
            or assessment.get("project_identity_key") != row.get("project_identity_key")
            or assessment.get("evidence_hash") != row.get("content_hash")
            or assessment.get("semantic_hash") != row.get("semantic_hash")
        ):
            continue
        retained = assessment.get("research_claims")
        if not isinstance(retained, list):
            continue
        published_at = row.get("published_at")
        extracted = extract_project_claims(
            str(row.get("abstract") or ""),
            references=[subject, str(item.get("location") or "")],
            activity_key=activity,
            published_at=published_at if isinstance(published_at, date) else None,
            today=today,
        )
        for claim in retained:
            if not isinstance(claim, dict) or not (
                claim.get("field") == "activity_load_mw"
                and claim.get("project_id") == project_id
                and claim.get("need_id") == need_id
                and claim.get("activity_key") == activity
                and claim.get("evidence_id") == str(row.get("id"))
                and claim.get("evidence_hash") == row.get("content_hash")
                and isinstance(claim.get("quote"), str)
                and claim["quote"] in str(row.get("abstract") or "")
            ):
                continue
            if not any(
                parsed.get("field") == "activity_load_mw"
                and parsed.get("value") == claim.get("value")
                and parsed.get("quote") == claim.get("quote")
                for parsed in extracted
            ):
                continue
            evidence_id = str(row.get("id"))
            evidence_ref = {
                "id": evidence_id,
                "url": row.get("url"),
                "content_hash": row.get("content_hash"),
            }
            claims.append({**claim, "evidence": evidence_ref})
            references[evidence_id] = evidence_ref
    if not claims:
        return None
    state = project_claim_state(claims, today=today)["activity_load_mw"]
    if state["status"] == "CONFLICT":
        return {
            "status": "CONFLICT",
            "scope": activity,
            "evidence": [],
            "reported_activity_load": True,
        }
    if state["status"] != "SUPPORTED" or state["value"] is None:
        return None
    return {
        "status": "SUPPORTED",
        "value": f"{state['value']} MW",
        "scope": activity,
        "amount_class": "documented",
        "evidence": [
            references[str(claim["evidence"]["id"])]
            for claim in state.get("claims", [])
            if isinstance(claim.get("evidence"), dict)
        ],
        "reported_activity_load": True,
    }


def _date_in_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    return match.group(1) if match else None


def _accepted_sources(item: dict) -> list[dict]:
    rows = item.get("evidence")
    if not isinstance(rows, list):
        rows = []
    result = []
    seen = set()
    for evidence in rows[:40]:
        if not isinstance(evidence, dict) or evidence.get("current") is not True:
            continue
        source = _source(evidence)
        if not source.get("evidence_id") or _source_key(source) in seen:
            continue
        seen.add(_source_key(source))
        result.append(source)
    return result


def _valid_amount(value: Any) -> tuple[str, str] | None:
    """Keep only explicit, simple MW/kW point/range quantities."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    import re

    match = re.fullmatch(
        r"\s*(\d[\d,]*(?:\.\d+)?)\s*(kW|MW)\s*(?:[-–]\s*(\d[\d,]*(?:\.\d+)?)\s*(kW|MW))?\s*",
        value,
        re.I,
    )
    if not match:
        return None
    try:
        low = Decimal(match.group(1).replace(",", ""))
        high = Decimal((match.group(3) or match.group(1)).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not low.is_finite() or not high.is_finite() or low < 0 or high < low:
        return None
    low_unit = match.group(2).casefold()
    high_unit = (match.group(4) or match.group(2)).casefold()
    if low_unit != high_unit:
        return None
    low = Decimal(match.group(1).replace(",", ""))
    high = Decimal((match.group(3) or match.group(1)).replace(",", ""))
    scale = Decimal("0.001") if low_unit == "kw" else Decimal("1")
    low *= scale
    high *= scale
    normalized = (
        format(low.normalize(), "f")
        if low == high
        else f"{format(low.normalize(), 'f')}–{format(high.normalize(), 'f')}"
    )
    return normalized, "MW"


def _power(item: dict, *, today: date) -> dict:
    parsed_amount = _valid_amount(item.get("required_mw"))
    required = parsed_amount[0] if parsed_amount else None
    amount_class: str = "unknown"
    # A campus or nameplate figure is not an activity rental requirement.
    scope = (
        item.get("power_scope")
        or item.get("power_activity")
        or item.get("activity")
        or item.get("activity_key")
    )
    scope = str(scope).strip() if scope is not None else None
    text = " ".join(
        str(item.get(key) or "")
        for key in (
            "power_summary",
            "power_need_summary",
            "required_mw",
            "activity",
            "activity_key",
        )
    )
    out_of_scope = bool(
        re.search(r"\b(?:campus|nameplate|IT\s+(?:load|capacity)|design capacity)\b", text, re.I)
    )
    state = item.get("power_need")
    limits_scope_conflict = False
    if not isinstance(state, dict):
        state = _research_activity_load(item, today=today)
    if isinstance(state, dict):
        state_scope = state.get("scope")
        if state.get("status") == "CONFLICT":
            required = None
            status = "conflict"
            amount_class = "unknown"
        elif not scope or (state_scope is not None and str(state_scope).strip() != scope):
            required = None
            status = "unknown"
            amount_class = "unknown"
            limits_scope_conflict = True
        elif (
            state.get("status") == "SUPPORTED"
            and isinstance(state.get("evidence"), list)
            and state["evidence"]
            and isinstance(state.get("value"), str)
            and _power_references_current(state["evidence"], item.get("evidence"))
        ):
            parsed = _valid_amount(state.get("value"))
            required = parsed[0] if parsed else None
            status = "supported" if parsed else "unknown"
            state_amount_class = state.get("amount_class")
            amount_class = state_amount_class if state_amount_class in AMOUNT_CLASSES else "unknown"
            if status == "unknown":
                required = None
        else:
            required = None
            status = "unknown"
    else:
        required = None
        status = "unknown"
    if out_of_scope:
        required = None
        status = "unknown"
        amount_class = "unknown"
    if item.get("evidence_overflow"):
        required = None
        status = "unknown"
        amount_class = "unknown"
    limits = []
    if status == "conflict":
        limits.append("Conflicting power claims; amount withheld.")
    if required is None:
        limits.append("Activity-specific power amount is unknown; unknown is not zero.")
    if out_of_scope:
        limits.append("Campus, IT, or equipment nameplate amount is not rental demand.")
    if item.get("evidence_overflow"):
        limits.append("Current source set exceeds the brief evidence bound; power claims withheld.")
    if isinstance(state, dict) and state.get("reported_activity_load"):
        limits.append(
            "Source reports activity load; temporary rental equipment need remains unconfirmed."
        )
    if not scope:
        limits.append("Power need scope is not established.")
    if limits_scope_conflict:
        limits.append("Power claim scope does not match this activity; amount withheld.")
    return {
        "amount_class": amount_class,
        "scope": scope,
        "value": required,
        "unit": "MW" if required else None,
        "status": status,
        "limitations": limits,
    }


def _contact(actions: Any) -> dict | None:
    if not isinstance(actions, list):
        return None
    candidates = [
        a
        for a in actions
        if isinstance(a, dict) and a.get("kind") in {"call", "email", "contact"} and a.get("href")
    ]
    if not candidates:
        return None
    # Deterministic preference: specific person route first, then generic contact route.
    candidates.sort(
        key=lambda a: (
            0 if a.get("name") and a.get("responsibility") != "General company contact path" else 1,
            {"email": 0, "call": 1, "contact": 2}.get(str(a.get("kind")), 9),
            str(a.get("href")),
        )
    )
    action = candidates[0]
    label = action.get("name") or action.get("company") or "Company contact"
    if action.get("responsibility") == "General company contact path":
        label = action.get("company") or "Company contact"
    authority = str(action.get("purchasing_authority") or "Unknown; confirm for this need.")
    deliverability = "Unknown; route has not been verified for delivery."
    return {
        "contact": str(label),
        "kind": action["kind"],
        "route_kind": "person_method"
        if action.get("name") and action.get("responsibility") != "General company contact path"
        else "company_route",
        "authority": authority,
        "deliverability": deliverability,
        "sources": [],
        "href": action["href"] if isinstance(action.get("href"), str) else None,
    }


def _find_evidence(item: dict, evidence_id: str | None) -> dict | None:
    if not evidence_id:
        return None
    for row in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
        if (
            isinstance(row, dict)
            and row.get("current") is True
            and str(row.get("id") or row.get("evidence_id") or "") == str(evidence_id)
        ):
            return row
    return None


def build_commercial_brief(item: dict, *, now=None) -> dict:
    """Build a deterministic public projection; unsupported facts remain unknown."""
    item = dict(item)
    item["evidence_overflow"] = item.get("evidence_overflow") is True or any(
        isinstance(row, dict) and row.get("overflow") is True
        for row in item.get("evidence", [])
        if isinstance(item.get("evidence"), list)
    )
    current = now or datetime.now(UTC)
    as_of = _iso(current)
    evidence = _accepted_sources(item)
    limitations: list[str] = []
    assessment = item.get("shortlist_assessment")
    why_text = None
    why_date = None
    why_scope = None
    why_sources: list[dict] = []
    if not isinstance(assessment, dict) or assessment.get("eligible") is not True:
        event = item.get("event")
        if not isinstance(event, dict):
            metadata = item.get("project_metadata")
            event = metadata.get("event") if isinstance(metadata, dict) else None
        if isinstance(event, dict) and not item.get("evidence_overflow"):
            refs = (
                event.get("evidence_refs") if isinstance(event.get("evidence_refs"), list) else []
            )
            mismatched_event_date = False
            bound_event_dates: set[str] = set()
            for ref in refs if isinstance(refs, list) else []:
                row = _find_evidence(item, str(ref))
                if row:
                    source_event_day = _iso(row.get("event_date"))
                    declared_event_day = _iso(event.get("date"))
                    if declared_event_day and source_event_day != declared_event_day:
                        mismatched_event_date = True
                        continue
                    if source_event_day:
                        bound_event_dates.add(source_event_day)
                    source = _source(row)
                    why_sources.append(source)
                    why_date = source_event_day or _iso(row.get("published_at"))
            conflicting_event_dates = len(bound_event_dates) > 1
            if why_sources and not mismatched_event_date and not conflicting_event_dates:
                why_scope = (
                    item.get("supported_action") or item.get("activity") or item.get("activity_key")
                )
                if why_date:
                    selected_source = why_sources[0]
                    event_label = selected_source.get("event_date_label") or (
                        "Published" if not selected_source.get("date") else "Source reported"
                    )
                    event_scope = why_scope or "scope is not established"
                    why_text = f"{event_label} {why_date}: {event_scope}"
            elif mismatched_event_date:
                why_sources = []
                why_date = None
                limitations.append(
                    "Project event date does not match its cited current source; why-now withheld."
                )
            elif conflicting_event_dates:
                why_sources = []
                why_date = None
                limitations.append(
                    "Conflicting current dates for the cited project event; why-now withheld."
                )
    if isinstance(assessment, dict) and assessment.get("eligible") is True:
        refs = (
            assessment.get("evidence_refs")
            if isinstance(assessment.get("evidence_refs"), list)
            else []
        )
        resolved = []
        for ref in refs[:40] if isinstance(refs, list) else []:
            row = _find_evidence(item, str(ref))
            if row:
                resolved.append(row)
        why_scope = assessment.get("scope")
        cited_date = _date_in_text(assessment.get("why_now"))
        event_date_groups: dict[str, set[str]] = {}
        for row in resolved:
            event_day = _iso(row.get("event_date"))
            label = str(row.get("event_date_label") or "unspecified event").casefold()
            if event_day:
                event_date_groups.setdefault(label, set()).add(event_day)
        conflicting_event = any(len(days) > 1 for days in event_date_groups.values())
        if item.get("evidence_overflow"):
            limitations.append(
                "Current source set exceeds the brief evidence bound; source claims withheld."
            )
        elif conflicting_event:
            limitations.append(
                "Conflicting current dates for the same source event; why-now date withheld."
            )
        elif resolved:
            matched = [
                row
                for row in resolved
                if cited_date
                and cited_date
                in {
                    _iso(row.get("event_date")),
                    _iso(row.get("published_at")),
                }
            ]
            event_rows = [row for row in resolved if row.get("event_date")]
            selected = matched or event_rows or resolved
            chosen = selected[0]
            why_date = _iso(chosen.get("event_date") or chosen.get("published_at"))
            why_sources = [_source(row) for row in selected]
            label = chosen.get("event_date_label") or (
                "Published" if not chosen.get("event_date") else "Source reported"
            )
            if why_date:
                why_text = f"{label} {why_date}: {why_scope or 'scope is not established'}"
        if not why_sources:
            why_text = None
            why_scope = None
            why_date = None
            if not resolved:
                limitations.append(
                    "No current source citation is available for a why-now statement."
                )
    elif not why_sources:
        limitations.append("No current source-backed event is available to explain why now.")
    try:
        power_as_of = date.fromisoformat(str(as_of)[:10])
    except (TypeError, ValueError):
        power_as_of = date.today()
    power = _power(item, today=power_as_of)
    limitations.extend(power["limitations"])
    actions = item.get("contact_actions") or item.get("contact")
    best_contact = _contact(actions)
    if best_contact is None:
        limitations.append("No privacy-filtered contact route is available.")
    preview = item.get("commercial_preview")
    if not isinstance(preview, dict):
        preview = {}
    action_text = (
        preview.get("next_action") or item.get("commercial_next_action") or item.get("next_action")
    )
    action_source = None
    if why_sources:
        action_source = why_sources[0]
    if not isinstance(action_text, str) or not action_text.strip():
        action_text = "Research the scoped power need and timing from current source evidence."
        limitations.append(
            "Next action is a research prompt; no buyer or purchase authority is established."
        )
    # Source dates are intentionally separate from retrieval/as-of dates.
    source_dates = [source.get("date") for source in evidence if source.get("date")]
    source_age = None
    if source_dates:
        try:
            as_of_day = date.fromisoformat(str(as_of)[:10])
            latest_source_day = max(date.fromisoformat(str(value)[:10]) for value in source_dates)
            source_age = max(0, (as_of_day - latest_source_day).days)
        except ValueError:
            source_age = None
    freshness_state = (
        "source_unavailable"
        if not evidence
        else "current_source"
        if source_age is not None and source_age <= 180
        else "source_age_unknown"
        if source_age is None
        else "stale_source"
    )
    if isinstance(assessment, dict) and assessment.get("eligible") is True and not why_sources:
        freshness_state = "refresh_unavailable"
        limitations.append(
            "A source refresh or accepted citation is unavailable for this rationale."
        )
    return {
        "version": VERSION,
        "why_now": {
            "text": why_text,
            "source_date": why_date,
            "scope": why_scope,
            "sources": why_sources,
        },
        "power_need": power,
        "best_contact": best_contact,
        "next_action": {
            "text": action_text.strip(),
            "kind": "research" if not best_contact else "confirm_need",
            "source": action_source,
        },
        "freshness": {
            "as_of": as_of,
            "status": freshness_state,
            "source_date": why_date,
            "source_age_days": source_age,
        },
        "limitations": list(dict.fromkeys(limitations)),
        "sources": evidence,
    }


def build_optional_commercial_brief(item: dict, *, now=None) -> dict:
    """Keep optional brief failures from changing legacy card availability."""
    try:
        return build_commercial_brief(item, now=now)
    except Exception:
        return {
            "version": VERSION,
            "why_now": {"text": None, "source_date": None, "scope": None, "sources": []},
            "power_need": {
                "amount_class": "unknown",
                "scope": None,
                "value": None,
                "unit": None,
                "status": "unknown",
                "limitations": [
                    "Commercial brief unavailable; source-backed power amount remains unknown."
                ],
            },
            "best_contact": None,
            "next_action": {
                "text": "Review current source evidence.",
                "kind": "research",
                "source": None,
            },
            "freshness": {
                "as_of": _iso(now or datetime.now(UTC)),
                "status": "unavailable",
                "source_date": None,
            },
            "limitations": [
                "Commercial brief unavailable; legacy project details remain available."
            ],
            "sources": [],
        }
