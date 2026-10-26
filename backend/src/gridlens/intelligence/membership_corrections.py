"""Exceptional internal retraction of a source-bound company/project membership."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    CompanyProjectMembership,
    CompanyProjectMembershipCorrection,
)


class MembershipCorrectionConflict(ValueError):
    """The reviewed membership snapshot or idempotent request no longer matches."""


def _request_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label} must be nonempty and at most {maximum} characters")
    return value.strip()


def _reviewed_membership(
    session: Session,
    *,
    membership_id: UUID,
    project_id: UUID,
    company_id: UUID,
    expected_source_evidence_id: UUID,
    expected_source_hash: str,
    lock: bool,
) -> CompanyProjectMembership:
    scope = session.execute(
        select(CompanyProjectMembership.source_id, CompanyProjectMembership.role).where(
            CompanyProjectMembership.id == membership_id,
            CompanyProjectMembership.project_id == project_id,
            CompanyProjectMembership.company_identity_id == company_id,
        )
    ).one_or_none()
    if scope is None:
        raise LookupError("Membership not found for the exact project and company")
    if lock:
        # Match the source writer's lock order, so a refresh cannot replace the
        # reviewed current association while its exception is being recorded.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"customer-membership:{project_id}:{scope.source_id}:{scope.role}"},
        )
    query = select(CompanyProjectMembership).where(
        CompanyProjectMembership.id == membership_id,
        CompanyProjectMembership.project_id == project_id,
        CompanyProjectMembership.company_identity_id == company_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    membership = session.scalar(query)
    if membership is None:
        raise LookupError("Membership no longer exists in the reviewed scope")
    if (
        membership.source_evidence_id != expected_source_evidence_id
        or membership.source_version_hash != expected_source_hash
    ):
        raise MembershipCorrectionConflict("Membership source version differs from the review")
    return membership


def preview_membership_retraction(
    session: Session,
    *,
    membership_id: UUID,
    project_id: UUID,
    company_id: UUID,
    expected_version: int,
    expected_source_evidence_id: UUID,
    expected_source_hash: str,
) -> dict:
    """Read a prospective retraction without locks, writes or positive identity edits."""
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("expected_version must be a nonnegative integer")
    membership = _reviewed_membership(
        session,
        membership_id=membership_id,
        project_id=project_id,
        company_id=company_id,
        expected_source_evidence_id=expected_source_evidence_id,
        expected_source_hash=expected_source_hash,
        lock=False,
    )
    if membership.version != expected_version or membership.state != "current":
        raise MembershipCorrectionConflict("Membership changed; review its current state")
    return {
        "action": "retract_membership",
        "membership_id": str(membership.id),
        "project_id": str(membership.project_id),
        "company_id": str(membership.company_identity_id),
        "expected_version": membership.version,
        "source_evidence_id": str(membership.source_evidence_id),
        "source_version_hash": membership.source_version_hash,
        "state": membership.state,
    }


def retract_project_membership(
    session: Session,
    *,
    membership_id: UUID,
    project_id: UUID,
    company_id: UUID,
    expected_version: int,
    expected_source_evidence_id: UUID,
    expected_source_hash: str,
    idempotency_key: str,
    reason: str,
    actor: str,
) -> CompanyProjectMembershipCorrection:
    """Append one audited negative correction; preserve source and physical identity."""
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("expected_version must be a nonnegative integer")
    reason = _request_text(reason, "reason", 10_000)
    actor = _request_text(actor, "actor", 120)
    idempotency_key = _request_text(idempotency_key, "idempotency_key", 120)
    expected_source_hash = _request_text(expected_source_hash, "expected_source_hash", 64)
    membership = _reviewed_membership(
        session,
        membership_id=membership_id,
        project_id=project_id,
        company_id=company_id,
        expected_source_evidence_id=expected_source_evidence_id,
        expected_source_hash=expected_source_hash,
        lock=True,
    )
    # Scope and source checks precede replay. A known idempotency key cannot
    # acknowledge a request against another project, company or source version.
    prior = session.scalar(
        select(CompanyProjectMembershipCorrection).where(
            CompanyProjectMembershipCorrection.membership_id == membership_id,
            CompanyProjectMembershipCorrection.idempotency_key == idempotency_key,
        )
    )
    if prior is not None:
        if (
            prior.action,
            prior.expected_version,
            prior.reason,
            prior.actor,
        ) != ("retracted", expected_version, reason, actor):
            raise MembershipCorrectionConflict("Idempotency key belongs to another request")
        return prior
    if membership.version != expected_version or membership.state != "current":
        raise MembershipCorrectionConflict("Membership changed; review its current state")
    event = CompanyProjectMembershipCorrection(
        membership_id=membership.id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        action="retracted",
        reason=reason,
        actor=actor,
    )
    session.add(event)
    membership.state = "retracted"
    membership.superseded_at = datetime.now(UTC)
    membership.version = expected_version + 1
    session.flush()
    return event
