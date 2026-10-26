"""Evidence-checked append-only operator decisions for buying-chain claims."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.persistence.models import (
    BuyingChainCorrection,
)

_SEMANTIC_FIELDS = {
    "organization",
    "person_name",
    "title",
    "category",
    "organization_relationship",
    "person_organization_relationship",
    "person_project_relationship",
}
_OVERLAY_FIELDS = _SEMANTIC_FIELDS | {"public_contact_kind", "public_contact_value"}


def _ordered_correction_chain(
    fingerprint: str, rows: Sequence[BuyingChainCorrection]
) -> list[BuyingChainCorrection] | None:
    """Order append-only decisions by their expected-version links, failing closed on forks."""
    by_expected: dict[str, BuyingChainCorrection] = {}
    for row in sorted(rows, key=lambda item: (item.created_at, item.id)):
        if row.expected_version in by_expected:
            return None
        by_expected[row.expected_version] = row
    ordered: list[BuyingChainCorrection] = []
    seen: set[UUID] = set()
    version = fingerprint
    while version in by_expected:
        row = by_expected[version]
        if row.id in seen:
            return None
        ordered.append(row)
        seen.add(row.id)
        version = str(row.id)
    return ordered if len(ordered) == len(rows) else None


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


def _keeps_other_contact_kind(item: dict[str, Any], requested_kind: Any) -> bool:
    return (
        bool(requested_kind)
        and str(item.get("kind", "")).casefold() != str(requested_kind).casefold()
    )


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
        unordered = by_claim.get(candidate["id"], [])
        ordered = _ordered_correction_chain(str(candidate.get("fingerprint", "")), unordered)
        if ordered is None:
            candidate["correction_stale"] = True
            if history:
                candidate["correction_history"] = [correction_view(row) for row in unordered]
            if unordered:
                candidate["correction_version"] = str(unordered[-1].id)
            continue
        decisions = ordered
        if history:
            candidate["correction_history"] = [correction_view(row) for row in decisions]
        if not decisions:
            candidate["correction_version"] = candidate.get("fingerprint")
            continue
        contact_values: dict[str, Any] = {}
        for row in decisions:
            cited = row.source_evidence_id is None or any(
                str(item.get("id")) == str(row.source_evidence_id)
                and str(item.get("current_source_version_id")) == str(row.source_evidence_id)
                and item.get("content_hash") == row.source_version_hash
                and item.get("current_support")
                for item in candidate.get("evidence", [])
            )
            if not cited:
                candidate["correction_stale"] = True
                break
            if row.action == "retract":
                candidate["retracted"] = True
                candidate["public_contacts"] = []
                candidate["reported_contacts"] = []
                contact_values.clear()
                continue

            values = dict(row.values)
            restores_relationship = any(key in values for key in _SEMANTIC_FIELDS)
            if not candidate.get("retracted") or (
                row.source_evidence_id is not None and cited and restores_relationship
            ):
                candidate["retracted"] = False
            contact_status = values.pop("contact_status", None)
            subject_changed = any(
                key in values and values[key] != candidate.get(key)
                for key in ("organization", "person_name")
            )
            if subject_changed:
                # Existing methods belong to the prior subject unless this row
                # supplies its own current, cited method below.
                candidate["public_contacts"] = []
                candidate["reported_contacts"] = []
                contact_values.clear()
            for key, value in values.items():
                if key in _OVERLAY_FIELDS and not key.startswith("public_contact_"):
                    candidate[key] = value
            if "public_contact_kind" in values:
                contact_values["public_contact_kind"] = values["public_contact_kind"]
            if "public_contact_value" in values:
                contact_values["public_contact_value"] = values["public_contact_value"]
                contact_values["contact_status"] = contact_status
                requested_kind = contact_values.get("public_contact_kind")
                if values["public_contact_value"] is None or (
                    isinstance(values["public_contact_value"], str)
                    and not values["public_contact_value"].strip()
                ):
                    # A clear uses the accumulated kind when one was previously
                    # selected; with no kind, clearing the claim is the safe choice.
                    candidate["public_contacts"] = [
                        item
                        for item in candidate.get("public_contacts", [])
                        if _keeps_other_contact_kind(item, requested_kind)
                    ]
                    candidate["reported_contacts"] = [
                        item
                        for item in candidate.get("reported_contacts", [])
                        if _keeps_other_contact_kind(item, requested_kind)
                    ]
                    if not requested_kind:
                        contact_values.clear()
                    else:
                        contact_values["public_contact_value"] = None
                elif contact_status == "operator_report":
                    kind = requested_kind or "reported"
                    # Without a supplied or previously selected kind, a report
                    # cannot safely scope its replacement, so clear prior actions.
                    candidate["public_contacts"] = [
                        item
                        for item in candidate.get("public_contacts", [])
                        if _keeps_other_contact_kind(item, requested_kind)
                    ]
                    candidate["reported_contacts"] = [
                        item
                        for item in candidate.get("reported_contacts", [])
                        if _keeps_other_contact_kind(item, requested_kind)
                    ]
                    contact = {
                        "kind": kind,
                        "value": values["public_contact_value"],
                        "source_url": "",
                        "quote": "",
                        "operator_report": True,
                    }
                    candidate["reported_contacts"].append(contact)
                elif values["public_contact_value"]:
                    kind = requested_kind or "general"
                    cited_contact = next(
                        (
                            item
                            for item in candidate.get("evidence", [])
                            if str(item.get("id")) == str(row.source_evidence_id)
                            and item.get("supports") == "public_contact"
                            and item.get("current_support")
                            and item.get("public_research_provenance")
                            and values["public_contact_value"].casefold()
                            in str(item.get("quote", "")).casefold()
                        ),
                        None,
                    )
                    existing = [
                        item
                        for item in candidate.get("public_contacts", [])
                        if str(item.get("kind", "")).casefold() != str(kind).casefold()
                    ]
                    candidate["public_contacts"] = existing
                    candidate["reported_contacts"] = [
                        item
                        for item in candidate.get("reported_contacts", [])
                        if str(item.get("kind", "")).casefold() != str(kind).casefold()
                    ]
                    if cited_contact:
                        existing.append(
                            {
                                "kind": kind,
                                "value": values["public_contact_value"],
                                "source_url": cited_contact.get("url", ""),
                                "quote": cited_contact.get("quote", ""),
                                "observed_at": cited_contact.get("observed_at"),
                                "operator_report": False,
                            }
                        )
                        candidate["public_contacts"] = existing
        # The write version tracks the append-only log head even if that row's
        # cited source is stale and its values are therefore not projected.
        candidate["correction_version"] = str(decisions[-1].id)
        if candidate.get("retracted"):
            continue
