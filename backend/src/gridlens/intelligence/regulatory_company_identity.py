"""Bind SEC issuer/domain proof to already-supported project company claims.

All source acquisition is owned by the existing bounded buying-chain pass. This
module only validates and joins its retained documents; it never fetches data.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import document_content_hash
from gridlens.intelligence.company_domain_proof import (
    CompanyDomainProof,
    DomainProofSource,
    parse_sec_domain_assertion,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    CompanyProjectMembership,
    IdentityIdentifier,
)
from gridlens.persistence.suppression_models import ContactSuppression

SEC_DOMAIN_IDENTIFIER = "sec_official_domain"
_MAX_OBSERVED_AGE = timedelta(days=30)
_MAX_PUBLISHED_AGE = timedelta(days=400)


class CompanyDomainProofContext:
    """Bulk-loaded immutable proof rows for one projection pass."""

    def __init__(self):
        self.identifiers_by_company: dict[UUID, list[IdentityIdentifier]] = defaultdict(list)
        self.sources_by_id: dict[UUID, BuyingChainEvidence] = {}
        self.latest_by_url: dict[str, BuyingChainEvidence] = {}
        self.proof_cache: dict[tuple[object, ...], CompanyDomainProof | None] = {}


def load_company_domain_proof_context(
    session: Session, company_ids: Iterable[UUID]
) -> CompanyDomainProofContext:
    context = CompanyDomainProofContext()
    ids = set(company_ids)
    if not ids or len(ids) > 128:
        return context
    identifiers = session.scalars(
        select(IdentityIdentifier)
        .where(
            IdentityIdentifier.entity_type == "company",
            IdentityIdentifier.company_identity_id.in_(ids),
            IdentityIdentifier.identifier_type.in_(["ein", SEC_DOMAIN_IDENTIFIER]),
        )
        .order_by(IdentityIdentifier.id)
        .limit(8193)
    ).all()
    if len(identifiers) > 8192:
        return CompanyDomainProofContext()
    for row in identifiers:
        assert row.company_identity_id is not None
        context.identifiers_by_company[row.company_identity_id].append(row)
    if any(len(rows) > 64 for rows in context.identifiers_by_company.values()):
        return CompanyDomainProofContext()
    source_ids = {
        row.source_evidence_id
        for row in identifiers
        if row.identifier_type == SEC_DOMAIN_IDENTIFIER
    }
    if not source_ids:
        return context
    for source in session.scalars(
        select(BuyingChainEvidence)
        .where(BuyingChainEvidence.id.in_(source_ids))
        .order_by(BuyingChainEvidence.id)
    ):
        context.sources_by_id[source.id] = source
    urls = {source.url for source in context.sources_by_id.values()}
    if urls:
        ranked = (
            select(
                BuyingChainEvidence.id.label("id"),
                BuyingChainEvidence.url.label("url"),
                func.row_number()
                .over(
                    partition_by=BuyingChainEvidence.url,
                    order_by=(
                        BuyingChainEvidence.last_seen_at.desc(),
                        BuyingChainEvidence.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .where(BuyingChainEvidence.url.in_(urls))
            .subquery()
        )
        latest_ids = session.scalars(
            select(ranked.c.id).where(ranked.c.rank == 1).limit(len(urls) + 1)
        ).all()
        for source in session.scalars(
            select(BuyingChainEvidence).where(BuyingChainEvidence.id.in_(latest_ids))
        ):
            context.latest_by_url[source.url] = source
    return context


def _domain_host(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.hostname is None
        ):
            return None
        host = parsed.hostname
    except (TypeError, ValueError):
        return None
    return host.casefold().rstrip(".") if host else None


def official_domain_matches_url(domain: str, url: str) -> bool:
    host = _domain_host(url)
    normalized = domain.casefold().removeprefix("www.").rstrip(".")
    return bool(host and (host == normalized or host.endswith(f".{normalized}")))


def _current_and_fresh(
    session: Session,
    source: BuyingChainEvidence,
    now: datetime,
    *,
    latest: BuyingChainEvidence | None = None,
) -> bool:
    if source.observed_at.tzinfo is None:
        observed = source.observed_at.replace(tzinfo=UTC)
    else:
        observed = source.observed_at.astimezone(UTC)
    last_seen = (
        source.last_seen_at.replace(tzinfo=UTC)
        if source.last_seen_at.tzinfo is None
        else source.last_seen_at.astimezone(UTC)
    )
    if observed > last_seen or last_seen > now + timedelta(minutes=5):
        return False
    if last_seen > now or now - last_seen > _MAX_OBSERVED_AGE:
        return False
    if source.published_at is None or source.published_at > now.date():
        return False
    if now.date() - source.published_at > _MAX_PUBLISHED_AGE:
        return False
    if latest is None:
        latest = session.scalar(
            select(BuyingChainEvidence)
            .where(BuyingChainEvidence.url == source.url)
            .order_by(BuyingChainEvidence.last_seen_at.desc(), BuyingChainEvidence.id.desc())
            .limit(1)
        )
    if latest is None or latest.content_hash != source.content_hash:
        return False
    document = PublicDocument(
        source.url,
        source.title,
        source.excerpt,
        source.published_at,
        source.observed_at,
        extraction_location=source.extraction_location,
    )
    return document_content_hash(document) == source.content_hash


def proof_for_company_identity(
    session: Session,
    *,
    source: BuyingChainEvidence,
    company_id: UUID,
    organization: str,
    now: datetime,
    context: CompanyDomainProofContext | None = None,
) -> CompanyDomainProof | None:
    """Revalidate stored SEC domain proof against current EIN and evidence."""
    cache_key = (
        company_id,
        organization,
        source.id,
        source.content_hash,
        now.isoformat(),
    )
    if context is not None and cache_key in context.proof_cache:
        return context.proof_cache[cache_key]

    def result(proof: CompanyDomainProof | None) -> CompanyDomainProof | None:
        if context is not None:
            context.proof_cache[cache_key] = proof
        return proof

    latest = context.latest_by_url.get(source.url) if context is not None else None
    if context is not None and latest is None:
        return result(None)
    if not _current_and_fresh(session, source, now, latest=latest):
        return result(None)
    identifiers = (
        context.identifiers_by_company.get(company_id, [])
        if context is not None
        else session.scalars(
            select(IdentityIdentifier)
            .where(
                IdentityIdentifier.entity_type == "company",
                IdentityIdentifier.company_identity_id == company_id,
            )
            .order_by(IdentityIdentifier.id)
        ).all()
    )
    ein_values = {
        re.sub(r"\D", "", row.normalized_value)
        for row in identifiers
        if row.identifier_type.casefold() == "ein"
        and len(re.sub(r"\D", "", row.normalized_value)) == 9
    }
    if len(ein_values) != 1:
        return result(None)
    proof = parse_sec_domain_assertion(
        cast(DomainProofSource, source),
        organization=organization,
        expected_ein=next(iter(ein_values)),
    )
    if proof is None:
        return result(None)
    domain_rows = [row for row in identifiers if row.identifier_type == SEC_DOMAIN_IDENTIFIER]
    if len(domain_rows) != 1:
        return result(None)
    domain_row = domain_rows[0]
    if (
        domain_row.source_evidence_id != source.id
        or domain_row.source_version_hash != source.content_hash
        or domain_row.normalized_value != proof.domain
    ):
        return result(None)
    return result(proof)


def verified_company_domain_matches(
    session: Session,
    *,
    document: object,
    company_id: UUID,
    organization: str,
    now: datetime | None = None,
    context: CompanyDomainProofContext | None = None,
) -> bool:
    """Check a source host against an independently retained, fresh SEC proof."""
    instant = now or datetime.now(UTC)
    if context is None:
        context = load_company_domain_proof_context(session, [company_id])
    domain_rows = [
        row
        for row in context.identifiers_by_company.get(company_id, [])
        if row.identifier_type == SEC_DOMAIN_IDENTIFIER
    ]
    if len(domain_rows) != 1:
        return False
    source = context.sources_by_id.get(domain_rows[0].source_evidence_id)
    if source is None and not context.sources_by_id:
        source = session.get(BuyingChainEvidence, domain_rows[0].source_evidence_id)
    url = getattr(document, "url", None)
    if source is None or not isinstance(url, str):
        return False
    proof = proof_for_company_identity(
        session,
        source=source,
        company_id=company_id,
        organization=organization,
        now=instant,
        context=context,
    )
    return bool(proof and official_domain_matches_url(proof.domain, url))


def _normalized_company_name(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    equivalents = {
        "inc": "incorporated",
        "incorporated": "incorporated",
        "corp": "corporation",
        "corporation": "corporation",
        "ltd": "limited",
        "limited": "limited",
    }
    if words and words[-1] in equivalents:
        words[-1] = equivalents[words[-1]]
    return " ".join(words)


def _matching_company_identifiers(
    session: Session, identifier_type: str, value: str
) -> list[IdentityIdentifier]:
    if identifier_type == "ein":
        normalized = re.sub(r"\D", "", value)
        if len(normalized) != 9:
            return []
        values = {normalized, f"{normalized[:2]}-{normalized[2:]}"}
    else:
        values = {value}
    return list(
        session.scalars(
            select(IdentityIdentifier)
            .where(
                IdentityIdentifier.entity_type == "company",
                IdentityIdentifier.identifier_type == identifier_type,
                IdentityIdentifier.normalized_value.in_(values),
            )
            .order_by(IdentityIdentifier.id)
            .limit(65)
        ).all()
    )


def _candidate_project_organization_source(
    session: Session, candidate: dict, domain: str
) -> BuyingChainEvidence | None:
    current_rows = [
        row
        for row in candidate.get("evidence", [])
        if row.get("supports") == "project_organization"
        and row.get("current_support")
        and str(row.get("id")) == str(row.get("current_source_version_id"))
    ]
    source_by_id = {}
    for row in current_rows:
        try:
            source_id = UUID(str(row.get("id")))
        except (TypeError, ValueError):
            continue
        source_by_id[str(source_id)] = session.get(BuyingChainEvidence, source_id)
    for source in source_by_id.values():
        if source and official_domain_matches_url(domain, source.url):
            return source
    return None


def bind_sec_domain_proofs_to_current_claims(
    session: Session,
    *,
    project_id: UUID,
    claim_ids: Iterable[str],
    sec_evidence_ids: Iterable[UUID],
    now: datetime,
) -> int:
    """Bind unambiguous SEC issuer proofs only to matching current site claims."""
    from gridlens.intelligence.buying_chain import _buying_chain_current_view
    from gridlens.intelligence.identity_reconciliation import (
        _automatic_identity_mutation_allowed,
        _validate_claim_evidence,
        link_claim_to_identity,
    )

    sec_ids = set(sec_evidence_ids)
    if not sec_ids:
        return 0
    # Identity rekeying can change method-level pseudonymous suppression keys.
    # Until the target identity's method aliases can be proven complete, match
    # the existing identity reconciliation guard and fail closed globally.
    if (
        session.scalar(
            select(ContactSuppression.id).where(ContactSuppression.scope == "method").limit(1)
        )
        is not None
    ):
        return 0
    candidates = {
        str(row["id"]): row
        for row in _buying_chain_current_view(session, project_id, now=now)["candidates"]
        if not row.get("stale")
    }
    claims = {
        str(claim.id): claim
        for claim in session.scalars(
            select(BuyingChainClaim).where(
                BuyingChainClaim.id.in_([UUID(value) for value in claim_ids])
            )
        )
    }
    sec_sources = [
        source
        for source in session.scalars(
            select(BuyingChainEvidence)
            .where(BuyingChainEvidence.id.in_(sec_ids))
            .order_by(BuyingChainEvidence.id)
        )
        if _current_and_fresh(session, source, now)
    ]
    bound = 0
    for claim_id, candidate in candidates.items():
        claim = claims.get(claim_id)
        if claim is None or claim.person_name is not None or not claim.organization.strip():
            continue
        project_source = None
        selected: tuple[BuyingChainEvidence, CompanyDomainProof] | None = None
        for sec_source in sec_sources:
            proof = parse_sec_domain_assertion(
                cast(DomainProofSource, sec_source), organization=claim.organization
            )
            if proof is None:
                continue
            matching_project_source = _candidate_project_organization_source(
                session, candidate, proof.domain
            )
            if matching_project_source is not None:
                identity_tuple = (
                    _normalized_company_name(proof.issuer_name),
                    re.sub(r"\D", "", proof.ein),
                    proof.domain,
                )
                if selected is not None:
                    selected_identity_tuple = (
                        _normalized_company_name(selected[1].issuer_name),
                        re.sub(r"\D", "", selected[1].ein),
                        selected[1].domain,
                    )
                    if selected_identity_tuple != identity_tuple:
                        selected = None
                        project_source = None
                        break
                    selected_source = selected[0]
                    if (sec_source.last_seen_at, sec_source.published_at) <= (
                        selected_source.last_seen_at,
                        selected_source.published_at,
                    ):
                        continue
                selected = sec_source, proof
                project_source = matching_project_source
        if selected is None or project_source is None:
            continue

        sec_source, proof = selected
        existing_ein = _matching_company_identifiers(session, "ein", proof.ein)
        if len(existing_ein) > 64:
            continue
        equivalent_identity_ids = {
            row.company_identity_id for row in existing_ein if row.company_identity_id
        }
        if len(equivalent_identity_ids) > 1:
            continue
        identity_id = next(iter(equivalent_identity_ids), None)

        existing_domain = _matching_company_identifiers(
            session, SEC_DOMAIN_IDENTIFIER, proof.domain
        )
        if len(existing_domain) > 64:
            continue
        if any(
            row.company_identity_id not in ({identity_id} if identity_id else set())
            for row in existing_domain
        ):
            continue
        if identity_id is not None:
            other_domains = session.scalars(
                select(IdentityIdentifier.normalized_value).where(
                    IdentityIdentifier.entity_type == "company",
                    IdentityIdentifier.company_identity_id == identity_id,
                    IdentityIdentifier.identifier_type == SEC_DOMAIN_IDENTIFIER,
                )
            ).all()
            if set(other_domains) - {proof.domain}:
                continue

        current_memberships = session.scalars(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == claim.project_id,
                CompanyProjectMembership.state == "current",
            )
        ).all()
        same_name_memberships = [
            membership
            for membership in current_memberships
            if _normalized_company_name(membership.organization_name)
            == _normalized_company_name(claim.organization)
        ]
        if identity_id is not None and any(
            membership.company_identity_id != identity_id for membership in same_name_memberships
        ):
            continue

        identity = session.get(CompanyIdentity, identity_id) if identity_id else None
        if identity_id is not None and identity is None:
            continue
        proposed_id = identity.id if identity else uuid4()
        current_links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == "company",
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        if any(
            link.company_identity_id != proposed_id and link.basis != "project_scoped"
            for link in current_links
        ):
            continue
        lineage = [claim]
        if not _automatic_identity_mutation_allowed(
            session, lineage, proposed_company_ids={proposed_id}
        ):
            continue
        try:
            validated_project_source = _validate_claim_evidence(
                session,
                claim,
                "company",
                project_source.id,
                current_candidate=candidate,
            )
        except ValueError:
            continue

        if identity is None:
            identity = CompanyIdentity(id=proposed_id)
            session.add(identity)
            session.flush()
        if not existing_ein:
            session.add(
                IdentityIdentifier(
                    entity_type="company",
                    company_identity_id=identity.id,
                    identifier_type="ein",
                    normalized_value=proof.ein,
                    source_evidence_id=sec_source.id,
                    source_version_hash=sec_source.content_hash,
                    reason=(
                        "SEC filing matched the exact issuer, EIN and official domain statement."
                    ),
                )
            )
        domain_rows = [
            row
            for row in existing_domain
            if row.company_identity_id == identity.id and row.normalized_value == proof.domain
        ]
        if domain_rows:
            domain_row = domain_rows[0]
            domain_row.source_evidence_id = sec_source.id
            domain_row.source_version_hash = sec_source.content_hash
            domain_row.reason = "Current SEC filing proves the issuer's official domain."
        else:
            session.add(
                IdentityIdentifier(
                    entity_type="company",
                    company_identity_id=identity.id,
                    identifier_type=SEC_DOMAIN_IDENTIFIER,
                    normalized_value=proof.domain,
                    source_evidence_id=sec_source.id,
                    source_version_hash=sec_source.content_hash,
                    reason="Current SEC filing proves the issuer's official domain.",
                )
            )
        session.flush()

        link_claim_to_identity(
            session,
            claim,
            "company",
            identity.id,
            validated_project_source,
            (
                "SEC issuer EIN and independent official-domain proof matched current project "
                "organization evidence."
            ),
            _strong_identifier=True,
            current_candidate=candidate,
        )
        bound += 1
    return bound
