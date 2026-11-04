"""Database glue for the Oklahoma DEQ permit-document stage.

The stage (``adapters/ok_deq_documents.py``) never touches the database. This module reads the
retained per-permit state from the newest evidence that has one, keeps the stage's key index
(change-detection validators, retry attempts, the probe frontier) in source health so it never
changes evidence hashes, and reuses the TCEQ glue's job-count merge. The health choice is the
same as the TCEQ stage: real failures make the job ``partial`` and are listed in
``rejected_records``, but ``collection_status`` is untouched, because that status drives the
listing's rate-limit cooldown and an optional stage must not move it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.ok_deq_documents import (
    HEALTH_KEY,
    MAX_INDEX_KEYS,
    STATE_KEY,
)
from gridlens.persistence.models import Evidence, Observation, Source


def load_prior_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Latest retained state per permit join key, from the newest evidence that has one."""
    rows = session.execute(
        select(Observation.external_id, Evidence.provenance)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(Observation.source_id == source_id, Evidence.provenance.op("?")(STATE_KEY))
        .distinct(Observation.external_id)
        .order_by(Observation.external_id, Evidence.observed_at.desc(), Evidence.id)
    ).all()
    states: dict[str, dict[str, Any]] = {}
    for _external_id, provenance in rows:
        found = provenance.get(STATE_KEY) if isinstance(provenance, dict) else None
        norm = found.get("permit_norm") if isinstance(found, dict) else None
        if isinstance(found, dict) and isinstance(norm, str) and norm:
            states[norm] = found
    return states


def load_index(session: Session, source_id: str) -> dict[str, Any]:
    source = session.get(Source, source_id)
    stored = (source.health or {}).get(HEALTH_KEY) if source is not None else None
    if not isinstance(stored, dict):
        return {}
    keys = stored.get("keys")
    return {
        "frontier": stored.get("frontier") if type(stored.get("frontier")) is int else None,
        "keys": (
            {str(k): dict(v) for k, v in list(keys.items())[:MAX_INDEX_KEYS] if isinstance(v, dict)}
            if isinstance(keys, dict)
            else {}
        ),
    }


def save_index(session: Session, source_id: str, index: dict[str, Any]) -> None:
    source = session.get(Source, source_id)
    if source is not None:
        source.health = {**(source.health or {}), HEALTH_KEY: index}
