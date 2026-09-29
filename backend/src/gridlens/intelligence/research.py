"""One-question, official-source research for an identity-linked Signal."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, date, datetime
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.jobs.queue import assert_fence
from gridlens.persistence.models import (
    Organization,
    PowerNeed,
    Project,
    ProjectRole,
    ResearchEvidence,
    ResearchJob,
)

_ALLOWED_URL = "https://taylortx.gov/1383/KDC-Project-Comal"
_MAX_BYTES = 2_000_000
_MAX_SECONDS = 20
_ADDRESS = re.compile(r"1051\s+County Road\s+401", re.IGNORECASE)


def _fetch(url: str) -> bytes:
    if url != _ALLOWED_URL:
        raise ValueError("Research URL is outside the single-source allowlist")
    deadline = time.monotonic() + _MAX_SECONDS
    parts: list[bytes] = []
    size = 0
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        with client.stream(
            "GET", url, headers={"User-Agent": "GridLens local research evidence reader"}
        ) as response:
            if response.url != httpx.URL(_ALLOWED_URL):
                raise ValueError("Official source redirected outside the allowlisted page")
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > _MAX_BYTES:
                raise ValueError("Official page exceeded the 2 MB response limit")
            for part in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TimeoutError("Official page exceeded the 20 second job limit")
                size += len(part)
                if size > _MAX_BYTES:
                    raise ValueError("Official page exceeded the 2 MB response limit")
                parts.append(part)
    if time.monotonic() > deadline:
        raise TimeoutError("Official page exceeded the 20 second job limit")
    return b"".join(parts)


def _source_date(soup: BeautifulSoup) -> date | None:
    for selector, attribute in (
        ("meta[property='article:published_time']", "content"),
        ("meta[property='article:modified_time']", "content"),
        ("meta[name='date']", "content"),
        ("time[datetime]", "datetime"),
    ):
        node = soup.select_one(selector)
        value = node.get(attribute) if node else None
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _extract(content: bytes) -> dict:
    soup = BeautifulSoup(content, "html.parser")
    main = soup.select_one("main") or soup
    heading = main.select_one("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    paragraphs = [p.get_text(" ", strip=True) for p in main.select("p")]
    identity = next((p for p in paragraphs if _ADDRESS.search(p)), "")
    developer = next(
        (
            p
            for p in paragraphs
            if "KDC Real Estate Development and Investments" in p
            or re.search(r"Developer\s+KDC\s+seeks", p, re.IGNORECASE)
        ),
        "",
    )
    explicit = (
        "comal" in title.casefold()
        and _ADDRESS.search(identity) is not None
        and bool(developer)
        and "data center" in identity.casefold()
    )
    excerpt_parts = [identity] if identity == developer else [identity, developer]
    excerpt = " ".join(value for value in excerpt_parts if value)
    if len(excerpt) > 1800:
        excerpt = excerpt[:1800]
    return {
        "title": title,
        "identity_excerpt": identity,
        "developer_excerpt": developer,
        "excerpt": excerpt or main.get_text(" ", strip=True)[:1800],
        "source_date": _source_date(soup),
        "supported": explicit,
    }


def process_research_job(
    session: Session,
    job_id: UUID,
    worker_id: str,
    fence: int,
    *,
    fetch=_fetch,
) -> dict[str, str]:
    research = session.get(ResearchJob, job_id, with_for_update=True)
    job = assert_fence(session, job_id, worker_id, fence)
    if job.kind != "research" or research is None:
        raise ValueError("Research worker received a non-research job")
    if research.status == "completed":
        return {"status": research.status}
    research.status = "running"
    research.started_at = research.started_at or datetime.now(UTC)
    need = session.get(PowerNeed, research.need_id)
    project = session.get(Project, need.project_id) if need else None
    if need is None or project is None:
        research.status = "unresolved"
        research.unresolved_reason = "Linked Signal project or need is missing"
        research.next_action = (
            "Review the retained Signal identity before attempting owner research."
        )
        research.completed_at = datetime.now(UTC)
        return {"status": research.status}

    try:
        content = fetch(research.source_url)
    except Exception as exc:  # persisted bounded failure, with no retry loop or hidden provider
        assert_fence(session, job_id, worker_id, fence)
        research.status = "unresolved"
        research.unresolved_reason = f"Official source retrieval failed: {type(exc).__name__}"
        research.next_action = (
            "Retry this one official project page after checking public availability."
        )
        research.result = {"decision": "source_unavailable"}
        research.completed_at = datetime.now(UTC)
        return {"status": research.status}

    page = _extract(content)
    assert_fence(session, job_id, worker_id, fence)
    digest = hashlib.sha256(content).hexdigest()
    evidence = session.scalar(
        select(ResearchEvidence).where(
            ResearchEvidence.job_id == research.job_id,
            ResearchEvidence.content_hash == digest,
        )
    )
    if evidence is None:
        evidence = ResearchEvidence(
            job_id=research.job_id,
            source_url=research.source_url,
            publisher="City of Taylor, Texas",
            source_date=page["source_date"],
            excerpt=page["excerpt"],
            extraction_location="Project Comal page: project overview",
            content_hash=digest,
            label="Reported" if page["supported"] else "Unknown",
            basis=(
                "The official page binds the developer to Project Comal and the same "
                "1051 County Road 401 site."
                if page["supported"]
                else "Official page did not support the requested developer relationship."
            ),
            confidence="High" if page["supported"] else "Unknown",
            relationship="Developer" if page["supported"] else None,
        )
        session.add(evidence)
        session.flush()

    if page["supported"]:
        organization = session.scalar(
            select(Organization).where(
                Organization.name == "KDC Real Estate Development and Investments"
            )
        )
        if organization is None:
            organization = Organization(name="KDC Real Estate Development and Investments")
            session.add(organization)
            session.flush()
        existing_role = session.scalar(
            select(ProjectRole.id).where(
                ProjectRole.project_id == project.id,
                ProjectRole.need_id == need.id,
                ProjectRole.organization_id == organization.id,
                ProjectRole.role == "Developer",
                ProjectRole.evidence_id == evidence.id,
            )
        )
        if existing_role is None:
            session.add(
                ProjectRole(
                    project_id=project.id,
                    need_id=need.id,
                    organization_id=organization.id,
                    role="Developer",
                    evidence_id=evidence.id,
                    basis=evidence.basis,
                    confidence="High",
                    effective_date=evidence.source_date,
                )
            )
        research.status = "completed"
        research.unresolved_reason = None
        research.result = {
            "decision": "supported",
            "organization": organization.name,
            "role": "Developer",
            "evidence_id": str(evidence.id),
            "content_hash": digest,
            "excerpt": page["excerpt"],
        }
        research.next_action = (
            "Review construction start and activity-specific power service; developer "
            "identity alone does not establish demand or supply."
        )
    else:
        research.status = "unresolved"
        research.unresolved_reason = (
            "Official page did not explicitly bind a developer to the named project and site"
        )
        research.result = {
            "decision": "unsupported_relationship",
            "evidence_id": str(evidence.id),
            "content_hash": digest,
        }
        research.next_action = (
            "Keep developer UNKNOWN and seek a project-specific official ownership "
            "or development record."
        )
    research.completed_at = datetime.now(UTC)
    job.checkpoint = str(evidence.id)
    return {"status": research.status}
