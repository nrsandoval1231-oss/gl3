"""Record when a stored record leaves (or returns to) a complete source snapshot.

Only sources declared ``snapshot_complete`` in the registry participate: each successful
run of those sources returns every row the publisher currently lists. A row that
disappears from such a listing (a pending permit that was issued, denied or withdrawn)
is a status change worth reviewing, not a deletion and not a cancellation. Evidence,
interpretations and needs are left untouched; the event marks the record for review.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    NeedObservation,
    Observation,
    PowerNeed,
)

ABSENT = "absent_from_source"
RETURNED = "returned_to_source"
PRESENCE_KINDS = (ABSENT, RETURNED)


def _latest_presence(session: Session, observation_ids: list[UUID]) -> dict[UUID, str]:
    latest: dict[UUID, str] = {}
    if not observation_ids:
        return latest
    rows = session.execute(
        select(ChangeEvent.observation_id, ChangeEvent.kind)
        .where(
            ChangeEvent.observation_id.in_(observation_ids),
            ChangeEvent.kind.in_(PRESENCE_KINDS),
        )
        .order_by(ChangeEvent.id)
    ).all()
    for observation_id, kind in rows:
        latest[observation_id] = kind
    return latest


def reconcile_snapshot(
    session: Session, source_id: str, present_external_ids: set[str]
) -> dict[str, int]:
    """Add one presence event per transition; replays of the same snapshot add nothing."""
    observations = session.scalars(
        select(Observation).where(Observation.source_id == source_id)
    ).all()
    latest = _latest_presence(session, [observation.id for observation in observations])
    counts = {"absent_from_snapshot": 0, "returned_to_snapshot": 0}
    for observation in observations:
        present = observation.external_id in present_external_ids
        current = latest.get(observation.id)
        if not present and current != ABSENT:
            kind = ABSENT
        elif present and current == ABSENT:
            kind = RETURNED
        else:
            continue
        evidence = session.scalar(
            select(Evidence)
            .where(Evidence.observation_id == observation.id)
            .order_by(Evidence.observed_at.desc())
            .limit(1)
        )
        project_id = session.scalar(
            select(PowerNeed.project_id)
            .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
            .where(NeedObservation.observation_id == observation.id)
            .limit(1)
        )
        transitions = len(
            session.scalars(
                select(ChangeEvent.id).where(
                    ChangeEvent.observation_id == observation.id,
                    ChangeEvent.kind.in_(PRESENCE_KINDS),
                )
            ).all()
        )
        session.add(
            ChangeEvent(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                kind=kind,
                project_id=project_id,
                evidence_id=evidence.id if evidence else None,
                field_name="source_listing",
                prior_state={"listed": kind == RETURNED},
                new_state={"listed": kind == RETURNED, "source_id": source_id},
                material=evidence is not None,
                replay_key=hashlib.sha256(
                    f"{observation.id}|{kind}|{transitions}".encode()
                ).hexdigest(),
            )
        )
        counts["absent_from_snapshot" if kind == ABSENT else "returned_to_snapshot"] += 1
    session.flush()
    return counts


def absent_need_ids(session: Session, need_ids: list[Any]) -> set[Any]:
    """Needs whose supporting observations have all left their source's current listing."""
    if not need_ids:
        return set()
    links = session.execute(
        select(NeedObservation.need_id, NeedObservation.observation_id).where(
            NeedObservation.need_id.in_(need_ids)
        )
    ).all()
    latest = _latest_presence(session, list({observation_id for _, observation_id in links}))
    by_need: dict[Any, list[bool]] = {}
    for need_id, observation_id in links:
        by_need.setdefault(need_id, []).append(latest.get(observation_id) == ABSENT)
    return {need_id for need_id, flags in by_need.items() if flags and all(flags)}
