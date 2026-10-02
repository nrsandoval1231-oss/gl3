"""Explicit bounded post-commit EvidenceJudge evaluation and durable shadow metadata."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from gridlens.integrations.typesafe_evidence_judge import SCHEMA_VERSION, TypesafeEvidenceJudge
from gridlens.intelligence.evidence_judge import InvalidJudgment
from gridlens.intelligence.project_state import project_state
from gridlens.intelligence.research_recommendation import recommend_from_context
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    EvidenceJudgeRun,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
)
from gridlens.settings import settings


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
        .order_by(Evidence.observed_at, Evidence.id)
        .limit(200 if not evidence_ids else min(len(evidence_ids), 20))
    )
    if not evidence_ids:
        # Filter deterministic exact matches before LIMIT so a large prefix of
        # ordinary accepted records cannot starve genuinely ambiguous cases.
        statement = statement.where(
            ~and_(
                Project.source_id == Observation.source_id,
                Project.external_id == Observation.external_id,
                Interpretation.assessment["project_identity_key"].astext == Project.identity_key,
            )
        )
    if evidence_ids:
        statement = statement.where(Evidence.id.in_([UUID(value) for value in evidence_ids]))
    rows = session.execute(statement).all()
    attempted = valid = failed = 0
    reserved = 0
    for project, evidence, observation, interpretation in rows:
        if attempted >= limit or reserved >= settings.jev_shadow_daily_limit:
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
            continue
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
            continue
        remaining = run_deadline - time.monotonic()
        if remaining <= 0:
            break
        # Serialize global UTC-day reservations; persist PENDING before any network effect.
        session.execute(text("SELECT pg_advisory_xact_lock(647809130122)"))
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
    return {"status": "complete", "attempted": attempted, "valid": valid, "failed": failed}
