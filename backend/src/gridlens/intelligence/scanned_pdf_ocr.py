"""Dormant, source-permitted scanned-PDF OCR through the shared call ledger."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.govinfo_scan import (
    CAPTURE_KEY,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    capture_govinfo_pdf,
    merge_write_once_capture,
)
from gridlens.integrations.intelligence_provider import (
    GROUNDED_INSTRUCTIONS,
    call_openai_input_token_count,
    call_openai_request,
    ocr_request_payload,
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
from gridlens.intelligence.ocr_transcript import public_ocr_transcript, validate_ocr_transcript
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

JOB_KIND = "intelligence_process"
OCR_TASK = "OCR_EXTRACTION"
OCR_FOLLOWON_TASK = "OCR_GROUNDED_FOLLOWON"
OCR_POLICY_VERSION = "source-permitted-pdf-ocr-v1"
OCR_SCHEMA_VERSION = "scanned-pdf-ocr-request-v1"
OCR_PREFLIGHT_CONTRACT_VERSION = "responses-input-tokens-count-v1"


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _preflight_context_digest(model: str, count_body_digest: str) -> str:
    return _digest(
        {
            "contract_version": OCR_PREFLIGHT_CONTRACT_VERSION,
            "policy_version": OCR_POLICY_VERSION,
            "model": model,
            "count_body_digest": count_body_digest,
            "verified_upper_cost_usd": str(settings.intelligence_ocr_preflight_max_cost_usd),
            "cost_bound_verified": settings.intelligence_ocr_preflight_cost_bound_verified,
            "cost_bound_reference": settings.intelligence_ocr_preflight_cost_reference,
        }
    )


def _retention_source_ids() -> set[str]:
    return {
        value.strip()
        for value in settings.intelligence_ocr_retention_source_ids.split(",")
        if value.strip()
    }


def _caps_ready(cost: Decimal) -> bool:
    if settings.intelligence_max_active_calls <= 0:
        return False
    if (
        cost <= 0
        or settings.intelligence_max_call_usd <= 0
        or cost > settings.intelligence_max_call_usd
    ):
        return False
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            if getattr(settings, f"intelligence_{scope}_{period}_calls") <= 0:
                return False
            if getattr(settings, f"intelligence_{scope}_{period}_usd") < cost:
                return False
    return True


def _rows_for_evidence(
    session: Session, need_id: UUID, evidence_id: UUID
) -> tuple[PowerNeed, Project, Evidence, Observation, Source]:
    need = session.get(PowerNeed, need_id)
    if need is None or not need.active:
        raise ValueError("Active power need is required")
    project = session.get(Project, need.project_id)
    if project is None:
        raise ValueError("Power need project is missing")
    row = session.execute(
        select(Evidence, Observation, Source)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(NeedObservation.need_id == need_id, Evidence.id == evidence_id)
    ).first()
    if row is None:
        raise ValueError("Evidence is not attached to this exact need")
    evidence, observation, source = row
    return need, project, evidence, observation, source


def _ocr_configuration_ready(task_type: str = OCR_TASK) -> tuple[bool, str]:
    if not settings.intelligence_enabled or settings.intelligence_mode not in {
        "evaluation",
        "advisory",
    }:
        return False, "INTELLIGENCE_DISABLED"
    if not settings.intelligence_ocr_enabled:
        return False, "OCR_DISABLED"
    if not settings.intelligence_ocr_vision_enabled:
        return False, "OCR_VISION_NOT_AUTHORIZED"
    if not settings.intelligence_ocr_preflight_enabled:
        return False, "OCR_PREFLIGHT_DISABLED"
    if (
        not settings.intelligence_ocr_preflight_cost_bound_verified
        or not settings.intelligence_ocr_preflight_cost_reference.strip()
    ):
        return False, "OCR_PREFLIGHT_COST_BOUND_UNVERIFIED"
    if not settings.intelligence_openai_enabled or not settings.intelligence_research_enabled:
        return False, "OPENAI_OR_RESEARCH_DISABLED"
    allowed_tasks = _retention_task_allowlist()
    if OCR_TASK not in allowed_tasks:
        return False, "OCR_CONTRACT_DISABLED"
    if task_type == OCR_FOLLOWON_TASK and OCR_FOLLOWON_TASK not in allowed_tasks:
        return False, "OCR_FOLLOWON_CONTRACT_DISABLED"
    if not settings.openai_api_key or not settings.intelligence_ocr_model:
        return False, "OCR_KEY_OR_PINNED_MODEL_MISSING"
    if (
        settings.intelligence_ocr_priced_model_id != settings.intelligence_ocr_model
        or not settings.intelligence_ocr_pricing_verified
        or settings.intelligence_ocr_input_usd_per_million <= 0
        or settings.intelligence_ocr_output_usd_per_million <= 0
        or settings.intelligence_ocr_max_output_tokens <= 0
    ):
        return False, "OCR_MODEL_PRICING_OR_OUTPUT_BOUND_MISSING"
    if settings.intelligence_ocr_detail not in {"auto", "low", "high"}:
        return False, "OCR_DETAIL_INVALID"
    preflight_cost = settings.intelligence_ocr_preflight_max_cost_usd
    if preflight_cost <= 0 or not _caps_ready(preflight_cost):
        return False, "OCR_PREFLIGHT_FINITE_BUDGET_REQUIRED"
    if not settings.intelligence_ocr_retention_reference.strip() or not _retention_source_ids():
        return False, "OCR_SOURCE_RETENTION_ALLOWLIST_EMPTY"
    return True, ""


def _retention_task_allowlist() -> set[str]:
    return {
        value.strip()
        for value in settings.intelligence_enabled_contracts.split(",")
        if value.strip()
    }


def _validate_source(evidence: Evidence, observation: Observation, source: Source) -> None:
    if not source.enabled or not source.registry_enabled:
        raise ValueError("Source is not currently enabled")
    if source.id not in _retention_source_ids():
        raise ValueError("Source is outside the explicit OCR retention allowlist")
    if not settings.intelligence_ocr_retention_reference.strip():
        raise ValueError("OCR retention policy reference is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.content_hash):
        raise ValueError("Original PDF Evidence hash is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", observation.content_hash):
        raise ValueError("Parent Federal Register Observation hash is invalid")
    from gridlens.ingestion.adapters.govinfo_scan import _checked_url

    _url, document_id = _checked_url(evidence.url)
    if observation.external_id != document_id:
        raise ValueError("GovInfo PDF document ID does not match its parent FR record")


def scanned_pdf_ocr_availability(
    session: Session, *, need_id: UUID, evidence_id: UUID
) -> tuple[bool, str]:
    ready, reason = _ocr_configuration_ready()
    if not ready:
        return False, reason
    try:
        _need, _project, evidence, observation, source = _rows_for_evidence(
            session, need_id, evidence_id
        )
        _validate_source(evidence, observation, source)
    except ValueError as exc:
        return False, str(exc)
    return True, ""


def enqueue_scanned_pdf_ocr(session: Session, *, need_id: UUID, evidence_id: UUID) -> Job:
    ready, reason = scanned_pdf_ocr_availability(session, need_id=need_id, evidence_id=evidence_id)
    if not ready:
        raise ValueError(reason)
    need, project, evidence, observation, source = _rows_for_evidence(session, need_id, evidence_id)
    config = {
        "task_type": OCR_TASK,
        "schema_version": OCR_SCHEMA_VERSION,
        "need_id": str(need_id),
        "project_id": str(project.id),
        "evidence_id": str(evidence.id),
        "evidence_hash": evidence.content_hash,
        "observation_id": str(observation.id),
        "observation_hash": observation.content_hash,
        "document_id": observation.external_id,
        "source_id": source.id,
        "source_url": evidence.url,
        "retention_reference": settings.intelligence_ocr_retention_reference,
        "model": settings.intelligence_ocr_model,
        "detail": settings.intelligence_ocr_detail,
        "max_output_tokens": settings.intelligence_ocr_max_output_tokens,
        "input_usd_per_million": str(settings.intelligence_ocr_input_usd_per_million),
        "output_usd_per_million": str(settings.intelligence_ocr_output_usd_per_million),
        "preflight_max_cost_usd": str(settings.intelligence_ocr_preflight_max_cost_usd),
        "preflight_cost_bound_verified": settings.intelligence_ocr_preflight_cost_bound_verified,
        "preflight_cost_reference": settings.intelligence_ocr_preflight_cost_reference,
        "max_call_usd": str(settings.intelligence_ocr_max_call_usd),
    }
    identity = _digest(config)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{need_id}:{OCR_TASK}:{evidence_id}"},
    )
    for job in session.scalars(
        select(Job)
        .where(
            Job.kind == JOB_KIND, Job.target_id == need_id, Job.status.in_(["queued", "running"])
        )
        .order_by(Job.created_at.desc())
        .limit(20)
    ):
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (ValueError, TypeError):
            continue
        if checkpoint.get("request_digest") == identity:
            return job
    job = Job(
        source_id=source.id,
        kind=JOB_KIND,
        target_id=need.id,
        checkpoint=json.dumps(
            {
                "schema_version": OCR_SCHEMA_VERSION,
                "task_type": OCR_TASK,
                "evidence_id": str(evidence.id),
                "request_digest": identity,
                "config_digest": identity,
                "payload": config,
                "status": "queued",
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


def _ocr_call_for_evidence(
    session: Session, evidence: Evidence
) -> tuple[LogicalCall, dict[str, Any]]:
    provenance = evidence.provenance if isinstance(evidence.provenance, dict) else {}
    ocr_value = provenance.get("ocr")
    ocr = ocr_value if isinstance(ocr_value, dict) else {}
    try:
        call_id = UUID(ocr["logical_call_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("A completed OCR transcript is required for grounded follow-on") from exc
    call = session.get(LogicalCall, call_id)
    transcript = public_ocr_transcript(call.result_payload) if call else None
    if call is None or call.status != "COMPLETED" or transcript is None:
        raise ValueError("Retained OCR transcript reference is stale or invalid")
    if (
        ocr.get("original_document_hash") != evidence.content_hash
        or ocr.get("transcript_hash") != transcript.get("transcript_hash")
        or transcript.get("logical_call_id") != str(call_id)
        or transcript.get("evidence_id") != str(evidence.id)
        or transcript.get("original_document_hash") != evidence.content_hash
        or transcript.get("source_url") != evidence.url
    ):
        raise ValueError("Retained OCR transcript reference is stale or invalid")
    return call, transcript


def _build_followon_request(
    session: Session,
    checkpoint: dict[str, Any],
) -> tuple[dict[str, Any], LogicalCall, dict[str, Any]]:
    payload_ref = checkpoint["payload"]
    need_id = UUID(payload_ref["need_id"])
    evidence_id = UUID(payload_ref["evidence_id"])
    _need, project, evidence, observation, source = _rows_for_evidence(
        session, need_id, evidence_id
    )
    _validate_source(evidence, observation, source)
    capture = _load_capture(evidence)
    if capture is None:
        raise ValueError("Retained immutable PDF capture is unavailable")
    call, transcript = _ocr_call_for_evidence(session, evidence)
    if (
        str(call.id) != checkpoint.get("transcript_call_id")
        or transcript["transcript_hash"] != checkpoint.get("transcript_hash")
        or transcript["version"] != checkpoint.get("transcript_version")
        or transcript["page_count"] != capture["page_count"]
    ):
        raise ValueError("OCR transcript version changed before grounded follow-on")

    request_payload = _followon_request_payload(
        session,
        need_id,
        evidence,
        observation,
        source,
        call,
        transcript,
        checkpoint["question_id"],
    )
    if _digest(request_payload) != checkpoint.get("request_digest"):
        raise ValueError("Grounded follow-on source context changed")
    return request_payload, call, transcript


def _followon_request_payload(
    session: Session,
    need_id: UUID,
    evidence: Evidence,
    observation: Observation,
    source: Source,
    call: LogicalCall,
    transcript: dict[str, Any],
    question_id: str,
) -> dict[str, Any]:
    from gridlens.intelligence.intelligence_jobs import _request_payload, _retained_context

    need, project, project_source, retained_evidence = _retained_context(session, need_id)
    retained = next((row for row in retained_evidence if row["id"] == str(evidence.id)), None)
    if retained is None or retained["content_hash"] != evidence.content_hash:
        raise ValueError("PDF Evidence is no longer retained on this need")
    page_text = "\n".join(f"[Page {page['page']}]: {page['text']}" for page in transcript["pages"])
    transcript_evidence = {
        "id": str(evidence.id),
        "observation_id": str(observation.id),
        "content_hash": evidence.content_hash,
        "title": "",
        "abstract": page_text,
        "url": evidence.url,
        "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
        "publisher": source.publisher,
        "extraction_location": "page-indexed OCR transcript; OCR_UNVERIFIED",
        "event_date": evidence.event_date.isoformat() if evidence.event_date else None,
        "event_date_label": evidence.event_date_label,
        "source_id": source.id,
        "source_enabled": source.enabled,
        "source_registry_enabled": source.registry_enabled,
        "retrieval_method": source.retrieval_method,
    }
    request_payload = _request_payload(
        session,
        "GROUNDED_EXTRACTION",
        question_id,
        need,
        project,
        project_source,
        [transcript_evidence],
    )
    request_payload.update(
        task_type=OCR_FOLLOWON_TASK,
        schema_version="ocr-grounded-followon-v1",
        ocr_transcript_reference={
            "logical_call_id": str(call.id),
            "transcript_hash": transcript["transcript_hash"],
            "version": transcript["version"],
            "status": "OCR_UNVERIFIED",
        },
    )
    if (
        len(json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        > 45_000
    ):
        raise ValueError("OCR transcript exceeds the grounded follow-on context limit")
    return request_payload


def enqueue_ocr_grounded_followon(
    session: Session, *, need_id: UUID, evidence_id: UUID, question_id: str
) -> Job:
    ready, reason = _ocr_configuration_ready(OCR_FOLLOWON_TASK)
    if not ready:
        raise ValueError(reason)
    if not question_id:
        raise ValueError("A grounded question contract is required")
    need, project, evidence, observation, source = _rows_for_evidence(session, need_id, evidence_id)
    _validate_source(evidence, observation, source)
    if _load_capture(evidence) is None:
        raise ValueError("Immutable source capture is unavailable")
    call, transcript = _ocr_call_for_evidence(session, evidence)
    from gridlens.intelligence.question_contracts import QUESTION_CONTRACTS

    if question_id not in QUESTION_CONTRACTS:
        raise ValueError("Unsupported grounded question contract")
    config = {
        "task_type": OCR_TASK,
        "request_kind": OCR_FOLLOWON_TASK,
        "schema_version": OCR_SCHEMA_VERSION,
        "need_id": str(need_id),
        "project_id": str(project.id),
        "evidence_id": str(evidence.id),
        "evidence_hash": evidence.content_hash,
        "observation_id": str(observation.id),
        "observation_hash": observation.content_hash,
        "document_id": observation.external_id,
        "source_id": source.id,
        "source_url": evidence.url,
        "retention_reference": settings.intelligence_ocr_retention_reference,
        "model": settings.intelligence_ocr_model,
        "detail": settings.intelligence_ocr_detail,
        "max_output_tokens": settings.intelligence_ocr_max_output_tokens,
        "input_usd_per_million": str(settings.intelligence_ocr_input_usd_per_million),
        "output_usd_per_million": str(settings.intelligence_ocr_output_usd_per_million),
        "preflight_max_cost_usd": str(settings.intelligence_ocr_preflight_max_cost_usd),
        "preflight_cost_bound_verified": settings.intelligence_ocr_preflight_cost_bound_verified,
        "preflight_cost_reference": settings.intelligence_ocr_preflight_cost_reference,
        "max_call_usd": str(settings.intelligence_ocr_max_call_usd),
        "question_id": question_id,
        "transcript_call_id": str(call.id),
        "transcript_hash": transcript["transcript_hash"],
        "transcript_version": transcript["version"],
    }
    checkpoint = {
        "schema_version": OCR_SCHEMA_VERSION,
        "task_type": OCR_TASK,
        "request_kind": OCR_FOLLOWON_TASK,
        "question_id": question_id,
        "evidence_id": str(evidence_id),
        "transcript_call_id": str(call.id),
        "transcript_hash": transcript["transcript_hash"],
        "transcript_version": transcript["version"],
        "payload": config,
        "status": "queued",
        "config_digest": _digest(config),
    }
    request_payload = _followon_request_payload(
        session, need_id, evidence, observation, source, call, transcript, question_id
    )
    identity = _digest(request_payload)
    checkpoint["request_digest"] = identity
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{need_id}:{OCR_FOLLOWON_TASK}:{evidence_id}:{question_id}"},
    )
    for job in session.scalars(
        select(Job)
        .where(
            Job.kind == JOB_KIND, Job.target_id == need_id, Job.status.in_(["queued", "running"])
        )
        .order_by(Job.created_at.desc())
        .limit(20)
    ):
        try:
            old = json.loads(job.checkpoint or "{}")
        except (TypeError, ValueError):
            continue
        if old.get("request_digest") == identity:
            return job
    job = Job(
        source_id=source.id,
        kind=JOB_KIND,
        target_id=need.id,
        checkpoint=json.dumps(checkpoint, separators=(",", ":")),
    )
    session.add(job)
    session.flush()
    checkpoint["job_id"] = str(job.id)
    job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
    return job


def _finish_without_call(
    job_id: UUID, worker_id: str, fence_token: int, status: str, error: str
) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(status=status, error=error, completed_at=datetime.now(UTC).isoformat())
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
        job.status = "succeeded" if status in {"blocked", "stale", "unknown"} else "failed"
        job.lease_owner, job.lease_until = None, None
    return {"status": status, "error": error, "job_id": str(job_id)}


def _load_capture(evidence: Evidence) -> dict[str, Any] | None:
    provenance = evidence.provenance if isinstance(evidence.provenance, dict) else {}
    capture = provenance.get(CAPTURE_KEY)
    if not isinstance(capture, dict):
        return None
    required = {
        "document_id",
        "content_hash",
        "page_count",
        "scanned_pages",
        "data_base64",
        "source_url",
        "source",
        "retention_policy",
        "retention_reference",
        "retrieved_at",
    }
    if not required.issubset(capture):
        raise ValueError("Stored GovInfo capture is incomplete")
    from gridlens.ingestion.adapters.govinfo_scan import _checked_url

    try:
        _url, document_id = _checked_url(evidence.url)
    except ValueError as exc:
        raise ValueError("Evidence URL is outside the exact GovInfo PDF path") from exc
    if (
        capture.get("content_hash") != evidence.content_hash
        or capture.get("source_url") != evidence.url
        or capture.get("document_id") != document_id
        or capture.get("source") != "www.govinfo.gov"
        or capture.get("retention_policy") != "explicit_source_retention_allowlist"
        or capture.get("retention_reference") != settings.intelligence_ocr_retention_reference
        or not isinstance(capture.get("retrieved_at"), str)
        or type(capture.get("page_count")) is not int
        or not 1 <= capture["page_count"] <= MAX_PDF_PAGES
        or not isinstance(capture.get("scanned_pages"), list)
        or not capture["scanned_pages"]
        or any(
            type(page) is not int or not 1 <= page <= capture["page_count"]
            for page in capture["scanned_pages"]
        )
        or len(set(capture["scanned_pages"])) != len(capture["scanned_pages"])
        or not isinstance(capture.get("data_base64"), str)
    ):
        raise ValueError("Stored GovInfo capture does not match current source evidence")
    try:
        raw = base64.b64decode(capture["data_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Stored GovInfo capture encoding is invalid") from exc
    if (
        not raw.startswith(b"%PDF-")
        or len(raw) > MAX_PDF_BYTES
        or hashlib.sha256(raw).hexdigest() != evidence.content_hash
    ):
        raise ValueError("Stored GovInfo capture bytes do not match source evidence")
    return capture


def _current_job_input(session: Session, checkpoint: dict[str, Any]):
    payload = checkpoint["payload"]
    if not _configuration_matches(payload):
        raise ValueError("OCR provider configuration changed")
    need_id = UUID(payload["need_id"])
    evidence_id = UUID(payload["evidence_id"])
    need, project, evidence, observation, source = _rows_for_evidence(session, need_id, evidence_id)
    _validate_source(evidence, observation, source)
    expected_digest = (
        checkpoint.get("config_digest")
        if checkpoint.get("request_kind") == OCR_FOLLOWON_TASK
        else checkpoint.get("request_digest")
    )
    if checkpoint.get("request_kind") != OCR_FOLLOWON_TASK:
        expected_digest = checkpoint.get("config_digest") or expected_digest
    if (
        str(project.id) != payload["project_id"]
        or source.id != payload["source_id"]
        or str(observation.id) != payload["observation_id"]
        or observation.content_hash != payload["observation_hash"]
        or observation.external_id != payload["document_id"]
        or evidence.url != payload["source_url"]
        or evidence.content_hash != payload["evidence_hash"]
        or _digest(payload) != expected_digest
    ):
        raise ValueError("OCR source or request changed")
    return need, project, evidence, observation, source


def _configuration_matches(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("model") == settings.intelligence_ocr_model
        and payload.get("detail") == settings.intelligence_ocr_detail
        and payload.get("max_output_tokens") == settings.intelligence_ocr_max_output_tokens
        and payload.get("input_usd_per_million")
        == str(settings.intelligence_ocr_input_usd_per_million)
        and payload.get("output_usd_per_million")
        == str(settings.intelligence_ocr_output_usd_per_million)
        and payload.get("preflight_max_cost_usd")
        == str(settings.intelligence_ocr_preflight_max_cost_usd)
        and payload.get("preflight_cost_bound_verified")
        == settings.intelligence_ocr_preflight_cost_bound_verified
        and payload.get("preflight_cost_reference")
        == settings.intelligence_ocr_preflight_cost_reference
        and payload.get("max_call_usd") == str(settings.intelligence_ocr_max_call_usd)
        and payload.get("retention_reference") == settings.intelligence_ocr_retention_reference
    )


def _preflight_ready(cost: Decimal) -> bool:
    return bool(
        _ocr_configuration_ready()[0]
        and bool(settings.openai_api_key)
        and settings.intelligence_ocr_enabled
        and settings.intelligence_ocr_vision_enabled
        and settings.intelligence_ocr_preflight_enabled
        and settings.intelligence_ocr_preflight_max_cost_usd == cost
        and _caps_ready(cost)
    )


def _ocr_response_ready(model: str, detail: str, cost: Decimal) -> bool:
    return bool(
        _ocr_configuration_ready()[0]
        and bool(settings.openai_api_key)
        and settings.intelligence_ocr_enabled
        and settings.intelligence_ocr_vision_enabled
        and settings.intelligence_ocr_preflight_enabled
        and settings.intelligence_ocr_model == model
        and settings.intelligence_ocr_priced_model_id == model
        and settings.intelligence_ocr_pricing_verified
        and settings.intelligence_ocr_detail == detail
        and _caps_ready(cost)
    )


def _reserve_ledger_call(
    *,
    job_id: UUID,
    worker_id: str,
    fence_token: int,
    task_type: str,
    task_key: str,
    evidence_hash: str,
    context_digest: str,
    model: str,
    source_id: str,
    project_id: UUID,
    cost: Decimal,
):
    with SessionLocal() as session:
        return reserve_call(
            session,
            task_type=task_type,
            task_key=task_key,
            evidence_digest=evidence_hash,
            context_digest=context_digest,
            prompt_contract=OCR_SCHEMA_VERSION,
            provider="openai",
            model=model,
            policy_version=OCR_POLICY_VERSION,
            source_id=source_id,
            project_id=project_id,
            lease_authority="job",
            job_id=job_id,
            worker_id=worker_id,
            enabled=True,
            estimated_cost_usd=cost,
            max_cost_usd=cost,
            caps=_ledger_caps(),
            max_active=settings.intelligence_max_active_calls,
            fence_token=fence_token,
        )


def _ledger_caps() -> dict[str, dict[str, int | Decimal | float | str]]:
    return {
        scope: {
            "daily": getattr(settings, f"intelligence_{scope}_daily_calls"),
            "monthly": getattr(settings, f"intelligence_{scope}_monthly_calls"),
            "daily_usd": getattr(settings, f"intelligence_{scope}_daily_usd"),
            "monthly_usd": getattr(settings, f"intelligence_{scope}_monthly_usd"),
        }
        for scope in ("global", "provider", "model", "source", "project")
    }


def _set_job_checkpoint(
    job_id: UUID,
    worker_id: str,
    fence_token: int,
    values: dict[str, Any],
    *,
    job_status: str | None = None,
) -> None:
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(values)
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
        if job_status:
            job.status = job_status
            job.lease_owner, job.lease_until = None, None


def _publish_completed_result(
    *,
    job_id: UUID,
    worker_id: str,
    fence_token: int,
    call_id: UUID,
    preflight_call_id: UUID,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Publish only a transcript pointer to job/evidence; transcript stays in ledger."""
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        call = session.get(LogicalCall, call_id)
        if call is None or call.status != "COMPLETED" or call.result_payload != result:
            raise ValueError("Completed OCR logical-call result is unavailable")
        checkpoint = json.loads(job.checkpoint or "{}")
        _need, _project, evidence, _observation, _source = _current_job_input(session, checkpoint)
        capture = _load_capture(evidence)
        if (
            capture is None
            or evidence.content_hash != result.get("original_document_hash")
            or evidence.url != result.get("source_url")
            or result.get("evidence_id") != str(evidence.id)
            or result.get("logical_call_id") != str(call_id)
        ):
            raise ValueError("OCR result no longer matches immutable source evidence")
        provenance = dict(evidence.provenance or {})
        old_ocr_value = provenance.get("ocr")
        old_ocr = old_ocr_value if isinstance(old_ocr_value, dict) else {}
        provenance["ocr"] = {
            **old_ocr,
            "original_document_hash": evidence.content_hash,
            "method": "OpenAI Responses inline PDF input",
            "version": result["version"],
            "review_status": "unreviewed",
            "transcript_hash": result["transcript_hash"],
            "logical_call_id": str(call_id),
            "provider_response_id": result.get("provider_response_id"),
            "actual_model": result["actual_model"],
        }
        evidence.provenance = provenance
        # Large transcript text is retained exactly once in LogicalCall.result_payload.
        checkpoint.update(
            status="completed",
            result_status="OCR_UNVERIFIED",
            transcript_hash=result["transcript_hash"],
            evidence_ids=[str(evidence.id)],
            logical_call_id=str(call_id),
            preflight_call_id=str(preflight_call_id),
            usage=result.get("usage"),
            completed_at=datetime.now(UTC).isoformat(),
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
        job.status, job.lease_owner, job.lease_until = "succeeded", None, None
    return {"status": "completed", "result": result, "job_id": str(job_id)}


def _publish_followon_result(
    job_id: UUID,
    worker_id: str,
    fence_token: int,
    call_id: UUID,
    preflight_call_id: UUID,
    result: dict[str, Any],
) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        current, _ocr_call, transcript = _build_followon_request(session, checkpoint)
        call = session.get(LogicalCall, call_id)
        if (
            call is None
            or call.status != "COMPLETED"
            or call.result_payload != result
            or _digest(current) != checkpoint.get("request_digest")
            or transcript["transcript_hash"] != checkpoint.get("transcript_hash")
        ):
            raise ValueError("Grounded OCR result no longer matches its retained transcript")
        checkpoint.update(
            status="completed",
            result_status="OCR_UNVERIFIED",
            logical_call_id=str(call_id),
            preflight_call_id=str(preflight_call_id),
            usage=result.get("usage"),
            completed_at=datetime.now(UTC).isoformat(),
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
        job.status, job.lease_owner, job.lease_until = "succeeded", None, None
    return {"status": "completed", "result": result, "job_id": str(job_id)}


def _process_grounded_followon(job_id: UUID, worker_id: str, fence_token: int) -> dict[str, Any]:
    ready, reason = _ocr_configuration_ready(OCR_FOLLOWON_TASK)
    if not ready:
        return _finish_without_call(job_id, worker_id, fence_token, "blocked", reason)
    try:
        with SessionLocal() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            checkpoint = json.loads(job.checkpoint or "{}")
            request_payload, ocr_call, transcript = _build_followon_request(session, checkpoint)
            evidence_id = UUID(checkpoint["payload"]["evidence_id"])
            evidence_hash = checkpoint["payload"]["evidence_hash"]
            source_id = checkpoint["payload"]["source_id"]
            project_id = UUID(checkpoint["payload"]["project_id"])
            need_id = UUID(checkpoint["payload"]["need_id"])
            model = checkpoint["payload"]["model"]
            max_output = checkpoint["payload"]["max_output_tokens"]
            instructions = (
                GROUNDED_INSTRUCTIONS
                + " The text source is OCR_UNVERIFIED. Each quote must remain OCR_UNVERIFIED, "
                "require independent source verification, and must never be accepted or promoted."
            )
            request = openai_request_payload(
                model=model,
                instructions=instructions,
                input_payload=request_payload,
                max_output_tokens=max_output,
            )
            count_body = {
                key: request[key]
                for key in ("model", "input", "instructions", "text", "tools")
                if key in request
            }
            request_digest = _digest(request)
            count_body_digest = _digest(count_body)
            count_context_digest = _preflight_context_digest(model, count_body_digest)
    except (ValueError, KeyError, TypeError):
        return _finish_without_call(job_id, worker_id, fence_token, "stale", "FOLLOWON_INPUT_STALE")

    preflight_cost = settings.intelligence_ocr_preflight_max_cost_usd
    if not _preflight_ready(preflight_cost):
        return _finish_without_call(
            job_id, worker_id, fence_token, "blocked", "OCR_PREFLIGHT_POLICY_CHANGED"
        )
    count_reservation = _reserve_ledger_call(
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence_token,
        task_type="OCR_FOLLOWON_INPUT_PREFLIGHT",
        task_key=f"{need_id}:{evidence_id}:{checkpoint['question_id']}:input-count",
        evidence_hash=evidence_hash,
        context_digest=count_context_digest,
        model=model,
        source_id=source_id,
        project_id=project_id,
        cost=preflight_cost,
    )
    if not count_reservation.call_id or count_reservation.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            count_reservation.blocked_reason or "FOLLOWON_PREFLIGHT_RESERVATION_FAILED",
        )
    count_call_id = count_reservation.call_id
    if count_reservation.status == "SENT_OUTCOME_UNKNOWN":
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "PREFLIGHT_OUTCOME_UNKNOWN"
        )
    if count_reservation.status == "FAILED":
        return _finish_without_call(job_id, worker_id, fence_token, "failed", "PREFLIGHT_FAILED")
    if count_reservation.status == "COMPLETED":
        with SessionLocal() as session:
            count_call = session.get(LogicalCall, count_call_id)
            count_result = count_call.result_payload if count_call else None
        if (
            not isinstance(count_result, dict)
            or count_result.get("count_body_digest") != count_body_digest
            or count_result.get("count_context_digest") != count_context_digest
            or count_result.get("model") != model
            or count_result.get("contract_version") != OCR_PREFLIGHT_CONTRACT_VERSION
            or count_result.get("cost_bound_reference")
            != settings.intelligence_ocr_preflight_cost_reference
        ):
            return _finish_without_call(
                job_id, worker_id, fence_token, "stale", "PREFLIGHT_REQUEST_MISMATCH"
            )
        counted_tokens = count_result.get("counted_input_tokens")
        if type(counted_tokens) is not int or counted_tokens <= 0:
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", "PREFLIGHT_COUNT_INVALID"
            )
    else:
        with SessionLocal() as session:
            dispatch = mark_dispatched(
                session,
                count_call_id,
                fence_token=fence_token,
                enabled=_preflight_ready(preflight_cost),
            )
        if dispatch.status != "SENT_OUTCOME_UNKNOWN" or dispatch.blocked_reason:
            return _finish_without_call(
                job_id,
                worker_id,
                fence_token,
                "blocked",
                dispatch.blocked_reason or "PREFLIGHT_NOT_DISPATCHED",
            )
        try:
            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            counted_tokens = call_openai_input_token_count(
                api_key=key, model=model, response_request=request
            )
            count_result = {
                "purpose": "preflight_only",
                "counted_input_tokens": counted_tokens,
                "count_body_digest": count_body_digest,
                "count_context_digest": count_context_digest,
                "model": model,
                "contract_version": OCR_PREFLIGHT_CONTRACT_VERSION,
                "cost_bound_reference": settings.intelligence_ocr_preflight_cost_reference,
                "counted_input_tokens_are_billable_usage": False,
                "actual_cost_usd": None,
            }
            with SessionLocal() as session:
                complete_call(
                    session,
                    count_call_id,
                    fence_token=count_reservation.fence_token or fence_token,
                    result_digest=_digest(count_result),
                    result_payload=count_result,
                )
        except Exception as exc:
            if getattr(exc, "conclusive", False):
                with SessionLocal() as session:
                    fail_call(
                        session,
                        count_call_id,
                        fence_token=count_reservation.fence_token or fence_token,
                        blocked_reason=type(exc).__name__,
                        conclusive_response_ref="count:conclusive-response",
                    )
                return _finish_without_call(
                    job_id, worker_id, fence_token, "failed", type(exc).__name__
                )
            return _finish_without_call(
                job_id, worker_id, fence_token, "unknown", "PREFLIGHT_OUTCOME_UNKNOWN"
            )
        _set_job_checkpoint(
            job_id,
            worker_id,
            fence_token,
            {
                "preflight_call_id": str(count_call_id),
                "counted_input_tokens": counted_tokens,
                "count_body_digest": count_body_digest,
                "count_context_digest": count_context_digest,
            },
        )

    response_cost = (
        Decimal(counted_tokens) * settings.intelligence_ocr_input_usd_per_million
        + Decimal(max_output) * settings.intelligence_ocr_output_usd_per_million
    ) / Decimal(1_000_000)
    if (
        response_cost <= 0
        or response_cost > settings.intelligence_ocr_max_call_usd
        or not _caps_ready(response_cost)
        or not _ocr_configuration_ready(OCR_FOLLOWON_TASK)[0]
    ):
        return _finish_without_call(
            job_id, worker_id, fence_token, "blocked", "OCR_RESPONSE_FINITE_BUDGET_REQUIRED"
        )
    try:
        with SessionLocal() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            current_payload, current_ocr_call, current_transcript = _build_followon_request(
                session, json.loads(job.checkpoint or "{}")
            )
            current_request = openai_request_payload(
                model=model,
                instructions=instructions,
                input_payload=current_payload,
                max_output_tokens=max_output,
            )
            if (
                _digest(current_request) != request_digest
                or current_ocr_call.id != ocr_call.id
                or current_transcript["transcript_hash"] != transcript["transcript_hash"]
            ):
                raise ValueError("Count no longer matches current OCR transcript")
    except (ValueError, KeyError, TypeError):
        return _finish_without_call(job_id, worker_id, fence_token, "stale", "PREFLIGHT_STALE")

    reservation = _reserve_ledger_call(
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence_token,
        task_type=OCR_FOLLOWON_TASK,
        task_key=f"{need_id}:{evidence_id}:{checkpoint['question_id']}:grounded-ocr",
        evidence_hash=evidence_hash,
        context_digest=_digest(
            {
                "request": request_digest,
                "count": count_context_digest,
                "ocr_call_id": str(ocr_call.id),
                "transcript_hash": transcript["transcript_hash"],
            }
        ),
        model=model,
        source_id=source_id,
        project_id=project_id,
        cost=response_cost,
    )
    if not reservation.call_id or reservation.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            reservation.blocked_reason or "OCR_FOLLOWON_RESERVATION_FAILED",
        )
    call_id = reservation.call_id
    if reservation.status == "SENT_OUTCOME_UNKNOWN":
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "OCR_FOLLOWON_OUTCOME_UNKNOWN"
        )
    if reservation.status == "FAILED":
        return _finish_without_call(job_id, worker_id, fence_token, "failed", "OCR_FOLLOWON_FAILED")
    if reservation.status == "COMPLETED":
        with SessionLocal() as session:
            call = session.get(LogicalCall, call_id)
            result = call.result_payload if call else None
        if not isinstance(result, dict):
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", "OCR_FOLLOWON_RESULT_MISSING"
            )
        return _publish_followon_result(
            job_id, worker_id, fence_token, call_id, count_call_id, result
        )
    with SessionLocal() as session:
        dispatch = mark_dispatched(
            session,
            call_id,
            fence_token=reservation.fence_token or fence_token,
            enabled=_ocr_configuration_ready(OCR_FOLLOWON_TASK)[0] and _caps_ready(response_cost),
        )
    if dispatch.status != "SENT_OUTCOME_UNKNOWN" or dispatch.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            dispatch.blocked_reason or "OCR_FOLLOWON_NOT_DISPATCHED",
        )
    try:
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        response = call_openai_request(api_key=key, request=request)
        if response.get("model") != model:
            raise ValueError("Provider response model does not match the pinned model")
        parsed = validate_grounded_candidates(response["output"], request_payload["evidence"])
        for candidate in parsed["candidates"]:
            candidate["verification_status"] = "OCR_UNVERIFIED"
        result = {
            **parsed,
            "status": "OCR_UNVERIFIED",
            "authority": "ADVISORY_ONLY",
            "canonical_promotion": "PROHIBITED",
            "independent_source_check": "REQUIRED",
            "ocr_transcript_reference": {
                "logical_call_id": str(ocr_call.id),
                "transcript_hash": transcript["transcript_hash"],
                "version": transcript["version"],
            },
            "actual_model": response.get("model"),
            "provider_response_id": response.get("provider_response_id"),
            "usage": {
                "input_tokens": response.get("input_tokens"),
                "output_tokens": response.get("output_tokens"),
                "counted_input_tokens_are_billable_usage": False,
                "actual_cost_usd": None,
            },
        }
        if (
            len(json.dumps(result, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
            > 65_536
        ):
            raise ValueError("OCR grounded result exceeds the durable result limit")
        with SessionLocal() as session:
            complete_call(
                session,
                call_id,
                fence_token=reservation.fence_token or fence_token,
                input_tokens=response.get("input_tokens"),
                output_tokens=response.get("output_tokens"),
                result_digest=_digest(result),
                result_payload=result,
            )
    except Exception as exc:
        response_id = getattr(exc, "request_id", None)
        complete_response = locals().get("response", {}).get("provider_response_id")
        if response_id and (getattr(exc, "conclusive", False) or complete_response):
            with SessionLocal() as session:
                fail_call(
                    session,
                    call_id,
                    fence_token=reservation.fence_token or fence_token,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=f"response:{response_id}",
                )
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", type(exc).__name__
            )
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "OCR_FOLLOWON_OUTCOME_UNKNOWN"
        )
    return _publish_followon_result(job_id, worker_id, fence_token, call_id, count_call_id, result)


def process_scanned_pdf_ocr(job_id: UUID, worker_id: str, fence_token: int) -> dict[str, Any]:
    """Acquire immutable source bytes, exact-count input, then OCR with ledger fences."""
    with SessionLocal() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
    if checkpoint.get("request_kind") == OCR_FOLLOWON_TASK:
        return _process_grounded_followon(job_id, worker_id, fence_token)
    ready, reason = _ocr_configuration_ready()
    if not ready:
        return _finish_without_call(job_id, worker_id, fence_token, "blocked", reason)
    try:
        with SessionLocal() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            checkpoint = json.loads(job.checkpoint or "{}")
            if checkpoint.get("task_type") != OCR_TASK:
                return _finish_without_call(
                    job_id, worker_id, fence_token, "blocked", "TASK_TYPE_INVALID"
                )
            need, project, evidence, observation, source = _current_job_input(session, checkpoint)
            capture = _load_capture(evidence)
            capture_request = (evidence.url, evidence.content_hash, source.id)
    except (ValueError, KeyError, TypeError):
        return _finish_without_call(
            job_id, worker_id, fence_token, "stale", "SOURCE_OR_REQUEST_INVALID"
        )

    if capture is None:
        try:
            fetched = capture_govinfo_pdf(capture_request[0], capture_request[1])
        except Exception as exc:
            if "changed" in str(exc).casefold() or "hash" in str(exc).casefold():
                return _finish_without_call(
                    job_id, worker_id, fence_token, "stale", "SOURCE_BYTES_CHANGED"
                )
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", type(exc).__name__
            )
        try:
            with SessionLocal.begin() as session:
                job = assert_fence(session, job_id, worker_id, fence_token)
                checkpoint = json.loads(job.checkpoint or "{}")
                _need, _project, evidence, observation, source = _current_job_input(
                    session, checkpoint
                )
                if (
                    evidence.content_hash != fetched["content_hash"]
                    or evidence.url != fetched["source_url"]
                ):
                    raise ValueError("Source changed after capture")
                if not fetched["scanned_pages"]:
                    checkpoint.update(status="blocked", error="PDF_HAS_NO_SCANNED_PAGES")
                    job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                    job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                    return {
                        "status": "blocked",
                        "error": "PDF_HAS_NO_SCANNED_PAGES",
                        "job_id": str(job_id),
                    }
                evidence.provenance = merge_write_once_capture(
                    evidence.provenance,
                    fetched,
                    source_allowed=source.id in _retention_source_ids(),
                    retention_allowed=bool(settings.intelligence_ocr_retention_reference.strip()),
                    retention_reference=settings.intelligence_ocr_retention_reference,
                )
                checkpoint.update(
                    capture_committed=True, captured_document_hash=fetched["content_hash"]
                )
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
        except (ValueError, KeyError, TypeError):
            return _finish_without_call(
                job_id, worker_id, fence_token, "stale", "CAPTURE_COMMIT_STALE"
            )

    try:
        with SessionLocal.begin() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            checkpoint = json.loads(job.checkpoint or "{}")
            need, project, evidence, observation, source = _current_job_input(session, checkpoint)
            capture = _load_capture(evidence)
            if capture is None:
                raise ValueError("Immutable PDF capture is unavailable")
            if not capture["scanned_pages"]:
                raise ValueError("PDF has no scanned pages")
            from gridlens.ingestion.adapters.govinfo_scan import _checked_url

            _url, document_id = _checked_url(evidence.url)
            if capture["document_id"] != document_id:
                raise ValueError("Captured document ID does not match evidence URL")
            payload = checkpoint["payload"]
            model, detail = payload["model"], payload["detail"]
            request = ocr_request_payload(
                model=model,
                pdf_base64=capture["data_base64"],
                detail=detail,
                max_output_tokens=payload["max_output_tokens"],
            )
            response_request_digest = _digest(request)
            evidence_hash, evidence_id = evidence.content_hash, evidence.id
            source_id, project_id = source.id, project.id
            expected_pages = capture["page_count"]
            source_url = evidence.url
    except (ValueError, KeyError, TypeError, AttributeError):
        return _finish_without_call(
            job_id, worker_id, fence_token, "stale", "CAPTURE_OR_REQUEST_INVALID"
        )

    preflight_cost = settings.intelligence_ocr_preflight_max_cost_usd
    if not _preflight_ready(preflight_cost):
        return _finish_without_call(
            job_id, worker_id, fence_token, "blocked", "OCR_PREFLIGHT_POLICY_CHANGED"
        )
    count_body = {
        key: request[key]
        for key in ("model", "input", "instructions", "text", "tools")
        if key in request
    }
    count_body_digest = _digest(count_body)
    count_context_digest = _preflight_context_digest(model, count_body_digest)
    task_key = f"{payload['need_id']}:{evidence_id}:input-count"
    count_reservation = _reserve_ledger_call(
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence_token,
        task_type="OCR_INPUT_PREFLIGHT",
        task_key=task_key,
        evidence_hash=evidence_hash,
        context_digest=count_context_digest,
        model=model,
        source_id=source_id,
        project_id=project_id,
        cost=preflight_cost,
    )
    if not count_reservation.call_id or count_reservation.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            count_reservation.blocked_reason or "PREFLIGHT_RESERVATION_FAILED",
        )
    count_call_id = count_reservation.call_id
    if count_reservation.status == "SENT_OUTCOME_UNKNOWN":
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "PREFLIGHT_OUTCOME_UNKNOWN"
        )
    if count_reservation.status == "FAILED":
        return _finish_without_call(job_id, worker_id, fence_token, "failed", "PREFLIGHT_FAILED")
    if count_reservation.status == "COMPLETED":
        with SessionLocal() as session:
            count_call = session.get(LogicalCall, count_call_id)
            count_result = count_call.result_payload if count_call else None
        if (
            not isinstance(count_result, dict)
            or count_result.get("count_body_digest") != count_body_digest
            or count_result.get("count_context_digest") != count_context_digest
            or count_result.get("model") != model
            or count_result.get("contract_version") != OCR_PREFLIGHT_CONTRACT_VERSION
            or count_result.get("cost_bound_reference")
            != settings.intelligence_ocr_preflight_cost_reference
        ):
            return _finish_without_call(
                job_id, worker_id, fence_token, "stale", "PREFLIGHT_REQUEST_MISMATCH"
            )
        counted_tokens = count_result.get("counted_input_tokens")
        if type(counted_tokens) is not int or counted_tokens <= 0:
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", "PREFLIGHT_COUNT_INVALID"
            )
    else:
        dispatch_ok = _preflight_ready(preflight_cost)
        with SessionLocal() as session:
            dispatched = mark_dispatched(
                session, count_call_id, fence_token=fence_token, enabled=dispatch_ok
            )
        if dispatched.status != "SENT_OUTCOME_UNKNOWN" or dispatched.blocked_reason:
            return _finish_without_call(
                job_id,
                worker_id,
                fence_token,
                "blocked",
                dispatched.blocked_reason or "PREFLIGHT_NOT_DISPATCHED",
            )
        try:
            api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            counted_tokens = call_openai_input_token_count(
                api_key=api_key, model=model, response_request=request
            )
            count_result = {
                "purpose": "preflight_only",
                "counted_input_tokens": counted_tokens,
                "count_body_digest": count_body_digest,
                "count_context_digest": count_context_digest,
                "model": model,
                "contract_version": OCR_PREFLIGHT_CONTRACT_VERSION,
                "cost_bound_reference": settings.intelligence_ocr_preflight_cost_reference,
                "counted_input_tokens_are_billable_usage": False,
                "actual_cost_usd": None,
            }
            with SessionLocal() as session:
                complete_call(
                    session,
                    count_call_id,
                    fence_token=count_reservation.fence_token or fence_token,
                    result_digest=_digest(count_result),
                    result_payload=count_result,
                )
        except Exception as exc:
            response_id = getattr(exc, "request_id", None)
            if getattr(exc, "conclusive", False):
                with SessionLocal() as session:
                    fail_call(
                        session,
                        count_call_id,
                        fence_token=count_reservation.fence_token or fence_token,
                        blocked_reason=type(exc).__name__,
                        conclusive_response_ref=f"count:{response_id or 'conclusive-response'}",
                    )
                return _finish_without_call(
                    job_id, worker_id, fence_token, "failed", type(exc).__name__
                )
            return _finish_without_call(
                job_id, worker_id, fence_token, "unknown", "PREFLIGHT_OUTCOME_UNKNOWN"
            )
        _set_job_checkpoint(
            job_id,
            worker_id,
            fence_token,
            {
                "preflight_call_id": str(count_call_id),
                "counted_input_tokens": counted_tokens,
                "count_body_digest": count_body_digest,
                "count_context_digest": count_context_digest,
            },
        )

    try:
        with SessionLocal() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            current_checkpoint = json.loads(job.checkpoint or "{}")
            _need, _project, current_evidence, _observation, _source = _current_job_input(
                session, current_checkpoint
            )
            current_capture = _load_capture(current_evidence)
            if current_capture is None:
                raise ValueError("Current source capture is missing")
            current_request = ocr_request_payload(
                model=model,
                pdf_base64=current_capture["data_base64"],
                detail=detail,
                max_output_tokens=payload["max_output_tokens"],
            )
            current_count_body = {
                key: current_request[key]
                for key in ("model", "input", "instructions", "text", "tools")
                if key in current_request
            }
            if (
                _digest(current_request) != response_request_digest
                or _digest(current_count_body) != count_body_digest
            ):
                raise ValueError("Count no longer matches the exact OCR request")
    except (ValueError, KeyError, TypeError, AttributeError):
        return _finish_without_call(job_id, worker_id, fence_token, "stale", "PREFLIGHT_STALE")

    response_cost = (
        Decimal(counted_tokens) * settings.intelligence_ocr_input_usd_per_million
        + Decimal(settings.intelligence_ocr_max_output_tokens)
        * settings.intelligence_ocr_output_usd_per_million
    ) / Decimal(1_000_000)
    if (
        response_cost <= 0
        or response_cost > settings.intelligence_ocr_max_call_usd
        or not _caps_ready(response_cost)
    ):
        return _finish_without_call(
            job_id, worker_id, fence_token, "blocked", "OCR_RESPONSE_FINITE_BUDGET_REQUIRED"
        )
    if not _ocr_response_ready(model, detail, response_cost):
        return _finish_without_call(
            job_id, worker_id, fence_token, "blocked", "OCR_RESPONSE_POLICY_CHANGED"
        )
    response_reservation = _reserve_ledger_call(
        job_id=job_id,
        worker_id=worker_id,
        fence_token=fence_token,
        task_type=OCR_TASK,
        task_key=f"{need.id}:{evidence_id}:ocr",
        evidence_hash=evidence_hash,
        context_digest=_digest(
            {
                "request": response_request_digest,
                "count_call_id": str(count_call_id),
                "counted_input_tokens": counted_tokens,
                "preflight_context_digest": count_context_digest,
            }
        ),
        model=model,
        source_id=source_id,
        project_id=project_id,
        cost=response_cost,
    )
    if not response_reservation.call_id or response_reservation.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            response_reservation.blocked_reason or "OCR_RESERVATION_FAILED",
        )
    call_id = response_reservation.call_id
    if response_reservation.status == "COMPLETED":
        with SessionLocal() as session:
            call = session.get(LogicalCall, call_id)
            cached_result = call.result_payload if call else None
        if not isinstance(cached_result, dict):
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", "OCR_RESULT_MISSING"
            )
        return _publish_completed_result(
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence_token,
            call_id=call_id,
            preflight_call_id=count_call_id,
            result=cached_result,
        )
    if response_reservation.status == "SENT_OUTCOME_UNKNOWN":
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "OCR_OUTCOME_UNKNOWN"
        )
    if response_reservation.status == "FAILED":
        return _finish_without_call(job_id, worker_id, fence_token, "failed", "OCR_CALL_FAILED")

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        checkpoint.update(
            status="dispatching",
            logical_call_id=str(call_id),
            request_digest=response_request_digest,
            count_call_id=str(count_call_id),
        )
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
    try:
        with SessionLocal() as session:
            job = assert_fence(session, job_id, worker_id, fence_token)
            current_checkpoint = json.loads(job.checkpoint or "{}")
            _need, _project, current_evidence, _observation, _source = _current_job_input(
                session, current_checkpoint
            )
            current_capture = _load_capture(current_evidence)
            if current_capture is None:
                raise ValueError("Current source capture is missing")
            final_request = ocr_request_payload(
                model=model,
                pdf_base64=current_capture["data_base64"],
                detail=detail,
                max_output_tokens=payload["max_output_tokens"],
            )
            if _digest(final_request) != response_request_digest:
                raise ValueError("OCR request changed after count reservation")
    except (ValueError, KeyError, TypeError, AttributeError):
        with SessionLocal() as session:
            cancel_call(
                session,
                call_id,
                fence_token=response_reservation.fence_token or fence_token,
            )
        return _finish_without_call(job_id, worker_id, fence_token, "stale", "OCR_REQUEST_STALE")
    dispatch_ok = _ocr_response_ready(model, detail, response_cost)
    with SessionLocal() as session:
        dispatched = mark_dispatched(
            session,
            call_id,
            fence_token=response_reservation.fence_token or fence_token,
            enabled=dispatch_ok,
        )
    if dispatched.status != "SENT_OUTCOME_UNKNOWN" or dispatched.blocked_reason:
        return _finish_without_call(
            job_id,
            worker_id,
            fence_token,
            "blocked",
            dispatched.blocked_reason or "OCR_NOT_DISPATCHED",
        )

    response: dict[str, Any] = {}
    try:
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        response = call_openai_request(api_key=api_key, request=request)
        if response.get("model") != model:
            raise ValueError("Provider response model does not match the pinned model")
        result = validate_ocr_transcript(
            response["output"],
            expected_pages=expected_pages,
            evidence_id=evidence_id,
            original_document_hash=evidence_hash,
            source_url=source_url,
            logical_call_id=call_id,
            actual_model=response["model"],
            provider_response_id=response.get("provider_response_id"),
        )
        result["preflight_counted_input_tokens"] = counted_tokens
        result["usage"] = {
            "input_tokens": response.get("input_tokens"),
            "output_tokens": response.get("output_tokens"),
            "counted_input_tokens_are_billable_usage": False,
            "actual_cost_usd": None,
        }
        result_digest = _digest(result)
        with SessionLocal() as session:
            complete_call(
                session,
                call_id,
                fence_token=response_reservation.fence_token or fence_token,
                input_tokens=response.get("input_tokens"),
                output_tokens=response.get("output_tokens"),
                result_digest=result_digest,
                result_payload=result,
            )
    except Exception as exc:
        response_id = getattr(exc, "request_id", None)
        if response_id and (
            getattr(exc, "conclusive", False) or response.get("provider_response_id")
        ):
            with SessionLocal() as session:
                fail_call(
                    session,
                    call_id,
                    fence_token=response_reservation.fence_token or fence_token,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=f"response:{response_id}",
                )
            return _finish_without_call(
                job_id, worker_id, fence_token, "failed", type(exc).__name__
            )
        return _finish_without_call(
            job_id, worker_id, fence_token, "unknown", "OCR_OUTCOME_UNKNOWN"
        )

    try:
        return _publish_completed_result(
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence_token,
            call_id=call_id,
            preflight_call_id=count_call_id,
            result=result,
        )
    except (ValueError, KeyError, TypeError):
        return _finish_without_call(
            job_id, worker_id, fence_token, "stale", "SOURCE_CHANGED_AFTER_OCR"
        )
