"""Retained customer facts over canonical evidence, frozen with browse generations.

EvidencePackage is an immutable audit receipt, never publication authority. Generation
builders re-extract accepted current evidence in bulk; navigation reads only frozen
BrowseRow.compact facts. Package-only writes therefore cannot change a published view.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import String, and_, exists, or_, select, union
from sqlalchemy.dialects.postgresql import insert

from gridlens.persistence.models import (
    BrowseRow,
    CompanyProjectMembership,
    Evidence,
    EvidencePackage,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)

CONTRACT = "customer-facts-v1"
MAX_SOURCE_CHARACTERS = 200_000
MAX_PROJECT_SOURCES = 128
_OWNER_ROLES = ("owner_developer", "owner_energy", "owner_construction", "asset_operator")
_OWNER_POSSESSIVE = re.compile(r"(?:^|\s)(?:[A-Z][\w&.’'-]*(?:\s+[A-Z][\w&.’'-]*){0,4})[’']s\s+")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _query(project_ids):
    # Resolve observation IDs through existing indexed joins before inspecting JSON
    # admission metadata. Avoid scanning the entire interpretation corpus per batch.
    linked = union(
        select(PowerNeed.project_id.label("project_id"), NeedObservation.observation_id)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .where(PowerNeed.project_id.in_(project_ids)),
        select(Project.id.label("project_id"), Observation.id.label("observation_id"))
        .join(
            Observation,
            and_(
                Project.source_id == Observation.source_id,
                Project.external_id == Observation.external_id,
            ),
        )
        .where(Project.id.in_(project_ids)),
    ).subquery()
    targeted = exists(
        select(NeedObservation.need_id)
        .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
        .where(
            NeedObservation.observation_id == Observation.id,
            PowerNeed.project_id == Project.id,
            Interpretation.assessment["target_need_id"].astext == PowerNeed.id.cast(String),
        )
    )
    return (
        select(Project, Observation, Evidence, Interpretation, Source)
        .select_from(Project)
        .join(linked, linked.c.project_id == Project.id)
        .join(Observation, Observation.id == linked.c.observation_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(
            Project.region_status == "ELIGIBLE",
            Interpretation.status == "accepted",
            Interpretation.content_hash == Observation.content_hash,
            Interpretation.assessment["project_identity_key"].astext == Project.identity_key,
            Interpretation.assessment["decision"].astext == "accepted",
            Interpretation.assessment["semantic_hash"].astext == Observation.content_hash,
            Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            or_(
                Interpretation.assessment["admission_status"].astext
                != "project_research_supplement",
                Interpretation.assessment["admission_status"].astext.is_(None),
                targeted,
            ),
        )
        .order_by(Project.id, Evidence.id)
    )


def _overflow(project_id, reason: str) -> dict:
    return {
        "version": CONTRACT,
        "project_id": str(project_id),
        "capacity_claims": [],
        "timeline_claims": [],
        "commissioning_inputs": [],
        "overflow": True,
        "limitations": [reason],
    }


def _reproduces_claim(claim: dict, field: str, predicate: str, source: dict) -> bool:
    from gridlens.domain.customer_intelligence import extract_customer_facts

    reproduced = extract_customer_facts(
        predicate,
        project_id=str(claim.get("project_id") or ""),
        source=source,
    )
    candidate_key = "capacity_claims" if field == "capacity_claims" else "timeline_claims"
    semantic_fields = (
        ("basis", "value_mw", "qualifier", "scope_id", "phase_id", "includes_scope_ids")
        if field == "capacity_claims"
        else (
            "event_type",
            "label",
            "precision",
            "qualifier",
            "scope_id",
            "start",
            "end",
            "earliest",
            "latest",
        )
    )
    return any(
        all(candidate.get(key) == claim.get(key) for key in semantic_fields)
        for candidate in reproduced.get(candidate_key, [])
    )


def scope_customer_facts(
    payload: dict,
    project_name: str,
    project_location: str = "",
    *,
    source_text: str | None = None,
    project_aliases: list[str] | tuple[str, ...] = (),
    trusted_owner_names: list[str] | tuple[str, ...] = (),
) -> dict:
    """Require an exact grammatical subject and a local electrical/timing predicate.

    Merely mentioning the selected project somewhere in a comparative sentence
    cannot assign another campus's quantities to it. Unsupported phrasing abstains.
    """
    from gridlens.domain.customer_subjects import (
        claim_has_owned_predicate,
        resolve_claim_subject,
    )

    result = dict(payload)
    for key in ("capacity_claims", "timeline_claims"):
        accepted = []
        for claim in payload.get(key, []):
            if not isinstance(claim, dict):
                continue
            quote = str(claim.get("quote") or "")
            if source_text is not None:
                claim_source = claim.get("source")
                source_hash = (
                    claim_source.get("content_hash") if isinstance(claim_source, dict) else None
                )
                binding = resolve_claim_subject(
                    source_text,
                    quote,
                    project_name=project_name,
                    project_aliases=project_aliases,
                    trusted_owner_names=trusted_owner_names,
                    source_hash=source_hash,
                )
                if binding is None:
                    continue
                if not claim_has_owned_predicate(
                    binding, claim, key, project_location=project_location
                ):
                    continue
                if not _reproduces_claim(
                    claim,
                    key,
                    binding["predicate"],
                    claim_source if isinstance(claim_source, dict) else {},
                ):
                    continue
                accepted.append({**claim, "subject_binding": binding})
                continue

            # Compatibility callers often have only the exact extracted quote,
            # not the full evidence document. Treat that quote as the complete
            # local source and apply the same bounded subject/predicate grammar.
            legacy_source_value = claim.get("source")
            source_hash = (
                legacy_source_value.get("content_hash")
                if isinstance(legacy_source_value, dict)
                else None
            )
            binding = resolve_claim_subject(
                quote,
                quote,
                project_name=project_name,
                source_hash=source_hash,
            )
            if binding is None or not claim_has_owned_predicate(
                binding, claim, key, project_location=project_location
            ):
                continue
            legacy_source: dict[str, Any] = (
                legacy_source_value if isinstance(legacy_source_value, dict) else {}
            )
            if _reproduces_claim(claim, key, binding["predicate"], legacy_source):
                accepted.append(claim)
        result[key] = accepted
    return result


def extract_commissioning_plan(
    text: str,
    *,
    project_id: str,
    project_name: str,
    source: dict,
    project_aliases: list[str] | tuple[str, ...] = (),
) -> list[dict]:
    """Read an explicitly scoped retained engineering JSON section, never infer a plan.

    All electrical ratings/loading/sequence values must occur in the section. Caller
    supplies only canonical identity and the current evidence envelope. Foreign source
    references, partial sections and unproved concurrent load disjointness abstain.
    """
    sections = [
        match.group(1)
        for match in re.finditer(r"```json\s*(.*?)\s*```", text, re.S | re.I)
        if '"commissioning_test_plan"' in match.group(1)
    ]
    if not sections:
        return []

    def invalid(reason: str) -> list[dict]:
        return [{"project_id": project_id, "invalid_reason": reason}]

    if len(sections) != 1 or len(sections[0]) > 64_000:
        return invalid("A single complete bounded engineering test-plan section is required.")
    try:
        document = json.loads(sections[0])
    except (TypeError, ValueError):
        return invalid("Engineering test-plan JSON is malformed.")
    site_names = {
        *(value for value in project_aliases if isinstance(value, str)),
        *([project_name] if len(project_name.split()) >= 2 else []),
    }
    public_name = document.get("project_name") if isinstance(document, dict) else None
    outside_json = re.sub(r"```json\s*.*?\s*```", " ", text, flags=re.S | re.I)
    if (
        not isinstance(document, dict)
        or not isinstance(public_name, str)
        or public_name not in site_names
        or not re.search(r"(?<!\w)" + re.escape(public_name) + r"(?!\w)", outside_json, re.I)
    ):
        return invalid("Engineering test-plan project name is not the exact canonical site.")
    blocks = document.get("commissioning_test_plan")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 200:
        return invalid("A complete bounded electrical test plan is required.")
    reference = {**source, "project_id": project_id, "quote": sections[0]}
    admitted = []
    stage_loads: dict[str, set[str]] = defaultdict(set)
    for raw in blocks:
        if not isinstance(raw, dict) or (
            raw.get("project_id") is not None and str(raw.get("project_id")) != project_id
        ):
            return invalid("Engineering test blocks cannot borrow another project's identity.")
        existing = raw.get("evidence")
        if existing is not None:
            if not isinstance(existing, dict):
                return invalid("Engineering source references are malformed.")
            for refs in existing.values():
                if not isinstance(refs, list):
                    return invalid("Engineering source references are malformed.")
                for ref in refs:
                    if not isinstance(ref, dict) or any(
                        key not in {"project_id", "url", "evidence_id", "content_hash"}
                        or value != reference.get(key)
                        for key, value in ref.items()
                    ):
                        return invalid("Engineering test inputs cite a different retained source.")
        dimensions = ["rating", "test_fraction", "sequence"]
        if raw.get("unit") == "kVA":
            dimensions.append("power_factor")
        if raw.get("scenarios") is not None:
            dimensions.append("scenarios")
        block = {
            **raw,
            "project_id": project_id,
            "evidence": {field: [dict(reference)] for field in dimensions},
        }
        admitted.append(block)
        stage_loads[str(raw.get("sequence_stage"))].add(str(raw.get("load_scope_id")))
    disjoint = document.get("disjoint_load_scope_ids", [])
    if any(len(scopes) > 1 for scopes in stage_loads.values()) and (
        not isinstance(disjoint, list)
        or any(not isinstance(item, str) for item in disjoint)
        or any(not scopes.issubset(set(disjoint)) for scopes in stage_loads.values())
    ):
        return invalid("Concurrent electrical load scopes are not explicitly proven disjoint.")
    return admitted


def _verified_project_owner_names(session, project_ids) -> dict[str, list[str]]:
    """Batch current source-bound owner/operator context for a project cohort."""
    from uuid import UUID

    from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project

    project_keys = {str(project_id) for project_id in project_ids}
    result: dict[str, set[str]] = {key: set() for key in project_keys}
    if not project_keys:
        return {}
    rows = session.execute(
        select(CompanyProjectMembership, Project, Evidence, Observation, Interpretation, Source)
        .join(Project, Project.id == CompanyProjectMembership.project_id)
        .join(Evidence, Evidence.id == CompanyProjectMembership.source_evidence_id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(
            CompanyProjectMembership.project_id.in_([UUID(key) for key in project_keys]),
            CompanyProjectMembership.role.in_(_OWNER_ROLES),
            CompanyProjectMembership.state == "current",
        )
        .order_by(CompanyProjectMembership.organization_name)
    )
    for membership, project, evidence, observation, interpretation, source in rows:
        if (
            membership.source_id != source.id
            or membership.source_version_hash != evidence.content_hash
            or evidence.observation_id != observation.id
            or not _retained_evidence_current_for_project(
                session,
                project,
                evidence,
                observation=observation,
                interpretation=interpretation,
                source=source,
                preloaded=True,
            )
        ):
            continue
        name = membership.organization_name.strip()
        if name:
            result[str(project.id)].add(name)
    return {project_id: sorted(names, key=str.casefold) for project_id, names in result.items()}


def _payload(
    project,
    observation,
    evidence,
    interpretation,
    source,
    *,
    trusted_owner_names=(),
    owner_name_loader=None,
) -> dict | None:
    from gridlens.domain.customer_intelligence import extract_customer_facts

    assessment = interpretation.assessment or {}
    if evidence.published_at is not None and evidence.published_at > date.today():
        return None
    # Relationship-only admission explicitly does not authorize electrical/timing claims.
    if assessment.get("admission_status") == "relationship_supplement":
        return None
    reference = assessment.get("evidence")
    if isinstance(reference, dict):
        if str(reference.get("id")) != str(evidence.id) or reference.get("url") != evidence.url:
            return None
    elif assessment.get("admission_status") != "project_research_supplement":
        return None
    if evidence.url != observation.url:
        return None
    if assessment.get("admission_status") == "project_research_supplement":
        from gridlens.domain.project_research import VERSION
        from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

        if (
            interpretation.evaluator_version != VERSION
            or assessment.get("acquisition_capture_version") != CAPTURE_VERSION
            or not assessment.get("target_need_id")
        ):
            return None
    text = evidence.abstract or ""
    if not text:
        return None
    if len(text) > MAX_SOURCE_CHARACTERS or len(re.split(r"(?<=[.!?])\s+|[\n;]+", text)) > 1000:
        return _overflow(project.id, "Source text exceeds the complete extraction bound.")
    try:
        parsed_url = urlsplit(evidence.url)
        host = (parsed_url.hostname or "").lower()
    except ValueError:
        return None
    if parsed_url.scheme not in {"http", "https"} or not host:
        return None
    authority = "regulatory" if host.endswith(".gov") else "unknown"
    observed_at = evidence.observed_at.isoformat() if evidence.observed_at else None
    provenance = {
        "url": evidence.url,
        "evidence_id": str(evidence.id),
        "content_hash": evidence.content_hash,
        "semantic_hash": observation.content_hash,
        "source_id": source.id,
        "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
        "observed_at": observed_at,
        # Frozen extraction metadata is source-bound, not changed on each read/retry.
        "extracted_at": (evidence.provenance or {}).get("extracted_at"),
        "extraction_method": "deterministic",
        "extraction_location": evidence.extraction_location,
        "authority": authority,
        "verification_status": "reported",
        "current": True,
    }
    payload = extract_customer_facts(text, project_id=str(project.id), source=provenance)
    if sum(len(payload.get(key, [])) for key in ("capacity_claims", "timeline_claims")) >= 200:
        return _overflow(project.id, "Source claims exceed the complete extraction bound.")
    identity_facts = project.identity_facts if isinstance(project.identity_facts, dict) else {}
    aliases = identity_facts.get("project_aliases", [])
    aliases = (
        [value for value in aliases if isinstance(value, str)] if isinstance(aliases, list) else []
    )
    trusted_owners = list(
        dict.fromkeys(value for value in trusted_owner_names if isinstance(value, str))
    )
    if (
        not trusted_owners
        and callable(owner_name_loader)
        and any(
            _OWNER_POSSESSIVE.search(str(claim.get("quote") or ""))
            for key in ("capacity_claims", "timeline_claims")
            for claim in payload.get(key, [])
            if isinstance(claim, dict)
        )
    ):
        trusted_owners = owner_name_loader()
    payload = scope_customer_facts(
        payload,
        project.name,
        project.location or "",
        source_text=text,
        project_aliases=aliases,
        trusted_owner_names=trusted_owners,
    )
    payload["commissioning_inputs"] = extract_commissioning_plan(
        text,
        project_id=str(project.id),
        project_name=project.name,
        source=provenance,
        project_aliases=aliases,
    )
    if not any(
        payload.get(key) for key in ("capacity_claims", "timeline_claims", "commissioning_inputs")
    ):
        return None
    payload["binding"] = {
        "project_identity_key": project.identity_key,
        "evidence_id": str(evidence.id),
        "evidence_hash": evidence.content_hash,
        "semantic_hash": observation.content_hash,
        "source_url": evidence.url,
        "evaluator_version": interpretation.evaluator_version,
    }
    return payload


def persist_customer_facts(
    session, *, project_id, evidence_id, source_text: str | None = None
) -> EvidencePackage | None:
    """Append an idempotent receipt; caller owns transaction, leases and admission.

    This receipt-only writer never emits alerts or changes public execution state.
    Existing material-state hooks own normal versus quiet-backfill change detection.
    It never mutates evidence, qualification, identities, or existing package history.
    """
    if isinstance(source_text, str) and len(source_text) <= MAX_SOURCE_CHARACTERS:
        from gridlens.domain.customer_intelligence import extract_customer_facts

        candidates = extract_customer_facts(
            source_text,
            project_id=str(project_id),
            source={},
        )
        has_public_plan = bool(
            re.search(
                r"```json\s*.*?\"commissioning_test_plan\".*?```",
                source_text,
                re.S | re.I,
            )
        )
        if (
            not candidates.get("overflow")
            and not candidates.get("capacity_claims")
            and not candidates.get("timeline_claims")
            and not has_public_plan
        ):
            return None
    project_id, evidence_id = UUID(str(project_id)), UUID(str(evidence_id))
    session.flush()
    row = session.execute(_query([project_id]).where(Evidence.id == evidence_id)).first()
    if row is None:
        return None
    project, observation, evidence, interpretation, source = row
    payload = _payload(
        *row,
        owner_name_loader=lambda: _verified_project_owner_names(session, [project.id]).get(
            str(project.id), []
        ),
    )
    if payload is None:
        return None
    package_key = _digest({"contract": CONTRACT, "payload": payload})
    session.execute(
        insert(EvidencePackage)
        .values(
            id=uuid4(),
            package_key=package_key,
            schema_version=CONTRACT,
            evidence_id=evidence.id,
            observation_id=observation.id,
            project_id=project.id,
            need_id=None,
            evidence_hash=evidence.content_hash,
            extractor_version=payload["version"],
            question_contract=CONTRACT,
            provider="deterministic",
            model=CONTRACT,
            processing_status="INCOMPLETE" if payload.get("overflow") else "COMPLETE_ADVISORY",
            payload=payload,
            logical_call_id=None,
        )
        .on_conflict_do_nothing(index_elements=["package_key"])
    )
    return session.scalar(select(EvidencePackage).where(EvidencePackage.package_key == package_key))


def project_customer_facts(session, project_ids, *, generation) -> dict[str, list[dict]]:
    """One batched read. Explicit ``generation=None`` is build-only current extraction.

    Supplying a generation reads only that generation's frozen source-bound facts;
    current-generation authorization and read-time privacy remain the API's guards.
    No research, package creation or other database writes occur here.
    """
    ids = sorted({UUID(str(value)) for value in project_ids}, key=str)
    result: dict[str, list[dict]] = {str(value): [] for value in ids}
    if not ids:
        return result
    seen: dict[str, set[str]] = defaultdict(set)
    if generation is not None:
        generation_id = getattr(generation, "id", generation)
        rows = session.execute(
            select(BrowseRow.project_id, BrowseRow.compact["customer_facts"])
            .where(
                BrowseRow.generation_id == UUID(str(generation_id)), BrowseRow.project_id.in_(ids)
            )
            .distinct()
        )
        for project_id, payloads in rows:
            for payload in payloads if isinstance(payloads, list) else []:
                if isinstance(payload, dict) and payload.get("project_id") == str(project_id):
                    key = _digest(payload)
                    if key not in seen[str(project_id)]:
                        seen[str(project_id)].add(key)
                        result[str(project_id)].append(payload)
        return result
    source_counts: dict[str, int] = defaultdict(int)
    trusted_owners = _verified_project_owner_names(session, ids)
    for row in session.execute(_query(ids)).yield_per(64):
        project_id = str(row[0].id)
        source_counts[project_id] += 1
        if source_counts[project_id] > MAX_PROJECT_SOURCES:
            result[project_id] = [
                _overflow(project_id, "Current sources exceed the complete project bound.")
            ]
            continue
        payload = _payload(*row, trusted_owner_names=trusted_owners[project_id])
        if payload is not None:
            project_id = str(row[0].id)
            key = _digest(payload)
            if key not in seen[project_id]:
                seen[project_id].add(key)
                result[project_id].append(payload)
    return result
