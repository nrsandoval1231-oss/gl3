"""Deterministic executable source routes for one existing canonical need."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.pursuit_research import FRESHNESS_HOURS, ROUTES, fingerprint
from gridlens.ingestion.adapters.pursuit_acquisition import SUPPORTED_SOURCES
from gridlens.ingestion.registry import load_registry
from gridlens.persistence.models import NeedObservation, Observation, Source

# Research freshness is intentionally distinct from a collector's poll cadence.
SOURCE_FRESHNESS_HOURS = {
    "construction-permits": 72,
    "news": 24,
    "oil-gas-regulatory-applications": 24,
    "municipal-planning-news": 72,
    "utility-filings": 24,
}


def selected_sources(session: Session, need_id: UUID) -> list[dict]:
    definitions = {source["id"]: source for source in load_registry()}
    rows = session.execute(
        select(Source, Observation)
        .join(Observation, Observation.source_id == Source.id)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .where(
            NeedObservation.need_id == need_id,
        )
        .order_by(Source.id, Observation.external_id)
    )
    return [
        {
            "source_id": source.id,
            "enabled": source.enabled,
            # Individually retained research pages are deliberately not RSS polling feeds.
            "targeted_only": source.id.startswith("research-public-")
            and source.family == "news"
            and source.retrieval_method == "publisher-rss",
            "external_id": observation.external_id,
            "url": observation.url,
            "family": source.family,
            "retrieval_method": source.retrieval_method,
            "definition": definitions.get(
                source.id,
                {
                    "id": source.id,
                    "endpoint": source.endpoint,
                    "family": source.family,
                    "retrieval_method": source.retrieval_method,
                    "publisher": source.publisher,
                    "cadence_hours": source.cadence_hours,
                },
            ),
        }
        for source, observation in rows
    ]


def route_plan(category: str, sources: list[dict]) -> list[dict]:
    """Every acquisition is executable or explicitly unavailable, never implied."""
    routes: list[dict] = [{"kind": "retained", "family": "canonical-evidence", "status": "PLANNED"}]
    for source in sorted(
        sources,
        key=lambda item: (
            item["source_id"] not in SUPPORTED_SOURCES,
            item["source_id"],
            item["external_id"],
        ),
    ):
        if not source.get("enabled", True) and not source.get("targeted_only", False):
            kind, status, reason = (
                "registered",
                "UNAVAILABLE",
                "Source is disabled for acquisition.",
            )
        elif source["source_id"] in SUPPORTED_SOURCES:
            kind, status, reason = "registered", "PLANNED", None
        elif source["family"] == "news" and source["retrieval_method"] == "publisher-rss":
            kind, status, reason = "public", "PLANNED", None
        else:
            kind, status = "registered", "UNAVAILABLE"
            reason = (
                "Registered RRC download requires a form submission; research prohibits forms."
                if source["source_id"].startswith("texas-rrc")
                else "No bounded exact-record adapter for this registered source."
            )
        routes.append(
            {
                "kind": kind,
                "family": source["family"],
                "status": status,
                "source_id": source["source_id"],
                "external_id": source["external_id"],
                "url": source["url"],
                "reason": reason,
            }
        )
    routes.extend(
        {"kind": "discovery", "family": family, "status": "PLANNED"} for family in ROUTES[category]
    )
    return routes


def routing_context(category: str, sources: list[dict]) -> dict:
    windows = [SOURCE_FRESHNESS_HOURS.get(source["family"], 24) for source in sources]
    return {
        "route_plan": route_plan(category, sources),
        "selected_source_fingerprint": fingerprint(sources),
        "freshness_hours": min([FRESHNESS_HOURS[category], *windows]),
    }
