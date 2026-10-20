"""Evidence-bound Signal display adjudication; commercial tier is independent."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.integrations import intelligence_provider
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    SignalDecision,
    Source,
)
from gridlens.settings import settings

POLICY_VERSION = "signal-display-v2"
MODEL = "jev-1.13.0"


class JevError(RuntimeError):
    def __init__(self, status: str, *, provider_error: Exception | None = None):
        self.status = status
        if provider_error is not None:
            for attribute in (
                "request_id",
                "conclusive",
                "status_code",
                "response_status",
                "response_received",
                "raw_response",
                "reported_model",
                "reported_usage",
                "raw_response_sha256",
                "raw_response_size",
            ):
                setattr(self, attribute, getattr(provider_error, attribute, None))
        super().__init__(f"Jev {status}")


def failure_status(exc: Exception) -> str:
    if isinstance(exc, JevError):
        return exc.status
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return "authentication_failed"
        return (
            "provider_unavailable"
            if status_code == 429 or status_code >= 500
            else "request_rejected"
        )
    if isinstance(exc, intelligence_provider.ProviderResponseError):
        provider_code = exc.status_code
        if provider_code in {401, 403}:
            return "authentication_failed"
        if provider_code is not None:
            return (
                "provider_unavailable"
                if provider_code == 429 or provider_code >= 500
                else "request_rejected"
            )
        return "malformed_response" if exc.conclusive else "provider_unavailable"
    if isinstance(exc, KeyError | TypeError | ValueError):
        return "malformed_response"
    return "provider_unavailable"


def jev_request_payload(state: dict[str, str], *, model: str = MODEL) -> dict[str, Any]:
    return {
        "state": {
            "title": state["title"][:300],
            "abstract": state["abstract"][:1500],
            "url": state["url"][:500],
            "published_at": state["published_at"][:30],
            "source_id": state["source_id"],
            "source_family": state["source_family"],
            "publisher": state["publisher"],
            "event_date": state["event_date"],
            "event_date_label": state["event_date_label"],
            "project_name": state["project_name"],
            "location": state["location"],
            "asset_type": state["asset_type"],
            "lifecycle_state": state["lifecycle_state"],
        },
        "model": model,
        "questions": {
            "physical_project_event": {
                "type": "noul",
                "instructions": (
                    "Does this describe a specific physical project or facility event, rather "
                    "than a general company announcement?"
                ),
            },
            "meaningful_new_activity": {
                "type": "noul",
                "instructions": (
                    "Does this describe meaningful new construction, conversion, expansion, or "
                    "commissioning activity rather than routine maintenance or replacement?"
                ),
            },
            "commercial_relevance": {
                "type": "noul",
                "instructions": (
                    "Could the specific described activity reasonably matter to a commercial "
                    "temporary power provider?"
                ),
            },
            "temporary_power_relevance": {
                "type": "noul",
                "instructions": (
                    "Does the text explicitly support temporary, bridge, construction, "
                    "commissioning, or generator power relevance?"
                ),
            },
            "routine_maintenance": {
                "type": "noul",
                "instructions": (
                    "Is this primarily routine repair, replacement, resurfacing, or maintenance "
                    "of an existing facility or equipment?"
                ),
            },
            "transient_event": {
                "type": "noul",
                "instructions": (
                    "Is this a temporary public event, race, walk, festival, or similar activity "
                    "rather than facility development?"
                ),
            },
        },
    }


def _jev_call(
    state: dict[str, str],
    api_key: str,
    *,
    model: str = MODEL,
    on_request: Callable[[], None] | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    payload = jev_request_payload(state, model=model)
    if not api_key.strip():
        raise JevError("missing_credentials")
    if not 1 <= max_attempts <= 3:
        raise ValueError("Jev allows one to three attempts")
    for attempt in range(max_attempts):
        try:
            if on_request:
                on_request()
            return intelligence_provider.call_typesafe(
                api_key=api_key,
                model=model,
                payload={"state": payload["state"], "questions": payload["questions"]},
                timeout_seconds=12.0,
            )
        except (httpx.HTTPError, ValueError, intelligence_provider.ProviderResponseError) as exc:
            status = failure_status(exc)
            if status == "provider_unavailable" and attempt + 1 < max_attempts:
                time.sleep(min(0.25 * (2**attempt), 1.0))
                continue
            raise JevError(
                status,
                provider_error=(
                    exc if isinstance(exc, intelligence_provider.ProviderResponseError) else None
                ),
            ) from None
    raise JevError("provider_unavailable")


def validated_dimensions(result: Any, *, expected_model: str = MODEL) -> dict[str, float]:
    if not isinstance(result, dict):
        raise ValueError("invalid Jev response")
    if result.get("model") != expected_model:
        raise ValueError("unexpected Jev model")
    answers = result["answers"]
    if not isinstance(answers, dict):
        raise ValueError("invalid Jev answers")
    dimension_values: dict[str, float] = {}
    for name in (
        "physical_project_event",
        "meaningful_new_activity",
        "commercial_relevance",
        "temporary_power_relevance",
        "routine_maintenance",
        "transient_event",
    ):
        answer = answers[name]
        if not isinstance(answer, dict):
            raise ValueError("invalid Jev answer")
        score = answer.get("noul")
        if (
            answer.get("type") != "noul"
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or not 0 <= score <= 1
        ):
            raise ValueError("invalid factual dimension")
        dimension_values[name] = float(score)
    return dimension_values


def adjudicate(
    session: Session,
    observation: Observation,
    evidence: Evidence,
    *,
    api_key: str | None = None,
    caller: Callable[[dict[str, str], str], dict[str, Any]] = _jev_call,
    policy_version: str = POLICY_VERSION,
    retry_errors: bool = False,
) -> SignalDecision:
    prior = session.scalar(
        select(SignalDecision)
        .where(
            SignalDecision.observation_id == observation.id,
            SignalDecision.content_hash == evidence.content_hash,
            SignalDecision.policy_version == policy_version,
        )
        .order_by(SignalDecision.id.desc())
    )
    key = (
        api_key
        if api_key is not None
        else (settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else None)
    )
    key = key.strip() if key else None
    if prior is not None and not (
        (prior.source == "jev_unavailable" and key)
        or (retry_errors and prior.source == "jev_error" and key)
        or (prior.source == "jev_pending" and caller is _jev_call and key)
    ):
        return prior
    text = f"{evidence.title}\n{evidence.abstract or ''}"
    override = deterministic_override(text, observation.published_at, evidence.url)
    if override is not None:
        decision, dims, reason = override
        source, model = "deterministic", None
    else:
        if not key:
            pending = SignalDecision(
                observation_id=observation.id,
                content_hash=evidence.content_hash,
                policy_version=policy_version,
                decision="REVIEW",
                source="jev_unavailable",
                model_version=None,
                dimensions={"status": "missing_api_key"},
                reason="Ambiguous evidence requires Jev; TYPESAFE_API_KEY is unavailable.",
            )
            session.add(pending)
            session.flush()
            return pending
        if caller is _jev_call:
            return queue_adjudication(session, observation, evidence, policy_version)
        try:
            state = _evidence_state(session, observation, evidence)
            result = caller(state, key)
            dimension_values = validated_dimensions(result)
            decision = map_dimensions(
                dimension_values, title=state["title"], abstract=state["abstract"]
            )
            source, model, dims = "jev", str(result["model"]), dimension_values
            reason = (
                "GL3 display policy mapped retained factual Jev dimensions to a display decision."
            )
        except (KeyError, TypeError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            decision, source, model, dims, reason = (
                "REVIEW",
                "jev_error",
                None,
                {"status": failure_status(exc)},
                f"Jev {failure_status(exc)}; evidence retained and manual review required.",
            )
    row = SignalDecision(
        observation_id=observation.id,
        content_hash=evidence.content_hash,
        policy_version=policy_version,
        decision=decision,
        source=source,
        model_version=model,
        dimensions=dims,
        reason=reason,
    )
    session.add(row)
    session.flush()
    return row


def queue_adjudication(
    session: Session,
    observation: Observation,
    evidence: Evidence,
    policy_version: str = POLICY_VERSION,
) -> SignalDecision:
    """Persist an explicit REVIEW and enqueue an exact retained-evidence worker job."""
    from sqlalchemy import select

    prior = session.scalar(
        select(SignalDecision)
        .where(
            SignalDecision.observation_id == observation.id,
            SignalDecision.content_hash == evidence.content_hash,
            SignalDecision.policy_version == policy_version,
        )
        .order_by(SignalDecision.id.desc())
    )
    row = prior
    if row is None:
        row = SignalDecision(
            observation_id=observation.id,
            content_hash=evidence.content_hash,
            policy_version=policy_version,
            decision="REVIEW",
            source="jev_pending",
            model_version=None,
            dimensions={"status": "queued_for_shared_ledger"},
            reason="Ambiguous evidence awaits bounded evidence-bound adjudication.",
        )
        session.add(row)
    job = session.scalar(
        select(Job).where(
            Job.kind == "signal_adjudication",
            Job.target_id == observation.id,
            Job.status.in_(["queued", "running"]),
        )
    )
    if job is None:
        session.add(
            Job(
                source_id=observation.source_id,
                kind="signal_adjudication",
                target_id=observation.id,
                checkpoint=json.dumps(
                    {
                        "evidence_id": str(evidence.id),
                        "content_hash": evidence.content_hash,
                        "policy_version": policy_version,
                    }
                ),
            )
        )
    session.flush()
    return row


def process_signal_adjudication_job(job_id: UUID, worker_id: str, fence: int) -> None:
    """Run one exact Jev request outside the transaction and append its display result."""
    import json

    from gridlens.integrations.legacy_calls import perform_legacy_call
    from gridlens.jobs.queue import assert_fence
    from gridlens.persistence.database import SessionLocal

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        observation = session.get(Observation, job.target_id)
        evidence = session.get(Evidence, UUID(checkpoint["evidence_id"]))
        if (
            observation is None
            or evidence is None
            or evidence.observation_id != observation.id
            or evidence.content_hash != checkpoint.get("content_hash")
        ):
            job.status, job.error = "succeeded", "STALE_EVIDENCE"
            job.lease_owner, job.lease_until = None, None
            return
        state = _evidence_state(session, observation, evidence)
        source_id = observation.source_id
        project = session.scalar(
            select(Project).where(
                Project.source_id == observation.source_id,
                Project.external_id == observation.external_id,
            )
        )
        project_id = project.id if project else None
        from gridlens.intelligence.intelligence_jobs import _enabled

        payload = {
            "state": state,
            "model": settings.intelligence_typesafe_model,
            "contract": "signal-display-v2",
            "observation_id": str(observation.id),
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence.content_hash,
        }
        enabled, _provider, model, reason = _enabled("SIGNAL_ADJUDICATION", payload=payload)
        if not enabled:
            job.status, job.error = "succeeded", f"BLOCKED:{reason}"
            job.lease_owner, job.lease_until = None, None
            return
        payload["model"] = model
        checkpoint_call_id = checkpoint.get("logical_call_id")
    api_key = settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else ""

    def invoke() -> tuple[dict[str, Any], int | None, int | None]:
        result = _jev_call(state, api_key, model=model, max_attempts=1)
        usage_value = result.get("usage")
        usage = usage_value if isinstance(usage_value, dict) else {}
        return result, usage.get("input_tokens"), usage.get("output_tokens")

    try:
        call = perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key=f"{observation.id}:{evidence.content_hash}:{checkpoint['policy_version']}",
            payload=payload,
            source_id=source_id,
            project_id=project_id,
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence,
            invoke=invoke,
            before_dispatch_with_policy=lambda call_id, policy: _save_signal_call_id_if_current(
                job_id,
                worker_id,
                fence,
                call_id,
                policy,
                observation.id,
                evidence.id,
                evidence.content_hash,
                source_id,
            ),
            existing_call_id=UUID(checkpoint_call_id) if checkpoint_call_id else None,
        )
        dimensions = validated_dimensions(call.result, expected_model=model)
        decision = map_dimensions(dimensions, title=state["title"], abstract=state["abstract"])
        model_version = str(call.result["model"])
        source = "jev"
        reason = "GL3 display policy mapped retained factual Jev dimensions to a display decision."
        dims: dict[str, Any] = dimensions
    except Exception as exc:
        decision, source, model_version = "REVIEW", "jev_error", None
        status = failure_status(exc)
        dims = {"status": status}
        reason = f"Jev {status}; evidence retained and manual review required."
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        current_observation = session.get(Observation, observation.id)
        current_evidence = session.get(Evidence, evidence.id)
        from gridlens.intelligence.intelligence_jobs import _enabled

        policy_enabled = _enabled("SIGNAL_ADJUDICATION", payload=payload)[0]
        if (
            current_observation is None
            or current_evidence is None
            or current_evidence.content_hash != evidence.content_hash
            or current_observation.content_hash != evidence.content_hash
            or not _signal_source_enabled(session, source_id)
            or not policy_enabled
        ):
            job.status, job.error = "succeeded", "STALE_EVIDENCE_OR_POLICY_AFTER_PROVIDER"
        else:
            session.add(
                SignalDecision(
                    observation_id=observation.id,
                    content_hash=evidence.content_hash,
                    policy_version=checkpoint["policy_version"],
                    decision=decision,
                    source=source,
                    model_version=model_version,
                    dimensions=dims,
                    reason=reason,
                )
            )
            job.status, job.error = "succeeded", None
        job.lease_owner, job.lease_until = None, None


def _save_signal_call_id(job_id: UUID, worker_id: str, fence: int, call_id: UUID) -> None:
    import json

    from gridlens.jobs.queue import assert_fence
    from gridlens.persistence.database import SessionLocal

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint["logical_call_id"] = str(call_id)
        job.checkpoint = json.dumps(checkpoint)


def _signal_source_enabled(session: Session, source_id: str) -> bool:
    source = session.get(Source, source_id)
    return bool(source and source.enabled and source.registry_enabled)


def _save_signal_call_id_if_current(
    job_id: UUID,
    worker_id: str,
    fence: int,
    call_id: UUID,
    billing_policy: dict[str, str] | None,
    observation_id: UUID,
    evidence_id: UUID,
    content_hash: str,
    source_id: str,
) -> None:
    """Recheck exact public provenance in the dispatch transaction before saving receipt."""
    import json

    from gridlens.jobs.queue import assert_fence
    from gridlens.persistence.database import SessionLocal

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence)
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        if (
            observation is None
            or evidence is None
            or observation.source_id != source_id
            or observation.content_hash != content_hash
            or evidence.observation_id != observation_id
            or evidence.content_hash != content_hash
            or not _signal_source_enabled(session, source_id)
        ):
            raise RuntimeError("SIGNAL_EVIDENCE_OR_SOURCE_STALE_BEFORE_DISPATCH")
        checkpoint = json.loads(job.checkpoint or "{}")
        prior_call_id = checkpoint.get("logical_call_id")
        prior_policy = checkpoint.get("logical_call_policy")
        if prior_call_id is not None and (
            prior_call_id != str(call_id) or prior_policy != billing_policy
        ):
            raise RuntimeError("SIGNAL_LOGICAL_CALL_POLICY_SNAPSHOT_MISMATCH")
        checkpoint["logical_call_id"] = str(call_id)
        checkpoint["logical_call_policy"] = billing_policy
        job.checkpoint = json.dumps(checkpoint)


def deterministic_override(
    text: str, published_at: date | None, url: str
) -> tuple[str, dict[str, Any], str] | None:
    """Sparse explicit Signal policy overrides; all other cases remain reviewable."""
    lower = text.casefold()
    explicit_negative = re.search(
        r"\bwithdrawn\b[^\n]{0,100}\b(?:application|permit|project)\b"
        r"|\b(?:application|permit|project|construction)\s+(?:has been |was )?"
        r"(?:withdrawn|cancelled|canceled|denied)\b|\b(?:withdrawn|cancelled|canceled|denied)"
        r"\s+(?:the )?(?:application|permit|project)\b",
        lower,
    )
    transient = re.search(
        r"\b(?:road race|fun run|walkathon|parade)\b"
        r"|\b(?:park|race|run|event)\b.{0,40}\bmarathon\b"
        r"|\bmarathon\b.{0,60}\b(?:run|race|course|participants|event|annual|park)\b"
        r"|\b(?:one-day|annual) festival\b"
        r"|\btemporary stage\b.{0,40}\b(?:event|festival|concert)\b"
        r"|\bstage for (?:the )?(?:event|festival|concert)\b"
        r"|\bwalk (?:event|for charity|to benefit)\b",
        lower,
    )
    like_for_like_replacement = re.search(
        r"\b(?:like[- ]for[- ]like|same[- ]for[- ]same)\b.{0,40}\b"
        r"(?:generator|genset|transformer|switchgear)\b"
        r"|\b(?:replace|replacing|replacement of)\s+(?:the )?existing\s+"
        r"(?:backup |emergency )?(?:generator|genset|transformer|switchgear)\b"
        r"|\bexisting\s+(?:backup |emergency )?"
        r"(?:generator|genset|transformer|switchgear)\s+replacement\b",
        lower,
    )
    if explicit_negative or transient or like_for_like_replacement:
        return (
            "HOLD",
            {
                "explicit_negative": bool(explicit_negative),
                "transient_event": bool(transient),
                "like_for_like_replacement": bool(like_for_like_replacement),
            },
            "Retained text supports a bounded negative display rule for this event.",
        )
    elif (
        not any(
            phrase in lower
            for phrase in (
                "not under construction",
                "no construction",
                "construction not started",
            )
        )
        and any(
            term in lower
            for term in (
                "under construction",
                "construction begins",
                "begins construction",
                "construction started",
                "construction of",
                "groundbreaking",
            )
        )
        and any(
            term in lower
            for term in (
                "data center",
                "manufacturing",
                "mine",
                "quarry",
                "power plant",
                "generator",
                "conversion",
            )
        )
        and published_at is not None
        and url.startswith("http")
    ):
        return (
            "SHOW",
            {"dated": True, "linked": True, "substantive": True},
            "Explicitly supported high-value construction event; Jev review is not required.",
        )
    return None


def _evidence_state(
    session: Session, observation: Observation, evidence: Evidence
) -> dict[str, str]:
    source = session.get(Source, observation.source_id)
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    assessment = interpretation.assessment if interpretation and interpretation.assessment else {}
    project_key = assessment.get("project_identity_key")
    project = (
        session.scalar(select(Project).where(Project.identity_key == project_key))
        if isinstance(project_key, str)
        else None
    )
    lifecycle = session.get(ProjectLifecycle, project.id) if project else None
    fields = {
        "title": evidence.title,
        "abstract": evidence.abstract or "",
        "url": evidence.url,
        "published_at": str(evidence.published_at or "unknown"),
        "source_id": observation.source_id,
        "source_family": source.family if source else "unknown",
        "publisher": source.publisher if source else "unknown",
        "event_date": str(evidence.event_date or "unknown"),
        "event_date_label": evidence.event_date_label or "unknown",
        "project_name": project.name if project else "unknown",
        "location": project.location if project and project.location else "unknown",
        "asset_type": project.asset_type if project else "unknown",
        "lifecycle_state": lifecycle.current_state if lifecycle else "unknown",
    }
    return fields


def map_dimensions(dimensions: dict[str, float], *, title: str = "", abstract: str = "") -> str:
    """Apply GL3 policy to factual probabilities and retained source context."""
    if dimensions["transient_event"] >= 0.8:
        return "HOLD"
    if dimensions["routine_maintenance"] >= 0.8 and dimensions["meaningful_new_activity"] <= 0.3:
        return "HOLD"
    context = f"{title}\n{abstract}".casefold()
    activity_match = re.search(
        r"(?im)^(?:description|scope of work|project description):\s*([^\n]{1,1200})",
        abstract,
    )
    activity_excerpt = activity_match.group(1) if activity_match else abstract[:800]
    activity_context = f"{title}\n{activity_excerpt}".casefold()
    power_relevant_sector = re.search(
        r"\b(?:data cent(?:er|re)|manufactur\w*|mine|quarry|renewable natural gas|\brng\b|"
        r"power plant|until (?:the )?(?:grid|utility) (?:power|service))\b",
        context,
    )
    generic_building = re.search(
        r"\b(?:office\s*/?\s*(?:limited\s+)?warehouse|warehouse|hospital|"
        r"office to laborator\w*)\b",
        activity_context,
    )
    existing_building_work = re.search(
        r"\b(?:remodel|renovat\w*|alterations?|interior remodel)\b", activity_context
    )
    additional_emergency_generators = re.search(
        r"\badditional\s+(?:two|\d+)?\s*\(?\s*\d*\s*\)?\s*"
        r"(?:diesel[- ]fired\s+)?emergency generators?\b",
        context,
    )
    existing_standby_fleet = re.search(
        r"\b(?:facility|data center)\s+(?:is\s+)?(?:operating|consists of)\b"
        r".{0,180}\bemergency generators\b",
        context,
    )
    explicit_development = re.search(
        r"\b(?:new|construct\w*|expand\w*|increas\w*|install\w*|development|"
        r"until (?:the )?(?:grid|utility))\b",
        context,
    )
    unchanged_site_capacity = re.search(
        r"\bno change in (?:the )?(?:facility\s*-?\s*wide )?"
        r"(?:fuel consumption|load|capacity)\b",
        context,
    )
    if (
        dimensions["physical_project_event"] >= 0.75
        and dimensions["meaningful_new_activity"] >= 0.8
        and dimensions["routine_maintenance"] <= 0.2
        and dimensions["transient_event"] <= 0.2
    ):
        if (
            (
                dimensions["commercial_relevance"] >= 0.7
                or (
                    power_relevant_sector
                    and dimensions["commercial_relevance"] >= 0.3
                    and explicit_development
                )
            )
            and not (
                dimensions["temporary_power_relevance"] < 0.5
                and (
                    generic_building
                    or (
                        existing_building_work
                        and not (
                            re.search(r"\bdata cent(?:er|re)\b", context) and explicit_development
                        )
                    )
                )
            )
            and not (
                dimensions["commercial_relevance"] < 0.7
                and additional_emergency_generators
                and existing_standby_fleet
            )
            and not (dimensions["commercial_relevance"] < 0.7 and unchanged_site_capacity)
        ):
            return "SHOW"
    return "REVIEW"


def adjudicate_current_signals(
    session: Session, *, limit: int = 100, policy_version: str = POLICY_VERSION
) -> dict[str, int]:
    """Bounded backfill for retained Signal evidence; safe to replay by version."""
    bound = max(1, min(limit, 500))
    counts = {"processed": 0, "show": 0, "review": 0, "hold": 0}

    # Existing Taylor revisions predate this table; retain their current
    # deterministic display decision without changing the historical evidence.
    taylor = session.execute(
        select(Observation, Evidence, Interpretation)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            Observation.source_id == "taylor-development-newsflash",
            Interpretation.status != "accepted",
            Interpretation.assessment["evidence_hash"].as_string() == Evidence.content_hash,
        )
        .order_by(Observation.id, Evidence.observed_at.desc())
        .limit(bound)
    ).all()
    for observation, evidence, interpretation in taylor:
        assessment = interpretation.assessment or {}
        if assessment.get("withdrawal_supported") is True:
            decision, dimension, reason = (
                "HOLD",
                "planning_application_withdrawn",
                "Official linked planning withdrawal; earlier project evidence remains "
                "historical and viability is UNKNOWN.",
            )
        elif "conflicting project or site facts" in str(assessment.get("reason") or ""):
            decision, dimension, reason = (
                "REVIEW",
                "identity_conflict",
                "Taylor revision conflicts with retained project or site facts; "
                "application and project status are UNKNOWN.",
            )
        else:
            continue
        prior = session.scalar(
            select(SignalDecision)
            .where(
                SignalDecision.observation_id == observation.id,
                SignalDecision.content_hash == evidence.content_hash,
                SignalDecision.policy_version == policy_version,
            )
            .order_by(SignalDecision.id.desc())
        )
        if prior is None or prior.decision != decision or prior.source != "deterministic":
            session.add(
                SignalDecision(
                    observation_id=observation.id,
                    content_hash=evidence.content_hash,
                    policy_version=policy_version,
                    decision=decision,
                    source="deterministic",
                    model_version=None,
                    dimensions={dimension: True},
                    reason=reason,
                )
            )
        counts["processed"] += 1
        counts[decision.casefold()] += 1

    remaining = bound - counts["processed"]
    if remaining <= 0:
        return counts

    current = session.execute(
        select(Observation, Evidence)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
        .where(
            Interpretation.status == "accepted",
            PowerNeed.tier == "Signal",
            PowerNeed.active.is_(True),
            Interpretation.assessment["evidence_hash"].as_string() == Evidence.content_hash,
        )
        .distinct()
        .order_by(Observation.id, Evidence.observed_at.desc())
        .limit(remaining)
    ).all()
    seen: set[UUID] = set()
    for observation, evidence in current:
        if observation.id in seen:
            continue
        seen.add(observation.id)
        signal_decision = adjudicate(session, observation, evidence, policy_version=policy_version)
        counts["processed"] += 1
        counts[signal_decision.decision.casefold()] += 1
    return counts
