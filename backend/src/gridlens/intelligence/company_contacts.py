"""Company contact read model over retained, version-checked buying-chain claims.

No name joins, provider requests, qualification writes, or inferred addresses.
Claim/evidence tables remain the append-only source of contact history.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, union
from sqlalchemy.orm import Session

from gridlens.domain.opportunity_intelligence import IntelligenceContact, contact_projection
from gridlens.intelligence.buying_chain import buying_chain_views
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainIdentityLink,
    CompanyProjectMembership,
    PowerNeed,
    Project,
)


class CompanyContact(IntelligenceContact):
    company_id: UUID
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
    research_required: bool = True
    imported_unverified: list[ImportedCompanyContact] = Field(default_factory=list)


def project_contacts(company_id: UUID, views: dict) -> CompanyContacts:
    """Use identities attached by the correction-aware buying-chain view only."""
    grouped: dict[tuple, CompanyContact] = {}
    for project_id, view in views.items():
        candidates = [
            c
            for c in view.get("candidates", [])
            if str(c.get("company_identity_id")) == str(company_id)
        ]
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
    return project_contacts(
        company_id, buying_chain_views(session, project_ids) if project_ids else {}
    )
