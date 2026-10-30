"""Source-bound power demand records, using the existing immutable package store.

This is a deterministic equipment contract, not a provider research package. Reads
recompute its claims against current admitted evidence before publishing anything.
No utility shortage, model call, manual review, or qualification promotion is needed.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import String, and_, case, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert

from gridlens.domain.equipment_claims import validate_equipment_claim
from gridlens.domain.equipment_demand import MODEL_ID, MODEL_VERSION, calculate_equipment_demand
from gridlens.domain.equipment_evidence import EvidenceContext, EvidenceReference
from gridlens.domain.ferc_equipment_interpretation import (
    EVALUATOR_VERSION as FERC_EVALUATOR_VERSION,
)
from gridlens.domain.ferc_equipment_interpretation import (
    source_docket_context,
    source_project_activities,
)
from gridlens.domain.signal_admission import admitted_from_source
from gridlens.ingestion.parsers.equipment import VERSION, extract_equipment_claims
from gridlens.ingestion.parsers.ferc_equipment import (
    VERSION as FERC_EXTRACTOR_VERSION,
)
from gridlens.ingestion.parsers.ferc_equipment import (
    extract_ferc_equipment,
)
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)

CONTRACT = "equipment-demand-v1"
MAX_DOCUMENTS = 32
BINDING_VERSION = 1
FERC_SOURCE_ID = "federal-register-eis"


def _is_native_ferc(source, interpretation) -> bool:
    assessment = interpretation.assessment or {}
    return bool(
        source.id == FERC_SOURCE_ID
        and interpretation.evaluator_version == FERC_EVALUATOR_VERSION
        and isinstance(assessment.get("native_equipment"), dict)
    )


def _extractor_version(source, interpretation) -> str:
    if _is_native_ferc(source, interpretation):
        return FERC_EXTRACTOR_VERSION
    return VERSION


def _json(value: Any) -> Any:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_json(v) for v in value]
    return value


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _name(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _binding_snapshot(project, source, interpretation) -> dict:
    assessment = interpretation.assessment or {}
    snapshot = {
        "version": BINDING_VERSION,
        "project": {
            "identity_key": project.identity_key,
            "name": project.name,
            "location": project.location,
        },
        "source": {"family": source.family, "retrieval_method": source.retrieval_method},
        "attribution": {
            "subject": assessment.get("subject"),
            "project_hint": assessment.get("project_hint"),
        },
    }
    if _is_native_ferc(source, interpretation):
        snapshot.update(
            evaluator_version=interpretation.evaluator_version,
            native_equipment=assessment.get("native_equipment"),
        )
    return snapshot


def _canonical_decimal(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    if not number.is_finite():
        return str(value)
    sign, raw_digits, exponent = number.as_tuple()
    if not isinstance(exponent, int):
        return str(value)
    digits = list(raw_digits)
    if not digits or not any(digits):
        return "0"
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return format(Decimal((sign, tuple(digits), exponent)), "f")


def _engineering_signature(record: dict) -> str:
    equipment = []
    for claim in record["equipment"]:
        normalized = {
            key: value
            for key, value in claim.items()
            if key not in {"source_id", "quote", "start", "end"}
        }
        normalized["equipment_id"] = _name(normalized.get("equipment_id"))
        for key in ("rating", "efficiency", "power_factor", "duty_fraction", "period_hours"):
            normalized[key] = _canonical_decimal(normalized.get(key))
        equipment.append(normalized)
    unique_equipment = {_digest(claim): claim for claim in equipment}
    return _digest(
        {
            "company": _name(record["company"]),
            "facility": _name(record["facility"]),
            "equipment": [unique_equipment[key] for key in sorted(unique_equipment)],
            "status": record["status"],
            "as_of": record["as_of"],
            "quantities": {
                key: _canonical_decimal(value)
                for key, value in (record["demand"] or {}).items()
                if key not in {"inputs", "input_hashes", "items"}
            },
        }
    )


def _eligible(need, project, observation, evidence, interpretation, source) -> bool:
    assessment = interpretation.assessment or {}
    ref = assessment.get("evidence") or {}
    return bool(
        need.active
        and project.region_status == "ELIGIBLE"
        and need.project_id == project.id
        and evidence.observation_id == observation.id
        and interpretation.observation_id == observation.id
        and observation.source_id == source.id
        and interpretation.status == "accepted"
        and interpretation.content_hash == observation.content_hash
        and assessment.get("semantic_hash") == observation.content_hash
        and assessment.get("evidence_hash") == evidence.content_hash
        and isinstance(ref, dict)
        and ref.get("id") == str(evidence.id)
        and assessment.get("project_identity_key") == project.identity_key
        and assessment.get("power_activity", assessment.get("activity_key")) == need.activity_key
        and (
            source.id != FERC_SOURCE_ID
            or (
                interpretation.evaluator_version == FERC_EVALUATOR_VERSION
                and assessment.get("source_document_number") == observation.external_id
                and ref.get("url") == evidence.url
            )
        )
        and admitted_from_source(source, assessment, evidence).admitted
    )


def _input_key(need, project, observation, evidence, source, interpretation) -> str:
    """Frozen interpretation inputs: replay does not parse or calculate twice."""
    assessment = interpretation.assessment or {}
    values: dict[str, Any] = {
        "versions": [CONTRACT, VERSION, MODEL_ID, MODEL_VERSION, BINDING_VERSION],
        "need": [need.id, need.activity_key],
        "project": [project.id, project.identity_key, project.name, project.location],
        "observation": [observation.id, observation.external_id, observation.content_hash],
        "source": [source.id, source.family, source.retrieval_method],
        "evidence": [
            evidence.id,
            evidence.content_hash,
            evidence.title,
            evidence.abstract,
            evidence.url,
            evidence.published_at,
            evidence.event_date,
            evidence.observed_at,
            evidence.extraction_location,
        ],
        "attribution": [assessment.get("subject"), assessment.get("project_hint")],
    }
    if _is_native_ferc(source, interpretation):
        values["versions"] = [
            CONTRACT,
            FERC_EXTRACTOR_VERSION,
            interpretation.evaluator_version,
            MODEL_ID,
            MODEL_VERSION,
            BINDING_VERSION,
        ]
        values["native_equipment"] = assessment.get("native_equipment")
        values["evaluator_version"] = interpretation.evaluator_version
    return _digest(values)


def _ferc_extraction(need, project, observation, evidence, interpretation, source):
    """Validate the selected native station claims against the retained PDF and DB scope."""
    from gridlens.domain.equipment_demand import EquipmentClaim
    from gridlens.ingestion.parsers.equipment import ExtractionResult

    assessment = interpretation.assessment or {}
    native = assessment.get("native_equipment")
    text = evidence.abstract or ""
    result = extract_ferc_equipment(text, title=evidence.title)
    extracted = ExtractionResult()
    context_questions: list[str] = []
    extracted.as_of = evidence.published_at.isoformat() if evidence.published_at else None
    extracted.truncated = result.truncated
    extracted.issues = list(result.issues)
    extracted.has_schedule = bool(result.sites)
    if not isinstance(native, dict) or not isinstance(native.get("site_key"), str):
        extracted.issues.append("Current accepted FERC assessment lacks its physical-site binding.")
        return extracted, context_questions, [], result.extractor_version, None
    expected_project_key = f"{FERC_SOURCE_ID}:equipment-site:{native['site_key']}"
    if project.identity_key != expected_project_key and not (
        _name(project.name) == _name(assessment.get("project_hint"))
        and _name(project.location) == _name(assessment.get("location"))
    ):
        extracted.issues.append("FERC equipment site does not match the bound physical project.")
        return extracted, context_questions, [], result.extractor_version, None
    heading = native.get("heading")
    if not isinstance(heading, dict):
        extracted.issues.append("Current accepted FERC assessment lacks its source heading.")
        return extracted, context_questions, [], result.extractor_version, None
    matches = [
        site
        for site in result.sites
        if site.heading_quote == heading.get("quote")
        and site.heading_start == heading.get("start")
        and site.heading_end == heading.get("end")
    ]
    if len(matches) != 1:
        extracted.issues.append("Accepted FERC site heading is not unique in current PDF evidence.")
        return extracted, context_questions, [], result.extractor_version, None
    site = matches[0]
    if _name(site.facility) != _name(project.name):
        extracted.issues.append("FERC facility does not match the bound physical project name.")
    if _name(site.location) != _name(project.location):
        extracted.issues.append("FERC site location does not match the bound physical project.")
    if not evidence.url.startswith("https://www.govinfo.gov/content/pkg/FR-"):
        extracted.issues.append("FERC equipment evidence is not from the retained GovInfo PDF.")
    if not evidence.published_at:
        extracted.issues.append("Establish the historical Federal Register publication date.")
    if not evidence.observed_at:
        extracted.issues.append("Establish the PDF retrieval timestamp.")
    extracted.facility = site.facility
    extracted.company = None  # The title party is attribution context, not resolved identity.
    context_questions.extend(
        f"Source-party attribution remains unresolved: {issue}."
        for issue in result.attribution_issues
    )
    context_questions.extend(
        f"Unsupported station activity remains unresolved: {item.activity}."
        for item in site.unsupported_activities
    )
    docket = source_docket_context(result, text)
    project_activities = source_project_activities(result, text)
    if docket != native.get("docket_context"):
        context_questions.append(
            "Current FERC docket context does not match the admitted source binding."
        )
    if project_activities != native.get("project_activities", []):
        context_questions.append(
            "Current FERC project activity context does not match the admitted source binding."
        )
    if not isinstance(docket, dict) or docket.get("status") != "SOURCE_BOUND":
        context_questions.append("FERC docket identity remains unknown or conflicting.")
    if native.get("complete_site_schedule") is not True:
        context_questions.append(
            "The notice identifies equipment but does not provide a complete site schedule."
        )

    validated_candidates = []
    for native_claim in site.claims:
        if (
            native_claim.start < 0
            or native_claim.end <= native_claim.start
            or text[native_claim.start : native_claim.end] != native_claim.quote
        ):
            extracted.issues.append("Resolve FERC equipment source-span mismatch.")
            continue
        reference = EvidenceReference(
            source_id=source.id,
            observation_id=observation.id,
            evidence_id=evidence.id,
            evidence_hash=evidence.content_hash,
            source_url=evidence.url,
            observed_at=(
                evidence.observed_at.astimezone(UTC)
                if evidence.observed_at.tzinfo
                else evidence.observed_at
            ),
            retrieved_at=(
                evidence.observed_at.astimezone(UTC)
                if evidence.observed_at.tzinfo
                else evidence.observed_at
            ),
            published_at=evidence.published_at,
            extraction_location=evidence.extraction_location,
            extractor_version=result.extractor_version,
            quote=native_claim.quote,
        )
        rating = (
            {
                "value": str(native_claim.rating),
                "unit": native_claim.rating_unit,
                "basis": native_claim.rating_basis,
            }
            if native_claim.rating is not None and native_claim.rating_unit
            else None
        )
        candidate_id = uuid5(
            NAMESPACE_URL,
            f"gridlens:equipment-claim-v1:{evidence.id}:{native_claim.start}:{native_claim.end}",
        )
        candidate = validate_equipment_claim(
            {
                "schema_version": "equipment-claim-v1",
                "claim_id": candidate_id,
                "project_id": project.id,
                "need_id": need.id,
                "equipment_id": native_claim.source_equipment_id or native_claim.claim_key,
                "equipment_type": native_claim.equipment_type,
                "drive_type": native_claim.drive,
                "lifecycle_status": native_claim.lifecycle_status,
                "operating_role": native_claim.role,
                "count": native_claim.count,
                "rating": rating,
                "evidence": reference.model_dump(mode="python"),
                "verification_state": "UNVERIFIED",
                "claim_state": "reported",
            },
            context=EvidenceContext(
                project_id=project.id,
                need_id=need.id,
                reference=reference,
                source_text=text,
            ),
        )
        validated_candidates.append(candidate.model_dump(mode="json"))
        basis = {
            "unknown": "unknown",
            "mechanical_output": "mechanical_output",
            "electrical_input": "electrical_input",
        }[candidate.rating.basis if candidate.rating else "unknown"]
        converted = EquipmentClaim(
            equipment_id=native_claim.source_equipment_id or native_claim.claim_key,
            equipment_type=native_claim.equipment_type,
            drive=native_claim.drive,
            rating=Decimal(candidate.rating.value) if candidate.rating else None,
            unit=candidate.rating.unit if candidate.rating else "hp",
            rating_basis=basis,
            count=candidate.count,
            state=native_claim.lifecycle_status,
            role=native_claim.role,
            quote=native_claim.quote,
            source_id=str(evidence.id),
            start=native_claim.start,
            end=native_claim.end,
        )
        extracted.claims.append(converted)
    source_context = {
        "classification": "CONTEXT_ONLY_EXCEPT_SELECTED_SITE",
        "notice_kind": native.get("notice_kind"),
        "docket": docket,
        "project_activities": project_activities,
        "sites": [
            {
                "facility": current_site.facility,
                "location": current_site.location,
                "scope": (
                    "selected_equipment_demand_site"
                    if current_site.heading_quote == site.heading_quote
                    and current_site.heading_start == site.heading_start
                    and current_site.heading_end == site.heading_end
                    else "context_only_site"
                ),
                "heading": {
                    "quote": current_site.heading_quote,
                    "start": current_site.heading_start,
                    "end": current_site.heading_end,
                },
                "equipment_assertions": [
                    {
                        "equipment_type": claim.equipment_type,
                        "drive": claim.drive,
                        "lifecycle_status": claim.lifecycle_status,
                        "count": claim.count,
                        "rating": str(claim.rating) if claim.rating is not None else None,
                        "rating_unit": claim.rating_unit,
                        "rating_basis": claim.rating_basis,
                        "source_equipment_id": claim.source_equipment_id,
                        "equipment_id_basis": claim.id_basis,
                        "role": claim.role,
                        "quote": claim.quote,
                        "start": claim.start,
                        "end": claim.end,
                    }
                    for claim in current_site.claims
                ],
                "unsupported_activities": [
                    {
                        "activity": activity.activity,
                        "quote": activity.quote,
                        "start": activity.start,
                        "end": activity.end,
                        "scope": "context_only",
                    }
                    for activity in current_site.unsupported_activities
                ],
            }
            for current_site in result.sites
        ],
    }
    return (
        extracted,
        context_questions,
        validated_candidates,
        result.extractor_version,
        source_context,
    )


def _payload(need, project, observation, evidence, source, interpretation) -> dict | None:
    text = evidence.abstract or ""
    assessment = interpretation.assessment or {}
    native_ferc = (
        source.id == FERC_SOURCE_ID
        and interpretation.evaluator_version == FERC_EVALUATOR_VERSION
        and isinstance(assessment.get("native_equipment"), dict)
    )
    if native_ferc:
        (
            extracted,
            context_questions,
            validated_candidates,
            extractor_version,
            native_source_context,
        ) = _ferc_extraction(need, project, observation, evidence, interpretation, source)
    else:
        extracted = extract_equipment_claims(text)
        context_questions = []
        validated_candidates = []
        extractor_version = VERSION
        native_source_context = None
    # Equipment words in ordinary permit/research prose are not a parsed
    # schedule; structured but unparseable schedules remain abstained evidence.
    if not extracted.claims and not extracted.has_schedule:
        return None
    questions = list(extracted.issues)
    blocking_questions = list(extracted.issues)
    if not extracted.company:
        company_question = (
            "Establish source-party identity and the responsible commercial company."
            if native_ferc
            else "Establish the source-reported company for this equipment schedule."
        )
        if native_ferc:
            context_questions.append(company_question)
        else:
            questions.append(company_question)
            blocking_questions.append(company_question)
    facility_names = {_name(project.name)}
    # Official permit assessment retains the facility separately from its applicant.
    # This hint is accepted only inside the exact current project/activity binding.
    if source.family == "construction-permits" and assessment.get("project_hint"):
        facility_names.add(_name(assessment["project_hint"]))
    if not native_ferc and (
        not extracted.facility or _name(extracted.facility) not in facility_names
    ):
        question = "Resolve the equipment facility against the canonical physical project."
        questions.append(question)
        blocking_questions.append(question)
    if not native_ferc and (
        assessment.get("project_hint")
        and extracted.company
        and _name(extracted.company) != _name(assessment.get("subject"))
    ):
        question = "Resolve the source company against the accepted applicant attribution."
        questions.append(question)
        blocking_questions.append(question)
    source_date = evidence.published_at or evidence.event_date
    as_of = source_date
    if extracted.as_of:
        try:
            as_of = date.fromisoformat(extracted.as_of)
        except ValueError:
            question = "Resolve the invalid equipment schedule date."
            questions.append(question)
            blocking_questions.append(question)
    if not source_date or not as_of:
        question = "Establish a dated source for the equipment schedule."
        questions.append(question)
        blocking_questions.append(question)
    # Freeze validation against acquisition time; no wall clock in the package key.
    retrieved = (
        evidence.observed_at.astimezone(UTC).date()
        if evidence.observed_at and evidence.observed_at.tzinfo
        else evidence.observed_at.date()
        if evidence.observed_at
        else None
    )
    if retrieved and ((source_date and source_date > retrieved) or (as_of and as_of > retrieved)):
        question = "Resolve a schedule or publication date after source retrieval."
        questions.append(question)
        blocking_questions.append(question)
    if extracted.truncated:
        question = "Investigate the complete schedule; bounded extraction was incomplete."
        questions.append(question)
        blocking_questions.append(question)
    for claim in extracted.claims:
        if claim.start is None or claim.end is None or text[claim.start : claim.end] != claim.quote:
            questions.append("Resolve equipment claim source-span mismatch.")
            blocking_questions.append("Resolve equipment claim source-span mismatch.")
    claims = [replace(c, source_id=str(evidence.id)) for c in extracted.claims]
    calculated = calculate_equipment_demand(claims, as_of=as_of)
    status = (
        "ABSTAINED"
        if blocking_questions or not claims
        else (
            "SUPPORTED"
            if all(i.status == "known" for i in calculated.items) and not calculated.unresolved
            else "PARTIAL"
        )
    )
    if any(i.status == "conflicted" for i in calculated.items):
        status = "ABSTAINED"
        questions.append("Investigate contradictory specifications for the same equipment.")
    if status == "PARTIAL":
        questions.extend(calculated.unresolved)
        questions.append(
            "Investigate missing ratings, efficiency, count, drive or operating configuration."
        )
    questions.extend(context_questions)
    if native_ferc and context_questions and status == "SUPPORTED":
        status = "PARTIAL"
    demand = None if status == "ABSTAINED" else _json(asdict(calculated))
    electric = [c for c in claims if c.drive == "electric"]
    new = [c for c in electric if c.state in {"new", "proposed"}]
    category = "CALCULATED" if demand and calculated.coincident_kw is not None else "UNKNOWN"
    payload: dict[str, Any] = {
        "schema_version": CONTRACT,
        "binding": _binding_snapshot(project, source, interpretation),
        "input_fingerprint": _input_key(
            need, project, observation, evidence, source, interpretation
        ),
        "record_id": _digest([str(need.id), str(project.id), CONTRACT]),
        "need_id": str(need.id),
        "project_id": str(project.id),
        # A source header establishes attribution, not a verified buyer or corporate identity.
        "company_id": None,
        "company": extracted.company,
        "company_basis": "UNKNOWN" if native_ferc else "DOCUMENTED",
        "facility_id": str(project.id),
        "facility": extracted.facility,
        "location": project.location,
        "scope": "identified_equipment_assertion" if native_ferc else "equipment_schedule",
        "demand_category": "electric_compression_and_pumping",
        "classification": category,
        "status": status,
        "demand": demand,
        "equipment": _json([asdict(c) for c in claims]),
        "lifecycle": sorted({c.state for c in claims}),
        "expected_start": sorted(
            {c.effective_from.isoformat() for c in claims if c.effective_from}
        ),
        "requirement_type": "UNKNOWN",
        "as_of": _json(as_of),
        "last_verified_at": None if native_ferc else _json(evidence.observed_at),
        "model": {"id": MODEL_ID, "version": MODEL_VERSION},
        "extractor_version": extractor_version,
        "assumptions": [],
        "claim_classes": {
            "company": "DOCUMENTED" if extracted.company else "UNKNOWN",
            "equipment_inputs": "DOCUMENTED",
            "demand": category,
            "expected_start": "DOCUMENTED" if any(c.effective_from for c in claims) else "UNKNOWN",
            "decision_maker": "UNKNOWN",
        },
        "quantity_classification": {
            field: "CALCULATED" if demand and demand.get(field) is not None else "UNKNOWN"
            for field in ("connected_kw", "coincident_kw", "incremental_kw", "energy_mwh")
        },
        "confidence": "UNCALIBRATED",
        "verification": {
            "source_authority": source.family,
            "retrieval_method": source.retrieval_method,
            "method": "source-span, schema, entity, unit, date, duplicate and arithmetic checks",
        },
        "commercial_relevance": "EMERGING_DEMAND"
        if new and status != "ABSTAINED"
        else "INVESTIGATION",
        "decision_maker": None,
        "supply_constraint_evidence": [],
        "residual_gap_kw": None,
        "unresolved_questions": questions
        + ["Identify the equipment procurement decision-maker and purchase timing."],
        "next_action": (
            "Investigate source-backed equipment procurement timing and the responsible buyer."
            if status != "ABSTAINED"
            else "Investigate unresolved source and equipment claims before numerical publication."
        ),
        "evidence": [
            {
                "evidence_id": str(evidence.id),
                "source_id": source.id,
                "content_hash": evidence.content_hash,
                "semantic_hash": observation.content_hash,
                "document_id": observation.external_id,
                "title": evidence.title,
                "url": evidence.url,
                "published_at": _json(evidence.published_at),
                "retrieved_at": _json(evidence.observed_at),
                "extraction_location": evidence.extraction_location,
                "metadata_claims": [
                    {
                        "classification": "DOCUMENTED",
                        "quote": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                    }
                    for match in re.finditer(
                        r"^(?:Company|Facility|As of):[^\r\n]*", text, re.M | re.I
                    )
                ],
                "claims": [{"quote": c.quote, "start": c.start, "end": c.end} for c in claims],
            }
        ],
        "aggregation_policy": "Equipment scope only; never sum with facility demand or infer gaps.",
    }
    if native_ferc:
        payload.update(
            equipment_identity=[
                {
                    "equipment_id": claim.equipment_id,
                    "equipment_id_basis": "internal_derived_semantic_key",
                    "source_equipment_id": None,
                }
                for claim in claims
            ],
            native_site_assertion={
                "notice_kind": assessment.get("native_equipment", {}).get("notice_kind"),
                "docket": assessment.get("native_equipment", {}).get("docket_context"),
                "project_activities": assessment.get("native_equipment", {}).get(
                    "project_activities", []
                ),
                "scope": assessment.get("native_equipment", {}).get("scope"),
                "site_key": assessment.get("native_equipment", {}).get("site_key"),
                "facility": extracted.facility,
                "location": project.location,
                "heading": assessment.get("native_equipment", {}).get("heading"),
                "company_attribution": assessment.get("native_equipment", {}).get(
                    "company_attribution"
                ),
                "body_applicant_attribution": assessment.get("native_equipment", {}).get(
                    "body_applicant_attribution"
                ),
                "company_identity": "UNKNOWN",
                "current_status": "UNKNOWN",
                "complete_site_schedule": assessment.get("native_equipment", {}).get(
                    "complete_site_schedule"
                ),
            },
            native_source_context=native_source_context,
            claim_candidates=validated_candidates,
        )
    return payload


def materialize_equipment_investigation(
    session,
    need,
    project,
    observation,
    evidence,
    interpretation,
    source,
) -> EvidencePackage | None:
    """Insert one immutable receipt per frozen input; caller owns transaction/fencing."""
    if not _eligible(need, project, observation, evidence, interpretation, source):
        return None
    if not session.scalar(
        select(NeedObservation.need_id).where(
            NeedObservation.need_id == need.id,
            NeedObservation.observation_id == observation.id,
        )
    ):
        return None
    key = _input_key(need, project, observation, evidence, source, interpretation)
    existing = session.scalar(select(EvidencePackage).where(EvidencePackage.package_key == key))
    if existing is not None:
        return existing
    payload = _payload(need, project, observation, evidence, source, interpretation)
    if payload is None:
        return None
    session.execute(
        insert(EvidencePackage)
        .values(
            id=uuid4(),
            package_key=key,
            schema_version=CONTRACT,
            evidence_id=evidence.id,
            observation_id=observation.id,
            project_id=project.id,
            need_id=need.id,
            evidence_hash=evidence.content_hash,
            extractor_version=payload["extractor_version"],
            question_contract=CONTRACT,
            provider="deterministic",
            model=f"{MODEL_ID}:{MODEL_VERSION}",
            processing_status="BLOCKED"
            if payload["status"] == "ABSTAINED"
            else "COMPLETE_ADVISORY",
            payload=payload,
            logical_call_id=None,
        )
        .on_conflict_do_nothing(index_elements=["package_key"])
    )
    return session.scalar(select(EvidencePackage).where(EvidencePackage.package_key == key))


def current_equipment_investigations(session, pairs: list[tuple]) -> dict[str, dict]:
    """Bounded bulk read with current source binding and deterministic payload validation.

    Multiple documents are deliberately not added: they may be overlapping schedules.
    Identical engineering inputs deduplicate; other overlap remains an investigation.
    """
    if not pairs:
        return {}
    if len(pairs) > 50:
        raise ValueError("Equipment demand batch exceeds 50 needs")
    wanted = {(str(n), str(p)) for n, p in pairs}
    ids = [UUID(str(n)) for n, _ in pairs]
    pair_filter = or_(
        *(
            and_(
                EvidencePackage.need_id == UUID(str(need_id)),
                EvidencePackage.project_id == UUID(str(project_id)),
            )
            for need_id, project_id in wanted
        )
    )
    native_sql_binding = and_(
        Source.id == FERC_SOURCE_ID,
        Interpretation.evaluator_version == FERC_EVALUATOR_VERSION,
        func.jsonb_extract_path_text(
            Interpretation.assessment, "native_equipment", "site_key"
        ).is_not(None),
    )
    legacy_snapshot = func.jsonb_build_object(
        "version",
        BINDING_VERSION,
        "project",
        func.jsonb_build_object(
            "identity_key",
            Project.identity_key,
            "name",
            Project.name,
            "location",
            Project.location,
        ),
        "source",
        func.jsonb_build_object(
            "family",
            Source.family,
            "retrieval_method",
            Source.retrieval_method,
        ),
        "attribution",
        func.jsonb_build_object(
            "subject",
            Interpretation.assessment["subject"],
            "project_hint",
            Interpretation.assessment["project_hint"],
        ),
    )
    current_snapshot = case(
        (
            native_sql_binding,
            func.jsonb_build_object(
                "version",
                BINDING_VERSION,
                "project",
                func.jsonb_build_object(
                    "identity_key",
                    Project.identity_key,
                    "name",
                    Project.name,
                    "location",
                    Project.location,
                ),
                "source",
                func.jsonb_build_object(
                    "family",
                    Source.family,
                    "retrieval_method",
                    Source.retrieval_method,
                ),
                "attribution",
                func.jsonb_build_object(
                    "subject",
                    Interpretation.assessment["subject"],
                    "project_hint",
                    Interpretation.assessment["project_hint"],
                ),
                "evaluator_version",
                Interpretation.evaluator_version,
                "native_equipment",
                Interpretation.assessment["native_equipment"],
            ),
        ),
        else_=legacy_snapshot,
    )
    ranked = (
        select(
            EvidencePackage.id,
            func.row_number()
            .over(
                partition_by=EvidencePackage.need_id,
                order_by=(EvidencePackage.created_at.desc(), EvidencePackage.id.desc()),
            )
            .label("position"),
        )
        .join(PowerNeed, PowerNeed.id == EvidencePackage.need_id)
        .join(Project, Project.id == EvidencePackage.project_id)
        .join(Observation, Observation.id == EvidencePackage.observation_id)
        .join(Evidence, Evidence.id == EvidencePackage.evidence_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .join(
            NeedObservation,
            and_(
                NeedObservation.need_id == PowerNeed.id,
                NeedObservation.observation_id == Observation.id,
            ),
        )
        .where(
            pair_filter,
            EvidencePackage.need_id.in_(ids),
            EvidencePackage.schema_version == CONTRACT,
            EvidencePackage.question_contract == CONTRACT,
            EvidencePackage.provider == "deterministic",
            EvidencePackage.model == f"{MODEL_ID}:{MODEL_VERSION}",
            EvidencePackage.logical_call_id.is_(None),
            or_(
                and_(
                    native_sql_binding,
                    EvidencePackage.extractor_version == FERC_EXTRACTOR_VERSION,
                ),
                and_(
                    not_(native_sql_binding),
                    EvidencePackage.extractor_version == VERSION,
                ),
            ),
            EvidencePackage.evidence_hash == Evidence.content_hash,
            PowerNeed.active.is_(True),
            Project.region_status == "ELIGIBLE",
            Interpretation.status == "accepted",
            Interpretation.content_hash == Observation.content_hash,
            func.jsonb_extract_path_text(Interpretation.assessment, "semantic_hash")
            == Observation.content_hash,
            func.jsonb_extract_path_text(Interpretation.assessment, "evidence_hash")
            == Evidence.content_hash,
            func.jsonb_extract_path_text(Interpretation.assessment, "evidence", "id")
            == func.cast(Evidence.id, String),
            func.jsonb_extract_path_text(Interpretation.assessment, "project_identity_key")
            == Project.identity_key,
            or_(
                not_(native_sql_binding),
                func.jsonb_extract_path_text(Interpretation.assessment, "source_document_number")
                == Observation.external_id,
            ),
            func.coalesce(
                func.jsonb_extract_path_text(Interpretation.assessment, "power_activity"),
                func.jsonb_extract_path_text(Interpretation.assessment, "activity_key"),
            )
            == PowerNeed.activity_key,
            EvidencePackage.payload["binding"] == current_snapshot,
        )
        .distinct()
        .subquery()
    )
    rows = session.execute(
        select(EvidencePackage, PowerNeed, Project, Observation, Evidence, Interpretation, Source)
        .join(ranked, ranked.c.id == EvidencePackage.id)
        .join(PowerNeed, PowerNeed.id == EvidencePackage.need_id)
        .join(Project, Project.id == EvidencePackage.project_id)
        .join(Observation, Observation.id == EvidencePackage.observation_id)
        .join(Evidence, Evidence.id == EvidencePackage.evidence_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .join(
            NeedObservation,
            (NeedObservation.need_id == PowerNeed.id)
            & (NeedObservation.observation_id == Observation.id),
        )
        .where(ranked.c.position <= MAX_DOCUMENTS + 1)
        .order_by(EvidencePackage.need_id, ranked.c.position)
    ).all()
    grouped: dict[str, list[dict]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for package, need, project, observation, evidence, interpretation, source in rows:
        key = str(need.id)
        counts[key] += 1
        if (key, str(project.id)) not in wanted:
            continue
        if not _eligible(need, project, observation, evidence, interpretation, source):
            continue
        if (
            package.question_contract != CONTRACT
            or package.provider != "deterministic"
            or package.model != f"{MODEL_ID}:{MODEL_VERSION}"
            or package.logical_call_id is not None
            or package.extractor_version != _extractor_version(source, interpretation)
            or package.evidence_hash != evidence.content_hash
        ):
            continue
        expected = _payload(need, project, observation, evidence, source, interpretation)
        if (
            expected is None
            or expected != package.payload
            or expected["input_fingerprint"] != package.package_key
        ):
            continue
        expected_status = "BLOCKED" if expected["status"] == "ABSTAINED" else "COMPLETE_ADVISORY"
        if package.processing_status != expected_status:
            continue
        grouped[key].append(expected)
    results = {}
    for key, receipts in grouped.items():
        result = dict(receipts[0])
        result["evidence"] = [ref for r in receipts for ref in r["evidence"]]
        # Different documents can describe the same units, or a complete vs partial
        # schedule. Never assume they describe additive physical demand.
        signatures = {_engineering_signature(r) for r in receipts}
        if len(signatures) > 1 or counts[key] > MAX_DOCUMENTS:
            result.update(
                status="ABSTAINED",
                demand=None,
                classification="UNKNOWN",
                commercial_relevance="INVESTIGATION",
            )
            result["claim_classes"] = {**result["claim_classes"], "demand": "UNKNOWN"}
            result["quantity_classification"] = dict.fromkeys(
                result["quantity_classification"], "UNKNOWN"
            )
            result["next_action"] = (
                "Reconcile source schedules and dates before publishing numerical demand."
            )
            result["unresolved_questions"] = list(result["unresolved_questions"]) + [
                "Reconcile overlapping or conflicting equipment schedules before aggregation."
                if len(signatures) > 1
                else "Investigate document history beyond the bounded current projection."
            ]
        results[key] = result
    return results


def current_equipment_investigation(session, need_id, project_id) -> dict | None:
    return current_equipment_investigations(session, [(need_id, project_id)]).get(str(need_id))
