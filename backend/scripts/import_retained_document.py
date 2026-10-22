"""Import one reviewed local F17 PDF through a normal fenced ingestion job."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.retained_document import SOURCES, extract
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_records
from gridlens.intelligence.buying_chain import enrich_buying_chain
from gridlens.jobs.queue import assert_fence
from gridlens.jobs.worker import sync_registry
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Source,
)
from gridlens.settings import settings

ACCEPTANCE_DATABASE = "gl3_pr105_f17_acceptance_20261021"


def assert_isolated_database(url: str) -> str:
    parsed = make_url(url)
    database = parsed.database
    if (
        parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or not database
        or not (database.endswith("_test") or database == ACCEPTANCE_DATABASE)
    ):
        raise ValueError("Refusing retained import outside an approved isolated database")
    return database


def _admit_retained_job(
    session: Session, source_id: str, job_id: UUID, worker_id: str, now: datetime
) -> None:
    # A durable Source row serializes admissions even when no active Job row
    # exists yet. The queue uses this same per-source lock before its Job check.
    row = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if row is None or row.registry_enabled or row.retrieval_method != "retained-document":
        raise ValueError("Retained source is missing, enabled, or registry-mismatched")
    active = session.scalar(
        select(Job.id)
        .where(
            Job.source_id == source_id,
            Job.kind == "retained_import",
            Job.status.in_(["queued", "running"]),
        )
        .with_for_update()
    )
    if active:
        raise ValueError("A retained import for this source is already active")
    session.add(
        Job(
            id=job_id,
            source_id=source_id,
            kind="retained_import",
            status="running",
            attempts=1,
            lease_owner=worker_id,
            fence=1,
            lease_until=now + timedelta(minutes=10),
        )
    )


def run(source_id: str, root: Path) -> dict[str, int | str]:
    # Guard before registry sync or any other database access that can write.
    database_name = assert_isolated_database(settings.database_url)
    definitions = {item["id"]: item for item in load_registry()}
    source = definitions.get(source_id)
    if source_id not in SOURCES or source is None or source.get("enabled") is not False:
        raise ValueError("Select an exact disabled retained-document registry entry")
    record = extract(source_id, root)
    sync_registry()
    worker_id = f"f17-retained-import-{uuid4()}"
    job_id = uuid4()
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        _admit_retained_job(session, source_id, job_id, worker_id, now)
    try:
        with SessionLocal.begin() as session:
            counts = process_records(
                session,
                job_id,
                worker_id,
                1,
                source,
                [record],
                commit=False,
                allow_model=False,
            )
            job = assert_fence(session, job_id, worker_id, 1)
            observation = session.scalar(
                select(Observation).where(
                    Observation.source_id == source_id,
                    Observation.external_id == record["document_number"],
                )
            )
            evidence = (
                session.scalar(
                    select(Evidence).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == record["source_hash"],
                    )
                )
                if observation
                else None
            )
            interpretation = (
                session.scalar(
                    select(Interpretation).where(Interpretation.observation_id == observation.id)
                )
                if observation
                else None
            )
            project_ids = (
                session.scalars(
                    select(PowerNeed.project_id)
                    .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                    .where(NeedObservation.observation_id == observation.id)
                    .distinct()
                ).all()
                if observation
                else []
            )
            for project_id in project_ids:
                if evidence is None:
                    raise RuntimeError("Accepted retained evidence version is missing")
                enrich_buying_chain(
                    session,
                    project_id,
                    retained_only=True,
                    retained_target_evidence_id=evidence.id,
                )
            has_need = bool(project_ids)
            if not (
                evidence
                and interpretation
                and interpretation.status == "accepted"
                and (interpretation.assessment or {}).get("decision") == "accepted"
                and (interpretation.assessment or {}).get("evidence_hash") == evidence.content_hash
                and has_need
            ):
                raise RuntimeError("Retained source did not produce an accepted linked need")
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
    except Exception as exc:
        try:
            with SessionLocal.begin() as session:
                job = assert_fence(session, job_id, worker_id, 1)
                job.status = "failed"
                job.error = f"Retained import failed: {type(exc).__name__}"
                job.lease_owner = job.lease_until = None
        except Exception:
            # A stale fence cannot be terminalized by this importer. Preserve the
            # newer owner’s job state and surface the original failure.
            pass
        raise
    return {key: value for key, value in counts.items() if isinstance(value, int)} | {
        "source_id": source_id,
        "database": database_name,
        "job_id": str(job_id),
        "evidence_sha256": record["source_hash"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument(
        "--root", type=Path, required=True, help="Directory holding reviewed source PDFs"
    )
    args = parser.parse_args()
    print(run(args.source, args.root))


if __name__ == "__main__":
    main()
