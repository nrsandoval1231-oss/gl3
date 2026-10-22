"""Evidence-checked append-only operator decisions for buying-chain claims."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import buying_chain_view
from gridlens.intelligence.buying_chain_extraction import (
    extract_organizations,
    extract_people,
    extract_retained_permit_organizations,
    organization_key,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    Evidence,
    Observation,
    PersonIdentity,
    Project,
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
REQUIRED_TEXT_FIELDS = {"organization"}
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

_SEMANTIC_FIELDS = {
    "organization",
    "person_name",
    "title",
    "category",
    "organization_relationship",
    "person_organization_relationship",
    "person_project_relationship",
}


def _version(claim: BuyingChainClaim, latest: BuyingChainCorrection | None) -> str:
    return str(latest.id) if latest else claim.fingerprint


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


def _has_current_semantic_support(
    *,
    session: Session,
    project_id: UUID,
    candidate: dict[str, Any],
    source: BuyingChainEvidence,
    values: dict[str, Any],
) -> bool:
    """Require the existing conservative extraction to support each positive edit."""
    requested = {key: value for key, value in values.items() if key in _SEMANTIC_FIELDS}
    if not requested:
        return True
    project = session.get(Project, project_id)
    if project is None:
        return False
    structured: tuple[dict[str, Any], ...] = ()
    retained_source_id = None
    from gridlens.ingestion.adapters.retained_document import SOURCES

    if source.retained_evidence_id is not None:
        retained = session.get(Evidence, source.retained_evidence_id)
        observation = session.get(Observation, retained.observation_id) if retained else None
        if retained is not None and observation is not None:
            retained_source_id = observation.source_id
            if retained_source_id in SOURCES:
                structured = (
                    {
                        "f17_retained": {
                            "source_id": retained_source_id,
                            "evidence_content_hash": retained.content_hash,
                            "project_name": project.name,
                            "project_location": project.location,
                            "retained_document": (retained.provenance or {}).get(
                                "retained_document"
                            ),
                        }
                    },
                )
    doc = PublicDocument(
        url=source.url,
        title=source.title,
        text=source.excerpt,
        published_at=source.published_at,
        observed_at=source.observed_at,
        extraction_location=source.extraction_location,
        structured=structured,
        retained_version=source.content_hash,
    )
    current_citations = {
        (str(item.get("quote", "")), str(item.get("supports", "")))
        for item in candidate.get("evidence", [])
        if str(item.get("id")) == str(source.id)
        and str(item.get("current_source_version_id")) == str(source.id)
        and item.get("content_hash") == source.content_hash
        and item.get("current_support")
    }
    if not current_citations:
        return False

    effective_organization = requested.get("organization", candidate.get("organization"))
    effective_person_value = requested.get("person_name", candidate.get("person_name"))
    effective_person = (
        effective_person_value.strip()
        if isinstance(effective_person_value, str) and effective_person_value.strip()
        else None
    )
    subject_changed = {
        field
        for field in ("organization", "person_name")
        if field in requested
        and requested[field] != candidate.get(field)
        and (field != "person_name" or effective_person is not None)
    }
    revalidate: set[str] = set()
    if "organization" in subject_changed:
        revalidate.update(
            {
                "category",
                "organization_relationship",
                "person_organization_relationship",
                "person_project_relationship",
                "title",
            }
        )
    if "person_name" in subject_changed:
        revalidate.update(
            {
                "category",
                "person_project_relationship",
                "person_organization_relationship",
                "title",
            }
        )
    for field in revalidate:
        if field not in requested:
            requested[field] = candidate.get(field)
    if retained_source_id in SOURCES:
        extracted_organizations = extract_retained_permit_organizations(doc, retained_source_id)
    elif retained_source_id is not None:
        extracted_organizations = [
            *extract_retained_permit_organizations(doc, retained_source_id),
            *extract_organizations(doc, project),
        ]
    elif project.source_id == "houston-weekly-permits" and "/ibi_apps/WFServlet.ibfs" in doc.url:
        extracted_organizations = extract_retained_permit_organizations(doc, project.source_id)
    else:
        extracted_organizations = extract_organizations(doc, project)
    organizations = [
        item
        for item in extracted_organizations
        if organization_key(item.organization)
        == organization_key(str(effective_organization or ""))
    ]
    people = extract_people(doc, organizations, project, project_scoped=True, today=date.today())
    if effective_person:
        people = [
            item
            for item in people
            if str(item.person_name or "").casefold() == str(effective_person).casefold()
        ]
    else:
        people = []

    def has_cited_support(item: Any, support: str | None = None) -> bool:
        return any(
            (support is None or citation.get("supports") == support)
            and (str(citation.get("quote", "")), str(citation.get("supports", "")))
            in current_citations
            for citation in item.citations
        )

    for field, requested_value in requested.items():
        if field == "person_name" and effective_person is None:
            # Clearing an optional person is a downgrade, not a new positive
            # subject claim that must be re-extracted.
            continue
        if field == "title" and (
            requested_value is None
            or (isinstance(requested_value, str) and not requested_value.strip())
        ):
            # Clearing an optional title is a downgrade, not a new positive
            # title claim that must be re-extracted.
            continue
        if (
            requested_value == candidate.get(field) and field not in revalidate
        ) or requested_value == "UNKNOWN":
            continue
        if field == "organization":
            if not any(has_cited_support(item) for item in organizations):
                return False
        elif field == "person_name":
            if not any(has_cited_support(item) for item in people):
                return False
        elif field == "title":
            title = str(requested_value).strip().casefold()
            if not any(
                str(item.title or "").strip().casefold() == title
                and has_cited_support(item, "organization_person_role")
                for item in people
            ):
                return False
        elif field == "person_organization_relationship":
            # Extraction reports CURRENT/UNKNOWN. The correction enum has a
            # different contract, so do not silently equate CURRENT with DIRECT.
            return False
        if field == "category":
            matches = people if effective_person else organizations
            if not any(
                item.category == requested_value and has_cited_support(item) for item in matches
            ):
                return False
        elif field == "organization_relationship":
            if not any(
                item.organization_relationship == requested_value and has_cited_support(item)
                for item in organizations
            ):
                return False
        elif field == "person_project_relationship":
            if not any(
                item.person_project_relationship == requested_value and has_cited_support(item)
                for item in people
            ):
                return False
    return True


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
    if action == "retract" and (identity_type is not None or identity_id is not None):
        raise ValueError("Retractions cannot include an identity reference")
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
    if reported_contact:
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
    current = buying_chain_view(session, project_id, history=False, include_identity_ids=False)
    current_candidate = next(
        (item for item in current["candidates"] if str(item["id"]) == str(claim_id)), None
    )
    candidate = current_candidate
    if candidate is None:
        historical = buying_chain_view(
            session, project_id, history=True, include_identity_ids=False
        )
        candidate = next(
            (item for item in historical["candidates"] if str(item["id"]) == str(claim_id)),
            None,
        )
    if candidate is not None and candidate.get("correction_stale"):
        raise RuntimeError(
            "Correction history is stale; restore current cited evidence before adding decisions"
        )
    correction_rows = session.scalars(
        select(BuyingChainCorrection).where(BuyingChainCorrection.claim_id == claim_id)
    ).all()
    ordered_rows = _ordered_correction_chain(claim.fingerprint, correction_rows)
    if ordered_rows is None:
        raise RuntimeError("Correction history dependencies are invalid; restore a valid chain")
    latest = ordered_rows[-1] if ordered_rows else None
    if _version(claim, latest) != expected_version:
        raise RuntimeError("Buying-chain correction version is stale")
    if action not in {"correct", "retract"}:
        raise ValueError("Correction action must be correct or retract")
    if action == "retract" and values:
        raise ValueError("Retraction cannot include replacement values")
    if set(values) - EDITABLE:
        raise ValueError("Correction contains unsupported fields")
    for key in REQUIRED_TEXT_FIELDS & values.keys():
        value = values[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Corrected value for {key} must be a non-empty string")
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
    if reported_contact and action == "correct" and source_evidence_id is None:
        if set(values) - {"public_contact_kind", "public_contact_value"}:
            raise ValueError(
                "Source-free operator reports may only replace or clear contact details"
            )
        if "public_contact_value" not in values:
            raise ValueError("Operator contact report must replace or clear a contact value")
        contact_value = values["public_contact_value"]
        if contact_value is not None and not isinstance(contact_value, str):
            raise ValueError("Operator contact value must be text or an explicit clear")
    source = None
    if source_evidence_id:
        source = session.get(BuyingChainEvidence, source_evidence_id)
        if source is None or source.project_id != project_id or source_hash != source.content_hash:
            raise ValueError("Source evidence ID and hash must match this project")
        if current_candidate is None:
            raise ValueError("Correction source must be a current cited version for this claim")
        candidate = current_candidate
        evidence = next(
            (
                item
                for item in (candidate or {}).get("evidence", [])
                if str(item["id"]) == str(source.id)
            ),
            None,
        )
        if (
            not evidence
            or not evidence.get("current_support")
            or evidence.get("content_hash") != source_hash
            or evidence.get("current_source_version_id") != source.id
        ):
            raise ValueError("Correction source must be a current cited version for this claim")
        if not _has_current_semantic_support(
            session=session,
            project_id=project_id,
            candidate=candidate,
            source=source,
            values=values,
        ):
            raise ValueError(
                "Positive semantic correction requires matching current cited subject evidence"
            )
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

    current_candidate = candidate
    changed_identity_types = {
        entity_type
        for field, entity_type in (("organization", "company"), ("person_name", "person"))
        if field in values
        and current_candidate is not None
        and values[field] != current_candidate.get(field)
    }
    if changed_identity_types and source is None:
        raise ValueError("Subject corrections require cited current source evidence")

    linked_type_with_explicit_rebind: str | None = None
    same_link_rebind = False
    if identity_id is not None:
        if source is None:
            raise ValueError("Identity reconciliation requires cited current source evidence")
        identity_model = CompanyIdentity if identity_type == "company" else PersonIdentity
        if session.get(identity_model, identity_id) is None:
            raise ValueError("identity does not exist")
        existing_link = session.scalar(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type == identity_type,
                BuyingChainIdentityLink.state == "current",
            )
        )
        link_claim_to_identity(
            session,
            claim,
            identity_type,  # type: ignore[arg-type]
            identity_id,
            source,
            reason,
            reviewed_by=actor,
        )
        linked_type_with_explicit_rebind = identity_type
        same_link_rebind = bool(
            identity_type in changed_identity_types
            and existing_link is not None
            and getattr(
                existing_link,
                "company_identity_id" if identity_type == "company" else "person_identity_id",
            )
            == identity_id
            and existing_link.source_version_hash == source.content_hash
        )
        if same_link_rebind:
            assert existing_link is not None
            existing_link.state = "superseded"
            existing_link.superseded_at = datetime.now(UTC)
            session.flush()
            link_claim_to_identity(
                session,
                claim,
                identity_type,  # type: ignore[arg-type]
                identity_id,
                source,
                reason,
                reviewed_by=actor,
            )

    types_to_supersede = changed_identity_types - (
        {linked_type_with_explicit_rebind} if linked_type_with_explicit_rebind else set()
    )
    if types_to_supersede:
        links = session.scalars(
            select(BuyingChainIdentityLink).where(
                BuyingChainIdentityLink.claim_id == claim.id,
                BuyingChainIdentityLink.entity_type.in_(types_to_supersede),
                BuyingChainIdentityLink.state == "current",
            )
        ).all()
        for link in links:
            link.state = "superseded"
            link.superseded_at = datetime.now(UTC)
        session.flush()
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

            candidate["retracted"] = False
            values = dict(row.values)
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
                if key in EDITABLE and not key.startswith("public_contact_"):
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
