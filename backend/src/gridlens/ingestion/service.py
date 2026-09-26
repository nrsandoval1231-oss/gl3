import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.qualification import assess_signal
from gridlens.ingestion.adapters import retrieve_source
from gridlens.ingestion.adapters.govinfo_pdf import MAX_PDFS_PER_RUN, retrieve_companion
from gridlens.intelligence.matching import interpret
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)


def _hash(record: dict[str, Any]) -> str:
    stable_fields = {
        "title": " ".join(record["title"].split()),
        "abstract": " ".join((record.get("abstract") or "").split()),
        "publication_date": record["publication_date"],
        "url": record.get("html_url"),
    }
    raw = json.dumps(stable_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_version_hash(record: dict[str, Any]) -> str:
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def process_job(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    records = retrieve_source(source_definition, client)
    counts: dict[str, Any] = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "signals": 0,
        "latest_publication_date": None,
        "pdf_candidates": 0,
        "pdf_eligible": 0,
        "pdf_enriched": 0,
        "pdf_skipped_not_signal": 0,
        "pdf_skipped_limit": 0,
    }
    pdf_documents = 0
    for record in records:
        assert_fence(session, job_id, worker_id, fence)
        source = session.get(Source, source_definition["id"])
        assert source is not None
        external_id = record["document_number"]
        digest = _hash(record)
        evidence_digest = record.get("source_hash") or _source_version_hash(record)
        counts["latest_publication_date"] = max(
            counts["latest_publication_date"] or "0000-00-00", record["publication_date"]
        )
        observation = session.scalar(
            select(Observation)
            .where(Observation.source_id == source.id, Observation.external_id == external_id)
            .with_for_update()
        )
        is_new = observation is None
        same_material_fields = bool(
            observation
            and observation.title == record["title"]
            and " ".join((observation.abstract or "").split())
            == " ".join((record.get("abstract") or "").split())
            and observation.published_at == date.fromisoformat(record["publication_date"])
            and observation.url == record["html_url"]
        )
        # Accept the prior candidate's hash during the first replay after this
        # semantic fingerprint is introduced; compare retained claims, not
        # provider-side representation links or irrelevant source markup.
        same_version = observation is not None and (
            observation.content_hash == digest or same_material_fields
        )
        change_kind = "discovered" if is_new else "updated"
        if is_new:
            observation = Observation(
                source_id=source.id,
                external_id=external_id,
                title=record["title"],
                abstract=record.get("abstract"),
                published_at=date.fromisoformat(record["publication_date"]),
                url=record["html_url"],
                content_hash=digest,
            )
            session.add(observation)
            session.flush()
            counts["new"] += 1
        elif same_version:
            counts["unchanged"] += 1
        else:
            assert observation is not None
            observation.title = record["title"]
            observation.abstract = record.get("abstract")
            observation.published_at = date.fromisoformat(record["publication_date"])
            observation.url = record["html_url"]
            observation.content_hash = digest
            counts["changed"] += 1
        assert observation is not None
        if (
            session.scalar(
                select(Evidence.id).where(
                    Evidence.observation_id == observation.id,
                    Evidence.content_hash == evidence_digest,
                )
            )
            is None
        ):
            session.add(
                Evidence(
                    observation_id=observation.id,
                    content_hash=evidence_digest,
                    title=record["title"],
                    abstract=record.get("abstract"),
                    url=record["html_url"],
                    published_at=date.fromisoformat(record["publication_date"]),
                    extraction_location=record.get("extraction_location", "title and abstract"),
                    event_date=None,
                )
            )
        session.commit()  # Keep retrieved source evidence durable if PDF enrichment fails.
        # The PDF is an alternate representation of the FR record. Attach its
        # content hash and page citation to this observation only.
        if record.get("pdf_url"):
            counts["pdf_candidates"] += 1
            eligible = (
                source.id == "federal-register-eis"
                and assess_signal(record["title"], record.get("abstract")) is not None
            )
            if not eligible:
                counts["pdf_skipped_not_signal"] += 1
                pdf_citations: list[dict[str, str]] = []
            else:
                counts["pdf_eligible"] += 1
                if pdf_documents >= MAX_PDFS_PER_RUN:
                    counts["pdf_skipped_limit"] += 1
                    pdf_citations = []
                else:
                    pdf_documents += 1
                    pdf_citations = retrieve_companion(record, client)
                    counts["pdf_enriched"] += 1
                    # Network retrieval can outlast this worker's lease. Reclaim
                    # the fence before inspecting or persisting its result.
                    assert_fence(session, job_id, worker_id, fence)
            if pdf_citations:
                pdf = pdf_citations[0]
                if (
                    session.scalar(
                        select(Evidence.id).where(
                            Evidence.observation_id == observation.id,
                            Evidence.content_hash == pdf["content_hash"],
                        )
                    )
                    is None
                ):
                    session.add(
                        Evidence(
                            observation_id=observation.id,
                            content_hash=pdf["content_hash"],
                            title=pdf["title"],
                            abstract=pdf["abstract"],
                            url=pdf["url"],
                            published_at=date.fromisoformat(pdf["published_at"]),
                            extraction_location=pdf["extraction_location"],
                            event_date=None,
                        )
                    )
                    session.commit()
        # PDF evidence has its own commit boundary. Reacquire the current fence
        # before creating or updating the durable interpretation backlog.
        assert_fence(session, job_id, worker_id, fence)
        interpretation = session.scalar(
            select(Interpretation)
            .where(Interpretation.observation_id == observation.id)
            .with_for_update()
        )
        prior_interpretation_status = interpretation.status if interpretation is not None else None
        if interpretation is None:
            interpretation = Interpretation(
                observation_id=observation.id, content_hash=digest, attempts=1
            )
            session.add(interpretation)
        else:
            interpretation.content_hash = digest
            interpretation.status, interpretation.error = "pending", None
            interpretation.attempts += 1
        session.flush()
        session.commit()  # Raw evidence and the interpretation backlog survive a crash.

        try:
            interpreted = interpret({**record, "source_id": source.id})
        except Exception as exc:
            assert_fence(session, job_id, worker_id, fence)
            interpretation.status, interpretation.error = "failed", type(exc).__name__
            session.commit()
            continue
        assert_fence(session, job_id, worker_id, fence)

        project_key = f"{source.id}:{external_id}"
        project = session.scalar(
            select(Project).where(Project.identity_key == project_key).with_for_update()
        )
        if interpreted is None:
            interpretation.status = "rejected"
            if project is not None:
                activity_to_close = (
                    "facility-expansion" if source.id == "nc-commerce" else "mine-development"
                )
                need = session.scalar(
                    select(PowerNeed)
                    .where(
                        PowerNeed.project_id == project.id,
                        PowerNeed.activity_key == activity_to_close,
                    )
                    .with_for_update()
                )
                if need is not None:
                    if need.active:
                        need.active = False
                        session.add(
                            ChangeEvent(
                                observation_id=observation.id,
                                content_hash=digest,
                                kind=(
                                    "reclassified"
                                    if same_version and prior_interpretation_status == "accepted"
                                    else "closed"
                                ),
                            )
                        )
                    if (
                        session.scalar(
                            select(NeedObservation.id).where(
                                NeedObservation.need_id == need.id,
                                NeedObservation.observation_id == observation.id,
                            )
                        )
                        is None
                    ):
                        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        else:
            project_name = interpreted["name"]
            activity_key = interpreted["activity_key"]
            rationale = interpreted["rationale"]
            project_location = interpreted.get("location")
            assert project_name is not None and activity_key is not None and rationale is not None
            assert project_location is None or isinstance(project_location, str)
            if project is None:
                project = Project(
                    identity_key=project_key,
                    name=project_name,
                    location=project_location,
                    source_id=source.id,
                    external_id=external_id,
                )
                session.add(project)
                session.flush()
            else:
                project.name = project_name
                if project_location and project.location != project_location:
                    project.location = project_location
            need = session.scalar(
                select(PowerNeed)
                .where(
                    PowerNeed.project_id == project.id,
                    PowerNeed.activity_key == activity_key,
                )
                .with_for_update()
            )
            material_change = False
            reopened = need is not None and not need.active
            if need is None:
                need = PowerNeed(
                    project_id=project.id,
                    activity_key=activity_key,
                    tier="Signal",
                    rationale=rationale,
                    supply="Unknown",
                )
                session.add(need)
                session.flush()
                counts["signals"] += 1
                material_change = True
            elif not need.active or need.rationale != rationale or not same_version:
                material_change = True
                need.active = True
                need.rationale = rationale
            if (
                session.scalar(
                    select(NeedObservation.id).where(
                        NeedObservation.need_id == need.id,
                        NeedObservation.observation_id == observation.id,
                    )
                )
                is None
            ):
                session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
            if material_change:
                event_kind = change_kind
                if same_version and prior_interpretation_status in {"accepted", "rejected"}:
                    event_kind = "reclassified"
                elif reopened:
                    event_kind = "reopened"
                session.add(
                    ChangeEvent(
                        observation_id=observation.id,
                        content_hash=digest,
                        kind=event_kind,
                    )
                )
            interpretation.status, interpretation.error = "accepted", None

        job = assert_fence(session, job_id, worker_id, fence)
        job.checkpoint = external_id
        job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
        session.commit()
    return counts
