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

from gridlens.intelligence.buying_chain_corrections import correct_buying_chain_claim
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


def correct_contact_assertion(
    session: Session,
    *,
    project_id: UUID,
    claim_id: UUID,
    expected_version: str,
    idempotency_key: str,
    action: str,
    kind: str,
    value: str | None,
    reason: str,
    actor: str,
    source_evidence_id: UUID | None = None,
    source_hash: str | None = None,
    verification_basis: str | None = None,
) -> dict[str, Any]:
    """Suppress/replace a method through the canonical append-only claim ledger.

    Source-free replacement is an attributed operator report, not a sourced
    published contact. This correction ledger has no durable independent-mailbox
    verification field, so verification requests remain unsupported; MX/DNS
    observations never verify a mailbox.
    """
    if action not in {"suppress", "replace", "retract"}:
        raise ValueError("Action must be suppress, replace, or retract")
    if action != "retract" and kind not in CONTACT_KINDS:
        raise ValueError("Unsupported contact method kind")
    if not reason.strip() or not actor.strip() or not idempotency_key.strip():
        raise ValueError("Reason, actor, and idempotency key are required")
    if verification_basis is not None:
        raise ValueError(
            "Independent mailbox verification is unsupported; MX/DNS and imported assertions "
            "cannot verify a mailbox"
        )
    if action == "retract":
        if value is not None:
            raise ValueError("A retraction cannot include a replacement contact value")
        row = correct_buying_chain_claim(
            session,
            project_id=project_id,
            claim_id=claim_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            action="retract",
            values={},
            source_evidence_id=None,
            source_hash=None,
            reason=reason,
            actor=actor,
        )
        return {"correction_id": str(row.id), "status": "retracted", "version": str(row.id)}
    if action == "suppress":
        if value not in {None, ""}:
            raise ValueError("Suppression must not provide a replacement value")
        values = {"public_contact_kind": kind, "public_contact_value": ""}
        reported_contact = True
        source_evidence_id = None
        source_hash = None
        verification_basis = None
    else:
        if not value or not value.strip():
            raise ValueError("Replacement contact value is required")
        values = {"public_contact_kind": kind, "public_contact_value": value.strip()}
        reported_contact = source_evidence_id is None
        if reported_contact and verification_basis is None:
            # Details may be retained as a reported method, but are never labeled
            # as verified merely because an operator entered them.
            verification_basis = None
    row = correct_buying_chain_claim(
        session,
        project_id=project_id,
        claim_id=claim_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        action="correct",
        values=values,
        source_evidence_id=source_evidence_id,
        source_hash=source_hash,
        reason=reason,
        actor=actor,
        reported_contact=reported_contact,
    )
    status = (
        "suppressed"
        if action == "suppress"
        else "published"
        if source_evidence_id is not None
        else "operator_report_unverified"
    )
    return {
        "correction_id": str(row.id),
        "status": status,
        "mailbox_verified": False,
        "independent_verification": "UNKNOWN_UNSUPPORTED",
        "version": str(row.id),
    }
