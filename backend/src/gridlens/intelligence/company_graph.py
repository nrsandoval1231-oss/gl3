"""Correction-aware, evidence-bound read API for canonical company graphs."""

from __future__ import annotations

import re
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
IDENTITY_NAME_TYPES = {"alias", "dba", "legal_name", "brand"}
RELATIONSHIP_TERMS = {
    "parent": re.compile(r"\b(parent|subsidiar(?:y|ies)|owns|owned by|ownership)\b", re.I),
    "subsidiary": re.compile(r"\b(parent|subsidiar(?:y|ies)|owns|owned by|ownership)\b", re.I),
    "developer": re.compile(r"\b(developer|develops|developed|development)\b", re.I),
    "operator": re.compile(r"\b(operator|operates|operated|operation)\b", re.I),
    "epc": re.compile(r"\b(epc|engineering procurement construction)\b", re.I),
    "gc": re.compile(r"\b(gc|general contractor|general contracting)\b", re.I),
    "utility": re.compile(r"\b(utility|utilities|electric provider|power provider)\b", re.I),
}
CLAIM_ROLE_LABELS = {
    "asset_operator": "operator",
    "field_operations": "operator",
    "owner_developer": "developer",
    "general_contractor": "gc",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _retained_current(session: Session, evidence: Evidence, project: Project) -> bool:
    return _retained_evidence_current_for_project(session, project, evidence)


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


def _identity_names_for_source(
    session: Session,
    company_id: UUID,
    source: BuyingChainEvidence,
    current_view: dict[str, Any],
) -> set[str]:
    """Names explicitly bound to this company by current evidence for this source."""
    names: set[str] = set()
    for candidate in current_view.get("candidates", []):
        if str(candidate.get("company_identity_id")) != str(company_id):
            continue
        has_source_support = any(
            str(item.get("id")) == str(source.id)
            and str(item.get("current_source_version_id")) == str(source.id)
            and item.get("content_hash") == source.content_hash
            and item.get("current_support")
            for item in candidate.get("evidence", [])
        )
        organization = candidate.get("organization")
        if has_source_support and isinstance(organization, str) and organization.strip():
            names.add(organization.strip())

    identifiers = session.scalars(
        select(IdentityIdentifier).where(
            IdentityIdentifier.entity_type == "company",
            IdentityIdentifier.company_identity_id == company_id,
            IdentityIdentifier.source_evidence_id == source.id,
            IdentityIdentifier.identifier_type.in_(IDENTITY_NAME_TYPES),
            IdentityIdentifier.source_version_hash == source.content_hash,
        )
    ).all()
    names.update(
        identifier.normalized_value.strip()
        for identifier in identifiers
        if identifier.normalized_value.strip()
    )
    return names


def _relationship_source_binding(
    session: Session,
    source_company_id: UUID,
    target_company_id: UUID,
    relationship_type: str,
    source: BuyingChainEvidence,
    current_view: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """Require two distinct, current identity names literally named with a role term."""
    excerpt_folded = source.excerpt.casefold()
    view = current_view or buying_chain_views(session, {source.project_id}).get(
        str(source.project_id), {}
    )
    source_names = _identity_names_for_source(session, source_company_id, source, view)
    target_names = _identity_names_for_source(session, target_company_id, source, view)
    term = RELATIONSHIP_TERMS[relationship_type]
    for source_name in sorted(source_names, key=str.casefold):
        source_folded = source_name.casefold()
        if source_folded not in excerpt_folded:
            continue
        for target_name in sorted(target_names, key=str.casefold):
            target_folded = target_name.casefold()
            if target_folded == source_folded or target_folded not in excerpt_folded:
                continue
            relationship_context = re.sub(
                re.escape(target_name),
                " ",
                re.sub(re.escape(source_name), " ", source.excerpt, flags=re.IGNORECASE),
                flags=re.IGNORECASE,
            )
            if term.search(relationship_context):
                return source_name, target_name
    return None


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
        "retract": "retracted",
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
    relationship_views: dict[UUID, dict[str, Any]] = {}
    for assertion in assertions:
        source = session.get(BuyingChainEvidence, assertion.source_evidence_id)
        if (
            source is None
            or source.content_hash != assertion.source_version_hash
            or not _buying_evidence_current(session, source)
        ):
            continue
        current_view = relationship_views.get(source.project_id)
        if current_view is None:
            current_view = buying_chain_views(session, {source.project_id}).get(
                str(source.project_id), {}
            )
            relationship_views[source.project_id] = current_view
        if (
            _relationship_source_binding(
                session,
                assertion.source_company_id,
                assertion.target_company_id,
                assertion.relationship_type,
                source,
                current_view,
            )
            is None
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
                "support_status": "operator_assertion_unverified",
                "source_quote": source.excerpt,
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
