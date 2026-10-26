"""Internal audited correction writers for existing append-only ledgers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.intelligence.company_graph import _relationship_state
from gridlens.intelligence.buying_chain_corrections import _ordered_correction_chain
from gridlens.intelligence.contact_suppressions import SuppressionConflict
from gridlens.persistence.contact_models import CompanyRelationshipAssertion, CompanyRelationshipCorrection
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
    prior = session.scalar(select(BuyingChainCorrection).where(
        BuyingChainCorrection.claim_id == claim_id,
        BuyingChainCorrection.idempotency_key == idempotency_key,
    ))
    if prior:
        return prior
    claim = session.get(BuyingChainClaim, claim_id)
    if claim is None or claim.project_id != project_id:
        raise LookupError("Buying-chain claim not found for project")
    rows = session.scalars(select(BuyingChainCorrection).where(
        BuyingChainCorrection.claim_id == claim_id
    )).all()
    chain = _ordered_correction_chain(str(claim.fingerprint), rows)
    if chain is None:
        raise SuppressionConflict("conflicted buying-chain correction history")
    current_version = str(chain[-1].id) if chain else str(claim.fingerprint)
    if expected_version != current_version:
        raise SuppressionConflict(f"stale buying-chain correction version {current_version}")
    if action not in {"correct", "retract"}:
        raise ValueError("action must be correct or retract")
    if not reason.strip() or not actor.strip() or not idempotency_key.strip():
        raise ValueError("reason, actor, and idempotency_key are required")
    row = BuyingChainCorrection(
        project_id=project_id, claim_id=claim_id, expected_version=expected_version,
        idempotency_key=idempotency_key, action=action, values=values,
        source_evidence_id=source_evidence_id, source_version_hash=source_version_hash,
        reason=reason.strip(), actor=actor.strip(),
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
    prior = session.scalar(select(CompanyRelationshipCorrection).where(
        CompanyRelationshipCorrection.assertion_id == assertion_id,
        CompanyRelationshipCorrection.idempotency_key == idempotency_key,
    ))
    if prior:
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
        assertion_id=assertion_id, expected_version=expected_version,
        version=expected_version + 1, action=action, reason=reason.strip(),
        actor=actor.strip(), idempotency_key=idempotency_key.strip(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise SuppressionConflict("concurrent correction; reload history and retry") from exc
    return row
