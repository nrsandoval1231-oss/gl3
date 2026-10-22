"""Bounded assembly from persisted canonical inputs; no acquisition or provider calls."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select

from gridlens.domain.commercial_triage import build_card
from gridlens.domain.opportunity_intelligence import assemble_card
from gridlens.domain.pursuit_research import fingerprint
from gridlens.persistence.models import Project, PursuitResearchQuestion
from gridlens.settings import settings


def attach_cards(session, items: list[dict], chains: dict) -> None:
    """Attach in place, reusing canonical bulk chains and one bounded question read."""
    from gridlens.api.app import chicago_today

    if not items:
        return
    if len(items) > 50:
        raise ValueError("Intelligence card batch exceeds 50 power needs")
    ids = [UUID(str(item["id"])) for item in items]
    ranked = (
        select(
            PursuitResearchQuestion.id.label("id"),
            func.row_number()
            .over(
                partition_by=PursuitResearchQuestion.need_id,
                order_by=(
                    PursuitResearchQuestion.created_at.desc(),
                    PursuitResearchQuestion.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(PursuitResearchQuestion.need_id.in_(ids))
        .subquery()
    )
    questions = defaultdict(list)
    for row in session.scalars(
        select(PursuitResearchQuestion)
        .join(ranked, ranked.c.id == PursuitResearchQuestion.id)
        .where(ranked.c.position <= 30)
        .order_by(ranked.c.position)
    ):
        questions[str(row.need_id)].append(
            {
                "id": str(row.id),
                "category": row.category,
                "status": row.status,
                "created_at": row.created_at,
                "completed_at": row.completed_at,
                "evidence_fingerprint": row.evidence_fingerprint,
                "post_evidence_fingerprint": row.receipt.get("post_evidence_fingerprint"),
            }
        )
    identities = dict(
        session.execute(
            select(Project.id, Project.identity_key).where(
                Project.id.in_({UUID(str(item["project_id"])) for item in items})
            )
        ).all()
    )
    from gridlens.intelligence.customer_accounts import associated_accounts_for_projects

    associated_accounts = associated_accounts_for_projects(
        session, {UUID(str(item["project_id"])) for item in items}
    )
    for item in items:
        item["associated_account"] = associated_accounts.get(UUID(str(item["project_id"])))
        chain = chains.get(str(item["project_id"]), {})
        commercial = build_card(item, chain, chicago_today())
        expected = fingerprint(
            [commercial["input_hash"], identities[UUID(str(item["project_id"]))]]
        )
        current_questions = [
            {
                **q,
                "status": q["status"]
                if expected in {q["evidence_fingerprint"], q.get("post_evidence_fingerprint")}
                else "STALE_INPUT",
            }
            for q in questions[str(item["id"])]
        ]
        item["intelligence_card"] = assemble_card(
            item,
            chain,
            commercial,
            current_questions,
            research_enabled=settings.autonomous_research_enabled,
        ).model_dump(mode="json")
