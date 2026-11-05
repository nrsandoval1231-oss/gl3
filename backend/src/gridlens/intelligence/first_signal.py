"""First-signal sample: when each source first observed each project (internal, read-only).

No new storage. ``Observation.first_seen_at`` is set once at insert and guarded against
rewrites (see ``persistence/models.py``); observations are never deleted, so that column is
the retained sample. This module reads it with the earliest evidence timestamps so lead time
against a later reference can be measured offline. It is not exposed in the product UI and
adds no workflow.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gridlens.persistence.models import Evidence, Observation, Project


def first_signal_sample(
    session: Session,
    *,
    source_ids: Iterable[str] | None = None,
    since: datetime | None = None,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    """One row per project: its source, first-seen time and earliest evidence dates."""
    earliest = (
        select(
            Evidence.observation_id.label("observation_id"),
            func.min(Evidence.observed_at).label("first_observed_at"),
            func.min(Evidence.event_date).label("first_event_date"),
            func.min(Evidence.published_at).label("first_published_at"),
        )
        .group_by(Evidence.observation_id)
        .subquery()
    )
    query = (
        select(Project, Observation, earliest)
        .join(
            Observation,
            (Observation.source_id == Project.source_id)
            & (Observation.external_id == Project.external_id),
        )
        .outerjoin(earliest, earliest.c.observation_id == Observation.id)
        .order_by(Observation.first_seen_at, Project.id)
        .limit(limit)
    )
    if source_ids is not None:
        query = query.where(Project.source_id.in_(list(source_ids)))
    if since is not None:
        query = query.where(Observation.first_seen_at >= since)
    rows = []
    for row in session.execute(query):
        project, observation = row[0], row[1]
        rows.append(
            {
                "project_id": str(project.id),
                "identity_key": project.identity_key,
                "source_id": project.source_id,
                "external_id": project.external_id,
                "first_seen_at": observation.first_seen_at,
                "first_evidence_observed_at": row.first_observed_at,
                "first_event_date": row.first_event_date,
                "first_published_at": row.first_published_at,
            }
        )
    return rows


def lead_time_days(first_seen_at: datetime, reference_at: datetime) -> float:
    """Days by which our first sighting precedes a later reference (negative: after it)."""
    return (reference_at - first_seen_at).total_seconds() / 86_400
