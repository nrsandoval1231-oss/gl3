"""Bounded, evidence-first company contact discovery jobs.

URLs are only public-page hints.  A job never accepts a contact on its own;
the existing buying-chain pass remains the only append-only claim writer.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, func, or_, select, union
from sqlalchemy.orm import Session

from gridlens.domain.pursuit_research import fingerprint
from gridlens.domain.pursuit_research import fingerprint as _hash
from gridlens.ingestion.adapters.buying_chain_public import (
    PublicDocument,
    retrieve,
    validate_public_url,
)
from gridlens.intelligence.buying_chain import (
    _entity_key,
    _retained_evidence_current_for_project,
    _store_document,
    buying_chain_view,
)
from gridlens.intelligence.buying_chain_extraction import (
    Extracted,
    extract_company_contacts,
    extract_people,
)
from gridlens.intelligence.company_contacts import company_contacts, relevant_named_contact
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    Job,
    LogicalCall,
    PowerNeed,
    Project,
)
from gridlens.settings import settings

JOB_KIND = "company_contact_discovery"
TASK_TYPE = "company_contact_discovery"
MAX_CANDIDATE_URLS = 4
MAX_ANCHOR_PROJECTS = 16
MAX_SECONDS = 35
CONTACT_PLANNER_RETRY_DAYS = 7
CONTACT_PLANNER_REFRESH_DAYS = 30
MAX_COMPANY_SCAN_PER_PLAN = 500
POLICY_VERSION = "company-contact-discovery-v12"


def _projects(session: Session, company_identity_id: UUID) -> list[Project]:
    eligible = select(Project.id).where(
        Project.region_status == "ELIGIBLE",
        select(PowerNeed.id)
        .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
        .exists(),
    )
    return list(
        session.scalars(
            select(Project)
            .where(
                Project.id.in_(
                    union(
                        select(CompanyProjectMembership.project_id).where(
                            CompanyProjectMembership.company_identity_id == company_identity_id,
                            CompanyProjectMembership.state == "current",
                        ),
                        select(BuyingChainClaim.project_id)
                        .join(
                            BuyingChainIdentityLink,
                            BuyingChainIdentityLink.claim_id == BuyingChainClaim.id,
                        )
                        .where(
                            BuyingChainIdentityLink.company_identity_id == company_identity_id,
                            BuyingChainIdentityLink.state == "current",
                        ),
                    )
                ),
                Project.id.in_(eligible),
            )
            .order_by(Project.id)
        ).all()
    )


def _select_anchor_project(
    session: Session, projects: list[Project], company_id: UUID
) -> Project | None:
    """Find a bounded current cited relationship before any network request."""
    for project in projects[:MAX_ANCHOR_PROJECTS]:
        memberships = session.scalars(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.company_identity_id == company_id,
                CompanyProjectMembership.state == "current",
            )
        ).all()
        if len(memberships) == 1:
            membership = memberships[0]
            competing = session.scalar(
                select(CompanyProjectMembership.id)
                .where(
                    CompanyProjectMembership.project_id == project.id,
                    CompanyProjectMembership.company_identity_id != company_id,
                    CompanyProjectMembership.state.in_(("current", "conflicted")),
                )
                .limit(1)
            )
            evidence = session.get(Evidence, membership.source_evidence_id)
            if (
                competing is None
                and evidence is not None
                and evidence.content_hash == membership.source_version_hash
                and _retained_evidence_current_for_project(session, project, evidence)
            ):
                return project
        elif not memberships:
            view = buying_chain_view(session, project.id)
            if any(
                str(item.get("company_identity_id")) == str(company_id)
                and not item.get("stale")
                and any(
                    c.get("supports") == "project_organization" and c.get("current_support")
                    for c in item["evidence"]
                )
                for item in view["candidates"]
            ):
                return project
    return None


def _checkpoint_outcome_time(checkpoint: dict, fallback: datetime, now: datetime) -> datetime:
    raw = (
        checkpoint.get("completed_at")
        or checkpoint.get("planned_at")
        or checkpoint.get("queued_at")
    )
    if isinstance(raw, str):
        try:
            fallback = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    fallback = fallback.replace(tzinfo=UTC) if fallback.tzinfo is None else fallback.astimezone(UTC)
    return min(fallback, now)


def _unresolved_retry_at(checkpoint: dict, outcome_at: datetime) -> datetime:
    retry_after = checkpoint.get("retry_after")
    if isinstance(retry_after, str):
        try:
            parsed = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
        except ValueError:
            parsed = outcome_at + timedelta(days=CONTACT_PLANNER_RETRY_DAYS)
        else:
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        return parsed
    reason = " ".join(
        str(value)
        for value in (
            checkpoint.get("reason"),
            checkpoint.get("discovery_reason"),
            checkpoint.get("results"),
        )
    ).casefold()
    days = (
        CONTACT_PLANNER_REFRESH_DAYS
        if any(
            term in reason
            for term in (
                "disabled",
                "unconfigured",
                "not enabled",
                "retry_exhausted",
                "retries_exhausted",
            )
        )
        else CONTACT_PLANNER_RETRY_DAYS
    )
    return outcome_at + timedelta(days=days)


def discover_company_contacts(
    session: Session,
    company_identity_id: UUID,
    *,
    candidate_urls: tuple[str, ...] | list[str] = (),
    now: datetime | None = None,
) -> dict:
    """Idempotently enqueue discovery; it intentionally performs no network I/O."""
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    urls = list(dict.fromkeys(validate_public_url(url) for url in candidate_urls))
    if len(urls) > MAX_CANDIDATE_URLS:
        raise ValueError(f"At most {MAX_CANDIDATE_URLS} candidate URLs are allowed")
    projects = _projects(session, company_identity_id)
    if not projects:
        return {"status": "unresolved", "reason": "no_current_eligible_membership", "job_id": None}
    anchor = _select_anchor_project(session, projects, company_identity_id)
    if anchor is None:
        return {
            "status": "unresolved",
            "reason": "no_current_source_backed_company_claim",
            "job_id": None,
        }
    session.scalar(select(func.pg_advisory_xact_lock(company_identity_id.int % (2**63 - 1))))
    existing = session.scalars(
        select(Job)
        .where(Job.kind == JOB_KIND, Job.target_id == company_identity_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(30)
    ).all()
    latest_job = max(
        existing,
        key=lambda job: (_outcome_time(job, _load_checkpoint(job), now), str(job.id)),
        default=None,
    )
    latest_checkpoint = _load_checkpoint(latest_job) if latest_job is not None else {}
    refresh_due = bool(
        latest_job is not None
        and latest_job.status == "succeeded"
        and str(latest_checkpoint.get("status") or "").casefold() in {"complete", "partial"}
        and now - _outcome_time(latest_job, latest_checkpoint, now)
        >= timedelta(days=CONTACT_PLANNER_REFRESH_DAYS)
    )
    digest = fingerprint(
        {
            "company_identity_id": str(company_identity_id),
            "candidate_urls": urls,
            "anchor": _anchor_digest(session, anchor, company_identity_id),
            "refresh_epoch": now.date().toordinal() // 30,
            "refresh_due": refresh_due,
            "policy": POLICY_VERSION,
        }
    )
    matching_failures = 0
    for job in existing:
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (TypeError, ValueError):
            continue
        if checkpoint.get("request_digest") == digest:
            if job.status in {"queued", "running"}:
                return {
                    "status": checkpoint.get("status", job.status),
                    "job_id": str(job.id),
                    "deduplicated": True,
                }
            if job.status == "succeeded":
                status = str(checkpoint.get("status") or "").casefold()
                outcome_at = _checkpoint_outcome_time(checkpoint, job.created_at, now)
                if status in {"complete", "partial"} and now - outcome_at < timedelta(
                    days=CONTACT_PLANNER_REFRESH_DAYS
                ):
                    return {
                        "status": status,
                        "job_id": str(job.id),
                        "deduplicated": True,
                    }
                if status == "unresolved" and now < _unresolved_retry_at(checkpoint, outcome_at):
                    return {
                        "status": status,
                        "job_id": str(job.id),
                        "deduplicated": True,
                    }
        if checkpoint.get("request_digest") == digest and job.status == "failed":
            matching_failures += 1
    if matching_failures >= 2:
        return {"status": "unresolved", "reason": "retries_exhausted", "job_id": None}
    job = Job(
        source_id=anchor.source_id,
        kind=JOB_KIND,
        target_id=company_identity_id,
        checkpoint=json.dumps(
            {
                "task_type": TASK_TYPE,
                "request_digest": digest,
                "payload": {
                    "company_identity_id": str(company_identity_id),
                    "candidate_urls": urls,
                    "refresh_due": refresh_due,
                },
                "status": "queued",
                "queued_at": now.isoformat(),
            },
            separators=(",", ":"),
        ),
    )
    session.add(job)
    session.flush()
    return {"status": "queued", "job_id": str(job.id), "deduplicated": False}


def _known_contact_urls(session: Session, company_id: UUID, projects: list[Project]) -> list[str]:
    """Reuse only source-cited contact URLs or earlier checked company pages."""
    urls: list[str] = []
    for project in projects[:4]:
        view = buying_chain_view(session, project.id)
        for item in view["candidates"]:
            if str(item.get("company_identity_id")) != str(company_id):
                continue
            for citation in item["evidence"]:
                if citation.get("supports") != "public_contact" or not (
                    citation.get("current_support") or citation.get("contact_stale")
                ):
                    continue
                urls.append(citation["url"])
    jobs = session.scalars(
        select(Job)
        .where(
            Job.kind == JOB_KIND,
            Job.target_id == company_id,
            Job.status == "succeeded",
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(8)
    ).all()
    for prior in jobs:
        try:
            checkpoint = json.loads(prior.checkpoint or "{}")
        except (TypeError, ValueError):
            continue
        if checkpoint.get("status") not in {"complete", "partial"}:
            continue
        urls.extend(checkpoint.get("checked_urls", []))
    valid: list[str] = []
    for url in urls:
        try:
            normalized = validate_public_url(url)
        except (TypeError, ValueError):
            continue
        if normalized not in valid:
            valid.append(normalized)
    return valid


def _job_time(value: datetime, now: datetime) -> datetime:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value if value <= now else now


def _load_checkpoint(job: Job) -> dict:
    try:
        return json.loads(job.checkpoint or "{}")
    except (TypeError, ValueError):
        return {}


def _outcome_time(job: Job, checkpoint: dict, now: datetime) -> datetime:
    return _checkpoint_outcome_time(checkpoint, job.created_at, now)


def _contact_planner_due(jobs: list[Job], now: datetime) -> bool:
    """Apply outcome-aware backoff; completed searches refresh on a 30-day cadence."""
    ordered = sorted(
        jobs,
        key=lambda row: (_job_time(row.created_at, now), str(row.id)),
        reverse=True,
    )
    if not ordered:
        return True
    active = next((row for row in ordered if row.status in {"queued", "running"}), None)
    if active:
        return False
    latest = ordered[0]
    checkpoint = _load_checkpoint(latest)
    outcome_at = _outcome_time(latest, checkpoint, now)
    status = str(checkpoint.get("status") or "").casefold()
    if latest.status == "failed":
        digest = checkpoint.get("request_digest")
        failed_count = sum(
            row.status == "failed"
            and _job_request_digest(row) == digest
            and (now - _outcome_time(row, _load_checkpoint(row), now)).days
            < CONTACT_PLANNER_REFRESH_DAYS
            for row in ordered
        )
        if failed_count >= 2:
            return now - outcome_at >= timedelta(days=CONTACT_PLANNER_REFRESH_DAYS)
        backoff = (1, 6, 24)[min(max(failed_count - 1, 0), 2)]
        return now - outcome_at >= timedelta(hours=backoff)
    if latest.status != "succeeded":
        return True
    if status in {"complete", "partial"}:
        return now - outcome_at >= timedelta(days=CONTACT_PLANNER_REFRESH_DAYS)
    if status == "unresolved":
        return now >= _unresolved_retry_at(checkpoint, outcome_at)
    return now - outcome_at >= timedelta(days=CONTACT_PLANNER_RETRY_DAYS)


def _job_request_digest(job: Job) -> str | None:
    return _load_checkpoint(job).get("request_digest")


def _planner_retry_after(jobs: list[Job], now: datetime) -> datetime:
    ordered = sorted(
        jobs,
        key=lambda row: (_job_time(row.created_at, now), str(row.id)),
        reverse=True,
    )
    if not ordered:
        return now + timedelta(days=CONTACT_PLANNER_RETRY_DAYS)
    latest = ordered[0]
    checkpoint = _load_checkpoint(latest)
    outcome_at = _outcome_time(latest, checkpoint, now)
    if checkpoint.get("status") == "unresolved":
        return _unresolved_retry_at(checkpoint, outcome_at)
    if latest.status == "failed":
        digest = checkpoint.get("request_digest")
        attempts = sum(
            row.status == "failed" and _job_request_digest(row) == digest for row in ordered
        )
        if attempts >= 2:
            return outcome_at + timedelta(days=CONTACT_PLANNER_REFRESH_DAYS)
        return outcome_at + timedelta(hours=1)
    if checkpoint.get("status") in {"complete", "partial"}:
        return outcome_at + timedelta(days=CONTACT_PLANNER_REFRESH_DAYS)
    return outcome_at + timedelta(days=CONTACT_PLANNER_RETRY_DAYS)


def plan_company_contact_jobs(
    session: Session, *, limit: int = 25, now: datetime | None = None
) -> int:
    """Plan a bounded number of due companies without starving later identities.

    Unresolvable companies receive an auditable terminal checkpoint and retry date.
    They do not create network jobs, and they leave the next due company selectable.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Contact planning limit must be 1..100")
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    eligible_projects = select(Project.id).where(
        Project.region_status == "ELIGIBLE",
        select(PowerNeed.id)
        .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
        .exists(),
    )
    membership_ids = select(CompanyProjectMembership.company_identity_id.label("company_id")).where(
        CompanyProjectMembership.state == "current",
        CompanyProjectMembership.project_id.in_(eligible_projects),
    )
    claim_ids = (
        select(BuyingChainIdentityLink.company_identity_id.label("company_id"))
        .join(BuyingChainClaim, BuyingChainClaim.id == BuyingChainIdentityLink.claim_id)
        .where(
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.state == "current",
            BuyingChainIdentityLink.company_identity_id.is_not(None),
            BuyingChainClaim.project_id.in_(eligible_projects),
        )
    )
    candidates = union(membership_ids, claim_ids).subquery()
    completed_checkpoint = or_(
        Job.checkpoint.like('%"status":"complete"%'),
        Job.checkpoint.like('%"status": "complete"%'),
        Job.checkpoint.like('%"status":"partial"%'),
        Job.checkpoint.like('%"status": "partial"%'),
    )
    unresolved_checkpoint = or_(
        Job.checkpoint.like('%"status":"unresolved"%'),
        Job.checkpoint.like('%"status": "unresolved"%'),
    )
    disabled_checkpoint = or_(
        Job.checkpoint.ilike("%disabled%"),
        Job.checkpoint.ilike("%unconfigured%"),
        Job.checkpoint.ilike("%not enabled%"),
        Job.checkpoint.ilike("%retries_exhausted%"),
    )
    not_due = (
        select(Job.id)
        .where(
            Job.kind == JOB_KIND,
            Job.target_id == candidates.c.company_id,
            or_(
                Job.status.in_(("queued", "running")),
                and_(
                    Job.status == "succeeded",
                    Job.available_at > now,
                    Job.checkpoint.like('%"planner_receipt":true%'),
                ),
                and_(
                    Job.status == "succeeded",
                    Job.created_at > now - timedelta(days=CONTACT_PLANNER_REFRESH_DAYS),
                    completed_checkpoint,
                ),
                and_(
                    Job.status == "succeeded",
                    Job.created_at >= now - timedelta(days=CONTACT_PLANNER_RETRY_DAYS),
                    unresolved_checkpoint,
                    ~disabled_checkpoint,
                ),
                and_(
                    Job.status == "succeeded",
                    Job.created_at >= now - timedelta(days=CONTACT_PLANNER_REFRESH_DAYS),
                    unresolved_checkpoint,
                    disabled_checkpoint,
                ),
                and_(Job.status == "failed", Job.created_at >= now - timedelta(hours=1)),
            ),
        )
        .exists()
    )
    ids = session.scalars(
        select(candidates.c.company_id)
        .where(~not_due)
        .order_by(candidates.c.company_id)
        .limit(min(MAX_COMPANY_SCAN_PER_PLAN, max(limit * 20, 100)))
    ).all()
    recent_jobs: dict[UUID, list[Job]] = {}
    if ids:
        ranked_jobs = (
            select(
                Job.id.label("id"),
                func.row_number()
                .over(
                    partition_by=Job.target_id,
                    order_by=(Job.created_at.desc(), Job.id.desc()),
                )
                .label("position"),
            )
            .where(Job.kind == JOB_KIND, Job.target_id.in_(ids))
            .subquery()
        )
        for job in session.scalars(
            select(Job)
            .join(ranked_jobs, ranked_jobs.c.id == Job.id)
            .where(ranked_jobs.c.position <= 30)
            .order_by(Job.target_id, Job.created_at.desc(), Job.id.desc())
        ):
            if job.target_id is not None:
                recent_jobs.setdefault(job.target_id, []).append(job)
    queued = 0
    for company_id in ids:
        history = recent_jobs.get(company_id, [])
        if not _contact_planner_due(history, now):
            retry_after = _planner_retry_after(history, now)
            project = next(iter(_projects(session, company_id)), None)
            if project is not None:
                marker = Job(
                    source_id=project.source_id,
                    kind=JOB_KIND,
                    target_id=company_id,
                    status="succeeded",
                    checkpoint=json.dumps(
                        {
                            "task_type": TASK_TYPE,
                            "status": "unresolved",
                            "reason": "planner_retry_backoff",
                            "planned_at": now.isoformat(),
                            "retry_after": retry_after.isoformat(),
                            "planner_receipt": True,
                        },
                        separators=(",", ":"),
                    ),
                    available_at=retry_after,
                    created_at=now,
                )
                session.add(marker)
                session.flush()
            continue
        result = discover_company_contacts(session, company_id, now=now)
        queued += result.get("status") == "queued" and not result.get("deduplicated", False)
        if result.get("status") == "unresolved" and result.get("job_id") is None:
            project = next(iter(_projects(session, company_id)), None)
            if project is not None:
                checkpoint = {
                    "task_type": TASK_TYPE,
                    "status": "unresolved",
                    "reason": result.get("reason", "no_current_source_backed_company_claim"),
                    "planned_at": now.isoformat(),
                    "retry_after": (now + timedelta(days=CONTACT_PLANNER_RETRY_DAYS)).isoformat(),
                    "planner_receipt": True,
                }
                marker = Job(
                    source_id=project.source_id,
                    kind=JOB_KIND,
                    target_id=company_id,
                    status="succeeded",
                    checkpoint=json.dumps(checkpoint, separators=(",", ":")),
                    available_at=datetime.fromisoformat(checkpoint["retry_after"]),
                    created_at=now,
                )
                session.add(marker)
                session.flush()
                recent_jobs.setdefault(company_id, []).insert(0, marker)
        if queued >= limit:
            break
    return queued


def _search_name(session: Session, project: Project, company_id: UUID) -> str | None:
    """Use only a current typed membership or a current identity-linked claim."""
    memberships = session.scalars(
        select(CompanyProjectMembership).where(
            CompanyProjectMembership.project_id == project.id,
            CompanyProjectMembership.company_identity_id == company_id,
            CompanyProjectMembership.state == "current",
        )
    ).all()
    if len(memberships) == 1:
        return memberships[0].organization_name
    if memberships:
        return None
    names = {
        str(item["organization"])
        for item in buying_chain_view(session, project.id)["candidates"]
        if str(item.get("company_identity_id")) == str(company_id)
        and not item.get("stale")
        and any(
            c.get("supports") == "project_organization" and c.get("current_support")
            for c in item["evidence"]
        )
    }
    return next(iter(names)) if len(names) == 1 else None


def _rrc_url(operator_number: str | None) -> str | None:
    if not operator_number or not re.fullmatch(r"\d{6}", operator_number):
        return None
    return (
        "https://webapps2.rrc.texas.gov/EWA/organizationResultsDrillDownAction.do"
        f"?methodToCall=searchByOperatorNo&operatorNo={operator_number}"
    )


def _rrc_public_method(
    doc: PublicDocument, operator_number: str, organization: str
) -> dict[str, str] | None:
    """Only a literal organization phone on the exact-number public RRC result."""
    if doc.url != _rrc_url(operator_number):
        return None
    if not re.search(r"Organization\s+Operator\s+Query\s+Results", doc.text, re.I):
        return None
    lines = [line.strip() for line in doc.text.splitlines()]
    numbers = re.findall(r"^Operator\s*(?:Number|No\.?|#):\s*(\d{6})\s*$", doc.text, re.I | re.M)
    names = re.findall(r"^Operator\s*Name:\s*(.+?)\s*$", doc.text, re.I | re.M)
    if numbers != [operator_number] or len(names) != 1:
        return None
    if _brand_key(names[0]) != _brand_key(organization):
        return None
    phones = [
        line
        for line in lines
        if re.fullmatch(r"Organization\s+Phone\s+No\.?:\s*[+()0-9 .-]{10,24}", line, re.I)
    ]
    if len(phones) != 1:
        return None
    value = phones[0].split(":", 1)[1].strip()
    if not re.fullmatch(r"(?:\+?1[ .-]?)?(?:\(?[2-9]\d{2}\)?[ .-]?){2}\d{4}", value):
        return None
    return {
        "kind": "phone",
        "value": value,
        "source_url": doc.url,
        "quote": phones[0],
        "observed_at": doc.observed_at.isoformat(),
    }


def _search_official_urls(
    job_id: UUID,
    worker_id: str,
    fence: int,
    company_id: UUID,
    project_id: UUID,
    organization: str,
    expected_digest: str | None,
    deadline: float,
) -> list[str]:
    """One gated, ledger-accounted URL search; no provider request on replay/UNKNOWN."""
    from gridlens.ingestion.adapters.pursuit_acquisition import discover_urls
    from gridlens.integrations.legacy_calls import LegacyCallBlocked, perform_legacy_call

    query = (
        f'"{organization}" contact email phone '
        "-site:linkedin.com -site:facebook.com -site:instagram.com -site:x.com"
    )
    if len(query) > 1000 or time.monotonic() >= deadline:
        raise LegacyCallBlocked("CONTACT_SEARCH_BOUNDS_EXCEEDED")
    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        previous_id = checkpoint.get("search_logical_call_id")
        source_id = job.source_id

    def before_dispatch(call_id: UUID) -> None:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence)
            projects = _projects(session, company_id)
            project = next((row for row in projects if row.id == project_id), None)
            if (
                time.monotonic() >= deadline
                or project is None
                or _anchor_digest(session, project, company_id) != expected_digest
                or _search_name(session, project, company_id) != organization
            ):
                raise LegacyCallBlocked("CONTACT_SOURCE_CONTEXT_CHANGED")
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint["search_logical_call_id"] = str(call_id)
            checkpoint["search_query"] = query
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))

    payload = {"query": query, "limit": MAX_CANDIDATE_URLS, "sources": [{"type": "web"}]}
    result = perform_legacy_call(
        task_type="FIRECRAWL_SEARCH_V2",
        task_key=f"company-contact:{company_id}:search:{fingerprint(query)}",
        payload=payload,
        source_id=source_id,
        project_id=project_id,
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence,
        before_dispatch=before_dispatch,
        existing_call_id=UUID(previous_id) if isinstance(previous_id, str) else None,
        invoke=lambda: (
            {
                "urls": discover_urls(
                    query,
                    api_key=settings.firecrawl_api_key.get_secret_value()
                    if settings.firecrawl_api_key
                    else None,
                    deadline=deadline,
                    before_request=lambda _endpoint: None,
                    limit=MAX_CANDIDATE_URLS,
                )
            },
            None,
            None,
        ),
    )
    urls = result.result.get("urls")
    if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
        raise ValueError("Cached Firecrawl contact search response is invalid")
    return list(dict.fromkeys(validate_public_url(url) for url in urls))[:MAX_CANDIDATE_URLS]


def process_company_contact_discovery(
    job_id: UUID,
    worker_id: str,
    fence: int,
    *,
    now: datetime | None = None,
    deadline: float | None = None,
) -> dict:
    """Fetch outside a transaction, then persist only under the current fence."""
    now = now or datetime.now(UTC)
    local_deadline = time.monotonic() + MAX_SECONDS
    deadline = min(deadline, local_deadline) if deadline is not None else local_deadline
    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        if checkpoint.get("completed_at") and checkpoint.get("status") in {
            "complete",
            "partial",
            "unresolved",
        }:
            return {
                "status": checkpoint["status"],
                "job_id": str(job.id),
                "failures": checkpoint.get("failures", []),
                "research_required": checkpoint.get("research_required", True),
                "results": checkpoint.get("results", []),
            }
        payload = checkpoint.get("payload", {})
        company_id = UUID(payload["company_identity_id"])
        refresh_due = payload.get("refresh_due") is True
        urls = payload.get("candidate_urls", [])
        projects = _projects(session, company_id)
        if not urls:
            urls = _known_contact_urls(session, company_id, projects)[:MAX_CANDIDATE_URLS]
        anchor = _select_anchor_project(session, projects, company_id)
        anchor_id = anchor.id if anchor else None
        expected_digest = _anchor_digest(session, anchor, company_id) if anchor else None
        current = company_contacts(session, company_id)
        already_named = any(relevant_named_contact(item) for item in current.contacts)
        reuse_named_contact = already_named and not refresh_due
        organization = _search_name(session, anchor, company_id) if anchor else None
        identity = session.get(CompanyIdentity, company_id)
        operator_number = identity.rrc_operator_number if identity else None

    fetched: dict[str, PublicDocument] = {}
    failures: list[dict[str, str]] = []
    discovery_reason: str | None = None
    if not urls and not already_named and organization and anchor_id is not None:
        try:
            urls = _search_official_urls(
                job_id,
                worker_id,
                fence,
                company_id,
                anchor_id,
                organization,
                expected_digest,
                deadline,
            )
        except Exception as exc:
            from gridlens.integrations.legacy_calls import LegacyCallBlocked, LegacyCallUnknown

            if not isinstance(exc, LegacyCallBlocked | LegacyCallUnknown):
                with SessionLocal() as session:
                    searched = session.get(Job, job_id)
                    searched_checkpoint = (
                        json.loads(searched.checkpoint or "{}") if searched else {}
                    )
                    call_id = searched_checkpoint.get("search_logical_call_id")
                    call = session.get(LogicalCall, UUID(call_id)) if call_id else None
                if call is None:
                    raise
                discovery_reason = (
                    "Paid search outcome UNKNOWN; retry prohibited"
                    if call.status == "SENT_OUTCOME_UNKNOWN"
                    else "Completed search response invalid"
                    if call.status == "COMPLETED"
                    else "Paid search unavailable"
                )
            else:
                discovery_reason = str(exc)
            failures.append({"url": "firecrawl:search", "reason": type(exc).__name__})
    to_check = [] if reuse_named_contact else list(urls[:MAX_CANDIDATE_URLS])
    checked: set[str] = set()
    while to_check and len(checked) < MAX_CANDIDATE_URLS:
        url = to_check.pop(0)
        if url in checked:
            continue
        checked.add(url)
        if time.monotonic() >= deadline:
            failures.append({"url": url, "reason": "DeadlineExceeded"})
            break
        try:
            document = retrieve(url, deadline=deadline)
            fetched[url] = document
            if organization and _self_identified_company_site(document, organization):
                origin = urlsplit(document.url).hostname
                official_links = [
                    link for link in document.links if urlsplit(link).hostname == origin
                ]
                pending_official = [link for link in to_check if urlsplit(link).hostname == origin]
                pending_contact = [
                    link
                    for link in pending_official
                    if re.search(r"(?:contact|reach|connect)", urlsplit(link).path, re.I)
                ]

                def link_priority(
                    link: str,
                    *,
                    links: tuple[str, ...] = document.links,
                    pending: list[str] = pending_contact,
                    pending_urls: list[str] = to_check,
                ) -> tuple[int, int]:
                    path = urlsplit(link).path
                    if re.search(r"(?:contact|reach|connect)", path, re.I):
                        order = links.index(link) if link in links else 0
                        return (0, order)
                    if link in pending:
                        return (1, pending_urls.index(link))
                    if re.search(r"(?:team|leadership|management)", path, re.I):
                        order = links.index(link) if link in links else 0
                        return (2, order)
                    order = links.index(link) if link in links else 0
                    return (3, order)

                # A verified official page can reveal a better same-host target
                # than the remaining search results. Keep the global fetch cap.
                prioritized = sorted(
                    dict.fromkeys([*official_links, *pending_official, *to_check]),
                    key=link_priority,
                )
                to_check = [link for link in prioritized if link not in checked][
                    : MAX_CANDIDATE_URLS - len(checked)
                ]
        except Exception as exc:
            failure = {"url": url, "reason": type(exc).__name__}
            detail = str(exc)
            if re.fullmatch(r"[A-Za-z0-9_ .:-]{1,80}", detail):
                failure["detail"] = detail
            failures.append(failure)
    official_method_found = bool(
        organization
        and any(
            _self_identified_company_site(doc, organization)
            and re.search(
                r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}|"
                r"^(?:Phone|Telephone|Tel|Toll Free)\s*:\s*[+()0-9 .-]{10,24}$",
                doc.text,
                re.I | re.M,
            )
            for doc in fetched.values()
        )
    )
    registry_url = _rrc_url(operator_number)
    registry_doc: PublicDocument | None = None
    if (
        not reuse_named_contact
        and not official_method_found
        and registry_url
        and len(checked) < MAX_CANDIDATE_URLS
        and time.monotonic() < deadline
    ):
        checked.add(registry_url)
        try:
            registry_doc = retrieve(registry_url, deadline=deadline)
            fetched[registry_url] = registry_doc
        except Exception as exc:
            failure = {"url": registry_url, "reason": type(exc).__name__}
            detail = str(exc)
            if re.fullmatch(r"[A-Za-z0-9_ .:-]{1,80}", detail):
                failure["detail"] = detail
            failures.append(failure)

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        projects = _projects(session, company_id)
        results: list[dict] = []
        project = next((row for row in projects if row.id == anchor_id), None)
        if reuse_named_contact:
            results.append({"status": "complete", "reason": "current_named_contact_reused"})
        elif refresh_due and already_named and not fetched and registry_doc is None:
            results.append({"status": "unresolved", "reason": "no_verified_refresh_source"})
        elif project is None or _anchor_digest(session, project, company_id) != expected_digest:
            results.append({"status": "unresolved", "reason": "source_context_changed"})
        else:
            try:
                with session.begin_nested():
                    results.append(
                        _discover_anchor(
                            session,
                            project,
                            company_id,
                            fetched,
                            now,
                            registry_doc=registry_doc,
                            operator_number=operator_number,
                        )
                    )
            except Exception as exc:
                failures.append({"project_id": str(project.id), "reason": type(exc).__name__})
        if discovery_reason and results and results[0].get("reason") == "no_verified_official_seed":
            results[0]["discovery_limit"] = discovery_reason
        if (
            urls
            and failures
            and not fetched
            and results
            and results[0].get("reason") == "no_verified_official_seed"
        ):
            results[0]["reason"] = "all_candidate_fetches_failed"
            results[0]["discovery_limit"] = "Verified official page retrieval failed"
        current = company_contacts(session, company_id)
        persisted = any(row.get("status") == "complete" for row in results)
        status = "partial" if persisted and failures else "complete" if persisted else "unresolved"
        checkpoint.update(
            status=status,
            completed_at=now.isoformat(),
            checked_urls=list(fetched),
            failures=failures,
            projects_checked=[str(anchor_id)] if anchor_id else [],
            research_required=current.research_required,
            results=results,
            discovery_reason=discovery_reason,
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
        job.status, job.error, job.lease_owner, job.lease_until = "succeeded", None, None, None
        return {
            "status": status,
            "job_id": str(job.id),
            "failures": failures,
            "research_required": current.research_required,
            "results": results,
        }


def _anchor_digest(session: Session, project: Project, company_id: UUID) -> str:
    """Fence network results to the exact membership and relationship versions."""
    memberships = session.scalars(
        select(CompanyProjectMembership).where(
            CompanyProjectMembership.project_id == project.id,
            CompanyProjectMembership.company_identity_id == company_id,
            CompanyProjectMembership.state == "current",
        )
    ).all()
    view = buying_chain_view(session, project.id)
    candidates = [
        item
        for item in view["candidates"]
        if str(item.get("company_identity_id")) == str(company_id) and not item.get("stale")
    ]
    company_only = [item for item in candidates if not item.get("person_name")]
    # A named role discovered by this job may have a different category from
    # its company, but it does not change the underlying company source.
    relationships = [
        (
            item["organization"],
            item["category"],
            item["organization_relationship"],
            citation["url"],
            citation["quote"],
            citation["content_hash"],
        )
        for item in (company_only or candidates)
        for citation in item["evidence"]
        if citation.get("supports") == "project_organization" and citation.get("current_support")
    ]
    identity = session.get(CompanyIdentity, company_id)
    return fingerprint(
        {
            "project": str(project.id),
            "company": str(company_id),
            "memberships": sorted(
                (str(row.id), row.source_version_hash, row.state, row.version)
                for row in memberships
            ),
            "operator_number": identity.rrc_operator_number if identity else None,
            "relationships": [] if memberships else sorted(set(relationships)),
            "policy": POLICY_VERSION,
        }
    )


def _normal(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _brand_key(value: str) -> str:
    """Allow a legal suffix in the registry but not on the company's own masthead."""
    return re.sub(r"(?:inc|incorporated|llc|corp|corporation|ltd)$", "", _normal(value))


def _self_identified_company_site(doc: PublicDocument, organization: str) -> bool:
    """Require the site's publisher identity, not a directory subject profile."""
    host = (urlsplit(validate_public_url(doc.url)).hostname or "").casefold().removeprefix("www.")
    if host.endswith((".gov", ".mil")):
        return False
    publisher_names: list[str] = []
    for row in doc.structured:
        if not isinstance(row, dict) or row.get("@type") != "Organization":
            continue
        declared = row.get("name")
        if not isinstance(declared, str) or not declared.strip():
            continue
        # A declared profile URL makes this a subject record even if its @id
        # happens to use a root fragment. Use @id only when no URL is declared.
        official_url = row.get("url") or row.get("@id")
        if not isinstance(official_url, str):
            continue
        try:
            root = urlsplit(validate_public_url(official_url))
        except ValueError:
            continue
        if (
            (root.hostname or "").casefold().removeprefix("www.") == host
            and root.path == "/"
            and not root.query
        ):
            publisher_names.append(declared)
    # Native HTML extraction can replace the copyright glyph with U+FFFD.
    # Match a terminal legal footer, including punctuation/case variations in
    # the registered company name, without accepting article mentions.
    footer_lines = [
        line
        for line in doc.text.splitlines()
        if not (line.lstrip().startswith("{") and '"@type": "Organization"' in line)
    ][-12:]
    for line in footer_lines:
        match = re.fullmatch(
            r"\s*(?:(?:©|\ufffd|copyright)\s*\d{4}(?:\s*[-–]\s*\d{4})?\s+"
            r"(?P<name>[^\n]{2,200}?)|(?P<name_first>[^\n]{2,200}?)\s+"
            r"(?:©|\ufffd|copyright)\s*\d{4})"
            r"(?:\s+All rights reserved\.?)?\s*",
            line,
            re.I,
        )
        if match:
            publisher_names.append(match.group("name") or match.group("name_first"))
    publisher_keys = {_brand_key(name) for name in publisher_names}
    # Conflicting root Organization or legal-footer declarations are ambiguous.
    # A profile Organization whose URL is merely on this host never proves
    # ownership of the site or its page-wide contact methods.
    if publisher_keys:
        return publisher_keys == {_brand_key(organization)}
    # Some small official sites use the registered name as the home-page title
    # and an explicit first-person self-description, with no legal footer.
    if urlsplit(doc.url).path in {"", "/"} and _brand_key(doc.title) == _brand_key(organization):
        lead = doc.text[:800]
        if re.search(re.escape(organization), lead, re.I) and re.search(
            r"\b(?:we|our)\b", lead, re.I
        ):
            return True
    return False


def _append_run_claim(
    session: Session,
    project: Project,
    claim: BuyingChainClaim,
    source_ids: list[str],
    now: datetime,
    *,
    replaces: UUID | None = None,
) -> None:
    prior = session.scalar(
        select(BuyingChainRun)
        .where(BuyingChainRun.project_id == project.id)
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(1)
    )
    prior_claims = prior.claim_ids if prior else []
    claim_ids = list(
        dict.fromkeys(
            [str(claim.id) if value == str(replaces) else value for value in prior_claims]
            + [str(claim.id)]
        )
    )
    evidence_ids = list(dict.fromkeys([*(prior.evidence_ids if prior else []), *source_ids]))
    if prior and prior.claim_ids == claim_ids and prior.evidence_ids == evidence_ids:
        return
    unresolved = list(prior.unresolved) if prior else ["Purchasing authority remains UNKNOWN."]
    written_at = now
    if prior and prior.created_at >= written_at:
        written_at = prior.created_at + timedelta(microseconds=1)
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash=fingerprint(
                {
                    "policy": POLICY_VERSION,
                    "prior": prior.input_hash if prior else None,
                    "claims": claim_ids,
                    "evidence": evidence_ids,
                }
            ),
            evidence_ids=evidence_ids,
            claim_ids=claim_ids,
            policy_version=prior.policy_version if prior else POLICY_VERSION,
            status="partial" if unresolved else "complete",
            documents_checked=prior.documents_checked if prior else 1,
            candidates_added=1,
            unresolved=unresolved,
            created_at=written_at,
        )
    )
    session.flush()


def _canonical_anchor(
    session: Session,
    project: Project,
    company_id: UUID,
    view: dict,
    now: datetime,
) -> tuple[BuyingChainClaim | None, BuyingChainEvidence | None]:
    """Choose a current organization claim, or seed one from exact membership evidence."""
    candidates = [
        item
        for item in view["candidates"]
        if str(item.get("company_identity_id")) == str(company_id) and not item.get("stale")
    ]
    company_only = next((item for item in candidates if not item.get("person_name")), None)
    if company_only is not None:
        return session.get(BuyingChainClaim, company_only["id"]), None

    source: BuyingChainEvidence | None = None
    category: str
    organization: str
    relationship: str
    if candidates:
        candidate = candidates[0]
        support = next(
            (
                item
                for item in candidate["evidence"]
                if item.get("supports") == "project_organization" and item.get("current_support")
            ),
            None,
        )
        if support is None:
            return None, None
        source = session.get(BuyingChainEvidence, support["id"])
        organization = str(candidate["organization"])
        category = str(candidate["category"])
        relationship = str(candidate["organization_relationship"])
        quote = str(support["quote"])
        basis = "contact_anchor"
    else:
        memberships = session.scalars(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.company_identity_id == company_id,
                CompanyProjectMembership.state == "current",
            )
        ).all()
        if len(memberships) != 1:
            return None, None
        membership = memberships[0]
        competing = session.scalar(
            select(CompanyProjectMembership.id)
            .where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.company_identity_id != company_id,
                CompanyProjectMembership.state.in_(("current", "conflicted")),
            )
            .limit(1)
        )
        evidence = session.get(Evidence, membership.source_evidence_id)
        if (
            competing is not None
            or evidence is None
            or evidence.content_hash != membership.source_version_hash
            or not _retained_evidence_current_for_project(session, project, evidence)
        ):
            return None, None
        document = PublicDocument(
            evidence.url,
            evidence.title,
            f"{evidence.title}\n{evidence.abstract or ''}",
            evidence.published_at,
            evidence.observed_at,
            evidence.extraction_location,
            retained_version=evidence.content_hash,
        )
        organization = membership.organization_name
        if not re.search(re.escape(organization), document.text, re.I):
            return None, None
        source = _store_document(
            session,
            project,
            document,
            "Current accepted typed customer membership on this physical project.",
            membership.source_evidence_id,
            seen_at=evidence.observed_at,
        )
        category = membership.role
        relationship = "DIRECT"
        quote = document.text
        basis = "current_membership"

    if source is None or quote not in source.excerpt:
        return None, None
    citation = {
        "evidence_id": str(source.id),
        "url": source.url,
        "quote": quote,
        "supports": "project_organization",
    }
    item = Extracted(organization, category)
    state = dict(
        policy_version=POLICY_VERSION,
        organization=organization,
        person_name=None,
        title=None,
        category=category,
        organization_relationship=relationship,
        person_organization_relationship="UNKNOWN",
        person_project_relationship="UNKNOWN",
        evidence_strength="High",
        reason="Current source-backed company relationship; purchasing authority UNKNOWN.",
        citations=[citation],
        public_contacts=[],
    )
    digest = fingerprint(state)
    claim = session.scalar(
        select(BuyingChainClaim).where(
            BuyingChainClaim.project_id == project.id,
            BuyingChainClaim.fingerprint == digest,
        )
    )
    if claim is None:
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key=_entity_key(item),
            fingerprint=digest,
            observed_at=now,
            verified_at=now,
            **state,
        )
        session.add(claim)
        session.flush()
    link = session.scalar(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id == claim.id,
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.state == "current",
        )
    )
    if link is None:
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company_id,
                reason="Current source-cited company relationship for contact research.",
                basis=basis,
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current",
            )
        )
    elif link.company_identity_id != company_id:
        return None, None
    _append_run_claim(session, project, claim, [str(source.id)], now)
    return claim, source


def _discover_anchor(
    session: Session,
    project: Project,
    company_id: UUID,
    fetched: dict[str, PublicDocument],
    now: datetime,
    *,
    registry_doc: PublicDocument | None = None,
    operator_number: str | None = None,
) -> dict:
    """Attach literal corporate methods without changing the project's buyer claim."""
    view = buying_chain_view(session, project.id, now=now)
    old, _membership_source = _canonical_anchor(session, project, company_id, view, now)
    if old is None:
        return {"status": "unresolved", "reason": "no_current_source_backed_company_claim"}
    if not fetched:
        return {
            "status": "unresolved",
            "reason": "no_verified_official_seed",
            "discovery_limit": "Firecrawl discovery is unconfigured"
            if not settings.firecrawl_api_key
            else "Paid discovery is not enabled for this contact job",
        }
    org = old.organization
    documents = []
    for doc in fetched.values():
        if not _self_identified_company_site(doc, org):
            continue
        documents.append(doc)
    identity = session.get(CompanyIdentity, company_id)
    registry_method = (
        _rrc_public_method(registry_doc, operator_number, org)
        if registry_doc is not None
        and operator_number is not None
        and identity is not None
        and identity.rrc_operator_number == operator_number
        else None
    )
    if not documents and not registry_method:
        return {"status": "unresolved", "reason": "official_identity_unverified"}
    contacts = []
    citations = list(old.citations)
    evidence_ids = []
    sources_by_url: dict[str, BuyingChainEvidence] = {}
    for doc in documents:
        source = _store_document(
            session,
            project,
            doc,
            "Self-identified official organization contact page.",
            seen_at=now,
        )
        evidence_ids.append(str(source.id))
        sources_by_url[doc.url] = source
        found = extract_company_contacts(
            doc, [Extracted(org, old.category, organization_relationship="DIRECT")]
        )
        for item in found:
            for contact in item.public_contacts:
                if contact.get("kind") == "phone" and any(
                    word in str(contact.get("quote", "")).casefold()
                    for word in ("fax", "emergency", "human resources", "investor relations")
                ):
                    continue
                contacts.append(contact)
                citations.append(
                    {
                        "evidence_id": str(source.id),
                        "url": doc.url,
                        "quote": contact["quote"],
                        "supports": "public_contact",
                    }
                )
        # Official self-identification may be in a footer while the contact
        # method is in the contact section. Preserve the literal local context.
        for match in re.finditer(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}|"
            r"(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?){2}\d{4}",
            doc.text,
        ):
            value = match.group(0)
            if any(row.get("value") == value for row in contacts):
                continue
            line_start = doc.text.rfind("\n", 0, match.start()) + 1
            line_end = doc.text.find("\n", match.end())
            if line_end < 0:
                line_end = len(doc.text)
            quote = doc.text[line_start:line_end].strip()
            if "@" not in value:
                label = quote[: match.start() - line_start].strip().casefold()
                if not re.fullmatch(r"(?:phone|telephone|tel|toll free)\s*:?", label):
                    continue
            contacts.append(
                {
                    "kind": "email" if "@" in value else "phone",
                    "value": value,
                    "source_url": doc.url,
                    "quote": quote,
                    "observed_at": now.isoformat(),
                }
            )
            citations.append(
                {
                    "evidence_id": str(source.id),
                    "url": doc.url,
                    "quote": quote,
                    "supports": "public_contact",
                }
            )
    if registry_doc is not None and registry_method is not None:
        source = _store_document(
            session,
            project,
            registry_doc,
            "Exact-number public RRC operator registry organization phone.",
            seen_at=now,
        )
        evidence_ids.append(str(source.id))
        contacts.append(registry_method)
        citations.append(
            {
                "evidence_id": str(source.id),
                "url": registry_doc.url,
                "quote": registry_method["quote"],
                "supports": "public_contact",
            }
        )
    named_count = _store_named_professionals(
        session, project, company_id, old, documents, sources_by_url, now
    )
    if not contacts:
        if named_count:
            return {
                "status": "complete",
                "contacts": 0,
                "named_professionals": named_count,
                "reason": "official_role_without_public_method",
            }
        return {"status": "unresolved", "reason": "no_literal_company_method"}
    # A refreshed contact page cannot erase a separately sourced current method.
    current_methods = [
        method
        for method in old.public_contacts
        if any(
            c.get("url") == method.get("source_url") and c.get("quote") == method.get("quote")
            for c in citations
        )
    ]
    contacts = list(
        {
            (method["kind"], method["value"], method["source_url"]): method
            for method in [*current_methods, *contacts]
        }.values()
    )
    citations = list(
        {
            (item["evidence_id"], item["supports"], item["quote"]): item for item in citations
        }.values()
    )
    state = {
        "policy_version": "company-contacts-v1",
        "organization": old.organization,
        "person_name": old.person_name,
        "title": old.title,
        "category": old.category,
        "organization_relationship": old.organization_relationship,
        "person_organization_relationship": old.person_organization_relationship,
        "person_project_relationship": old.person_project_relationship,
        "evidence_strength": old.evidence_strength,
        "reason": old.reason,
        "citations": citations,
        "public_contacts": contacts,
    }
    digest = _hash(
        {
            **state,
            "public_contacts": [
                {key: value for key, value in contact.items() if key != "observed_at"}
                for contact in contacts
            ],
        }
    )
    copy = session.scalar(
        select(BuyingChainClaim).where(
            BuyingChainClaim.project_id == project.id,
            BuyingChainClaim.fingerprint == digest,
        )
    )
    if copy is None:
        copy = BuyingChainClaim(
            project_id=project.id,
            entity_key=old.entity_key,
            fingerprint=digest,
            observed_at=now,
            verified_at=old.verified_at,
            **state,
        )
        session.add(copy)
        session.flush()
    old_link = session.scalar(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id == old.id,
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.company_identity_id == company_id,
            BuyingChainIdentityLink.state == "current",
        )
    )
    if old_link is None:
        raise ValueError("Canonical company link changed during contact persistence")
    copy_link = session.scalar(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id == copy.id,
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.state == "current",
        )
    )
    if copy_link is None:
        session.add(
            BuyingChainIdentityLink(
                claim_id=copy.id,
                entity_type="company",
                company_identity_id=company_id,
                reason="Unchanged project relationship citation across contact revision.",
                basis=old_link.basis,
                source_evidence_id=old_link.source_evidence_id,
                source_version_hash=old_link.source_version_hash,
                state="current",
            )
        )
    elif copy_link.company_identity_id != company_id:
        raise ValueError("Contact revision conflicts with existing company identity")
    _append_run_claim(session, project, copy, evidence_ids, now, replaces=old.id)
    return {
        "status": "complete",
        "contacts": len(contacts),
        "named_professionals": named_count,
        "source_class": "official_company_site" if documents else "public_registry",
    }


def _store_named_professionals(
    session: Session,
    project: Project,
    company_id: UUID,
    organization_claim: BuyingChainClaim,
    documents: list[PublicDocument],
    sources: dict[str, BuyingChainEvidence],
    now: datetime,
) -> int:
    """Keep sourced professional roles distinct from generic company methods."""
    project_citations = [
        item
        for item in organization_claim.citations
        if item["supports"] in {"project_organization", "organization_category"}
    ]
    organization = Extracted(
        organization_claim.organization,
        organization_claim.category,
        organization_relationship=organization_claim.organization_relationship,
        citations=project_citations,
    )
    count = 0
    for doc in documents:
        path = urlsplit(doc.url).path.strip("/").casefold().split("/")[-1]
        if path not in {"about", "about-us", "team", "leadership", "management", "our-team"}:
            continue
        source = sources[doc.url]
        people = extract_people(
            doc,
            [organization],
            project,
            project_scoped=False,
            today=now.date(),
            verified_official_roster=True,
        )
        for item in people:
            if not item.person_name or not item.title:
                continue
            person_citations = [*project_citations]
            for citation in item.citations:
                if citation["supports"] not in {"organization_person_role", "public_contact"}:
                    continue
                if citation["quote"] not in source.excerpt:
                    continue
                person_citations.append(
                    {
                        "evidence_id": str(source.id),
                        "url": source.url,
                        "quote": citation["quote"],
                        "supports": citation["supports"],
                    }
                )
            if not any(c["supports"] == "organization_person_role" for c in person_citations):
                continue
            state = dict(
                policy_version=POLICY_VERSION,
                organization=item.organization,
                person_name=item.person_name,
                title=item.title,
                category=item.category,
                organization_relationship=item.organization_relationship,
                person_organization_relationship=item.person_organization_relationship,
                person_project_relationship=item.person_project_relationship,
                evidence_strength=item.evidence_strength,
                reason=item.reason,
                citations=person_citations,
                public_contacts=item.public_contacts,
            )
            digest = fingerprint(
                {
                    **state,
                    "public_contacts": [
                        {key: value for key, value in contact.items() if key != "observed_at"}
                        for contact in item.public_contacts
                    ],
                }
            )
            claim = session.scalar(
                select(BuyingChainClaim).where(
                    BuyingChainClaim.project_id == project.id,
                    BuyingChainClaim.fingerprint == digest,
                )
            )
            if claim is None:
                claim = BuyingChainClaim(
                    project_id=project.id,
                    entity_key=_entity_key(item),
                    fingerprint=digest,
                    observed_at=now,
                    verified_at=None,
                    **state,
                )
                session.add(claim)
                session.flush()
            link = session.scalar(
                select(BuyingChainIdentityLink).where(
                    BuyingChainIdentityLink.claim_id == claim.id,
                    BuyingChainIdentityLink.entity_type == "company",
                    BuyingChainIdentityLink.state == "current",
                )
            )
            if link is None:
                company_link = session.scalar(
                    select(BuyingChainIdentityLink).where(
                        BuyingChainIdentityLink.claim_id == organization_claim.id,
                        BuyingChainIdentityLink.entity_type == "company",
                        BuyingChainIdentityLink.company_identity_id == company_id,
                        BuyingChainIdentityLink.state == "current",
                    )
                )
                if company_link is None:
                    raise ValueError("Organization identity changed during named contact write")
                session.add(
                    BuyingChainIdentityLink(
                        claim_id=claim.id,
                        entity_type="company",
                        company_identity_id=company_id,
                        reason="Same current source-cited organization as official roster.",
                        basis=company_link.basis,
                        source_evidence_id=company_link.source_evidence_id,
                        source_version_hash=company_link.source_version_hash,
                        state="current",
                    )
                )
            elif link.company_identity_id != company_id:
                raise ValueError("Named contact conflicts with canonical company identity")
            _append_run_claim(session, project, claim, [str(source.id)], now)
            count += 1
    return count
