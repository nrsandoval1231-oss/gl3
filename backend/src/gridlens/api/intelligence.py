"""Authenticated endpoints for bounded advisory intelligence and operations."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from gridlens.intelligence.commercial_assessment import digest as assessment_digest
from gridlens.intelligence.commercial_assessment import validate_assessment
from gridlens.intelligence.evidence_packages import validate_package
from gridlens.intelligence.intelligence_jobs import (
    COMMERCIAL_ASSESSMENT_TASK,
    GROUND_TASKS,
    _cost_bound,
    _current_payload,
    _digest,
    _enabled,
    _request_payload,
    _retained_context,
    enqueue_intelligence,
    intelligence_history,
)
from gridlens.intelligence.intelligence_operations import operations_view
from gridlens.intelligence.jev_contracts import CONTRACTS
from gridlens.intelligence.monitoring import upsert_watch, watch_view
from gridlens.intelligence.ocr_transcript import (
    public_ocr_grounded_result,
    public_ocr_transcript,
)
from gridlens.intelligence.question_contracts import QUESTION_CONTRACTS
from gridlens.intelligence.scanned_pdf_ocr import (
    OCR_FOLLOWON_TASK,
    OCR_TASK,
    _ocr_configuration_ready,
    enqueue_ocr_grounded_followon,
    enqueue_scanned_pdf_ocr,
)
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitCallNote,
    Source,
)
from gridlens.security import require_same_origin, require_session
from gridlens.settings import settings

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str = Field(min_length=1, max_length=80)
    question_id: str | None = Field(default=None, max_length=80)


class WatchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=100)
    allowed_urls: list[str] = Field(min_length=1, max_length=20)
    record_ids: list[str] = Field(default_factory=list, max_length=5)


class WatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[WatchSource] = Field(min_length=1, max_length=12)
    question_ids: list[str] | None = Field(default=None, max_length=12)
    enabled: bool = True
    reprocess_revision: str | None = Field(default=None, max_length=80)


class ReviewEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: UUID
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    source_url: str = Field(min_length=1, max_length=2000)


class CandidateReviewRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    value: str
    unit: str | None = None
    original_value: str | None = None
    original_unit: str | None = None
    precision: int | None = None
    date_precision: str | None = None
    evidence_id: UUID
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str
    section: str
    page: int | None = None
    span_start: int
    span_end: int
    publisher: str
    published_date: str | None = None
    speaker: str | None = None
    speaker_organization: str | None = None
    speaker_role: str | None = None
    support: str
    status: str
    source_url: str
    source_id: str | None = None


class OwnerFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: UUID
    job_id: UUID
    logical_call_id: UUID
    decision: Literal["SUPPORTED", "CONFLICT", "UNRESOLVED", "OTHER"]
    note: str = Field(min_length=1, max_length=5000)
    next_action: str = Field(default="", max_length=1000)
    follow_up: date | None = None
    candidate: CandidateReviewRef
    evidence_refs: list[ReviewEvidenceRef] = Field(min_length=1, max_length=12)


class CommercialAssessmentCitationOut(BaseModel):
    evidence_id: str
    evidence_hash: str
    source_url: str
    excerpt: str
    field: Literal["title", "abstract"]
    start: int
    end: int


class CommercialAssessmentFactSupportOut(BaseModel):
    fact_id: str
    field: str | None = None
    value: str | None = None
    label: str | None = None
    support_status: Literal["current", "saved", "unavailable", "stale"]
    unavailable_reason: str | None = None
    citation: CommercialAssessmentCitationOut | None = None


class CommercialAssessmentSupportOut(BaseModel):
    status: Literal["current", "saved", "unavailable", "stale"]
    reason: str | None = None
    document_coverage: str | None = None
    source_collection_status: str | None = None
    selected_facts: list[CommercialAssessmentFactSupportOut]


class IntelligenceHistoryOut(BaseModel):
    job_id: UUID
    task_type: str | None
    need_id: UUID
    status: str
    result: dict[str, Any] | None
    validation_outcome: str = "UNKNOWN"
    validation_reason: str | None = None
    provider_response_id: str | None = None
    result_status: str | None = None
    commercial_assessment_support: CommercialAssessmentSupportOut | None = None
    error: str | None
    evidence_ids: list[str]
    logical_call_id: UUID | None
    usage: dict[str, Any] | None
    reserved: bool
    uncertain: bool
    created_at: datetime | None
    completed_at: datetime | None


class IntelligenceTaskOut(BaseModel):
    task_type: str
    question_id: str | None
    eligible: bool
    reason: str | None
    provider: str | None
    pinned_model: str | None


class IntelligenceTasksOut(BaseModel):
    items: list[IntelligenceTaskOut]
    mode: str
    enabled: bool
    provider_configuration: dict[str, bool]
    note: str


class IntelligenceHistoryPageOut(BaseModel):
    items: list[IntelligenceHistoryOut]


class IntelligenceJobOut(IntelligenceHistoryOut):
    pass


class IntelligenceOperationsOut(BaseModel):
    window_days: int
    sources: list[dict[str, Any]]
    queue: dict[str, Any]
    providers: dict[str, Any]
    questions: dict[str, Any]
    material_changes_30d: int | None
    reviewed_signals: int | None
    independent_leads: int | None
    backup: str
    restore: str
    last_verified_restore_at: datetime | None
    last_reported_restore_at: datetime | None
    operational_receipt: dict[str, Any]
    commercial_review_receipt: dict[str, Any]
    owner_review_notes_30d: int


class IntelligenceWatchOut(BaseModel):
    item: dict[str, Any] | None = None


class OwnerFeedbackOut(BaseModel):
    id: UUID
    client_id: UUID
    metadata: dict[str, Any]
    note: str
    created_at: datetime | None


def _session_factory():
    # Follows the API module factory so integration tests can use isolated DBs.
    from gridlens.api import app as api_module

    return api_module.SessionLocal


def _job_status(job: Job, checkpoint: dict[str, Any]) -> str:
    status = checkpoint.get("status")
    if job.status == "running" and status == "queued":
        return "running"
    if status in {
        "queued",
        "running",
        "completed",
        "blocked",
        "unknown",
        "stale",
        "failed",
    }:
        return status
    if status == "cancelled":
        return "failed"
    if status == "dispatching":
        return "running"
    return {"succeeded": "completed", "failed": "failed"}.get(job.status, job.status)


def _job_view(job: Job) -> dict[str, Any]:
    try:
        checkpoint = json.loads(job.checkpoint or "{}")
    except (ValueError, TypeError):
        checkpoint = {}
    usage = checkpoint.get("usage")
    return {
        "job_id": str(job.id),
        "task_type": checkpoint.get("request_kind", checkpoint.get("task_type")),
        "need_id": str(job.target_id) if job.target_id else None,
        "status": _job_status(job, checkpoint),
        "result": checkpoint.get("result"),
        "validation_outcome": checkpoint.get("validation_outcome", "UNKNOWN"),
        "validation_reason": checkpoint.get("validation_reason"),
        "provider_response_id": checkpoint.get("provider_response_id"),
        "error": checkpoint.get("error")
        or ("CANCELLED_BEFORE_DISPATCH" if checkpoint.get("status") == "cancelled" else None),
        "evidence_ids": (
            [checkpoint["evidence_id"]]
            if checkpoint.get("task_type") == OCR_TASK and checkpoint.get("evidence_id")
            else [item.get("id") for item in checkpoint.get("payload", {}).get("evidence", [])]
        ),
        "logical_call_id": checkpoint.get("logical_call_id"),
        "usage": usage,
        "reserved": bool(checkpoint.get("logical_call_id")),
        "uncertain": checkpoint.get("status") == "unknown",
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": checkpoint.get("completed_at"),
    }


def _commercial_assessment_support(
    session, *, need_id: UUID, checkpoint: dict[str, Any], job_status: str
) -> dict[str, Any]:
    """Project selected M4 facts from the exact saved package, never raw package data."""
    result = checkpoint.get("result")
    payload = checkpoint.get("payload")
    package_payload = payload.get("package") if isinstance(payload, dict) else None
    empty = {
        "status": "unavailable",
        "reason": "ASSESSMENT_SUPPORT_UNAVAILABLE",
        "selected_facts": [],
    }
    if (
        job_status != "completed"
        or checkpoint.get("validation_outcome") != "VALIDATED"
        or not isinstance(result, dict)
        or not isinstance(payload, dict)
        or not isinstance(package_payload, dict)
    ):
        return empty
    try:
        project_id = UUID(str(payload["project"]["project_id"]))
        package_id = UUID(str(package_payload["id"]))
        current_need = payload["need"]
        if (
            not isinstance(current_need, dict)
            or str(current_need.get("need_id")) != str(need_id)
            or str(current_need.get("project_id")) != str(project_id)
        ):
            return {**empty, "reason": "CHECKPOINT_NEED_IDENTITY_MISMATCH"}
        checkpoint_references = package_payload.get("source_references")
        if not isinstance(checkpoint_references, list) or len(checkpoint_references) != 1:
            return {**empty, "reason": "CHECKPOINT_SOURCE_REFERENCE_INVALID"}
        checkpoint_reference = checkpoint_references[0]
        if not isinstance(checkpoint_reference, dict):
            return {**empty, "reason": "CHECKPOINT_SOURCE_REFERENCE_INVALID"}
        package_row = session.get(EvidencePackage, package_id)
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        if (
            package_row is None
            or need is None
            or project is None
            or need.project_id != project_id
            or package_row.need_id != need_id
            or package_row.project_id != project_id
            or package_row.processing_status != "COMPLETE_ADVISORY"
            or package_row.package_key != package_payload.get("package_key")
            or assessment_digest(package_row.payload) != package_payload.get("payload_digest")
            or package_row.evidence_id != UUID(str(checkpoint_reference["evidence_id"]))
            or package_row.observation_id != UUID(str(checkpoint_reference["observation_id"]))
            or package_row.evidence_hash != checkpoint_reference["evidence_hash"]
        ):
            return {**empty, "reason": "SAVED_PACKAGE_IDENTITY_MISMATCH"}
        package = package_row.payload
        identity = package.get("identity") if isinstance(package, dict) else None
        if (
            not isinstance(identity, dict)
            or identity.get("need_id") != str(need_id)
            or identity.get("project_id") != str(project_id)
        ):
            return {**empty, "reason": "SAVED_PACKAGE_IDENTITY_MISMATCH"}
        checkpoint_facts = package_payload.get("facts")
        if (
            package_payload.get("source_references") != package.get("source_references")
            or package_payload.get("document_coverage") != package.get("document_coverage")
            or package_payload.get("source_collection_status")
            != package.get("source_collection_status")
            or not isinstance(checkpoint_facts, list)
        ):
            return {**empty, "reason": "CHECKPOINT_PACKAGE_PROJECTION_MISMATCH"}
        expected_facts = {
            f"f-{assessment_digest(fact)[:16]}": fact
            for fact in package.get("facts", [])
            if isinstance(fact, dict)
        }
        for checkpoint_fact in checkpoint_facts:
            if not isinstance(checkpoint_fact, dict):
                return {**empty, "reason": "CHECKPOINT_PACKAGE_FACT_INVALID"}
            fact_id = checkpoint_fact.get("fact_id")
            source_fact = {key: value for key, value in checkpoint_fact.items() if key != "fact_id"}
            if not isinstance(fact_id, str) or expected_facts.get(fact_id) != source_fact:
                return {**empty, "reason": "CHECKPOINT_PACKAGE_FACT_MISMATCH"}
        package_for_validation = {
            **package_payload,
            "processing_status": package_payload.get("processing_status"),
            "project_id": str(project_id),
            "need_id": str(need_id),
        }
        validate_assessment(
            {
                key: result[key]
                for key in (
                    "disposition",
                    "reason_code",
                    "selected_fact_ids",
                    "research_dimensions",
                    "next_question_id",
                )
                if key in result
            },
            package=package_for_validation,
            need_id=str(need_id),
            project_id=str(project_id),
            current_need=current_need,
        )
        references = package.get("source_references")
        facts = package.get("facts")
        if not isinstance(references, list) or len(references) != 1 or not isinstance(facts, list):
            return {**empty, "reason": "SAVED_PACKAGE_CITATION_INVALID"}
        reference = references[0]
        evidence_id = UUID(str(reference["evidence_id"]))
        observation_id = UUID(str(reference["observation_id"]))
        evidence = session.get(Evidence, evidence_id)
        observation = session.get(Observation, observation_id)
        attached = session.scalar(
            select(NeedObservation.id).where(
                NeedObservation.need_id == need_id,
                NeedObservation.observation_id == observation_id,
            )
        )
        if (
            evidence is None
            or observation is None
            or not attached
            or evidence.observation_id != observation_id
            or evidence.content_hash != reference.get("evidence_hash")
            or evidence.url != reference.get("url")
            or observation.source_id != reference.get("source_id")
        ):
            return {**empty, "reason": "RETAINED_EVIDENCE_VERSION_UNAVAILABLE"}
        validate_package(
            package,
            evidence_fields={"title": evidence.title or "", "abstract": evidence.abstract or ""},
        )
        try:
            current = _digest(_current_payload(session, checkpoint, need_id)) == checkpoint.get(
                "request_digest"
            )
        except (ValueError, KeyError, TypeError):
            current = False
        support_status = "current" if current else "saved"
        fact_map = {
            fact.get("fact_id"): fact for fact in checkpoint_facts if isinstance(fact, dict)
        }
        selected_facts: list[dict[str, Any]] = []
        for fact_id in result.get("selected_fact_ids", []):
            fact = fact_map.get(fact_id) if isinstance(fact_id, str) else None
            if fact is None:
                selected_facts.append(
                    {
                        "fact_id": str(fact_id),
                        "support_status": "unavailable",
                        "unavailable_reason": "SELECTED_FACT_NOT_IN_SAVED_PACKAGE",
                    }
                )
                continue
            citation = fact.get("citation")
            span = citation.get("excerpt_location") if isinstance(citation, dict) else None
            field = span.get("field") if isinstance(span, dict) else None
            start = span.get("start") if isinstance(span, dict) else None
            end = span.get("end") if isinstance(span, dict) else None
            source_text = (
                evidence.title or ""
                if field == "title"
                else evidence.abstract or ""
                if field == "abstract"
                else None
            )
            parsed_url = urlparse(evidence.url or "")
            valid = (
                isinstance(citation, dict)
                and citation.get("evidence_id") == str(evidence.id)
                and citation.get("evidence_hash") == evidence.content_hash
                and type(start) is int
                and type(end) is int
                and 0 <= start < end
                and isinstance(source_text, str)
                and end <= len(source_text)
                and source_text[start:end] == fact.get("value")
                and parsed_url.scheme in {"http", "https"}
                and bool(parsed_url.netloc)
                and parsed_url.username is None
                and parsed_url.password is None
            )
            if not valid:
                selected_facts.append(
                    {
                        "fact_id": fact_id,
                        "support_status": "unavailable",
                        "unavailable_reason": "SAVED_CITATION_FAILED_VALIDATION",
                    }
                )
                continue
            assert isinstance(source_text, str) and type(start) is int and type(end) is int
            selected_facts.append(
                {
                    "fact_id": fact_id,
                    "field": fact.get("field") if isinstance(fact.get("field"), str) else "unknown",
                    "value": fact.get("value") if isinstance(fact.get("value"), str) else "",
                    "label": fact.get("label") if isinstance(fact.get("label"), str) else "Unknown",
                    "support_status": support_status,
                    "citation": {
                        "evidence_id": str(evidence.id),
                        "evidence_hash": evidence.content_hash,
                        "source_url": str(evidence.url),
                        "excerpt": source_text[start:end],
                        "field": field,
                        "start": start,
                        "end": end,
                    },
                }
            )
        return {
            "status": support_status,
            "reason": None,
            "document_coverage": package.get("document_coverage"),
            "source_collection_status": package.get("source_collection_status"),
            "selected_facts": selected_facts,
        }
    except (KeyError, TypeError, ValueError):
        return {**empty, "reason": "SAVED_PACKAGE_VALIDATION_FAILED"}


def _history_view(session, need_id: UUID, limit: int) -> list[dict[str, Any]]:
    items = intelligence_history(session, need_id, limit)
    job_ids = [UUID(item["job_id"]) for item in items]
    jobs = (
        {str(job.id): job for job in session.scalars(select(Job).where(Job.id.in_(job_ids))).all()}
        if job_ids
        else {}
    )
    checkpoints: dict[str, dict[str, Any]] = {}
    source_candidates: dict[str, dict[str, Any]] = {}
    for item in items:
        job_row = jobs.get(str(item["job_id"]))
        if job_row is not None:
            try:
                job_checkpoint = json.loads(job_row.checkpoint or "{}")
            except (ValueError, TypeError):
                job_checkpoint = {}
            item["status"] = _job_status(job_row, job_checkpoint)
            item["validation_outcome"] = job_checkpoint.get("validation_outcome", "UNKNOWN")
            item["validation_reason"] = job_checkpoint.get("validation_reason")
            item["provider_response_id"] = job_checkpoint.get("provider_response_id")
            item["task_type"] = job_checkpoint.get("request_kind", item.get("task_type"))
            if job_checkpoint.get("status") == "cancelled":
                item["error"] = "CANCELLED_BEFORE_DISPATCH"
            checkpoints[str(item["job_id"])] = job_checkpoint
    logical_call_ids: set[UUID] = set()
    for item in items:
        if item.get("task_type") in {OCR_TASK, OCR_FOLLOWON_TASK} and item.get("logical_call_id"):
            try:
                logical_call_ids.add(UUID(item["logical_call_id"]))
            except (TypeError, ValueError):
                pass
    logical_calls = (
        {
            str(call.id): call
            for call in session.scalars(
                select(LogicalCall).where(LogicalCall.id.in_(logical_call_ids))
            ).all()
        }
        if logical_call_ids
        else {}
    )
    for item in items:
        result = item.get("result")
        if item.get("task_type") == COMMERCIAL_ASSESSMENT_TASK:
            checkpoint = checkpoints.get(str(item["job_id"]), {})
            item["commercial_assessment_support"] = _commercial_assessment_support(
                session,
                need_id=need_id,
                checkpoint=checkpoint,
                job_status=item.get("status", "unknown"),
            )
        if item.get("task_type") == OCR_TASK and item.get("logical_call_id"):
            call = logical_calls.get(item["logical_call_id"])
            if call is not None and call.status == "COMPLETED":
                safe_result = public_ocr_transcript(call.result_payload)
                item["result"] = safe_result
                item["result_status"] = (
                    "OCR_UNVERIFIED" if safe_result is not None else "OCR_RESULT_UNAVAILABLE"
                )
                result = item["result"]
        if item.get("task_type") == OCR_FOLLOWON_TASK and item.get("logical_call_id"):
            call = logical_calls.get(item["logical_call_id"])
            safe_result = (
                public_ocr_grounded_result(call.result_payload)
                if call is not None and call.status == "COMPLETED"
                else None
            )
            item["result"] = safe_result
            item["result_status"] = (
                "OCR_UNVERIFIED" if safe_result is not None else "OCR_RESULT_UNAVAILABLE"
            )
            result = safe_result
            checkpoint = checkpoints.get(str(item["job_id"]), {})
            evidence_id = checkpoint.get("evidence_id")
            if evidence_id:
                item["evidence_ids"] = [evidence_id]
                evidence = session.get(Evidence, UUID(evidence_id))
                if evidence is not None:
                    source_candidates[str(evidence.id)] = {
                        "id": str(evidence.id),
                        "url": evidence.url,
                        "content_hash": evidence.content_hash,
                    }
        if item.get("task_type") == OCR_TASK:
            checkpoint = checkpoints.get(str(item["job_id"]), {})
            evidence_id = checkpoint.get("evidence_id")
            if evidence_id and evidence_id not in item.get("evidence_ids", []):
                item["evidence_ids"] = [evidence_id]
        if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
            continue
        checkpoint = checkpoints.get(str(item["job_id"]), {})
        source_candidates.update(
            {
                str(source.get("id")): source
                for source in checkpoint.get("payload", {}).get("evidence", [])
                if isinstance(source, dict) and source.get("id")
            }
        )
    evidence_ids = []
    for value in source_candidates:
        try:
            evidence_ids.append(UUID(value))
        except ValueError:
            continue
    source_ids = (
        {
            str(evidence_id): source_id
            for evidence_id, source_id in session.execute(
                select(Evidence.id, Source.id)
                .join(Observation, Observation.id == Evidence.observation_id)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .join(Source, Source.id == Observation.source_id)
                .where(Evidence.id.in_(evidence_ids), NeedObservation.need_id == need_id)
                .limit(1200)
            ).all()
        }
        if evidence_ids
        else {}
    )
    for item in items:
        result = item.get("result")
        if isinstance(result, dict) and isinstance(result.get("candidates"), list):
            checkpoint = checkpoints.get(str(item["job_id"]), {})
            sources = {
                str(source.get("id")): source
                for source in checkpoint.get("payload", {}).get("evidence", [])
                if isinstance(source, dict)
            }
            if checkpoint.get("request_kind") == OCR_FOLLOWON_TASK:
                source = source_candidates.get(checkpoint.get("evidence_id", ""))
                if source:
                    sources[str(source["id"])] = source
            for candidate in result["candidates"]:
                source = sources.get(str(candidate.get("evidence_id")))
                if source:
                    candidate["source_url"] = source.get("url")
                    candidate["source_id"] = source_ids.get(str(candidate.get("evidence_id")))
    return items


@router.get("/tasks", response_model=IntelligenceTasksOut, dependencies=[Depends(require_session)])
def intelligence_tasks():
    task_rows = []
    for task_type in sorted(CONTRACTS):
        enabled, provider, model, reason = _enabled(task_type)
        task_rows.append(
            {
                "task_type": task_type,
                "question_id": None,
                "eligible": enabled,
                "reason": reason or None,
                "provider": provider or None,
                "pinned_model": model or None,
            }
        )
    for question_id in sorted(QUESTION_CONTRACTS):
        enabled, provider, model, reason = _enabled("GROUNDED_DOSSIER", question_id)
        task_rows.append(
            {
                "task_type": "GROUNDED_DOSSIER",
                "question_id": question_id,
                "eligible": enabled,
                "reason": reason or None,
                "provider": provider or None,
                "pinned_model": model or None,
            }
        )
    for task_type in ("GROUNDED_EXTRACTION",):
        enabled, provider, model, reason = _enabled(task_type, "TEMP_LOAD_MW")
        task_rows.append(
            {
                "task_type": task_type,
                "question_id": "TEMP_LOAD_MW",
                "eligible": enabled,
                "reason": reason or None,
                "provider": provider or None,
                "pinned_model": model or None,
            }
        )
    ocr_enabled, ocr_reason = _ocr_configuration_ready()
    task_rows.append(
        {
            "task_type": OCR_TASK,
            "question_id": None,
            "eligible": ocr_enabled,
            "reason": ocr_reason or None,
            "provider": "openai" if ocr_enabled else None,
            "pinned_model": settings.intelligence_ocr_model if ocr_enabled else None,
        }
    )
    followon_enabled, followon_reason = _ocr_configuration_ready(OCR_FOLLOWON_TASK)
    task_rows.append(
        {
            "task_type": OCR_FOLLOWON_TASK,
            "question_id": None,
            "eligible": followon_enabled,
            "reason": followon_reason or None,
            "provider": "openai" if followon_enabled else None,
            "pinned_model": settings.intelligence_ocr_model if followon_enabled else None,
        }
    )
    return {
        "items": task_rows,
        "mode": settings.intelligence_mode,
        "enabled": bool(settings.intelligence_enabled),
        "provider_configuration": {
            "openai_key_present": bool(settings.openai_api_key),
            "typesafe_key_present": bool(settings.typesafe_api_key),
        },
        "note": "Configuration metadata only. GET does not call providers or verify credentials.",
    }


@router.get(
    "/operations", response_model=IntelligenceOperationsOut, dependencies=[Depends(require_session)]
)
def intelligence_operations():
    with _session_factory()() as session:
        return operations_view(session)


@router.get(
    "/needs/{need_id}/history",
    response_model=IntelligenceHistoryPageOut,
    dependencies=[Depends(require_session)],
)
def need_intelligence_history(need_id: UUID, limit: int = Query(default=20, ge=1, le=50)):
    with _session_factory()() as session:
        if session.get(PowerNeed, need_id) is None:
            raise HTTPException(404, "Power need not found")
        return {"items": _history_view(session, need_id, limit)}


@router.post(
    "/needs/{need_id}/jobs",
    response_model=IntelligenceJobOut,
    dependencies=[Depends(require_session)],
)
def request_intelligence_job(need_id: UUID, body: JobRequest, request: Request):
    require_same_origin(request)
    allowed = body.task_type in CONTRACTS or body.task_type in GROUND_TASKS
    if not allowed:
        raise HTTPException(422, "Unsupported intelligence task")
    if body.task_type in GROUND_TASKS:
        if body.question_id not in QUESTION_CONTRACTS:
            raise HTTPException(422, "A supported question contract is required")
    elif body.question_id is not None:
        raise HTTPException(422, "question_id is only valid for grounded tasks")
    eligible, _provider, _model, reason = _enabled(body.task_type, body.question_id)
    if not eligible:
        raise HTTPException(409, {"reason": reason or "TASK_DISABLED"})
    with _session_factory().begin() as session:
        need = session.get(PowerNeed, need_id)
        if need is None or not need.active:
            raise HTTPException(404, "Active power need not found")
        try:
            retained_need, project, source, evidence = _retained_context(session, need_id)
            payload = _request_payload(
                session,
                body.task_type,
                body.question_id,
                retained_need,
                project,
                source,
                evidence,
            )
            max_cost = _cost_bound(_provider, body.task_type, payload)
            if (
                max_cost <= 0
                or max_cost > settings.intelligence_max_call_usd
                or settings.intelligence_max_active_calls <= 0
            ):
                raise HTTPException(409, {"reason": "FINITE_BUDGET_REQUIRED"})
            for scope in ("global", "provider", "model", "source", "project"):
                if any(
                    getattr(settings, f"intelligence_{scope}_{limit}") <= 0
                    for limit in ("daily_calls", "monthly_calls", "daily_usd", "monthly_usd")
                ):
                    raise HTTPException(409, {"reason": "FINITE_BUDGET_REQUIRED"})
            job = enqueue_intelligence(
                session, need_id=need_id, task_type=body.task_type, question_id=body.question_id
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.flush()
        result = _job_view(job)
    return result


@router.post(
    "/needs/{need_id}/evidence/{evidence_id}/ocr",
    response_model=IntelligenceJobOut,
    dependencies=[Depends(require_session)],
)
def request_scanned_pdf_ocr(need_id: UUID, evidence_id: UUID, request: Request):
    """Queue OCR only for one already-linked source Evidence; never fetch in the API."""
    require_same_origin(request)
    with _session_factory().begin() as session:
        need = session.get(PowerNeed, need_id)
        if need is None or not need.active:
            raise HTTPException(404, "Active power need not found")
        try:
            job = enqueue_scanned_pdf_ocr(session, need_id=need_id, evidence_id=evidence_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.flush()
        return _job_view(job)


@router.post(
    "/needs/{need_id}/evidence/{evidence_id}/ocr-followon",
    response_model=IntelligenceJobOut,
    dependencies=[Depends(require_session)],
)
def request_ocr_grounded_followon(
    need_id: UUID, evidence_id: UUID, body: JobRequest, request: Request
):
    """Queue a separate OCR_UNVERIFIED candidate extraction over an existing transcript."""
    require_same_origin(request)
    if body.task_type != OCR_FOLLOWON_TASK or body.question_id not in QUESTION_CONTRACTS:
        raise HTTPException(422, "A supported OCR grounded question contract is required")
    with _session_factory().begin() as session:
        need = session.get(PowerNeed, need_id)
        if need is None or not need.active:
            raise HTTPException(404, "Active power need not found")
        try:
            job = enqueue_ocr_grounded_followon(
                session,
                need_id=need_id,
                evidence_id=evidence_id,
                question_id=body.question_id,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.flush()
        return _job_view(job)


@router.post(
    "/needs/{need_id}/jobs/{job_id}/cancel",
    response_model=IntelligenceJobOut,
    dependencies=[Depends(require_session)],
)
def cancel_intelligence_job(need_id: UUID, job_id: UUID, request: Request):
    require_same_origin(request)
    with _session_factory().begin() as session:
        job = session.scalar(
            select(Job)
            .where(Job.id == job_id, Job.kind == "intelligence_process", Job.target_id == need_id)
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Intelligence job not found")
        checkpoint = json.loads(job.checkpoint or "{}")
        if (
            checkpoint.get("logical_call_id")
            or checkpoint.get("status") != "queued"
            or job.status != "queued"
        ):
            raise HTTPException(409, "Only an undispatched queued request can be cancelled")
        checkpoint.update(status="cancelled", error=None)
        job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
        job.status = "failed"
        job.error = None
        session.flush()
        return _job_view(job)


@router.post(
    "/needs/{need_id}/jobs/{job_id}/retry",
    response_model=IntelligenceJobOut,
    dependencies=[Depends(require_session)],
)
def retry_intelligence_job(need_id: UUID, job_id: UUID, request: Request):
    require_same_origin(request)
    with _session_factory().begin() as session:
        job = session.scalar(
            select(Job)
            .where(Job.id == job_id, Job.kind == "intelligence_process", Job.target_id == need_id)
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Intelligence job not found")
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (TypeError, ValueError):
            checkpoint = {}
        status = _job_status(job, checkpoint)
        if status == "unknown" or checkpoint.get("logical_call_id"):
            raise HTTPException(409, "A reserved or uncertain provider call cannot be retried")
        if status != "failed":
            raise HTTPException(409, "Only a conclusive failed request can be retried")
        if (
            checkpoint.get("task_type") == OCR_TASK
            or checkpoint.get("request_kind") == OCR_FOLLOWON_TASK
        ):
            raise HTTPException(
                409,
                "Queue a new exact OCR request after reviewing the source and prior ledger outcome",
            )
        task_type = checkpoint.get("task_type")
        question_id = checkpoint.get("question_id")
        eligible, _provider, _model, reason = _enabled(task_type, question_id)
        if not eligible:
            raise HTTPException(409, {"reason": reason or "TASK_DISABLED"})
        try:
            retry_job = enqueue_intelligence(
                session, need_id=need_id, task_type=task_type, question_id=question_id
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.flush()
        return _job_view(retry_job)


@router.post(
    "/needs/{need_id}/watches",
    response_model=IntelligenceWatchOut,
    dependencies=[Depends(require_session)],
)
def set_need_watch(need_id: UUID, body: WatchRequest, request: Request):
    require_same_origin(request)
    with _session_factory().begin() as session:
        need = session.get(PowerNeed, need_id)
        if need is None:
            raise HTTPException(404, "Power need not found")
        try:
            upsert_watch(
                session,
                need_id,
                sources=[item.model_dump() for item in body.sources],
                question_ids=body.question_ids,
                enabled=body.enabled,
                reprocess_revision=body.reprocess_revision,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"item": watch_view(session, need_id)}


@router.get(
    "/needs/{need_id}/watches",
    response_model=IntelligenceWatchOut,
    dependencies=[Depends(require_session)],
)
def get_need_watch(need_id: UUID):
    with _session_factory()() as session:
        if session.get(PowerNeed, need_id) is None:
            raise HTTPException(404, "Power need not found")
        return {"item": watch_view(session, need_id)}


@router.post(
    "/needs/{need_id}/feedback",
    response_model=OwnerFeedbackOut,
    dependencies=[Depends(require_session)],
)
def save_owner_feedback(need_id: UUID, body: OwnerFeedback, request: Request):
    require_same_origin(request)
    with _session_factory().begin() as session:
        need = session.get(PowerNeed, need_id)
        if need is None:
            raise HTTPException(404, "Power need not found")
        job = session.scalar(
            select(Job)
            .where(
                Job.id == body.job_id, Job.kind == "intelligence_process", Job.target_id == need_id
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Candidate job does not belong to this need")
        try:
            checkpoint = json.loads(job.checkpoint or "{}")
        except (ValueError, TypeError):
            checkpoint = {}
        if (
            checkpoint.get("status") != "completed"
            or checkpoint.get("result_status") == "stale_context"
        ):
            raise HTTPException(409, "Only a current completed candidate can be reviewed")
        if checkpoint.get("request_kind") == OCR_FOLLOWON_TASK:
            raise HTTPException(
                409,
                "OCR_UNVERIFIED candidates require an independent source check before owner review",
            )
        if checkpoint.get("logical_call_id") != str(body.logical_call_id):
            raise HTTPException(409, "Logical call does not match the candidate job")
        logical_call = session.get(LogicalCall, body.logical_call_id)
        if logical_call is None or logical_call.job_id != job.id:
            raise HTTPException(409, "Logical call does not belong to the candidate job")
        retained = {
            str(row.get("id")): row
            for row in checkpoint.get("payload", {}).get("evidence", [])
            if isinstance(row, dict)
        }
        result = checkpoint.get("result")
        candidate_rows = result.get("candidates", []) if isinstance(result, dict) else []
        canonical_candidate = next(
            (
                item
                for item in candidate_rows
                if isinstance(item, dict)
                and str(item.get("evidence_id")) == str(body.candidate.evidence_id)
                and item.get("evidence_hash") == body.candidate.evidence_hash
                and item.get("value") == body.candidate.value
                and item.get("quote") == body.candidate.quote
                and item.get("section") == body.candidate.section
                and item.get("span_start") == body.candidate.span_start
                and item.get("span_end") == body.candidate.span_end
            ),
            None,
        )
        source_row = retained.get(str(body.candidate.evidence_id))
        if canonical_candidate is None or source_row is None:
            raise HTTPException(
                422, "Owner review must reference an exact saved grounded candidate"
            )
        cited_source_ids = {
            str(evidence_id): source_id
            for evidence_id, source_id in session.execute(
                select(Evidence.id, Source.id)
                .join(Observation, Observation.id == Evidence.observation_id)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .join(Source, Source.id == Observation.source_id)
                .where(
                    Evidence.id == body.candidate.evidence_id,
                    NeedObservation.need_id == need_id,
                )
                .limit(1)
            ).all()
        }
        canonical_snapshot = {
            **canonical_candidate,
            "source_url": source_row.get("url"),
            "source_id": cited_source_ids.get(str(body.candidate.evidence_id)),
        }
        for optional_field in (
            "original_value",
            "original_unit",
            "precision",
            "date_precision",
            "speaker",
            "speaker_organization",
            "speaker_role",
        ):
            canonical_snapshot.setdefault(optional_field, None)
        if body.candidate.model_dump(mode="json") != canonical_snapshot:
            raise HTTPException(
                422, "Candidate details changed; reload the saved evidence candidate"
            )
        cited: list[dict[str, Any]] = []
        for ref in body.evidence_refs:
            row = retained.get(str(ref.evidence_id))
            if (
                not row
                or row.get("content_hash") != ref.content_hash
                or row.get("url") != ref.source_url
            ):
                raise HTTPException(
                    422, "Feedback evidence must exactly match the candidate's retained citations"
                )
            cited.append(
                {
                    "evidence_id": str(ref.evidence_id),
                    "content_hash": ref.content_hash,
                    "source_url": ref.source_url,
                    "publisher": row.get("publisher"),
                }
            )
        if not any(item["evidence_id"] == str(body.candidate.evidence_id) for item in cited):
            raise HTTPException(422, "Review metadata must cite the candidate's source evidence")
        project = session.get(Project, need.project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        pursuit = session.scalar(
            select(Pursuit)
            .where(Pursuit.identity_key == "commercial-need:" + str(need_id))
            .with_for_update()
        )
        if pursuit is None:
            raise HTTPException(
                409, "Save the commercial pursuit workspace before recording a review note"
            )
        prior_note: PursuitCallNote | None = session.scalar(
            select(PursuitCallNote)
            .where(
                PursuitCallNote.pursuit_id == pursuit.id,
                PursuitCallNote.client_id == body.client_id,
            )
            .with_for_update()
        )
        metadata = {
            "version": "intelligence-review-v1",
            "need_id": str(need_id),
            "job_id": str(job.id),
            "logical_call_id": str(body.logical_call_id),
            "decision": body.decision,
            "candidate": canonical_snapshot,
            "evidence_refs": cited,
            "review_state": "pending_independent_review",
        }
        if prior_note:
            if (
                prior_note.intelligence_review != metadata
                or prior_note.note != body.note
                or prior_note.next_action != body.next_action
                or (prior_note.follow_up.isoformat() if prior_note.follow_up else None)
                != (body.follow_up.isoformat() if body.follow_up else None)
            ):
                raise HTTPException(
                    409, "This feedback id was already saved with different content"
                )
            return {
                "id": str(prior_note.id),
                "client_id": str(prior_note.client_id),
                "metadata": prior_note.intelligence_review,
                "note": prior_note.note,
                "created_at": prior_note.created_at,
            }
        note_row = PursuitCallNote(
            pursuit_id=pursuit.id,
            client_id=body.client_id,
            owner="Nick Sandoval",
            note=body.note,
            outcome="Needs follow-up",
            next_action=body.next_action,
            follow_up=body.follow_up,
            intelligence_review=metadata,
        )
        session.add(note_row)
        session.flush()
        return {
            "id": str(note_row.id),
            "client_id": str(note_row.client_id),
            "metadata": note_row.intelligence_review,
            "note": note_row.note,
            "created_at": note_row.created_at,
        }
