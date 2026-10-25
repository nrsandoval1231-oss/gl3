"""Company contact read model over retained, version-checked buying-chain claims.

No name joins, provider requests, qualification writes, or inferred addresses.
Claim/evidence tables remain the append-only source of contact history.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.opportunity_intelligence import IntelligenceContact, contact_projection
from gridlens.intelligence.buying_chain import buying_chain_views
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainIdentityLink,
    PowerNeed,
    Project,
)


class CompanyContact(IntelligenceContact):
    company_id: UUID
    project_ids: list[UUID] = Field(default_factory=list)
    verification_status: str = "Source verified; reachability and authority unconfirmed"
    confidence: str = "High: literal contact method in current retained evidence"
    phone_type: str = "unknown"


def relevant_named_contact(contact: IntelligenceContact) -> bool:
    return bool(
        contact.name
        and contact.methods
        and contact.responsibility
        in {
            "Verified project responsibility",
            "Verified organizational responsibility",
            "Inferred likely role",
        }
        and contact.role not in {"unknown", "permit applicant"}
    )


class CompanyContacts(BaseModel):
    company_id: UUID
    contacts: list[CompanyContact] = Field(default_factory=list)
    research_required: bool = True


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
            if not contact.methods:
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
                    **contact.model_dump(), company_id=company_id, project_ids=[project_id]
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
    project_ids = set(
        session.scalars(
            select(BuyingChainClaim.project_id)
            .join(BuyingChainIdentityLink, BuyingChainIdentityLink.claim_id == BuyingChainClaim.id)
            .join(Project, Project.id == BuyingChainClaim.project_id)
            .where(
                BuyingChainIdentityLink.company_identity_id == company_id,
                BuyingChainIdentityLink.state == "current",
                Project.region_status == "ELIGIBLE",
                select(PowerNeed.id)
                .where(PowerNeed.project_id == Project.id, PowerNeed.active.is_(True))
                .exists(),
            )
            .distinct()
        )
    )
    return project_contacts(
        company_id, buying_chain_views(session, project_ids) if project_ids else {}
    )
