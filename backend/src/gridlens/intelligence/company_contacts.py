"""Company contact read model over retained, version-checked buying-chain claims.

No name joins, provider requests, qualification writes, or inferred addresses.
Claim/evidence tables remain the append-only source of contact history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, union
from sqlalchemy.orm import Session

from gridlens.domain.evaluation_clock import evaluation_now
from gridlens.domain.opportunity_intelligence import IntelligenceContact, contact_projection
from gridlens.intelligence.buying_chain import buying_chain_views
from gridlens.intelligence.contact_suppressions import apply_contact_suppressions
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyProjectMembership,
    PowerNeed,
    Project,
)


class CompanyContact(IntelligenceContact):
    company_id: UUID
    company_identity_id: str | None = None
    person_identity_id: str | None = None
    project_ids: list[UUID] = Field(default_factory=list)
    verification_status: str = "Source verified; reachability and authority unconfirmed"
    confidence: str = (
        "Literal method attributed to this company in current retained evidence; "
        "deliverability and authority unconfirmed"
    )
    phone_type: str = "unknown"
    assertion_status: str = "published"
    mailbox_verified: bool = False
    verification_basis: str | None = None
    independent_verification: str = "UNKNOWN_UNSUPPORTED"


def relevant_named_contact(contact: IntelligenceContact) -> bool:
    return bool(relevant_named_professional(contact) and contact.methods)


def relevant_named_professional(contact: IntelligenceContact) -> bool:
    return bool(
        contact.name
        and contact.responsibility
        in {
            "Verified project responsibility",
            "Verified organizational responsibility",
            "Inferred likely role",
        }
        and contact.role not in {"unknown", "permit applicant"}
    )


class ImportedCompanyContact(BaseModel):
    import_row_id: str
    batch_id: str
    sheet: str
    row_number: int
    company: str | None
    name: str | None
    title: str | None
    email: str | None
    phone: str | None
    profile_url: str | None
    assertion_status: str = "imported_unverified"
    mailbox_verified: bool = False


class CompanyContacts(BaseModel):
    company_id: UUID
    contacts: list[CompanyContact] = Field(default_factory=list)
    published_company_roles: list[PublishedCompanyRole] = Field(default_factory=list)
    research_required: bool = True
    imported_unverified: list[ImportedCompanyContact] = Field(default_factory=list)


class PublishedCompanyRole(BaseModel):
    """Company roster assertion, with no implied project assignment or methods."""

    company_identity_id: str
    name: str
    title: str
    role: str
    responsibility: str = "Published company role; project involvement unverified"
    person_project_relationship: str = "UNKNOWN"
    source_url: str
    source_title: str
    source_quote: str
    source_hash: str
    observed_at: str
    valid_until: str
    published_at: str | None = None
    methods: list[dict[str, str]] = Field(default_factory=list)
    project_ids: list[UUID] = Field(default_factory=list)
    verification_status: str = (
        "Published company role; current employment and project involvement unverified"
    )


def project_contacts(company_id: UUID, views: dict) -> CompanyContacts:
    """Use identities attached by the correction-aware buying-chain view only."""
    grouped: dict[tuple, CompanyContact] = {}
    for project_id, view in views.items():
        candidates = [
            c
            for c in view.get("candidates", [])
            if str(c.get("company_identity_id")) == str(company_id)
        ]
        candidate_by_claim = {str(candidate.get("id")): candidate for candidate in candidates}
        for contact in contact_projection({"candidates": candidates}):
            if not contact.methods and not relevant_named_professional(contact):
                continue
            # Keep different people/roles separate even when sharing a switchboard.
            key = (
                contact.name,
                contact.title,
                contact.role,
                contact.responsibility,
                tuple(sorted((m["kind"], m["href"]) for m in contact.methods)),
            )
            if key not in grouped:
                grouped[key] = CompanyContact(
                    **contact.model_dump(),
                    company_id=company_id,
                    company_identity_id=str(company_id),
                    person_identity_id=(
                        str(candidate_by_claim.get(contact.claim_id, {}).get("person_identity_id"))
                        if candidate_by_claim.get(contact.claim_id, {}).get("person_identity_id")
                        else None
                    ),
                    project_ids=[project_id],
                    confidence=(
                        "Literal method attributed to this company in current retained evidence; "
                        "deliverability and authority unconfirmed"
                        if contact.methods
                        else "Published role; no verified direct contact method"
                    ),
                )
            else:
                previous = grouped[key]
                if project_id not in previous.project_ids:
                    previous.project_ids.append(project_id)
                for source in contact.sources:
                    if source not in previous.sources:
                        previous.sources.append(source)
    contacts = sorted(
        grouped.values(),
        key=lambda c: (
            c.name is None,
            c.responsibility != "Verified project responsibility",
            not any(m["kind"] == "email" for m in c.methods),
            c.company,
            c.name or "",
            c.claim_id,
        ),
    )
    return CompanyContacts(
        company_id=company_id,
        contacts=contacts,
        research_required=not any(relevant_named_contact(c) for c in contacts),
    )


def _published_company_roles(
    session: Session,
    company_id: UUID,
    project_ids: set[UUID],
    views: dict,
    *,
    now: datetime,
) -> list[PublishedCompanyRole]:
    if not project_ids:
        return []
    # Roster URLs describe the company, not a project. Select the newest
    # immutable capture across every current project anchor for this company so
    # an older link on another project cannot resurrect a withdrawn person.
    from sqlalchemy import func

    ranked = (
        select(
            BuyingChainEvidence,
            func.dense_rank()
            .over(
                partition_by=BuyingChainEvidence.url,
                order_by=BuyingChainEvidence.last_seen_at.desc(),
            )
            .label("version_rank"),
        )
        .where(BuyingChainEvidence.project_id.in_(project_ids))
        .subquery()
    )
    sources = session.scalars(
        select(BuyingChainEvidence)
        .join(ranked, ranked.c.id == BuyingChainEvidence.id)
        .where(ranked.c.version_rank == 1)
    ).all()
    latest_hashes_by_url: dict[str, set[str]] = {}
    for source in sources:
        latest_hashes_by_url.setdefault(source.url, set()).add(source.content_hash)
    source_project_ids = {source.project_id for source in sources}
    source_projects = {
        project.id: project
        for project in session.scalars(
            select(Project).where(Project.id.in_(source_project_ids))
        ).all()
    }
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import (
        Extracted,
        exact_native_company_roster_page,
        extract_people,
    )
    from gridlens.intelligence.company_contact_attribution import _source_hash_is_current

    grouped: dict[tuple[str, str, str], PublishedCompanyRole] = {}
    for source in sources:
        # Different bytes at an indistinguishable latest capture time have no
        # defensible chronology. Withhold that URL instead of letting UUID
        # order decide whether a removed person reappears.
        if len(latest_hashes_by_url.get(source.url, set())) > 1:
            continue
        if source.project_match_reason != "Exact actor-name company-domain roster; roles only.":
            continue
        project_id = str(source.project_id)
        source_project = source_projects.get(source.project_id)
        view = views.get(project_id)
        if view is None or source_project is None:
            continue
        anchors = [
            candidate
            for candidate in view.get("candidates", [])
            if not candidate.get("person_name")
            and not candidate.get("stale")
            and not candidate.get("correction_stale")
            and not candidate.get("retracted")
            and not candidate.get("suppressed")
            and candidate.get("organization_relationship") == "DIRECT"
            and str(candidate.get("company_identity_id")) == str(company_id)
            and any(
                citation.get("supports") == "project_organization"
                and citation.get("current_support")
                for citation in candidate.get("evidence", [])
            )
        ]
        if not anchors:
            continue
        native_company_source_urls = [
            str(citation.get("url"))
            for anchor_candidate in anchors
            for citation in anchor_candidate.get("evidence", [])
            if citation.get("supports") == "project_organization"
            and citation.get("current_support")
            and citation.get("url")
        ]
        observed = (
            source.observed_at.replace(tzinfo=UTC)
            if source.observed_at.tzinfo is None
            else source.observed_at.astimezone(UTC)
        )
        last_seen = (
            source.last_seen_at.replace(tzinfo=UTC)
            if source.last_seen_at.tzinfo is None
            else source.last_seen_at.astimezone(UTC)
        )
        if (
            observed > last_seen
            or last_seen > now
            or now - last_seen > timedelta(days=30)
            or not _source_hash_is_current(source)
        ):
            continue
        document = PublicDocument(
            url=source.url,
            title=source.title,
            text=source.excerpt,
            published_at=source.published_at,
            observed_at=source.last_seen_at,
            extraction_location=source.extraction_location,
        )
        anchor = anchors[0]
        organization = str(anchor.get("organization") or "")
        if not exact_native_company_roster_page(
            document,
            organization,
            native_company_source_urls=native_company_source_urls,
        ):
            continue
        seed = Extracted(
            organization,
            str(anchor.get("category") or "owner"),
            organization_relationship="DIRECT",
        )
        for parsed in extract_people(
            document,
            [seed],
            source_project,
            project_scoped=False,
            today=now.date(),
            verified_official_roster=True,
            company_only_role=True,
        ):
            role_quote = next(
                (
                    citation.get("quote")
                    for citation in parsed.citations
                    if citation.get("supports") == "organization_person_role"
                ),
                None,
            )
            if not role_quote:
                continue
            key = (parsed.person_name or "", parsed.title or "", source.url)
            if not key[0] or not key[1]:
                continue
            grouped[key] = PublishedCompanyRole(
                company_identity_id=str(company_id),
                name=key[0],
                title=key[1],
                role=parsed.category,
                source_url=source.url,
                source_title=source.title,
                source_quote=role_quote,
                source_hash=source.content_hash,
                observed_at=last_seen.isoformat(),
                valid_until=(last_seen + timedelta(days=30)).isoformat(),
                published_at=source.published_at.isoformat() if source.published_at else None,
            )
    return sorted(grouped.values(), key=lambda item: (item.name.casefold(), item.title.casefold()))


def company_contacts(session: Session, company_id: UUID) -> CompanyContacts:
    eligible = select(Project.id).where(
        Project.region_status == "ELIGIBLE",
        select(PowerNeed.id)
        .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
        .exists(),
    )
    project_ids = set(
        session.scalars(
            union(
                select(BuyingChainClaim.project_id)
                .join(
                    BuyingChainIdentityLink, BuyingChainIdentityLink.claim_id == BuyingChainClaim.id
                )
                .where(
                    BuyingChainIdentityLink.company_identity_id == company_id,
                    BuyingChainIdentityLink.state == "current",
                    BuyingChainClaim.project_id.in_(eligible),
                ),
                select(CompanyProjectMembership.project_id).where(
                    CompanyProjectMembership.company_identity_id == company_id,
                    CompanyProjectMembership.state == "current",
                    CompanyProjectMembership.project_id.in_(eligible),
                ),
            )
        )
    )
    views = buying_chain_views(session, project_ids) if project_ids else {}
    result = project_contacts(company_id, views)
    result.contacts = apply_contact_suppressions(session, company_id, result.contacts)
    result.published_company_roles = apply_contact_suppressions(
        session,
        company_id,
        _published_company_roles(
            session,
            company_id,
            project_ids,
            views,
            now=evaluation_now(datetime.now(UTC)),
        ),
    )
    result.research_required = not any(relevant_named_contact(c) for c in result.contacts)
    return result
