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
from gridlens.intelligence.buying_chain_extraction import organization_key
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
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


def _normalized_identifier(identifier_type: str, value: str) -> str:
    if identifier_type == "ein":
        return re.sub(r"\D", "", value)
    return _normalized(value)


def _typed_subject_binding(
    quote: str, identifier_type: str, normalized_value: str, subject: str
) -> bool:
    """Require an exact typed field and a named subject in the same short passage."""
    if not subject.strip():
        return False
    if identifier_type == "ein":
        digits = re.sub(r"\D", "", normalized_value)
        escaped = f"{re.escape(digits[:2])}-?{re.escape(digits[2:])}"
    else:
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
    normalized = _normalized_identifier(identifier_type, identifier_value)
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
    lookup_values = [normalized]
    if identifier_type == "ein":
        lookup_values.append(f"{normalized[:2]}-{normalized[2:]}")
    identifiers = session.scalars(
        select(IdentityIdentifier)
        .where(
            IdentityIdentifier.entity_type == entity_type,
            IdentityIdentifier.identifier_type == identifier_type,
        )
        .where(IdentityIdentifier.normalized_value.in_(lookup_values))
        .order_by(IdentityIdentifier.normalized_value)
    ).all()
    linked_identity_id: UUID | None
    if not identifiers:
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
        identity_ids = {
            row.company_identity_id if entity_type == "company" else row.person_identity_id
            for row in identifiers
        }
        if None in identity_ids:
            raise ValueError("identity identifier is not linked to a valid identity")
        if len(identity_ids) != 1:
            raise ValueError("equivalent identifier records conflict; identity reuse is ambiguous")
        linked_identity_id = next(iter(identity_ids))
        if (
            linked_identity_id is None
            or session.get(
                CompanyIdentity if entity_type == "company" else PersonIdentity, linked_identity_id
            )
            is None
        ):
            raise ValueError("identity identifier is not linked to a valid identity")
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
    # Membership identity wins before local fallback allocation so a source-bound
    # account never leaves an orphan project-scoped company identity behind.
    _ensure_current_membership_links(session, list(claims.values()), current_by_claim)
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
    _reuse_exact_project_company_for_named_people(session, list(claims.values()), current_by_claim)


def _same_current_project_organization_source(
    person_candidate: dict[str, Any],
    company_candidate: dict[str, Any],
    *,
    person_project_id: UUID,
    company_project_id: UUID,
) -> tuple[str, str] | None:
    """Find exact shared current support for a person-to-company project link.

    This is deliberately narrower than identity resolution: it permits a local
    company-link reuse only when both claims have the same exact organization,
    project, and immutable source version, and that source also explicitly
    assigns the named person an organization role.
    """
    if (
        person_project_id != company_project_id
        or person_candidate.get("suppressed")
        or company_candidate.get("suppressed")
        or person_candidate.get("correction_stale")
        or company_candidate.get("correction_stale")
        or not person_candidate.get("person_name")
        or company_candidate.get("person_name")
        or person_candidate.get("organization_relationship") != "DIRECT"
        or company_candidate.get("organization_relationship") != "DIRECT"
        or person_candidate.get("organization") != company_candidate.get("organization")
    ):
        return None

    def current_citations(candidate: dict[str, Any], support: str) -> dict[str, tuple[str, str]]:
        citations: dict[str, tuple[str, str]] = {}
        for item in candidate.get("evidence", []):
            evidence_id = str(item.get("id") or "")
            content_hash = str(item.get("content_hash") or "")
            if (
                item.get("supports") == support
                and item.get("current_support")
                and evidence_id
                and str(item.get("current_source_version_id")) == evidence_id
                and content_hash
            ):
                citations[evidence_id] = (content_hash, str(item.get("quote") or ""))
        return citations

    person_org = current_citations(person_candidate, "project_organization")
    company_org = current_citations(company_candidate, "project_organization")
    person_role = current_citations(person_candidate, "organization_person_role")
    for evidence_id, (content_hash, quote) in person_org.items():
        if (
            quote
            and person_role.get(evidence_id, (None, None))[0] == content_hash
            and person_role[evidence_id][1]
            and company_org.get(evidence_id) == (content_hash, quote)
        ):
            return evidence_id, content_hash
    return None


def _reuse_exact_project_company_for_named_people(
    session: Session,
    claims: list[BuyingChainClaim],
    current_by_claim: dict[UUID, dict[str, Any]],
) -> None:
    """Align a named person claim to its exact same-source project company.

    This rebinds only an automatic project-scoped company link. It never merges
    identities across projects and leaves reviewed/strong/membership links and
    superseded identity history intact.
    """
    project_by_claim = {claim.id: claim.project_id for claim in claims}
    for person_claim in claims:
        person_candidate = current_by_claim.get(person_claim.id)
        if person_candidate is None or not person_claim.person_name:
            continue
        peers = []
        for peer_id, company_candidate in current_by_claim.items():
            if peer_id == person_claim.id or company_candidate.get("person_name"):
                continue
            peer_project_id = project_by_claim.get(peer_id)
            if peer_project_id is None:
                peer_claim = session.get(BuyingChainClaim, peer_id)
                peer_project_id = peer_claim.project_id if peer_claim is not None else None
            if peer_project_id is None:
                continue
            exact_source = _same_current_project_organization_source(
                person_candidate,
                company_candidate,
                person_project_id=person_claim.project_id,
                company_project_id=peer_project_id,
            )
            if exact_source is not None:
                peers.append((peer_id, exact_source))
        if len(peers) != 1:
            continue

        company_claim_id, (evidence_id, source_hash) = peers[0]
        source = session.get(BuyingChainEvidence, UUID(evidence_id))
        if (
            source is None
            or source.project_id != person_claim.project_id
            or source.content_hash != source_hash
        ):
            continue
        company_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == company_claim_id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        if len(company_links) != 1:
            continue
        company_link = company_links[0]
        company_identity_id = company_link.company_identity_id
        if (
            company_identity_id is None
            or session.get(CompanyIdentity, company_identity_id) is None
            or company_link.source_evidence_id != source.id
            or company_link.source_version_hash != source.content_hash
        ):
            continue

        person_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == person_claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        if len(person_links) > 1:
            continue
        person_link = person_links[0] if person_links else None
        if person_link is not None:
            # Keep explicit review, strong identifier, and accepted membership
            # decisions authoritative. Rebind only the fallback allocated by
            # this same project-scoped identity pass.
            if person_link.company_identity_id == company_identity_id:
                continue
            if person_link.basis != "project_scoped":
                continue
        link_claim_to_identity(
            session,
            person_claim,
            "company",
            company_identity_id,
            source,
            (
                "Named project person and personless organization cite the exact "
                "same current organization source on the same project."
            ),
            _project_scoped=True,
        )


def membership_supports_claim(
    claim: BuyingChainClaim,
    candidate: dict[str, Any],
    membership: CompanyProjectMembership,
    source_id: UUID,
    peers: list[dict[str, Any]],
) -> bool:
    """Bind a typed membership only to its own sourced organization and role.

    A retained article may name several companies. Sharing its Evidence ID is
    not an identity assertion. Named roles inherit the company's typed project
    role only when a current company-only claim establishes it on this source.
    """
    member_key = organization_key(membership.organization_name)
    if (
        not member_key
        or membership.project_id != claim.project_id
        or organization_key(str(candidate.get("organization") or "")) != member_key
        or candidate.get("organization_relationship") != "DIRECT"
    ):
        return False

    def cited_project_relationship(item: dict[str, Any]) -> bool:
        return any(
            str(citation.get("id")) == str(source_id)
            and str(citation.get("current_source_version_id")) == str(source_id)
            and citation.get("current_support")
            and citation.get("supports") == "project_organization"
            and re.search(
                rf"(?<![a-z0-9]){re.escape(member_key)}(?![a-z0-9])",
                organization_key(str(citation.get("quote") or "")),
            )
            for citation in item.get("evidence", [])
        )

    if not cited_project_relationship(candidate):
        return False
    if not candidate.get("person_name"):
        return candidate.get("category") == membership.role
    return any(
        not peer.get("person_name")
        and organization_key(str(peer.get("organization") or "")) == member_key
        and peer.get("organization_relationship") == "DIRECT"
        and peer.get("category") == membership.role
        and cited_project_relationship(peer)
        for peer in peers
    )


def _ensure_current_membership_links(
    session: Session,
    claims: list[BuyingChainClaim],
    current_by_claim: dict[UUID, dict[str, Any]],
) -> None:
    """Bridge a claim only to its exact accepted project membership evidence.

    The membership Evidence and BuyingChainEvidence live in different hash
    domains. Verify both, then the claim's own organization and typed role.
    """
    for claim in claims:
        candidate = current_by_claim.get(claim.id)
        if candidate is None or candidate.get("stale"):
            continue
        memberships = session.scalars(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == claim.project_id,
                CompanyProjectMembership.state == "current",
            )
        ).all()
        matches: list[tuple[CompanyProjectMembership, BuyingChainEvidence]] = []
        for membership in memberships:
            # Membership's source hash is in the retained Evidence domain.
            retained = session.get(Evidence, membership.source_evidence_id)
            if retained is None or retained.content_hash != membership.source_version_hash:
                continue
            for citation in candidate.get("evidence", []):
                if citation.get("supports") != "project_organization" or not citation.get(
                    "current_support"
                ):
                    continue
                source = session.get(BuyingChainEvidence, citation.get("id"))
                if (
                    source is not None
                    and source.project_id == claim.project_id
                    and source.retained_evidence_id == membership.source_evidence_id
                    and citation.get("current_source_version_id") == source.id
                    and citation.get("content_hash") == source.content_hash
                    and membership_supports_claim(
                        claim,
                        candidate,
                        membership,
                        source.id,
                        list(current_by_claim.values()),
                    )
                ):
                    matches.append((membership, source))
        # More than one accepted identity is ambiguity, never a name-merge tie break.
        identity_ids = {membership.company_identity_id for membership, _source in matches}
        if len(identity_ids) != 1:
            continue
        membership, source = matches[0]
        existing = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        )
        if existing and existing.basis in {"attributed_review", "strong_identifier"}:
            try:
                protected_source = _validate_claim_evidence(
                    session,
                    claim,
                    "company",
                    existing.source_evidence_id,
                    current_candidate=candidate,
                )
            except ValueError:
                protected_source = None
            if (
                protected_source is not None
                and protected_source.content_hash == existing.source_version_hash
                and existing.company_identity_id is not None
                and session.get(CompanyIdentity, existing.company_identity_id) is not None
            ):
                continue
        if (
            existing
            and existing.basis == "current_membership"
            and existing.company_identity_id == membership.company_identity_id
            and existing.source_evidence_id == source.id
            and existing.source_version_hash == source.content_hash
        ):
            continue
        if existing:
            existing.state = "superseded"
            existing.superseded_at = datetime.now(UTC)
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=membership.company_identity_id,
                reason="Exact current CompanyProjectMembership evidence cited by this claim.",
                basis="current_membership",
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
        if link.basis == "current_membership":
            link_source = session.get(BuyingChainEvidence, link.source_evidence_id)
            if link_source is None:
                continue
            membership = session.scalar(
                select(CompanyProjectMembership).where(
                    CompanyProjectMembership.project_id == claims[link.claim_id].project_id,
                    CompanyProjectMembership.company_identity_id == link.company_identity_id,
                    CompanyProjectMembership.source_evidence_id == link_source.retained_evidence_id,
                    CompanyProjectMembership.state == "current",
                )
            )
            retained = session.get(Evidence, membership.source_evidence_id) if membership else None
            if (
                membership is None
                or retained is None
                or retained.content_hash != membership.source_version_hash
                or not membership_supports_claim(
                    claims[link.claim_id],
                    candidate,
                    membership,
                    link_source.id,
                    [
                        peer
                        for peer in views[str(claims[link.claim_id].project_id)]["candidates"]
                        if not peer.get("stale")
                    ],
                )
            ):
                continue
        result.setdefault(link.claim_id, {})[f"{link.entity_type}_identity_id"] = str(
            link.company_identity_id if link.entity_type == "company" else link.person_identity_id
        )
    return result
