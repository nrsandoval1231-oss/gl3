"""Isolated staging persistence for source workbooks; imports never change canonical claims."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from gridlens.intelligence.company_graph import _buying_evidence_current, _retained_current
from gridlens.persistence.models import (
    BuyingChainEvidence,
    CompanyProjectMembership,
    Evidence,
    ExternalImportActivation,
    ExternalImportBatch,
    ExternalImportEvent,
    ExternalImportRow,
    IdentityIdentifier,
    Project,
)


def _assert_staging_session(session: Session) -> None:
    """Fail closed unless this session is bound to a clearly isolated staging/test DB."""
    if not isinstance(session, Session) or not session.is_active:
        raise RuntimeError("external imports require an active SQLAlchemy staging session")
    bind = session.get_bind()
    url = getattr(bind, "url", None)
    if url is None:
        raise RuntimeError("external imports require a session with an identifiable database bind")
    database = (url.database or "").lower()
    if not (
        "staging" in database
        or database.endswith("_stage")
        or database == "test"
        or database.endswith("_test")
    ):
        raise RuntimeError(
            "external import writes are restricted to an explicitly named staging/test database"
        )
    if (url.host or "").lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("external import writes require a loopback staging database")


def _normal_name(value: Any) -> str:
    value = re.sub(
        r"\b(incorporated|inc|corporation|corp|limited|ltd|llc|lp|pllc)\b",
        "",
        str(value or "").lower(),
    )
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _project_key(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _domain(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "").removeprefix("www.")


def _preview_fingerprint(preview: Any) -> str:
    row_data = [
        {
            "sheet": row.sheet,
            "row_number": row.row_number,
            "row_kind": row.row_kind,
            "normalized": row.normalized,
            "errors": row.errors,
        }
        for row in preview.rows
    ]
    payload = json.dumps(row_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_FREE_EMAIL_DOMAINS = {
    "aol.com",
    "comcast.net",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}


def _company_match(
    normalized: dict[str, Any],
    catalog: dict[str, Any],
    site_candidates: list[tuple[Project, list[str]]],
) -> dict[str, Any]:
    company_name = _normal_name(normalized.get("company_name"))
    domain = _domain(normalized.get("domain"))
    email = str(normalized.get("email") or "").strip().lower()
    email_domain = email.rsplit("@", 1)[1] if "@" in email else ""
    email_domain = _domain(email_domain)
    given_domain = domain or (email_domain if email_domain not in _FREE_EMAIL_DOMAINS else "")
    if not company_name:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "reasons": ["missing company name"],
        }
    candidate_ids = (
        catalog["companies_by_domain"].get(given_domain, set()) if given_domain else set()
    )
    if candidate_ids:
        name_ids = {
            item.company_identity_id
            for identity_id in candidate_ids
            for item in catalog["memberships_by_company"].get(identity_id, [])
            if _normal_name(item.organization_name) == company_name
        }
        exact = candidate_ids & name_ids
        reasons = ["exact registered domain", "exact current project-membership organization name"]
        if len(exact) == 1:
            return {"status": "matched", "candidate_id": str(next(iter(exact))), "reasons": reasons}
        if len(exact) > 1:
            return {
                "status": "ambiguous",
                "candidate_ids": sorted(map(str, exact)),
                "reasons": [*reasons, "multiple identities share both signals"],
            }
        return {
            "status": "unmatched",
            "candidate_id": None,
            "candidate_ids": sorted(map(str, candidate_ids)),
            "reasons": [
                "registered domain candidate conflicts with company name",
                "no identity adopted",
            ],
        }

    site_project_ids = {project.id for project, _reasons in site_candidates}
    membership_ids = {
        membership.company_identity_id
        for project_id in site_project_ids
        for membership in catalog["memberships_by_project"].get(project_id, [])
        if _normal_name(membership.organization_name) == company_name
    }
    if len(membership_ids) == 1:
        return {
            "status": "matched",
            "candidate_id": str(next(iter(membership_ids))),
            "reasons": [
                "exact current project-membership organization name",
                "independent exact project name and site location",
            ],
        }
    if len(membership_ids) > 1:
        return {
            "status": "ambiguous",
            "candidate_ids": sorted(map(str, membership_ids)),
            "reasons": ["company name and site corroborate multiple current memberships"],
        }
    if not given_domain:
        missing = [
            name
            for name, present in (("company_name", company_name), ("domain", given_domain))
            if not present
        ]
        return {
            "status": "unmatched",
            "candidate_id": None,
            "reasons": [
                "missing corroborating company signals",
                *[f"missing {field}" for field in missing],
            ],
        }

    return {
        "status": "unmatched",
        "candidate_id": None,
        "reasons": ["company name alone is insufficient", "no corroborated current membership"],
    }


def _site_project_candidates(
    normalized: dict[str, Any], catalog: dict[str, Any]
) -> list[tuple[Project, list[str]]]:
    project_name = _project_key(normalized.get("project_name"))
    if not project_name:
        return []
    address = _normal_name(normalized.get("address"))
    city = str(normalized.get("city") or "").strip()
    state = str(normalized.get("state") or "").strip().upper()
    city_state = _normal_name(f"{city} {state}") if city and state else ""
    candidates: list[tuple[Project, list[str]]] = []
    for project in catalog["projects_by_name"].get(project_name, []):
        if state and project.region_state and project.region_state != state:
            continue
        location = _normal_name(project.location)
        reasons = []
        if (
            address
            and len(address) >= 12
            and location
            and (address in location or location in address)
        ):
            reasons.append("project name and address/location agree")
        if city_state and location and city_state in location:
            reasons.append("project name and city/state agree")
        if reasons:
            candidates.append((project, reasons))
    return candidates


def _project_match(
    normalized: dict[str, Any],
    company_match: dict[str, Any],
    catalog: dict[str, Any],
    site_candidates: list[tuple[Project, list[str]]],
) -> dict[str, Any]:
    project_name = _project_key(normalized.get("project_name"))
    if not project_name:
        return {"status": "unmatched", "candidate_id": None, "reasons": ["missing project name"]}
    matched_company = (
        company_match.get("candidate_id") if company_match.get("status") == "matched" else None
    )
    company_project_ids: set[UUID] = set()
    if matched_company:
        company_project_ids = catalog["projects_by_company"].get(UUID(matched_company), set())
    city = str(normalized.get("city") or "").strip()
    state = str(normalized.get("state") or "").strip().upper()
    city_state = _normal_name(f"{city} {state}") if city and state else ""
    candidates: list[tuple[Project, list[str]]] = []
    name_candidates = catalog["projects_by_name"].get(project_name, [])
    for project in name_candidates:
        corroborating = next(
            (reasons.copy() for site, reasons in site_candidates if site.id == project.id), []
        )
        if state and project.region_state and project.region_state != state:
            continue
        location = _normal_name(project.location)
        if city_state and city_state not in location:
            continue
        if project.id in company_project_ids:
            corroborating.append("project name and current company membership agree")
        if corroborating:
            candidates.append((project, corroborating))
    if len(candidates) == 1:
        project, why = candidates[0]
        return {
            "status": "matched",
            "candidate_id": str(project.id),
            "reasons": ["exact normalized project name", *why],
        }
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "candidate_ids": sorted(str(p.id) for p, _ in candidates),
            "reasons": ["multiple existing projects have corroborating signals"],
        }
    if name_candidates:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "candidate_ids": [str(p.id) for p in name_candidates],
            "reasons": [
                "project name matches but no independent site/company signal corroborates it"
            ],
        }
    return {
        "status": "unmatched",
        "candidate_id": None,
        "reasons": ["no exact existing project name", "no project created from import"],
    }


def _matching_catalog(session: Session, normalized_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Load only company and project candidates referenced by this bounded workbook."""
    domains: set[str] = set()
    project_names: set[str] = set()
    for normalized in normalized_rows:
        domain = _domain(normalized.get("domain"))
        email = str(normalized.get("email") or "").strip().lower()
        email_domain = email.rsplit("@", 1)[1] if "@" in email else ""
        email_domain = _domain(email_domain)
        if domain or (email_domain and email_domain not in _FREE_EMAIL_DOMAINS):
            domains.add(domain or email_domain)
        if normalized.get("project_name"):
            project_names.add(_project_key(normalized["project_name"]))

    companies_by_domain: dict[str, set[UUID]] = {}
    company_ids: set[UUID] = set()
    domain_values = list(domains)
    for start in range(0, len(domain_values), 5000):
        identifiers = session.scalars(
            select(IdentityIdentifier).where(
                IdentityIdentifier.entity_type == "company",
                IdentityIdentifier.identifier_type.in_(("domain", "website_domain")),
                IdentityIdentifier.normalized_value.in_(domain_values[start : start + 5000]),
                IdentityIdentifier.company_identity_id.is_not(None),
            )
        )
        for identifier in identifiers:
            if identifier.company_identity_id is not None:
                source = session.get(BuyingChainEvidence, identifier.source_evidence_id)
                if (
                    source is None
                    or source.content_hash != identifier.source_version_hash
                    or not _buying_evidence_current(session, source)
                ):
                    continue
                companies_by_domain.setdefault(identifier.normalized_value, set()).add(
                    identifier.company_identity_id
                )
                company_ids.add(identifier.company_identity_id)

    projects_by_name: dict[str, list[Project]] = {}
    project_ids: set[UUID] = set()
    name_key = func.btrim(func.regexp_replace(func.lower(Project.name), "[^a-z0-9]+", " ", "g"))
    name_values = list(project_names)
    for start in range(0, len(name_values), 5000):
        candidates = session.scalars(
            select(Project).where(name_key.in_(name_values[start : start + 5000]))
        )
        for project in candidates:
            projects_by_name.setdefault(_project_key(project.name), []).append(project)
            project_ids.add(project.id)

    memberships_by_company: dict[UUID, list[CompanyProjectMembership]] = {}
    memberships_by_project: dict[UUID, list[CompanyProjectMembership]] = {}
    projects_by_company: dict[UUID, set[UUID]] = {}
    membership_by_id: dict[UUID, CompanyProjectMembership] = {}
    for values, column in (
        (list(company_ids), CompanyProjectMembership.company_identity_id),
        (list(project_ids), CompanyProjectMembership.project_id),
    ):
        for start in range(0, len(values), 5000):
            memberships = session.scalars(
                select(CompanyProjectMembership).where(
                    column.in_(values[start : start + 5000]),
                    CompanyProjectMembership.state == "current",
                )
            )
            membership_by_id.update({item.id: item for item in memberships})
    for membership in membership_by_id.values():
        evidence = session.get(Evidence, membership.source_evidence_id)
        evidence_project = session.get(Project, membership.project_id)
        if (
            evidence is None
            or evidence_project is None
            or evidence.content_hash != membership.source_version_hash
            or not _retained_current(session, evidence, evidence_project)
        ):
            continue
        memberships_by_company.setdefault(membership.company_identity_id, []).append(membership)
        memberships_by_project.setdefault(membership.project_id, []).append(membership)
        projects_by_company.setdefault(membership.company_identity_id, set()).add(
            membership.project_id
        )
    return {
        "companies_by_domain": companies_by_domain,
        "memberships_by_company": memberships_by_company,
        "memberships_by_project": memberships_by_project,
        "projects_by_company": projects_by_company,
        "projects_by_name": projects_by_name,
    }


def _result(
    session: Session, batch: ExternalImportBatch, *, include_rows: bool = False
) -> dict[str, Any]:
    counts = {
        status: count
        for status, count in session.execute(
            select(ExternalImportRow.match_status, func.count())
            .where(ExternalImportRow.batch_id == batch.id)
            .group_by(ExternalImportRow.match_status)
        )
    }
    row_count = sum(counts.values())
    active_count = (
        session.scalar(
            select(func.count())
            .select_from(ExternalImportActivation)
            .join(ExternalImportRow, ExternalImportActivation.row_id == ExternalImportRow.id)
            .where(
                ExternalImportRow.batch_id == batch.id, ExternalImportActivation.active.is_(True)
            )
        )
        or 0
    )
    serialized: list[dict[str, Any]] = []
    if include_rows:
        rows = list(
            session.scalars(
                select(ExternalImportRow)
                .where(ExternalImportRow.batch_id == batch.id)
                .order_by(ExternalImportRow.sheet, ExternalImportRow.row_number)
                .limit(100)
            )
        )
        activations = (
            {
                activation.row_id: activation.active
                for activation in session.scalars(
                    select(ExternalImportActivation).where(
                        ExternalImportActivation.row_id.in_([r.id for r in rows])
                    )
                )
            }
            if rows
            else {}
        )
        serialized = [
            {
                "row_id": str(row.id),
                "sheet": row.sheet,
                "row_number": row.row_number,
                "row_kind": row.row_kind,
                "status": row.match_status,
                "active": activations.get(row.id, False),
                "company_match": row.company_match,
                "project_match": row.project_match,
                "errors": row.errors,
            }
            for row in rows
        ]
    rolled_back = any(
        event.action == "rolled_back"
        for event in session.scalars(
            select(ExternalImportEvent).where(ExternalImportEvent.batch_id == batch.id)
        )
    )
    return {
        "batch_id": str(batch.id),
        "filename": batch.filename,
        "content_hash": batch.content_hash,
        "status": "rolled_back" if rolled_back else "staged",
        "row_count": row_count,
        "active_count": active_count,
        "matched_count": counts.get("matched", 0),
        "ambiguous_count": counts.get("ambiguous", 0),
        "unmatched_count": counts.get("unmatched", 0),
        "invalid_count": counts.get("invalid", 0),
        "ignored_count": counts.get("ignored", 0),
        "metrics": {
            **batch.metrics,
            "matched_rows": counts.get("matched", 0),
            "ambiguous_rows": counts.get("ambiguous", 0),
            "unmatched_rows": counts.get("unmatched", 0),
            "invalid_rows": counts.get("invalid", 0),
            "ignored_rows": counts.get("ignored", 0),
            "active_rows": active_count,
            "conflicting_rows": counts.get("ambiguous", 0),
        },
        "rows": serialized,
        "rows_truncated": include_rows and row_count > len(serialized),
    }


def stage_import(session: Session, preview: Any, *, actor: str) -> dict[str, Any]:
    """Persist immutable original rows and proposals idempotently in a staging DB."""
    _assert_staging_session(session)
    if not actor or len(actor) > 120:
        raise ValueError("actor is required and must be at most 120 characters")
    if len(preview.rows) > 100_000:
        raise ValueError("workbook preview exceeds the 100,000 row staging limit")
    if preview.report.get("truncated") or preview.report.get("limit_reached"):
        raise ValueError("incomplete or limit-truncated previews cannot be staged")
    if (
        len(preview.content_hash) != 64
        or any(char not in "0123456789abcdef" for char in preview.content_hash.lower())
        or preview.content_hash != preview.content_hash.lower()
    ):
        raise ValueError("preview content_hash must be a lowercase SHA-256 hex digest")
    preview_fingerprint = _preview_fingerprint(preview)
    # Serialize duplicate uploads so the unique manifest constraint is a normal
    # replay path, rather than an avoidable IntegrityError race.
    lock_key = int.from_bytes(
        hashlib.sha256(preview.content_hash.encode()).digest()[:8], "big", signed=True
    )
    session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    existing = session.scalar(
        select(ExternalImportBatch).where(ExternalImportBatch.content_hash == preview.content_hash)
    )
    if existing is not None:
        if existing.metrics.get("preview_fingerprint") != preview_fingerprint:
            raise ValueError(
                "this file content was already staged with a different normalized preview"
            )
        return _result(session, existing, include_rows=True)

    normalized_rows = [dict(row.normalized) for row in preview.rows]
    catalog = _matching_catalog(session, normalized_rows)
    batch_metrics = {
        "total_rows": len(preview.rows),
        "preview_fingerprint": preview_fingerprint,
        "rows_with_errors": sum(bool(row.errors) for row in preview.rows),
        "rows_with_contacts": sum(
            any(row.normalized.get(key) for key in ("contact_name", "email", "phone"))
            for row in preview.rows
        ),
        "rows_with_power_assertions": sum(
            any(
                row.normalized.get(key) is not None
                for key in ("demand_mw", "supply_mw", "facility_demand_mw", "it_capacity_mw")
            )
            for row in preview.rows
        ),
        "exact_duplicate_groups": len(preview.report.get("exact_duplicates", [])),
        "probable_duplicate_groups": len(preview.report.get("probable_duplicates", [])),
        "ignored_rows": sum(
            row.row_kind in {"summary", "metadata"} or not row.normalized for row in preview.rows
        ),
    }

    batch = ExternalImportBatch(
        filename=preview.filename[:300],
        content_hash=preview.content_hash,
        report=preview.report,
        metrics=batch_metrics,
        actor=actor,
    )
    session.add(batch)
    session.flush()
    for start in range(0, len(preview.rows), 1000):
        source_chunk = preview.rows[start : start + 1000]
        row_records = []
        activation_records = []
        for source_row in source_chunk:
            normalized = dict(source_row.normalized)
            is_metadata = source_row.row_kind in {"summary", "metadata"} or not normalized
            site_candidates = [] if is_metadata else _site_project_candidates(normalized, catalog)
            if is_metadata:
                company = {
                    "status": "unmatched",
                    "candidate_id": None,
                    "reasons": ["summary/metadata rows are retained without identity matching"],
                }
                project = {
                    "status": "unmatched",
                    "candidate_id": None,
                    "reasons": ["summary/metadata rows are retained without project matching"],
                }
            else:
                company = _company_match(normalized, catalog, site_candidates)
                project = _project_match(normalized, company, catalog, site_candidates)
            errors = list(source_row.errors)
            status = (
                "ignored"
                if is_metadata
                else "invalid"
                if errors
                else "ambiguous"
                if "ambiguous" in (company["status"], project["status"])
                else "matched"
                if company["status"] == "matched" and project["status"] == "matched"
                else "unmatched"
            )
            row_id = uuid4()
            row_records.append(
                {
                    "id": row_id,
                    "batch_id": batch.id,
                    "sheet": source_row.sheet[:120],
                    "row_number": source_row.row_number,
                    "row_kind": source_row.row_kind,
                    "raw": source_row.raw,
                    "normalized": normalized,
                    "errors": errors,
                    "match_status": status,
                    "company_match": company,
                    "project_match": project,
                }
            )
            activation_records.append(
                {
                    "row_id": row_id,
                    "active": not errors and not is_metadata,
                    "changed_by": actor,
                }
            )
        if row_records:
            session.execute(insert(ExternalImportRow), row_records)
            session.execute(insert(ExternalImportActivation), activation_records)
    session.add(
        ExternalImportEvent(
            batch_id=batch.id,
            action="staged",
            actor=actor,
            details={"row_count": len(preview.rows), "source_content_hash": preview.content_hash},
        )
    )
    session.flush()
    return _result(session, batch, include_rows=True)


def rollback_import(session: Session, batch_id: str | UUID, *, actor: str) -> dict[str, Any]:
    """Reversibly deactivate staged rows, preserving original rows and audit history."""
    _assert_staging_session(session)
    if not actor or len(actor) > 120:
        raise ValueError("actor is required and must be at most 120 characters")
    try:
        identity = UUID(str(batch_id))
    except ValueError as exc:
        raise ValueError("batch_id must be a UUID") from exc
    batch = session.get(ExternalImportBatch, identity)
    if batch is None:
        raise LookupError("external import batch not found")
    lock_key = int.from_bytes(identity.bytes[:8], "big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    already_rolled_back = session.scalar(
        select(ExternalImportEvent.id).where(
            ExternalImportEvent.batch_id == identity, ExternalImportEvent.action == "rolled_back"
        )
    )
    if not already_rolled_back:
        active_count = (
            session.scalar(
                select(func.count())
                .select_from(ExternalImportActivation)
                .join(ExternalImportRow)
                .where(
                    ExternalImportRow.batch_id == identity,
                    ExternalImportActivation.active.is_(True),
                )
            )
            or 0
        )
        session.execute(
            update(ExternalImportActivation)
            .where(
                ExternalImportActivation.row_id.in_(
                    select(ExternalImportRow.id).where(ExternalImportRow.batch_id == identity)
                )
            )
            .values(active=False, changed_by=actor, changed_at=func.clock_timestamp())
        )
        session.add(
            ExternalImportEvent(
                batch_id=identity,
                action="rolled_back",
                actor=actor,
                details={"deactivated_rows": active_count},
            )
        )
        session.flush()
    return _result(session, batch, include_rows=True)


def import_history(session: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return newest staged batch summaries from the same explicitly isolated DB."""
    _assert_staging_session(session)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    batches = list(
        session.scalars(
            select(ExternalImportBatch)
            .order_by(ExternalImportBatch.created_at.desc(), ExternalImportBatch.id.desc())
            .limit(limit)
        )
    )
    return [_result(session, batch) for batch in batches]
