"""One bounded selected-project enrichment pass. No queue, tier or outreach changes."""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from sqlalchemy import and_, func, or_, select, union
from sqlalchemy.orm import Session

from gridlens.domain.buying_chain import (
    CATEGORY_PRIORITY,
    CONTACT_MAX_AGE_DAYS,
    MAX_CANDIDATES,
    MAX_DOCUMENTS,
    MAX_SOURCE_URLS,
    POLICY_VERSION,
    ROLE_MAX_AGE_DAYS,
)
from gridlens.domain.evaluation_clock import evaluation_now
from gridlens.domain.pursuit_research import fingerprint as _hash
from gridlens.domain.signal_admission import admitted_from_source
from gridlens.ingestion.adapters.acquisition_runtime import remaining_seconds
from gridlens.ingestion.adapters.bounded_http import run_isolated
from gridlens.ingestion.adapters.buying_chain_public import (
    CAPTURE_VERSION,
    PublicDocument,
    retrieve,
    validate_public_url,
)
from gridlens.ingestion.adapters.houston_permit_details import (
    SUPPORTED_TYPES,
    response_type_code,
    retrieve_detail,
)
from gridlens.ingestion.adapters.retained_permits import GEORGIA, chicago_contacts, georgia_identity
from gridlens.ingestion.adapters.retained_permits import facts as permit_facts
from gridlens.intelligence.buying_chain_extraction import (
    _ROLE_WORDS,
    Extracted,
    document_content_hash,
    document_key,
    extract_company_contacts,
    extract_organizations,
    extract_people,
    extract_retained_permit_organizations,
    organization_key,
    project_document_match,
)
from gridlens.intelligence.project_identity import normalized_identity
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyProjectMembership,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

MAX_SECONDS = 35
BUYING_CHAIN_JOB_KIND = "buying_chain_research"
BUYING_CHAIN_TASK_TYPE = "buying_chain_research"
RETAINED_BUYING_CHAIN_TASK_TYPE = "buying_chain_retained"
MAX_RETAINED_BACKFILL_PROJECTS = 100


def _buying_chain_context_digest(session: Session, project: Project) -> str:
    retained = _retained(session, project)
    latest_run = session.scalar(
        select(BuyingChainRun)
        .where(BuyingChainRun.project_id == project.id)
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(1)
    )
    claims = session.scalars(
        select(BuyingChainClaim)
        .where(BuyingChainClaim.project_id == project.id)
        .order_by(BuyingChainClaim.id)
    ).all()
    return _hash(
        {
            "project": {
                "id": str(project.id),
                "source_id": project.source_id,
                "external_id": project.external_id,
                "identity_key": project.identity_key,
                "name": project.name,
                "location": project.location,
                "asset_type": project.asset_type,
                "identity_facts": project.identity_facts,
            },
            "retained": sorted((str(row.id), row.content_hash) for row in retained),
            "latest_run": latest_run.input_hash if latest_run else None,
            "claims": [
                (
                    str(row.id),
                    row.fingerprint,
                    row.organization,
                    row.person_name,
                    row.title,
                    row.category,
                    row.organization_relationship,
                    row.person_organization_relationship,
                    row.person_project_relationship,
                    row.citations,
                )
                for row in claims
            ],
            "policy": POLICY_VERSION,
        }
    )


def _retained_buying_chain_context_digest(session: Session, project: Project) -> str:
    """Fence retained-only extraction on source state, never its own derived claims."""
    current_evidence = []
    for evidence in _retained(session, project):
        observation = session.get(Observation, evidence.observation_id)
        interpretation = (
            session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            if observation
            else None
        )
        current_evidence.append(
            (
                str(evidence.id),
                evidence.content_hash,
                retained_evidence_policy_version(interpretation),
            )
        )
    return _hash(
        {
            "project": {
                "id": str(project.id),
                "identity_key": project.identity_key,
                "name": project.name,
                "location": project.location,
                "identity_facts": project.identity_facts,
            },
            "accepted_evidence": sorted(current_evidence),
            "buying_chain_policy_version": POLICY_VERSION,
        }
    )


def retained_evidence_policy_version(interpretation: Interpretation | None) -> str | None:
    """Identify the evaluator that accepted this source version across source families."""
    if interpretation is None:
        return None
    assessment = interpretation.assessment or {}
    value = (
        assessment.get("admission_policy_version")
        or assessment.get("evaluator_version")
        or interpretation.evaluator_version
    )
    return value if isinstance(value, str) and value else None


def _public_research_plan(
    session: Session,
    project: Project,
    retained_documents: list[tuple[PublicDocument, bool, str, UUID | None]],
    supplied_urls: list[str],
    previous_run: BuyingChainRun | None,
) -> tuple[list[str], bool]:
    retained_permit = project.source_id == "chicago-building-permits" and any(
        chicago_contacts(doc.text) for doc, _, _, _ in retained_documents
    )
    retained_permit = retained_permit or (
        project.source_id == GEORGIA
        and any(georgia_identity(doc.text) for doc, _, _, _ in retained_documents)
    )
    retained_permit = retained_permit or (
        project.source_id
        in {
            "austin-building-permits",
            "dallas-monthly-permits",
            "el-paso-new-commercial-permits",
            "houston-weekly-permits",
            "texas-rrc-drilling-permits",
            "boston-building-permits",
        }
        and any(permit_facts(project.source_id, doc.text) for doc, _, _, _ in retained_documents)
    )
    urls: list[str] = []
    if (
        not retained_permit
        and project.source_id == "chicago-building-permits"
        and project.external_id.isdigit()
    ):
        registered_source = session.get(Source, project.source_id)
        if registered_source and registered_source.endpoint.startswith(
            "https://data.cityofchicago.org/resource/"
        ):
            urls.append(
                registered_source.endpoint.split("?")[0]
                + "?"
                + urlencode({"$where": f"id='{project.external_id}'", "$limit": 1})
            )
    elif not retained_permit:
        urls.extend(doc.url for doc, _, _, _ in retained_documents[:2])
    urls.extend(supplied_urls)
    if previous_run:
        retained_urls = {doc.url for doc, _, _, _ in retained_documents}
        for evidence_id in previous_run.evidence_ids:
            previous_evidence = session.get(BuyingChainEvidence, UUID(evidence_id))
            if (
                previous_evidence
                and previous_evidence.retained_evidence_id is None
                and not (
                    project.source_id == "houston-weekly-permits"
                    and "/ibi_apps/WFServlet.ibfs" in previous_evidence.url
                )
                and not (retained_permit and previous_evidence.url in retained_urls)
            ):
                urls.append(previous_evidence.url)
    return list(dict.fromkeys(validate_public_url(url) for url in urls)), retained_permit


def enqueue_buying_chain_research(
    session: Session, project_id: UUID, source_urls: list[str] | None = None
) -> Job:
    if len(source_urls or []) > MAX_SOURCE_URLS:
        raise ValueError("At most four additional public source URLs are allowed")
    normalized_urls = list(dict.fromkeys(validate_public_url(url) for url in source_urls or []))
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise LookupError("Project not found")
    context_digest = _buying_chain_context_digest(session, project)
    request_digest = _hash(
        {
            "project_id": str(project.id),
            "source_urls": normalized_urls,
            "context_digest": context_digest,
            "policy_version": POLICY_VERSION,
        }
    )
    for active in session.scalars(
        select(Job)
        .where(
            Job.kind == BUYING_CHAIN_JOB_KIND,
            Job.target_id == project.id,
            Job.status.in_(["queued", "running"]),
        )
        .order_by(Job.created_at.desc())
        .limit(20)
    ):
        try:
            checkpoint = json.loads(active.checkpoint or "{}")
        except (TypeError, ValueError):
            continue
        if checkpoint.get("request_digest") == request_digest:
            return active
    retained_documents: list[tuple[PublicDocument, bool, str, UUID | None]] = [
        (
            PublicDocument(
                evidence.url,
                evidence.title,
                f"{evidence.title}\n{evidence.abstract or ''}",
                evidence.published_at,
                evidence.observed_at,
                evidence.extraction_location,
                retained_version=evidence.content_hash,
            ),
            True,
            "Previously accepted evidence linked to this selected physical project.",
            evidence.id,
        )
        for evidence in _retained(session, project)
    ]
    previous_run = session.scalar(
        select(BuyingChainRun)
        .where(BuyingChainRun.project_id == project.id)
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(1)
    )
    planned_urls, _ = _public_research_plan(
        session, project, retained_documents, normalized_urls, previous_run
    )
    job = Job(
        source_id=project.source_id,
        kind=BUYING_CHAIN_JOB_KIND,
        target_id=project.id,
        checkpoint=json.dumps(
            {
                "task_type": BUYING_CHAIN_TASK_TYPE,
                "request_digest": request_digest,
                "context_digest": context_digest,
                "payload": {
                    "project_id": str(project.id),
                    "source_urls": normalized_urls,
                    "planned_urls": planned_urls,
                },
                "status": "queued",
            },
            separators=(",", ":"),
        ),
    )
    session.add(job)
    session.flush()
    return job


def enqueue_retained_buying_chain_research(
    session: Session,
    project_id: UUID,
    evidence_id: UUID,
    evidence_hash: str,
) -> Job | None:
    """Queue one retained-only extraction for an accepted evidence version."""
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    evidence = session.get(Evidence, evidence_id)
    observation = session.get(Observation, evidence.observation_id) if evidence else None
    interpretation = (
        session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        if observation
        else None
    )
    if (
        project is None
        or evidence is None
        or evidence.content_hash != evidence_hash
        or not _retained_evidence_current_for_project(
            session, project, evidence, observation=observation, interpretation=interpretation
        )
    ):
        return None
    evidence_policy_version = retained_evidence_policy_version(interpretation)
    if evidence_policy_version is None:
        return None
    context_digest = _retained_buying_chain_context_digest(session, project)
    request_digest = _hash(
        {
            "task_type": RETAINED_BUYING_CHAIN_TASK_TYPE,
            "contact_extraction_policy": "company-contacts-v1",
            "project_id": str(project.id),
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence_hash,
            "evidence_policy_version": evidence_policy_version,
            "context_digest": context_digest,
            "buying_chain_policy_version": POLICY_VERSION,
        }
    )
    prior_jobs = session.scalars(
        select(Job)
        .where(
            Job.kind == BUYING_CHAIN_JOB_KIND,
            Job.target_id == project.id,
            Job.checkpoint.contains(request_digest),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all()
    matching_jobs = []
    for prior_job in prior_jobs:
        try:
            prior_checkpoint = json.loads(prior_job.checkpoint or "{}")
        except (TypeError, ValueError):
            prior_checkpoint = {}
        if prior_checkpoint.get("request_digest") == request_digest:
            matching_jobs.append(prior_job)
    if matching_jobs:
        # Active/successful work remains idempotent. Permit one replacement job
        # after a failed row, but count every historical row for this exact digest
        # so repeated ingestion cannot reset the queue's per-row attempt ceiling.
        reusable = next(
            (job for job in matching_jobs if job.status in {"queued", "running", "succeeded"}),
            None,
        )
        if reusable is not None:
            return reusable
        latest = matching_jobs[0]
        if latest.status != "failed" or len(matching_jobs) >= 2:
            return latest
    job = Job(
        source_id=project.source_id,
        kind=BUYING_CHAIN_JOB_KIND,
        target_id=project.id,
        checkpoint=json.dumps(
            {
                "task_type": RETAINED_BUYING_CHAIN_TASK_TYPE,
                "request_digest": request_digest,
                "context_digest": context_digest,
                "payload": {
                    "project_id": str(project.id),
                    "evidence_id": str(evidence.id),
                    "evidence_hash": evidence_hash,
                    "evidence_policy_version": evidence_policy_version,
                },
                "status": "queued",
            },
            separators=(",", ":"),
        ),
    )
    session.add(job)
    session.flush()
    return job


def retained_buying_chain_backfill(
    session: Session,
    *,
    after_project_id: UUID | None = None,
    limit: int = 50,
    enqueue: bool = False,
) -> dict[str, Any]:
    """Plan or enqueue one bounded page of projects with current accepted evidence."""
    if not 1 <= limit <= MAX_RETAINED_BACKFILL_PROJECTS:
        raise ValueError(f"Backfill limit must be between 1 and {MAX_RETAINED_BACKFILL_PROJECTS}")
    query = (
        select(Project)
        .join(PowerNeed, PowerNeed.project_id == Project.id)
        .where(PowerNeed.active.is_(True))
        .distinct()
        .order_by(Project.id)
        .limit(limit)
    )
    if after_project_id is not None:
        query = query.where(Project.id > after_project_id)
    projects = session.scalars(query).all()
    candidates: list[dict[str, Any]] = []
    queued_count = 0
    now = datetime.now(UTC)
    for project in projects:
        evidence = next(iter(_retained(session, project)), None)
        if evidence is None:
            continue
        observation = session.get(Observation, evidence.observation_id)
        interpretation = (
            session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            if observation
            else None
        )
        policy_version = retained_evidence_policy_version(interpretation)
        if policy_version is None:
            continue
        job = (
            enqueue_retained_buying_chain_research(
                session, project.id, evidence.id, evidence.content_hash
            )
            if enqueue
            else None
        )
        if job is not None and job.attempts < 5 and job.available_at is not None:
            available_at = job.available_at
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            lease_until = job.lease_until
            if lease_until is not None and lease_until.tzinfo is None:
                lease_until = lease_until.replace(tzinfo=UTC)
            if available_at <= now and (
                job.status == "queued"
                or (job.status == "running" and lease_until is not None and lease_until < now)
            ):
                queued_count += 1
        candidates.append(
            {
                "project_id": str(project.id),
                "evidence_id": str(evidence.id),
                "evidence_hash": evidence.content_hash,
                "evidence_policy_version": policy_version,
                "job_id": str(job.id) if job else None,
                "job_status": job.status if job else None,
            }
        )
    return {
        "scanned_projects": len(projects),
        "candidate_count": len(candidates),
        "queued_count": queued_count if enqueue else 0,
        "next_after_project_id": str(projects[-1].id) if projects else None,
        "candidates": candidates,
    }


def buying_chain_job_status(session: Session, project_id: UUID) -> dict | None:
    job = session.scalar(
        select(Job)
        .where(Job.kind == BUYING_CHAIN_JOB_KIND, Job.target_id == project_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "detail_status": (json.loads(job.checkpoint or "{}")).get("status"),
        "created_at": job.created_at,
    }


def run_buying_chain_research(
    job_id: UUID,
    worker_id: str,
    fence: int,
    *,
    deadline: float | None = None,
    lease_expiry: datetime | None = None,
) -> dict[str, Any]:
    """Acquire public evidence without a DB transaction, then persist under a fresh fence."""
    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        task_type = checkpoint.get("task_type")
        if task_type not in {BUYING_CHAIN_TASK_TYPE, RETAINED_BUYING_CHAIN_TASK_TYPE}:
            raise ValueError("Buying-chain job payload is invalid")
        retained_only_task = task_type == RETAINED_BUYING_CHAIN_TASK_TYPE
        payload = checkpoint.get("payload") or {}
        project_id = UUID(payload["project_id"])
        project = session.get(Project, project_id)
        if project is None or project.id != job.target_id:
            raise LookupError("Project not found")
        expected_context = checkpoint.get("context_digest")
        retained_version_current = True
        if retained_only_task:
            try:
                retained_evidence_id = UUID(payload["evidence_id"])
            except (KeyError, TypeError, ValueError):
                retained_version_current = False
            else:
                retained_evidence = session.get(Evidence, retained_evidence_id)
                retained_observation = (
                    session.get(Observation, retained_evidence.observation_id)
                    if retained_evidence
                    else None
                )
                retained_interpretation = (
                    session.scalar(
                        select(Interpretation).where(
                            Interpretation.observation_id == retained_observation.id
                        )
                    )
                    if retained_observation
                    else None
                )
                evidence_policy_version = retained_evidence_policy_version(retained_interpretation)
                retained_version_current = bool(
                    retained_evidence
                    and retained_evidence.content_hash == payload.get("evidence_hash")
                    and retained_interpretation
                    and evidence_policy_version == payload.get("evidence_policy_version")
                    and _retained_evidence_current_for_project(
                        session,
                        project,
                        retained_evidence,
                        observation=retained_observation,
                        interpretation=retained_interpretation,
                    )
                )
        current_context = (
            _retained_buying_chain_context_digest(session, project)
            if retained_only_task
            else _buying_chain_context_digest(session, project)
        )
        if not retained_version_current or current_context != expected_context:
            checkpoint["stale_reason"] = (
                "retained_evidence_version_changed"
                if not retained_version_current
                else "retained_context_changed"
            )
            checkpoint.update(status="stale", completed_at=datetime.now(UTC).isoformat())
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            job.status = "succeeded"
            job.lease_owner = job.lease_until = None
            session.commit()
            return {"status": "stale", "job_id": str(job_id)}
        source = session.get(Source, job.source_id)
        source_enabled = bool(source and source.enabled and source.registry_enabled)
        retained_documents: list[tuple[PublicDocument, bool, str, UUID | None]] = [
            (
                PublicDocument(
                    evidence.url,
                    evidence.title,
                    f"{evidence.title}\n{evidence.abstract or ''}",
                    evidence.published_at,
                    evidence.observed_at,
                    evidence.extraction_location,
                    retained_version=evidence.content_hash,
                ),
                True,
                "Previously accepted evidence linked to this selected physical project.",
                evidence.id,
            )
            for evidence in _retained(
                session,
                project,
                target_evidence_id=retained_evidence_id if retained_only_task else None,
            )
        ]
        previous_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project_id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
            .limit(1)
        )
        planned_urls, _ = _public_research_plan(
            session, project, retained_documents, payload.get("source_urls", []), previous_run
        )
        retained_permit_text = next(
            (
                doc.text
                for doc, _, _, retained_id in retained_documents
                if retained_id is not None
                and project.source_id == "houston-weekly-permits"
                and permit_facts(project.source_id, doc.text)
            ),
            "",
        )
        permit_fields = {
            item["label"]: item["value"]
            for item in permit_facts(project.source_id, retained_permit_text)
        }
        project_snapshot = project

    public_enabled = (
        not retained_only_task
        and settings.buying_chain_public_research_enabled
        and source_enabled
        and deadline is not None
    )
    prefetched_documents: dict[str, PublicDocument] = {}
    retrieval_failures: dict[str, str] = {}
    prefetched_detail: PublicDocument | None = None
    detail_prefetched = True
    if public_enabled:
        urls = list(planned_urls)
        checked: set[str] = set()
        while urls and len(checked) < MAX_DOCUMENTS and len(prefetched_documents) < MAX_DOCUMENTS:
            try:
                remaining_seconds(deadline)
            except TimeoutError:
                retrieval_failures[urls[0]] = "DeadlineExceeded"
                break
            url = urls.pop(0)
            if url in checked:
                continue
            checked.add(url)
            try:
                doc = retrieve(url, deadline=deadline)
                validate_public_url(doc.url)
                matched, _reason = project_document_match(project_snapshot, doc)
                prefetched_documents[url] = doc
                if matched:
                    urls.extend(
                        link for link in doc.links if link not in checked and link not in urls
                    )
            except Exception as exc:
                retrieval_failures[url] = type(exc).__name__
        if permit_fields.get("Permit type") == "Building Pmt":
            try:
                if deadline is None:
                    raise TimeoutError("A finite acquisition deadline is required")
                prefetched_detail = run_isolated(
                    "gridlens.ingestion.adapters.houston_permit_details:retrieve_detail",
                    (
                        permit_fields.get("Source record", ""),
                        permit_fields["Permit type"],
                    ),
                    {
                        "event_date": permit_fields.get(
                            "Permit sale event date (weekly report)", ""
                        ),
                        "site_address": permit_fields.get("Site address", ""),
                    },
                    deadline=deadline,
                )
            except Exception:
                prefetched_detail = None
    else:
        detail_prefetched = False

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        project = session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current_retained_context = (
            _retained_buying_chain_context_digest(session, project)
            if retained_only_task and project is not None
            else None
        )
        current_manual_context = (
            _buying_chain_context_digest(session, project)
            if not retained_only_task and project is not None
            else None
        )
        retained_target_current = True
        if retained_only_task:
            target = session.get(Evidence, retained_evidence_id)
            target_observation = session.get(Observation, target.observation_id) if target else None
            target_interpretation = (
                session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == target_observation.id
                    )
                )
                if target_observation
                else None
            )
            retained_target_current = bool(
                project
                and target
                and target.content_hash == payload.get("evidence_hash")
                and retained_evidence_policy_version(target_interpretation)
                == payload.get("evidence_policy_version")
                and _retained_evidence_current_for_project(
                    session,
                    project,
                    target,
                    observation=target_observation,
                    interpretation=target_interpretation,
                )
            )
        if (
            project is None
            or (current_retained_context if retained_only_task else current_manual_context)
            != expected_context
            or not retained_target_current
        ):
            checkpoint.update(
                status="stale",
                stale_reason=(
                    "retained_evidence_version_changed"
                    if not retained_target_current
                    else "retained_context_changed"
                ),
                completed_at=datetime.now(UTC).isoformat(),
            )
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            job.status = "succeeded"
            job.lease_owner = job.lease_until = None
            return {"status": "stale", "job_id": str(job_id)}
        current_source = session.get(Source, job.source_id)
        policy_active = bool(
            current_source and current_source.enabled and current_source.registry_enabled
        )
        still_public_enabled = settings.buying_chain_public_research_enabled and policy_active
        result = enrich_buying_chain(
            session,
            project_id,
            source_urls=payload.get("source_urls", []),
            prefetched_documents=prefetched_documents
            if public_enabled and still_public_enabled
            else {},
            retrieval_failures=retrieval_failures,
            prefetched_houston_detail=prefetched_detail,
            houston_detail_prefetched=detail_prefetched,
            retained_only=not (public_enabled and still_public_enabled),
            retained_target_evidence_id=(retained_evidence_id if retained_only_task else None),
        )
        detail_status = (
            result.get("status", "complete")
            if retained_only_task
            else "disabled"
            if not settings.buying_chain_public_research_enabled
            else "blocked_source_policy"
            if not policy_active
            else "blocked_deadline"
            if deadline is None
            else result.get("status", "complete")
        )
        checkpoint.update(
            status="complete"
            if detail_status in {"complete", "partial", "unresolved"}
            else detail_status,
            detail_status=detail_status,
            completed_at=datetime.now(UTC).isoformat(),
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
        job.status = "succeeded"
        job.error = None
        job.lease_owner = job.lease_until = None
        return {"status": detail_status, "job_id": str(job_id), "result": result}


@dataclass(slots=True)
class BuyingChainViewPreload:
    runs: dict[UUID, list[BuyingChainRun]] = field(default_factory=lambda: defaultdict(list))
    claims: dict[UUID, list[BuyingChainClaim]] = field(default_factory=lambda: defaultdict(list))
    sources: dict[UUID, list[BuyingChainEvidence]] = field(
        default_factory=lambda: defaultdict(list)
    )
    retained: dict[UUID, list[Evidence]] = field(default_factory=lambda: defaultdict(list))
    retained_observations: dict[UUID, dict[UUID, Observation]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    retained_current: dict[UUID, dict[UUID, bool]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    retained_source_ids: dict[UUID, dict[UUID, str]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    permit_details: dict[UUID, list[BuyingChainEvidence]] = field(
        default_factory=lambda: defaultdict(list)
    )
    corrections: dict[UUID, list[Any]] = field(default_factory=lambda: defaultdict(list))


def _accepted_version(interpretation: Interpretation | None, evidence: Evidence) -> bool:
    if interpretation is None or not interpretation.assessment:
        return False
    assessment = interpretation.assessment
    # Processing failure/pending is not a new factual decision. The ingestion
    # service deliberately keeps the last accepted, evidence-bound assessment.
    accepted = interpretation.status == "accepted" or (
        interpretation.status in {"failed", "pending"} and assessment.get("decision") == "accepted"
    )
    return accepted and assessment.get("evidence_hash") == evidence.content_hash


def _retained_evidence_current_for_project(
    session: Session,
    project: Project,
    evidence: Evidence,
    *,
    observation: Observation | None = None,
    interpretation: Interpretation | None = None,
    source: Source | None = None,
    preloaded: bool = False,
) -> bool:
    """Return whether a retained citation can support this project's current view.

    Official admitted evidence may introduce a relationship itself.  Context
    news may do so only after ingestion recorded it as an explicit supplemental
    match to an already-admitted project need.  Both cases require a concrete
    current project binding; missing keys are never a wildcard.
    """
    if not preloaded:
        observation = observation or session.get(Observation, evidence.observation_id)
        interpretation = interpretation or (
            session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            if observation
            else None
        )
    if (
        observation is None
        or interpretation is None
        or not _accepted_version(interpretation, evidence)
    ):
        return False
    assessment = interpretation.assessment or {}
    bound_project = assessment.get("project_identity_key")
    if (
        not isinstance(bound_project, str)
        or not bound_project
        or bound_project != project.identity_key
    ):
        return False
    if not preloaded:
        source = source or session.get(Source, observation.source_id)
    if source is None:
        return False
    if (
        source.id.startswith("research-public-")
        and assessment.get("acquisition_capture_version") != CAPTURE_VERSION
    ):
        # Older public captures selected only a main container. Preserve their
        # history, but require a complete bounded capture before current use.
        return False
    if assessment.get("admission_status") == "relationship_supplement":
        # Relationship documents do not support power/activity projection. Recheck
        # their exact project binding and explicit organization role on retained
        # text before using them for the buying chain.
        document = PublicDocument(
            evidence.url,
            evidence.title,
            evidence.abstract or "",
            evidence.published_at,
            evidence.observed_at,
            evidence.extraction_location,
        )
        return (
            interpretation.status == "accepted"
            and interpretation.evaluator_version == "research-relationship-v2"
            and "power_activity" not in assessment
            and "activity_key" not in assessment
            and project_document_match(project, document)[0]
            and any(
                item.organization_relationship == "DIRECT"
                for item in extract_organizations(document, project)
            )
        )
    if admitted_from_source(source, assessment, evidence).admitted:
        return True
    # Only `_attach_news_supplement` writes this status, after attaching the
    # observation to an admitted need and recording the matched project key.
    # Retain that durable decision even when a later cleanup no longer has the
    # original NeedObservation row in memory.
    return assessment.get("admission_status") == "supplemental"


def _retained(
    session: Session,
    project: Project,
    *,
    target_evidence_id: UUID | None = None,
) -> list[Evidence]:
    observations = (
        select(NeedObservation.observation_id)
        .join(
            PowerNeed,
            PowerNeed.id == NeedObservation.need_id,
        )
        .where(PowerNeed.project_id == project.id)
    )
    query = (
        select(Evidence, Interpretation)
        .join(Observation, Observation.id == Evidence.observation_id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            or_(
                Observation.id.in_(observations),
                (Observation.source_id == project.source_id)
                & (Observation.external_id == project.external_id),
            )
        )
        .order_by(Evidence.observed_at.desc(), Evidence.id)
    )
    accepted: list[Evidence] = []
    cursor: tuple[datetime, UUID] | None = None
    while len(accepted) < 4:
        page = query
        if cursor is not None:
            observed_at, evidence_id = cursor
            page = page.where(
                or_(
                    Evidence.observed_at < observed_at,
                    and_(Evidence.observed_at == observed_at, Evidence.id > evidence_id),
                )
            )
        rows = session.execute(page.limit(24)).all()
        if not rows:
            break
        for evidence, _ in rows:
            if _retained_evidence_current_for_project(session, project, evidence):
                accepted.append(evidence)
                if len(accepted) == 4:
                    break
        cursor = (rows[-1][0].observed_at, rows[-1][0].id)
        if len(rows) < 24:
            break
    if target_evidence_id is not None:
        target = session.get(Evidence, target_evidence_id)
        if (
            target is not None
            and target not in accepted
            and _retained_evidence_current_for_project(session, project, target)
        ):
            # A per-evidence retained job must read its current target even when
            # it falls outside the usual four newest accepted documents.
            accepted = [*accepted[:3], target]
    return accepted


def _store_document(
    session: Session,
    project: Project,
    doc: PublicDocument,
    reason: str,
    retained_id: UUID | None = None,
    *,
    seen_at: datetime,
) -> BuyingChainEvidence:
    digest = document_content_hash(doc)
    existing = session.scalar(
        select(BuyingChainEvidence).where(
            BuyingChainEvidence.project_id == project.id,
            BuyingChainEvidence.url == doc.url,
            BuyingChainEvidence.content_hash == digest,
        )
    )
    if existing:
        # Preserve first-observed time, content hash and excerpt on unchanged replay.
        existing.last_seen_at = max(existing.last_seen_at, seen_at)
        return existing
    row = BuyingChainEvidence(
        project_id=project.id,
        retained_evidence_id=retained_id,
        url=doc.url,
        title=doc.title,
        excerpt=doc.text,
        content_hash=digest,
        extraction_location=doc.extraction_location,
        published_at=doc.published_at,
        observed_at=doc.observed_at,
        last_seen_at=seen_at,
        project_match_reason=reason,
    )
    session.add(row)
    session.flush()
    return row


def has_public_research_provenance(source: BuyingChainEvidence) -> bool:
    """Validate a bounded public-research citation without inventing registry IDs."""
    if source.retained_evidence_id is not None or not source.project_match_reason.strip():
        return False
    try:
        validated_url = validate_public_url(source.url)
    except ValueError:
        return False
    document = PublicDocument(
        url=source.url,
        title=source.title,
        text=source.excerpt,
        published_at=source.published_at,
        observed_at=source.observed_at,
        extraction_location=source.extraction_location,
    )
    return validated_url == source.url and document_content_hash(document) == source.content_hash


def _entity_key(item: Extracted) -> str:
    return _hash(
        [
            organization_key(item.organization),
            normalized_identity(item.person_name),
            item.category if item.person_name is None else "person",
        ]
    )


def _deduplicate(items: list[Extracted]) -> list[Extracted]:
    grouped: dict[str, Extracted] = {}
    for item in items:
        key = _entity_key(item)
        prior = grouped.get(key)
        if prior is None:
            grouped[key] = item
            continue

        def permit_name_only(value: Extracted) -> bool:
            return bool(
                value.person_name
                and value.title is None
                and value.person_organization_relationship == "UNKNOWN"
                and any(c["supports"] == "permit_listed_person" for c in value.citations)
            )

        # A permit names a person without reporting a current job. That absence
        # cannot contradict a separately evidenced current role. Raw permit name
        # attribution remains in permit facts and immutable evidence/history.
        if permit_name_only(prior) and item.person_organization_relationship == "CURRENT":
            grouped[key] = item
            continue
        if permit_name_only(item) and prior.person_organization_relationship == "CURRENT":
            continue
        different = (
            normalized_identity(prior.title) != normalized_identity(item.title)
            or prior.organization_relationship != item.organization_relationship
            or prior.person_organization_relationship != item.person_organization_relationship
            or prior.person_project_relationship != item.person_project_relationship
        )
        if different:
            prior.person_project_relationship = "UNKNOWN"
            if prior.person_name:
                prior.person_organization_relationship = "UNKNOWN"
            if prior.organization_relationship != item.organization_relationship:
                prior.organization_relationship = "UNKNOWN"
            prior.evidence_strength = "Low"
            prior.reason = (
                "Conflicting relationship or title evidence; current responsibility is UNKNOWN."
            )
        for citation in item.citations:
            if citation not in prior.citations:
                prior.citations.append(citation)
        for contact in item.public_contacts:
            if contact not in prior.public_contacts:
                prior.public_contacts.append(contact)
    return sorted(
        grouped.values(),
        key=lambda item: (
            CATEGORY_PRIORITY.get(item.category, 99),
            item.person_name is None,
            organization_key(item.organization),
            item.person_name or "",
        ),
    )


def _retain_unchecked_contacts(session, project_id, candidates, saved, retrieved_urls, now):
    """A bounded or failed refresh is not evidence that an existing method vanished."""
    prior_view = buying_chain_view(session, project_id, now=now)
    for previous in prior_view["candidates"]:
        if previous.get("stale") or previous.get("retracted"):
            continue
        prior = session.get(BuyingChainClaim, previous["id"])
        if prior is None:
            continue
        for item in candidates:
            if (
                _entity_key(item) != prior.entity_key
                or item.organization != previous["organization"]
                or item.person_name != previous.get("person_name")
                or item.title != previous.get("title")
                or item.organization_relationship != "DIRECT"
            ):
                continue
            for contact in previous.get("public_contacts", []):
                if contact["source_url"] in retrieved_urls:
                    continue
                support = next(
                    (
                        e
                        for e in previous["evidence"]
                        if e.get("current_support")
                        and e.get("supports") == "public_contact"
                        and e["url"] == contact["source_url"]
                        and e["quote"] == contact["quote"]
                    ),
                    None,
                )
                if support is None:
                    continue
                evidence = session.get(BuyingChainEvidence, UUID(str(support["id"])))
                if evidence is None:
                    continue
                key = evidence.url + ":" + evidence.content_hash
                saved[key] = evidence
                citation = {
                    "url": evidence.url,
                    "quote": contact["quote"],
                    "supports": "public_contact",
                    "document_key": key,
                }
                if citation not in item.citations:
                    item.citations.append(citation)
                if contact not in item.public_contacts:
                    item.public_contacts.append(contact)


def _retain_unchecked_assignments(
    session: Session,
    project_id: UUID,
    candidates: list[Extracted],
    saved: dict[str, BuyingChainEvidence],
    retrieved_urls: set[str],
    now: datetime,
) -> None:
    """A source outage cannot retract a still-valid explicit person assignment.

    Merge only an unchanged, independently current role with a previously direct
    assignment that the normal view still validates for freshness and conflicts.
    Different titles, UNKNOWN roles and successfully retracted sources never qualify.
    """
    prior_view = buying_chain_view(session, project_id, now=now)
    prior_candidates = {str(item["id"]): item for item in prior_view["candidates"]}
    for prior_id, previous in prior_candidates.items():
        if previous["person_project_relationship"] != "DIRECT":
            continue
        prior = session.get(BuyingChainClaim, UUID(prior_id))
        if prior is None:
            continue
        for item in candidates:
            if (
                _entity_key(item) != prior.entity_key
                or normalized_identity(item.title) != normalized_identity(prior.title)
                or item.person_organization_relationship != "CURRENT"
                or item.organization_relationship != "DIRECT"
                or item.person_project_relationship != "ROLE_SUPPORTED"
            ):
                continue
            assignments = [
                citation
                for citation in prior.citations
                if citation["supports"] == "person_project_assignment"
                and citation["url"] not in retrieved_urls
            ]
            if not assignments:
                continue
            for citation in assignments:
                evidence = session.get(BuyingChainEvidence, UUID(citation["evidence_id"]))
                if evidence is None:
                    continue
                key = evidence.url + ":" + evidence.content_hash
                saved[key] = evidence
                retained_citation = {
                    **{key: value for key, value in citation.items() if key != "evidence_id"},
                    "document_key": key,
                }
                if retained_citation not in item.citations:
                    item.citations.append(retained_citation)
            item.person_project_relationship = "DIRECT"
            item.evidence_strength = "High"
            item.reason = (
                "Previously explicit assignment retained while its source is unchecked; "
                "the same current role is supported. Purchasing authority remains unverified."
            )


def _newest_source_by_url(
    sources: Sequence[BuyingChainEvidence], active_run: BuyingChainRun | None
) -> dict[str, UUID]:
    by_id = {str(row.id): row for row in sources}
    newest: dict[str, UUID] = {}
    for version in sorted(
        sources,
        key=lambda row: (row.last_seen_at, row.retained_evidence_id is None, row.id),
        reverse=True,
    ):
        newest.setdefault(version.url, version.id)
    if active_run:
        for evidence_id in active_run.evidence_ids:
            if evidence_id not in by_id:
                continue
            run_source = by_id[evidence_id]
            current = by_id[str(newest[run_source.url])]
            if (
                run_source.last_seen_at,
                run_source.retained_evidence_id is None,
            ) >= (current.last_seen_at, current.retained_evidence_id is None):
                newest[run_source.url] = run_source.id
    return newest


def enrich_buying_chain(
    session: Session,
    project_id: UUID,
    *,
    source_urls: list[str] | None = None,
    fetcher: Callable[[str], PublicDocument] = retrieve,
    prefetched_documents: dict[str, PublicDocument] | None = None,
    retrieval_failures: dict[str, str] | None = None,
    prefetched_houston_detail: PublicDocument | None = None,
    houston_detail_prefetched: bool = False,
    now: datetime | None = None,
    retained_only: bool = False,
    retained_target_evidence_id: UUID | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    # Lock one project during this bounded pass to serialize replay without another queue.
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise LookupError("Project not found")
    # Capture the actual accepted current state before this pass mutates the
    # selected claim/run projection. The diff is emitted only after a retained
    # accepted Evidence version is available to support it.
    from gridlens.intelligence.change_detection import seed_material_state

    material_baseline = seed_material_state(session, project)
    buying_chain_baseline = buying_chain_view(session, project.id, now=now)
    if len(source_urls or []) > MAX_SOURCE_URLS:
        raise ValueError("At most four additional public source URLs are allowed")
    supplied = [validate_public_url(url) for url in source_urls or []]
    previous_run = session.scalar(
        select(BuyingChainRun)
        .where(
            BuyingChainRun.project_id == project.id,
        )
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
    )
    # Snapshot the actual checked version before this pass can update last_seen_at
    # on a reused immutable version. Partial runs can retain older IDs as history.
    prior_versions = _newest_source_by_url(
        session.scalars(
            select(BuyingChainEvidence).where(BuyingChainEvidence.project_id == project.id)
        ).all(),
        previous_run,
    )
    started = time.monotonic()
    deadline = started + MAX_SECONDS
    unresolved: list[str] = []
    documents: list[tuple[PublicDocument, bool, str, UUID | None]] = []
    from gridlens.ingestion.adapters.retained_document import SOURCES as F17_SOURCES

    for evidence in _retained(session, project, target_evidence_id=retained_target_evidence_id):
        observation = session.get(Observation, evidence.observation_id)
        structured: tuple[dict, ...] = ()
        if observation and observation.source_id in F17_SOURCES:
            retained = (evidence.provenance or {}).get("retained_document")
            structured = (
                {
                    "f17_retained": {
                        "source_id": observation.source_id,
                        "evidence_content_hash": evidence.content_hash,
                        "project_name": project.name,
                        "project_location": project.location,
                        "retained_document": retained,
                    }
                },
            )
        documents.append(
            (
                PublicDocument(
                    evidence.url,
                    evidence.title,
                    f"{evidence.title}\n{evidence.abstract or ''}",
                    evidence.published_at,
                    evidence.observed_at,
                    evidence.extraction_location,
                    structured=structured,
                    retained_version=evidence.content_hash,
                ),
                True,
                "Previously accepted evidence linked to this selected physical project.",
                evidence.id,
            )
        )
    urls: list[str] = []
    urls, retained_permit = _public_research_plan(
        session, project, documents, supplied, previous_run
    )
    checked_urls: set[str] = set()
    retrieval_failed = False
    # Network budget is independent of retained-document count.
    if retained_only:
        urls = []
    while urls and len(checked_urls) < MAX_DOCUMENTS and len(documents) < MAX_DOCUMENTS:
        if time.monotonic() - started >= MAX_SECONDS:
            retrieval_failed = True
            unresolved.append("Public research stopped at the 35-second elapsed-time limit.")
            break
        url = urls.pop(0)
        if url in checked_urls:
            continue
        checked_urls.add(url)
        try:
            if prefetched_documents is not None:
                doc = prefetched_documents.get(url)
                if doc is None:
                    retrieval_failed = True
                    unresolved.append(
                        f"Public retrieval unavailable for {url}: "
                        f"{(retrieval_failures or {}).get(url, 'Unavailable')}."
                    )
                    continue
            else:
                doc = retrieve(url, deadline=deadline) if fetcher is retrieve else fetcher(url)
            validate_public_url(doc.url)
            matched, reason = project_document_match(project, doc)
            documents.append((doc, matched, reason, None))
            # Only same-host, relevant links found on a scoped document. No crawl expansion.
            if matched:
                urls.extend(
                    link for link in doc.links if link not in checked_urls and link not in urls
                )
        except Exception as exc:
            retrieval_failed = True
            # Never include exception text, credentials, response bodies or stack traces in API.
            unresolved.append(f"Public retrieval unavailable for {url}: {type(exc).__name__}.")
    if project.source_id == "houston-weekly-permits" and not retained_only:
        retained_permit_doc = next(
            (doc for doc, _, _, retained_id in documents if retained_id is not None), None
        )
        parsed_permit = (
            permit_facts(project.source_id, retained_permit_doc.text)
            if retained_permit_doc is not None
            else {}
        )
        permit_fields = {item["label"]: item["value"] for item in parsed_permit}
        # The XLSX permit type is an official exact-project search selector only
        # where the UI result supplied this same mapping (Building Pmt -> 13).
        if permit_fields.get("Permit type") == "Building Pmt" and houston_detail_prefetched:
            if prefetched_houston_detail is not None:
                documents.append(
                    (
                        prefetched_houston_detail,
                        True,
                        "Exact Houston sold permit project, permit type, date and site "
                        "match the selected project.",
                        None,
                    )
                )
            else:
                retrieval_failed = True
                unresolved.append("Exact Houston permit detail unavailable: PublicRetrievalError.")
        elif permit_fields.get("Permit type") == "Building Pmt":
            try:
                detail = retrieve_detail(
                    permit_fields.get("Source record", ""),
                    permit_fields["Permit type"],
                    event_date=permit_fields.get("Permit sale event date (weekly report)", ""),
                    site_address=permit_fields.get("Site address", ""),
                )
                detail_values = {
                    item["label"]: item["value"]
                    for item in permit_facts(project.source_id, detail.text)
                }
                expected_type_code = SUPPORTED_TYPES[permit_fields["Permit type"]]
                if response_type_code(detail_values.get("Permit type code", "")) != (
                    expected_type_code
                ):
                    raise ValueError(
                        "Houston exact permit detail type did not match the weekly row"
                    )
                expected_address = permit_fields.get("Site address", "")
                found_address = detail_values.get("Permit job address", "")
                if not found_address.casefold().startswith(expected_address.casefold()):
                    raise ValueError(
                        "Houston exact detail site did not match retained permit evidence"
                    )
                documents.append(
                    (
                        detail,
                        True,
                        "Exact Houston sold permit project, permit type, date and site "
                        "match the selected project.",
                        None,
                    )
                )
            except Exception as exc:
                retrieval_failed = True
                unresolved.append(f"Exact Houston permit detail unavailable: {type(exc).__name__}.")
    research_incomplete = retained_only or retrieval_failed or bool(urls)
    if urls:
        unresolved.append(
            "Public research reached its time or document bound; some sources remain unchecked."
        )
    retrieved_by_url = {
        doc.url: doc for doc, _, _, retained_id in documents if retained_id is None or retained_only
    }
    organizations: list[Extracted] = []
    saved: dict[str, BuyingChainEvidence] = {}
    from gridlens.ingestion.adapters.retained_document import SOURCES as F17_SOURCES

    for doc, matched, reason, retained_id in documents:
        f17_source_id = None
        if matched:
            row = _store_document(
                session,
                project,
                doc,
                reason,
                retained_id,
                seen_at=doc.observed_at if retained_id else now,
            )
            saved[document_key(doc)] = row
            if retained_id:
                original = session.get(Evidence, retained_id)
                observation = (
                    session.get(Observation, original.observation_id) if original else None
                )
                if observation:
                    if observation.source_id == "texas-tdlr-tabs-data-centers":
                        f17_source_id = observation.source_id
                        organizations.extend(
                            extract_retained_permit_organizations(
                                doc, observation.source_id, project=project
                            )
                        )
                    else:
                        if observation.source_id in F17_SOURCES:
                            f17_source_id = observation.source_id
                        organizations.extend(
                            extract_retained_permit_organizations(doc, observation.source_id)
                        )
            elif (
                project.source_id == "houston-weekly-permits"
                and "/ibi_apps/WFServlet.ibfs" in doc.url
            ):
                organizations.extend(extract_retained_permit_organizations(doc, project.source_id))
            if f17_source_id is None:
                organizations.extend(extract_organizations(doc, project))
    people = [item for item in organizations if item.person_name is not None]
    organizations = _deduplicate([item for item in organizations if item.person_name is None])
    for doc, matched, reason, retained_id in documents:
        f17_retained = any(
            isinstance(row, dict) and "f17_retained" in row for row in doc.structured
        )
        results = (
            []
            if f17_retained
            else extract_people(
                doc, organizations, project, project_scoped=matched, today=now.date()
            )
        )
        results.extend(extract_company_contacts(doc, organizations))
        if results:
            row = _store_document(
                session,
                project,
                doc,
                reason
                if matched
                else "Organization-role source only; no person-project assignment inferred.",
                retained_id,
                seen_at=doc.observed_at if retained_id else now,
            )
            saved[document_key(doc)] = row
            people.extend(results)
        elif not matched:
            # A successfully rechecked known role page can retract a role. Retain
            # its changed version even when it now has no extractable relationship.
            known_source = session.scalar(
                select(BuyingChainEvidence.id)
                .where(
                    BuyingChainEvidence.project_id == project.id,
                    BuyingChainEvidence.url == doc.url,
                )
                .limit(1)
            )
            if known_source is not None:
                row = _store_document(
                    session,
                    project,
                    doc,
                    "Previously supported source rechecked; no supported relationship remains.",
                    retained_id,
                    seen_at=doc.observed_at if retained_id else now,
                )
                saved[document_key(doc)] = row
            unresolved.append(
                f"No supported project or relevant role relationship extracted from {doc.url}."
            )
    candidates = _deduplicate([*organizations, *people])
    if previous_run:
        _retain_unchecked_contacts(
            session, project.id, candidates, saved, set(retrieved_by_url), now
        )
    if previous_run and research_incomplete:
        _retain_unchecked_assignments(
            session, project.id, candidates, saved, set(retrieved_by_url), now
        )
    if retained_only:
        # Retained abstracts must not downgrade a still-current full-page identity
        # citation for the exact same relationship statement.
        for item in candidates:
            for previous in buying_chain_baseline["candidates"]:
                prior = session.get(BuyingChainClaim, previous["id"])
                if prior is None or prior.entity_key != _entity_key(item):
                    continue
                for citation in item.citations:
                    retained_support = next(
                        (
                            e
                            for e in previous["evidence"]
                            if e.get("current_support")
                            and e.get("id") == e.get("current_source_version_id")
                            and e["url"] == citation["url"]
                            and e["quote"] == citation["quote"]
                            and e["supports"] == citation["supports"]
                        ),
                        None,
                    )
                    if retained_support:
                        retained_source = session.get(BuyingChainEvidence, retained_support["id"])
                        if retained_source is None:
                            continue
                        key = retained_source.url + ":" + retained_source.content_hash
                        saved[key] = retained_source
                        citation["document_key"] = key
    if len(candidates) > MAX_CANDIDATES:
        unresolved.append(
            "Eight-candidate result limit reached; lower-priority relationships were not added."
        )
    candidates = candidates[:MAX_CANDIDATES]
    added = 0
    current_claim_ids = []
    for item in candidates:
        # Operator decisions remain authoritative across automated rediscovery.
        # Keep their claim/version chain; the view still revalidates its sources.
        corrected_prior = (
            session.scalar(
                select(BuyingChainClaim)
                .join(BuyingChainCorrection, BuyingChainCorrection.claim_id == BuyingChainClaim.id)
                .where(
                    BuyingChainClaim.project_id == project.id,
                    BuyingChainClaim.entity_key == _entity_key(item),
                    BuyingChainClaim.id.in_([UUID(v) for v in previous_run.claim_ids]),
                )
                .order_by(BuyingChainClaim.observed_at.desc())
                .limit(1)
            )
            if previous_run
            else None
        )
        if corrected_prior is not None:
            current_claim_ids.append(str(corrected_prior.id))
            continue
        citations = []
        for citation in item.citations:
            source = saved[citation["document_key"]]
            if citation["quote"] not in source.excerpt:
                raise ValueError("Citation does not match retained evidence version")
            citations.append(
                {
                    **{k: v for k, v in citation.items() if k != "document_key"},
                    "evidence_id": str(source.id),
                }
            )
        state: dict[str, Any] = {
            "policy_version": POLICY_VERSION,
            "organization": item.organization,
            "person_name": item.person_name,
            "title": item.title,
            "category": item.category,
            "organization_relationship": item.organization_relationship,
            "person_organization_relationship": item.person_organization_relationship,
            "person_project_relationship": item.person_project_relationship,
            "evidence_strength": item.evidence_strength,
            "reason": item.reason,
            "citations": sorted(citations, key=lambda c: (c["url"], c["supports"], c["quote"])),
            "public_contacts": item.public_contacts,
        }
        fingerprint = _hash(
            {
                **state,
                "public_contacts": [
                    {key: value for key, value in contact.items() if key != "observed_at"}
                    for contact in state["public_contacts"]
                ],
            }
        )
        existing_claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.fingerprint == fingerprint,
            )
        )
        if existing_claim:
            current_claim_ids.append(str(existing_claim.id))
            continue
        evidence_times = [
            saved[citation["document_key"]].observed_at for citation in item.citations
        ]
        new_claim = BuyingChainClaim(
            project_id=project.id,
            entity_key=_entity_key(item),
            fingerprint=fingerprint,
            **state,
            observed_at=max(evidence_times),
            verified_at=now if item.organization_relationship == "DIRECT" else None,
        )
        session.add(new_claim)
        session.flush()
        # A contact-only revision must not split the canonical company account.
        # Carry an identity only across the same project/entity and an identical
        # supporting relationship quote on the same source URL.
        for previous in buying_chain_baseline["candidates"]:
            prior = session.get(BuyingChainClaim, previous["id"])
            if prior is None or prior.entity_key != new_claim.entity_key:
                continue
            for link in session.scalars(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == prior.id,
                    BuyingChainIdentityLink.state == "current",
                )
            ):
                identity_field = f"{link.entity_type}_identity_id"
                if str(previous.get(identity_field)) != str(getattr(link, identity_field)):
                    continue
                old_support = [
                    e
                    for e in previous["evidence"]
                    if e.get("current_support") and str(e["id"]) == str(link.source_evidence_id)
                ]
                replacement = next(
                    (
                        c
                        for c in citations
                        if any(
                            c["url"] == e["url"]
                            and c["quote"] == e["quote"]
                            and c["supports"] == e["supports"]
                            for e in old_support
                        )
                    ),
                    None,
                )
                if replacement is None:
                    continue
                replacement_source = session.get(
                    BuyingChainEvidence, UUID(replacement["evidence_id"])
                )
                if replacement_source is None:
                    continue
                session.add(
                    BuyingChainIdentityLink(
                        claim_id=new_claim.id,
                        entity_type=link.entity_type,
                        company_identity_id=link.company_identity_id,
                        person_identity_id=link.person_identity_id,
                        basis=link.basis,
                        reason="Unchanged source-cited relationship across contact revision.",
                        reviewed_by=link.reviewed_by,
                        source_evidence_id=replacement_source.id,
                        source_version_hash=replacement_source.content_hash,
                        state="current",
                    )
                )
        current_claim_ids.append(str(new_claim.id))
        added += 1
    if not candidates:
        unresolved.append("No explicit buying-chain relationship found; buyer remains UNKNOWN.")
    if not any(item.person_project_relationship == "DIRECT" for item in candidates):
        unresolved.append(
            "Named individual project assignment and purchasing authority remain UNKNOWN."
        )
    current_evidence_ids = [str(row.id) for row in saved.values()]
    if previous_run and research_incomplete:
        # An outage or unvisited source is not negative evidence. A successful
        # source retraction is: never carry a claim contradicted by a checked version.
        known_entities = {_entity_key(item) for item in candidates}
        for prior_id in previous_run.claim_ids:
            prior_claim = session.get(BuyingChainClaim, UUID(prior_id))
            if prior_claim is None or prior_claim.entity_key in known_entities:
                continue
            has_unchecked_source = any(
                citation["url"] not in retrieved_by_url for citation in prior_claim.citations
            )
            contradicted = any(
                citation["url"] in retrieved_by_url
                and citation["quote"] not in retrieved_by_url[citation["url"]].text
                for citation in prior_claim.citations
            )
            if has_unchecked_source and not contradicted:
                current_claim_ids.append(prior_id)
        current_evidence_ids = list(
            dict.fromkeys(
                [
                    *previous_run.evidence_ids,
                    *current_evidence_ids,
                ]
            )
        )
    unresolved = list(dict.fromkeys(unresolved))
    status = (
        "partial"
        if current_claim_ids and unresolved
        else "complete"
        if current_claim_ids
        else "unresolved"
    )
    input_hash = _hash(
        {
            "policy": POLICY_VERSION,
            "evidence": sorted(current_evidence_ids),
            "claims": sorted(current_claim_ids),
            "unresolved": unresolved,
        }
    )
    if previous_run is None or previous_run.input_hash != input_hash or added:
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash=input_hash,
                policy_version=POLICY_VERSION,
                evidence_ids=current_evidence_ids,
                claim_ids=current_claim_ids,
                status=status,
                documents_checked=len(documents),
                candidates_added=added,
                unresolved=unresolved,
                created_at=now,
            )
        )
    session.flush()
    from gridlens.intelligence.identity_reconciliation import ensure_project_scoped_identity_links

    ensure_project_scoped_identity_links(session, current_claim_ids)
    # Queue bounded account research after identity reconciliation.  Queueing is
    # best-effort: discovery must never make source ingestion fail.
    if settings.company_contact_discovery_enabled:
        try:
            from gridlens.intelligence.company_contact_discovery import discover_company_contacts

            with session.begin_nested():
                company_ids = set(
                    session.scalars(
                        select(BuyingChainIdentityLink.company_identity_id).where(
                            BuyingChainIdentityLink.claim_id.in_(
                                [UUID(value) for value in current_claim_ids]
                            ),
                            BuyingChainIdentityLink.entity_type == "company",
                            BuyingChainIdentityLink.state == "current",
                        )
                    )
                )
                for company_id in company_ids:
                    if company_id is not None:
                        discover_company_contacts(session, company_id)
        except Exception:
            # The primary evidence transaction remains authoritative; a future
            # planner/replay can recover a missed discovery enqueue.
            pass
    session.flush()
    retained_after = _retained(session, project)
    if retained_after:
        from gridlens.intelligence.change_detection import record_material_diff

        # Contractor and buyer deltas are supported by the immutable buying-chain
        # document version, not an unrelated retained permit used to select this project.
        semantic_fields = (
            "organization",
            "person_name",
            "title",
            "category",
            "organization_relationship",
            "person_project_relationship",
        )

        def semantic_key(row: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(row.get(key) for key in semantic_fields)

        def support_for(field: str) -> list[BuyingChainEvidence]:
            # Match the complete semantic rows emitted by material_state.
            # Organization-only matching can cite an unchanged role at the
            # same organization when a different role changes.
            def field_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
                return [
                    row
                    for row in view["candidates"]
                    if not row.get("stale")
                    and (
                        field != "contractor"
                        or row.get("category")
                        in {"contractor", "electrical_contractor", "epc", "general_contractor"}
                    )
                ]

            after_rows = [
                row for row in field_rows(buying_chain_view(session, project.id, now=now))
            ]
            before_rows = [row for row in field_rows(buying_chain_baseline)]
            removed = Counter(map(semantic_key, before_rows)) - Counter(
                map(semantic_key, after_rows)
            )
            added = Counter(map(semantic_key, after_rows)) - Counter(map(semantic_key, before_rows))
            if not removed and not added:
                return []

            checked = {
                source.url: source
                for source in saved.values()
                if source.id != prior_versions.get(source.url)
            }
            causes: dict[UUID, BuyingChainEvidence] = {}
            for row in after_rows:
                if added[semantic_key(row)] <= 0:
                    continue
                for citation in row.get("evidence", []):
                    if not citation.get("current_support"):
                        continue
                    source = session.get(BuyingChainEvidence, citation.get("id"))
                    if (
                        source is not None
                        and (current := checked.get(source.url)) is not None
                        and current.id == source.id
                    ):
                        causes[source.id] = source
            for row in before_rows:
                if removed[semantic_key(row)] <= 0:
                    continue
                for citation in row.get("evidence", []):
                    if not citation.get("current_support"):
                        continue
                    source = session.get(BuyingChainEvidence, citation.get("id"))
                    if source is not None and (replacement := checked.get(source.url)) is not None:
                        # A checked same-URL version, rather than the old citation,
                        # supports a withdrawal when the source changed its claim.
                        causes[replacement.id] = replacement
            return sorted(causes.values(), key=lambda row: (row.url, str(row.id)))

        support: dict[str, list[BuyingChainEvidence]] = {}
        for field in ("contractor", "buyer"):
            field_sources = support_for(field)
            if field_sources:
                support[field] = field_sources
        record_material_diff(
            session, project, retained_after[0], material_baseline, buying_evidence=support
        )
    return buying_chain_view(session, project.id, now=now)


def _apply_contact_privacy(session: Session, candidates: list[dict]) -> None:
    """Apply one bounded privacy ledger snapshot to a read cohort."""
    if not candidates:
        return
    from gridlens.intelligence.contact_suppressions import (
        _ledger_states,
        company_suppression_key,
        global_method_suppression_key,
        global_person_suppression_key,
        method_suppression_key,
        person_suppression_key,
    )

    claim_ids = [item["id"] for item in candidates]
    links = session.scalars(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id.in_(claim_ids),
            BuyingChainIdentityLink.state == "current",
            BuyingChainIdentityLink.entity_type.in_(("company", "person")),
        )
    ).all()
    company_by_claim = {
        row.claim_id: row.company_identity_id
        for row in links
        if row.entity_type == "company" and row.company_identity_id is not None
    }
    person_by_claim = {
        row.claim_id: row.person_identity_id
        for row in links
        if row.entity_type == "person" and row.person_identity_id is not None
    }
    candidate_scope: dict[UUID, tuple[UUID | None, str]] = {}
    keys: set[tuple[str, str]] = set()
    for item in candidates:
        company_id = company_by_claim.get(item["id"])
        name = item.get("person_name") or ""
        person_id = person_by_claim.get(item["id"])
        candidate_scope[item["id"]] = (company_id, name)
        if company_id is not None:
            keys.add(("company", company_suppression_key(company_id)))
            if name:
                keys.add(("person", person_suppression_key(company_id, name)))
        if person_id is not None:
            keys.add(("person", global_person_suppression_key(person_id)))
        for contact_field in ("public_contacts", "reported_contacts"):
            for contact in item.get(contact_field, []):
                kind, value = str(contact.get("kind") or ""), str(contact.get("value") or "")
                keys.add(("method", global_method_suppression_key(kind, value)))
                if company_id is not None:
                    keys.add(("method", method_suppression_key(company_id, name, kind, value)))
    states = _ledger_states(session, keys)
    for item in candidates:
        company_id, name = candidate_scope[item["id"]]
        person_id = person_by_claim.get(item["id"])
        suppressed_subject = (
            bool(
                company_id is not None
                and states.get(("company", company_suppression_key(company_id))) == "suppress"
            )
            or bool(
                company_id is not None
                and name
                and states.get(("person", person_suppression_key(company_id, name))) == "suppress"
            )
            or bool(
                person_id is not None
                and states.get(("person", global_person_suppression_key(person_id))) == "suppress"
            )
        )
        if suppressed_subject:
            item["suppressed"] = True
            item["person_name"] = None
            item["title"] = None
            item["reason"] = "Contact assertion suppressed by an internal privacy control."
            item["public_contacts"] = []
            item["reported_contacts"] = []
            item["evidence"] = []
            item["correction_history"] = []
            continue
        hidden_values: list[str] = []
        for contact_field in ("public_contacts", "reported_contacts"):
            visible = []
            for contact in item.get(contact_field, []):
                kind, value = str(contact.get("kind") or ""), str(contact.get("value") or "")
                global_key = global_method_suppression_key(kind, value)
                scoped_key = (
                    method_suppression_key(company_id, name, kind, value) if company_id else None
                )
                hidden = states.get(("method", global_key)) == "suppress" or (
                    scoped_key is not None and states.get(("method", scoped_key)) == "suppress"
                )
                if hidden:
                    if value:
                        hidden_values.append(value.casefold())
                else:
                    visible.append(contact)
            item[contact_field] = visible
        if hidden_values:

            def scrub(value, hidden=tuple(hidden_values)):
                if isinstance(value, str):
                    return "" if any(term in value.casefold() for term in hidden) else value
                if isinstance(value, list):
                    return [scrub(part, hidden) for part in value]
                if isinstance(value, dict):
                    return {key: scrub(part, hidden) for key, part in value.items()}
                return value

            item["evidence"] = scrub(item.get("evidence", []))
            item["reason"] = scrub(item.get("reason", ""))
            item["correction_history"] = scrub(item.get("correction_history", []))
            item["correction_history"] = [
                {
                    **row,
                    "values": {
                        key: value
                        for key, value in row.get("values", {}).items()
                        if key != "public_contact_value"
                    },
                }
                for row in item.get("correction_history", [])
            ]


def buying_chain_views(
    session: Session, project_ids: set[UUID], *, now: datetime | None = None
) -> dict[str, dict]:
    """Bulk-load the canonical selected-project buying-chain projections."""
    if not project_ids:
        return {}
    projects = {
        project.id: project
        for project in session.scalars(select(Project).where(Project.id.in_(project_ids)))
    }
    preload = BuyingChainViewPreload()

    ranked_runs = (
        select(
            BuyingChainRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=BuyingChainRun.project_id,
                order_by=(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc()),
            )
            .label("run_rank"),
        )
        .where(BuyingChainRun.project_id.in_(project_ids))
        .subquery()
    )
    for run_row in session.scalars(
        select(BuyingChainRun)
        .join(ranked_runs, ranked_runs.c.run_id == BuyingChainRun.id)
        .where(ranked_runs.c.run_rank <= 10)
        .order_by(
            BuyingChainRun.project_id,
            BuyingChainRun.created_at.desc(),
            BuyingChainRun.id.desc(),
        )
    ):
        preload.runs[run_row.project_id].append(run_row)
    for claim_row in session.scalars(
        select(BuyingChainClaim)
        .where(BuyingChainClaim.project_id.in_(project_ids))
        .order_by(BuyingChainClaim.created_at.desc(), BuyingChainClaim.id.desc())
    ):
        preload.claims[claim_row.project_id].append(claim_row)
    from gridlens.persistence.models import BuyingChainCorrection

    for correction_row in session.scalars(
        select(BuyingChainCorrection)
        .where(BuyingChainCorrection.project_id.in_(project_ids))
        .order_by(BuyingChainCorrection.created_at, BuyingChainCorrection.id)
    ):
        preload.corrections[correction_row.project_id].append(correction_row)
    for source_row in session.scalars(
        select(BuyingChainEvidence)
        .where(BuyingChainEvidence.project_id.in_(project_ids))
        .order_by(BuyingChainEvidence.last_seen_at.desc(), BuyingChainEvidence.id.desc())
    ):
        preload.sources[source_row.project_id].append(source_row)
    for detail_row in session.scalars(
        select(BuyingChainEvidence)
        .where(
            BuyingChainEvidence.project_id.in_(project_ids),
            BuyingChainEvidence.retained_evidence_id.is_(None),
            BuyingChainEvidence.url.like("https://cohtora.houstontx.gov/ibi_apps/WFServlet.ibfs%"),
        )
        .order_by(BuyingChainEvidence.last_seen_at.desc())
    ):
        preload.permit_details[detail_row.project_id].append(detail_row)

    linked_project_observations = (
        select(
            PowerNeed.project_id.label("project_id"),
            NeedObservation.observation_id.label("observation_id"),
        )
        .select_from(NeedObservation)
        .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
        .where(PowerNeed.project_id.in_(project_ids))
    )
    direct_project_observations = (
        select(
            Project.id.label("project_id"),
            Observation.id.label("observation_id"),
        )
        .select_from(Project)
        .join(
            Observation,
            and_(
                Observation.source_id == Project.source_id,
                Observation.external_id == Project.external_id,
            ),
        )
        .where(Project.id.in_(project_ids))
    )
    selected_project_observations = union(
        linked_project_observations, direct_project_observations
    ).subquery()
    retained_query = (
        select(Project, Evidence, Observation, Interpretation, Source)
        .select_from(Project)
        .join(
            selected_project_observations,
            selected_project_observations.c.project_id == Project.id,
        )
        .join(Observation, Observation.id == selected_project_observations.c.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(Project.id.in_(project_ids))
        .order_by(Project.id, Evidence.observed_at.desc(), Evidence.id)
    )
    for project, evidence, observation, interpretation, source in session.execute(
        retained_query.execution_options(yield_per=500)
    ):
        current = _retained_evidence_current_for_project(
            session,
            project,
            evidence,
            observation=observation,
            interpretation=interpretation,
            source=source,
            preloaded=True,
        )
        preload.retained_current[project.id][evidence.id] = current
        if current and len(preload.retained[project.id]) < 4:
            preload.retained[project.id].append(evidence)
            preload.retained_observations[project.id][evidence.id] = observation

    retained_reference_rows = session.execute(
        select(Project, Evidence, Observation, Interpretation, Source)
        .select_from(Project)
        .join(BuyingChainEvidence, BuyingChainEvidence.project_id == Project.id)
        .join(Evidence, Evidence.id == BuyingChainEvidence.retained_evidence_id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(
            Project.id.in_(project_ids),
            BuyingChainEvidence.retained_evidence_id.is_not(None),
        )
        .distinct()
        .execution_options(yield_per=500)
    )
    for project, evidence, observation, interpretation, source in retained_reference_rows:
        preload.retained_source_ids[project.id][evidence.id] = observation.source_id
        if evidence.id not in preload.retained_current[project.id]:
            preload.retained_current[project.id][evidence.id] = (
                _retained_evidence_current_for_project(
                    session,
                    project,
                    evidence,
                    observation=observation,
                    interpretation=interpretation,
                    source=source,
                    preloaded=True,
                )
            )

    views = {
        str(project_id): buying_chain_view(
            session,
            project_id,
            now=now,
            preload=preload,
            include_identity_ids=False,
            _apply_privacy=False,
        )
        for project_id in project_ids
        if project_id in projects
    }
    _apply_contact_privacy(
        session,
        [candidate for view in views.values() for candidate in view.get("candidates", [])],
    )
    _attach_identity_ids(session, list(views.values()))
    return views


def buying_chain_view(
    session: Session,
    project_id: UUID,
    *,
    now: datetime | None = None,
    history: bool = False,
    preload: BuyingChainViewPreload | None = None,
    include_identity_ids: bool = True,
    _apply_privacy: bool = True,
) -> dict:
    now = now or evaluation_now(datetime.now(UTC))
    project = session.get(Project, project_id)
    if project is None:
        raise LookupError("Project not found")
    runs = (
        preload.runs.get(project_id, [])
        if preload
        else session.scalars(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project_id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
            .limit(10)
        ).all()
    )
    claims = (
        preload.claims.get(project_id, [])
        if preload
        else session.scalars(
            select(BuyingChainClaim)
            .where(BuyingChainClaim.project_id == project_id)
            .order_by(BuyingChainClaim.created_at.desc(), BuyingChainClaim.id.desc())
        ).all()
    )
    sources = (
        preload.sources.get(project_id, [])
        if preload
        else session.scalars(
            select(BuyingChainEvidence)
            .where(BuyingChainEvidence.project_id == project_id)
            .order_by(BuyingChainEvidence.last_seen_at.desc(), BuyingChainEvidence.id.desc())
        ).all()
    )
    by_id = {str(row.id): row for row in sources}
    active_run = runs[0] if runs else None
    newest_by_url = _newest_source_by_url(sources, active_run)
    grouped: dict[str, list[BuyingChainClaim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.entity_key].append(claim)

    current_claim_ids = set(runs[0].claim_ids) if runs else set()

    def retained_source_current(source: BuyingChainEvidence) -> bool:
        if source.retained_evidence_id is None:
            return True
        if preload is not None:
            return preload.retained_current.get(project_id, {}).get(
                source.retained_evidence_id, False
            )
        original = session.get(Evidence, source.retained_evidence_id)
        return bool(original and _retained_evidence_current_for_project(session, project, original))

    def retained_source_id(source: BuyingChainEvidence) -> str | None:
        retained_id = source.retained_evidence_id
        if retained_id is None:
            return None
        if preload is not None:
            return preload.retained_source_ids.get(project_id, {}).get(retained_id)
        original = session.get(Evidence, retained_id)
        observation = session.get(Observation, original.observation_id) if original else None
        return observation.source_id if observation else None

    selected = claims if history else [row for row in claims if str(row.id) in current_claim_ids]
    candidates: list[dict[str, Any]] = []
    for claim in selected:
        evidence = []
        stale = False
        organization_stale = False
        role_stale = False
        current_supports: set[str] = set()
        invalid_supports: set[str] = set()
        current_contacts: set[tuple[str, str]] = set()
        current_organization_quotes: list[str] = []
        organization_support = False
        role_support = False
        for citation in claim.citations:
            row = by_id.get(citation["evidence_id"])
            if row is None or citation["quote"] not in row.excerpt:
                stale = True
                invalid_supports.add(citation["supports"])
                continue
            if not history and not retained_source_current(row):
                invalid_supports.add(citation["supports"])
                continue
            newest = by_id[str(newest_by_url[row.url])]
            source_superseded = newest.id != row.id and citation["quote"] not in newest.excerpt
            age_basis = row.published_at or row.last_seen_at.date()
            role_aged = (
                citation["supports"] in {"organization_person_role", "person_project_assignment"}
                and (now.date() - age_basis).days > ROLE_MAX_AGE_DAYS
            )
            contact_aged = (
                citation["supports"] == "public_contact"
                and (now.date() - row.last_seen_at.date()).days > CONTACT_MAX_AGE_DAYS
            )
            if row.retained_evidence_id:
                original = (
                    None if preload is not None else session.get(Evidence, row.retained_evidence_id)
                )
                # The accepted observation version is authoritative for retained
                # fields. Native lines and earlier live JSON use different quote
                # formats; a later research fetch cannot retract accepted evidence.
                source_superseded = (
                    not preload.retained_current.get(project_id, {}).get(
                        row.retained_evidence_id, False
                    )
                    if preload is not None
                    else not (
                        original
                        and _retained_evidence_current_for_project(session, project, original)
                    )
                )
            if citation["supports"] in {"project_organization", "organization_category"}:
                organization_stale = organization_stale or source_superseded
            elif citation["supports"] != "person_project_assignment":
                role_stale = role_stale or source_superseded or role_aged
            # Assignment freshness is independent of a newly verified employment role.
            stale = stale or source_superseded or role_aged
            if source_superseded or role_aged or contact_aged:
                invalid_supports.add(citation["supports"])
            if not source_superseded and not role_aged and not contact_aged:
                current_supports.add(citation["supports"])
                if citation["supports"] in {"project_organization", "organization_category"}:
                    current_organization_quotes.append(citation["quote"])
                if citation["supports"] == "public_contact":
                    current_contacts.add((citation["url"], citation["quote"]))
            evidence.append(
                {
                    "id": row.id,
                    "retained_evidence_id": (
                        str(row.retained_evidence_id) if row.retained_evidence_id else None
                    ),
                    "source_id": retained_source_id(row),
                    "public_research_provenance": has_public_research_provenance(row),
                    "url": row.url,
                    "quote": citation["quote"],
                    "supports": citation["supports"],
                    "extraction_location": row.extraction_location,
                    "published_at": row.published_at,
                    "observed_at": row.observed_at,
                    "content_hash": row.content_hash,
                    "current_source_version_id": newest_by_url[row.url],
                    "current_support": not source_superseded and not role_aged and not contact_aged,
                    "contact_stale": contact_aged and not source_superseded,
                }
            )
        if not history:
            if not evidence:
                continue
            if invalid_supports:
                organization_support = bool(
                    current_supports
                    & {
                        "project_organization",
                        "organization_category",
                    }
                )
                role_support = "organization_person_role" in current_supports
                organization_stale = not organization_support
                role_stale = bool(claim.person_name) and not role_support
                stale = organization_stale or role_stale
                if not organization_support and not role_support:
                    continue
        independent_conflict = False
        if claim.person_name and not history:
            role_urls = {
                c["url"]
                for c in claim.citations
                if c["supports"] == "organization_person_role"
                and (source := by_id.get(c["evidence_id"])) is not None
                and retained_source_current(source)
            }
            for prior in grouped[claim.entity_key]:
                if normalized_identity(prior.title) == normalized_identity(claim.title):
                    continue
                for prior_citation in prior.citations:
                    if (
                        prior_citation["supports"] != "organization_person_role"
                        or prior_citation["url"] in role_urls
                    ):
                        continue
                    prior_source = by_id.get(prior_citation["evidence_id"])
                    if prior_source is None:
                        continue
                    if not retained_source_current(prior_source):
                        continue
                    current_source = by_id[str(newest_by_url[prior_source.url])]
                    if not retained_source_current(current_source):
                        continue
                    age = (
                        now.date() - (prior_source.published_at or prior_source.last_seen_at.date())
                    ).days
                    if (
                        age > ROLE_MAX_AGE_DAYS
                        or prior_citation["quote"] not in current_source.excerpt
                    ):
                        continue
                    independent_conflict = role_stale = stale = True
                    evidence.append(
                        {
                            "id": prior_source.id,
                            "retained_evidence_id": (
                                str(prior_source.retained_evidence_id)
                                if prior_source.retained_evidence_id
                                else None
                            ),
                            "source_id": retained_source_id(prior_source),
                            "public_research_provenance": has_public_research_provenance(
                                prior_source
                            ),
                            "url": prior_source.url,
                            "quote": prior_citation["quote"],
                            "supports": "conflicting_organization_person_role",
                            "extraction_location": prior_source.extraction_location,
                            "published_at": prior_source.published_at,
                            "observed_at": prior_source.observed_at,
                            "content_hash": prior_source.content_hash,
                        }
                    )
        category = claim.category
        project_relationship = claim.person_project_relationship
        if invalid_supports and not history:
            category_supported = "organization_category" in current_supports or any(
                category.value == claim.category
                and re.search(rf"\b{re.escape(term)}\b", quote, re.I)
                for quote in current_organization_quotes
                for term, category in _ROLE_WORDS.items()
            )
            if not category_supported:
                category = "unknown"
            if not organization_support or (claim.person_name and not role_support):
                project_relationship = "UNKNOWN"
            elif (
                project_relationship == "DIRECT"
                and "person_project_assignment" in invalid_supports
                and "person_project_assignment" not in current_supports
            ):
                project_relationship = "ROLE_SUPPORTED"
        candidates.append(
            {
                "id": claim.id,
                "fingerprint": claim.fingerprint,
                "organization": claim.organization,
                "person_name": claim.person_name,
                "title": claim.title,
                "category": category,
                "organization_relationship": "UNKNOWN"
                if organization_stale
                else claim.organization_relationship,
                "person_organization_relationship": "UNKNOWN"
                if role_stale
                else claim.person_organization_relationship,
                "person_project_relationship": "UNKNOWN" if stale else project_relationship,
                "evidence_strength": "Low" if stale else claim.evidence_strength,
                "reason": (
                    "Conflicting independent role evidence; "
                    "current role and assignment are UNKNOWN."
                )
                if independent_conflict
                else "Aged or superseded evidence; affected relationships are UNKNOWN. "
                + claim.reason
                if stale
                else claim.reason,
                "observed_at": claim.observed_at,
                "verified_at": claim.verified_at,
                "public_contacts": (
                    [
                        contact
                        for contact in claim.public_contacts
                        if (contact.get("source_url"), contact.get("quote")) in current_contacts
                    ]
                    if invalid_supports and not history and (not claim.person_name or role_support)
                    else []
                    if invalid_supports and not history
                    else claim.public_contacts
                ),
                "evidence": evidence,
                "history_count": len(grouped[claim.entity_key]),
                "stale": stale,
            }
        )
    candidates.sort(
        key=lambda item: (
            CATEGORY_PRIORITY.get(item["category"], 99),
            item["person_name"] is None,
            item["organization"],
            item["person_name"] or "",
        )
    )
    from gridlens.intelligence.buying_chain_corrections import overlay_corrections

    overlay_corrections(
        session,
        project_id,
        candidates,
        history,
        decisions=preload.corrections.get(project_id, []) if preload else None,
    )
    if _apply_privacy:
        _apply_contact_privacy(session, candidates)
    candidates = [item for item in candidates if history or not item.get("retracted")]
    # Reuse the latest-run selection loaded above for bounded multi-project reads.
    unresolved = (
        list(active_run.unresolved)
        if active_run
        else ["Buying chain has not been researched for this project."]
    )
    if any(item["stale"] for item in candidates):
        unresolved.append("Some evidence is stale or superseded; verify current responsibility.")
    result = {
        "project_id": project_id,
        "status": active_run.status if active_run else "not_researched",
        "candidates": candidates if history else candidates[:MAX_CANDIDATES],
        "unresolved": unresolved,
        "runs": [
            {
                "id": row.id,
                "status": row.status,
                "documents_checked": row.documents_checked,
                "candidates_added": row.candidates_added,
                "unresolved": row.unresolved,
                "created_at": row.created_at,
            }
            for row in runs
        ],
        "permit_summaries": _permit_summaries(session, project_id, preload=preload),
        "policy_version": POLICY_VERSION,
    }
    if not history and include_identity_ids:
        _attach_identity_ids(session, [result])
    return result


def _attach_identity_ids(session: Session, views: list[dict]) -> None:
    """Attach current claim IDs with one batched link read and no contact aggregation."""
    from gridlens.intelligence.buying_chain_corrections import _ordered_correction_chain

    candidates = [
        candidate
        for view in views
        for candidate in view["candidates"]
        if not candidate["stale"] and not candidate.get("correction_stale")
    ]
    claim_ids = {candidate["id"] for candidate in candidates}
    if not claim_ids:
        return
    by_claim = {candidate["id"]: candidate for candidate in candidates}
    project_by_claim = {
        candidate["id"]: UUID(str(view["project_id"]))
        for view in views
        if "project_id" in view
        for candidate in view["candidates"]
    }
    links = session.scalars(
        select(BuyingChainIdentityLink)
        .where(
            BuyingChainIdentityLink.claim_id.in_(claim_ids),
            BuyingChainIdentityLink.state == "current",
        )
        .order_by(BuyingChainIdentityLink.created_at.desc(), BuyingChainIdentityLink.id.desc())
    ).all()
    corrections = session.scalars(
        select(BuyingChainCorrection)
        .where(BuyingChainCorrection.claim_id.in_(claim_ids))
        .order_by(
            BuyingChainCorrection.created_at,
            BuyingChainCorrection.id,
        )
    ).all()
    by_correction_claim: dict[UUID, list[BuyingChainCorrection]] = defaultdict(list)
    for correction in corrections:
        by_correction_claim[correction.claim_id].append(correction)
    ordered_by_claim = {
        claim_id: _ordered_correction_chain(str(by_claim[claim_id]["fingerprint"]), rows)
        for claim_id, rows in by_correction_claim.items()
    }
    seen: set[tuple[UUID, str]] = set()
    identity_supports = {
        "company": {"project_organization"},
        "person": {"organization_person_role", "person_project_assignment"},
    }
    for link in links:
        key = (link.claim_id, link.entity_type)
        if key in seen:
            continue
        seen.add(key)
        supported_by = identity_supports.get(link.entity_type)
        identity_value = (
            link.company_identity_id if link.entity_type == "company" else link.person_identity_id
        )
        if not supported_by or identity_value is None:
            continue
        candidate = by_claim[link.claim_id]
        correction_chain = ordered_by_claim.get(link.claim_id, [])
        if correction_chain is None:
            continue
        invalidated = False
        explicit_rebind: tuple[str, str] | None = None
        for correction in correction_chain:
            if correction.source_evidence_id is not None and not any(
                str(item.get("id")) == str(correction.source_evidence_id)
                and str(item.get("current_source_version_id")) == str(correction.source_evidence_id)
                and item.get("content_hash") == correction.source_version_hash
                and item.get("current_support")
                for item in candidate["evidence"]
            ):
                continue
            values = correction.values
            subject_field = "organization" if link.entity_type == "company" else "person_name"
            if subject_field in values:
                invalidated = True
                explicit_rebind = None
            reference = values.get("identity_reference")
            if (
                isinstance(reference, dict)
                and reference.get("type") == link.entity_type
                and reference.get("id")
                and correction.source_evidence_id is not None
            ):
                invalidated = False
                explicit_rebind = (str(reference["id"]), str(correction.source_evidence_id))
        identity_id = str(identity_value)
        if invalidated or (
            explicit_rebind is not None
            and (
                explicit_rebind[0] != identity_id
                or explicit_rebind[1] != str(link.source_evidence_id)
            )
        ):
            continue
        if not any(
            str(item["id"]) == str(link.source_evidence_id)
            and str(item.get("current_source_version_id")) == str(link.source_evidence_id)
            and item.get("content_hash") == link.source_version_hash
            and item.get("current_support")
            and item.get("supports") in supported_by
            for item in candidate["evidence"]
        ):
            continue
        if link.entity_type == "company" and getattr(link, "basis", None) == "current_membership":
            from gridlens.intelligence.identity_reconciliation import membership_supports_claim

            if link.claim_id not in project_by_claim:
                continue
            source = session.get(BuyingChainEvidence, link.source_evidence_id)
            retained_id = source.retained_evidence_id if source else None
            membership = (
                session.scalar(
                    select(CompanyProjectMembership)
                    .where(
                        CompanyProjectMembership.project_id == project_by_claim[link.claim_id],
                        CompanyProjectMembership.company_identity_id == link.company_identity_id,
                        CompanyProjectMembership.source_evidence_id == retained_id,
                        CompanyProjectMembership.state == "current",
                    )
                    .limit(1)
                )
                if retained_id
                else None
            )
            retained = session.get(Evidence, retained_id) if retained_id else None
            linked_claim = session.get(BuyingChainClaim, link.claim_id)
            if (
                membership is None
                or retained is None
                or source is None
                or linked_claim is None
                or membership.source_version_hash != retained.content_hash
                or not membership_supports_claim(
                    linked_claim,
                    candidate,
                    membership,
                    source.id,
                    [
                        peer
                        for view in views
                        if str(view.get("project_id")) == str(project_by_claim[link.claim_id])
                        for peer in view["candidates"]
                        if not peer.get("stale")
                    ],
                )
            ):
                continue
        candidate[f"{link.entity_type}_identity_id"] = identity_id


def _permit_summaries(
    session: Session, project_id: UUID, *, preload: BuyingChainViewPreload | None = None
) -> list[dict]:
    project = session.get(Project, project_id)
    if project is None:
        return []
    summaries: list[dict[str, Any]] = []
    retained = preload.retained.get(project_id, []) if preload else _retained(session, project)
    for evidence in retained:
        observation = (
            preload.retained_observations.get(project_id, {}).get(evidence.id)
            if preload
            else session.get(Observation, evidence.observation_id)
        )
        if observation is None:
            continue
        facts = permit_facts(observation.source_id, evidence.abstract or "")
        if facts:
            summaries.append(
                {
                    "evidence_id": evidence.id,
                    "source_id": observation.source_id,
                    "url": evidence.url,
                    "title": evidence.title,
                    "observed_at": evidence.observed_at,
                    "extraction_location": evidence.extraction_location,
                    "facts": facts,
                }
            )
    if project.source_id == "houston-weekly-permits":
        primary = next(
            (item for item in summaries if item["source_id"] == project.source_id),
            None,
        )
        if primary:
            primary_facts = {item["label"]: item["value"] for item in primary["facts"]}
            detail_rows = (
                preload.permit_details.get(project_id, [])
                if preload
                else session.scalars(
                    select(BuyingChainEvidence)
                    .where(
                        BuyingChainEvidence.project_id == project.id,
                        BuyingChainEvidence.retained_evidence_id.is_(None),
                        BuyingChainEvidence.url.like(
                            "https://cohtora.houstontx.gov/ibi_apps/WFServlet.ibfs%"
                        ),
                    )
                    .order_by(BuyingChainEvidence.last_seen_at.desc())
                )
            )
            for detail in detail_rows:
                query = parse_qs(urlsplit(detail.url).query)
                details = permit_facts(project.source_id, detail.excerpt)
                fields = {item["label"]: item["value"] for item in details}
                expected_type_code = SUPPORTED_TYPES.get(primary_facts.get("Permit type", ""))
                if (
                    query.get("PN") != [primary_facts.get("Source record")]
                    or not expected_type_code
                    or query.get("PT") != [expected_type_code]
                    or fields.get("Houston exact permit project number")
                    != primary_facts.get("Source record")
                    or response_type_code(fields.get("Permit type code", "")) != expected_type_code
                    or fields.get("Houston sold permit detail date")
                    != primary_facts.get("Permit sale event date (weekly report)")
                    or not fields.get("Permit job address", "")
                    .casefold()
                    .startswith(primary_facts.get("Site address", "").casefold())
                ):
                    continue
                summaries.append(
                    {
                        "evidence_id": detail.id,
                        "source_id": project.source_id,
                        "url": detail.url,
                        "title": detail.title,
                        "observed_at": detail.last_seen_at,
                        "extraction_location": detail.extraction_location,
                        "facts": details,
                    }
                )
    return summaries
