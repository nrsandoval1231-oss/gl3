"""Bounded question scheduling on the existing PostgreSQL jobs and pursuits."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.domain.pursuit_research import (
    ACTIVE,
    POLICY_VERSION,
    fingerprint,
    plan_questions,
    targeted_queries,
    targeted_query_plan,
)
from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.intelligence.commercial_evaluation import save_evaluations
from gridlens.intelligence.research_routing import routing_context, selected_sources
from gridlens.persistence.models import (
    Job,
    PowerNeed,
    Project,
    Pursuit,
    PursuitResearchQuestion,
)
from gridlens.settings import settings

BUDGET = {
    "searches": 3,
    "urls": 10,
    "documents": 5,
    "document_bytes": 750_000,
    "model_calls": 0,
    "timeout_seconds": 180,
    "max_cost_usd": "0",
}

# Retry unavailable/transient routes on a short bounded schedule. Successful
# checked negatives retain their category freshness window instead.
RETRY_BACKOFF_HOURS = (1, 6, 24)


def question_view(row: PursuitResearchQuestion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "pursuit_id": str(row.pursuit_id),
        "project_id": str(row.project_id),
        "need_id": str(row.need_id),
        "question": row.question,
        "category": row.category,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
        "retry_after": row.retry_after,
        "query_fingerprint": row.query_fingerprint,
        "evidence_fingerprint": row.evidence_fingerprint,
        "context": row.context,
        "budget": row.budget,
        "receipt": row.receipt,
    }


def schedule_questions(
    session: Session,
    cards: list[dict],
    *,
    force: bool = False,
    origin: str = "automatic",
    parent_id: UUID | None = None,
    now: datetime | None = None,
) -> list[PursuitResearchQuestion]:
    """Serialize planning/caps. Changed inputs never overwrite a running attempt."""
    if origin not in {"automatic", "manual", "follow_up", "validation"}:
        raise ValueError("Unknown research scheduling origin")
    now = now or datetime.now(UTC)
    session.execute(text("SELECT pg_advisory_xact_lock(290029)"))
    save_evaluations(session, cards, now=now)
    rows = list(session.scalars(select(PursuitResearchQuestion)))
    today_count = sum(row.created_at.date() == now.date() for row in rows)
    created = []
    for card in cards:
        pursuit = session.scalar(
            select(Pursuit)
            .where(Pursuit.identity_key == "commercial-need:" + str(card["id"]))
            .with_for_update()
        )
        assert pursuit is not None
        need = session.get(PowerNeed, UUID(str(card["id"])))
        project = session.get(Project, pursuit.project_id)
        if need is None or project is None or need.project_id != project.id:
            continue
        prior = [row for row in rows if row.pursuit_id == pursuit.id]
        active = [row for row in prior if row.status in ACTIVE]
        if parent_id:
            parent = session.get(PursuitResearchQuestion, parent_id)
            if (
                not parent
                or parent.pursuit_id != pursuit.id
                or parent.parent_id
                or any(row.parent_id == parent_id for row in rows)
            ):
                continue
        sources = selected_sources(session, need.id)
        chain = buying_chain_view(session, project.id)
        organizations = [
            {
                "name": item["organization"],
                "role": item.get("category"),
                "relationship": item.get("organization_relationship"),
            }
            for item in chain.get("candidates", [])
            if not item.get("stale") and item.get("organization_relationship") == "DIRECT"
        ]
        context = {
            "policy_version": POLICY_VERSION,
            "name": project.name,
            "site_address": project.location,
            "geography": project.location,
            "organization_names": sorted(
                {item["name"] for item in organizations}
                | {
                    str(c["organization"])
                    for c in card.get("contacts", [])
                    if c.get("organization")
                }
            ),
            "organizations": organizations,
            "stable_identifiers": sorted(
                {
                    source["external_id"]
                    for source in sources
                    if source["family"] != "news"
                    and not (
                        len(source["external_id"]) == 64
                        and all(char in "0123456789abcdef" for char in source["external_id"])
                    )
                }
            ),
            "selected_sources": sources,
            "origin": "follow_up" if parent_id else origin,
            "known_facts": card.get("facts", []),
            "unknowns": card.get("unknowns", []),
            "evidence_ids": sorted(
                {str(f["evidence_id"]) for f in card.get("sources", []) if f.get("evidence_id")}
            ),
            "source_id": project.source_id,
            "before": json.loads(json.dumps(card, default=str)),
        }
        # Project/card semantic hash includes current evidence and buying-chain provenance.
        evidence_hash = fingerprint([card["input_hash"], project.identity_key])
        resolved = {
            row.category
            for row in prior
            if row.status == "RESOLVED"
            and row.context.get("policy_version") == POLICY_VERSION
            and row.context.get("selected_source_fingerprint")
            == routing_context(row.category, sources)["selected_source_fingerprint"]
            and row.receipt.get("post_evidence_fingerprint") == evidence_hash
            and row.retry_after
            and row.retry_after > now
        }
        if parent_id:
            assert parent is not None
            resolved.add(parent.category)
        for planned in plan_questions(card, resolved_categories=resolved):
            if len(active) >= 2 or today_count >= settings.autonomous_research_daily_questions:
                break
            category = planned["category"]
            queries = targeted_queries(context, category)
            routing = routing_context(category, sources)
            query_hash = fingerprint(
                [POLICY_VERSION, planned, queries, routing["selected_source_fingerprint"]]
            )
            if any(row.category == category for row in active):
                continue
            reusable = [
                row
                for row in prior
                if row.query_fingerprint == query_hash
                and evidence_hash
                in {row.evidence_fingerprint, row.receipt.get("post_evidence_fingerprint")}
                and row.retry_after
                and row.retry_after > now
                and _fresh_checked_result(row)
            ]
            unresolved_effect = any(
                row.receipt.get("inflight_url") or row.receipt.get("ambiguous_effects")
                for row in prior
            )
            if unresolved_effect:
                continue
            pending_retry = any(
                row.query_fingerprint == query_hash
                and row.evidence_fingerprint == evidence_hash
                and row.receipt.get("retry_class") == "BOUNDED_TRANSIENT"
                and row.retry_after
                and row.retry_after > now
                for row in prior
            )
            if pending_retry and not force:
                continue
            retry_index = max(
                (
                    int(row.context.get("retry_index", 0)) + 1
                    for row in prior
                    if row.query_fingerprint == query_hash
                    and row.evidence_fingerprint == evidence_hash
                    and row.receipt.get("retry_class") == "BOUNDED_TRANSIENT"
                ),
                default=0,
            )
            retry_exhausted = any(
                row.query_fingerprint == query_hash
                and row.evidence_fingerprint == evidence_hash
                and row.receipt.get("retry_class") == "RETRIES_EXHAUSTED"
                for row in prior
            )
            if (retry_index > len(RETRY_BACKOFF_HOURS) or retry_exhausted) and not force:
                continue
            if reusable and not force:
                continue
            # WATCH must first show a material change after its baseline receipt.
            # An initial WATCH can be investigated once; unchanged retries honor freshness.
            row = PursuitResearchQuestion(
                pursuit_id=pursuit.id,
                project_id=project.id,
                need_id=need.id,
                parent_id=parent_id,
                category=category,
                question=planned["question"],
                query_fingerprint=query_hash,
                evidence_fingerprint=evidence_hash,
                context={
                    **context,
                    **planned,
                    "queries": queries,
                    "query_routes": targeted_query_plan(context, category),
                    "force": force,
                    "retry_index": retry_index,
                    **routing,
                },
                budget={
                    **BUDGET,
                    "searches": settings.autonomous_research_max_searches,
                    "urls": settings.autonomous_research_max_urls,
                    "document_bytes": settings.autonomous_research_max_document_bytes,
                    "documents": settings.autonomous_research_max_documents,
                    "timeout_seconds": settings.autonomous_research_timeout_seconds,
                    "max_cost_usd": str(settings.autonomous_research_max_cost_usd),
                },
                receipt={
                    "source_checks": [],
                    "resulting_evidence_ids": [],
                    "reevaluation_status": "NOT_STARTED",
                },
                status="QUEUED",
                attempt_count=0,
            )
            session.add(row)
            session.flush()
            # Unlike the source-wide enqueue helper, each question owns its target.
            session.add(Job(source_id=project.source_id, kind="pursuit_question", target_id=row.id))
            rows.append(row)
            active.append(row)
            created.append(row)
            today_count += 1
            if parent_id:
                break
    return created


def _fresh_checked_result(row: PursuitResearchQuestion) -> bool:
    """Only a completed provider/source check suppresses unchanged research."""
    if row.status not in {"RESOLVED", "UNRESOLVED", "PARTIALLY_RESOLVED"}:
        return False
    if row.receipt.get("inflight_url") or row.receipt.get("ambiguous_effects"):
        return False
    checks = row.receipt.get("source_checks", [])
    routes = row.receipt.get("route_results", [])
    return any(
        check.get("disposition") in {"ACCEPTED", "REJECTED", "UNRESOLVED"} for check in checks
    ) or any(route.get("status") == "CHECKED" for route in routes)
