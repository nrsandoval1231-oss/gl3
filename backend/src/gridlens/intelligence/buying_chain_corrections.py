"""Evidence-checked append-only operator decisions for buying-chain claims."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
)

EDITABLE = {
    "organization",
    "person_name",
    "title",
    "category",
    "organization_relationship",
    "person_organization_relationship",
    "person_project_relationship",
    "public_contact_kind",
    "public_contact_value",
}
ALLOWED_VALUES = {
    "category": {
        "electrical_contractor",
        "general_contractor",
        "epc",
        "commissioning",
        "owner_construction",
        "owner_energy",
        "owner_developer",
        "asset_operator",
        "field_operations",
        "procurement",
        "unknown",
    },
    "organization_relationship": {"DIRECT", "INDIRECT", "UNKNOWN"},
    "person_organization_relationship": {"DIRECT", "INDIRECT", "UNKNOWN"},
    "person_project_relationship": {"DIRECT", "ROLE_SUPPORTED", "UNKNOWN"},
    "public_contact_kind": {"phone", "email", "profile", "website", "general"},
}


def _version(claim: BuyingChainClaim, latest: BuyingChainCorrection | None) -> str:
    return str(latest.id) if latest else claim.fingerprint


def correct_buying_chain_claim(
    session: Session,
    *,
    project_id: UUID,
    claim_id: UUID,
    expected_version: str,
    idempotency_key: str,
    action: str,
    values: dict[str, Any],
    source_evidence_id: UUID | None,
    source_hash: str | None,
    reason: str,
    actor: str,
    reported_contact: bool = False,
    identity_type: str | None = None,
    identity_id: UUID | None = None,
) -> BuyingChainCorrection:
    claim = session.scalar(
        select(BuyingChainClaim)
        .where(
            BuyingChainClaim.id == claim_id,
            BuyingChainClaim.project_id == project_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise LookupError("Buying-chain claim not found in project")
    stored_values = dict(values)
    if reported_contact and stored_values.get("public_contact_value"):
        stored_values["contact_status"] = "operator_report"
    if identity_id is not None and identity_type is not None:
        stored_values["identity_reference"] = {"type": identity_type, "id": str(identity_id)}
    prior = session.scalar(
        select(BuyingChainCorrection).where(
            BuyingChainCorrection.claim_id == claim_id,
            BuyingChainCorrection.idempotency_key == idempotency_key,
        )
    )
    if prior is not None:
        if (
            prior.expected_version != expected_version
            or prior.action != action
            or prior.values != stored_values
            or prior.source_evidence_id != source_evidence_id
            or prior.source_version_hash != source_hash
            or prior.reason != reason.strip()
        ):
            raise ValueError("Idempotency key was already used for a different correction")
        return prior
    latest = session.scalar(
        select(BuyingChainCorrection)
        .where(BuyingChainCorrection.claim_id == claim_id)
        .order_by(BuyingChainCorrection.created_at.desc(), BuyingChainCorrection.id.desc())
        .limit(1)
    )
    if _version(claim, latest) != expected_version:
        raise RuntimeError("Buying-chain correction version is stale")
    if action not in {"correct", "retract"}:
        raise ValueError("Correction action must be correct or retract")
    if action == "retract" and values:
        raise ValueError("Retraction cannot include replacement values")
    if set(values) - EDITABLE:
        raise ValueError("Correction contains unsupported fields")
    for key, allowed in ALLOWED_VALUES.items():
        if key in values and values[key] not in allowed:
            raise ValueError(f"Unsupported correction value for {key}")
    if not reason.strip() or not actor.strip():
        raise ValueError("Reason and attributed operator are required")
    if not values and action != "retract":
        if identity_id is None:
            raise ValueError("Correction must include a field, identity reference, or retraction")
    if (identity_type is None) != (identity_id is None):
        raise ValueError("Identity type and ID must be supplied together")
    source = None
    if source_evidence_id:
        source = session.get(BuyingChainEvidence, source_evidence_id)
        if source is None or source.project_id != project_id or source_hash != source.content_hash:
            raise ValueError("Source evidence ID and hash must match this project")
        current = buying_chain_view(session, project_id)
        candidate = next(
            (item for item in current["candidates"] if str(item["id"]) == str(claim_id)), None
        )
        evidence = next(
            (
                item
                for item in (candidate or {}).get("evidence", [])
                if str(item["id"]) == str(source.id)
            ),
            None,
        )
        if (
            candidate is None
            or candidate["stale"]
            or not evidence
            or not evidence.get("current_support")
            or evidence.get("content_hash") != source_hash
            or evidence.get("current_source_version_id") != source.id
        ):
            raise ValueError("Correction source must be a current cited version for this claim")
        for key in ("organization", "person_name", "title", "public_contact_value"):
            value = values.get(key)
            if value and str(value).casefold() not in source.excerpt.casefold():
                if not (reported_contact and key == "public_contact_value"):
                    raise ValueError("Corrected value must appear literally in the cited source")
            if key == "public_contact_value" and value and not reported_contact:
                if not any(
                    item.get("supports") == "public_contact"
                    and item.get("current_support")
                    and item.get("public_research_provenance")
                    and str(value).casefold() in str(item.get("quote", "")).casefold()
                    for item in candidate.get("evidence", [])
                    if str(item.get("id")) == str(source.id)
                ):
                    raise ValueError(
                        "Public contact action requires a current permitted public-contact citation"
                    )
    elif not reported_contact and action != "retract":
        raise ValueError(
            "Current source evidence is required unless this is explicitly an operator report"
        )
    if identity_id is not None:
        if source is None:
            raise ValueError("Identity reconciliation requires cited current source evidence")
        from gridlens.intelligence.identity_reconciliation import link_claim_to_identity

        link_claim_to_identity(
            session,
            claim,
            identity_type,  # type: ignore[arg-type]
            identity_id,
            source,
            reason,
            reviewed_by=actor,
        )
    row = BuyingChainCorrection(
        project_id=project_id,
        claim_id=claim_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        action=action,
        values=stored_values,
        source_evidence_id=source.id if source else None,
        source_version_hash=source.content_hash if source else None,
        reason=reason.strip(),
        actor=actor.strip(),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def correction_view(row: BuyingChainCorrection) -> dict[str, Any]:
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "project_id": row.project_id,
        "version": str(row.id),
        "action": row.action,
        "values": row.values,
        "reason": row.reason,
        "actor": row.actor,
        "created_at": row.created_at,
        "reported_contact": row.values.get("contact_status") == "operator_report",
    }


def overlay_corrections(
    session: Session,
    project_id: UUID,
    candidates: list[dict[str, Any]],
    history: bool,
    *,
    decisions: list[BuyingChainCorrection] | None = None,
) -> None:
    claim_ids = {item["id"] for item in candidates}
    if not claim_ids:
        return
    rows: Sequence[BuyingChainCorrection]
    if decisions is None:
        rows = session.scalars(
            select(BuyingChainCorrection)
            .where(
                BuyingChainCorrection.project_id == project_id,
                BuyingChainCorrection.claim_id.in_(claim_ids),
            )
            .order_by(BuyingChainCorrection.created_at, BuyingChainCorrection.id)
        ).all()
    else:
        rows = decisions
    rows = [row for row in rows if row.claim_id in claim_ids]
    by_claim: dict[UUID, list[BuyingChainCorrection]] = {}
    for row in rows:
        by_claim.setdefault(row.claim_id, []).append(row)
    for candidate in candidates:
        decisions = by_claim.get(candidate["id"], [])
        if history:
            candidate["correction_history"] = [correction_view(row) for row in decisions]
        if not decisions:
            candidate["correction_version"] = candidate.get("fingerprint")
            continue
        latest = decisions[-1]
        if latest.source_evidence_id is not None and not any(
            str(item.get("id")) == str(latest.source_evidence_id)
            and str(item.get("current_source_version_id")) == str(latest.source_evidence_id)
            and item.get("content_hash") == latest.source_version_hash
            and item.get("current_support")
            for item in candidate.get("evidence", [])
        ):
            candidate["correction_version"] = candidate.get("fingerprint")
            candidate["correction_stale"] = True
            continue
        candidate["correction_version"] = str(latest.id)
        if latest.action == "retract":
            candidate["retracted"] = True
            candidate["public_contacts"] = []
            continue
        values = dict(latest.values)
        contact_status = values.pop("contact_status", None)
        for key, value in values.items():
            if key in EDITABLE and key.startswith("public_contact_"):
                continue
            if key in EDITABLE:
                candidate[key] = value
        if values.get("public_contact_value"):
            contact = {
                "kind": values.get("public_contact_kind") or "reported",
                "value": values["public_contact_value"],
                "source_url": "",
                "quote": "",
                "operator_report": contact_status == "operator_report",
            }
            if contact_status == "operator_report":
                candidate["reported_contacts"] = [contact]
            else:
                candidate["public_contacts"] = [*candidate["public_contacts"], contact]
