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
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from gridlens.domain.equipment_demand import MODEL_ID, MODEL_VERSION, calculate_equipment_demand
from gridlens.domain.signal_admission import admitted_from_source
from gridlens.ingestion.parsers.equipment import VERSION, extract_equipment_claims
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


def _json(value: Any) -> Any:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, date | datetime):
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
        and admitted_from_source(source, assessment, evidence).admitted
    )


def _input_key(need, project, observation, evidence, source, interpretation) -> str:
    """Frozen interpretation inputs: replay does not parse or calculate twice."""
    assessment = interpretation.assessment or {}
    return _digest(
        {
            "versions": [CONTRACT, VERSION, MODEL_ID, MODEL_VERSION],
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
    )


def _payload(need, project, observation, evidence, source, interpretation) -> dict | None:
    text = evidence.abstract or ""
    extracted = extract_equipment_claims(text)
    if not extracted.claims and not extracted.issues:
        return None
    questions = list(extracted.issues)
    if not extracted.company:
        questions.append("Establish the source-reported company for this equipment schedule.")
    assessment = interpretation.assessment or {}
    facility_names = {_name(project.name)}
    # Official permit assessment retains the facility separately from its applicant.
    # This hint is accepted only inside the exact current project/activity binding.
    if source.family == "construction-permits" and assessment.get("project_hint"):
        facility_names.add(_name(assessment["project_hint"]))
    if not extracted.facility or _name(extracted.facility) not in facility_names:
        questions.append("Resolve the equipment facility against the canonical physical project.")
    if (
        assessment.get("project_hint")
        and extracted.company
        and _name(extracted.company) != _name(assessment.get("subject"))
    ):
        questions.append("Resolve the source company against the accepted applicant attribution.")
    source_date = evidence.published_at or evidence.event_date
    as_of = source_date
    if extracted.as_of:
        try:
            as_of = date.fromisoformat(extracted.as_of)
        except ValueError:
            questions.append("Resolve the invalid equipment schedule date.")
    if not source_date or not as_of:
        questions.append("Establish a dated source for the equipment schedule.")
    # Freeze validation against acquisition time; no wall clock in the package key.
    retrieved = evidence.observed_at.date() if evidence.observed_at else None
    if retrieved and ((source_date and source_date > retrieved) or (as_of and as_of > retrieved)):
        questions.append("Resolve a schedule or publication date after source retrieval.")
    if extracted.truncated:
        questions.append("Investigate the complete schedule; bounded extraction was incomplete.")
    for claim in extracted.claims:
        if claim.start is None or claim.end is None or text[claim.start : claim.end] != claim.quote:
            questions.append("Resolve equipment claim source-span mismatch.")
    claims = [replace(c, source_id=str(evidence.id)) for c in extracted.claims]
    calculated = calculate_equipment_demand(claims, as_of=as_of)
    status = (
        "ABSTAINED"
        if questions or not claims
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
    demand = None if status == "ABSTAINED" else _json(asdict(calculated))
    electric = [c for c in claims if c.drive == "electric"]
    new = [c for c in electric if c.state in {"new", "proposed"}]
    category = "CALCULATED" if demand and calculated.coincident_kw is not None else "UNKNOWN"
    return {
        "schema_version": CONTRACT,
        "input_fingerprint": _input_key(
            need, project, observation, evidence, source, interpretation
        ),
        "record_id": _digest([str(need.id), str(project.id), CONTRACT]),
        "need_id": str(need.id),
        "project_id": str(project.id),
        # A source header establishes attribution, not a verified buyer or corporate identity.
        "company_id": None,
        "company": extracted.company,
        "company_basis": "DOCUMENTED",
        "facility_id": str(project.id),
        "facility": extracted.facility,
        "location": project.location,
        "scope": "equipment_schedule",
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
        "last_verified_at": _json(evidence.observed_at),
        "model": {"id": MODEL_ID, "version": MODEL_VERSION},
        "extractor_version": VERSION,
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
            extractor_version=VERSION,
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
        .where(EvidencePackage.need_id.in_(ids), EvidencePackage.schema_version == CONTRACT)
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
            or package.extractor_version != VERSION
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
        signatures = {
            _digest(
                {
                    "company": r["company"],
                    "facility": r["facility"],
                    "equipment": [
                        {
                            k: v
                            for k, v in c.items()
                            if k not in {"source_id", "quote", "start", "end"}
                        }
                        for c in r["equipment"]
                    ],
                    "status": r["status"],
                    "as_of": r["as_of"],
                    "quantities": {
                        k: v
                        for k, v in (r["demand"] or {}).items()
                        if k not in {"inputs", "input_hashes", "items"}
                    },
                }
            )
            for r in receipts
        }
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
