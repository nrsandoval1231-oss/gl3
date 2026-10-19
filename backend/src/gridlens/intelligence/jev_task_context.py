"""Bounded, task-specific inputs for advisory Jev contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.pursuit_research import ACTIVE
from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.persistence.models import (
    ChangeEvent,
    Project,
    ProjectMatchDecision,
    ProjectMaterialState,
    PursuitResearchQuestion,
)

CONTRACT_INSTRUCTIONS: dict[str, dict[str, Any]] = {
    "SOURCE_RELEVANCE_V1": {
        "instructions": "Assess whether the retained passage is relevant to this exact power need.",
        "disallowed_assumptions": [
            "source availability proves the claim",
            "a source is authoritative merely because it is enabled",
        ],
    },
    "EVENT_CLASS_V1": {
        "instructions": (
            "Classify only an event explicitly supported by the retained passage for this need."
        ),
        "disallowed_assumptions": ["planned means completed", "an undated event has a known date"],
    },
    "MATCH_ADVISORY_V1": {
        "instructions": (
            "For every exact existing candidate UUID, advise SAME, DIFFERENT, or UNRESOLVED "
            "from the supplied deterministic facts."
        ),
        "disallowed_assumptions": [
            "name or city similarity alone establishes identity",
            "create or merge a project",
        ],
    },
    "MATERIALITY_V1": {
        "instructions": (
            "Assess semantic change only from the supplied before and after accepted states."
        ),
        "disallowed_assumptions": ["metadata churn is material", "missing state proves change"],
    },
    "POWER_ACTIVITY_HINT_V1": {
        "instructions": "Classify the evidenced power activity for this exact need and site.",
        "disallowed_assumptions": [
            "a generic construction label establishes temporary power",
            "an industry label proves a buyer need",
        ],
    },
    "RESEARCH_PRIORITY_V1": {
        "instructions": (
            "Rank the supplied bounded research work using its need, evidence, freshness, "
            "and unresolved questions."
        ),
        "disallowed_assumptions": [
            "priority is sales probability",
            "priority overrides caps or source permissions",
        ],
    },
    "BUYER_ROLE_HINT_V1": {
        "instructions": (
            "Classify the role of the exact named party candidate using only its cited "
            "retained evidence."
        ),
        "disallowed_assumptions": [
            "applicant is the buyer",
            "unrelated parties can be aggregated",
            "a role is proven without citations",
        ],
    },
    "LLM_ROUTE_V1": {
        "instructions": (
            "Choose a bounded permitted follow-up for the exact need from the supplied "
            "unresolved evidence state."
        ),
        "disallowed_assumptions": [
            "invoke a model URL or tool",
            "bypass policy, source, queue, or spend gates",
        ],
    },
}


def _party_candidates(session: Session, project_id: UUID) -> list[dict[str, Any]]:
    view = buying_chain_view(session, project_id)
    result = []
    for candidate in view.get("candidates", []):
        if candidate.get("stale"):
            continue
        citations = [
            item
            for item in candidate.get("evidence", [])
            if item.get("current_support") is True
            and item.get("id")
            and item.get("url")
            and item.get("quote")
        ]
        if not candidate.get("organization") or not citations:
            continue
        result.append(
            {
                "party_id": str(candidate["id"]),
                "organization": str(candidate["organization"])[:180],
                "person": str(candidate.get("person_name") or "")[:120] or None,
                "title": str(candidate.get("title") or "")[:120] or None,
                "category": candidate.get("category"),
                "relationship": candidate.get("organization_relationship"),
                "person_project_relationship": candidate.get("person_project_relationship"),
                "citations": [
                    {
                        "citation_id": str(item["id"]),
                        "url": str(item.get("url", ""))[:500],
                        "quote": str(item.get("quote", ""))[:500],
                        "content_hash": item.get("content_hash"),
                        "supports": item.get("supports"),
                    }
                    for item in citations[:4]
                    if item.get("id") and item.get("url") and item.get("quote")
                ],
            }
        )
        if len(result) == 3:
            break
    return result


def _match_candidates(
    session: Session, project: Project, evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence_ids = [UUID(item["id"]) for item in evidence]
    if not evidence_ids:
        return []
    rows = session.execute(
        select(ProjectMatchDecision, Project)
        .join(Project, Project.id == ProjectMatchDecision.candidate_project_id)
        .where(
            ProjectMatchDecision.evidence_id.in_(evidence_ids),
            ProjectMatchDecision.candidate_project_id.is_not(None),
            Project.id != project.id,
        )
        .order_by(ProjectMatchDecision.decided_at.desc(), ProjectMatchDecision.id.desc())
        .limit(24)
    ).all()
    candidates: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    for decision, candidate in rows:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        candidates.append(
            {
                "candidate_id": str(candidate.id),
                "identity_key": candidate.identity_key,
                "name": candidate.name[:180],
                "location": candidate.location[:180] if candidate.location else None,
                "identity_facts": candidate.identity_facts or {},
                "deterministic_decision": decision.decision,
                "deterministic_reason": decision.reason[:300],
                "matched_facts": (decision.matched_facts or [])[:8],
                "evidence_id": str(decision.evidence_id) if decision.evidence_id else None,
                "decision_id": decision.id,
            }
        )
        if len(candidates) == 3:
            break
    return candidates


def _materiality_context(
    session: Session, project_id: UUID, evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    material_events = session.scalars(
        select(ChangeEvent)
        .where(ChangeEvent.project_id == project_id, ChangeEvent.material.is_(True))
        .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
        .limit(8)
    ).all()
    current = session.get(ProjectMaterialState, project_id)
    exact_ids = {item["id"] for item in evidence}
    events = [
        {
            "event_id": row.id,
            "evidence_id": str(row.evidence_id) if row.evidence_id else None,
            "content_hash": row.content_hash,
            "field": row.field_name,
            "before": row.prior_state,
            "after": row.new_state,
            "source_date": row.source_date.isoformat() if row.source_date else None,
        }
        for row in material_events
        if row.evidence_id is None or str(row.evidence_id) in exact_ids
    ]
    return {
        "before_after_events": events,
        "current_accepted_semantic_state": current.state if current else None,
        "missing_state": not bool(events and current),
    }


def _unresolved_questions(session: Session, need_id: UUID) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(PursuitResearchQuestion)
        .where(
            PursuitResearchQuestion.need_id == need_id,
            PursuitResearchQuestion.status.in_(ACTIVE),
        )
        .order_by(PursuitResearchQuestion.created_at, PursuitResearchQuestion.id)
        .limit(8)
    ).all()
    return [
        {
            "question_id": str(row.id),
            "category": row.category,
            "question": row.question[:500],
            "status": row.status,
            "attempt_count": row.attempt_count,
            "query_fingerprint": row.query_fingerprint,
        }
        for row in rows
    ]


def build_task_context(
    session: Session,
    task_type: str,
    need: Any,
    project: Project,
    source: Any,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return only bounded immutable task inputs; callers digest the full result."""
    instructions = CONTRACT_INSTRUCTIONS[task_type]
    base: dict[str, Any] = {
        "contract_id": task_type,
        "contract_instructions": instructions["instructions"],
        "disallowed_assumptions": instructions["disallowed_assumptions"],
        "task_version": "jev-task-context-v1",
        "need": {
            "need_id": str(need.id),
            "updated_at": need.updated_at.isoformat() if need.updated_at else None,
            "admission_basis": need.admission_basis,
            "activity": need.activity_key,
            "rationale": need.rationale[:900],
            "required_mw": need.required_mw,
            "start_window": need.start_window,
            "duration": need.duration,
            "supply": need.supply,
        },
        "accepted_operator_facts": getattr(need, "_intelligence_accepted_facts", []),
        "project_identity": {
            "project_id": str(project.id),
            "identity_key": project.identity_key,
            "identity_facts": project.identity_facts or {},
        },
        "source_restrictions": {
            "primary_source_id": source.id,
            "primary_source_enabled": bool(source.enabled and source.registry_enabled),
            "evidence_sources": [
                {
                    "evidence_id": item["id"],
                    "source_id": item.get("source_id"),
                    "enabled": item.get("source_enabled"),
                    "registry_enabled": item.get("source_registry_enabled"),
                    "retrieval_method": item.get("retrieval_method"),
                }
                for item in evidence
            ],
        },
        "evidence": evidence,
        "unresolved_questions": _unresolved_questions(session, need.id),
    }
    if task_type == "MATCH_ADVISORY_V1":
        base["deterministic_candidates"] = _match_candidates(session, project, evidence)
    elif task_type == "MATERIALITY_V1":
        base["materiality"] = _materiality_context(session, project.id, evidence)
    elif task_type == "BUYER_ROLE_HINT_V1":
        base["party_candidates"] = _party_candidates(session, project.id)
    elif task_type in {"SOURCE_RELEVANCE_V1", "EVENT_CLASS_V1"}:
        base["task_evidence_scope"] = {
            "evidence_ids": [item["id"] for item in evidence],
            "latest_published_at": next(
                (item["published_at"] for item in evidence if item.get("published_at")), None
            ),
        }
    elif task_type in {"POWER_ACTIVITY_HINT_V1", "RESEARCH_PRIORITY_V1", "LLM_ROUTE_V1"}:
        base["research_state"] = getattr(need, "_intelligence_accepted_source_claims", {})
    return base
