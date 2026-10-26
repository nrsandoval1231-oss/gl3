"""Safe contact assertion labels and append-only corrections over canonical claims.

This module deliberately stores no second contact database. Workbook contacts
stay in immutable external import rows; active contacts remain the existing
correction-aware company_contacts projection.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.company_contacts import company_contacts
from gridlens.persistence.models import (
    ExternalImportActivation,
    ExternalImportRow,
)

CONTACT_ASSERTION_STATUSES = frozenset(
    {"imported_unverified", "inferred", "published", "independently_verified"}
)
INDEPENDENT_VERIFICATION_SUPPORTED = False
CONTACT_KINDS = frozenset({"email", "phone", "profile", "website", "general"})


def contact_assertion_status(
    *,
    imported: bool = False,
    inferred: bool = False,
    published: bool = False,
    verification_basis: str | None = None,
    mailbox_confirmed: bool = False,
) -> dict[str, Any]:
    """Classify contact provenance; MX/domain observations never verify a mailbox."""
    if imported:
        status = "imported_unverified"
    elif inferred:
        status = "inferred"
    elif published:
        status = "published"
    else:
        status = "inferred"
    return {
        "assertion_status": status,
        "mailbox_verified": False,
        "verification_basis": None,
        "independent_verification": "UNKNOWN_UNSUPPORTED",
    }


def project_contact_assertions(session: Session, company_id: UUID) -> dict[str, Any]:
    """Expose canonical published/inferred contacts beside separate raw imports."""
    canonical = company_contacts(session, company_id)
    contacts: list[dict[str, Any]] = []
    for contact in canonical.contacts:
        inferred = contact.responsibility == "Inferred likely role"
        label = contact_assertion_status(
            inferred=inferred,
            published=bool(contact.methods),
        )
        contacts.append({**contact.model_dump(mode="json"), **label})

    imported: list[dict[str, Any]] = []
    activated_rows = session.execute(
        select(ExternalImportRow, ExternalImportActivation)
        .join(ExternalImportActivation, ExternalImportActivation.row_id == ExternalImportRow.id)
        .where(
            ExternalImportActivation.active.is_(True),
            ExternalImportRow.company_match["status"].as_string() == "matched",
            ExternalImportRow.company_match["candidate_id"].as_string() == str(company_id),
        )
        .order_by(ExternalImportRow.created_at.desc(), ExternalImportRow.id)
        .limit(100)
    ).all()
    for row, _activation in activated_rows:
        raw = row.normalized or {}
        if not any(raw.get(key) for key in ("contact_name", "email", "phone", "profile_url")):
            continue
        imported.append(
            {
                "import_row_id": str(row.id),
                "batch_id": str(row.batch_id),
                "sheet": row.sheet,
                "row_number": row.row_number,
                "company": raw.get("company_name"),
                "name": raw.get("contact_name"),
                "title": raw.get("title"),
                "email": raw.get("email"),
                "phone": raw.get("phone"),
                "profile_url": raw.get("profile_url"),
                **contact_assertion_status(imported=True),
            }
        )
    return {
        "company_id": str(company_id),
        "contacts": contacts,
        "imported_unverified": imported,
        "research_required": canonical.research_required,
    }
