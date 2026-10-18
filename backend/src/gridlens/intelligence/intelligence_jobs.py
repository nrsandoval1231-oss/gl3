"""Fenced shared-ledger queue for bounded advisory intelligence work."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.integrations.intelligence_provider import (
    GROUNDED_INSTRUCTIONS,
    call_openai,
    call_typesafe,
    openai_request_payload,
)
from gridlens.integrations.logical_calls import (
    cancel_call,
    complete_call,
    fail_call,
    mark_dispatched,
    reserve_call,
)
from gridlens.intelligence.grounded_candidates import validate_grounded_candidates
from gridlens.intelligence.jev_contracts import CONTRACTS, validate_answer
from gridlens.intelligence.question_contracts import QUESTION_CONTRACTS, question_contract
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings

JOB_KIND = "intelligence_process"
POLICY_VERSION = "bounded-intelligence-v1"
SCHEMA_VERSION = "intelligence-request-v1"
MAX_CONTEXT_BYTES = 45_000
MAX_PROVIDER_RESPONSE_BYTES = 65_536
GROUND_TASKS = {"GROUNDED_EXTRACTION", "GROUNDED_DOSSIER"}
LEGACY_BRIEF_OUTPUT_TOKENS = 700
LEGACY_TASKS = {
    "POWER_NEED_BRIEF",
    "SIGNAL_ADJUDICATION",
    "EVIDENCE_SHADOW",
    "JEV_HEALTH_PROBE",
    "FIRECRAWL_SEARCH_V2",
    "FIRECRAWL_SCRAPE_V2",
}


def legacy_paid_path_block_reason() -> str | None:
    """Compatibility name: legacy work now uses the same explicit ledger policy."""
    if not settings.intelligence_enabled or settings.intelligence_mode == "disabled":
        return "INTELLIGENCE_DISABLED"
    if settings.intelligence_mode == "bounded_routing":
        return "LEGACY_TASK_NOT_AUTHORIZED_FOR_ROUTING"
    if settings.intelligence_max_active_calls <= 0 or settings.intelligence_max_call_usd <= 0:
        return "FINITE_BUDGET_REQUIRED"
    return None


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _retained_context(
    session: Session, need_id: UUID
) -> tuple[PowerNeed, Project, Source, list[dict[str, Any]]]:
    need = session.get(PowerNeed, need_id)
    if need is None or not need.active:
        raise ValueError("Active power need is required")
    project = session.get(Project, need.project_id)
    source = session.get(Source, project.source_id) if project else None
    if project is None or source is None or not source.enabled or not source.registry_enabled:
        raise ValueError("Need must resolve to its enabled actual source")
    rows = session.execute(
        select(Evidence, Observation, Source, Interpretation)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .where(NeedObservation.need_id == need_id)
        .order_by(Evidence.observed_at.desc(), Evidence.id)
        .limit(24)
    ).all()
    evidence = [
        {
            "id": str(ev.id),
            "content_hash": ev.content_hash,
            "title": ev.title[:600],
            "abstract": (ev.abstract or "")[:1800],
            "url": ev.url[:1200],
            "published_at": ev.published_at.isoformat() if ev.published_at else None,
            "publisher": evidence_source.publisher,
        }
        for ev, observation, evidence_source, interpretation in rows
        if (evidence_source.enabled and evidence_source.registry_enabled)
        or (
            not evidence_source.enabled
            and not evidence_source.registry_enabled
            and observation.content_hash == ev.content_hash
            and interpretation is not None
            and interpretation.status == "accepted"
            and interpretation.content_hash == observation.content_hash
            and interpretation.assessment is not None
            and interpretation.assessment.get("admission_status") == "project_research_supplement"
            and interpretation.assessment.get("semantic_hash") == observation.content_hash
            and interpretation.assessment.get("evidence_hash") == ev.content_hash
            and interpretation.assessment.get("target_need_id") == str(need.id)
            and interpretation.assessment.get("project_identity_key") == project.identity_key
        )
    ]
    if not evidence:
        raise ValueError("No retained evidence is attached to this need")
    from gridlens.domain.call_facts import current_accepted_facts

    versions = session.scalars(
        select(CallFactVersion).where(CallFactVersion.need_id == need_id)
    ).all()
    decisions = session.scalars(
        select(CallFactDecision).where(CallFactDecision.need_id == need_id)
    ).all()
    accepted_facts = [
        {
            "fact_type": row.fact_type,
            "value": row.value,
            "effective_from": row.effective_from.isoformat(),
            "effective_until": row.effective_until.isoformat() if row.effective_until else None,
            "content_hash": row.content_hash,
        }
        for row in current_accepted_facts(list(versions), list(decisions))
    ]
    need._intelligence_accepted_facts = accepted_facts  # type: ignore[attr-defined]
    return need, project, source, evidence


def _request_payload(
    task_type: str,
    question_id: str | None,
    need: PowerNeed,
    project: Project,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    current_state = {
        "need_id": str(need.id),
        "need_updated_at": need.updated_at.isoformat() if need.updated_at else None,
        "admission_basis": need.admission_basis,
        "accepted_operator_facts": getattr(need, "_intelligence_accepted_facts", []),
        "project_identity_key": project.identity_key,
        "project_identity_facts": project.identity_facts,
    }
    state_version_digest = _digest(current_state)
    if task_type in CONTRACTS:
        contract = CONTRACTS[task_type]
        questions = {
            "answer": {
                "type": "choice",
                "instructions": (
                    f"Choose exactly one advisory answer for {task_type} "
                    "using only the retained evidence."
                ),
                "criteria": {choice: choice for choice in contract.choices},
            }
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "task_type": task_type,
            "need": {
                "need_id": str(need.id),
                "project_id": str(project.id),
                "activity": need.activity_key,
                "rationale": need.rationale[:1200],
                "required_mw": need.required_mw,
                "start_window": need.start_window,
                "duration": need.duration,
                "supply": need.supply,
                "updated_at": need.updated_at.isoformat() if need.updated_at else None,
                "admission_basis": need.admission_basis,
                "accepted_operator_facts": getattr(need, "_intelligence_accepted_facts", []),
                "project_identity_key": project.identity_key,
                "project_identity_facts": project.identity_facts,
                "state_version_digest": state_version_digest,
            },
            "evidence": evidence,
            "questions": questions,
        }
    if task_type in GROUND_TASKS:
        question_spec = question_contract(question_id or "TEMP_LOAD_MW")
        return {
            "schema_version": SCHEMA_VERSION,
            "task_type": task_type,
            "question": question_spec,
            "need": {
                "need_id": str(need.id),
                "project_id": str(project.id),
                "project_name": project.name[:200],
                "activity": need.activity_key,
                "rationale": need.rationale[:1200],
                "updated_at": need.updated_at.isoformat() if need.updated_at else None,
                "admission_basis": need.admission_basis,
                "accepted_operator_facts": getattr(need, "_intelligence_accepted_facts", []),
                "project_identity_key": project.identity_key,
                "project_identity_facts": project.identity_facts,
                "state_version_digest": state_version_digest,
            },
            "evidence": evidence,
        }
    raise ValueError("Unknown intelligence task type")


def enqueue_intelligence(
    session: Session,
    *,
    need_id: UUID,
    task_type: str,
    question_id: str | None = None,
    origin: str = "operator",
) -> Job:
    """Queue one exact need/evidence request; active unchanged jobs are reused."""
    need, project, source, evidence = _retained_context(session, need_id)
    payload = _request_payload(task_type, question_id, need, project, evidence)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Bounded intelligence context exceeds size limit")
    identity = _digest(payload)
    # Serialize only this need's active queue identity so concurrent monitor
    # observations cannot create duplicate active jobs.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{need_id}:{task_type}:{question_id or ''}"},
    )
    for job in session.scalars(
        select(Job)
        .where(
            Job.kind == JOB_KIND,
            Job.target_id == need_id,
            Job.status.in_(["queued", "running"]),
        )
        .order_by(Job.created_at.desc())
        .limit(10)
    ):
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (ValueError, TypeError):
            continue
        if checkpoint.get("request_digest") == identity and job.status in {"queued", "running"}:
            return job
    research_question_id, created_research_question = _linked_research_question(
        session, need_id, question_id, payload, identity
    )
    job = Job(
        source_id=source.id,
        kind=JOB_KIND,
        target_id=need_id,
        checkpoint=json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "task_type": task_type,
                "question_id": question_id,
                "origin": origin[:40],
                "request_digest": identity,
                "payload": payload,
                "status": "queued",
                "research_question_id": research_question_id,
                "research_question_created": created_research_question,
            },
            separators=(",", ":"),
        ),
    )
    session.add(job)
    session.flush()
    checkpoint = json.loads(job.checkpoint or "{}")
    checkpoint["job_id"] = str(job.id)
    job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
    return job


def _linked_research_question(
    session: Session,
    need_id: UUID,
    question_id: str | None,
    payload: dict[str, Any],
    request_digest: str,
) -> tuple[str | None, bool]:
    if not question_id:
        return None, False
    contract = question_contract(question_id)
    category = contract["category"]
    row = session.scalar(
        select(PursuitResearchQuestion)
        .where(
            PursuitResearchQuestion.need_id == need_id, PursuitResearchQuestion.category == category
        )
        .order_by(PursuitResearchQuestion.created_at.desc())
        .limit(1)
    )
    if row:
        return str(row.id), False
    need = session.get(PowerNeed, need_id)
    pursuit = (
        session.scalar(
            select(Pursuit)
            .where(Pursuit.project_id == need.project_id)
            .order_by(Pursuit.id)
            .limit(1)
        )
        if need
        else None
    )
    if pursuit is None or need is None:
        return None, False
    evidence_digest = _digest(
        [(item["id"], item["content_hash"]) for item in payload.get("evidence", [])]
    )
    versioned = PursuitResearchQuestion(
        pursuit_id=pursuit.id,
        project_id=need.project_id,
        need_id=need_id,
        parent_id=None,
        category=category,
        question=contract["question"],
        status="QUEUED",
        attempt_count=0,
        query_fingerprint=request_digest,
        evidence_fingerprint=evidence_digest,
        context={
            "origin": "bounded_intelligence",
            "question_id": question_id,
            "contract_version": contract["version"],
            "task_type": "GROUNDED_DOSSIER",
            "request_digest": request_digest,
            "authority": "ADVISORY_ONLY",
        },
        budget={"mode": "intelligence_advisory", "network_calls": 0, "max_cost_usd": "0"},
        receipt={
            "source_checks": [],
            "resulting_evidence_ids": [],
            "reevaluation_status": "NOT_STARTED",
            "intelligence_only": True,
        },
    )
    session.add(versioned)
    session.flush()
    return str(versioned.id), True


def enqueue_missing_intelligence(
    session: Session,
    *,
    need_id: UUID,
    question_ids: list[str],
    origin: str = "monitoring",
) -> list[Job]:
    """Queue up to two unresolved high-value questions after retained context changes."""
    if (
        not settings.intelligence_enabled
        or settings.intelligence_mode not in {"evaluation", "advisory"}
        or not settings.intelligence_openai_enabled
        or not settings.intelligence_research_enabled
        or not settings.openai_api_key
        or not settings.intelligence_openai_reasoning_model
        or settings.intelligence_max_call_usd <= 0
        or settings.intelligence_max_active_calls <= 0
    ):
        return []
    priority = {
        "TEMP_LOAD_MW": 0,
        "UTILITY_ONLINE_DATE": 1,
        "COMMISSIONING_WINDOW": 2,
        "CONSTRUCTION_START": 3,
        "DIRECT_BUYER_AUTHORITY": 4,
        "NATURAL_GAS_AVAILABILITY": 5,
    }
    allowed = {
        item.strip() for item in settings.intelligence_enabled_contracts.split(",") if item.strip()
    }
    selected = sorted(
        {item for item in question_ids if item in QUESTION_CONTRACTS and item in allowed},
        key=lambda item: (priority[item], item),
    )[:2]
    return [
        enqueue_intelligence(
            session,
            need_id=need_id,
            task_type="GROUNDED_DOSSIER",
            question_id=question_id,
            origin=origin,
        )
        for question_id in selected
    ]


def _enabled(task_type: str, question_id: str | None = None) -> tuple[bool, str, str, str]:
    mode = settings.intelligence_mode
    allowlist = {v.strip() for v in settings.intelligence_enabled_contracts.split(",") if v.strip()}
    if (question_id if task_type in GROUND_TASKS else task_type) not in allowlist:
        return False, "", "", "CONTRACT_DISABLED"
    if task_type == "MATCH_ADVISORY_V1":
        return False, "", "", "MATCH_CONTEXT_INCOMPLETE"
    if not settings.intelligence_enabled or mode not in {
        "evaluation",
        "advisory",
        "bounded_routing",
    }:
        return False, "", "", "INTELLIGENCE_DISABLED"
    if mode == "bounded_routing":
        if task_type not in {"RESEARCH_PRIORITY_V1", "LLM_ROUTE_V1"}:
            return False, "", "", "ROUTING_TASK_NOT_AUTHORIZED"
        if not (
            settings.intelligence_routing_policy_id
            and settings.intelligence_routing_policy_evaluated
            and settings.intelligence_bounded_routing_authorized
        ):
            return False, "", "", "ROUTING_POLICY_NOT_EVALUATED_OR_AUTHORIZED"
    if task_type in GROUND_TASKS:
        if not settings.intelligence_openai_enabled or not settings.intelligence_research_enabled:
            return False, "", "", "OPENAI_OR_RESEARCH_DISABLED"
        model = (
            settings.intelligence_openai_fast_model
            if task_type == "GROUNDED_EXTRACTION"
            else settings.intelligence_openai_reasoning_model
        )
        if not settings.openai_api_key or not model:
            return False, "", "", "OPENAI_KEY_OR_PINNED_MODEL_MISSING"
        prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
        output_bound = getattr(settings, f"intelligence_openai_{prefix}_max_output_tokens")
        priced_model = getattr(settings, f"intelligence_openai_{prefix}_priced_model_id")
        pricing_verified = getattr(settings, f"intelligence_openai_{prefix}_pricing_verified")
        if output_bound <= 0 or priced_model != model or not pricing_verified:
            return False, "", "", "OPENAI_OUTPUT_BOUND_OR_MODEL_PRICING_MISSING"
        if (
            getattr(settings, f"intelligence_openai_{prefix}_input_usd_per_million") <= 0
            or getattr(settings, f"intelligence_openai_{prefix}_output_usd_per_million") < 0
        ):
            return False, "", "", "OPENAI_TRUSTED_PRICING_MISSING"
        return True, "openai", model, ""
    if task_type in LEGACY_TASKS:
        if settings.intelligence_mode not in {"evaluation", "advisory"}:
            return False, "", "", "LEGACY_TASK_REQUIRES_EVALUATION_OR_ADVISORY"
        if task_type in {"FIRECRAWL_SEARCH_V2", "FIRECRAWL_SCRAPE_V2"}:
            unit_cost = (
                settings.firecrawl_search_cost_usd
                if task_type == "FIRECRAWL_SEARCH_V2"
                else settings.firecrawl_scrape_cost_usd
            )
            if (
                not settings.intelligence_research_enabled
                or not settings.firecrawl_api_key
                or unit_cost is None
                or unit_cost <= 0
            ):
                return False, "", "", "FIRECRAWL_DISABLED_OR_UNIT_COST_MISSING"
            return True, "firecrawl", task_type.casefold(), ""
        if task_type == "POWER_NEED_BRIEF":
            if not settings.intelligence_openai_enabled or not settings.openai_api_key:
                return False, "", "", "OPENAI_DISABLED_OR_KEY_MISSING"
            model = settings.openai_brief_model
            if model != settings.intelligence_openai_reasoning_model:
                return False, "", "", "BRIEF_MODEL_NOT_MATCHED_TO_PRICED_REASONING_MODEL"
            if (
                not settings.intelligence_openai_reasoning_pricing_verified
                or settings.intelligence_openai_reasoning_priced_model_id != model
                or settings.intelligence_openai_reasoning_max_output_tokens
                < LEGACY_BRIEF_OUTPUT_TOKENS
                or settings.intelligence_openai_reasoning_input_usd_per_million <= 0
                or settings.intelligence_openai_reasoning_output_usd_per_million < 0
            ):
                return False, "", "", "OPENAI_OUTPUT_BOUND_OR_MODEL_PRICING_MISSING"
            return True, "openai", model, ""
        expected_model = settings.intelligence_typesafe_model
        if not settings.jev_enabled or not settings.intelligence_typesafe_enabled:
            return False, "", "", "TYPESAFE_DISABLED"
        if not settings.typesafe_api_key:
            return False, "", "", "TYPESAFE_KEY_OR_PINNED_MODEL_MISSING"
        if (
            not settings.intelligence_typesafe_pricing_verified
            or not expected_model
            or settings.intelligence_typesafe_priced_model_id != expected_model
            or settings.intelligence_typesafe_input_usd_per_million <= 0
        ):
            return False, "", "", "TYPESAFE_INPUT_PRICING_OR_MODEL_MISSING"
        return True, "typesafe", expected_model, ""
    if not settings.jev_enabled or not settings.intelligence_typesafe_enabled:
        return False, "", "", "TYPESAFE_DISABLED"
    if not settings.typesafe_api_key or not settings.intelligence_typesafe_model:
        return False, "", "", "TYPESAFE_KEY_OR_PINNED_MODEL_MISSING"
    if (
        not settings.intelligence_typesafe_pricing_verified
        or settings.intelligence_typesafe_priced_model_id != settings.intelligence_typesafe_model
        or settings.intelligence_typesafe_input_usd_per_million <= 0
    ):
        return False, "", "", "TYPESAFE_INPUT_PRICING_OR_MODEL_MISSING"
    return True, "typesafe", settings.intelligence_typesafe_model, ""


def _caps() -> dict[str, dict[str, int | Decimal]]:
    result = {}
    for scope, key in (
        ("global", "global"),
        ("provider", "provider"),
        ("model", "model"),
        ("source", "source"),
        ("project", "project"),
    ):
        result[scope] = {
            "daily": getattr(settings, f"intelligence_{key}_daily_calls"),
            "monthly": getattr(settings, f"intelligence_{key}_monthly_calls"),
            "daily_usd": getattr(settings, f"intelligence_{key}_daily_usd"),
            "monthly_usd": getattr(settings, f"intelligence_{key}_monthly_usd"),
        }
    return result


def _dispatch_policy(
    task_type: str,
    question_id: str | None,
    provider: str,
    model: str,
    payload: dict[str, Any],
    reserved_cost: Decimal,
) -> tuple[bool, str]:
    enabled, current_provider, current_model, reason = _enabled(task_type, question_id)
    if not enabled or current_provider != provider or current_model != model:
        return False, reason or "PROVIDER_POLICY_CHANGED"
    if settings.intelligence_max_call_usd <= 0 or settings.intelligence_max_active_calls <= 0:
        return False, "FINITE_BUDGET_REQUIRED"
    current_cost = _cost_bound(provider, task_type, payload)
    if (
        current_cost <= 0
        or current_cost != reserved_cost
        or current_cost > settings.intelligence_max_call_usd
    ):
        return False, "CURRENT_COST_CEILING_INVALID"
    scopes = _caps()
    for scope, limits in scopes.items():
        for period in ("daily", "monthly"):
            count_cap = limits[period]
            usd_cap = limits[f"{period}_usd"]
            if type(count_cap) is not int or count_cap <= 0:
                return False, f"{scope.upper()}_{period.upper()}_CAP_ZERO"
            if usd_cap <= 0 or current_cost > usd_cap:
                return False, f"{scope.upper()}_{period.upper()}_USD_CAP_INVALID"
    return True, ""


def _cost_bound(provider: str, task_type: str, payload: dict[str, Any]) -> Decimal:
    if provider == "firecrawl":
        unit = (
            settings.firecrawl_search_cost_usd
            if task_type == "FIRECRAWL_SEARCH_V2"
            else settings.firecrawl_scrape_cost_usd
        )
        return unit or Decimal("0")
    if provider == "openai":
        from gridlens.intelligence.briefs import brief_request_payload

        if task_type == "POWER_NEED_BRIEF":
            request = brief_request_payload(
                payload["brief"], payload["facts"], model=settings.openai_brief_model
            )
            input_price = settings.intelligence_openai_reasoning_input_usd_per_million
            output_price = settings.intelligence_openai_reasoning_output_usd_per_million
            output_tokens = settings.intelligence_openai_reasoning_max_output_tokens
            request_bytes = _serialized_request_bytes(request)
            return (
                Decimal(request_bytes) * input_price + Decimal(output_tokens) * output_price
            ) / Decimal(1_000_000)
        prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
        input_price = getattr(settings, f"intelligence_openai_{prefix}_input_usd_per_million")
        output_price = getattr(settings, f"intelligence_openai_{prefix}_output_usd_per_million")
        output_tokens = getattr(settings, f"intelligence_openai_{prefix}_max_output_tokens")
        model = (
            settings.intelligence_openai_fast_model
            if task_type == "GROUNDED_EXTRACTION"
            else settings.intelligence_openai_reasoning_model
        )
        request = openai_request_payload(
            model=model,
            instructions=GROUNDED_INSTRUCTIONS,
            input_payload=payload,
            max_output_tokens=output_tokens,
        )
        request_bytes = _serialized_request_bytes(request)
    else:
        input_price = settings.intelligence_typesafe_input_usd_per_million
        # TypeSafe's documented client exposes no output-token cap. Price a
        # conservative full-request input bound only; retain actual usage as NULL.
        output_price = Decimal("0")
        output_tokens = 0
        from gridlens.integrations.typesafe_evidence_judge import TypesafeEvidenceJudge
        from gridlens.intelligence.signal_adjudication import jev_request_payload

        model = settings.intelligence_typesafe_model
        if task_type in {"SIGNAL_ADJUDICATION", "JEV_HEALTH_PROBE"}:
            request = jev_request_payload(payload["state"], model=model)
        elif task_type == "EVIDENCE_SHADOW":
            request = TypesafeEvidenceJudge.build_request(
                payload["project"], payload["evidence"], payload["candidates"], model=model
            )
        elif task_type in CONTRACTS or task_type in GROUND_TASKS:
            request = typesafe_request_payload(task_type, payload, model=model)
        else:
            # Until a transport-specific request builder exists, unknown wrappers
            # are not activated under a fabricated byte estimate.
            return Decimal("0")
        request_bytes = _serialized_request_bytes(request)
    # One byte per token is a conservative bound over the complete serialized request.
    return (Decimal(request_bytes) * input_price + Decimal(output_tokens) * output_price) / Decimal(
        1_000_000
    )


def _estimated_cost_from_usage(
    provider: str, task_type: str, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    if input_tokens is None or output_tokens is None:
        return None
    if type(input_tokens) is not int or input_tokens < 0:
        raise ValueError("Provider input token usage is invalid")
    if type(output_tokens) is not int or output_tokens < 0:
        raise ValueError("Provider output token usage is invalid")
    if provider == "openai":
        prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
        input_price = getattr(settings, f"intelligence_openai_{prefix}_input_usd_per_million")
        output_price = getattr(settings, f"intelligence_openai_{prefix}_output_usd_per_million")
    else:
        input_price = settings.intelligence_typesafe_input_usd_per_million
        output_price = Decimal("0")
    return (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / Decimal(
        1_000_000
    )


def _serialized_request_bytes(request: dict[str, Any]) -> int:
    return len(
        json.dumps(
            request,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )


def typesafe_request_payload(
    task_type: str, payload: dict[str, Any], *, model: str
) -> dict[str, Any]:
    """Build the complete TypeSafe HTTP JSON body used for a catalog contract."""
    if task_type not in CONTRACTS and task_type not in GROUND_TASKS:
        raise ValueError("No catalog TypeSafe request contract for task")
    return {
        "model": model,
        "state": {
            "schema_version": payload["schema_version"],
            "task_type": task_type,
            "need": payload["need"],
            "evidence": payload["evidence"],
        },
        "questions": payload["questions"],
    }


def _type_safe_result(
    data: dict[str, Any], task_type: str
) -> tuple[dict[str, Any], str, int | None, int | None]:
    if not isinstance(data.get("model"), str) or not data["model"]:
        raise ValueError("Provider response omitted actual model")
    answer = data.get("answers", {}).get("answer")
    if not isinstance(answer, dict) or set(answer) != {
        "type",
        "choice",
        "confidence",
        "probabilities",
    }:
        raise ValueError("TypeSafe answer shape mismatch")
    if answer.get("type") != "choice":
        raise ValueError("TypeSafe answer type must be choice")
    contract = CONTRACTS[task_type]
    confidence = answer.get("confidence")
    probabilities = answer.get("probabilities")
    if (
        not isinstance(confidence, int | float)
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or not isinstance(probabilities, dict)
        or set(probabilities) != set(contract.choices)
        or any(
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in probabilities.values()
        )
        or not 0.98 <= sum(probabilities.values()) <= 1.02
    ):
        raise ValueError("TypeSafe confidence or probabilities are invalid")
    validated = validate_answer(
        task_type,
        {key: value for key, value in answer.items() if key != "type"},
    )
    usage_value = data.get("usage")
    usage: dict[str, Any] = usage_value if isinstance(usage_value, dict) else {}
    counts = []
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Provider token usage is invalid")
        counts.append(value)
    return (
        {
            "schema_version": "jev-advisory-v1",
            "answer": validated.model_dump(),
            "authority": "ADVISORY_ONLY",
        },
        data["model"],
        counts[0],
        counts[1],
    )


def process_intelligence_job(job_id: UUID, worker_id: str, fence_token: int) -> dict[str, Any]:
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_response_id: str | None = None
    provider_response_complete = False
    # Prepare bounded input and the ledger identity while holding only the job
    # fence. reserve_call commits its own transaction, so never pass it this
    # session or retain a job row lock across that call.
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
            task_type = checkpoint["task_type"]
            payload = checkpoint["payload"]
            if job.target_id is None:
                raise ValueError("Intelligence job has no target need")
            need, project, source, evidence = _retained_context(session, job.target_id)
            current = _request_payload(
                task_type, checkpoint.get("question_id"), need, project, evidence
            )
            if _digest(current) != checkpoint.get("request_digest"):
                checkpoint.update(status="stale", error="INPUT_CHANGED_BEFORE_DISPATCH")
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                _record_research_receipt(session, checkpoint)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                return {"status": "stale", "job_id": str(job_id)}
            enabled, provider, model, reason = _enabled(task_type, checkpoint.get("question_id"))
            if not enabled:
                checkpoint.update(status="blocked", error=reason)
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                _record_research_receipt(session, checkpoint)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                return {"status": "blocked", "error": reason, "job_id": str(job_id)}
            task_key = f"{need.id}:{checkpoint.get('question_id') or task_type}"
            evidence_digest = _digest([(item["id"], item["content_hash"]) for item in evidence])
            routing_approval = None
            if settings.intelligence_mode == "bounded_routing":
                routing_approval = {
                    "policy_id": settings.intelligence_routing_policy_id,
                    "evaluated": settings.intelligence_routing_policy_evaluated,
                    "authorized": settings.intelligence_bounded_routing_authorized,
                }
                checkpoint["routing_approval"] = routing_approval
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            context_digest = _digest({"payload": payload, "routing_approval": routing_approval})
            max_cost = _cost_bound(provider, task_type, payload)
            if (
                max_cost <= 0
                or settings.intelligence_max_call_usd <= 0
                or max_cost > settings.intelligence_max_call_usd
                or settings.intelligence_max_active_calls <= 0
            ):
                checkpoint.update(status="blocked", error="FINITE_BUDGET_REQUIRED")
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                _record_research_receipt(session, checkpoint)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                return {
                    "status": "blocked",
                    "error": "FINITE_BUDGET_REQUIRED",
                    "job_id": str(job_id),
                }
            reserve_args = {
                "task_type": task_type,
                "task_key": task_key,
                "evidence_digest": evidence_digest,
                "context_digest": context_digest,
                "prompt_contract": SCHEMA_VERSION,
                "provider": provider,
                "model": model,
                "policy_version": POLICY_VERSION,
                "source_id": source.id,
                "project_id": project.id,
                "lease_authority": "job",
                "job_id": job.id,
                "worker_id": worker_id,
                "enabled": True,
                "estimated_cost_usd": max_cost,
                "max_cost_usd": max_cost,
                "caps": _caps(),
                "max_active": settings.intelligence_max_active_calls,
                "fence_token": fence_token,
            }
        except (ValueError, KeyError, TypeError) as exc:
            checkpoint = locals().get("checkpoint", {})
            checkpoint.update(status="blocked", error=type(exc).__name__)
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
            return {"status": "blocked", "error": type(exc).__name__, "job_id": str(job_id)}

    with SessionLocal() as session:
        reservation = reserve_call(session, **reserve_args)
    if not reservation.call_id or reservation.blocked_reason:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint.update(status="blocked", error=reservation.blocked_reason)
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            _record_research_receipt(session, checkpoint)
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
        return {"status": "blocked", "error": reservation.blocked_reason, "job_id": str(job_id)}
    call_id = reservation.call_id
    if reservation.status == "COMPLETED":
        from gridlens.persistence.models import LogicalCall

        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            cached = session.get(LogicalCall, call_id)
            result = cached.result_payload if cached else None
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint.update(
                status="completed",
                result=result,
                logical_call_id=str(call_id),
                cached=True,
            )
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
            _record_research_receipt(session, checkpoint)
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
        return {"status": "completed", "result": result, "job_id": str(job_id)}
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(status="dispatching", logical_call_id=str(call_id), request=payload)
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))

    dispatch_enabled, dispatch_reason = _dispatch_policy(
        task_type,
        checkpoint.get("question_id"),
        provider,
        model,
        payload,
        max_cost,
    )
    with SessionLocal() as session:
        dispatched = mark_dispatched(
            session,
            call_id,
            fence_token=fence_token,
            enabled=dispatch_enabled,
        )
    if dispatched.status != "SENT_OUTCOME_UNKNOWN" or dispatched.blocked_reason is not None:
        if dispatched.blocked_reason == "INTELLIGENCE_DISABLED":
            with SessionLocal() as session:
                cancel_call(session, call_id, fence_token=fence_token)
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            checkpoint = json.loads(job.checkpoint or "{}")
            checkpoint.update(status="blocked", error=dispatch_reason or dispatched.blocked_reason)
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            _record_research_receipt(session, checkpoint)
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
        return {"status": "blocked", "error": dispatched.blocked_reason, "job_id": str(job_id)}

    try:
        if provider == "typesafe":
            key = settings.typesafe_api_key.get_secret_value() if settings.typesafe_api_key else ""
            typesafe_payload = typesafe_request_payload(task_type, payload, model=model)
            data = call_typesafe(
                api_key=key,
                model=model,
                payload={key: value for key, value in typesafe_payload.items() if key != "model"},
            )
            provider_response_complete = True
            provider_response_id = data.get("provider_response_id")
            parsed, actual_model, input_tokens, output_tokens = _type_safe_result(data, task_type)
        else:
            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            instructions = GROUNDED_INSTRUCTIONS
            output_limit = (
                settings.intelligence_openai_fast_max_output_tokens
                if task_type == "GROUNDED_EXTRACTION"
                else settings.intelligence_openai_reasoning_max_output_tokens
            )
            data = call_openai(
                api_key=key,
                model=model,
                instructions=instructions,
                input_payload=payload,
                max_output_tokens=output_limit,
            )
            provider_response_complete = True
            provider_response_id = data.get("provider_response_id")
            parsed = validate_grounded_candidates(data["output"], payload["evidence"])
            response_model = data.get("model")
            input_tokens, output_tokens = data.get("input_tokens"), data.get("output_tokens")
            if not isinstance(response_model, str) or not response_model:
                raise ValueError("Provider response omitted actual model")
            actual_model = response_model
        call_result = {
            **parsed,
            "provider": provider,
            "actual_model": actual_model,
            "latency_ms": data.get("latency_ms", data.get("provider_latency_ms")),
        }
        estimated_cost = _estimated_cost_from_usage(
            provider, task_type, input_tokens, output_tokens
        )
        call_result["usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "actual_cost_usd": None,
            "estimated_cost_usd": str(estimated_cost) if estimated_cost is not None else None,
            "cost_basis": (
                "derived_from_verified_usage_and_pinned_rates"
                if estimated_cost is not None
                else None
            ),
        }
        result_digest = _digest(call_result)
        with SessionLocal() as session:
            complete_call(
                session,
                call_id,
                fence_token=fence_token,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                result_digest=result_digest,
                result_payload=call_result,
            )
        status = "completed"
        error = None
    except Exception as exc:
        provider_response_id = provider_response_id or getattr(exc, "request_id", None)
        response_ref = f"response:{provider_response_id}" if provider_response_id else None
        terminal_failure = False
        if response_ref and (getattr(exc, "conclusive", False) or provider_response_complete):
            with SessionLocal() as session:
                failure = fail_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=response_ref,
                )
                terminal_failure = failure.status == "FAILED"
        status = "failed" if terminal_failure else "unknown"
        error, call_result = type(exc).__name__, None

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(
            status=status,
            completed_at=datetime.now(UTC).isoformat(),
            result=call_result,
            error=error,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "actual_cost_usd": None,
                "estimated_cost_usd": (
                    call_result.get("usage", {}).get("estimated_cost_usd") if call_result else None
                ),
                "cost_basis": call_result.get("usage", {}).get("cost_basis")
                if call_result
                else None,
            }
            if status == "completed"
            else None,
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
        _record_research_receipt(session, checkpoint)
        job.status = "succeeded" if status in {"completed", "unknown"} else "failed"
        job.lease_owner, job.lease_until = None, None
    return {"status": status, "result": call_result, "error": error, "job_id": str(job_id)}


def _record_research_receipt(session: Session, checkpoint: dict[str, Any]) -> None:
    question_id = checkpoint.get("research_question_id")
    if not question_id:
        return
    question = session.get(PursuitResearchQuestion, UUID(question_id))
    if question is None:
        return
    question.receipt = {
        **question.receipt,
        "intelligence_job": {
            "job_id": checkpoint.get("job_id"),
            "logical_call_id": checkpoint.get("logical_call_id"),
            "status": checkpoint.get("status"),
            "result": checkpoint.get("result"),
            "error": checkpoint.get("error"),
            "evidence_ids": [
                item.get("id") for item in checkpoint.get("payload", {}).get("evidence", [])
            ],
        },
    }
    if checkpoint.get("research_question_created"):
        question.status = "UNRESOLVED"
        question.completed_at = datetime.now(UTC)


def intelligence_history(session: Session, need_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    rows = session.scalars(
        select(Job)
        .where(Job.kind == JOB_KIND, Job.target_id == need_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    ).all()
    output = []
    for job in rows:
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (ValueError, TypeError):
            checkpoint = {}
        status = checkpoint.get("status", job.status)
        output.append(
            {
                "job_id": str(job.id),
                "task_type": checkpoint.get("task_type"),
                "need_id": str(need_id),
                "status": status,
                "result": checkpoint.get("result"),
                "error": checkpoint.get("error"),
                "evidence_ids": [
                    item.get("id") for item in checkpoint.get("payload", {}).get("evidence", [])
                ],
                "logical_call_id": checkpoint.get("logical_call_id"),
                "usage": checkpoint.get("usage"),
                "reserved": bool(checkpoint.get("logical_call_id")),
                "uncertain": status == "unknown",
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": checkpoint.get("completed_at"),
            }
        )
    return output
