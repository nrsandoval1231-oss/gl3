"""Export a deterministic, read-only snapshot of retained GridLens records."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.persistence.database import SessionLocal, engine
from gridlens.persistence.models import (
    Evidence,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)


def build_export(session: Session) -> dict[str, Any]:
    """Read retained observations and their evidence/admission links."""
    observations = sorted(
        session.scalars(select(Observation).order_by(Observation.id)).all(),
        key=lambda item: str(item.id),
    )
    output: list[dict[str, Any]] = []
    for observation in observations:
        source = session.get(Source, observation.source_id)
        retained_evidence = session.scalars(
            select(Evidence)
            .where(Evidence.observation_id == observation.id)
            .order_by(Evidence.content_hash, Evidence.id)
        ).all()
        retained_evidence = sorted(
            retained_evidence, key=lambda item: (item.content_hash, str(item.id))
        )
        links = session.execute(
            select(NeedObservation, PowerNeed, Project)
            .join(PowerNeed, NeedObservation.need_id == PowerNeed.id)
            .join(Project, PowerNeed.project_id == Project.id)
            .where(NeedObservation.observation_id == observation.id)
            .order_by(PowerNeed.id)
        ).all()
        output.append(
            {
                "observation_id": str(observation.id),
                "source": {
                    "id": observation.source_id,
                    "publisher": source.publisher if source else None,
                    "family": source.family if source else None,
                    "geography": source.geography if source else None,
                    "industries": source.industries if source else [],
                },
                "external_id": observation.external_id,
                "title": observation.title,
                "abstract": observation.abstract,
                "published_at": observation.published_at.isoformat(),
                "url": observation.url,
                "content_hash": observation.content_hash,
                "evidence": [
                    {
                        "evidence_id": str(item.id),
                        "content_hash": item.content_hash,
                        "title": item.title,
                        "abstract": item.abstract,
                        "url": item.url,
                        "published_at": item.published_at.isoformat(),
                        "observed_at": item.observed_at.isoformat(),
                        "extraction_location": item.extraction_location,
                        "event_date": item.event_date.isoformat() if item.event_date else None,
                    }
                    for item in retained_evidence
                ],
                "admissions": [
                    {
                        "need_id": str(need.id),
                        "project_id": str(project.id),
                        "project_name": project.name,
                        "location": project.location,
                        "tier": need.tier,
                        "active": need.active,
                        "rationale": need.rationale,
                        "activity_key": need.activity_key,
                    }
                    for _, need, project in links
                ],
            }
        )
    return {
        "schema_version": 1,
        "scope": {
            "record_set": (
                "all persisted observations, retained evidence versions, and linked needs"
            ),
            "ordering": "observation UUID; evidence content hash then UUID; need UUID",
            "limits": [
                "A stored admission is system state, not a verified quality label.",
                "Unlinked observations remain present with an empty admissions list.",
                "No source content beyond the persisted title and abstract is fetched.",
            ],
        },
        "observations": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(".artifacts/local-review-sample.json")
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SessionLocal() as session:
            data = build_export(session)
    finally:
        engine.dispose()
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_counts = Counter(item["source"]["id"] for item in data["observations"])
    print(f"Wrote {len(data['observations'])} observations to {output}")
    print(f"Source counts: {dict(sorted(source_counts.items()))}")


if __name__ == "__main__":
    main()
