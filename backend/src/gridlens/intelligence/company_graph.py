"""Correction-aware, evidence-bound read API for canonical company graphs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import (
    _retained_evidence_current_for_project,
    buying_chain_views,
)
from gridlens.persistence.contact_models import (
    CompanyRelationshipAssertion,
    CompanyRelationshipCorrection,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    IdentityIdentifier,
    Interpretation,
    Observation,
    PowerNeed,
    Project,
    Source,
)

RELATIONSHIP_TYPES = frozenset(
    {
        "parent",
        "subsidiary",
        "developer",
        "operator",
        "epc",
        "gc",
        "utility",
    }
)
GRAPH_PROJECT_LIMIT = 100
GRAPH_ASSERTION_LIMIT = 100
CLAIM_ROLE_LABELS = {
    "asset_operator": "operator",
    "field_operations": "operator",
    "owner_developer": "developer",
    "general_contractor": "gc",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _retained_current(session: Session, evidence: Evidence, project: Project) -> bool:
    observation = session.get(Observation, evidence.observation_id)
    if observation is None or observation.content_hash != evidence.content_hash:
        return False
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    assessment = interpretation.assessment if interpretation else None
    return bool(
        interpretation
        and interpretation.status == "accepted"
        and assessment
        and assessment.get("decision") == "accepted"
        and assessment.get("evidence_hash") == evidence.content_hash
        and assessment.get("project_identity_key") == project.identity_key
    )


def _canonical_evidence(session: Session, evidence: Evidence) -> dict[str, Any]:
    observation = session.get(Observation, evidence.observation_id)
    source = session.get(Source, observation.source_id) if observation else None
    return {
        "id": str(evidence.id),
        "title": evidence.title,
        "url": evidence.url,
        "content_hash": evidence.content_hash,
        "source_id": source.id if source else None,
        "observed_at": _iso(evidence.observed_at),
        "published_at": _iso(evidence.published_at),
    }


def _buying_evidence(session: Session, source: BuyingChainEvidence) -> dict[str, Any]:
    retained = (
        session.get(Evidence, source.retained_evidence_id) if source.retained_evidence_id else None
    )
    observation = session.get(Observation, retained.observation_id) if retained else None
    publisher = session.get(Source, observation.source_id) if observation else None
    return {
        "id": str(source.id),
        "title": source.title,
        "url": source.url,
        "content_hash": source.content_hash,
        "source_id": publisher.id if publisher else None,
        "observed_at": _iso(source.observed_at),
        "published_at": _iso(source.published_at),
    }


def _buying_evidence_current(session: Session, source: BuyingChainEvidence) -> bool:
    project = session.get(Project, source.project_id)
    if (
        project is None
        or project.region_status != "ELIGIBLE"
        or project.region_state not in {"TX", "OK", "NM"}
    ):
        return False
    latest = session.scalar(
        select(BuyingChainEvidence)
        .where(
            BuyingChainEvidence.project_id == source.project_id,
            BuyingChainEvidence.url == source.url,
        )
        .order_by(BuyingChainEvidence.observed_at.desc(), BuyingChainEvidence.id.desc())
        .limit(1)
    )
    run = session.scalar(
        select(BuyingChainRun)
        .where(BuyingChainRun.project_id == project.id)
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(1)
    )
    if latest is None or latest.id != source.id or run is None:
        return False
    if str(source.id) not in set(run.evidence_ids or []):
        return False
    if source.retained_evidence_id is not None:
        retained = session.get(Evidence, source.retained_evidence_id)
        return bool(retained and _retained_evidence_current_for_project(session, project, retained))
    return True


def _relationship_state(
    session: Session, assertion: CompanyRelationshipAssertion
) -> tuple[str, int, str | None]:
    rows = session.scalars(
        select(CompanyRelationshipCorrection)
        .where(CompanyRelationshipCorrection.assertion_id == assertion.id)
        .order_by(CompanyRelationshipCorrection.version)
    ).all()
    state, version, latest_id = "current", 1, None
    for row in rows:
        if row.expected_version != version or row.version != version + 1:
            return "conflicted", version, latest_id
        state, version, latest_id = row.action, row.version, str(row.id)
    normalized = {
        "reinstate": "current",
        "suppress": "suppressed",
    }.get(state, state)
    return normalized, version, latest_id


def company_graph(session: Session, company_id: UUID) -> dict[str, Any]:
    """Return bounded company identity, regional roles, current evidence, and assertions."""
    company = session.get(CompanyIdentity, company_id)
    if company is None:
        raise LookupError("Company identity not found")

    identifiers = session.scalars(
        select(IdentityIdentifier)
        .where(
            IdentityIdentifier.entity_type == "company",
            IdentityIdentifier.company_identity_id == company_id,
        )
        .order_by(IdentityIdentifier.identifier_type, IdentityIdentifier.normalized_value)
        .limit(100)
    ).all()
    has_active_need = (
        select(PowerNeed.id)
        .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
        .exists()
    )
    memberships = session.scalars(
        select(CompanyProjectMembership)
        .join(Project, Project.id == CompanyProjectMembership.project_id)
        .where(
            CompanyProjectMembership.company_identity_id == company_id,
            CompanyProjectMembership.state == "current",
            Project.region_status == "ELIGIBLE",
            Project.region_state.in_({"TX", "OK", "NM"}),
            has_active_need,
        )
        .order_by(Project.name, CompanyProjectMembership.role)
        .limit(GRAPH_PROJECT_LIMIT)
    ).all()
    project_ids = list(dict.fromkeys(membership.project_id for membership in memberships))
    linked_project_ids = session.scalars(
        select(Project.id)
        .select_from(BuyingChainIdentityLink)
        .join(BuyingChainClaim, BuyingChainClaim.id == BuyingChainIdentityLink.claim_id)
        .join(Project, Project.id == BuyingChainClaim.project_id)
        .where(
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.company_identity_id == company_id,
            BuyingChainIdentityLink.state == "current",
            Project.region_status == "ELIGIBLE",
            Project.region_state.in_({"TX", "OK", "NM"}),
            has_active_need,
        )
        .distinct()
        .order_by(Project.id)
        .limit(GRAPH_PROJECT_LIMIT)
    ).all()
    for project_id in linked_project_ids:
        if project_id not in project_ids and len(project_ids) < GRAPH_PROJECT_LIMIT:
            project_ids.append(project_id)

    projects: dict[UUID, dict[str, Any]] = {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    role_keys: dict[UUID, set[tuple[str, str]]] = {}
    current_company_evidence: dict[UUID, set[UUID]] = {}
    display_name: str | None = None
    for membership in memberships:
        project = session.get(Project, membership.project_id)
        evidence = session.get(Evidence, membership.source_evidence_id)
        if (
            project is None
            or evidence is None
            or evidence.content_hash != membership.source_version_hash
            or not _retained_current(session, evidence, project)
        ):
            continue
        evidence_doc = _canonical_evidence(session, evidence)
        evidence_by_id[str(evidence.id)] = evidence_doc
        display_name = display_name or membership.organization_name
        membership_entry = projects.setdefault(
            project.id,
            {
                "id": str(project.id),
                "name": project.name,
                "location": project.location,
                "roles": [],
            },
        )
        role_key = (membership.role, membership.organization_name)
        role_keys.setdefault(project.id, set()).add(role_key)
        membership_entry["roles"].append(
            {
                "role": membership.role,
                "organization_name": membership.organization_name,
                "state": membership.state,
                "evidence": evidence_doc,
            }
        )

    # The existing view owns claim freshness, source-version checks, corrections,
    # and identity-link validation. Consume its accepted current candidates rather
    # than reimplementing those rules in this graph projection.
    views = buying_chain_views(session, set(project_ids)) if project_ids else {}
    for project_key, view in views.items():
        project_id = UUID(str(project_key))
        project = session.get(Project, project_id)
        if project is None:
            continue
        linked_project_entry = projects.get(project_id)
        for candidate in view.get("candidates", []):
            if str(candidate.get("company_identity_id")) != str(company_id):
                continue
            for item in candidate.get("evidence", []):
                if item.get("current_support") and str(
                    item.get("current_source_version_id")
                ) == str(item.get("id")):
                    try:
                        current_company_evidence.setdefault(project_id, set()).add(
                            UUID(str(item["id"]))
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
            citation = next(
                (
                    item
                    for item in candidate.get("evidence", [])
                    if item.get("supports") == "project_organization"
                    and item.get("current_support")
                ),
                None,
            )
            if citation is None:
                continue
            source = session.get(BuyingChainEvidence, citation["id"])
            if source is None:
                continue
            evidence_doc = _buying_evidence(session, source)
            evidence_by_id[str(source.id)] = evidence_doc
            display_name = display_name or candidate.get("organization")
            if linked_project_entry is None:
                linked_project_entry = projects.setdefault(
                    project_id,
                    {
                        "id": str(project.id),
                        "name": project.name,
                        "location": project.location,
                        "roles": [],
                    },
                )
            organization_name = str(candidate.get("organization") or "")
            category = str(candidate.get("category") or "organization")
            role = CLAIM_ROLE_LABELS.get(category, category)
            role_key = (role, organization_name)
            keys = role_keys.setdefault(project_id, set())
            if role_key in keys:
                continue
            keys.add(role_key)
            linked_project_entry["roles"].append(
                {
                    "role": role,
                    "organization_name": organization_name or None,
                    "state": "current",
                    "evidence": evidence_doc,
                }
            )

    id_rows: list[dict[str, Any]] = []
    alias_rows: list[dict[str, Any]] = []
    for item in identifiers:
        source = session.get(BuyingChainEvidence, item.source_evidence_id)
        if (
            source is None
            or source.content_hash != item.source_version_hash
            or source.id not in current_company_evidence.get(source.project_id, set())
        ):
            continue
        entry = {
            "identifier_type": item.identifier_type,
            "value": item.normalized_value,
            "evidence": _buying_evidence(session, source),
        }
        is_alias = item.identifier_type in {"alias", "dba", "legal_name", "brand"}
        (alias_rows if is_alias else id_rows).append(entry)

    assertions = session.scalars(
        select(CompanyRelationshipAssertion)
        .where(
            (CompanyRelationshipAssertion.source_company_id == company_id)
            | (CompanyRelationshipAssertion.target_company_id == company_id)
        )
        .order_by(CompanyRelationshipAssertion.created_at.desc())
        .limit(GRAPH_ASSERTION_LIMIT)
    ).all()
    relationships: list[dict[str, Any]] = []
    for assertion in assertions:
        source = session.get(BuyingChainEvidence, assertion.source_evidence_id)
        if (
            source is None
            or source.content_hash != assertion.source_version_hash
            or not _buying_evidence_current(session, source)
        ):
            continue
        state, version, correction_id = _relationship_state(session, assertion)
        relationships.append(
            {
                "id": str(assertion.id),
                "source_company_id": str(assertion.source_company_id),
                "target_company_id": str(assertion.target_company_id),
                "relationship_type": assertion.relationship_type,
                "status": state,
                "version": version,
                "correction_id": correction_id,
                "reason": assertion.reason,
                "evidence": _buying_evidence(session, source),
            }
        )

    return {
        "company": {
            "id": str(company.id),
            "display_name": display_name
            or (
                f"RRC operator {company.rrc_operator_number}"
                if company.rrc_operator_number
                else None
            ),
            "identifiers": id_rows,
            "aliases": alias_rows,
        },
        "projects": list(projects.values()),
        "relationships": relationships,
        "evidence": list(evidence_by_id.values()),
        "limits": {"projects": GRAPH_PROJECT_LIMIT, "relationships": GRAPH_ASSERTION_LIMIT},
    }


def assert_company_relationship(
    session: Session,
    *,
    source_company_id: UUID,
    target_company_id: UUID,
    relationship_type: str,
    source_evidence_id: UUID,
    source_version_hash: str,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> CompanyRelationshipAssertion:
    """Append a manually attributed, source-version-bound relationship assertion."""
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError("Unsupported company relationship type")
    if source_company_id == target_company_id:
        raise ValueError("A company cannot be related to itself")
    if not all(value and value.strip() for value in (reason, actor, idempotency_key)):
        raise ValueError("Reason, actor, and idempotency key are required")
    for identity_id in (source_company_id, target_company_id):
        if session.get(CompanyIdentity, identity_id) is None:
            raise LookupError("Company identity not found")
    source = session.get(BuyingChainEvidence, source_evidence_id)
    if (
        source is None
        or source.content_hash != source_version_hash
        or not _buying_evidence_current(session, source)
    ):
        raise ValueError("Relationship evidence hash must match the retained source version")
    existing = session.scalar(
        select(CompanyRelationshipAssertion).where(
            CompanyRelationshipAssertion.idempotency_key == idempotency_key
        )
    )
    if existing:
        matches = (
            existing.source_company_id == source_company_id
            and existing.target_company_id == target_company_id
            and existing.relationship_type == relationship_type
            and existing.source_evidence_id == source_evidence_id
            and existing.source_version_hash == source_version_hash
            and existing.reason == reason.strip()
        )
        if not matches:
            raise ValueError("Idempotency key was already used for a different assertion")
        return existing
    row = CompanyRelationshipAssertion(
        source_company_id=source_company_id,
        target_company_id=target_company_id,
        relationship_type=relationship_type,
        source_evidence_id=source_evidence_id,
        source_version_hash=source_version_hash,
        reason=reason.strip(),
        actor=actor.strip(),
        idempotency_key=idempotency_key.strip(),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def correct_company_relationship(
    session: Session,
    assertion_id: UUID,
    *,
    expected_version: int,
    action: str,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> CompanyRelationshipCorrection:
    """Append a correction event with optimistic version and idempotency guards."""
    if action not in {"retract", "suppress", "reinstate"}:
        raise ValueError("Action must be retract, suppress, or reinstate")
    if not all(value and value.strip() for value in (reason, actor, idempotency_key)):
        raise ValueError("Reason, actor, and idempotency key are required")
    assertion = session.scalar(
        select(CompanyRelationshipAssertion)
        .where(CompanyRelationshipAssertion.id == assertion_id)
        .with_for_update()
    )
    if assertion is None:
        raise LookupError("Company relationship assertion not found")
    existing = session.scalar(
        select(CompanyRelationshipCorrection).where(
            CompanyRelationshipCorrection.assertion_id == assertion_id,
            CompanyRelationshipCorrection.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if (
            existing.expected_version != expected_version
            or existing.action != action
            or existing.reason != reason.strip()
        ):
            raise ValueError("Idempotency key was already used for a different correction")
        return existing
    state, version, _ = _relationship_state(session, assertion)
    if version != expected_version:
        raise RuntimeError("Company relationship correction version is stale")
    if action == "reinstate" and state not in {"retracted", "suppressed"}:
        raise ValueError("Only suppressed or retracted relationships can be reinstated")
    if action in {"retract", "suppress"} and state != "current":
        raise ValueError("Only current relationships can be retracted or suppressed")
    row = CompanyRelationshipCorrection(
        assertion_id=assertion_id,
        expected_version=version,
        version=version + 1,
        action=action,
        reason=reason.strip(),
        actor=actor.strip(),
        idempotency_key=idempotency_key.strip(),
    )
    session.add(row)
    session.flush()
    return row
