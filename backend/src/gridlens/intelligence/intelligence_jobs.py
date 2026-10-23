"""Fenced shared-ledger queue for bounded advisory intelligence work."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from gridlens.integrations.intelligence_provider import (
    GROUNDED_INSTRUCTIONS,
    call_openai,
    call_openai_request,
    call_typesafe,
    commercial_assessment_request_payload,
    openai_request_payload,
)
from gridlens.integrations.logical_calls import (
    MAX_ACTUAL_USD,
    MAX_RESULT_BYTES,
    cancel_call,
    complete_call,
    fail_call,
    mark_dispatched,
    quarantine_call,
    reserve_call,
)
from gridlens.intelligence.commercial_assessment import (
    ASSESSMENT_SCHEMA,
    validate_assessment,
)
from gridlens.intelligence.grounded_candidates import validate_grounded_candidates
from gridlens.intelligence.jev_contracts import CONTRACTS, validate_answer
from gridlens.intelligence.jev_task_context import build_task_context
from gridlens.intelligence.question_contracts import QUESTION_CONTRACTS, question_contract
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    Evidence,
    EvidencePackage,
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
from gridlens.persistence.watch_models import ProjectMonitorWatch
from gridlens.settings import settings

JOB_KIND = "intelligence_process"
POLICY_VERSION = "bounded-intelligence-v1"
TYPESAFE_BILLING_CONTRACT_ID = "systemone-v1"
TYPESAFE_BILLING_POLICY_ID = "typesafe-total-input-ceiling-v1"
TYPESAFE_UNLIMITED_BILLING_POLICY_ID = "typesafe-reported-input-usage-v1"
TYPESAFE_SIGNAL_ESTIMATE_POLICY_ID = "typesafe-signal-estimate-v1"
TYPESAFE_SIGNAL_ESTIMATE_TASK = "SIGNAL_ADJUDICATION"
TYPESAFE_SIGNAL_ESTIMATE_MODEL = "jev-1.13.0"
TYPESAFE_SIGNAL_REQUEST_MAX_BYTES = 16_384
TYPESAFE_SIGNAL_REPORTED_INPUT_REVIEW_TOKENS = 64_000
SCHEMA_VERSION = "intelligence-request-v1"
MAX_CONTEXT_BYTES = 45_000
MAX_EVIDENCE_DOCUMENTS = 24
MAX_PROVIDER_RESPONSE_BYTES = 65_536
GROUND_TASKS = {"GROUNDED_EXTRACTION", "GROUNDED_DOSSIER"}
LEGACY_BRIEF_OUTPUT_TOKENS = 700
POWER_NEED_TITLE_OUTPUT_TOKENS = 240
LEGACY_TASKS = {
    "POWER_NEED_BRIEF",
    "POWER_NEED_TITLE",
    "SIGNAL_ADJUDICATION",
    "EVIDENCE_SHADOW",
    "JEV_HEALTH_PROBE",
    "FIRECRAWL_SEARCH_V2",
    "FIRECRAWL_SCRAPE_V2",
}
COMMERCIAL_ASSESSMENT_TASK = "COMMERCIAL_ASSESSMENT_V1"
COMMERCIAL_ASSESSMENT_OUTPUT_TOKENS = 6000


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
        .limit(MAX_EVIDENCE_DOCUMENTS)
    ).all()
    evidence = []
    for ev, observation, evidence_source, interpretation in rows:
        actual_source = evidence_source.enabled and evidence_source.registry_enabled
        assessment = interpretation.assessment if interpretation is not None else None
        accepted_supplement = bool(
            not evidence_source.enabled
            and not evidence_source.registry_enabled
            and interpretation is not None
            and interpretation.status == "accepted"
            and interpretation.content_hash == observation.content_hash
            and assessment
            and assessment.get("admission_status") == "project_research_supplement"
            and assessment.get("semantic_hash") == observation.content_hash
            and assessment.get("evidence_hash") == ev.content_hash
            and assessment.get("target_need_id") == str(need.id)
            and assessment.get("project_identity_key") == project.identity_key
        )
        if not (actual_source or accepted_supplement):
            continue
        provenance = ev.provenance if isinstance(ev.provenance, dict) else {}
        ocr = provenance.get("ocr") if isinstance(provenance.get("ocr"), dict) else None
        scanned = bool(
            provenance.get("scan_detected")
            or provenance.get("document_type") == "scanned"
            or ("ocr" in ev.extraction_location.casefold())
        )
        valid_ocr = bool(
            ocr
            and ocr.get("original_document_hash") == ev.content_hash
            and isinstance(ocr.get("method"), str)
            and ocr.get("method")
            and isinstance(ocr.get("version"), str)
            and ocr.get("version")
            and ocr.get("review_status") == "unreviewed"
            and re.fullmatch(r"[0-9a-f]{64}", str(ocr.get("transcript_hash", "")))
        )
        retained_abstract = ev.abstract or ""
        omitted_text_start: int | None = None
        if scanned and not valid_ocr:
            retained_abstract = ""
        else:
            # RRC keeps opaque source bytes in the immutable Evidence abstract
            # for audit, but binary/base64 tails are not readable passages.
            marker = "\nOpaque source bytes (base64; not interpreted): "
            opaque_tail = retained_abstract.find(marker)
            if opaque_tail >= 0:
                omitted_text_start = opaque_tail
                retained_abstract = retained_abstract[:opaque_tail]
        evidence.append(
            {
                "id": str(ev.id),
                "observation_id": str(observation.id),
                "content_hash": ev.content_hash,
                "title": ev.title,
                "abstract": retained_abstract,
                "url": ev.url,
                "published_at": ev.published_at.isoformat() if ev.published_at else None,
                "publisher": evidence_source.publisher,
                "extraction_location": ev.extraction_location,
                "event_date": ev.event_date.isoformat() if ev.event_date else None,
                "event_date_label": ev.event_date_label,
                "ocr_provenance": ocr if valid_ocr else None,
                "text_truncated": omitted_text_start is not None,
                "omitted_text_start": omitted_text_start,
                "omitted_text_end": len(ev.abstract or "")
                if omitted_text_start is not None
                else None,
                "retained_text_status": (
                    "partial_retained_excerpt"
                    if omitted_text_start is not None
                    else "retained_ocr_unreviewed"
                    if valid_ocr
                    else "unavailable_ocr"
                    if scanned
                    else "retained_excerpt"
                ),
                "source_id": evidence_source.id,
                "source_enabled": evidence_source.enabled,
                "source_registry_enabled": evidence_source.registry_enabled,
                "retrieval_method": evidence_source.retrieval_method,
            }
        )
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
    from gridlens.intelligence.project_state import current_research_state

    accepted_source_claims = current_research_state(session, project.id, need.id, project=project)
    need._intelligence_accepted_facts = accepted_facts  # type: ignore[attr-defined]
    need._intelligence_accepted_source_claims = accepted_source_claims  # type: ignore[attr-defined]
    return need, project, source, evidence


def _request_payload(
    session: Session,
    task_type: str,
    question_id: str | None,
    need: PowerNeed,
    project: Project,
    source: Source,
    evidence: list[dict[str, Any]],
    package_id: UUID | None = None,
) -> dict[str, Any]:
    current_state = {
        "need_id": str(need.id),
        "need_updated_at": need.updated_at.isoformat() if need.updated_at else None,
        "admission_basis": need.admission_basis,
        "accepted_operator_facts": getattr(need, "_intelligence_accepted_facts", []),
        "project_identity_key": project.identity_key,
        "project_identity_facts": project.identity_facts,
    }
    if task_type in GROUND_TASKS:
        from gridlens.domain.project_research import VERSION as PROJECT_RESEARCH_VERSION

        current_state["accepted_source_claims"] = getattr(
            need, "_intelligence_accepted_source_claims", {}
        )
        current_state["project_research_policy_version"] = PROJECT_RESEARCH_VERSION
        current_state["grounding_policy_version"] = "retained-grounding-v2"
    state_version_digest = _digest(current_state)
    if task_type == COMMERCIAL_ASSESSMENT_TASK:
        if package_id is None:
            raise ValueError("Exact M3 package ID is required")
        from gridlens.intelligence.evidence_packages import validate_package

        package_row = session.get(EvidencePackage, package_id)
        if package_row is None or package_row.processing_status != "COMPLETE_ADVISORY":
            raise ValueError("Package is not COMPLETE_ADVISORY")
        package = package_row.payload
        if package_row.project_id != project.id or package_row.need_id != need.id:
            raise ValueError("Package project/need identity mismatch")
        if package_row.processing_status != package.get("processing_status"):
            raise ValueError("Package row and payload status mismatch")
        if package.get("package_key") != package_row.package_key:
            raise ValueError("Package row and payload key mismatch")
        evidence_by_id = {item["id"]: item for item in evidence}
        references = package.get("source_references")
        if not isinstance(references, list) or len(references) != 1:
            raise ValueError("Package evidence references are malformed")
        reference = references[0]
        retained = evidence_by_id.get(reference.get("evidence_id"))
        if retained is None or retained.get("content_hash") != reference.get("evidence_hash"):
            raise ValueError("Package evidence is no longer current")
        evidence_id = UUID(reference["evidence_id"])
        observation_id = UUID(reference["observation_id"])
        if retained.get("observation_id") != str(observation_id):
            raise ValueError("Package evidence observation identity is stale")
        ev = session.get(Evidence, evidence_id)
        if ev is None or ev.content_hash != reference["evidence_hash"]:
            raise ValueError("Package evidence hash is stale")
        observation = session.get(Observation, observation_id)
        if (
            ev.observation_id != observation_id
            or observation is None
            or observation.source_id != reference.get("source_id")
            or observation.content_hash != ev.content_hash
            or package_row.evidence_id != ev.id
            or package_row.observation_id != observation.id
            or package_row.evidence_hash != ev.content_hash
        ):
            raise ValueError("Package observation version or evidence relation is stale")
        validate_package(
            package, evidence_fields={"title": ev.title or "", "abstract": ev.abstract or ""}
        )
        from gridlens.intelligence.commercial_assessment import digest as m4_digest

        facts = []
        for fact in package.get("facts", []):
            citation = fact.get("citation", {})
            span = citation.get("excerpt_location", {})
            field_name = span.get("field")
            source_text = ev.title or "" if field_name == "title" else ev.abstract or ""
            start, end = span.get("start"), span.get("end")
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end < start
                or end > len(source_text)
            ):
                raise ValueError("Package citation span is stale")
            if source_text[start:end] != fact.get("value"):
                raise ValueError("Package citation text mismatch")
            facts.append({**fact, "fact_id": f"f-{m4_digest(fact)[:16]}"})
        if project.region_status != "ELIGIBLE":
            raise ValueError("Project region is not eligible")
        return {
            "schema_version": "commercial-assessment-v1",
            "task_type": task_type,
            "need": {
                "need_id": str(need.id),
                "project_id": str(project.id),
                "updated_at": need.updated_at.isoformat() if need.updated_at else None,
                "activity": need.activity_key,
                "required_mw": need.required_mw,
                "start_window": need.start_window,
                "duration": need.duration,
                "supply": need.supply,
                "accepted_facts": getattr(need, "_intelligence_accepted_facts", []),
            },
            "project": {
                "project_id": str(project.id),
                "identity_key": project.identity_key,
                "identity_facts": project.identity_facts,
                "region_status": project.region_status,
                "region_state": project.region_state,
                "region_provenance": project.region_provenance,
            },
            "package": {
                "id": str(package_row.id),
                "package_key": package_row.package_key,
                "schema_version": package_row.schema_version,
                "processing_status": package_row.processing_status,
                "payload_digest": m4_digest(package),
                "document_coverage": package.get("document_coverage"),
                "source_collection_status": package.get("source_collection_status"),
                "facts": facts,
                "missing_fields": package.get("missing_fields"),
                "source_references": references,
                "source_id": source.id,
                "source_health": source.health,
                "source_enabled": source.enabled,
                "source_registry_enabled": source.registry_enabled,
            },
        }
    if task_type in CONTRACTS:
        contract = CONTRACTS[task_type]
        context = build_task_context(session, task_type, need, project, source, evidence)
        if task_type in {"MATCH_ADVISORY_V1", "BUYER_ROLE_HINT_V1"}:
            candidates = (
                context["deterministic_candidates"]
                if task_type == "MATCH_ADVISORY_V1"
                else context["party_candidates"]
            )
            key = "candidate_id" if task_type == "MATCH_ADVISORY_V1" else "party_id"
            questions = {
                str(candidate[key]): {
                    "type": "choice",
                    "instructions": (
                        "For this exact candidate UUID, select SAME, DIFFERENT, or UNRESOLVED. "
                        "Do not compare it with another candidate or create/merge identity."
                    )
                    if task_type == "MATCH_ADVISORY_V1"
                    else (
                        "For this exact named party UUID, classify only the role supported by "
                        "its listed citations. Do not substitute another party or treat an "
                        "applicant as buyer."
                    ),
                    "criteria": {choice: choice for choice in contract.choices},
                }
                for candidate in candidates
            }
        else:
            questions = {
                "answer": {
                    "type": "choice",
                    "instructions": context["contract_instructions"],
                    "criteria": {choice: choice for choice in contract.choices},
                }
            }
        request: dict[str, Any] = {
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
                "state_version_digest": "",
            },
            "task_context": context,
            "evidence": evidence,
            "questions": questions,
        }
        request["need"]["state_version_digest"] = _digest(request)
        return request
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
                "accepted_source_claims": getattr(need, "_intelligence_accepted_source_claims", {}),
                "project_identity_key": project.identity_key,
                "project_identity_facts": project.identity_facts,
                "state_version_digest": state_version_digest,
            },
            "evidence": evidence,
        }
    raise ValueError("Unknown intelligence task type")


def _watch_context(session: Session, need_id: UUID, origin: str) -> dict[str, Any] | None:
    if origin != "monitoring":
        return None
    watch = session.scalar(
        select(ProjectMonitorWatch).where(ProjectMonitorWatch.need_id == need_id)
    )
    if watch is None:
        return None
    return {"version": watch.version, "reprocess_revision": watch.reprocess_revision}


def _bound_grounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain exact UTF-8 spans under the request cap and mark clipped excerpts."""
    if payload.get("task_type") not in GROUND_TASKS:
        return payload
    result = json.loads(json.dumps(payload, ensure_ascii=True))
    result["context_truncation"] = {"partial": False, "text_bytes_removed": 0}

    def encoded() -> bytes:
        return json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )

    if len(encoded()) <= MAX_CONTEXT_BYTES:
        return result
    # Clip only a suffix of retained abstract text. Its original prefix offsets
    # remain exact, and the response receives explicit partial-context metadata.
    for evidence in reversed(result.get("evidence", [])):
        text = evidence.get("abstract", "")
        while text and len(encoded()) > MAX_CONTEXT_BYTES:
            excess = max(1, len(encoded()) - MAX_CONTEXT_BYTES)
            remove_chars = min(len(text), excess)
            before_bytes = len(text.encode("utf-8"))
            text = text[:-remove_chars]
            evidence["abstract"] = text
            evidence["text_truncated"] = True
            evidence["retained_text_status"] = "partial_retained_excerpt"
            result["context_truncation"]["partial"] = True
            result["context_truncation"]["text_bytes_removed"] += before_bytes - len(
                text.encode("utf-8")
            )
    if len(encoded()) > MAX_CONTEXT_BYTES:
        raise ValueError("Grounded metadata exceeds context size limit")
    return result


def _current_payload(session: Session, checkpoint: dict[str, Any], need_id: UUID) -> dict[str, Any]:
    task_type = checkpoint["task_type"]
    need, project, source, evidence = _retained_context(session, need_id)
    payload = _request_payload(
        session,
        task_type,
        checkpoint.get("question_id"),
        need,
        project,
        source,
        evidence,
        UUID(checkpoint["package_id"]) if checkpoint.get("package_id") else None,
    )
    payload = _bound_grounded_payload(payload)
    watch_context = _watch_context(session, need_id, checkpoint.get("origin", ""))
    if watch_context is not None:
        payload["watch_context"] = watch_context
        payload = _bound_grounded_payload(payload)
    return payload


def _publish_commercial_assessment_result(
    *,
    job_id: UUID,
    worker_id: str,
    fence_token: int,
    call_id: UUID,
    call_result: dict[str, Any],
    input_tokens: int,
    output_tokens: int,
    provider_response_id: str | None,
) -> dict[str, Any]:
    """Settle the M4 call and its job from one coherent publication snapshot."""
    for attempt in range(2):
        try:
            with SessionLocal.begin() as session:
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                job = assert_fence(session, job_id, worker_id, fence_token)
                checkpoint = json.loads(job.checkpoint or "{}")
                payload = checkpoint.get("payload", {})
                need_id = job.target_id
                if need_id is None:
                    raise ValueError("M4 job has no target need")
                lock_specs = (
                    (PowerNeed, payload.get("need", {}).get("need_id")),
                    (Project, payload.get("project", {}).get("project_id")),
                    (EvidencePackage, payload.get("package", {}).get("id")),
                )
                for model, raw_id in lock_specs:
                    if not raw_id:
                        raise ValueError("M4 publication identity is incomplete")
                    row_id = UUID(str(raw_id))
                    row = session.scalar(
                        select(model)
                        .where(model.id == row_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if row is None:
                        raise ValueError("M4 publication identity is missing")
                package = payload.get("package", {})
                refs = package.get("source_references", [])
                if not isinstance(refs, list) or len(refs) != 1:
                    raise ValueError("M4 package source references are malformed")
                ref = refs[0]
                for citation_model, key in (
                    (Evidence, "evidence_id"),
                    (Observation, "observation_id"),
                    (Source, "source_id"),
                ):
                    raw_id = ref.get(key)
                    if not raw_id:
                        raise ValueError("M4 citation identity is incomplete")
                    row_id = raw_id if citation_model is Source else UUID(str(raw_id))
                    row = session.scalar(
                        select(citation_model)
                        .where(citation_model.id == row_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if row is None:
                        raise ValueError("M4 citation identity is missing")

                try:
                    current_payload = _current_payload(session, checkpoint, need_id)
                    fresh = _digest(current_payload) == checkpoint.get("request_digest")
                except (ValueError, KeyError, TypeError):
                    fresh = False
                published_at = datetime.now(UTC).isoformat()
                if fresh:
                    result = dict(call_result)
                    result["validation_outcome"] = "VALIDATED"
                else:
                    result = {
                        "provider": call_result.get("provider"),
                        "actual_model": call_result.get("actual_model"),
                        "service_tier": call_result.get("service_tier"),
                        "provider_response_id": provider_response_id,
                        "usage": call_result.get("usage"),
                        "validation_outcome": "STALE_CONTEXT",
                        "validation_reason": "INPUT_CHANGED_DURING_PROVIDER_CALL",
                    }
                result["publication_snapshot"] = {
                    "request_digest": checkpoint.get("request_digest"),
                    "published_at": published_at,
                    "basis": "as_of_publication_repeatable_read",
                }
                transition = complete_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    result_digest=_digest(result),
                    result_payload=result,
                    defer_commit=True,
                )
                if (
                    transition.status != "COMPLETED"
                    or transition.reused
                    or transition.blocked_reason
                ):
                    raise RuntimeError("M4 call settlement did not complete under its fence")
                checkpoint.update(
                    status="completed" if fresh else "stale",
                    completed_at=published_at,
                    result=result,
                    result_status="validated" if fresh else "stale_context",
                    error=None if fresh else "INPUT_CHANGED_DURING_PROVIDER_CALL",
                    validation_outcome="VALIDATED" if fresh else "STALE_CONTEXT",
                    validation_reason=None if fresh else "INPUT_CHANGED_DURING_PROVIDER_CALL",
                    provider_response_id=provider_response_id,
                    usage=result.get("usage"),
                )
                if fresh:
                    _apply_bounded_routing_effect(
                        session,
                        checkpoint=checkpoint,
                        result=result,
                        need_id=need_id,
                    )
                _record_research_receipt(session, checkpoint)
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
            return {
                "status": "completed" if fresh else "stale",
                "result": result,
                "error": None if fresh else "INPUT_CHANGED_DURING_PROVIDER_CALL",
                "job_id": str(job_id),
            }
        except DBAPIError as exc:
            original = exc.orig
            state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            if state != "40001" or attempt:
                raise
    raise RuntimeError("M4 publication retry exhausted")


def _queue_stale_reassessment(
    session: Session, checkpoint: dict[str, Any], need_id: UUID
) -> str | None:
    question_id = checkpoint.get("question_id")
    if checkpoint.get("task_type") not in GROUND_TASKS or not question_id:
        return None
    job = enqueue_intelligence(
        session,
        need_id=need_id,
        task_type="GROUNDED_DOSSIER",
        question_id=question_id,
        origin="stale_reassessment",
    )
    return str(job.id)


def enqueue_intelligence(
    session: Session,
    *,
    need_id: UUID,
    task_type: str,
    question_id: str | None = None,
    origin: str = "operator",
    package_id: UUID | None = None,
) -> Job:
    """Queue one exact need/evidence request; active unchanged jobs are reused."""
    need, project, source, evidence = _retained_context(session, need_id)
    payload = _request_payload(
        session, task_type, question_id, need, project, source, evidence, package_id
    )
    payload = _bound_grounded_payload(payload)
    watch_context = _watch_context(session, need_id, origin)
    if watch_context is not None:
        payload["watch_context"] = watch_context
        payload = _bound_grounded_payload(payload)
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
    matching_job_id = session.scalar(
        select(Job.id)
        .where(
            Job.kind == JOB_KIND,
            Job.target_id == need_id,
            Job.status.in_(["queued", "running"]),
            text(
                "CASE WHEN pg_input_is_valid(jobs.checkpoint, 'jsonb') "
                "THEN jobs.checkpoint::jsonb->>'request_digest' END = :request_digest"
            ),
        )
        .params(request_digest=identity)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )
    if matching_job_id is not None:
        matching_job = session.get(Job, matching_job_id)
        if matching_job is not None:
            return matching_job
    no_subject_result: dict[str, Any] | None = None
    no_subject_status: str | None = None
    if task_type == "MATCH_ADVISORY_V1" and not payload["task_context"]["deterministic_candidates"]:
        no_subject_status = "not_applicable"
        no_subject_result = {
            "schema_version": "jev-advisory-v1",
            "match_advisories": [],
            "disposition": "UNRESOLVED_NO_ELIGIBLE_CANDIDATE",
            "authority": "ADVISORY_ONLY",
        }
    elif task_type == "BUYER_ROLE_HINT_V1" and not payload["task_context"]["party_candidates"]:
        no_subject_status = "advisory_unknown"
        no_subject_result = {
            "schema_version": "jev-advisory-v1",
            "answer": {"choice": "UNKNOWN", "confidence": None, "probabilities": None},
            "disposition": "UNRESOLVED_NO_NAMED_PARTY_CANDIDATE",
            "authority": "ADVISORY_ONLY",
        }
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
                "package_id": str(package_id) if package_id else None,
                "question_id": question_id,
                "origin": origin[:40],
                "request_digest": identity,
                "payload": payload,
                "status": no_subject_status or "queued",
                "result": no_subject_result,
                "research_question_id": research_question_id,
                "research_question_created": created_research_question,
            },
            separators=(",", ":"),
        ),
    )
    session.add(job)
    if no_subject_status:
        job.status = "succeeded"
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


def _enabled(
    task_type: str,
    question_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, str, str, str]:
    mode = settings.intelligence_mode
    allowlist = {v.strip() for v in settings.intelligence_enabled_contracts.split(",") if v.strip()}
    if (question_id if task_type in GROUND_TASKS else task_type) not in allowlist:
        return False, "", "", "CONTRACT_DISABLED"
    if task_type == "MATCH_ADVISORY_V1" and not (
        payload and payload.get("task_context", {}).get("deterministic_candidates")
    ):
        return False, "", "", "MATCH_CONTEXT_INCOMPLETE"
    if task_type == "BUYER_ROLE_HINT_V1" and not (
        payload and payload.get("task_context", {}).get("party_candidates")
    ):
        return False, "", "", "BUYER_SUBJECT_UNRESOLVED"
    if task_type == COMMERCIAL_ASSESSMENT_TASK:
        model = settings.intelligence_openai_reasoning_model
        if not settings.intelligence_enabled or mode not in {"evaluation", "advisory"}:
            return False, "", "", "INTELLIGENCE_DISABLED"
        if not settings.intelligence_openai_enabled or not settings.openai_api_key:
            return False, "", "", "OPENAI_DISABLED_OR_KEY_MISSING"
        if (
            model != "gpt-6.1-sol"
            or settings.intelligence_openai_reasoning_priced_model_id != model
            or not settings.intelligence_openai_reasoning_pricing_verified
        ):
            return False, "", "", "M4_PINNED_MODEL_PRICING_MISSING"
        if not payload or payload.get("project", {}).get("region_status") != "ELIGIBLE":
            return False, "", "", "M4_PROJECT_REGION_NOT_ELIGIBLE"
        return True, "openai", model, ""
    if not settings.intelligence_enabled or mode not in {
        "evaluation",
        "advisory",
        "bounded_routing",
    }:
        return False, "", "", "INTELLIGENCE_DISABLED"
    if mode == "bounded_routing":
        if task_type not in {"RESEARCH_PRIORITY_V1", "LLM_ROUTE_V1", *GROUND_TASKS}:
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
        if task_type == "POWER_NEED_TITLE":
            if not settings.power_need_titles_enabled:
                return False, "", "", "TITLE_ENRICHMENT_DISABLED"
            if not settings.intelligence_openai_enabled or not settings.openai_api_key:
                return False, "", "", "OPENAI_DISABLED_OR_KEY_MISSING"
            model = settings.openai_brief_model
            if model != settings.intelligence_openai_reasoning_model:
                return False, "", "", "TITLE_MODEL_NOT_MATCHED_TO_PRICED_REASONING_MODEL"
            if (
                not settings.intelligence_openai_reasoning_pricing_verified
                or settings.intelligence_openai_reasoning_priced_model_id != model
                or settings.intelligence_openai_reasoning_max_output_tokens < 240
                or settings.intelligence_openai_reasoning_input_usd_per_million <= 0
                or settings.intelligence_openai_reasoning_output_usd_per_million < 0
            ):
                return False, "", "", "OPENAI_OUTPUT_BOUND_OR_MODEL_PRICING_MISSING"
            return True, "openai", model, ""
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
        if task_type == TYPESAFE_SIGNAL_ESTIMATE_TASK and _estimated_signal_policy_selected():
            reason = _estimated_signal_policy_block_reason(payload)
            if reason:
                return False, "", "", reason
            return True, "typesafe", TYPESAFE_SIGNAL_ESTIMATE_MODEL, ""
        expected_model = settings.intelligence_typesafe_model
        if not settings.jev_enabled or not settings.intelligence_typesafe_enabled:
            return False, "", "", "TYPESAFE_DISABLED"
        if not settings.typesafe_api_key:
            return False, "", "", "TYPESAFE_KEY_OR_PINNED_MODEL_MISSING"
        billing_reason = _typesafe_billing_block_reason(expected_model, task_type)
        if billing_reason:
            return False, "", "", billing_reason
        if (
            not settings.intelligence_typesafe_pricing_verified
            or settings.intelligence_typesafe_priced_model_id != expected_model
            or settings.intelligence_typesafe_input_usd_per_million <= 0
        ):
            return False, "", "", "TYPESAFE_INPUT_PRICING_OR_MODEL_MISSING"
        return True, "typesafe", expected_model, ""
    if not settings.jev_enabled or not settings.intelligence_typesafe_enabled:
        return False, "", "", "TYPESAFE_DISABLED"
    if not settings.typesafe_api_key or not settings.intelligence_typesafe_model:
        return False, "", "", "TYPESAFE_KEY_OR_PINNED_MODEL_MISSING"
    billing_reason = _typesafe_billing_block_reason(settings.intelligence_typesafe_model, task_type)
    if billing_reason:
        return False, "", "", billing_reason
    if (
        not settings.intelligence_typesafe_pricing_verified
        or settings.intelligence_typesafe_priced_model_id != settings.intelligence_typesafe_model
        or settings.intelligence_typesafe_input_usd_per_million <= 0
    ):
        return False, "", "", "TYPESAFE_INPUT_PRICING_OR_MODEL_MISSING"
    return True, "typesafe", settings.intelligence_typesafe_model, ""


def _estimated_signal_policy_selected() -> bool:
    """Select estimate mode explicitly; malformed partial configuration cannot fall back."""
    return bool(
        settings.intelligence_typesafe_billing_policy_id == TYPESAFE_SIGNAL_ESTIMATE_POLICY_ID
        or settings.intelligence_typesafe_estimated_reservation_usd != 0
        or settings.intelligence_typesafe_estimate_observation_ids.strip()
    )


def _estimated_signal_observation_ids() -> set[str]:
    ids: set[str] = set()
    for item in settings.intelligence_typesafe_estimate_observation_ids.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.add(str(UUID(value)))
        except (ValueError, AttributeError):
            return set()
        if len(ids) > 10:
            return set()
    return ids


def _estimated_signal_policy_block_reason(payload: dict[str, Any] | None) -> str:
    """Validate the sole narrow estimated-reservation policy without claiming a hard bound."""
    amount = settings.intelligence_typesafe_estimated_reservation_usd
    selected = _estimated_signal_observation_ids()
    if settings.intelligence_typesafe_billing_policy_id != TYPESAFE_SIGNAL_ESTIMATE_POLICY_ID:
        return "TYPESAFE_ESTIMATE_POLICY_ID_MISMATCH"
    if (
        not amount.is_finite()
        or amount != Decimal("0.01")
        or amount > settings.intelligence_max_call_usd
    ):
        return "TYPESAFE_ESTIMATE_RESERVATION_INVALID"
    if not selected:
        return "TYPESAFE_ESTIMATE_SCOPE_EMPTY_OR_INVALID"
    if (
        not settings.intelligence_enabled
        or settings.intelligence_mode not in {"evaluation", "advisory"}
        or not settings.jev_enabled
        or not settings.intelligence_typesafe_enabled
        or not settings.typesafe_api_key
    ):
        return "TYPESAFE_OR_INTELLIGENCE_DISABLED"
    if settings.intelligence_typesafe_model != TYPESAFE_SIGNAL_ESTIMATE_MODEL:
        return "TYPESAFE_ESTIMATE_MODEL_NOT_PINNED"
    if (
        settings.intelligence_typesafe_billing_mode != "input_only"
        or not settings.intelligence_typesafe_billing_verified
        or settings.intelligence_typesafe_billing_model_id != TYPESAFE_SIGNAL_ESTIMATE_MODEL
        or settings.intelligence_typesafe_billing_contract_id != TYPESAFE_BILLING_CONTRACT_ID
        or not settings.intelligence_typesafe_billing_reference.strip()
        or not settings.intelligence_typesafe_pricing_verified
        or settings.intelligence_typesafe_priced_model_id != TYPESAFE_SIGNAL_ESTIMATE_MODEL
        or settings.intelligence_typesafe_input_usd_per_million != Decimal("0.042")
        or settings.intelligence_typesafe_output_usd_per_million != Decimal("0")
        or settings.intelligence_typesafe_total_input_bound_verified
    ):
        return "TYPESAFE_ESTIMATE_PRICING_OR_NO_HARD_BOUND_POLICY_INVALID"
    if payload is None:
        return "TYPESAFE_ESTIMATE_OBSERVATION_SCOPE_REQUIRED"
    observation_id = payload.get("observation_id")
    evidence_id = payload.get("evidence_id")
    evidence_hash = payload.get("evidence_hash")
    try:
        normalized_id = str(UUID(str(observation_id)))
        UUID(str(evidence_id))
    except (ValueError, TypeError, AttributeError):
        return "TYPESAFE_ESTIMATE_RETAINED_EVIDENCE_REQUIRED"
    if normalized_id not in selected or not isinstance(evidence_hash, str) or not evidence_hash:
        return "TYPESAFE_ESTIMATE_OBSERVATION_NOT_SELECTED"
    state = payload.get("state")
    if not isinstance(state, dict):
        return "TYPESAFE_ESTIMATE_REQUEST_INVALID"
    try:
        from gridlens.intelligence.signal_adjudication import jev_request_payload

        request = jev_request_payload(state, model=TYPESAFE_SIGNAL_ESTIMATE_MODEL)
        request_bytes = _serialized_request_bytes(request)
    except (KeyError, TypeError, ValueError, RecursionError):
        return "TYPESAFE_ESTIMATE_REQUEST_INVALID"
    if request_bytes > TYPESAFE_SIGNAL_REQUEST_MAX_BYTES:
        return "TYPESAFE_ESTIMATE_REQUEST_TOO_LARGE"
    return ""


def _typesafe_billing_block_reason(model: str, task_type: str | None = None) -> str:
    """Require explicit model/contract/policy proof and a total input ceiling.

    The current SystemOne transport has no documented, enforced output bound, so
    billable output cannot be reserved safely. Input proof must include all
    provider-wrapper tokens; client JSON size and a numeric cap alone are not proof.
    """
    unlimited = bool(task_type and _owner_unlimited_allowed("typesafe", task_type))
    if unlimited and re.fullmatch(r"jev-\d+\.\d+\.\d+", model) is None:
        return "TYPESAFE_PINNED_VERSIONED_MODEL_REQUIRED"
    expected_policy = (
        TYPESAFE_UNLIMITED_BILLING_POLICY_ID if unlimited else TYPESAFE_BILLING_POLICY_ID
    )
    common_invalid = (
        not settings.intelligence_typesafe_billing_verified
        or settings.intelligence_typesafe_billing_mode != "input_only"
        or not model
        or settings.intelligence_typesafe_billing_model_id != model
        or settings.intelligence_typesafe_billing_contract_id != TYPESAFE_BILLING_CONTRACT_ID
        or settings.intelligence_typesafe_billing_policy_id != expected_policy
        or not settings.intelligence_typesafe_billing_reference.strip()
    )
    if common_invalid or (
        not unlimited
        and (
            not settings.intelligence_typesafe_total_input_bound_verified
            or settings.intelligence_typesafe_max_total_billable_input_tokens <= 0
        )
    ):
        return "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"
    if settings.intelligence_typesafe_output_usd_per_million != 0:
        return "TYPESAFE_OUTPUT_BOUND_UNVERIFIED"
    return ""


def _billing_policy_identity(
    provider: str, model: str, task_type: str | None = None
) -> dict[str, str] | None:
    """Return response/billing policy identity used for call freshness and dispatch."""
    if provider not in {"typesafe", "openai"}:
        return None
    financial_identity = {
        "financial_budget_mode": settings.intelligence_financial_budget_mode,
        "financial_authorization_ref": settings.intelligence_financial_authorization_ref,
        "unlimited_contracts": settings.intelligence_unlimited_contracts,
        "unlimited_providers": settings.intelligence_unlimited_providers,
    }
    response_policy = {"response_guard_policy": "exact-model-usage-v1", "provider_model": model}
    if provider == "openai":
        if task_type == COMMERCIAL_ASSESSMENT_TASK:
            return {
                **response_policy,
                **financial_identity,
                "task_type": COMMERCIAL_ASSESSMENT_TASK,
                "policy_id": "m4-commercial-assessment-v1",
                "input_rate_usd_per_million": "2.50",
                "output_rate_usd_per_million": "10",
                "max_output_tokens": str(COMMERCIAL_ASSESSMENT_OUTPUT_TOKENS),
                "service_tier": "default",
                "reasoning_effort": "medium",
                "prompt_cache_ttl": "30m",
            }
        prefix = (
            "ocr"
            if task_type in {"OCR_EXTRACTION", "OCR_GROUNDED_FOLLOWON"}
            else "fast"
            if task_type == "GROUNDED_EXTRACTION"
            else "reasoning"
        )
        name_prefix = "intelligence_ocr" if prefix == "ocr" else f"intelligence_openai_{prefix}"
        return {
            **response_policy,
            **financial_identity,
            "pricing_verified": str(getattr(settings, f"{name_prefix}_pricing_verified")).lower(),
            "priced_model_id": getattr(settings, f"{name_prefix}_priced_model_id"),
            "input_rate": str(getattr(settings, f"{name_prefix}_input_usd_per_million")),
            "output_rate": str(getattr(settings, f"{name_prefix}_output_usd_per_million")),
            "max_output_tokens": str(getattr(settings, f"{name_prefix}_max_output_tokens")),
        }
    if task_type == TYPESAFE_SIGNAL_ESTIMATE_TASK and _estimated_signal_policy_selected():
        scope = sorted(_estimated_signal_observation_ids())
        return {
            **response_policy,
            **financial_identity,
            "task_type": TYPESAFE_SIGNAL_ESTIMATE_TASK,
            "cost_basis": "ESTIMATE",
            "policy_id": TYPESAFE_SIGNAL_ESTIMATE_POLICY_ID,
            "billing_mode": settings.intelligence_typesafe_billing_mode,
            "billing_verified": str(settings.intelligence_typesafe_billing_verified).lower(),
            "billing_model_id": settings.intelligence_typesafe_billing_model_id,
            "billing_contract_id": settings.intelligence_typesafe_billing_contract_id,
            "pricing_verified": str(settings.intelligence_typesafe_pricing_verified).lower(),
            "priced_model_id": settings.intelligence_typesafe_priced_model_id,
            "pricing_reference": settings.intelligence_typesafe_billing_reference,
            "input_rate": str(settings.intelligence_typesafe_input_usd_per_million),
            "output_rate": str(settings.intelligence_typesafe_output_usd_per_million),
            "reservation_usd": str(settings.intelligence_typesafe_estimated_reservation_usd),
            "request_max_bytes": str(TYPESAFE_SIGNAL_REQUEST_MAX_BYTES),
            "reported_input_review_tokens": str(TYPESAFE_SIGNAL_REPORTED_INPUT_REVIEW_TOKENS),
            "max_attempts": "1",
            "hard_bound_verified": "false",
            "selected_scope_sha256": hashlib.sha256(
                json.dumps(scope, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest(),
        }
    return {
        **response_policy,
        **financial_identity,
        "mode": settings.intelligence_typesafe_billing_mode,
        "verified": str(settings.intelligence_typesafe_billing_verified).lower(),
        "model_id": settings.intelligence_typesafe_billing_model_id,
        "contract_id": settings.intelligence_typesafe_billing_contract_id,
        "policy_id": (
            TYPESAFE_UNLIMITED_BILLING_POLICY_ID
            if task_type is not None and _owner_unlimited_allowed(provider, task_type)
            else settings.intelligence_typesafe_billing_policy_id
        ),
        "reference": settings.intelligence_typesafe_billing_reference,
        "max_total_billable_input_tokens": (
            "UNBOUNDED"
            if task_type is not None and _owner_unlimited_allowed(provider, task_type)
            else str(settings.intelligence_typesafe_max_total_billable_input_tokens)
        ),
        "total_input_bound_verified": str(
            settings.intelligence_typesafe_total_input_bound_verified
        ).lower(),
        "pricing_verified": str(settings.intelligence_typesafe_pricing_verified).lower(),
        "priced_model_id": settings.intelligence_typesafe_priced_model_id,
        "input_rate": str(settings.intelligence_typesafe_input_usd_per_million),
        "output_rate": str(settings.intelligence_typesafe_output_usd_per_million),
    }


def _openai_output_bound(task_type: str) -> int:
    if task_type == COMMERCIAL_ASSESSMENT_TASK:
        return COMMERCIAL_ASSESSMENT_OUTPUT_TOKENS
    if task_type == "POWER_NEED_TITLE":
        return POWER_NEED_TITLE_OUTPUT_TOKENS
    if task_type in {"OCR_EXTRACTION", "OCR_GROUNDED_FOLLOWON"}:
        return settings.intelligence_ocr_max_output_tokens
    prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
    return getattr(settings, f"intelligence_openai_{prefix}_max_output_tokens")


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
    reserved_cost: Decimal | None,
    expected_billing_policy: dict[str, str] | None = None,
) -> tuple[bool, str]:
    enabled, current_provider, current_model, reason = _enabled(task_type, question_id, payload)
    if not enabled or current_provider != provider or current_model != model:
        return False, reason or "PROVIDER_POLICY_CHANGED"
    if (
        expected_billing_policy is not None
        and _billing_policy_identity(provider, model, task_type) != expected_billing_policy
    ):
        return False, "TYPESAFE_BILLING_POLICY_CHANGED"
    unlimited = _owner_unlimited_allowed(provider, task_type)
    if settings.intelligence_max_active_calls <= 0:
        return False, "ACTIVE_CALL_CAP_REQUIRED"
    if not unlimited and settings.intelligence_max_call_usd <= 0:
        return False, "FINITE_BUDGET_REQUIRED"
    current_cost = _cost_bound(provider, task_type, payload)
    if unlimited:
        if reserved_cost is not None:
            return False, "FINANCIAL_POLICY_CHANGED"
    elif (
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
            if not unlimited and (usd_cap <= 0 or current_cost > usd_cap):
                return False, f"{scope.upper()}_{period.upper()}_USD_CAP_INVALID"
    return True, ""


def _owner_unlimited_allowed(provider: str, task_type: str) -> bool:
    return bool(
        settings.intelligence_financial_budget_mode == "owner_unlimited"
        and settings.intelligence_financial_authorization_ref.strip()
        and provider
        in {v.strip() for v in settings.intelligence_unlimited_providers.split(",") if v.strip()}
        and task_type
        in {v.strip() for v in settings.intelligence_unlimited_contracts.split(",") if v.strip()}
    )


def _cost_bound(provider: str, task_type: str, payload: dict[str, Any]) -> Decimal:
    if provider == "firecrawl":
        unit = (
            settings.firecrawl_search_cost_usd
            if task_type == "FIRECRAWL_SEARCH_V2"
            else settings.firecrawl_scrape_cost_usd
        )
        return unit or Decimal("0")
    if provider == "openai":
        if task_type == COMMERCIAL_ASSESSMENT_TASK:
            request = commercial_assessment_request_payload(
                model=settings.intelligence_openai_reasoning_model,
                input_payload=payload,
                schema=ASSESSMENT_SCHEMA,
            )
            input_upper = _serialized_request_bytes(request)
            reserved = (
                Decimal(input_upper) * Decimal("2.50") + Decimal(6000) * Decimal("10")
            ) / Decimal(1_000_000)
            return reserved if reserved <= Decimal("0.25") else Decimal("0")
        from gridlens.intelligence.briefs import brief_request_payload

        if task_type == "POWER_NEED_TITLE":
            from gridlens.intelligence.titles import MAX_OUTPUT_TOKENS, title_request_payload

            title_payload = payload["title"]
            evidence = payload["evidence"]
            if not payload.get("roles") and not payload.get("activities"):
                return Decimal("0")
            request = title_request_payload(
                title_payload, evidence, payload.get("roles"), payload.get("activities")
            )
            request_bytes = _serialized_request_bytes(request)
            input_price = settings.intelligence_openai_reasoning_input_usd_per_million
            output_price = settings.intelligence_openai_reasoning_output_usd_per_million
            output_tokens = MAX_OUTPUT_TOKENS
            return (
                Decimal(request_bytes) * input_price + Decimal(output_tokens) * output_price
            ) / Decimal(1_000_000)
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
        if (
            provider == "typesafe"
            and task_type == TYPESAFE_SIGNAL_ESTIMATE_TASK
            and _estimated_signal_policy_selected()
        ):
            if _estimated_signal_policy_block_reason(payload):
                return Decimal("0")
            from gridlens.intelligence.signal_adjudication import jev_request_payload

            request = jev_request_payload(payload["state"], model=TYPESAFE_SIGNAL_ESTIMATE_MODEL)
            if _serialized_request_bytes(request) > TYPESAFE_SIGNAL_REQUEST_MAX_BYTES:
                return Decimal("0")
            return settings.intelligence_typesafe_estimated_reservation_usd
        if _typesafe_billing_block_reason(settings.intelligence_typesafe_model, task_type):
            return Decimal("0")
        input_price = settings.intelligence_typesafe_input_usd_per_million
        input_tokens = settings.intelligence_typesafe_max_total_billable_input_tokens
        # Reserve the attested maximum for all billable input, including opaque
        # SystemOne wrapper tokens. Client serialization cannot bound that wrapper.
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
        if not request:
            return Decimal("0")
        return (
            Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price
        ) / Decimal(1_000_000)
    # One byte per token is a conservative bound over the complete serialized request.
    return (Decimal(request_bytes) * input_price + Decimal(output_tokens) * output_price) / Decimal(
        1_000_000
    )


def _estimated_cost_from_usage(
    provider: str,
    task_type: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    billing_policy: dict[str, str] | None = None,
) -> Decimal | None:
    estimate_policy = billing_policy is not None and billing_policy.get("cost_basis") == "ESTIMATE"
    if input_tokens is None or (output_tokens is None and not estimate_policy):
        return None
    if type(input_tokens) is not int or input_tokens < 0:
        raise ValueError("Provider input token usage is invalid")
    if output_tokens is None and estimate_policy:
        output_tokens = 0
    if type(output_tokens) is not int or output_tokens < 0:
        raise ValueError("Provider output token usage is invalid")
    if provider == "openai":
        if task_type == COMMERCIAL_ASSESSMENT_TASK:
            input_price, output_price = Decimal("2.50"), Decimal("10")
            return (
                Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price
            ) / Decimal(1_000_000)
        prefix = "fast" if task_type == "GROUNDED_EXTRACTION" else "reasoning"
        input_price = getattr(settings, f"intelligence_openai_{prefix}_input_usd_per_million")
        output_price = getattr(settings, f"intelligence_openai_{prefix}_output_usd_per_million")
    elif estimate_policy:
        assert billing_policy is not None
        input_price = Decimal(billing_policy["input_rate"])
        output_price = Decimal(billing_policy["output_rate"])
    else:
        input_price = settings.intelligence_typesafe_input_usd_per_million
        output_price = Decimal("0")
    return (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / Decimal(
        1_000_000
    )


def _safe_provider_audit(value: Any) -> Any:
    """Return bounded redacted evidence; pathological trees degrade to safe identity metadata."""
    secret_keys = {"authorization", "api_key", "apikey", "access_token", "secret", "credential"}
    visited = 0

    def fallback(omitted: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {"omitted": omitted}
        if isinstance(value, dict):
            for key in (
                "provider_response_id",
                "provider_request_id",
                "model",
                "raw_response_sha256",
            ):
                scalar = value.get(key)
                if isinstance(scalar, str):
                    metadata[key] = scalar[:256]
            raw_bytes = value.get("raw_response_bytes")
            if type(raw_bytes) is int and raw_bytes >= 0:
                metadata["raw_response_bytes"] = raw_bytes
            usage = value.get("usage")
            if isinstance(usage, dict):
                metadata["usage"] = {
                    key: token
                    for key in ("input_tokens", "output_tokens")
                    if (token := usage.get(key)) is None
                    or (type(token) is int and 0 <= token <= 2**63 - 1)
                }
        canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        metadata["identity_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return metadata

    def clean(item: Any, depth: int = 0) -> Any:
        nonlocal visited
        visited += 1
        if visited > 5000:
            return "[TRUNCATED_MAX_ITEMS]"
        if depth >= 32:
            return "[TRUNCATED_MAX_DEPTH]"
        if isinstance(item, dict):
            result = {}
            for index, (key, child) in enumerate(item.items()):
                if index >= 1000:
                    result["_truncated"] = "MAX_FIELDS"
                    break
                key_text = str(key)[:200]
                normalized = key_text.casefold().replace("-", "_")
                result[key_text] = (
                    "[REDACTED]"
                    if normalized in secret_keys or normalized.endswith("_secret")
                    else clean(child, depth + 1)
                )
            return result
        if isinstance(item, list):
            items = [clean(child, depth + 1) for child in item[:1000]]
            if len(item) > 1000:
                items.append("[TRUNCATED_MAX_FIELDS]")
            return items
        if isinstance(item, str):
            return item[:8000]
        if isinstance(item, float) and not math.isfinite(item):
            return str(item)
        if isinstance(item, int | float | bool) or item is None:
            return item
        try:
            return str(item)[:2000]
        except (RecursionError, ValueError, TypeError):
            return "[UNSERIALIZABLE_VALUE]"

    if _provider_audit_exceeds_bound(value):
        return fallback("MAX_RESULT_BYTES")
    try:
        return clean(value)
    except (RecursionError, ValueError, TypeError, OverflowError):
        # Never serialize the provider body again on this fallback path. Its
        # digest identifies only the shallow safe metadata, not the raw body.
        return fallback("UNSAFE_PROVIDER_RESPONSE_TREE")


def _provider_response_id(data: dict[str, Any]) -> str | None:
    value = data.get("provider_response_id")
    return value if isinstance(value, str) and value.strip() and len(value) <= 256 else None


def _provider_audit_exceeds_bound(value: Any) -> bool:
    """Measure original provider JSON before any redaction or list truncation."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return True
    return len(encoded) > MAX_RESULT_BYTES


def _bounded_cost_exposure(
    provider: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    billing_policy: dict[str, str] | None = None,
) -> tuple[Decimal | None, str]:
    """Do not let an unrepresentable estimate prevent durable provider quarantine."""
    try:
        if provider == "openai" and task_type in {
            "OCR_EXTRACTION",
            "OCR_GROUNDED_FOLLOWON",
        }:
            estimate = (
                Decimal(input_tokens) * settings.intelligence_ocr_input_usd_per_million
                + Decimal(output_tokens) * settings.intelligence_ocr_output_usd_per_million
            ) / Decimal(1_000_000)
        else:
            estimate = _estimated_cost_from_usage(
                provider, task_type, input_tokens, output_tokens, billing_policy=billing_policy
            )
        if estimate is None or not estimate.is_finite() or estimate > MAX_ACTUAL_USD:
            return None, "UNBOUNDED"
        return estimate, "BOUNDED"
    except (ArithmeticError, ValueError, TypeError):
        return None, "UNBOUNDED"


def _provider_error_quarantine_details(
    error: Exception,
    *,
    provider: str,
    task_type: str,
    expected_model: str,
    input_token_limit: int | None = None,
    billing_policy: dict[str, str] | None = None,
    actual_service_tier: Any = None,
) -> dict[str, Any] | None:
    """Normalize a received provider error into bounded quarantine evidence."""
    if provider not in {"typesafe", "openai"} or not getattr(error, "response_received", False):
        return None
    response_status = getattr(error, "response_status", None)
    if isinstance(response_status, int) and 400 <= response_status < 500:
        return None  # Conclusive client rejection, retained on the existing failure path.
    raw = getattr(error, "raw_response", None)
    actual_model = getattr(error, "reported_model", None)
    usage = getattr(error, "reported_usage", None)
    if isinstance(raw, dict):
        if actual_model is None:
            actual_model = raw.get("model")
        if not isinstance(usage, dict):
            usage = raw.get("usage")
        if actual_service_tier is None:
            actual_service_tier = raw.get("service_tier")
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    raw_size = getattr(error, "raw_response_size", None)
    too_large = isinstance(raw_size, int) and raw_size > MAX_RESULT_BYTES
    if raw is not None and _provider_audit_exceeds_bound(raw):
        too_large = True

    if too_large:
        reason = "RESPONSE_TOO_LARGE"
    elif actual_model != expected_model:
        reason = "MODEL_IDENTITY_MISMATCH"
    elif task_type == COMMERCIAL_ASSESSMENT_TASK and actual_service_tier != "default":
        reason = "SERVICE_TIER_MISMATCH"
    elif not _valid_reported_tokens(input_tokens) or not _valid_reported_tokens(output_tokens):
        reason = "INVALID_REPORTED_USAGE"
    elif input_tokens is None or (provider == "openai" and output_tokens is None):
        reason = "MISSING_REPORTED_USAGE"
    elif (
        input_token_limit is not None
        and input_tokens is not None
        and input_tokens > input_token_limit
    ):
        reason = "REPORTED_INPUT_EXCEEDS_PREFLIGHT_COUNT"
    elif (
        provider == "typesafe"
        and billing_policy is not None
        and billing_policy.get("cost_basis") == "ESTIMATE"
        and input_tokens is not None
        and input_tokens > TYPESAFE_SIGNAL_REPORTED_INPUT_REVIEW_TOKENS
    ):
        reason = "ESTIMATED_CONTEXT_ASSUMPTION_EXCEEDED"
    elif (
        provider == "typesafe"
        and not (billing_policy is not None and billing_policy.get("cost_basis") == "ESTIMATE")
        and (billing_policy or {}).get("policy_id") != TYPESAFE_UNLIMITED_BILLING_POLICY_ID
        and input_tokens > settings.intelligence_typesafe_max_total_billable_input_tokens
    ):
        reason = "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED"
    elif (
        provider == "openai"
        and output_tokens is not None
        and output_tokens > _openai_output_bound(task_type)
    ):
        reason = "ENFORCED_OUTPUT_BOUND_EXCEEDED"
    else:
        reason = "PROVIDER_RESPONSE_UNVALIDATABLE"

    if isinstance(raw, dict):
        response_payload = dict(raw)
        provider_response_id = response_payload.get("provider_response_id")
        if not isinstance(provider_response_id, str) and isinstance(
            response_payload.get("id"), str
        ):
            response_payload["provider_response_id"] = response_payload["id"]
        request_id = getattr(error, "request_id", None)
        if isinstance(request_id, str):
            response_payload["provider_request_id"] = request_id
        raw_digest = getattr(error, "raw_response_sha256", None)
        if isinstance(raw_digest, str):
            response_payload["raw_response_sha256"] = raw_digest
        if type(raw_size) is int and raw_size >= 0:
            response_payload["raw_response_bytes"] = raw_size
    else:
        response_payload = {
            "provider_request_id": getattr(error, "request_id", None),
            "model": actual_model,
            "usage": usage,
            "response_status": response_status,
            "response_body_sha256": getattr(error, "raw_response_sha256", None),
            "response_body_bytes": raw_size,
            "provider_error": type(error).__name__,
        }
    response_payload = _safe_provider_audit(response_payload)

    exposure: Decimal | None = None
    exposure_status = "UNKNOWN"
    exposure_basis = None
    if actual_model == expected_model and _valid_reported_tokens(input_tokens):
        if provider == "typesafe" and input_tokens is not None:
            exposure, exposure_status = _bounded_cost_exposure(
                provider, task_type, input_tokens, 0, billing_policy=billing_policy
            )
            exposure_basis = (
                "reported_same_model_input_tokens_at_estimated_input_rate"
                if billing_policy is not None and billing_policy.get("cost_basis") == "ESTIMATE"
                else "reported_same_model_input_tokens_at_pinned_input_rate"
            )
        elif (
            provider == "openai"
            and input_tokens is not None
            and _valid_reported_tokens(output_tokens)
            and output_tokens is not None
        ):
            exposure, exposure_status = _bounded_cost_exposure(
                provider, task_type, input_tokens, output_tokens
            )
            exposure_basis = "reported_same_model_usage_at_pinned_rates"
    return {
        "reason": reason,
        "actual_model": actual_model,
        "service_tier": actual_service_tier if actual_service_tier is not None else "UNKNOWN",
        "input_tokens": input_tokens if _valid_reported_tokens(input_tokens) else None,
        "output_tokens": output_tokens if _valid_reported_tokens(output_tokens) else None,
        "response_payload": response_payload,
        "conservative_exposure_usd": exposure,
        "exposure_basis": exposure_basis,
        "exposure_status": exposure_status,
    }


def _valid_reported_tokens(value: Any) -> bool:
    return value is None or (type(value) is int and 0 <= value <= 2**63 - 1)


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
            "task_context": payload.get("task_context", {}),
        },
        "questions": payload["questions"],
    }


def _type_safe_result(
    data: dict[str, Any], task_type: str, payload: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str, int | None, int | None]:
    if not isinstance(data.get("model"), str) or not data["model"]:
        raise ValueError("Provider response omitted actual model")
    if task_type in {"MATCH_ADVISORY_V1", "BUYER_ROLE_HINT_V1"}:
        candidate_key = (
            "deterministic_candidates" if task_type == "MATCH_ADVISORY_V1" else "party_candidates"
        )
        candidates = (payload or {}).get("task_context", {}).get(candidate_key)
        if not isinstance(candidates, list):
            raise ValueError("Multi-subject response is missing exact candidate context")
        id_key = "candidate_id" if task_type == "MATCH_ADVISORY_V1" else "party_id"
        expected_ids = {str(item[id_key]) for item in candidates}
        answers = data.get("answers")
        if not expected_ids or not isinstance(answers, dict) or set(answers) != expected_ids:
            raise ValueError("Answer keys must exactly match subject UUIDs")
        advisories = []
        for candidate_id in sorted(expected_ids):
            answer = answers[candidate_id]
            _validate_typesafe_choice(answer, CONTRACTS[task_type])
            validated = validate_answer(
                task_type, {key: value for key, value in answer.items() if key != "type"}
            )
            result_id_key = (
                "candidate_project_id" if task_type == "MATCH_ADVISORY_V1" else "party_id"
            )
            advisories.append({result_id_key: candidate_id, **validated.model_dump()})
        usage_value = data.get("usage")
        match_usage = usage_value if isinstance(usage_value, dict) else {}
        counts = []
        for key in ("input_tokens", "output_tokens"):
            value = match_usage.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Provider token usage is invalid")
            counts.append(value)
        return (
            {
                "schema_version": "jev-advisory-v1",
                (
                    "match_advisories"
                    if task_type == "MATCH_ADVISORY_V1"
                    else "buyer_role_advisories"
                ): advisories,
                "authority": "ADVISORY_ONLY",
            },
            data["model"],
            counts[0],
            counts[1],
        )
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
    _validate_typesafe_choice(answer, contract)
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


def _validate_typesafe_choice(answer: Any, contract: Any) -> None:
    if not isinstance(answer, dict) or set(answer) != {
        "type",
        "choice",
        "confidence",
        "probabilities",
    }:
        raise ValueError("TypeSafe answer shape mismatch")
    confidence, probabilities = answer.get("confidence"), answer.get("probabilities")
    if (
        answer.get("type") != "choice"
        or not isinstance(confidence, int | float)
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


def _active_routing_reference(reference: dict[str, Any] | None) -> bool:
    if not reference or settings.intelligence_mode != "bounded_routing":
        return False
    if not (
        reference.get("policy_id")
        and reference.get("policy_id") == settings.intelligence_routing_policy_id
        and reference.get("evaluated") is True
        and settings.intelligence_routing_policy_evaluated is True
        and reference.get("authorized") is True
        and settings.intelligence_bounded_routing_authorized is True
        and settings.intelligence_max_active_calls > 0
        and settings.intelligence_max_call_usd > 0
    ):
        return False
    return all(
        type(limits[period]) is int and limits[period] > 0 and limits[f"{period}_usd"] > 0
        for limits in _caps().values()
        for period in ("daily", "monthly")
    )


def _apply_bounded_routing_effect(
    session: Session,
    *,
    checkpoint: dict[str, Any],
    result: dict[str, Any],
    need_id: UUID,
) -> dict[str, Any] | None:
    """Apply an authorized advisory only to already queued bounded work."""
    task_type = checkpoint.get("task_type")
    if task_type not in {"RESEARCH_PRIORITY_V1", "LLM_ROUTE_V1"}:
        return None
    reference = checkpoint.get("routing_approval")
    if not _active_routing_reference(reference):
        return None
    if not isinstance(reference, dict):
        return None
    answer = result.get("answer") if isinstance(result, dict) else None
    choice = answer.get("choice") if isinstance(answer, dict) else None
    if task_type == "RESEARCH_PRIORITY_V1":
        if choice not in {"1", "2", "3", "4", "5"}:
            return None
        rank = 6 - int(choice)
        route = "RESEARCH_PRIORITY"
    else:
        if choice not in {"NONE", "FAST_EXTRACT", "DEEP_RESEARCH", "HUMAN_REVIEW"}:
            return None
        route = choice
        if choice == "NONE":
            return {"status": "NO_FOLLOW_ON", "route": route, "policy_id": reference["policy_id"]}
        if choice == "HUMAN_REVIEW":
            return {
                "status": "HUMAN_REVIEW_REQUIRED",
                "route": route,
                "policy_id": reference["policy_id"],
            }
        return _enqueue_routed_grounding(
            session,
            checkpoint=checkpoint,
            need_id=need_id,
            route=choice,
            reference=reference,
        )

    eligible: list[Job] = []
    for queued in session.scalars(
        select(Job)
        .where(
            Job.kind == JOB_KIND,
            Job.target_id == need_id,
            Job.status == "queued",
        )
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(20)
    ):
        try:
            queued_checkpoint = json.loads(queued.checkpoint or "{}")
        except (ValueError, TypeError):
            continue
        queued_type = queued_checkpoint.get("task_type")
        queued_question = queued_checkpoint.get("question_id")
        queued_payload = queued_checkpoint.get("payload")
        if not isinstance(queued_payload, dict) or queued_checkpoint.get("status") != "queued":
            continue
        try:
            fresh_payload = _current_payload(session, queued_checkpoint, need_id)
            if _digest(fresh_payload) != queued_checkpoint.get("request_digest"):
                continue
            enabled, provider, model, _reason = _enabled(
                queued_type, queued_question, fresh_payload
            )
            if not enabled:
                continue
            cost = _cost_bound(provider, queued_type, fresh_payload)
            if not _dispatch_policy(
                queued_type, queued_question, provider, model, fresh_payload, cost
            )[0]:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        eligible.append(queued)
    if not eligible:
        return {
            "status": "NO_ELIGIBLE_QUEUED_WORK",
            "route": route,
            "policy_id": reference["policy_id"],
        }
    applied_to: list[str] = []
    for queued in eligible:
        queued_checkpoint = json.loads(queued.checkpoint or "{}")
        queued_checkpoint["routing_priority"] = {
            "rank": rank,
            "route": route,
            "policy_id": reference["policy_id"],
            "evaluated": True,
            "authorized": True,
            "evaluation_job_id": checkpoint.get("job_id"),
            "evaluation_call_id": checkpoint.get("logical_call_id"),
            "request_digest": checkpoint.get("request_digest"),
        }
        queued.checkpoint = json.dumps(queued_checkpoint, separators=(",", ":"))
        applied_to.append(str(queued.id))
    return {
        "status": "QUEUED_WORK_RANKED",
        "route": route,
        "policy_id": reference["policy_id"],
        "job_ids": applied_to,
    }


def _enqueue_routed_grounding(
    session: Session,
    *,
    checkpoint: dict[str, Any],
    need_id: UUID,
    route: str,
    reference: dict[str, Any],
) -> dict[str, Any]:
    payload = checkpoint.get("payload")
    unresolved = (
        payload.get("task_context", {}).get("unresolved_questions", [])
        if isinstance(payload, dict)
        else []
    )
    categories = {
        item.get("category")
        for item in unresolved
        if isinstance(item, dict) and item.get("category")
    }
    configured = {
        value.strip()
        for value in settings.intelligence_enabled_contracts.split(",")
        if value.strip()
    }
    ordered_questions = (
        "TEMP_LOAD_MW",
        "UTILITY_ONLINE_DATE",
        "COMMISSIONING_WINDOW",
        "CONSTRUCTION_START",
        "DIRECT_BUYER_AUTHORITY",
        "NATURAL_GAS_AVAILABILITY",
    )
    question_id = next(
        (
            candidate
            for candidate in ordered_questions
            if candidate in configured and QUESTION_CONTRACTS[candidate]["category"] in categories
        ),
        None,
    )
    if question_id is None:
        return {
            "status": "NO_AUTHORIZED_UNRESOLVED_QUESTION",
            "route": route,
            "policy_id": reference["policy_id"],
        }
    need, project, source, evidence = _retained_context(session, need_id)
    target_kind = "GROUNDED_EXTRACTION" if route == "FAST_EXTRACT" else "GROUNDED_DOSSIER"
    target_payload = _request_payload(
        session, target_kind, question_id, need, project, source, evidence
    )
    enabled, provider, model, reason = _enabled(target_kind, question_id, target_payload)
    if not enabled:
        return {
            "status": "FOLLOW_ON_BLOCKED",
            "route": route,
            "reason": reason,
            "policy_id": reference["policy_id"],
        }
    cost = _cost_bound(provider, target_kind, target_payload)
    allowed, reason = _dispatch_policy(
        target_kind, question_id, provider, model, target_payload, cost
    )
    if not allowed:
        return {
            "status": "FOLLOW_ON_BLOCKED",
            "route": route,
            "reason": reason,
            "policy_id": reference["policy_id"],
        }
    job = enqueue_intelligence(
        session,
        need_id=need_id,
        task_type=target_kind,
        question_id=question_id,
        origin="bounded_route",
    )
    if job.status != "queued":
        return {
            "status": "FOLLOW_ON_ALREADY_ACTIVE",
            "route": route,
            "job_id": str(job.id),
            "policy_id": reference["policy_id"],
        }
    follow_on = json.loads(job.checkpoint or "{}")
    follow_on["routing_priority"] = {
        "rank": 1 if route == "FAST_EXTRACT" else 2,
        "route": route,
        "policy_id": reference["policy_id"],
        "evaluated": True,
        "authorized": True,
        "evaluation_job_id": checkpoint.get("job_id"),
        "evaluation_call_id": checkpoint.get("logical_call_id"),
        "request_digest": checkpoint.get("request_digest"),
    }
    job.checkpoint = json.dumps(follow_on, separators=(",", ":"))
    return {
        "status": "ROUTED_JOB_ENQUEUED",
        "route": route,
        "job_id": str(job.id),
        "task_type": target_kind,
        "question_id": question_id,
        "policy_id": reference["policy_id"],
    }


def process_intelligence_job(job_id: UUID, worker_id: str, fence_token: int) -> dict[str, Any]:
    input_tokens: int | None = None
    output_tokens: int | None = None
    input_token_upper_bound: int | None = None
    provider_response_id: str | None = None
    provider_response_complete = False
    billing_quarantined = False
    error: str | None = None
    validation_reason: str | None = None
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
            current = _bound_grounded_payload(
                _request_payload(
                    session,
                    task_type,
                    checkpoint.get("question_id"),
                    need,
                    project,
                    source,
                    evidence,
                    UUID(checkpoint["package_id"]) if checkpoint.get("package_id") else None,
                )
            )
            watch_context = _watch_context(session, job.target_id, checkpoint.get("origin", ""))
            if watch_context is not None:
                current["watch_context"] = watch_context
                current = _bound_grounded_payload(current)
            if _digest(current) != checkpoint.get("request_digest"):
                checkpoint.update(status="stale", error="INPUT_CHANGED_BEFORE_DISPATCH")
                checkpoint.update(
                    validation_outcome="BLOCKED", validation_reason="INPUT_CHANGED_BEFORE_DISPATCH"
                )
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                _record_research_receipt(session, checkpoint)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                return {"status": "stale", "job_id": str(job_id)}
            enabled, provider, model, reason = _enabled(
                task_type, checkpoint.get("question_id"), payload
            )
            if not enabled:
                checkpoint.update(status="blocked", error=reason)
                checkpoint.update(validation_outcome="BLOCKED", validation_reason=reason)
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
                    "reference_type": "configured_policy_id",
                }
                checkpoint["routing_approval"] = routing_approval
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
            billing_policy = _billing_policy_identity(provider, model, task_type)
            context_digest = _digest(
                {
                    "payload": payload,
                    "routing_approval": routing_approval,
                    "billing_policy": billing_policy,
                }
            )
            max_cost = _cost_bound(provider, task_type, payload)
            unlimited = _owner_unlimited_allowed(provider, task_type)
            if settings.intelligence_financial_budget_mode == "owner_unlimited" and not unlimited:
                budget_error = "UNLIMITED_CONTRACT_NOT_AUTHORIZED"
            elif settings.intelligence_max_active_calls <= 0:
                budget_error = "ACTIVE_CALL_CAP_REQUIRED"
            elif not unlimited and (
                max_cost <= 0
                or settings.intelligence_max_call_usd <= 0
                or max_cost > settings.intelligence_max_call_usd
            ):
                budget_error = "FINITE_BUDGET_REQUIRED"
            else:
                budget_error = ""
            if budget_error:
                checkpoint.update(status="blocked", error=budget_error)
                checkpoint.update(validation_outcome="BLOCKED", validation_reason=budget_error)
                job.checkpoint = json.dumps(checkpoint, separators=(",", ":"))
                _record_research_receipt(session, checkpoint)
                job.status, job.lease_owner, job.lease_until = "succeeded", None, None
                return {
                    "status": "blocked",
                    "error": budget_error,
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
                "estimated_cost_usd": None if unlimited else max_cost,
                "max_cost_usd": None if unlimited else max_cost,
                "financial_budget_mode": settings.intelligence_financial_budget_mode,
                "financial_authorization_ref": settings.intelligence_financial_authorization_ref
                if unlimited
                else None,
                "unlimited_contracts": settings.intelligence_unlimited_contracts,
                "unlimited_providers": settings.intelligence_unlimited_providers,
                "caps": _caps(),
                "max_active": settings.intelligence_max_active_calls,
                "fence_token": fence_token,
            }
        except (ValueError, KeyError, TypeError) as exc:
            checkpoint = locals().get("checkpoint", {})
            checkpoint.update(status="blocked", error=type(exc).__name__)
            checkpoint.update(validation_outcome="BLOCKED", validation_reason=type(exc).__name__)
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
            checkpoint.update(
                validation_outcome="BLOCKED", validation_reason=reservation.blocked_reason
            )
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
            validation_outcome = (
                result.get("validation_outcome", "UNKNOWN")
                if isinstance(result, dict)
                else "UNKNOWN"
            )
            checkpoint.update(
                status="completed",
                result=result,
                logical_call_id=str(call_id),
                cached=True,
                validation_outcome=validation_outcome,
                validation_reason=result.get("validation_reason")
                if isinstance(result, dict)
                else None,
                provider_response_id=result.get("provider_response_id")
                if isinstance(result, dict)
                else None,
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
        None if unlimited else max_cost,
        billing_policy,
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
            checkpoint.update(
                validation_outcome="BLOCKED",
                validation_reason=dispatch_reason or dispatched.blocked_reason,
            )
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
            provider_response_id = _provider_response_id(data)
            usage_value = data.get("usage")
            response_usage = usage_value if isinstance(usage_value, dict) else {}
            actual_model = data.get("model")
            input_tokens = response_usage.get("input_tokens")
            output_tokens = response_usage.get("output_tokens")
            quarantine_reason = None
            if actual_model != model:
                quarantine_reason = "MODEL_IDENTITY_MISMATCH"
            elif not _valid_reported_tokens(input_tokens) or not _valid_reported_tokens(
                output_tokens
            ):
                quarantine_reason = "INVALID_REPORTED_USAGE"
            elif (
                input_tokens is not None
                and (billing_policy or {}).get("policy_id") != TYPESAFE_UNLIMITED_BILLING_POLICY_ID
                and input_tokens > settings.intelligence_typesafe_max_total_billable_input_tokens
            ):
                quarantine_reason = "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED"
            elif _provider_audit_exceeds_bound(data):
                quarantine_reason = "RESPONSE_TOO_LARGE"
            if quarantine_reason:
                safe_data = _safe_provider_audit(data)
                safe_usage = _safe_provider_audit(response_usage)
                exposure, exposure_status = (None, "UNKNOWN")
                exposure_basis = None
                if (
                    type(input_tokens) is int
                    and input_tokens >= 0
                    and actual_model == model
                    and quarantine_reason == "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED"
                ):
                    exposure, exposure_status = _bounded_cost_exposure(
                        provider, task_type, input_tokens, 0
                    )
                    exposure_basis = "reported_same_model_input_tokens_at_pinned_input_rate"
                with SessionLocal() as session:
                    quarantined = quarantine_call(
                        session,
                        call_id,
                        fence_token=fence_token,
                        expected_model=model,
                        actual_model=actual_model,
                        reason=quarantine_reason,
                        response_payload=safe_data,
                        input_tokens=input_tokens if _valid_reported_tokens(input_tokens) else None,
                        output_tokens=output_tokens
                        if _valid_reported_tokens(output_tokens)
                        else None,
                        conservative_exposure_usd=exposure,
                        exposure_basis=exposure_basis,
                        exposure_status=exposure_status,
                    )
                billing_quarantined = True
                status = "unknown"
                error = quarantined.blocked_reason or quarantine_reason
                validation_reason = quarantine_reason
                call_result = {
                    "provider": provider,
                    "actual_model": actual_model,
                    "usage": safe_usage,
                    "billing_quarantine": quarantine_reason,
                }
            else:
                parsed, actual_model, input_tokens, output_tokens = _type_safe_result(
                    data, task_type, payload
                )
        else:
            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            output_limit = (
                COMMERCIAL_ASSESSMENT_OUTPUT_TOKENS
                if task_type == COMMERCIAL_ASSESSMENT_TASK
                else settings.intelligence_openai_fast_max_output_tokens
                if task_type == "GROUNDED_EXTRACTION"
                else settings.intelligence_openai_reasoning_max_output_tokens
            )
            if task_type == COMMERCIAL_ASSESSMENT_TASK:
                request = commercial_assessment_request_payload(
                    model=model, input_payload=payload, schema=ASSESSMENT_SCHEMA
                )
                input_token_upper_bound = _serialized_request_bytes(request)
                data = call_openai_request(
                    api_key=key,
                    request=request,
                )
            else:
                data = call_openai(
                    api_key=key,
                    model=model,
                    instructions=GROUNDED_INSTRUCTIONS,
                    input_payload=payload,
                    max_output_tokens=output_limit,
                )
            provider_response_complete = True
            provider_response_id = _provider_response_id(data)
            response_model = data.get("model")
            input_tokens, output_tokens = data.get("input_tokens"), data.get("output_tokens")
            actual_model = response_model
            actual_service_tier = data.get("service_tier")
            quarantine_reason = None
            if actual_model != model:
                quarantine_reason = "MODEL_IDENTITY_MISMATCH"
            elif task_type == COMMERCIAL_ASSESSMENT_TASK and actual_service_tier != "default":
                quarantine_reason = "SERVICE_TIER_MISMATCH"
            elif task_type == COMMERCIAL_ASSESSMENT_TASK and (
                type(input_tokens) is not int or type(output_tokens) is not int
            ):
                quarantine_reason = "MISSING_REPORTED_USAGE"
            elif not _valid_reported_tokens(input_tokens) or not _valid_reported_tokens(
                output_tokens
            ):
                quarantine_reason = "INVALID_REPORTED_USAGE"
            elif (
                task_type == COMMERCIAL_ASSESSMENT_TASK
                and input_token_upper_bound is not None
                and input_tokens is not None
                and input_tokens > input_token_upper_bound
            ):
                quarantine_reason = "ENFORCED_INPUT_BOUND_EXCEEDED"
            elif output_tokens is not None and output_tokens > output_limit:
                quarantine_reason = "ENFORCED_OUTPUT_BOUND_EXCEEDED"
            elif _provider_audit_exceeds_bound(data):
                quarantine_reason = "RESPONSE_TOO_LARGE"
            if quarantine_reason:
                safe_data = _safe_provider_audit(data)
                exposure, exposure_status = (None, "UNKNOWN")
                exposure_basis = None
                if (
                    actual_model == model
                    and not (
                        task_type == COMMERCIAL_ASSESSMENT_TASK and actual_service_tier != "default"
                    )
                    and _valid_reported_tokens(input_tokens)
                    and _valid_reported_tokens(output_tokens)
                    and input_tokens is not None
                    and output_tokens is not None
                ):
                    exposure, exposure_status = _bounded_cost_exposure(
                        provider, task_type, input_tokens, output_tokens
                    )
                    exposure_basis = "reported_same_model_usage_at_pinned_rates"
                with SessionLocal() as session:
                    quarantined = quarantine_call(
                        session,
                        call_id,
                        fence_token=fence_token,
                        expected_model=model,
                        actual_model=actual_model,
                        reason=quarantine_reason,
                        response_payload=safe_data,
                        input_tokens=input_tokens if _valid_reported_tokens(input_tokens) else None,
                        output_tokens=output_tokens
                        if _valid_reported_tokens(output_tokens)
                        else None,
                        conservative_exposure_usd=exposure,
                        exposure_basis=(exposure_basis),
                        exposure_status=exposure_status,
                    )
                billing_quarantined = True
                status = "unknown"
                error = quarantined.blocked_reason or quarantine_reason
                validation_reason = quarantine_reason
                call_result = {
                    "provider": provider,
                    "actual_model": actual_model,
                    "service_tier": actual_service_tier or "UNKNOWN",
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                    "billing_quarantine": quarantine_reason,
                }
        if not billing_quarantined:
            if provider == "openai" and task_type == COMMERCIAL_ASSESSMENT_TASK:
                package_context = payload["package"]
                package_for_validation = {
                    **package_context,
                    "processing_status": package_context["processing_status"],
                    "project_id": payload["project"]["project_id"],
                    "need_id": payload["need"]["need_id"],
                }
                parsed = validate_assessment(
                    data["output"],
                    package=package_for_validation,
                    need_id=payload["need"]["need_id"],
                    project_id=payload["project"]["project_id"],
                    current_need=payload["need"],
                )
            elif provider == "openai":
                parsed = validate_grounded_candidates(data["output"], payload["evidence"])
            call_result = {
                **parsed,
                "provider": provider,
                "actual_model": actual_model,
                "latency_ms": data.get("latency_ms", data.get("provider_latency_ms")),
                "service_tier": data.get("service_tier", "UNKNOWN"),
                "reported_usage": data.get("reported_usage"),
                "validation_outcome": "VALIDATED",
            }
            if provider_response_id:
                call_result["provider_response_id"] = provider_response_id
            estimated_cost = _estimated_cost_from_usage(
                provider, task_type, input_tokens, output_tokens
            )
            call_result["usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "actual_cost_usd": None,
                "estimated_cost_usd": str(estimated_cost) if estimated_cost is not None else None,
                "cost_basis": (
                    "conservative_usage_estimate_not_invoice"
                    if task_type == COMMERCIAL_ASSESSMENT_TASK
                    else "derived_from_verified_usage_and_pinned_rates"
                    if estimated_cost is not None
                    else None
                ),
            }
            result_digest = _digest(call_result)
            if task_type != COMMERCIAL_ASSESSMENT_TASK:
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
        provider_request_id = getattr(exc, "request_id", None)
        error_quarantine = _provider_error_quarantine_details(
            exc,
            provider=provider,
            task_type=task_type,
            expected_model=model,
            input_token_limit=input_token_upper_bound,
        )
        if error_quarantine is not None:
            actual_model = error_quarantine["actual_model"]
            input_tokens = error_quarantine["input_tokens"]
            output_tokens = error_quarantine["output_tokens"]
            quarantine_reason = error_quarantine["reason"]
            with SessionLocal() as session:
                quarantined = quarantine_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    expected_model=model,
                    actual_model=actual_model,
                    reason=quarantine_reason,
                    response_payload=error_quarantine["response_payload"],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    conservative_exposure_usd=error_quarantine["conservative_exposure_usd"],
                    exposure_basis=error_quarantine["exposure_basis"],
                    exposure_status=error_quarantine["exposure_status"],
                )
            billing_quarantined = True
            status = "unknown"
            error = quarantined.blocked_reason or quarantine_reason
            validation_reason = quarantine_reason
            call_result = {
                "provider": provider,
                "actual_model": actual_model,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "billing_quarantine": quarantine_reason,
            }
        response_identity = provider_response_id or provider_request_id
        response_ref = f"response:{response_identity}" if response_identity else None
        terminal_failure = False
        if (
            not billing_quarantined
            and response_ref
            and (getattr(exc, "conclusive", False) or provider_response_complete)
        ):
            with SessionLocal() as session:
                failure = fail_call(
                    session,
                    call_id,
                    fence_token=fence_token,
                    blocked_reason=type(exc).__name__,
                    conclusive_response_ref=response_ref,
                )
                terminal_failure = failure.status == "FAILED"
        if not billing_quarantined:
            status = "failed" if terminal_failure else "unknown"
            error, call_result = type(exc).__name__, None
            validation_reason = error

    if status == "completed" and task_type == COMMERCIAL_ASSESSMENT_TASK:
        if (
            not isinstance(call_result, dict)
            or type(input_tokens) is not int
            or type(output_tokens) is not int
        ):
            raise RuntimeError("M4 validated response is missing its result or reported usage")
        return _publish_commercial_assessment_result(
            job_id=job_id,
            worker_id=worker_id,
            fence_token=fence_token,
            call_id=call_id,
            call_result=call_result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_response_id=provider_response_id,
        )

    with SessionLocal.begin() as session:
        job = assert_fence(session, job_id, worker_id, fence_token)
        checkpoint = json.loads(job.checkpoint or "{}")
        fresh = False
        if status == "completed" and job.target_id is not None:
            try:
                fresh = _digest(
                    _current_payload(session, checkpoint, job.target_id)
                ) == checkpoint.get("request_digest")
            except (ValueError, KeyError, TypeError):
                fresh = False
        if status == "completed" and not fresh:
            checkpoint.update(
                status="stale",
                result=call_result,
                result_status="stale_context",
                error="INPUT_CHANGED_DURING_PROVIDER_CALL",
                validation_outcome=(
                    "STALE_CONTEXT" if task_type == COMMERCIAL_ASSESSMENT_TASK else "VALIDATED"
                ),
                validation_reason=(
                    "INPUT_CHANGED_DURING_PROVIDER_CALL"
                    if task_type == COMMERCIAL_ASSESSMENT_TASK
                    else None
                ),
                provider_response_id=provider_response_id,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "actual_cost_usd": None,
                    "estimated_cost_usd": call_result.get("usage", {}).get("estimated_cost_usd")
                    if call_result
                    else None,
                    "cost_basis": call_result.get("usage", {}).get("cost_basis")
                    if call_result
                    else None,
                },
            )
            try:
                reassessment_id = (
                    _queue_stale_reassessment(session, checkpoint, job.target_id)
                    if job.target_id is not None
                    else None
                )
            except (ValueError, KeyError, TypeError):
                reassessment_id = None
            if reassessment_id:
                checkpoint["reassessment_job_id"] = reassessment_id
            checkpoint["completed_at"] = datetime.now(UTC).isoformat()
            job.checkpoint = json.dumps(checkpoint, separators=(",", ":"), default=str)
            _record_research_receipt(session, checkpoint)
            job.status, job.lease_owner, job.lease_until = "succeeded", None, None
            return {
                "status": "stale",
                "result": call_result,
                "error": "INPUT_CHANGED_DURING_PROVIDER_CALL",
                "job_id": str(job_id),
            }
        routing_effect = (
            _apply_bounded_routing_effect(
                session,
                checkpoint=checkpoint,
                result=call_result,
                need_id=job.target_id,
            )
            if status == "completed" and fresh and job.target_id is not None and call_result
            else None
        )
        validation_outcome = (
            "QUARANTINED"
            if billing_quarantined
            else "VALIDATED"
            if status == "completed"
            else "REJECTED"
            if status == "failed"
            else "UNKNOWN"
        )
        if isinstance(call_result, dict):
            call_result.setdefault("validation_outcome", validation_outcome)
            if validation_reason:
                call_result.setdefault("validation_reason", validation_reason)
            if provider_response_id:
                call_result.setdefault("provider_response_id", provider_response_id)
        checkpoint.update(
            status=status,
            completed_at=datetime.now(UTC).isoformat(),
            result=call_result,
            error=error,
            validation_outcome=validation_outcome,
            validation_reason=validation_reason or (error if status != "completed" else None),
            provider_response_id=provider_response_id,
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
        if routing_effect is not None:
            checkpoint["routing_effect"] = routing_effect
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
            "validation_outcome": checkpoint.get("validation_outcome", "UNKNOWN"),
            "validation_reason": checkpoint.get("validation_reason"),
            "provider_response_id": checkpoint.get("provider_response_id"),
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
                "validation_outcome": checkpoint.get("validation_outcome", "UNKNOWN"),
                "validation_reason": checkpoint.get("validation_reason"),
                "provider_response_id": checkpoint.get("provider_response_id"),
                "result_status": checkpoint.get("result_status"),
                "error": checkpoint.get("error"),
                "reassessment_job_id": checkpoint.get("reassessment_job_id"),
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
