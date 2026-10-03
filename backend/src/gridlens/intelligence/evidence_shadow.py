"""Explicit bounded post-commit EvidenceJudge evaluation and durable shadow metadata."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gridlens.integrations.typesafe_evidence_judge import SCHEMA_VERSION, TypesafeEvidenceJudge
from gridlens.intelligence.evidence_judge import InvalidJudgment
from gridlens.intelligence.project_state import project_state
from gridlens.intelligence.research_recommendation import recommend_from_context
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    EvidenceJudgeRun,
    EvidenceJudgeScanCheckpoint,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
)
from gridlens.settings import settings


def _candidate_pages(session, statement, cursor_run, cursor_evidence, deadline, page_size=100):
    """Walk a stable, bounded-time keyset from the durable attempt cursor and wrap once."""
    if cursor_run is None or cursor_evidence is None:
        queries = [statement]
    else:
        after = statement.where(
            or_(
                Evidence.observed_at > cursor_evidence.observed_at,
                and_(
                    Evidence.observed_at == cursor_evidence.observed_at,
                    Evidence.id > cursor_evidence.id,
                ),
                and_(
                    Evidence.observed_at == cursor_evidence.observed_at,
                    Evidence.id == cursor_evidence.id,
                    Project.id > cursor_run.project_id,
                ),
            )
        )
        before_or_at = statement.where(
            or_(
                Evidence.observed_at < cursor_evidence.observed_at,
                and_(
                    Evidence.observed_at == cursor_evidence.observed_at,
                    Evidence.id < cursor_evidence.id,
                ),
                and_(
                    Evidence.observed_at == cursor_evidence.observed_at,
                    Evidence.id == cursor_evidence.id,
                    Project.id <= cursor_run.project_id,
                ),
            )
        )
        queries = [after, before_or_at]

    for query in queries:
        offset = 0
        while time.monotonic() < deadline:
            page = session.execute(query.limit(page_size).offset(offset)).all()
            if not page:
                break
            yield from page
            offset += len(page)
            if len(page) < page_size:
                break


def _checkpoint(session: Session) -> EvidenceJudgeScanCheckpoint:
    checkpoint = session.get(EvidenceJudgeScanCheckpoint, "default")
    if checkpoint is None:
        checkpoint = EvidenceJudgeScanCheckpoint(name="default")
        session.add(checkpoint)
        session.flush()
    # A default scan may have no eligible rows.  Commit its metadata before
    # releasing the separate scan lease so an open caller Session cannot hold
    # the singleton insert and block the next scanner.
    session.commit()
    return checkpoint


def _release_scan_connection(connection, acquired: bool) -> None:
    try:
        if acquired:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": 647809130123}
            )
    finally:
        connection.close()


def _advance_checkpoint(
    session: Session,
    checkpoint: EvidenceJudgeScanCheckpoint,
    project: Project,
    evidence: Evidence,
) -> None:
    """Persist each visited row, including already-attempted contexts."""
    checkpoint.project_id = project.id
    checkpoint.evidence_id = evidence.id
    checkpoint.observed_at = evidence.observed_at
    session.commit()


def run_shadow(
    session: Session,
    *,
    limit: int = 10,
    judge=None,
    evidence_ids: list[str] | None = None,
) -> dict:
    run_deadline = time.monotonic() + max(1, min(settings.jev_shadow_timeout_seconds, 90))
    limit = min(max(1, limit), settings.jev_shadow_batch_limit, 20)
    if not settings.jev_enabled or not settings.jev_shadow_mode:
        return {"status": "disabled", "attempted": 0, "valid": 0, "failed": 0}
    api_key = settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else None
    if judge is None and not api_key:
        return {
            "status": "unavailable",
            "reason": "missing_key",
            "attempted": 0,
            "valid": 0,
            "failed": 0,
        }
    judge = judge or TypesafeEvidenceJudge(api_key or "")
    statement = (
        select(Project, Evidence, Observation, Interpretation)
        .join(PowerNeed, PowerNeed.project_id == Project.id)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            Interpretation.status == "accepted",
            Interpretation.content_hash == Observation.content_hash,
            PowerNeed.active.is_(True),
            Interpretation.assessment.is_not(None),
            Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
        )
        .order_by(Evidence.observed_at, Evidence.id, Project.id)
        .distinct()
    )
    if not evidence_ids:
        # Filter deterministic exact matches before LIMIT so a large prefix of
        # ordinary accepted records cannot starve genuinely ambiguous cases.
        exact_match = and_(
            Project.source_id == Observation.source_id,
            Project.external_id == Observation.external_id,
            Interpretation.assessment["project_identity_key"].astext == Project.identity_key,
        )
        # SQL NOT(NULL) is NULL, which would silently discard candidates with
        # missing identity keys. Exclude only a positively proven exact match.
        statement = statement.where(~exact_match.is_(True))
    if evidence_ids:
        statement = statement.where(Evidence.id.in_([UUID(value) for value in evidence_ids]))
    # Keep a dedicated connection checked out for the full scan. The work
    # session commits pending/final attempts, so it cannot retain this lock.
    scan_lock = 647809130123
    scan_connection = None
    scan_acquired = False
    if not evidence_ids:
        bind = session.get_bind()
        if not isinstance(bind, Engine):
            return {"status": "complete", "attempted": 0, "valid": 0, "failed": 0}
        try:
            scan_connection = bind.connect()
            scan_acquired = bool(
                scan_connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": scan_lock}
                )
            )
        except Exception:
            if scan_connection is not None:
                _release_scan_connection(scan_connection, scan_acquired)
            raise
        if not scan_acquired:
            _release_scan_connection(scan_connection, False)
            return {"status": "complete", "attempted": 0, "valid": 0, "failed": 0}
    try:
        checkpoint = _checkpoint(session) if not evidence_ids else None
        cursor_evidence = (
            session.get(Evidence, checkpoint.evidence_id)
            if checkpoint and checkpoint.evidence_id
            else None
        )
        rows = (
            # Apply the attempt limit after existing keys are skipped. Truncating
            # this query at 20 would make the 21st explicit ID unreachable.
            iter(session.execute(statement).all())
            if evidence_ids
            else _candidate_pages(session, statement, checkpoint, cursor_evidence, run_deadline)
        )
    except Exception:
        if scan_connection is not None:
            _release_scan_connection(scan_connection, scan_acquired)
        raise
    attempted = valid = failed = 0
    reserved = 0
    try:
        for project, evidence, observation, interpretation in rows:
            if (
                attempted >= limit
                or reserved >= settings.jev_shadow_daily_limit
                or time.monotonic() >= run_deadline
            ):
                break
            assessment = interpretation.assessment or {}
            candidate_rows = session.execute(
                select(ProjectMatchDecision, Project)
                .join(Project, Project.id == ProjectMatchDecision.candidate_project_id)
                .where(
                    ProjectMatchDecision.observation_id == observation.id,
                    ProjectMatchDecision.evidence_id == evidence.id,
                )
                .order_by(ProjectMatchDecision.decided_at.desc())
                .limit(8)
            ).all()
            candidates = [
                {
                    "project_id": str(candidate.id),
                    "name": candidate.name[:250],
                    "location": candidate.location[:250] if candidate.location else None,
                    "decision": decision.decision,
                    "reason": decision.reason[:500],
                    "matched_facts": (decision.matched_facts or [])[:8],
                }
                for decision, candidate in candidate_rows
            ]
            material_event = session.scalar(
                select(ChangeEvent.id)
                .where(
                    ChangeEvent.project_id == project.id,
                    ChangeEvent.evidence_id == evidence.id,
                    ChangeEvent.material.is_(True),
                )
                .limit(1)
            )
            deterministic = {
                "relevant": "YES",
                "same_project": "YES"
                if assessment.get("project_identity_key") == project.identity_key
                else "UNKNOWN",
                "material_change": "YES" if material_event else "NO",
            }
            exact_match = (
                project.source_id == observation.source_id
                and project.external_id == observation.external_id
                and assessment.get("project_identity_key") == project.identity_key
            )
            if exact_match:
                if checkpoint:
                    _advance_checkpoint(session, checkpoint, project, evidence)
                continue
            remaining = run_deadline - time.monotonic()
            if remaining <= 0:
                break
            full_state = project_state(session, project.id) or {}
            state_values = full_state.get("state", {})
            bounded_state = {
                "project_id": full_state.get("project_id"),
                "state": {
                    key: state_values.get(key)
                    for key in (
                        "identity",
                        "site",
                        "lifecycle",
                        "activity",
                        "power_need",
                        "utility_service",
                    )
                },
                "organizations_and_roles": full_state.get("organizations_and_roles", [])[:8],
                "candidate_matches": full_state.get("candidate_matches", [])[:8],
            }
            evidence_context = {
                "id": str(evidence.id),
                "hash": evidence.content_hash,
                "title": evidence.title[:300],
                "abstract": evidence.abstract[:1200] if evidence.abstract else None,
                "url": evidence.url[:500],
                "published_at": evidence.published_at,
                "retrieved_at": evidence.observed_at,
                "extraction_location": evidence.extraction_location[:150],
            }
            request_context = {
                "project": bounded_state,
                "evidence": evidence_context,
                "candidates": candidates,
                "deterministic": deterministic,
                "schema": SCHEMA_VERSION,
                "model": "jev-latest",
            }
            input_key = hashlib.sha256(
                json.dumps(request_context, sort_keys=True, default=str).encode()
            ).hexdigest()
            existing = session.scalar(
                select(EvidenceJudgeRun).where(EvidenceJudgeRun.input_key == input_key)
            )
            if existing:
                # A pending row means a prior process stopped during the provider call.
                # Keep it visible and never blindly repeat a potentially billed request.
                if checkpoint:
                    _advance_checkpoint(session, checkpoint, project, evidence)
                continue
            remaining = run_deadline - time.monotonic()
            if remaining <= 0:
                break
            # The run deadline also bounds coordination: never wait behind another
            # worker's daily reservation transaction beyond this call.
            acquired = session.scalar(text("SELECT pg_try_advisory_xact_lock(647809130122)"))
            if not acquired:
                session.rollback()
                break
            # Another worker may have reserved this exact context while this worker
            # was preparing its bounded request payload.
            if session.scalar(
                select(EvidenceJudgeRun.id).where(EvidenceJudgeRun.input_key == input_key)
            ):
                session.rollback()
                continue
            day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            daily_count = (
                session.scalar(
                    select(func.count(EvidenceJudgeRun.id)).where(
                        EvidenceJudgeRun.started_at >= day_start
                    )
                )
                or 0
            )
            if daily_count >= settings.jev_shadow_daily_limit:
                session.rollback()
                break
            remaining = run_deadline - time.monotonic()
            if remaining <= 0:
                session.rollback()
                break
            now = datetime.now(UTC)
            attempt = EvidenceJudgeRun(
                project_id=project.id,
                evidence_id=evidence.id,
                candidate_project_id=UUID(candidates[0]["project_id"])
                if len(candidates) == 1
                else None,
                input_key=input_key,
                schema_version=SCHEMA_VERSION,
                model="jev-latest",
                status="pending",
                deterministic=deterministic,
                result=None,
                started_at=now,
            )
            session.add(attempt)
            session.commit()
            reserved += 1
            attempted += 1
            status, result, meta, error_class = "valid", None, {}, None
            provider_started = time.monotonic()
            try:
                if hasattr(judge, "timeout"):
                    judge.timeout = min(judge.timeout, remaining)
                result, meta = judge.judge(
                    bounded_state,
                    evidence_context,
                    candidates,
                )
                judgment = result.model_dump(mode="json")
                result = {
                    **judgment,
                    "advisory": {
                        "research_recommended": recommend_from_context(judgment, bounded_state)
                    },
                }
                valid += 1
            except InvalidJudgment:
                status, error_class = "invalid", "InvalidJudgment"
                failed += 1
            except httpx.TimeoutException:
                status, error_class = "timeout", "TimeoutException"
                failed += 1
            except Exception as exc:
                status, error_class = "failed", type(exc).__name__
                failed += 1
            attempt.status = status
            attempt.model = meta.get("model", "jev-latest")
            attempt.result = result
            attempt.error_class = error_class
            attempt.finished_at = datetime.now(UTC)
            attempt.latency_ms = meta.get("latency_ms") or int(
                (time.monotonic() - provider_started) * 1000
            )
            attempt.input_tokens = meta.get("input_tokens")
            attempt.output_tokens = meta.get("output_tokens")
            session.commit()
            if checkpoint:
                _advance_checkpoint(session, checkpoint, project, evidence)
    finally:
        if scan_connection is not None:
            _release_scan_connection(scan_connection, scan_acquired)
    return {"status": "complete", "attempted": attempted, "valid": valid, "failed": failed}
