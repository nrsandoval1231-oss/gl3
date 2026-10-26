"""Internal audited correction writers for existing append-only ledgers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.domain.buying_chain import CATEGORY_PRIORITY
from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.intelligence.buying_chain_corrections import _ordered_correction_chain
from gridlens.intelligence.company_graph import _relationship_state
from gridlens.intelligence.contact_suppressions import SuppressionConflict
from gridlens.persistence.contact_models import (
    CompanyRelationshipAssertion,
    CompanyRelationshipCorrection,
)
from gridlens.persistence.models import BuyingChainClaim, BuyingChainCorrection


def correct_buying_chain_claim(
    session: Session,
    *,
    project_id: UUID,
    claim_id: UUID,
    expected_version: str,
    action: str,
    values: dict,
    reason: str,
    actor: str,
    idempotency_key: str,
    source_evidence_id: UUID | None = None,
    source_version_hash: str | None = None,
) -> BuyingChainCorrection:
    """Append a project-scoped, idempotent correction after optimistic version check."""
    claim = session.get(BuyingChainClaim, claim_id)
    if claim is None or claim.project_id != project_id:
        raise LookupError("Buying-chain claim not found for project")
    prior = session.scalar(
        select(BuyingChainCorrection).where(
            BuyingChainCorrection.claim_id == claim_id,
            BuyingChainCorrection.idempotency_key == idempotency_key,
        )
    )
    if prior:
        if (
            prior.expected_version,
            prior.project_id,
            prior.action,
            prior.values,
            prior.source_evidence_id,
            prior.source_version_hash,
            prior.reason,
            prior.actor,
        ) != (
            expected_version,
            project_id,
            action,
            values,
            source_evidence_id,
            source_version_hash,
            reason.strip(),
            actor.strip(),
        ):
            raise SuppressionConflict("idempotency key was already used for a different correction")
        return prior
    rows = session.scalars(
        select(BuyingChainCorrection).where(BuyingChainCorrection.claim_id == claim_id)
    ).all()
    chain = _ordered_correction_chain(str(claim.fingerprint), rows)
    if chain is None:
        raise SuppressionConflict("conflicted buying-chain correction history")
    current_version = str(chain[-1].id) if chain else str(claim.fingerprint)
    if expected_version != current_version:
        raise SuppressionConflict(f"stale buying-chain correction version {current_version}")
    if action not in {"correct", "retract"}:
        raise ValueError("action must be correct or retract")
    if not isinstance(values, dict):
        raise ValueError("correction values must be an object")
    if not reason.strip() or not actor.strip() or not idempotency_key.strip():
        raise ValueError("reason, actor, and idempotency_key are required")
    if action == "correct":
        allowed = {
            "organization",
            "person_name",
            "title",
            "category",
            "organization_relationship",
            "person_organization_relationship",
            "person_project_relationship",
            "public_contact_kind",
            "public_contact_value",
            "contact_status",
        }
        if set(values) - allowed:
            raise ValueError("correction contains unsupported fields")
        if "category" in values and (
            not isinstance(values["category"], str)
            or values["category"] not in CATEGORY_PRIORITY
        ):
            raise ValueError("unsupported buying-chain category")
        for field in ("organization", "person_name", "title"):
            if field in values and (
                not isinstance(values[field], str)
                or not values[field].strip()
                or len(values[field]) > 300
            ):
                raise ValueError(f"{field} must be a nonempty string of at most 300 characters")
        for field in (
            "organization_relationship",
            "person_organization_relationship",
            "person_project_relationship",
        ):
            if field in values and (
                not isinstance(values[field], str)
                or values[field] not in {"DIRECT", "ROLE_SUPPORTED", "UNKNOWN"}
            ):
                raise ValueError(f"unsupported value for {field}")
        if "public_contact_kind" in values and (
            not isinstance(values["public_contact_kind"], str)
            or values["public_contact_kind"]
            not in {"email", "phone", "profile", "website", "general"}
        ):
            raise ValueError("unsupported public contact kind")
        if (
            "public_contact_value" in values
            and values["public_contact_value"] is not None
            and (
                not isinstance(values["public_contact_value"], str)
                or len(values["public_contact_value"]) > 500
            )
        ):
            raise ValueError("public_contact_value must be a bounded string or null")
        if values.get("contact_status") is not None:
            raise ValueError("contact status cannot be operator supplied")
        if source_evidence_id is None or not source_version_hash:
            raise ValueError("correct actions require a cited evidence ID and version hash")
        current = buying_chain_view(session, project_id)
        candidate = next(
            (item for item in current.get("candidates", []) if item.get("id") == claim_id), None
        )
        if candidate is None or candidate.get("stale") or candidate.get("correction_stale"):
            raise ValueError("claim is stale or absent from the current project view")
        support = next(
            (
                item
                for item in (candidate or {}).get("evidence", [])
                if str(item.get("id")) == str(source_evidence_id)
                and item.get("content_hash") == source_version_hash
                and item.get("current_support")
                and item.get("current_source_version_id") == str(source_evidence_id)
            ),
            None,
        )
        if support is None:
            raise ValueError("correction source must be current evidence supporting this claim")
        support_for_field = {
            "organization": {"project_organization"},
            "organization_relationship": {"project_organization"},
            "person_name": {"organization_person_role"},
            "title": {"organization_person_role"},
            "category": {"organization_person_role"},
            "person_organization_relationship": {"organization_person_role"},
            "person_project_relationship": {"person_project_assignment"},
            "public_contact_kind": {"public_contact"},
            "public_contact_value": {"public_contact"},
        }
        fields_to_check = set(values) - {"contact_status"}
        current_evidence = [
            item
            for item in candidate.get("evidence", [])
            if str(item.get("id")) == str(source_evidence_id)
            and item.get("current_support")
            and item.get("content_hash") == source_version_hash
        ]
        for field in fields_to_check:
            appropriate = [
                e for e in current_evidence if e.get("supports") in support_for_field[field]
            ]
            if not appropriate:
                raise ValueError(f"source does not support correction field {field}")
            value = values[field]
            if field == "public_contact_value":
                if value is None:
                    continue
                if not any(
                    value == contact.get("value")
                    and (
                        "public_contact_kind" not in values
                        or values["public_contact_kind"] == contact.get("kind")
                    )
                    and contact.get("source_url") == support.get("url")
                    and contact.get("quote") == support.get("quote")
                    for contact in candidate.get("public_contacts", [])
                ):
                    raise ValueError(
                        "positive method corrections must exactly reuse an extracted contact"
                    )
                continue
            # This control surface may retract or clear unsupported assertions.
            # Positive semantic changes only reuse the exact current extracted
            # value; new identity/role qualification is left to autonomous research.
            if value != candidate.get(field):
                raise ValueError(
                    f"positive {field} edits must reuse the current extracted assertion"
                )
        if "public_contact_kind" in values:
            if not any(
                contact.get("kind") == values["public_contact_kind"]
                for contact in candidate.get("public_contacts", [])
            ):
                raise ValueError("positive contact kinds must exactly reuse an extracted contact")
    row = BuyingChainCorrection(
        project_id=project_id,
        claim_id=claim_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        action=action,
        values=values,
        source_evidence_id=source_evidence_id,
        source_version_hash=source_version_hash,
        reason=reason.strip(),
        actor=actor.strip(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise SuppressionConflict("concurrent correction; reload history and retry") from exc
    return row


def correct_company_relationship(
    session: Session,
    *,
    assertion_id: UUID,
    expected_version: int,
    action: str,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> CompanyRelationshipCorrection:
    prior = session.scalar(
        select(CompanyRelationshipCorrection).where(
            CompanyRelationshipCorrection.assertion_id == assertion_id,
            CompanyRelationshipCorrection.idempotency_key == idempotency_key,
        )
    )
    if prior:
        if (
            prior.expected_version != expected_version
            or prior.action != action
            or prior.reason != reason.strip()
            or prior.actor != actor.strip()
        ):
            raise SuppressionConflict(
                "idempotency key was already used for another relationship event"
            )
        return prior
    assertion = session.get(CompanyRelationshipAssertion, assertion_id)
    if assertion is None:
        raise LookupError("Company relationship assertion not found")
    state, version, _ = _relationship_state(session, assertion)
    if version != expected_version or state == "conflicted":
        raise SuppressionConflict(f"stale or conflicted relationship version {version}")
    if action not in {"retract", "suppress", "reinstate"}:
        raise ValueError("unsupported relationship action")
    if (action == "reinstate" and state not in {"suppressed", "retracted"}) or (
        action != "reinstate" and state in {"suppressed", "retracted"}
    ):
        raise SuppressionConflict("action does not match current relationship state")
    if not reason.strip() or not actor.strip() or not idempotency_key.strip():
        raise ValueError("reason, actor, and idempotency_key are required")
    row = CompanyRelationshipCorrection(
        assertion_id=assertion_id,
        expected_version=expected_version,
        version=expected_version + 1,
        action=action,
        reason=reason.strip(),
        actor=actor.strip(),
        idempotency_key=idempotency_key.strip(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise SuppressionConflict("concurrent correction; reload history and retry") from exc
    return row
