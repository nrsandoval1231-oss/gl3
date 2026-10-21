"""Evidence-bound cross-project identity links for buying-chain claims.

Names and employment are never merge keys. A link is established by a strong
identifier or attributed review and remains attached to its project-scoped claim.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import buying_chain_view, buying_chain_views
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    IdentityIdentifier,
    PersonIdentity,
)

EntityType = Literal["company", "person"]
COMPANY_IDENTIFIERS = {"lei", "ein"}
PERSON_IDENTIFIERS: set[str] = set()


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _valid_lei(value: str) -> bool:
    normalized = _normalized(value).upper()
    if not re.fullmatch(r"[0-9A-Z]{20}", normalized):
        return False
    expanded = "".join(str(ord(char) - 55) if char.isalpha() else char for char in normalized)
    remainder = 0
    for digit in expanded:
        remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _valid_ein(value: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{2}-?\d{7})", value.strip()))


def _typed_subject_binding(
    quote: str, identifier_type: str, normalized_value: str, subject: str
) -> bool:
    """Require an exact typed field and a named subject in the same short passage."""
    if not subject.strip():
        return False
    escaped = re.escape(normalized_value)
    label = (
        r"\b(?:LEI|Legal Entity Identifier)\b"
        if identifier_type == "lei"
        else r"\b(?:US EIN|EIN|Employer Identification Number)\b"
    )
    pattern = rf"{label}\s*(?:number|identifier)?\s*[:#=]?\s*{escaped}\b"
    if not re.search(pattern, quote, re.IGNORECASE):
        return False
    return bool(re.search(re.escape(subject.strip()), quote, re.IGNORECASE))


def _validate_claim_evidence(
    session: Session,
    claim: BuyingChainClaim,
    entity_type: EntityType,
    evidence_id: UUID,
    *,
    current_candidate: dict[str, Any] | None = None,
) -> BuyingChainEvidence:
    row = session.get(BuyingChainEvidence, evidence_id)
    if row is None:
        raise ValueError("identity evidence version does not exist")
    citation = next(
        (
            item
            for item in claim.citations
            if item.get("evidence_id") == str(evidence_id)
            and (
                item.get("supports") == "project_organization"
                if entity_type == "company"
                else str(item.get("supports"))
                in {"organization_person_role", "person_project_assignment"}
            )
            and str(item.get("quote", "")) in row.excerpt
        ),
        None,
    )
    if citation is None:
        raise ValueError("identity evidence must be cited by this claim for the entity type")
    current = current_candidate
    if current is None:
        current = next(
            (
                item
                for item in buying_chain_view(session, claim.project_id)["candidates"]
                if item["id"] == claim.id
            ),
            None,
        )
    if (
        current is None
        or current["stale"]
        or not any(
            item.get("id") == row.id
            and item.get("current_source_version_id") == row.id
            and item.get("content_hash") == row.content_hash
            and item.get("current_support")
            for item in current["evidence"]
        )
    ):
        raise ValueError("identity claim and cited evidence version must be current")
    return row


def reconcile_claim_identity(
    session: Session,
    claim_id: UUID,
    entity_type: EntityType,
    identifier_type: str,
    identifier_value: str,
    source_evidence_id: UUID,
    reason: str,
) -> BuyingChainIdentityLink:
    """Idempotently link one claim using a cited current strong identifier."""
    claim = session.get(BuyingChainClaim, claim_id)
    if claim is None:
        raise ValueError("buying-chain claim does not exist")
    if entity_type not in {"company", "person"}:
        raise ValueError("entity type must be company or person")
    supported = COMPANY_IDENTIFIERS if entity_type == "company" else PERSON_IDENTIFIERS
    if identifier_type not in supported:
        raise ValueError("identifier type is not an approved strong identifier")
    if not identifier_value.strip() or not reason.strip():
        raise ValueError("identifier value and reason are required")
    source = _validate_claim_evidence(session, claim, entity_type, source_evidence_id)
    normalized = _normalized(identifier_value)
    if identifier_type == "lei" and not _valid_lei(identifier_value):
        raise ValueError("LEI must be a checksum-valid 20-character identifier")
    if identifier_type == "ein" and not _valid_ein(identifier_value):
        raise ValueError("EIN must be an exact nine-digit US identifier")
    subject = claim.organization if entity_type == "company" else claim.person_name
    bound = any(
        citation.get("evidence_id") == str(source.id)
        and citation.get("supports")
        == ("project_organization" if entity_type == "company" else "organization_person_role")
        and _typed_subject_binding(
            str(citation.get("quote", "")), identifier_type, normalized, subject or ""
        )
        for citation in claim.citations
    )
    if not bound:
        raise ValueError(
            "typed identifier must be unambiguously bound to the entity in its citation"
        )
    identifier = session.scalar(
        select(IdentityIdentifier).where(
            IdentityIdentifier.entity_type == entity_type,
            IdentityIdentifier.identifier_type == identifier_type,
            IdentityIdentifier.normalized_value == normalized,
        )
    )
    linked_identity_id: UUID | None
    if identifier is None:
        identity = CompanyIdentity() if entity_type == "company" else PersonIdentity()
        session.add(identity)
        session.flush()
        identifier = IdentityIdentifier(
            entity_type=entity_type,
            company_identity_id=identity.id if entity_type == "company" else None,
            person_identity_id=identity.id if entity_type == "person" else None,
            identifier_type=identifier_type,
            normalized_value=normalized,
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
            reason=reason.strip(),
        )
        session.add(identifier)
        session.flush()
        linked_identity_id = identity.id
    else:
        identity_id = (
            identifier.company_identity_id
            if entity_type == "company"
            else identifier.person_identity_id
        )
        found_identity = session.get(
            CompanyIdentity if entity_type == "company" else PersonIdentity, identity_id
        )
        if found_identity is None:
            raise ValueError("identity identifier is not linked to a valid identity")
        linked_identity_id = (
            identifier.company_identity_id
            if entity_type == "company"
            else identifier.person_identity_id
        )
        if linked_identity_id is None:
            raise ValueError("identity identifier is not linked to the requested entity type")
    return link_claim_to_identity(
        session, claim, entity_type, linked_identity_id, source, reason, _strong_identifier=True
    )


def link_claim_to_identity(
    session: Session,
    claim: BuyingChainClaim,
    entity_type: EntityType,
    identity_id: UUID,
    source: BuyingChainEvidence,
    reason: str,
    *,
    reviewed_by: str | None = None,
    _strong_identifier: bool = False,
    _project_scoped: bool = False,
) -> BuyingChainIdentityLink:
    """Set or correct a claim link; prior link remains as superseded history."""
    if not _strong_identifier and not _project_scoped and not (reviewed_by and reviewed_by.strip()):
        raise ValueError("attributed review is required to set an identity link directly")
    _validate_claim_evidence(session, claim, entity_type, source.id)
    identity_model = CompanyIdentity if entity_type == "company" else PersonIdentity
    if session.get(identity_model, identity_id) is None:
        raise ValueError("identity does not exist")
    existing = session.scalar(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id == claim.id,
            BuyingChainIdentityLink.entity_type == entity_type,
            BuyingChainIdentityLink.state == "current",
        )
    )
    identity_field = "company_identity_id" if entity_type == "company" else "person_identity_id"
    if (
        existing
        and getattr(existing, identity_field) == identity_id
        and existing.source_version_hash == source.content_hash
    ):
        return existing
    if existing:
        existing.state = "superseded"
        existing.superseded_at = datetime.now(UTC)
        session.flush()
    link = BuyingChainIdentityLink(
        claim_id=claim.id,
        entity_type=entity_type,
        company_identity_id=identity_id if entity_type == "company" else None,
        person_identity_id=identity_id if entity_type == "person" else None,
        reason=reason.strip(),
        basis=(
            "strong_identifier"
            if _strong_identifier
            else "project_scoped"
            if _project_scoped
            else "attributed_review"
        ),
        reviewed_by=reviewed_by.strip() if reviewed_by else None,
        source_evidence_id=source.id,
        source_version_hash=source.content_hash,
        state="current",
    )
    session.add(link)
    session.flush()
    return link


def ensure_project_scoped_identity_links(session: Session, claim_ids: list[str]) -> None:
    """Give current supported claims stable local IDs without merging by names."""
    if not claim_ids:
        return
    claims = {
        claim.id: claim
        for claim in session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.id.in_([UUID(value) for value in claim_ids])
            )
        ).all()
    }
    views = buying_chain_views(session, {claim.project_id for claim in claims.values()})
    current_by_claim = {
        item["id"]: item
        for view in views.values()
        for item in view["candidates"]
        if not item["stale"]
    }
    for claim_id, claim in claims.items():
        candidate = current_by_claim.get(claim_id)
        if candidate is None:
            continue
        entity_specs: list[tuple[EntityType, str, type[CompanyIdentity] | type[PersonIdentity]]] = [
            ("company", "project_organization", CompanyIdentity)
        ]
        if claim.person_name:
            person_support = (
                "organization_person_role"
                if any(
                    item.get("supports") == "organization_person_role"
                    for item in candidate["evidence"]
                )
                else "person_project_assignment"
            )
            entity_specs.append(("person", person_support, PersonIdentity))
        existing_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim_id,
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        for entity_type, support, identity_model in entity_specs:
            citation = next(
                (
                    item
                    for item in candidate["evidence"]
                    if item.get("supports") == support
                    and item.get("current_source_version_id") == item.get("id")
                    and item.get("current_support")
                ),
                None,
            )
            if citation is None:
                continue
            source = session.get(BuyingChainEvidence, citation["id"])
            if source is None:
                continue
            existing = next(
                (link for link in existing_links if link.entity_type == entity_type), None
            )
            if existing:
                identity_id = (
                    existing.company_identity_id
                    if entity_type == "company"
                    else existing.person_identity_id
                )
                try:
                    linked_source = _validate_claim_evidence(
                        session,
                        claim,
                        entity_type,
                        existing.source_evidence_id,
                        current_candidate=candidate,
                    )
                except ValueError:
                    linked_source = None
                if (
                    linked_source is not None
                    and linked_source.content_hash == existing.source_version_hash
                    and identity_id is not None
                    and session.get(identity_model, identity_id) is not None
                    and (
                        existing.basis == "attributed_review"
                        or (
                            existing.source_evidence_id == source.id
                            and existing.source_version_hash == source.content_hash
                        )
                    )
                ):
                    # Citation order cannot invalidate an explicitly reviewed
                    # link whose own evidence basis is still current.
                    continue
            if existing:
                existing.state = "superseded"
                existing.superseded_at = datetime.now(UTC)
                session.flush()
            identity = identity_model()
            session.add(identity)
            session.flush()
            session.add(
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type=entity_type,
                    company_identity_id=identity.id if entity_type == "company" else None,
                    person_identity_id=identity.id if entity_type == "person" else None,
                    reason="Stable project-scoped claim identity; no cross-project merge inferred.",
                    basis="project_scoped",
                    source_evidence_id=source.id,
                    source_version_hash=source.content_hash,
                    state="current",
                )
            )
            session.flush()


def current_claim_identity_links(
    session: Session, claim_ids: set[UUID]
) -> dict[UUID, dict[str, str]]:
    """Return current links only when the exact source version remains current."""
    if not claim_ids:
        return {}
    result: dict[UUID, dict[str, str]] = {}
    links = session.scalars(
        select(BuyingChainIdentityLink).where(
            BuyingChainIdentityLink.claim_id.in_(claim_ids),
            BuyingChainIdentityLink.state == "current",
        )
    ).all()
    claims = {
        claim.id: claim
        for claim in session.scalars(
            select(BuyingChainClaim).where(BuyingChainClaim.id.in_(claim_ids))
        ).all()
    }
    current_candidates: dict[UUID, dict[str, Any]] = {}
    views = buying_chain_views(session, {claim.project_id for claim in claims.values()})
    for view in views.values():
        for candidate in view["candidates"]:
            current_candidates[candidate["id"]] = candidate
    for link in links:
        candidate = current_candidates.get(link.claim_id)
        if (
            candidate is None
            or candidate["stale"]
            or not any(
                str(item["id"]) == str(link.source_evidence_id)
                and str(item.get("current_source_version_id")) == str(link.source_evidence_id)
                and item.get("content_hash") == link.source_version_hash
                and item.get("current_support")
                for item in candidate["evidence"]
            )
        ):
            continue
        result.setdefault(link.claim_id, {})[f"{link.entity_type}_identity_id"] = str(
            link.company_identity_id if link.entity_type == "company" else link.person_identity_id
        )
    return result
