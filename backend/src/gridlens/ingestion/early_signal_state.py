"""Database glue for the early-signal sources (ERCOT planning documents, PUCT CCN dockets).

The adapters never touch the database. This module reads the retained per-document state from the
newest evidence that carries one (``Evidence.provenance["early_signal"]`` with ``stateful`` true)
and keeps the stage's check index (``not_before``, retry attempts, validators) in source health, so
a re-check never changes an evidence hash. Same health choice as the TCEQ, OK DEQ and NMED stages:
real failures make the job ``partial`` and are listed in ``rejected_records``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.early_signal_link import peers_from_states
from gridlens.ingestion.adapters.early_signal_stage import HEALTH_KEY, MAX_INDEX_ENTRIES, STATE_KEY
from gridlens.persistence.models import Evidence, Observation, Source

RPG_SOURCE_ID = "texas-ercot-rpg-projects"


def _states(session: Session, source_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Observation.external_id, Evidence.provenance)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(
            Observation.source_id == source_id,
            Evidence.provenance[STATE_KEY]["stateful"].astext == "true",
        )
        .distinct(Observation.external_id)
        .order_by(Observation.external_id, Evidence.observed_at.desc(), Evidence.id)
    ).all()
    found: list[dict[str, Any]] = []
    for _external_id, provenance in rows:
        state = provenance.get(STATE_KEY) if isinstance(provenance, dict) else None
        if isinstance(state, dict) and isinstance(state.get("key"), str):
            found.append(state)
    return found


def load_prior_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Latest retained state per document key (URL for ERCOT, control number for PUCT)."""
    return {str(state["key"]): state for state in _states(session, source_id)}


def load_peers(session: Session) -> list[dict[str, Any]]:
    """RPG project summaries (substations and counties with evidence) held for linking."""
    return peers_from_states(_states(session, RPG_SOURCE_ID))


def load_index(session: Session, source_id: str) -> dict[str, Any]:
    source = session.get(Source, source_id)
    stored = (source.health or {}).get(HEALTH_KEY) if source is not None else None
    if not isinstance(stored, dict):
        return {}
    urls = stored.get("urls")
    result: dict[str, Any] = {
        "urls": (
            {
                str(k): dict(v)
                for k, v in list(urls.items())[:MAX_INDEX_ENTRIES]
                if isinstance(v, dict) and isinstance(k, str) and len(k) <= 700
            }
            if isinstance(urls, dict)
            else {}
        )
    }
    if isinstance(stored.get("not_before"), str):
        result["not_before"] = stored["not_before"]
    return result


def save_index(session: Session, source_id: str, index: dict[str, Any]) -> None:
    source = session.get(Source, source_id)
    if source is not None:
        source.health = {**(source.health or {}), HEALTH_KEY: index}
