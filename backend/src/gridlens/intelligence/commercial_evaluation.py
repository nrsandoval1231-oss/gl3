"""Shared persistence of existing deterministic commercial evaluation receipts."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.domain.commercial_triage import surfaced_on as commercial_surfaced_on
from gridlens.domain.pursuits import CommercialTriageCard
from gridlens.persistence.models import Pursuit


def evaluate_targets(
    session: Session,
    need_ids,
    *,
    cohort: list[dict] | None = None,
    grouped: bool = False,
) -> dict:
    """Evaluate exact saved targets by default; group only for planner discovery."""
    from uuid import UUID

    from gridlens.api.app import _commercial_triage_cards, opportunity_projection
    from gridlens.domain.commercial_triage import build_card, group_cards
    from gridlens.intelligence.buying_chain import buying_chain_view
    from gridlens.persistence.models import PowerNeed, Project

    wanted = {str(need_id) for need_id in need_ids}
    today = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()
    found = {}
    if grouped:
        cohort = _commercial_triage_cards(session, 50) if cohort is None else cohort
        for card in cohort:
            for related_id in card.get("related_need_ids", [card["id"]]):
                if related_id in wanted:
                    found[related_id] = card
        missing = wanted - found.keys()
        if not missing:
            return found
    else:
        items = opportunity_projection(
            session, include_below_floor=True, include_operator_fact_refs=True,
            selected_need_ids={UUID(identity) for identity in wanted},
        )
        exact_items = {str(item["id"]): item for item in items if str(item["id"]) in wanted}
        chains = {
            str(project_id): buying_chain_view(session, project_id)
            for project_id in sorted(
                {item["project_id"] for item in exact_items.values()}, key=str
            )
        }
        for need_id, item in exact_items.items():
            card = build_card(item, chains.get(str(item["project_id"])), today)
            card["related_need_ids"] = [need_id]
            card["related_need_states"] = []
            found[need_id] = card
        missing = wanted - found.keys()
        if not missing:
            return found

    if grouped:
        items = opportunity_projection(
            session, include_below_floor=True, include_operator_fact_refs=True
        )
        # Resolve exact work groups across the full projection before doing the more
        # expensive buying-chain reads. Group identity depends on source/document/site
        # evidence; final cards are rebuilt with current chain data for selected groups.
        identity_groups = group_cards(items, {}, today)
        requested_groups = [
            card
            for card in identity_groups
            if missing.intersection(card["related_need_ids"])
        ]
        requested_ids = {
            need_id for card in requested_groups for need_id in card["related_need_ids"]
        }
        selected_items = [item for item in items if str(item["id"]) in requested_ids]
        selected_projects = sorted({item["project_id"] for item in selected_items}, key=str)
        chains = {
            str(project_id): buying_chain_view(session, project_id)
            for project_id in selected_projects
        }
        grouped_cards = group_cards(selected_items, chains, today)
        for card in grouped_cards:
            for related_id in card["related_need_ids"]:
                if related_id in missing:
                    found[related_id] = card
        missing = wanted - found.keys()
        if not missing:
            return found

    # Preserve saved inactive targets, but never turn an unsupported active need
    # into a planning card merely because its ID appeared in a saved workspace.
    rows = session.execute(
        select(PowerNeed, Project)
        .join(Project)
        .where(PowerNeed.id.in_([UUID(identity) for identity in missing]))
    )
    for need, project in rows:
        if need.active:
            continue  # Unsupported is unknown, never proof of cancellation.
        item = {
            "id": need.id,
            "project_id": project.id,
            "name": project.name,
            "location": project.location,
            "tier": need.tier,
            "activity": need.activity_key,
            "asset_type": project.asset_type,
            "canonical_inactive": True,
            "evidence": [],
        }
        if str(project.id) not in chains:
            chains[str(project.id)] = buying_chain_view(session, project.id)
        card = build_card(item, chains.get(str(project.id)), today)
        card["related_need_ids"] = [str(need.id)]
        card["related_need_states"] = []
        found[str(need.id)] = card
    return found


def evaluate_target(session: Session, need_id) -> dict | None:
    """Reevaluate the exact target after closure, promotion or grouping changes."""
    return evaluate_targets(session, [need_id]).get(str(need_id))


def save_evaluations(session: Session, cards: list[dict], *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    saved_at = now.isoformat()
    for card in cards:
        identity = "commercial-need:" + card["id"]
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 29))"),
            {"identity": identity},
        )
        row = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == identity).with_for_update()
        )
        if row is None:
            row = Pursuit(
                identity_key=identity,
                project_id=card["project_id"],
                project_ids=[card["project_id"]],
                snapshot={},
            )
            session.add(row)
            session.flush()
        row.project_ids = card["related_project_ids"]
        card["pursuit_id"] = row.id
        saved_card = CommercialTriageCard.model_validate(card).model_dump(mode="json")
        if not card.get("operator_fact_refs"):
            saved_card.pop("operator_fact_refs", None)
        saved_card["notes"] = []
        snapshot = dict(row.snapshot or {})
        prior = snapshot.get("commercial_triage", {})
        versions = (
            list(prior.get("versions", [])) if isinstance(prior.get("versions"), list) else []
        )
        if not versions and any(
            prior.get(key) is not None
            for key in ("input_hash", "disposition", "saved_at", "saved_card")
        ):
            prior_card = prior.get("saved_card")
            if isinstance(prior_card, dict):
                prior_card = {**prior_card, "pursuit_id": str(row.id), "notes": []}
            versions.append(
                {
                    "version": 1,
                    "disposition": prior.get("disposition")
                    or (prior_card or {}).get("disposition")
                    or "UNKNOWN",
                    "evaluated_on": prior.get("evaluated_on"),
                    "evaluated_at": prior.get("saved_at"),
                    "input_hash": prior.get("input_hash") or (prior_card or {}).get("input_hash"),
                    "snapshot_status": "saved_as_of" if prior_card else "metadata_only",
                    "live_status": "not_rechecked",
                    "saved_card": prior_card,
                }
            )
        changed = (
            prior.get("input_hash") != card["input_hash"]
            or prior.get("disposition") != card["disposition"]
        )
        if changed:
            versions.append(
                {
                    "version": len(versions) + 1,
                    "disposition": card["disposition"],
                    "evaluated_on": today,
                    "evaluated_at": saved_at,
                    "input_hash": card["input_hash"],
                    "operator_fact_provenance": "recorded",
                    "snapshot_status": "saved_as_of",
                    "live_status": "not_rechecked",
                    "saved_card": saved_card,
                }
            )
        elif not versions:
            # Defensive: a malformed legacy receipt should not create duplicate versions.
            versions.append(
                {
                    "version": 1,
                    "disposition": prior.get("disposition") or "UNKNOWN",
                    "evaluated_on": prior.get("evaluated_on"),
                    "evaluated_at": prior.get("saved_at"),
                    "input_hash": prior.get("input_hash"),
                    "snapshot_status": "metadata_only",
                    "live_status": "not_rechecked",
                    "saved_card": None,
                }
            )
        if changed:
            snapshot["commercial_triage"] = {
                "need_id": card["id"],
                "input_hash": card["input_hash"],
                "disposition": card["disposition"],
                "evaluated_on": today,
                "saved_at": saved_at,
                "saved_card": saved_card,
                "surfaced_on": commercial_surfaced_on(prior, card, today),
                "versions": versions,
            }
        row.snapshot = snapshot
