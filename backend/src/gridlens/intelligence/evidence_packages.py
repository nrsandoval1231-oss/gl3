"""Deterministic, versioned packages over retained evidence and typed Jev results."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
    SourceCollectionProgress,
)

SCHEMA_VERSION = "evidence-package-v1"
EXTRACTOR_VERSION = "retained-evidence-fields-v1"
QUESTION_CONTRACT = "signal-display-v2"
PROVIDER = "typesafe"
MODEL = "jev-1.13.0"
STATUSES = {"PREPARED", "COMPLETE_ADVISORY", "INCOMPLETE", "BLOCKED"}
FACT_LABELS = {"REPORTED", "DERIVED", "INFERRED", "UNKNOWN"}
FACT_FIELDS = {
    "applicant",
    "facility",
    "permit_number",
    "permit_numbers",
    "permit_no",
    "application_received",
    "application_stage",
    "location",
    "stated_purpose",
}

_LABELED_FIELD = re.compile(
    r"(?P<label>Applicant|Facility|Permit(?: numbers?| number| no\.?)?|Application received|"
    r"Application stage|Location|Stated purpose)\s*:\s*"
    r"(?P<value>[^\r\n;|]{1,500})",
    re.IGNORECASE,
)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _package_key(
    *,
    evidence: Evidence,
    observation: Observation,
    project: Project | None,
    need: PowerNeed | None,
) -> str:
    return _digest(
        {
            "schema_version": SCHEMA_VERSION,
            "evidence_id": str(evidence.id),
            "evidence_hash": evidence.content_hash,
            "observation_id": str(observation.id),
            "project_id": str(project.id) if project else None,
            "project_identity_key": project.identity_key if project else None,
            "need_id": str(need.id) if need else None,
            "extractor_version": EXTRACTOR_VERSION,
            "question_contract": QUESTION_CONTRACT,
            "provider": PROVIDER,
            "model": MODEL,
        }
    )


def _citation(evidence: Evidence, field: str, start: int, end: int) -> dict[str, Any]:
    return {
        "evidence_id": str(evidence.id),
        "evidence_hash": evidence.content_hash,
        "url": evidence.url,
        "excerpt_location": {"field": field, "start": start, "end": end},
    }


def _source_collection_status(session: Session, source: Source) -> str:
    health = source.health if isinstance(source.health, dict) else {}
    status = health.get("collection_status", health.get("source_collection_status"))
    if isinstance(status, str) and status.upper() in {"COMPLETE", "PARTIAL"}:
        return status.upper()
    status = health.get("status")
    if isinstance(status, str) and status.casefold() == "partial":
        return "PARTIAL"
    progress = session.scalars(
        select(SourceCollectionProgress).where(SourceCollectionProgress.source_id == source.id)
    ).all()
    if progress:
        states = {row.status.casefold() for row in progress}
        return "COMPLETE" if states == {"complete"} else "PARTIAL"
    return "UNKNOWN"


def build_package(
    session: Session,
    evidence_id: UUID,
    *,
    processing_status: str = "PREPARED",
) -> tuple[dict[str, Any], Evidence, Observation, Source, Project | None, PowerNeed | None]:
    """Build a cited source package; never infer business facts from free text."""
    if processing_status not in STATUSES:
        raise ValueError("Invalid evidence package processing status")
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        raise ValueError("Evidence ID does not exist")
    observation = session.get(Observation, evidence.observation_id)
    source = session.get(Source, observation.source_id) if observation else None
    if observation is None or source is None:
        raise ValueError("Evidence does not resolve to its observation and source")
    if observation.content_hash != evidence.content_hash:
        raise ValueError("Stale evidence hash: current observation differs from evidence version")
    if observation.source_id != source.id:
        raise ValueError("Evidence source identity mismatch")

    project = session.scalar(
        select(Project).where(
            Project.source_id == observation.source_id,
            Project.external_id == observation.external_id,
        )
    )
    needs = session.scalars(
        select(PowerNeed)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .where(NeedObservation.observation_id == observation.id)
    ).all()
    if project is not None:
        needs = [need for need in needs if need.project_id == project.id]
    need = needs[0] if len(needs) == 1 else None
    provenance = evidence.provenance if isinstance(evidence.provenance, dict) else {}
    ocr = provenance.get("ocr") if isinstance(provenance.get("ocr"), dict) else {}
    scanned = bool(
        provenance.get("scan_detected")
        or provenance.get("document_type") == "scanned"
        or "ocr" in evidence.extraction_location.casefold()
    )
    readable = bool(evidence.title.strip() or (evidence.abstract or "").strip())
    document_coverage = "RECORD_EXCERPT" if readable else "UNAVAILABLE"
    if scanned and not ocr:
        document_coverage = "UNAVAILABLE"
    abstract = evidence.abstract or ""
    title = evidence.title or ""
    facts: list[dict[str, Any]] = []
    for field_name, field_text in (("title", title), ("abstract", abstract)):
        for match in _LABELED_FIELD.finditer(field_text):
            raw_value = match.group("value")
            leading = len(raw_value) - len(raw_value.lstrip())
            value = raw_value.strip()
            if not value:
                continue
            start = match.start("value") + leading
            end = start + len(value)
            source_label = match.group("label").casefold()
            normalized = re.sub(r"[^a-z]+", "_", source_label).strip("_")
            facts.append(
                {
                    "field": normalized,
                    "value": value,
                    "unit": None,
                    "label": "REPORTED",
                    "extractor_basis": f"explicit retained label {match.group('label')!r}",
                    "citation": _citation(evidence, field_name, start, end),
                }
            )
    entities = []
    for claim in facts:
        if claim["field"] not in {"applicant", "facility"}:
            continue
        entities.append(
            {
                "value": claim["value"],
                "unit": None,
                "label": "REPORTED",
                "role": "applicant" if claim["field"] == "applicant" else "facility",
                "extractor_basis": claim["extractor_basis"],
                "citation": claim["citation"],
            }
        )
    package = {
        "schema_version": SCHEMA_VERSION,
        "package_key": _package_key(
            evidence=evidence, observation=observation, project=project, need=need
        ),
        "processing_status": processing_status,
        "source_references": [
            {
                "evidence_id": str(evidence.id),
                "evidence_hash": evidence.content_hash,
                "observation_id": str(observation.id),
                "source_id": source.id,
                "url": evidence.url,
                "extraction_location": evidence.extraction_location,
                "field_lengths": {
                    "title": len(title),
                    "abstract": len(abstract),
                },
            }
        ],
        "identity": {
            "project_id": str(project.id) if project else None,
            "project_identity_key": project.identity_key if project else None,
            "need_id": str(need.id) if need else None,
        },
        "extractor_version": EXTRACTOR_VERSION,
        "question_contract": QUESTION_CONTRACT,
        "provider": PROVIDER,
        "model": MODEL,
        "facts": facts,
        "entity_candidates": entities,
        "missing_fields": [
            {
                "field": field,
                "status": "UNKNOWN",
                "reason": "No deterministic retained-field parser supplied this value.",
            }
            for field in ("buyer", "required_mw", "start_window", "duration", "supply")
        ],
        "contradiction_pairs": [],
        "unevaluated_dimensions": ["cross-claim contradictions", "commercial role classification"],
        "quality_basis": [
            "Assertions use verbatim values from explicit retained labeled fields.",
            "Each value is checked against its exact retained text span.",
            "No confidence probability or unsupported unit is assigned.",
        ],
        "document_coverage": document_coverage,
        "document_coverage_basis": (
            "Retained text is a source excerpt; full document coverage is not established."
        ),
        "jev_input_coverage": {
            "title": "WHOLE_RETAINED_FIELD" if len(title) <= 300 else "TRUNCATED_RETAINED_FIELD",
            "title_sent_characters": min(len(title), 300),
            "abstract": (
                "WHOLE_RETAINED_ABSTRACT"
                if len(abstract) <= 1500
                else "TRUNCATED_RETAINED_ABSTRACT"
            ),
            "abstract_sent_characters": min(len(abstract), 1500),
            "abstract_omitted_tail_characters": max(0, len(abstract) - 1500),
            "url_sent_characters": min(len(evidence.url), 500),
            "url_omitted_tail_characters": max(0, len(evidence.url) - 500),
            "published_at_sent_characters": min(
                len(evidence.published_at.isoformat() if evidence.published_at else "unknown"),
                30,
            ),
            "metadata_fields_sent": [
                "source_id",
                "source_family",
                "publisher",
                "event_date",
                "event_date_label",
                "project_name",
                "location",
                "asset_type",
                "lifecycle_state",
            ],
        },
        "source_collection_status": _source_collection_status(session, source),
        "advisory": None,
        "reason": None,
        "logical_call_id": None,
    }
    validate_package(package, evidence_fields={"title": title, "abstract": abstract})
    return package, evidence, observation, source, project, need


def validate_package(
    package: dict[str, Any], *, evidence_fields: dict[str, str] | None = None
) -> None:
    """Reject malformed packages and unsupported citations before storage or reuse."""
    required = {
        "schema_version",
        "package_key",
        "processing_status",
        "source_references",
        "identity",
        "extractor_version",
        "question_contract",
        "provider",
        "model",
        "facts",
        "entity_candidates",
        "missing_fields",
        "contradiction_pairs",
        "unevaluated_dimensions",
        "quality_basis",
        "document_coverage",
        "document_coverage_basis",
        "jev_input_coverage",
        "source_collection_status",
        "advisory",
        "reason",
        "logical_call_id",
    }
    if not isinstance(package, dict) or not required.issubset(package):
        raise ValueError("Evidence package is missing required schema fields")
    if (
        package.get("schema_version") != SCHEMA_VERSION
        or package.get("processing_status") not in STATUSES
    ):
        raise ValueError("Invalid evidence package schema or processing status")
    if (
        package.get("provider") != PROVIDER
        or package.get("model") != MODEL
        or package.get("question_contract") != QUESTION_CONTRACT
        or not isinstance(package.get("package_key"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", package["package_key"])
    ):
        raise ValueError("Evidence package identity is missing or unpinned")
    refs_list = package.get("source_references")
    if (
        not isinstance(refs_list, list)
        or not refs_list
        or not all(isinstance(row, dict) for row in refs_list)
    ):
        raise ValueError("Evidence package requires a source reference")
    refs = {row.get("evidence_id"): row for row in refs_list}
    if len(refs) != len(refs_list):
        raise ValueError("Evidence package contains duplicate source references")
    if len(refs_list) != 1:
        raise ValueError("Evidence package v1 is bound to exactly one source version")
    for ref in refs_list:
        lengths = ref.get("field_lengths")
        if (
            not isinstance(ref.get("evidence_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("evidence_hash", "")))
            or not isinstance(ref.get("url"), str)
            or not ref["url"]
            or not isinstance(ref.get("observation_id"), str)
            or not isinstance(ref.get("source_id"), str)
            or not isinstance(ref.get("extraction_location"), str)
            or not isinstance(lengths, dict)
            or not all(
                type(lengths.get(field)) is int and lengths[field] >= 0
                for field in ("title", "abstract")
            )
        ):
            raise ValueError("Evidence package source reference is malformed")
        if evidence_fields is not None and any(
            lengths[field] != len(evidence_fields.get(field, "")) for field in ("title", "abstract")
        ):
            raise ValueError("Evidence package source span lengths differ from retained evidence")
    facts = package.get("facts")
    entities = package.get("entity_candidates")
    if not isinstance(facts, list) or not all(isinstance(item, dict) for item in facts):
        raise ValueError("Evidence package facts must be typed records")
    if not isinstance(entities, list) or not all(isinstance(item, dict) for item in entities):
        raise ValueError("Evidence package entities must be typed records")
    for claim in [*facts, *entities]:
        field_or_role = claim.get("field", claim.get("role"))
        if (
            not isinstance(field_or_role, str)
            or not isinstance(claim.get("unit"), str | None)
            or not isinstance(claim.get("value"), str)
            or not claim["value"]
            or claim.get("label") not in FACT_LABELS
            or not isinstance(claim.get("extractor_basis"), str)
            or not claim["extractor_basis"]
            or "unit" not in claim
        ):
            raise ValueError(
                "Evidence package claim is missing its typed value or extraction basis"
            )
        if claim.get("label") != "REPORTED":
            raise ValueError("Only source-reported claims are supported by this extractor")
        if "field" in claim and field_or_role not in FACT_FIELDS:
            raise ValueError("Evidence package fact field is unsupported")
        if "role" in claim and field_or_role not in {"applicant", "facility"}:
            raise ValueError("Evidence package entity role is unsupported")
        citation = claim.get("citation")
        ref = refs.get(citation.get("evidence_id")) if isinstance(citation, dict) else None
        location = citation.get("excerpt_location") if isinstance(citation, dict) else None
        if (
            ref is None
            or citation.get("evidence_hash") != ref["evidence_hash"]
            or citation.get("url") != ref["url"]
            or not isinstance(location, dict)
            or type(location.get("start")) is not int
            or type(location.get("end")) is not int
            or location["start"] < 0
            or location["end"] <= location["start"]
            or location.get("field") not in ref.get("field_lengths", {})
            or location["end"] > ref["field_lengths"].get(location.get("field"), -1)
        ):
            raise ValueError("Evidence package contains an invalid or mismatched citation")
        if location["end"] > location["start"]:
            source_text = evidence_fields.get(location["field"]) if evidence_fields else None
            if evidence_fields is not None and (
                not isinstance(source_text, str)
                or source_text[location["start"] : location["end"]] != claim["value"]
            ):
                raise ValueError("Claim value does not match its cited retained text span")
    for entity in entities:
        role = entity["role"]
        if not any(
            fact.get("field") == role
            and fact.get("value") == entity["value"]
            and fact.get("citation") == entity.get("citation")
            for fact in facts
        ):
            raise ValueError("Entity role must be supported by its matching labeled source fact")
    if not isinstance(package.get("missing_fields"), list) or not all(
        isinstance(row, dict)
        and isinstance(row.get("field"), str)
        and row.get("status") == "UNKNOWN"
        and isinstance(row.get("reason"), str)
        and bool(row["reason"])
        for row in package["missing_fields"]
    ):
        raise ValueError("Evidence package missing fields are malformed")
    identity = package.get("identity")
    if not isinstance(identity, dict) or not {
        "project_id",
        "project_identity_key",
        "need_id",
    }.issubset(identity):
        raise ValueError("Evidence package identity is malformed")
    if any(
        identity[key] is not None and not isinstance(identity[key], str)
        for key in ("project_id", "project_identity_key", "need_id")
    ):
        raise ValueError("Evidence package identity values must be strings or null")
    if not isinstance(package.get("extractor_version"), str) or not package["extractor_version"]:
        raise ValueError("Evidence package extractor version is missing")
    if (
        not isinstance(package.get("quality_basis"), list)
        or not package["quality_basis"]
        or not all(isinstance(x, str) and x for x in package["quality_basis"])
    ):
        raise ValueError("Evidence package quality basis is malformed")
    if not isinstance(package.get("unevaluated_dimensions"), list) or not all(
        isinstance(x, str) for x in package["unevaluated_dimensions"]
    ):
        raise ValueError("Evidence package unevaluated dimensions are malformed")
    coverage = package.get("jev_input_coverage")
    if not isinstance(coverage, dict) or not {
        "title",
        "title_sent_characters",
        "abstract",
        "abstract_sent_characters",
        "abstract_omitted_tail_characters",
        "url_sent_characters",
        "url_omitted_tail_characters",
        "published_at_sent_characters",
        "metadata_fields_sent",
    }.issubset(coverage):
        raise ValueError("Evidence package Jev input coverage is malformed")
    for name in (
        "title_sent_characters",
        "abstract_sent_characters",
        "abstract_omitted_tail_characters",
        "url_sent_characters",
        "url_omitted_tail_characters",
        "published_at_sent_characters",
    ):
        if type(coverage[name]) is not int or coverage[name] < 0:
            raise ValueError("Evidence package Jev input character counts are malformed")
    if not isinstance(coverage["metadata_fields_sent"], list) or not all(
        isinstance(x, str) for x in coverage["metadata_fields_sent"]
    ):
        raise ValueError("Evidence package Jev metadata field list is malformed")
    first_ref = refs_list[0]
    lengths = first_ref["field_lengths"]
    expected_key = _digest(
        {
            "schema_version": SCHEMA_VERSION,
            "evidence_id": first_ref["evidence_id"],
            "evidence_hash": first_ref["evidence_hash"],
            "observation_id": first_ref["observation_id"],
            "project_id": identity["project_id"],
            "project_identity_key": identity["project_identity_key"],
            "need_id": identity["need_id"],
            "extractor_version": package["extractor_version"],
            "question_contract": package["question_contract"],
            "provider": package["provider"],
            "model": package["model"],
        }
    )
    if package["package_key"] != expected_key:
        raise ValueError("Evidence package key does not bind its immutable input identity")
    if (
        coverage["title_sent_characters"] != min(lengths["title"], 300)
        or coverage["abstract_sent_characters"] != min(lengths["abstract"], 1500)
        or coverage["abstract_omitted_tail_characters"] != max(0, lengths["abstract"] - 1500)
        or coverage["url_sent_characters"] != min(len(first_ref["url"]), 500)
        or coverage["url_omitted_tail_characters"] != max(0, len(first_ref["url"]) - 500)
        or coverage["title"]
        != ("WHOLE_RETAINED_FIELD" if lengths["title"] <= 300 else "TRUNCATED_RETAINED_FIELD")
        or coverage["abstract"]
        != (
            "WHOLE_RETAINED_ABSTRACT"
            if lengths["abstract"] <= 1500
            else "TRUNCATED_RETAINED_ABSTRACT"
        )
    ):
        raise ValueError("Jev input coverage does not match the bounded source excerpts")
    if package.get("document_coverage") == "FULL_RETAINED_DOCUMENT":
        raise ValueError("Full document coverage requires producer-verified source proof")
    if package.get("document_coverage") not in {"RECORD_EXCERPT", "UNAVAILABLE"}:
        raise ValueError("Evidence package document coverage is unsupported")
    if (
        not isinstance(package.get("document_coverage_basis"), str)
        or not package["document_coverage_basis"]
    ):
        raise ValueError("Evidence package document coverage basis is missing")
    if package.get("contradiction_pairs") != []:
        raise ValueError(
            "Unsupported contradiction pair lacks deterministic cited-claim validation"
        )
    if package.get("document_coverage") not in {
        "FULL_RETAINED_DOCUMENT",
        "RECORD_EXCERPT",
        "UNAVAILABLE",
    } or package.get("source_collection_status") not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Evidence package coverage state is invalid")
    if package.get("processing_status") == "COMPLETE_ADVISORY":
        advisory = package.get("advisory")
        if (
            not isinstance(advisory, dict)
            or advisory.get("source") != "jev"
            or advisory.get("model") != MODEL
            or not isinstance(advisory.get("logical_call_id"), str)
            or not isinstance(package.get("logical_call_id"), str)
            or advisory.get("logical_call_id") != package.get("logical_call_id")
        ):
            raise ValueError("Complete advisory is missing its exact Jev receipt reference")
    if package.get("processing_status") in {"INCOMPLETE", "BLOCKED"} and not isinstance(
        package.get("reason"), str
    ):
        raise ValueError("Incomplete or blocked package requires a reason")
    if package.get("processing_status") == "PREPARED" and (
        package.get("advisory") is not None or package.get("logical_call_id") is not None
    ):
        raise ValueError("Prepared package cannot contain a Jev receipt")


def materialize_package(session: Session, evidence_id: UUID) -> EvidencePackage:
    package, evidence, observation, _source, project, need = build_package(session, evidence_id)
    row = session.scalar(
        select(EvidencePackage).where(EvidencePackage.package_key == package["package_key"])
    )
    if row is not None:
        validate_package(
            row.payload,
            evidence_fields={"title": evidence.title or "", "abstract": evidence.abstract or ""},
        )
        if row.processing_status != row.payload.get("processing_status"):
            raise ValueError("Stored evidence package status does not match its payload")
        immutable_fields = (
            "source_references",
            "identity",
            "extractor_version",
            "question_contract",
            "provider",
            "model",
            "facts",
            "entity_candidates",
            "missing_fields",
            "contradiction_pairs",
            "unevaluated_dimensions",
            "quality_basis",
            "document_coverage",
            "jev_input_coverage",
        )
        if any(row.payload.get(field) != package.get(field) for field in immutable_fields):
            raise ValueError("Stored evidence package differs from current deterministic evidence")
        return row
    row = EvidencePackage(
        package_key=package["package_key"],
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence.id,
        observation_id=observation.id,
        project_id=project.id if project else None,
        need_id=need.id if need else None,
        evidence_hash=evidence.content_hash,
        extractor_version=EXTRACTOR_VERSION,
        question_contract=QUESTION_CONTRACT,
        provider=PROVIDER,
        model=MODEL,
        processing_status="PREPARED",
        payload=package,
    )
    session.add(row)
    session.flush()
    return row


def update_status(
    session: Session,
    row: EvidencePackage,
    status: str,
    *,
    reason: str | None = None,
    logical_call_id: UUID | None = None,
    advisory: dict[str, Any] | None = None,
) -> None:
    if status not in STATUSES:
        raise ValueError("Invalid evidence package processing status")
    payload = dict(row.payload)
    payload["processing_status"] = status
    payload["reason"] = reason
    payload["logical_call_id"] = str(logical_call_id) if logical_call_id else None
    if advisory is not None:
        payload["advisory"] = advisory
    row.payload = payload
    row.processing_status = status
    if logical_call_id is not None:
        row.logical_call_id = logical_call_id
    validate_package(payload)
