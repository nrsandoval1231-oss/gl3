"""Database glue for the NMED application-document stage.

The stage (``adapters/nmed_application_documents.py``) never touches the database. This module
reads the retained per-document state from the newest evidence that carries one and keeps the
stage's check index (validators, retry attempts, ``not_before``) in source health, so a re-check
never changes an evidence hash. Same health choice as the TCEQ and OK DEQ stages: real failures
make the job ``partial`` and are listed in ``rejected_records`` while ``collection_status`` is
untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.nmed_application_documents import (
    HEALTH_KEY,
    MAX_INDEX_URLS,
    STATE_KEY,
    document_url_ok,
)
from gridlens.persistence.models import Evidence, Observation, Source


def load_prior_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Latest retained state per document URL, from the newest evidence that has one."""
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
        url = found.get("url") if isinstance(found, dict) else None
        if isinstance(found, dict) and document_url_ok(url):
            states[str(url)] = found
    return states


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
                for k, v in list(urls.items())[:MAX_INDEX_URLS]
                if isinstance(v, dict) and document_url_ok(k)
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
