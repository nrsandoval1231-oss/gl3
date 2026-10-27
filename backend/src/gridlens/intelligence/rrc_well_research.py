"""Bounded, version-fenced official well research; ordinary reads never acquire sources."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

import httpx
from sqlalchemy import exists, func, select

from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

SOURCE = "texas-rrc-drilling-permits"
KIND = "rrc_well_research"
POLICY = "rrc-exact-well-v1"
MAX_ACTIVE = 2
DAILY_JOB_LIMIT = 24
REFRESH_DAYS = 7


def _access_cooldown(session, now: datetime) -> bool:
    return bool(
        session.scalar(
            select(Job.id)
            .where(
                Job.kind == KIND,
                Job.source_id == SOURCE,
                Job.created_at >= now - timedelta(days=1),
                Job.checkpoint.contains('"status":"access_restricted"'),
            )
            .limit(1)
        )
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _native(session, project: Project):
    row = session.execute(
        select(Observation, Interpretation)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(Observation.source_id == SOURCE, Observation.external_id == project.external_id)
    ).one_or_none()
    if row is None:
        return None
    observation, interpretation = row
    assessment = interpretation.assessment or {}
    if (
        interpretation.status != "accepted"
        or interpretation.content_hash != observation.content_hash
        or assessment.get("semantic_hash") != observation.content_hash
        or assessment.get("project_identity_key") != project.identity_key
    ):
        return None
    return observation


def verified_rrc_metadata(session, project_ids: set[UUID]) -> dict[str, dict | list[dict]]:
    """Load bounded prepared-build inputs, failing closed on stale native versions.

    This reads only the selected generation-build batch. The result never grants
    qualification or rewrites canonical project identities.
    """
    projects = session.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    result = {}
    for project in projects:
        containers = project.identity_facts or {}
        candidates = [
            containers.get("rrc_official_well"),
            *containers.get("rrc_official_completion", []),
        ]
        candidates = [
            row for row in candidates if isinstance(row, dict) and row.get("policy") == POLICY
        ]
        if not candidates:
            continue
        observation = _native(session, project)
        if observation is None:
            continue
        supported = []
        for retained in candidates:
            if retained.get("native_content_hash") != observation.content_hash:
                continue
            if retained.get("native_observation_id") != str(observation.id):
                continue
            try:
                evidence_id = UUID(retained["evidence_id"])
            except (ValueError, KeyError, TypeError):
                continue
            evidence = session.get(Evidence, evidence_id)
            if (
                evidence is None
                or evidence.observation_id != observation.id
                or evidence.content_hash != retained.get("content_hash")
                or evidence.url != retained.get("source_url")
                or evidence.abstract != _canonical(retained.get("facts"))
            ):
                continue
            facts = retained.get("facts")
            if not isinstance(facts, dict) or facts.get("identity_validated") is not True:
                continue
            refs = [str(evidence.id)]
            supported.append(
                {
                    **facts,
                    "native_content_hash": observation.content_hash,
                    "evidence_refs": refs,
                    "asset_identity": {**facts.get("asset_identity", {}), "evidence_refs": refs},
                    "events": [
                        {**event, "source": facts.get("source"), "evidence_refs": refs}
                        for event in facts.get("events", [])
                    ],
                }
            )
        if supported:
            result[str(project.id)] = supported[0] if len(supported) == 1 else supported
    return result


def plan_rrc_well_jobs(session, *, now: datetime | None = None) -> int:
    """Schedule finite exact-record work, respecting native version and cooldown."""
    now = now or datetime.now(UTC)
    source = session.get(Source, SOURCE)
    if source is None or not source.enabled or not source.registry_enabled:
        return 0
    session.execute(select(Source.id).where(Source.id == SOURCE).with_for_update())
    if _access_cooldown(session, now):
        return 0
    active = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.kind == KIND, Job.status.in_(["queued", "running"]))
        )
        or 0
    )
    daily = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.kind == KIND,
                Job.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        or 0
    )
    available = max(0, min(MAX_ACTIVE - active, DAILY_JOB_LIMIT - daily))
    if not available:
        return 0
    recent_job = exists(
        select(Job.id).where(
            Job.kind == KIND,
            Job.target_id == Project.id,
            Job.created_at > now - timedelta(days=REFRESH_DAYS),
            Job.checkpoint.contains(POLICY),
            Job.checkpoint.contains(Observation.content_hash),
        )
    )
    candidates = session.scalars(
        select(Project)
        .join(
            Observation,
            (Observation.source_id == Project.source_id)
            & (Observation.external_id == Project.external_id),
        )
        .where(
            Project.source_id == SOURCE,
            Project.region_status == "ELIGIBLE",
            exists(
                select(PowerNeed.id).where(
                    PowerNeed.project_id == Project.id, PowerNeed.active.is_(True)
                )
            ),
            ~recent_job,
        )
        .order_by(Observation.published_at.desc().nullslast(), Project.id)
        .limit(available * 8)
    ).all()
    planned = 0
    for project in candidates:
        observation = _native(session, project)
        if observation is None:
            continue
        session.add(
            Job(
                source_id=SOURCE,
                kind=KIND,
                target_id=project.id,
                checkpoint=_canonical(
                    {"policy": POLICY, "native_content_hash": observation.content_hash}
                ),
            )
        )
        planned += 1
        if planned == available:
            break
    return planned


def retain_rrc_result(session, project: Project, observation: Observation, facts: dict) -> dict:
    """Publish validated source output through the same path used by worker replay."""
    if (
        facts.get("identity_validated") is not True
        or not facts.get("content_hash")
        or not facts.get("source_url")
    ):
        raise ValueError("Official well result lacks validated source provenance")
    evidence = session.scalar(
        select(Evidence).where(
            Evidence.observation_id == observation.id,
            Evidence.content_hash == facts["content_hash"],
        )
    )
    if evidence is None:
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=facts["content_hash"],
            title="RRC official exact-well identity and lifecycle lookup",
            abstract=_canonical(facts),
            url=facts["source_url"],
            extraction_location="Official RRC W-1 detail; exact permit/operator/lease/well/county",
            provenance={"native_content_hash": observation.content_hash, "policy": POLICY},
        )
        session.add(evidence)
        session.flush()
    if evidence.abstract != _canonical(facts) or evidence.url != facts["source_url"]:
        raise ValueError("Official retained source hash conflicts with prior extraction")
    retained = {
        "policy": POLICY,
        "facts": facts,
        "evidence_id": str(evidence.id),
        "native_observation_id": str(observation.id),
        "native_content_hash": observation.content_hash,
        "source_url": facts["source_url"],
        "content_hash": facts["content_hash"],
    }
    current = project.identity_facts or {}
    if facts.get("source") == "texas-rrc-completion-packet":
        records = [
            row
            for row in current.get("rrc_official_completion", [])
            if row.get("facts", {}).get("packet_number") != facts.get("packet_number")
        ]
        records.append(retained)
        project.identity_facts = {**current, "rrc_official_completion": records}
    elif current.get("rrc_official_well") != retained:
        project.identity_facts = {**current, "rrc_official_well": retained}
    return retained


def process_rrc_well_job(
    job_id: UUID, worker_id: str, fence: int, *, deadline: float | None = None
) -> None:
    from gridlens.ingestion.adapters.rrc_completion import retrieve_completion_history
    from gridlens.ingestion.adapters.rrc_drilling import reconstruct_retained_record
    from gridlens.ingestion.adapters.rrc_well_lifecycle import (
        RrcAccessRestricted,
        retrieve_w1_detail,
    )

    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        source = session.get(Source, SOURCE)
        if (
            not settings.rrc_well_research_enabled
            or source is None
            or not source.enabled
            or not source.registry_enabled
            or _access_cooldown(session, datetime.now(UTC))
        ):
            job.status, job.error, job.lease_owner, job.lease_until = (
                "succeeded",
                None,
                None,
                None,
            )
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint.update(status="disabled_or_access_deferred", acquisition_performed=False)
            job.checkpoint = _canonical(checkpoint)
            session.commit()
            return
        project = session.get(Project, job.target_id)
        observation = _native(session, project) if project is not None else None
        if project is None or observation is None or project.source_id != SOURCE:
            raise ValueError("Official research target has no current native permit support")
        native_hash = observation.content_hash
        observed_at = session.scalar(
            select(Evidence.observed_at).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == observation.content_hash,
            )
        )
        if observed_at is None:
            raise ValueError("Native permit lacks retained original evidence")
        record = reconstruct_retained_record(
            observation.abstract, permit_number=project.external_id, observed_at=observed_at
        )
    research_deadline = min(deadline or float("inf"), monotonic() + 35)
    try:
        facts = retrieve_w1_detail(record, deadline=research_deadline)
    except RrcAccessRestricted:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence)
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint.update(status="access_restricted", source_claims_admitted=False)
            job.checkpoint = _canonical(checkpoint)
            job.status, job.error, job.lease_owner, job.lease_until = "succeeded", None, None, None
        return
    try:
        completion = retrieve_completion_history(facts["identity"], deadline=research_deadline)
    except (ValueError, OSError, TimeoutError, httpx.HTTPError) as exc:
        # Identity remains useful when bounded history research is unavailable;
        # no unavailable source becomes a missing/completed milestone claim.
        completion = {"status": "unavailable", "error_class": type(exc).__name__, "records": []}
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        project = session.get(Project, job.target_id)
        observation = _native(session, project) if project is not None else None
        if project is None or observation is None or observation.content_hash != native_hash:
            raise ValueError("Native permit changed during official research; result withheld")
        retain_rrc_result(session, project, observation, facts)
        for packet in completion.get("records", []):
            retain_rrc_result(session, project, observation, packet)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(
            status="completed",
            evidence_hash=facts["content_hash"],
            identity_supported=True,
            milestone_count=len(facts.get("events", []))
            + sum(len(packet.get("events", [])) for packet in completion.get("records", [])),
            completion_research={
                key: value for key, value in completion.items() if key != "records"
            },
        )
        job.checkpoint = _canonical(checkpoint)
        job.status, job.error, job.lease_owner, job.lease_until = "succeeded", None, None, None
