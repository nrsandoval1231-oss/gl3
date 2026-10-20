"""Repeatable-read projection of retained workspace changes and fact decisions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, tuple_
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    BuyingChainEvidence,
    CallFactDecision,
    CallFactVersion,
    ChangeEvent,
    Evidence,
    NeedObservation,
    PowerNeed,
    Project,
    Source,
    WorkspaceChangeAcknowledgment,
)

UNINITIALIZED_BASELINE = uuid5(NAMESPACE_URL, "https://gridlens.local/workspace-change-baseline/v1")
CHANGE_CATEGORIES = ("discovered", "changed", "promoted", "closed", "review_exception")
_TIER_ORDER = {"signal": 0, "prospect": 1, "lead": 2}
_ACCEPTED_ASSERTIONS = {"accepted", "corrected"}


def review_token(baseline_identity: UUID, event_keys: list[str]) -> str:
    payload = json.dumps(
        {"baseline_identity": str(baseline_identity), "event_keys": event_keys},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _power_need_rows(value: object) -> dict[str, dict]:
    if not isinstance(value, list):
        return {}
    return {
        str(row["activity"]): row
        for row in value
        if isinstance(row, dict) and isinstance(row.get("activity"), str)
    }


def _transition(before: dict | None, after: dict | None) -> str:
    if before is None:
        return "discovered"
    if after is None:
        return "closed"
    old_tier = _TIER_ORDER.get(str(before.get("tier", "")).casefold())
    new_tier = _TIER_ORDER.get(str(after.get("tier", "")).casefold())
    if old_tier is not None and new_tier is not None and new_tier > old_tier:
        return "promoted"
    return "changed"


def _event_projection(event: ChangeEvent) -> dict | None:
    before_state = event.prior_state
    after_state = event.new_state
    field = (event.field_name or "").casefold()
    kind = event.kind.casefold()
    if field == "source_listing" or "absent_from_source" in kind:
        if not isinstance(before_state, dict) or not isinstance(after_state, dict):
            return None
        before_value, after_value = before_state.get("listed"), after_state.get("listed")
        if before_value == after_value:
            return None
        absent = after_value is False
        return {
            "event_key": f"change:{event.id}",
            "category": "review_exception" if absent else "changed",
            "title": "Source listing absent" if absent else "Source listing returned",
            "detail": (
                "The record left a complete source snapshot. Review its status; "
                "absence does not close the need."
                if absent
                else "The source listing returned. Review the preserved source state."
            ),
            "created_at": event.created_at,
            "source_date": event.source_date,
            "project_id": event.project_id,
            "before_state": before_state,
            "after_state": after_state,
            "needs": [],
            "sources": [],
            "_event": event,
            "_need_observation_id": event.observation_id,
        }

    if field == "power_need" or kind == "power_need_changed":
        if not isinstance(before_state, dict) or not isinstance(after_state, dict):
            return None
        before = _power_need_rows(before_state.get("value"))
        after = _power_need_rows(after_state.get("value"))
        activities = set(before) | set(after)
        changed = {
            activity for activity in activities if before.get(activity) != after.get(activity)
        }
        if not changed:
            return None
        transitions = {
            activity: _transition(before.get(activity), after.get(activity)) for activity in changed
        }
        distinct = set(transitions.values())
        category = next(iter(distinct)) if len(distinct) == 1 else "changed"
        label = ", ".join(sorted(changed))
        return {
            "event_key": f"change:{event.id}",
            "category": category,
            "title": f"Power need transition: {label}",
            "detail": "Supported before/after power-need state changed.",
            "created_at": event.created_at,
            "source_date": event.source_date,
            "project_id": event.project_id,
            "before_state": before_state,
            "after_state": after_state,
            "needs": [],
            "transitions": transitions,
            "sources": [],
            "_event": event,
            "_need_activities": changed,
        }

    if not isinstance(before_state, dict) or not isinstance(after_state, dict):
        return None
    if before_state == after_state:
        return None
    return {
        "event_key": f"change:{event.id}",
        "category": "changed",
        "title": f"{event.field_name or event.kind.replace('_', ' ').title()} changed",
        "detail": (
            "Retained project state changed; this project-level event is not "
            "assigned to a sibling need."
        ),
        "created_at": event.created_at,
        "source_date": event.source_date,
        "project_id": event.project_id,
        "before_state": before_state,
        "after_state": after_state,
        "needs": [],
        "sources": [],
        "_event": event,
    }


def _fact_rows(session: Session) -> Sequence[Row[tuple[CallFactDecision, CallFactVersion]]]:
    return session.execute(
        select(CallFactDecision, CallFactVersion)
        .join(CallFactVersion, CallFactVersion.id == CallFactDecision.fact_version_id)
        .where(CallFactDecision.decision.in_(("accepted", "corrected", "retracted")))
        .order_by(CallFactDecision.created_at.desc(), CallFactDecision.id.desc())
    ).all()


def _fact_projections(session: Session, acknowledged: set[str]) -> list[dict]:
    rows = _fact_rows(session)
    rows = sorted(rows, key=lambda row: row[0].version)
    versions = {fact.id: fact for _decision, fact in rows}
    latest_assertion: dict[UUID, CallFactDecision] = {}
    projections = []
    for decision, fact in rows:
        prior_for_fact = latest_assertion.get(fact.id)
        before_fact: CallFactVersion | None = None
        before_version: int | None = None
        after_version: int | None = None
        is_change = False
        if decision.decision == "accepted":
            is_change = (
                prior_for_fact is None or prior_for_fact.decision not in _ACCEPTED_ASSERTIONS
            )
            after_version = decision.version
        elif decision.decision == "corrected":
            before_fact = versions.get(fact.predecessor_id) if fact.predecessor_id else None
            prior = latest_assertion.get(before_fact.id) if before_fact is not None else None
            is_change = (
                before_fact is not None
                and prior is not None
                and prior.decision in _ACCEPTED_ASSERTIONS
                and (
                    before_fact.fact_type != fact.fact_type
                    or before_fact.value != fact.value
                    or before_fact.effective_from != fact.effective_from
                    or before_fact.effective_until != fact.effective_until
                )
            )
            if is_change and prior is not None:
                before_version = prior.version
            after_version = decision.version
        elif decision.decision == "retracted":
            prior = prior_for_fact
            is_change = prior is not None and prior.decision in _ACCEPTED_ASSERTIONS
            before_fact = fact
            if is_change and prior is not None:
                before_version = prior.version
            after_version = decision.version

        if is_change and f"fact:{decision.id}" not in acknowledged:

            def fact_state(version: CallFactVersion) -> dict:
                return {
                    "fact_type": version.fact_type,
                    "value": version.value,
                    "effective_from": (
                        version.effective_from.isoformat() if version.effective_from else None
                    ),
                    "effective_until": (
                        version.effective_until.isoformat() if version.effective_until else None
                    ),
                }

            before_value = fact_state(before_fact) if before_fact is not None else None
            after_value = fact_state(fact) if decision.decision != "retracted" else None
            projections.append(
                {
                    "event_key": f"fact:{decision.id}",
                    "category": "changed",
                    "title": f"Call fact {decision.decision}: {fact.fact_type.replace('_', ' ')}",
                    "detail": fact.facility_scope,
                    "created_at": decision.created_at,
                    "source_date": fact.source_date,
                    "project_id": fact.project_id,
                    "before_state": before_value,
                    "after_state": after_value,
                    "needs": [],
                    "sources": [],
                    "fact_version_id": fact.id,
                    "before_version": before_version,
                    "after_version": after_version,
                    "fact_type": fact.fact_type,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "actor": decision.actor,
                    "confirmed_at": fact.confirmed_at,
                    "source_reference": fact.source_reference,
                    "_fact": fact,
                }
            )

        latest_assertion[decision.fact_version_id] = decision
    return projections


def _enrich_displayed_items(session: Session, items: list[dict]) -> None:
    events = [item["_event"] for item in items if "_event" in item]
    facts = [item["_fact"] for item in items if "_fact" in item]
    power_pairs = {
        (event.project_id, activity)
        for item in items
        if item.get("_need_activities")
        for event in (item["_event"],)
        if event.project_id is not None
        for activity in item["_need_activities"]
    }
    need_links: dict[tuple[UUID, str], list[dict]] = {}
    if power_pairs:
        power_rows = session.execute(
            select(PowerNeed, Project.name, Project.location)
            .outerjoin(Project, Project.id == PowerNeed.project_id)
            .where(tuple_(PowerNeed.project_id, PowerNeed.activity_key).in_(power_pairs))
            .order_by(PowerNeed.activity_key, PowerNeed.id)
        ).all()
        for need, name, location in power_rows:
            need_links.setdefault((need.project_id, need.activity_key), []).append(
                {
                    "id": need.id,
                    "name": name or need.activity_key,
                    "location": location,
                    "active": need.active,
                    "tier": need.tier,
                }
            )

    observation_ids = {
        item["_need_observation_id"] for item in items if "_need_observation_id" in item
    }
    observation_links: dict[UUID, list[dict]] = {}
    if observation_ids:
        observation_rows = session.execute(
            select(NeedObservation.observation_id, PowerNeed, Project.name, Project.location)
            .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
            .outerjoin(Project, Project.id == PowerNeed.project_id)
            .where(NeedObservation.observation_id.in_(observation_ids))
            .order_by(NeedObservation.observation_id, PowerNeed.id)
        ).all()
        for observation_id, need, name, location in observation_rows:
            observation_links.setdefault(observation_id, []).append(
                {
                    "id": need.id,
                    "name": name or need.activity_key,
                    "location": location,
                    "active": need.active,
                    "tier": need.tier,
                }
            )

    fact_meta: dict[UUID, tuple[str | None, str | None, bool | None, str | None]] = {}
    if facts:
        fact_rows = session.execute(
            select(
                CallFactVersion.id,
                Project.name,
                Project.location,
                PowerNeed.active,
                PowerNeed.tier,
            )
            .select_from(CallFactVersion)
            .outerjoin(Project, Project.id == CallFactVersion.project_id)
            .outerjoin(PowerNeed, PowerNeed.id == CallFactVersion.need_id)
            .where(CallFactVersion.id.in_({fact.id for fact in facts}))
        ).all()
        fact_meta = {
            fact_id: (name, location, active, tier)
            for fact_id, name, location, active, tier in fact_rows
        }

    evidence_ids = {event.evidence_id for event in events if event.evidence_id is not None}
    evidence_by_id = (
        {
            source.id: source
            for source in session.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids)))
        }
        if evidence_ids
        else {}
    )
    chain_ids: set[UUID] = set()
    event_chain_ids: dict[int, list[UUID]] = {}
    for event in events:
        ids = (
            (event.new_state or {}).get(
                "buying_chain_evidence_ids", [str(event.buying_chain_evidence_id)]
            )
            if isinstance(event.new_state, dict)
            else [str(event.buying_chain_evidence_id)]
        )
        if event.buying_chain_evidence_id is not None and isinstance(ids, list):
            parsed = []
            for value in ids:
                try:
                    chain_id = UUID(str(value))
                except ValueError:
                    continue
                parsed.append(chain_id)
                chain_ids.add(chain_id)
            event_chain_ids[event.id] = parsed
    chain_by_id = (
        {
            source.id: source
            for source in session.scalars(
                select(BuyingChainEvidence).where(BuyingChainEvidence.id.in_(chain_ids))
            )
        }
        if chain_ids
        else {}
    )

    for item in items:
        if "_event" in item:
            event = item.pop("_event")
            if "_need_observation_id" in item:
                item["needs"] = observation_links.get(item.pop("_need_observation_id"), [])
            elif "_need_activities" in item:
                activities = item.pop("_need_activities")
                item["needs"] = [
                    need
                    for activity in sorted(activities)
                    for need in need_links.get((event.project_id, activity), [])
                ]
            sources = []
            if (
                event.evidence_id is not None
                and (source := evidence_by_id.get(event.evidence_id)) is not None
            ):
                sources.append(
                    {
                        "title": source.title,
                        "url": source.url,
                        "published_at": source.published_at,
                        "event_date": source.event_date,
                        "retrieved_at": source.observed_at,
                        "content_hash": source.content_hash,
                    }
                )
            for source_id in event_chain_ids.get(event.id, []):
                if (chain_source := chain_by_id.get(source_id)) is not None:
                    sources.append(
                        {
                            "title": chain_source.title,
                            "url": chain_source.url,
                            "published_at": chain_source.published_at,
                            "event_date": None,
                            "retrieved_at": chain_source.last_seen_at,
                            "content_hash": chain_source.content_hash,
                        }
                    )
            item["sources"] = sources
        elif "_fact" in item:
            fact = item.pop("_fact")
            name, location, active, tier = fact_meta.get(fact.id, (None, None, None, None))
            item["detail"] = f"{fact.facility_scope} · {name or 'Project unavailable'}"
            item["needs"] = [
                {
                    "id": fact.need_id,
                    "name": name or fact.activity_key,
                    "location": location,
                    "active": active if active is not None else False,
                    "tier": tier or "Unknown",
                }
            ]


def source_health_exceptions(session: Session) -> list[dict]:
    exceptions = []
    for source in session.scalars(select(Source).order_by(Source.id)):
        health = source.health if isinstance(source.health, dict) else {}
        status = str(health.get("status") or "Unknown")
        error = health.get("error")
        parse_failures = int(health.get("parse_failures") or 0)
        if (
            source.enabled
            and source.registry_enabled
            and (
                status.casefold()
                in {"failed", "partial", "unknown", "registryunavailable", "overdue"}
                or error
                or parse_failures > 0
            )
        ):
            exceptions.append(
                {
                    "source_id": source.id,
                    "status": status,
                    "error": str(error)[:300] if error else None,
                    "parse_failures": parse_failures,
                }
            )
    return exceptions


def workspace_changes(
    session: Session,
    baseline_identity: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    evaluated_at: datetime | None = None,
) -> dict:
    """Return the exact unreviewed page, full category counts, and its bound token."""
    acknowledged = set(session.scalars(select(WorkspaceChangeAcknowledgment.event_key)).all())
    acknowledged_change_ids = {
        int(event_key.removeprefix("change:"))
        for event_key in acknowledged
        if event_key.startswith("change:") and event_key.removeprefix("change:").isdigit()
    }
    events = session.scalars(
        select(ChangeEvent)
        .where(ChangeEvent.material.is_(True))
        .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
    ).all()
    candidates = [
        item
        for event in events
        if event.id not in acknowledged_change_ids
        and (item := _event_projection(event)) is not None
    ]
    candidates.extend(_fact_projections(session, acknowledged))
    candidates.sort(
        key=lambda item: (
            item["created_at"] or datetime.min.replace(tzinfo=UTC),
            item["event_key"],
        ),
        reverse=True,
    )
    counts = Counter(item["category"] for item in candidates)
    displayed = candidates[offset : offset + limit]
    _enrich_displayed_items(session, displayed)
    keys = [item["event_key"] for item in displayed]
    next_offset = offset + limit if offset + limit < len(candidates) else None
    return {
        "items": displayed,
        "counts": {category: counts.get(category, 0) for category in CHANGE_CATEGORIES},
        "total_unreviewed": len(candidates),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "evaluated_at": evaluated_at or datetime.now(UTC),
        "baseline_identity": baseline_identity,
        "token": review_token(baseline_identity, keys),
        "source_health_exceptions": source_health_exceptions(session),
    }
