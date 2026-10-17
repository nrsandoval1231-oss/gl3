"""Narrow read-only evidence export. Operator clearance is a private local file."""

import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from gridlens.domain.editorial import evaluate_feed
from gridlens.ingestion.registry import load_registry
from gridlens.persistence.models import Evidence, Observation, Source


def export_editorial(session, review_path: Path):
    if review_path.stat().st_size > 1_000_000:
        raise ValueError("Editorial review file exceeds 1 MB")
    document = json.loads(review_path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"version", "reviews", "recentIds"}
        or document["version"] != "2g-editorial-review/1"
        or not isinstance(document["reviews"], list)
        or len(document["reviews"]) > 200
        or not isinstance(document["recentIds"], list)
        or not all(isinstance(x, str) for x in document["recentIds"])
    ):
        raise ValueError("Invalid editorial review file")
    ids = []
    for review in document["reviews"]:
        if not isinstance(review, dict) or not isinstance(review.get("evidenceId"), str):
            continue
        try:
            ids.append(UUID(review["evidenceId"]))
        except (ValueError, TypeError, KeyError):
            continue
    records = {}
    if ids:
        newer = aliased(Evidence)
        rows = session.execute(
            select(Observation, Evidence, Source)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .join(Source, Source.id == Observation.source_id)
            .where(
                Evidence.id.in_(ids),
                ~exists().where(
                    newer.observation_id == Evidence.observation_id,
                    newer.id != Evidence.id,
                    newer.observed_at >= Evidence.observed_at,
                ),
            )
        ).all()
        records = {str(e.id): (o, e, s) for o, e, s in rows}
    # Public registry endpoints only; private/manual sources and off-host
    # evidence need an explicit policy change, never automatic URL following.
    hosts = {
        s["id"]: {urlsplit(s["endpoint"]).hostname}
        for s in load_registry()
        if not s.get("credential_reference")
        and s.get("retention")
        and s["endpoint"].startswith("https://")
    }
    return evaluate_feed(
        document["reviews"], records, recent_ids=document["recentIds"], allowed_hosts=hosts
    )
