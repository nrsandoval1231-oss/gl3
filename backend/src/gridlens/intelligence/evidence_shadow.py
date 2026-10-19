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
    Job,
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


def _current_admitted_evidence(session: Session, project: Project, evidence: Evidence) -> bool:
    """Match companion evidence by canonical semantic assessment, not raw hash."""
    observation = session.get(Observation, evidence.observation_id)
    if observation is None:
        return False
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    assessment = interpretation.assessment if interpretation else None
    return bool(
        observation.source_id == project.source_id
        and interpretation
        and interpretation.status == "accepted"
        and interpretation.content_hash == observation.content_hash
        and isinstance(assessment, dict)
        and assessment.get("semantic_hash") == observation.content_hash
        and assessment.get("evidence_hash") == evidence.content_hash
        and assessment.get("project_identity_key") == project.identity_key
    )


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
    queue_worker = judge is None
    model = settings.intelligence_typesafe_model or "jev-latest"
    if judge is None and not api_key:
        return {
            "status": "unavailable",
            "reason": "missing_key",
            "attempted": 0,
            "valid": 0,
            "failed": 0,
        }
    if queue_worker:
        from gridlens.intelligence.intelligence_jobs import _enabled

        allowed, _provider, model, reason = _enabled("EVIDENCE_SHADOW")
        if not allowed:
            return {
                "status": "blocked",
                "reason": reason,
                "attempted": 0,
                "valid": 0,
                "failed": 0,
            }
    judge = judge or TypesafeEvidenceJudge(api_key or "", model=model)
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
                "model": model,
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
                model=model,
                status="pending",
                deterministic=deterministic,
                result=None,
                started_at=now,
            )
            session.add(attempt)
            session.commit()
            reserved += 1
            attempted += 1
            if queue_worker:
                from gridlens.intelligence.intelligence_jobs import _digest

                job = Job(
                    source_id=observation.source_id,
                    kind="evidence_shadow",
                    target_id=attempt.id,
                    checkpoint=json.dumps(
                        {
                            "evidence_judge_run_id": str(attempt.id),
                            "input_key": input_key,
                            "request_context": request_context,
                            "request_digest": _digest(request_context),
                            "project_id": str(project.id),
                            "evidence_id": str(evidence.id),
                            "contract_version": SCHEMA_VERSION,
                        },
                        default=str,
                        separators=(",", ":"),
                    ),
                )
                session.add(job)
                session.flush()
                attempt.deterministic = {
                    **deterministic,
                    "logical_call_id": None,
                    "job_id": str(job.id),
                    "contract_version": SCHEMA_VERSION,
                    "status": "queued",
                }
                session.commit()
                if checkpoint:
                    _advance_checkpoint(session, checkpoint, project, evidence)
                continue
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


def process_evidence_shadow_job(job_id: UUID, worker_id: str, fence: int) -> None:
    """Run one queued EvidenceJudge attempt through the shared logical-call ledger."""
    from gridlens.integrations.legacy_calls import perform_legacy_call
    from gridlens.integrations.typesafe_evidence_judge import TypesafeEvidenceJudge
    from gridlens.jobs.queue import assert_fence
    from gridlens.persistence.database import SessionLocal

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        attempt = session.get(EvidenceJudgeRun, job.target_id)
        evidence = session.get(Evidence, UUID(checkpoint["evidence_id"]))
        observation = session.get(Observation, evidence.observation_id) if evidence else None
        project = session.get(Project, UUID(checkpoint["project_id"]))
        request_context = checkpoint.get("request_context")
        if (
            attempt is None
            or evidence is None
            or observation is None
            or project is None
            or attempt.input_key != checkpoint.get("input_key")
            or not _current_admitted_evidence(session, project, evidence)
            or not isinstance(request_context, dict)
        ):
            job.status, job.error = "succeeded", "STALE_SHADOW_INPUT"
            job.lease_owner, job.lease_until = None, None
            if attempt:
                attempt.status, attempt.error_class = "failed", "StaleInput"
                attempt.finished_at = datetime.now(UTC)
            return
        payload = request_context
        project_id, evidence_id, source_id = project.id, evidence.id, observation.source_id
    api_key = settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else ""
    from gridlens.intelligence.intelligence_jobs import _enabled

    enabled, _provider, model, reason = _enabled("EVIDENCE_SHADOW")
    if not enabled:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence)
            attempt = session.get(EvidenceJudgeRun, job.target_id)
            if attempt:
                attempt.status, attempt.error_class = "failed", reason
                attempt.finished_at = datetime.now(UTC)
            job.status, job.error = "succeeded", reason
            job.lease_owner, job.lease_until = None, None
        return
    judge = TypesafeEvidenceJudge(api_key, model=model)

    def invoke() -> tuple[dict, int | None, int | None]:
        from gridlens.integrations.intelligence_provider import call_typesafe

        request = judge.build_request(
            payload["project"], payload["evidence"], payload["candidates"], model=model
        )
        # Preserve raw response identity for the shared ledger guard before the
        # semantic parser can reject or normalize provider output.
        result = call_typesafe(
            api_key=api_key,
            model=model,
            payload={key: value for key, value in request.items() if key != "model"},
        )
        usage_value = result.get("usage")
        usage = usage_value if isinstance(usage_value, dict) else {}
        return result, usage.get("input_tokens"), usage.get("output_tokens")

    def record_call_id(call_id: UUID) -> None:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence)
            attempt = session.get(EvidenceJudgeRun, job.target_id)
            if attempt is None:
                raise LookupError("EvidenceJudgeRun disappeared before dispatch")
            attempt.deterministic = {
                **attempt.deterministic,
                "logical_call_id": str(call_id),
                "job_id": str(job_id),
                "contract_version": SCHEMA_VERSION,
                "status": "dispatching",
            }
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint["logical_call_id"] = str(call_id)
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))

    try:
        call = perform_legacy_call(
            task_type="EVIDENCE_SHADOW",
            task_key=f"{attempt.input_key}:{checkpoint['contract_version']}",
            payload=payload,
            source_id=source_id,
            project_id=project_id,
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence,
            invoke=invoke,
            before_dispatch=record_call_id,
        )
        from gridlens.integrations.typesafe_evidence_judge import parse_typesafe_response

        parsed_judgment, _actual_model, _input_tokens, _output_tokens = parse_typesafe_response(
            call.result, expected_model=model
        )
        from gridlens.intelligence.evidence_judge import Judgment
        from gridlens.intelligence.research_recommendation import recommend_from_context

        validated = Judgment.model_validate(parsed_judgment)
        result = {
            **validated.model_dump(mode="json"),
            "advisory": {
                "research_recommended": recommend_from_context(
                    validated.model_dump(mode="json"), payload["project"]
                )
            },
        }
        status, error_class = "valid", None
    except Exception as exc:
        result = None
        status, error_class = "failed", type(exc).__name__
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        attempt = session.get(EvidenceJudgeRun, job.target_id)
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, evidence.observation_id) if evidence else None
        project = session.get(Project, project_id)
        if attempt is None:
            job.status, job.error = "failed", "MISSING_SHADOW_ATTEMPT"
        elif (
            evidence is None
            or observation is None
            or project is None
            or not _current_admitted_evidence(session, project, evidence)
        ):
            attempt.status, attempt.error_class = "failed", "StaleInputAfterProvider"
            attempt.finished_at = datetime.now(UTC)
            attempt.deterministic = {
                **attempt.deterministic,
                "logical_call_id": attempt.deterministic.get("logical_call_id"),
                "job_id": str(job_id),
                "contract_version": SCHEMA_VERSION,
                "status": "stale_after_provider",
            }
            job.status, job.error = "succeeded", "STALE_SHADOW_INPUT_AFTER_PROVIDER"
        else:
            attempt.status = status
            attempt.result = result
            attempt.error_class = error_class
            attempt.finished_at = datetime.now(UTC)
            attempt.model = model
            attempt.input_tokens = call.input_tokens if "call" in locals() else None
            attempt.output_tokens = call.output_tokens if "call" in locals() else None
            attempt.deterministic = {
                **attempt.deterministic,
                "logical_call_id": (
                    str(call.logical_call_id)
                    if "call" in locals()
                    else attempt.deterministic.get("logical_call_id")
                ),
                "job_id": str(job_id),
                "contract_version": SCHEMA_VERSION,
                "status": "completed" if status == "valid" else "failed",
            }
            job.status, job.error = "succeeded", error_class
        job.lease_owner, job.lease_until = None, None
