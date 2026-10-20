"""Repeatable-read projection of retained workspace changes and fact decisions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
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


def _need_links(session: Session, event: ChangeEvent, activities: set[str]) -> list[dict]:
    if not activities or event.project_id is None:
        return []
    needs = session.scalars(
        select(PowerNeed)
        .where(
            PowerNeed.project_id == event.project_id,
            PowerNeed.activity_key.in_(activities),
        )
        .order_by(PowerNeed.activity_key, PowerNeed.id)
    ).all()
    projects = {need.project_id: session.get(Project, need.project_id) for need in needs}
    links = []
    for need in needs:
        project = projects[need.project_id]
        links.append(
            {
                "id": need.id,
                "name": project.name if project else need.activity_key,
                "location": project.location if project else None,
                "active": need.active,
                "tier": need.tier,
            }
        )
    return links


def _event_projection(session: Session, event: ChangeEvent) -> dict | None:
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
        needs = session.scalars(
            select(PowerNeed)
            .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
            .where(NeedObservation.observation_id == event.observation_id)
            .order_by(PowerNeed.id)
        ).all()
        projects = {need.project_id: session.get(Project, need.project_id) for need in needs}
        links = []
        for need in needs:
            project = projects[need.project_id]
            links.append(
                {
                    "id": need.id,
                    "name": project.name if project else need.activity_key,
                    "location": project.location if project else None,
                    "active": need.active,
                    "tier": need.tier,
                }
            )
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
            "needs": links,
            "sources": _event_sources(session, event),
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
            "needs": _need_links(session, event, changed),
            "transitions": transitions,
            "sources": _event_sources(session, event),
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
        "sources": _event_sources(session, event),
    }


def _event_sources(session: Session, event: ChangeEvent) -> list[dict]:
    sources: list[dict] = []
    if event.evidence_id is not None:
        source = session.get(Evidence, event.evidence_id)
        if source is not None:
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
    if event.buying_chain_evidence_id is not None:
        ids = (event.new_state or {}).get(
            "buying_chain_evidence_ids", [str(event.buying_chain_evidence_id)]
        )
        if isinstance(ids, list):
            for source_id in ids:
                chain_source = session.get(BuyingChainEvidence, UUID(str(source_id)))
                if chain_source is not None:
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
    return sources


def _fact_rows(session: Session) -> Sequence[Row[tuple[CallFactDecision, CallFactVersion]]]:
    return session.execute(
        select(CallFactDecision, CallFactVersion)
        .join(CallFactVersion, CallFactVersion.id == CallFactDecision.fact_version_id)
        .where(CallFactDecision.decision.in_(("accepted", "corrected", "retracted")))
        .order_by(CallFactDecision.created_at.desc(), CallFactDecision.id.desc())
    ).all()


def _latest_assertion_decision(
    decisions: Sequence[CallFactDecision], fact_version_id: UUID, before_version: int
) -> CallFactDecision | None:
    candidates = [
        decision
        for decision in decisions
        if decision.fact_version_id == fact_version_id
        and decision.version < before_version
        and decision.decision in {"accepted", "corrected", "retracted"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda decision: decision.version)


def _fact_projections(session: Session) -> list[dict]:
    rows = _fact_rows(session)
    decisions = session.scalars(select(CallFactDecision).order_by(CallFactDecision.version)).all()
    versions = {version.id: version for _decision, version in rows}
    projections = []
    for decision, fact in rows:
        before_fact: CallFactVersion | None = None
        before_version: int | None = None
        after_version: int | None = None
        if decision.decision == "accepted":
            prior = _latest_assertion_decision(decisions, fact.id, decision.version)
            if prior is not None and prior.decision in _ACCEPTED_ASSERTIONS:
                continue
            after_version = decision.version
        elif decision.decision == "corrected":
            before_fact = versions.get(fact.predecessor_id) if fact.predecessor_id else None
            prior = (
                _latest_assertion_decision(decisions, before_fact.id, decision.version)
                if before_fact is not None
                else None
            )
            if before_fact is None or prior is None or prior.decision not in _ACCEPTED_ASSERTIONS:
                continue
            if before_fact.fact_type == fact.fact_type and before_fact.value == fact.value:
                continue
            before_version = prior.version
            after_version = decision.version
        elif decision.decision == "retracted":
            prior = _latest_assertion_decision(decisions, fact.id, decision.version)
            if prior is None or prior.decision not in _ACCEPTED_ASSERTIONS:
                continue
            before_fact = fact
            before_version = prior.version
            after_version = decision.version

        project = session.get(Project, fact.project_id)
        need = session.get(PowerNeed, fact.need_id)
        before_value = (
            {"fact_type": before_fact.fact_type, "value": before_fact.value}
            if before_fact is not None
            else None
        )
        after_value = (
            {"fact_type": fact.fact_type, "value": fact.value}
            if decision.decision != "retracted"
            else None
        )
        projections.append(
            {
                "event_key": f"fact:{decision.id}",
                "category": "changed",
                "title": f"Call fact {decision.decision}: {fact.fact_type.replace('_', ' ')}",
                "detail": (
                    f"{fact.facility_scope} · {project.name if project else 'Project unavailable'}"
                ),
                "created_at": decision.created_at,
                "source_date": fact.source_date,
                "project_id": fact.project_id,
                "before_state": before_value,
                "after_state": after_value,
                "needs": [
                    {
                        "id": fact.need_id,
                        "name": project.name if project else fact.activity_key,
                        "location": project.location if project else None,
                        "active": need.active if need else False,
                        "tier": need.tier if need else "Unknown",
                    }
                ],
                "fact_version_id": fact.id,
                "before_version": before_version,
                "after_version": after_version,
                "fact_type": fact.fact_type,
                "decision": decision.decision,
                "reason": decision.reason,
                "actor": decision.actor,
                "confirmed_at": fact.confirmed_at,
                "source_reference": fact.source_reference,
                "sources": [],
            }
        )
    return projections


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
    events = session.scalars(
        select(ChangeEvent)
        .where(ChangeEvent.material.is_(True))
        .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
    ).all()
    candidates = [
        item for event in events if (item := _event_projection(session, event)) is not None
    ]
    candidates.extend(_fact_projections(session))
    candidates = [item for item in candidates if item["event_key"] not in acknowledged]
    candidates.sort(
        key=lambda item: (
            item["created_at"] or datetime.min.replace(tzinfo=UTC),
            item["event_key"],
        ),
        reverse=True,
    )
    counts = Counter(item["category"] for item in candidates)
    displayed = candidates[offset : offset + limit]
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
