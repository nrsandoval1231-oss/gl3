"""Semantic current-state snapshots and idempotent material project transitions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.domain.buying_chain import ROLE_MAX_AGE_DAYS
from gridlens.intelligence.buying_chain import (
    _retained_evidence_current_for_project,
    buying_chain_view,
)
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported
from gridlens.intelligence.project_state import _accepted_need_evidence
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    ChangeEvent,
    Evidence,
    Interpretation,
    LifecycleEvent,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectMaterialState,
)

MATERIAL_FIELDS = ("phase", "contractor", "utility_timing", "power_need", "buyer")


def lock_project(session: Session, project_id: UUID) -> None:
    # Establish one lock order for state transitions: project row, then
    # transaction advisory lock, then material-state/need rows.
    session.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:project_id, 0))"),
        {"project_id": str(project_id)},
    )


def material_state(session: Session, project_id: UUID, *, now: datetime | None = None) -> dict:
    project = session.get(Project, project_id)
    need_claims = _accepted_need_evidence(session, project) if project is not None else {}
    needs = session.scalars(
        select(PowerNeed).where(PowerNeed.project_id == project_id).order_by(PowerNeed.activity_key)
    ).all()
    lifecycle = session.get(ProjectLifecycle, project_id)
    events = session.scalars(
        select(LifecycleEvent)
        .where(LifecycleEvent.project_id == project_id)
        .order_by(LifecycleEvent.occurred_on, LifecycleEvent.event_type, LifecycleEvent.id)
    ).all()
    accepted_events = []
    for event in events:
        evidence = session.get(Evidence, event.evidence_id)
        interpretation = (
            session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == evidence.observation_id
                )
            )
            if evidence
            else None
        )
        if (
            evidence
            and project
            and lifecycle_event_supported(event.event_type, evidence, interpretation, project)
        ):
            accepted_events.append(event)
    chain = buying_chain_view(session, project_id, now=now or datetime.now(UTC))
    people = [
        {
            key: item.get(key)
            for key in (
                "organization",
                "person_name",
                "title",
                "category",
                "organization_relationship",
                "person_project_relationship",
            )
        }
        for item in chain["candidates"]
        if not item.get("stale")
    ]
    people.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    power_rows = []
    for need in needs:
        if not need.active:
            continue
        row = {
            "activity": need.activity_key,
            "active": need.active,
            "tier": need.tier,
            "required_mw": need.required_mw,
            "start_window": need.start_window,
            "duration": need.duration,
            "supply": need.supply,
        }
        conflicts = {}
        for field in ("tier", "mw", "timing", "duration", "supply"):
            distinct = []
            for value, _evidence in need_claims[need.id][field]:
                if value not in distinct:
                    distinct.append(value)
            if len(distinct) > 1:
                conflicts[field] = sorted(
                    distinct, key=lambda value: json.dumps(value, default=str)
                )
        if conflicts:
            row["conflicts"] = conflicts
        power_rows.append(row)
    return {
        "phase": lifecycle.current_state if lifecycle else None,
        "utility_timing": sorted(
            {
                str(e.occurred_on)
                for e in accepted_events
                if e.occurred_on and ("utility" in e.event_type or "energiz" in e.event_type)
            }
        ),
        "power_need": power_rows,
        "contractor": [
            p
            for p in people
            if p.get("category")
            in {"contractor", "electrical_contractor", "epc", "general_contractor"}
        ],
        "buyer": people,
    }


def seed_material_state(session: Session, project: Project) -> ProjectMaterialState:
    lock_project(session, project.id)
    row = session.scalar(
        select(ProjectMaterialState)
        .where(ProjectMaterialState.project_id == project.id)
        .with_for_update()
    )
    if row is None:
        row = ProjectMaterialState(
            project_id=project.id, state=material_state(session, project.id), revision=0
        )
        session.add(row)
        session.flush()
    else:
        # A persisted pre-R7 row has no conflict metadata. Capture the actual
        # pre-action claims under the project lock, then preserve the stored
        # selected values so only this metadata is quietly normalized.
        current_by_activity = {
            item["activity"]: item
            for item in material_state(session, project.id)["power_need"]
        }
        prior_needs = row.state.get("power_need", [])
        normalized = []
        for prior in prior_needs:
            item = dict(prior)
            current = current_by_activity.get(item.get("activity"), {})
            if current.get("conflicts"):
                item["conflicts"] = current["conflicts"]
            else:
                item.pop("conflicts", None)
            normalized.append(item)
        if normalized != prior_needs:
            row.state = {**row.state, "power_need": normalized}
            session.flush()
    return row


def _freshness_expired_rows(
    session: Session, project_id: UUID, field: str, before: list, *, now: datetime
) -> Counter[tuple]:
    """Identify prior semantic rows excluded solely by role-evidence age."""
    contractor_categories = {"contractor", "electrical_contractor", "epc", "general_contractor"}
    fields = (
        "organization",
        "person_name",
        "title",
        "category",
        "organization_relationship",
        "person_project_relationship",
    )

    def key(row: dict) -> tuple:
        return tuple(row.get(name) for name in fields)

    all_sources = session.scalars(
        select(BuyingChainEvidence).where(BuyingChainEvidence.project_id == project_id)
    ).all()
    by_id = {str(source.id): source for source in all_sources}
    newest_by_url: dict[str, BuyingChainEvidence] = {}
    for source in sorted(
        all_sources,
        key=lambda item: (item.last_seen_at, item.retained_evidence_id is None),
        reverse=True,
    ):
        newest_by_url.setdefault(source.url, source)
    candidates = buying_chain_view(session, project_id, now=now)["candidates"]
    expired: Counter[tuple] = Counter()
    role_supports = {"organization_person_role", "person_project_assignment"}
    for candidate in candidates:
        if field == "contractor" and candidate.get("category") not in contractor_categories:
            continue
        claim = session.get(BuyingChainClaim, candidate["id"])
        if claim is None:
            continue
        row_key = key(
            {
                "organization": claim.organization,
                "person_name": claim.person_name,
                "title": claim.title,
                "category": claim.category,
                "organization_relationship": claim.organization_relationship,
                "person_project_relationship": claim.person_project_relationship,
            }
        )
        if row_key not in {key(row) for row in before if isinstance(row, dict)}:
            continue
        age_expired = False
        stale_for_another_reason = False
        for citation in claim.citations:
            cited_source = by_id.get(citation["evidence_id"])
            if cited_source is None or citation["quote"] not in cited_source.excerpt:
                stale_for_another_reason = True
                break
            newest = newest_by_url[cited_source.url]
            if newest.id != cited_source.id and citation["quote"] not in newest.excerpt:
                stale_for_another_reason = True
                break
            if cited_source.retained_evidence_id:
                retained = session.get(Evidence, cited_source.retained_evidence_id)
                project = session.get(Project, project_id)
                if (
                    retained is None
                    or project is None
                    or not _retained_evidence_current_for_project(session, project, retained)
                ):
                    stale_for_another_reason = True
                    break
            age_basis = cited_source.published_at or cited_source.last_seen_at.date()
            age_expired = age_expired or (
                citation["supports"] in role_supports
                and (now.date() - age_basis).days > ROLE_MAX_AGE_DAYS
            )
        if age_expired and not stale_for_another_reason:
            expired[row_key] += 1

    remaining = Counter(key(row) for row in before if isinstance(row, dict))
    return expired & remaining


def record_material_diff(
    session: Session,
    project: Project,
    evidence: Evidence,
    previous: ProjectMaterialState,
    buying_evidence: dict[str, BuyingChainEvidence] | None = None,
) -> list[ChangeEvent]:
    """Compare the actual persisted old state with current state; metadata is excluded."""
    now = datetime.now(UTC)
    current = material_state(session, project.id, now=now)
    created: list[ChangeEvent] = []
    for field in MATERIAL_FIELDS:
        before, after = previous.state.get(field), current.get(field)
        if before == after:
            continue
        comparison_before = before
        if field in {"contractor", "buyer"} and isinstance(before, list):
            expired = _freshness_expired_rows(session, project.id, field, before, now=now)
            if expired:
                comparison_before = []
                for row in before:
                    if isinstance(row, dict):
                        row_key = tuple(
                            row.get(name)
                            for name in (
                                "organization",
                                "person_name",
                                "title",
                                "category",
                                "organization_relationship",
                                "person_project_relationship",
                            )
                        )
                    else:
                        row_key = ()
                    if isinstance(row, dict) and expired[row_key] > 0:
                        expired[row_key] -= 1
                    else:
                        comparison_before.append(row)
        before = comparison_before
        if before == after:
            continue
        field_support = (buying_evidence or {}).get(field)
        if (
            buying_evidence is not None
            and field in {"contractor", "buyer"}
            and (field_support is None)
        ):
            # Enrichment can age a role out of the current projection without
            # finding new support. Persist UNKNOWN/current state quietly; the
            # permit Evidence passed for project context did not cause that change.
            continue
        # Revision is the serialized predecessor identity. It deliberately
        # permits A -> B -> A -> B even when one immutable Evidence version is
        # the support for more than one later correction.
        revision = previous.revision + 1
        digest = hashlib.sha256(
            json.dumps(
                {
                    "project": str(project.id),
                    "revision": revision,
                    "field": field,
                    "before": before,
                    "after": after,
                    "evidence": str(evidence.id),
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if session.scalar(select(ChangeEvent.id).where(ChangeEvent.replay_key == digest)):
            continue
        previous.revision = revision
        event = ChangeEvent(
            observation_id=evidence.observation_id,
            content_hash=evidence.content_hash,
            kind=f"{field}_changed",
            project_id=project.id,
            evidence_id=None if field_support else evidence.id,
            buying_chain_evidence_id=field_support.id if field_support else None,
            field_name=field,
            prior_state={"value": before},
            new_state={"value": after},
            material=True,
            source_date=(
                field_support.published_at
                if field_support
                else evidence.event_date or evidence.published_at
            ),
            replay_key=digest,
        )
        session.add(event)
        created.append(event)
    previous.state = current
    session.flush()
    return created
