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

    from gridlens.api.app import (
        _commercial_current_triage_page,
        _commercial_triage_cards,
        opportunity_projection,
    )
    from gridlens.domain.commercial_triage import build_card
    from gridlens.intelligence.buying_chain import buying_chain_view
    from gridlens.persistence.models import PowerNeed, Project

    wanted = {str(need_id) for need_id in need_ids}
    today = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()
    found = {}
    chains: dict = {}
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
            session,
            buying_chain_results=chains,
            include_below_floor=True,
            include_operator_fact_refs=True,
            selected_need_ids={UUID(identity) for identity in wanted},
        )
        exact_items = {str(item["id"]): item for item in items if str(item["id"]) in wanted}
        for need_id, item in exact_items.items():
            card = build_card(item, chains.get(str(item["project_id"])), today)
            from gridlens.domain.opportunity_intelligence import assemble_card
            from gridlens.settings import settings

            card["intelligence_card"] = assemble_card(
                item,
                chains.get(str(item["project_id"]), {}),
                card,
                [],
                research_enabled=settings.autonomous_research_enabled,
            ).model_dump(mode="json")
            card["related_need_ids"] = [need_id]
            card["related_need_states"] = []
            found[need_id] = card
        missing = wanted - found.keys()
        if not missing:
            return found

    if grouped:
        # Plan remaining complete work groups through the same current-evidence
        # preflight as the shortlist. Never hydrate all evidence first or retry
        # an excluded group through an unguarded projection fallback.
        pending = set(missing)
        while pending:
            excluded = {
                need_id
                for diagnostic in session.info.get("commercial_planner_exclusions", {}).values()
                for need_id in diagnostic["need_ids"]
            }
            pending -= excluded
            if not pending:
                break
            grouped_cards, _total = _commercial_current_triage_page(
                session,
                50,
                tier=None,
                include_below_floor=True,
                requested_need_ids={UUID(identity) for identity in pending},
                isolate_resource_bounds=True,
            )
            before = len(pending)
            for card in grouped_cards:
                for related_id in card["related_need_ids"]:
                    if related_id in missing:
                        found[related_id] = card
                        pending.discard(related_id)
            newly_excluded = {
                need_id
                for diagnostic in session.info.get("commercial_planner_exclusions", {}).values()
                for need_id in diagnostic["need_ids"]
            }
            pending -= newly_excluded
            if len(pending) == before:
                break
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
        if project.region_status != "ELIGIBLE":
            continue
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
        prior_saved_card = prior.get("saved_card")
        prior_intelligence = (
            prior_saved_card.get("intelligence_card")
            if isinstance(prior_saved_card, dict)
            else None
        )
        current_intelligence = card.get("intelligence_card")
        if current_intelligence is None and prior_intelligence is not None:
            # An optional current projection may be omitted by callers. Keep its
            # last saved as-of value when writing another commercial snapshot.
            saved_card["intelligence_card"] = prior_intelligence
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
        intelligence_changed = bool(
            current_intelligence is not None
            and (
                prior_intelligence is None
                or prior_intelligence.get("input_fingerprint")
                != current_intelligence.get("input_fingerprint")
            )
        )
        changed = (
            prior.get("input_hash") != card["input_hash"]
            or prior.get("disposition") != card["disposition"]
            or intelligence_changed
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
