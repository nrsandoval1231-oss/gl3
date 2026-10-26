"""Isolated staging persistence for source workbooks; imports never change canonical claims."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Any, TypedDict
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, insert, literal_column, select, update
from sqlalchemy.orm import Session

from gridlens.ingestion.workbook_import import (
    HYPERLINK_METADATA_PARSER_REVISION,
)
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

MAX_RECONCILIATION_OUTPUT_ROWS = 500
MAX_RECONCILIATION_DUPLICATE_GROUPS = 200
MAX_DUPLICATE_GROUP_SAMPLE_ROWS = 10
MAX_DUPLICATE_HINTS_PER_ROW = 5
MAX_EXACT_PROJECT_CANDIDATES_PER_NAME = 20
MAX_EXACT_SOURCE_PROJECT_NAMES = 5000
MAX_PROBABLE_STATES = 50
MAX_PROBABLE_PROJECTS_PER_STATE = 200
MAX_PROBABLE_COMPANIES = 100
MAX_PROBABLE_PROJECTS_PER_COMPANY = 100
MAX_PROBABLE_COMPANY_PROJECTS = 500
MAX_PROBABLE_NAME_SCANS = 1000
MAX_PROJECT_CANDIDATE_DETAILS = 20
MAX_METADATA_REPARSE_BYTES = 16 * 1024 * 1024
MAX_METADATA_REPARSE_HINTS = 100_000
MAX_METADATA_REPARSE_REVISIONS = 10
MAX_METADATA_HINTS_IN_RESULT = 100

_ACTIVITY_SPECIFIC_POWER_HEADER = re.compile(
    r"(?:temporary|rental|construction|commissioning).*(?:demand|load|power)|"
    r"(?:demand|load|power).*(?:temporary|rental|construction|commissioning)",
    re.IGNORECASE,
)


class _ProbableProjectCandidate(TypedDict):
    candidate_id: str
    name: str
    location: str | None
    similarity: float
    reasons: list[str]


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


def _metadata_sidecar_keys(report: dict[str, Any]) -> dict[str, set[str]]:
    value = report.get("hyperlink_metadata_sidecar_keys", {})
    if not isinstance(value, dict):
        return {}
    return {
        str(sheet): {key for key in keys if isinstance(key, str)}
        for sheet, keys in value.items()
        if isinstance(keys, list)
    }


def _is_hyperlink_sidecar(key: str, value: Any, *, sidecar_keys: set[str]) -> bool:
    return bool(
        key in sidecar_keys
        and isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(column, str) and isinstance(target, str)
            for column, target in value.items()
        )
    )


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _raw_without_hyperlink_metadata(
    raw: dict[str, Any], *, sidecar_keys: set[str]
) -> dict[str, Any]:
    return {
        key: value
        for key, value in raw.items()
        if not _is_hyperlink_sidecar(key, value, sidecar_keys=sidecar_keys)
    }


def _hyperlink_metadata(preview: Any) -> tuple[str | None, list[dict[str, Any]]]:
    revision = preview.report.get("hyperlink_metadata_parser_revision")
    sidecar_keys_by_sheet = _metadata_sidecar_keys(preview.report)
    hints: list[dict[str, Any]] = []
    hint_bytes = 0
    for row in preview.rows:
        metadata = {
            key: value
            for key, value in row.raw.items()
            if _is_hyperlink_sidecar(
                key, value, sidecar_keys=sidecar_keys_by_sheet.get(row.sheet, set())
            )
        }
        for container in metadata.values():
            if not isinstance(container, dict):
                raise ValueError("hyperlink metadata must be a column-to-URL object")
            for column, target in container.items():
                if not isinstance(column, str) or not isinstance(target, str):
                    raise ValueError("hyperlink metadata contains an invalid target")
                hint_bytes += len(target.encode("utf-8"))
                if len(hints) >= MAX_METADATA_REPARSE_HINTS:
                    raise ValueError("recovered hyperlink metadata exceeds its target-count budget")
                if hint_bytes > MAX_METADATA_REPARSE_BYTES:
                    raise ValueError("recovered hyperlink metadata exceeds its staging byte budget")
                hints.append(
                    {
                        "sheet": row.sheet,
                        "row_number": row.row_number,
                        "column": column,
                        "url": target if _is_http_url(target) else None,
                        "target": target,
                        "verification_status": (
                            "UNVERIFIED_SOURCE_HINT"
                            if _is_http_url(target)
                            else "UNVERIFIED_UNSUPPORTED_HYPERLINK_TARGET"
                        ),
                    }
                )
    if not hints:
        return revision, []
    if revision != HYPERLINK_METADATA_PARSER_REVISION:
        raise ValueError("hyperlink metadata was not produced by the current workbook parser")
    serialized = json.dumps(hints, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_METADATA_REPARSE_BYTES:
        raise ValueError("recovered hyperlink metadata exceeds its staging byte budget")
    return revision, hints


def _append_metadata_reparse_if_unchanged(
    session: Session,
    batch: ExternalImportBatch,
    preview: Any,
    *,
    actor: str,
) -> None:
    """Append hyperlink hints only when every original staged row remains byte-stable."""
    metadata_report_fields = {
        "hyperlink_metadata_parser_revision",
        "hyperlink_metadata_sidecar_keys",
    }
    original_report = {
        key: value
        for key, value in batch.report.items()
        if key not in metadata_report_fields
    }
    replay_report = {
        key: value
        for key, value in preview.report.items()
        if key not in metadata_report_fields
    }
    if original_report != replay_report:
        raise ValueError("metadata-only replay changed workbook mapping or parser report")
    stored_rows = list(
        session.scalars(
            select(ExternalImportRow)
            .where(ExternalImportRow.batch_id == batch.id)
            .order_by(ExternalImportRow.sheet, ExternalImportRow.row_number)
        )
    )
    incoming_rows = sorted(preview.rows, key=lambda row: (row.sheet, row.row_number))
    sidecar_keys_by_sheet = _metadata_sidecar_keys(preview.report)
    if len(stored_rows) != len(incoming_rows):
        raise ValueError("metadata-only replay changed the original workbook row set")
    for stored, incoming in zip(stored_rows, incoming_rows, strict=True):
        if (
            stored.sheet != incoming.sheet
            or stored.row_number != incoming.row_number
            or stored.row_kind != incoming.row_kind
            or _raw_without_hyperlink_metadata(
                stored.raw, sidecar_keys=sidecar_keys_by_sheet.get(incoming.sheet, set())
            )
            != _raw_without_hyperlink_metadata(
                incoming.raw, sidecar_keys=sidecar_keys_by_sheet.get(incoming.sheet, set())
            )
            or stored.normalized != incoming.normalized
            or stored.errors != incoming.errors
        ):
            raise ValueError("metadata-only replay changed original raw or normalized row data")

    parser_revision, hints = _hyperlink_metadata(preview)
    metadata_payload = json.dumps(
        hints, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    metadata_fingerprint = hashlib.sha256(metadata_payload.encode("utf-8")).hexdigest()
    stored_sidecars = [
        {
            key: value
            for key, value in stored.raw.items()
            if _is_hyperlink_sidecar(
                key, value, sidecar_keys=sidecar_keys_by_sheet.get(stored.sheet, set())
            )
        }
        for stored in stored_rows
    ]
    incoming_sidecars = [
        {
            key: value
            for key, value in incoming.raw.items()
            if _is_hyperlink_sidecar(
                key, value, sidecar_keys=sidecar_keys_by_sheet.get(incoming.sheet, set())
            )
        }
        for incoming in incoming_rows
    ]
    stored_parser_revision = batch.report.get("hyperlink_metadata_parser_revision")
    if stored_parser_revision == parser_revision and stored_sidecars != incoming_sidecars:
        raise ValueError("the same parser revision produced different workbook hyperlink metadata")
    existing_revision = session.scalar(
        select(ExternalImportEvent).where(
            ExternalImportEvent.batch_id == batch.id,
            ExternalImportEvent.action == "metadata_reparsed",
            ExternalImportEvent.details["kind"].astext == "metadata_reparse",
            ExternalImportEvent.details["parser_revision"].astext == parser_revision,
        )
    )
    if existing_revision is not None:
        if existing_revision.details.get("metadata_fingerprint") != metadata_fingerprint:
            raise ValueError("this parser revision produced different hyperlink metadata")
        return
    existing_fingerprint = session.scalar(
        select(ExternalImportEvent).where(
            ExternalImportEvent.batch_id == batch.id,
            ExternalImportEvent.action == "metadata_reparsed",
            ExternalImportEvent.details["metadata_fingerprint"].astext == metadata_fingerprint,
        )
    )
    if existing_fingerprint is not None:
        return
    if stored_sidecars == incoming_sidecars and (
        any(stored_sidecars) or stored_parser_revision == parser_revision
    ):
        return
    if not hints:
        return
    if not isinstance(parser_revision, str) or not 1 <= len(parser_revision) <= 120:
        raise ValueError("hyperlink metadata parser revision is invalid")
    revision_count = session.scalar(
        select(func.count()).select_from(ExternalImportEvent).where(
            ExternalImportEvent.batch_id == batch.id,
            ExternalImportEvent.action == "metadata_reparsed",
        )
    )
    if revision_count >= MAX_METADATA_REPARSE_REVISIONS:
        raise ValueError("workbook metadata reparse revision limit reached")
    session.add(
        ExternalImportEvent(
            batch_id=batch.id,
            action="metadata_reparsed",
            actor=actor,
            details={
                "kind": "metadata_reparse",
                "source_content_hash": batch.content_hash,
                "parser_revision": parser_revision,
                "metadata_fingerprint": metadata_fingerprint,
                "target_count": len(hints),
                "hyperlink_hints": hints,
            },
        )
    )
    session.flush()


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
    supplied_domain = bool(str(normalized.get("domain") or "").strip()) or bool(
        email_domain and email_domain not in _FREE_EMAIL_DOMAINS
    )
    given_domain = domain or (email_domain if email_domain not in _FREE_EMAIL_DOMAINS else "")
    if not company_name:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "reasons": ["missing company name"],
        }
    if supplied_domain and not given_domain:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "reasons": ["supplied company domain could not be normalized"],
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

    if given_domain:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "reasons": [
                "supplied company domain has no current registered identity",
                "site evidence cannot override a conflicting or unknown domain",
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
    return {
        "status": "unmatched",
        "candidate_id": None,
        "reasons": ["company name alone is insufficient", "no corroborated current membership"],
    }


def _state_code(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().upper().split())
    return {"TEXAS": "TX", "OKLAHOMA": "OK", "NEW MEXICO": "NM"}.get(normalized, normalized)


def _site_evidence(normalized: dict[str, Any], project: Project) -> tuple[bool, list[str]]:
    """Return whether all supplied site facts agree and which facts independently match."""
    supplied_address = str(normalized.get("address") or "").strip()
    supplied_city = _normal_name(normalized.get("city"))
    supplied_state = _state_code(normalized.get("state"))
    location = str(project.location or "").strip()
    location_parts = [_normal_name(part) for part in location.split(",") if _normal_name(part)]
    reasons: list[str] = []

    if supplied_state and project.region_state and project.region_state != supplied_state:
        return False, []
    if supplied_state and not project.region_state:
        return False, []

    if supplied_city:
        canonical_city = ""
        if project.region_state and len(location_parts) >= 2:
            if location_parts[-1] == _normal_name(project.region_state):
                canonical_city = location_parts[-2]
        if not canonical_city or canonical_city != supplied_city:
            return False, []
        reasons.append("project name and city agree")

    if supplied_address:
        address_parts = [
            _normal_name(part) for part in supplied_address.split(",") if _normal_name(part)
        ]
        # Address is a whole street segment. Substring matches let a house
        # number or partial street name link unrelated physical sites.
        if (
            not address_parts
            or not location_parts
            or address_parts != location_parts[: len(address_parts)]
        ):
            return False, []
        reasons.append("project name and exact street-address segment agree")

    return True, reasons


def _site_project_candidates(
    normalized: dict[str, Any], catalog: dict[str, Any]
) -> list[tuple[Project, list[str]]]:
    project_name = _project_key(normalized.get("project_name"))
    if not project_name:
        return []
    candidates: list[tuple[Project, list[str]]] = []
    for project in catalog["projects_by_name"].get(project_name, []):
        compatible, reasons = _site_evidence(normalized, project)
        if not compatible:
            continue
        if reasons:
            candidates.append((project, reasons))
    return candidates


def _project_match(
    normalized: dict[str, Any],
    company_match: dict[str, Any],
    catalog: dict[str, Any],
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
    candidates: list[tuple[Project, list[str]]] = []
    name_candidates = catalog["projects_by_name"].get(project_name, [])
    exact_candidate_count = catalog["project_name_counts"].get(project_name, len(name_candidates))
    if project_name in catalog["exact_name_search_skipped"]:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "search_limited": True,
            "reasons": ["exact project-name search budget reached; no identity adopted"],
        }
    if catalog["project_name_search_truncated"].get(project_name, False):
        return {
            "status": "ambiguous",
            "candidate_id": None,
            "candidate_ids": [
                str(project.id) for project in name_candidates[:MAX_PROJECT_CANDIDATE_DETAILS]
            ],
            "candidate_count": exact_candidate_count,
            "candidates_truncated": True,
            "reasons": ["exact project-name candidate set exceeded its safe comparison bound"],
        }
    for project in name_candidates:
        compatible, corroborating = _site_evidence(normalized, project)
        if not compatible:
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
        candidate_ids = sorted(str(p.id) for p, _ in candidates)
        return {
            "status": "ambiguous",
            "candidate_ids": candidate_ids[:MAX_PROJECT_CANDIDATE_DETAILS],
            "candidate_count": len(candidate_ids),
            "candidates_truncated": len(candidate_ids) > MAX_PROJECT_CANDIDATE_DETAILS,
            "reasons": ["multiple existing projects have corroborating signals"],
        }
    if not name_candidates:
        probable, search_limited = _probable_project_match(normalized, company_match, catalog)
        if probable is not None:
            return probable
        if search_limited:
            return {
                "status": "unmatched",
                "candidate_id": None,
                "search_limited": True,
                "reasons": [
                    "no exact project name",
                    "probable project candidate search was bounded; no identity adopted",
                ],
            }
    if name_candidates:
        return {
            "status": "unmatched",
            "candidate_id": None,
            "candidate_ids": [str(p.id) for p in name_candidates[:MAX_PROJECT_CANDIDATE_DETAILS]],
            "candidate_count": exact_candidate_count,
            "candidates_truncated": exact_candidate_count > MAX_PROJECT_CANDIDATE_DETAILS,
            "reasons": [
                "project name matches but no independent site/company signal corroborates it"
            ],
        }
    return {
        "status": "unmatched",
        "candidate_id": None,
        "reasons": ["no exact existing project name", "no project created from import"],
    }


def _probable_project_match(
    normalized: dict[str, Any], company_match: dict[str, Any], catalog: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    """Return a non-adopting near-name project suggestion with independent corroboration."""
    source_name = _project_key(normalized.get("project_name"))
    if not source_name:
        return None, False
    state = _state_code(normalized.get("state"))
    matched_company = (
        UUID(str(company_match["candidate_id"]))
        if company_match.get("status") == "matched" and company_match.get("candidate_id")
        else None
    )
    cache_key = (source_name, state, matched_company)
    probable_names: dict[tuple[str, str, UUID | None], tuple[list[tuple[Project, float]], bool]] = (
        catalog["probable_names"]
    )
    limited = False
    if cache_key not in probable_names:
        if len(probable_names) >= MAX_PROBABLE_NAME_SCANS:
            limited = True
            near_names: list[tuple[Project, float]] = []
        else:
            state_pool = catalog["probable_projects_by_state"].get(state, []) if state else []
            company_pool = (
                catalog["probable_projects_by_company"].get(matched_company, [])
                if matched_company
                else []
            )
            candidate_pool = {project.id: project for project in (*state_pool, *company_pool)}
            if state:
                limited = catalog["probable_state_pool_truncated"].get(state, False) or (
                    state in catalog["probable_state_pool_skipped"]
                )
            elif not matched_company:
                limited = True
            if matched_company:
                limited = (
                    limited
                    or catalog["probable_company_pool_truncated"].get(matched_company, False)
                    or matched_company in catalog["probable_company_pool_skipped"]
                )
            near_names = [
                (candidate, ratio)
                for candidate in candidate_pool.values()
                if (candidate_name := _project_key(candidate.name)) != source_name
                and (ratio := SequenceMatcher(None, source_name, candidate_name).ratio()) >= 0.88
            ]
            probable_names[cache_key] = (near_names, limited)
    else:
        near_names, limited = probable_names[cache_key]
    suggestions: list[_ProbableProjectCandidate] = []
    company_projects = (
        catalog["projects_by_company"].get(matched_company, set()) if matched_company else set()
    )
    for candidate, ratio in near_names:
        compatible, site_reasons = _site_evidence(normalized, candidate)
        company_reason = candidate.id in company_projects
        if not compatible or not (site_reasons or company_reason):
            continue
        reasons = [f"similar normalized project name ({ratio:.3f})", *site_reasons]
        if company_reason:
            reasons.append("current company membership corroborates the project")
        suggestions.append(
            {
                "candidate_id": str(candidate.id),
                "name": candidate.name,
                "location": candidate.location,
                "similarity": round(ratio, 3),
                "reasons": reasons,
            }
        )
    suggestions.sort(key=lambda item: (-item["similarity"], item["candidate_id"]))
    candidates = suggestions[:MAX_PROJECT_CANDIDATE_DETAILS]
    candidates_truncated = len(suggestions) > MAX_PROJECT_CANDIDATE_DETAILS
    if len(suggestions) == 1 and not limited:
        return {
            "status": "probable",
            "candidate_id": suggestions[0]["candidate_id"],
            "search_limited": limited,
            "candidates": candidates,
            "candidate_count": 1,
            "reasons": [
                *suggestions[0]["reasons"],
                "suggestion only; exact identity not adopted",
            ],
        }, limited
    if suggestions:
        return {
            "status": "ambiguous",
            "candidate_id": None,
            "search_limited": limited,
            "candidate_ids": [item["candidate_id"] for item in candidates],
            "candidate_count_lower_bound": len(suggestions),
            "candidates_truncated": candidates_truncated,
            "candidates": candidates,
            "reasons": ["probable candidate pool is non-unique or truncated; no identity adopted"],
        }, limited
    return None, limited


def _matching_catalog(session: Session, normalized_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Load referenced companies plus projects needed for exact/probable matching."""
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
    project_name_counts: dict[str, int] = {}
    project_name_search_truncated: dict[str, bool] = {}
    project_ids: set[UUID] = set()
    exact_name_search_skipped = set(sorted(project_names)[MAX_EXACT_SOURCE_PROJECT_NAMES:])
    searchable_names = sorted(project_names)[:MAX_EXACT_SOURCE_PROJECT_NAMES]
    name_key = func.btrim(func.regexp_replace(func.lower(Project.name), "[^a-z0-9]+", " ", "g"))
    rows_per_name = MAX_EXACT_PROJECT_CANDIDATES_PER_NAME + 1
    for start in range(0, len(searchable_names), 5000):
        name_batch = searchable_names[start : start + 5000]
        if not name_batch:
            continue
        ranked = (
            select(
                Project.id.label("project_id"),
                name_key.label("project_key"),
                func.count().over(partition_by=name_key).label("candidate_count"),
                func.row_number()
                .over(partition_by=name_key, order_by=Project.id)
                .label("candidate_rank"),
            )
            .where(name_key.in_(name_batch))
            .subquery()
        )
        candidates = session.execute(
            select(Project, ranked.c.project_key, ranked.c.candidate_count)
            .join(ranked, ranked.c.project_id == Project.id)
            .where(ranked.c.candidate_rank <= rows_per_name)
            .order_by(ranked.c.project_key, Project.id)
        )
        for project, key, candidate_count in candidates:
            project_key = str(key)
            projects_by_name.setdefault(project_key, []).append(project)
            project_name_counts[project_key] = int(candidate_count)
            project_name_search_truncated[project_key] = int(candidate_count) > rows_per_name
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

    requested_states = sorted(
        {_state_code(row.get("state")) for row in normalized_rows if _state_code(row.get("state"))}
    )
    probable_state_pool_skipped = set(requested_states[MAX_PROBABLE_STATES:])
    probable_projects_by_state: dict[str, list[Project]] = {}
    probable_state_pool_truncated: dict[str, bool] = {}
    for state in requested_states[:MAX_PROBABLE_STATES]:
        state_projects = list(
            session.scalars(
                select(Project)
                .where(Project.region_state == state)
                .order_by(Project.id)
                .limit(MAX_PROBABLE_PROJECTS_PER_STATE + 1)
            )
        )
        probable_state_pool_truncated[state] = len(state_projects) > MAX_PROBABLE_PROJECTS_PER_STATE
        probable_projects_by_state[state] = state_projects[:MAX_PROBABLE_PROJECTS_PER_STATE]

    probable_company_pool_skipped = set(
        sorted(projects_by_company, key=str)[MAX_PROBABLE_COMPANIES:]
    )
    probable_projects_by_company: dict[UUID, list[Project]] = {}
    probable_company_pool_truncated: dict[UUID, bool] = {}
    for company_id in sorted(projects_by_company, key=str)[:MAX_PROBABLE_COMPANIES]:
        project_ids_for_company = sorted(projects_by_company[company_id], key=str)
        selected_ids = project_ids_for_company[:MAX_PROBABLE_PROJECTS_PER_COMPANY]
        company_projects = (
            list(
                session.scalars(
                    select(Project).where(Project.id.in_(selected_ids)).order_by(Project.id)
                )
            )
            if selected_ids
            else []
        )
        probable_projects_by_company[company_id] = company_projects
        probable_company_pool_truncated[company_id] = (
            len(project_ids_for_company) > MAX_PROBABLE_PROJECTS_PER_COMPANY
        )
    return {
        "companies_by_domain": companies_by_domain,
        "memberships_by_company": memberships_by_company,
        "memberships_by_project": memberships_by_project,
        "projects_by_company": projects_by_company,
        "projects_by_name": projects_by_name,
        "project_name_counts": project_name_counts,
        "project_name_search_truncated": project_name_search_truncated,
        "exact_name_search_skipped": exact_name_search_skipped,
        "probable_projects_by_state": probable_projects_by_state,
        "probable_state_pool_truncated": probable_state_pool_truncated,
        "probable_state_pool_skipped": probable_state_pool_skipped,
        "probable_projects_by_company": probable_projects_by_company,
        "probable_company_pool_truncated": probable_company_pool_truncated,
        "probable_company_pool_skipped": probable_company_pool_skipped,
        "probable_names": {},
        "probable_name_limit": MAX_PROBABLE_NAME_SCANS,
    }


def _has_activity_specific_demand_header(source_row: Any, worksheets: list[dict[str, Any]]) -> bool:
    for sheet in worksheets:
        if sheet.get("name") != source_row.sheet:
            continue
        return any(
            field == "demand_mw" and _ACTIVITY_SPECIFIC_POWER_HEADER.search(str(header))
            for header, field in sheet.get("mapped_columns", {}).items()
        )
    return False


def reconcile_preview(session: Session, preview: Any) -> dict[str, Any]:
    """Compare a parsed source with current canonical identities without writing anything.

    Every source row remains a proposal. A match reports identity evidence only; it
    never verifies imported claims or promotes a project/need.
    """
    normalized_rows = [dict(row.normalized) for row in preview.rows]
    catalog = _matching_catalog(session, normalized_rows)
    duplicate_refs: dict[tuple[str, int], list[dict[str, Any]]] = {}
    duplicate_group_reports: list[dict[str, Any]] = []
    duplicate_group_count = 0
    for kind, groups in (
        ("exact", preview.report.get("exact_duplicates", [])),
        ("probable", preview.report.get("probable_duplicates", [])),
    ):
        for group in groups:
            refs = group.get("rows", []) if isinstance(group, dict) else []
            if len(refs) < 2:
                continue
            duplicate_group_count += 1
            group_id = f"{kind}-{duplicate_group_count}"
            group_included = len(duplicate_group_reports) < MAX_RECONCILIATION_DUPLICATE_GROUPS
            if group_included:
                duplicate_group_reports.append(
                    {
                        "group_id": group_id,
                        "kind": kind,
                        "row_count": len(refs),
                        "sample_rows": refs[:MAX_DUPLICATE_GROUP_SAMPLE_ROWS],
                        "sample_truncated": len(refs) > MAX_DUPLICATE_GROUP_SAMPLE_ROWS,
                    }
                )
            for ref in refs:
                key = (str(ref.get("sheet", "")), int(ref.get("row_number", 0)))
                hints = duplicate_refs.setdefault(key, [])
                if len(hints) < MAX_DUPLICATE_HINTS_PER_ROW:
                    hints.append(
                        {
                            "group_id": group_id,
                            "kind": kind,
                            "row_count": len(refs),
                            "group_summary_included": group_included,
                        }
                    )

    rows: list[dict[str, Any]] = []
    counts = {
        key: 0
        for key in ("exact_match", "probable", "ambiguous", "unmatched", "invalid", "ignored")
    }
    for source_row in preview.rows:
        normalized = dict(source_row.normalized)
        metadata = source_row.row_kind in {"summary", "metadata"} or not normalized
        search_limited = False
        site_candidates = [] if metadata else _site_project_candidates(normalized, catalog)
        if metadata:
            company = {
                "status": "unmatched",
                "candidate_id": None,
                "reasons": ["metadata rows are not canonical entities"],
            }
            project = {
                "status": "unmatched",
                "candidate_id": None,
                "reasons": ["metadata rows are not canonical projects"],
            }
        else:
            company = _company_match(normalized, catalog, site_candidates)
            project = _project_match(normalized, company, catalog)
            search_limited = bool(project.get("search_limited"))
            if (
                source_row.row_kind == "contact"
                and not normalized.get("project_name")
                and any(normalized.get(key) for key in ("contact_name", "email", "phone"))
            ):
                project = {
                    "status": "not_applicable",
                    "candidate_id": None,
                    "reasons": ["contact-only row supplies no project relationship"],
                }
        status = (
            "ignored"
            if metadata
            else "invalid"
            if source_row.errors
            else "ambiguous"
            if "ambiguous" in (company["status"], project["status"])
            else "exact_match"
            if company["status"] == "matched" and project["status"] in {"matched", "not_applicable"}
            else "probable"
            if project["status"] == "probable"
            else "unmatched"
        )
        counts[status] += 1
        missing = []
        if not normalized.get("company_name"):
            missing.append(
                {
                    "field": "company_identity",
                    "priority": "high",
                    "reason": "no source company name to resolve",
                }
            )
        if not normalized.get("project_name"):
            missing.append(
                {
                    "field": "physical_project",
                    "priority": "high",
                    "reason": "no physical project name to resolve",
                }
            )
        if not normalized.get("address") and not normalized.get("city"):
            missing.append(
                {
                    "field": "site_location",
                    "priority": "high",
                    "reason": "physical-site corroboration is absent",
                }
            )
        activity_specific_demand = _has_activity_specific_demand_header(
            source_row, preview.report.get("worksheets", [])
        )
        reported_demand_present = (
            normalized.get("demand_mw") is not None or normalized.get("demand_mw_range") is not None
        )
        if not reported_demand_present or not activity_specific_demand:
            missing.append(
                {
                    "field": "temporary_demand",
                    "priority": "high",
                    "reason": (
                        "activity-specific demand is absent; generic demand/capacity is not "
                        "temporary demand"
                    ),
                }
            )
        if normalized.get("supply_mw") is None:
            missing.append(
                {
                    "field": "committed_supply",
                    "priority": "high",
                    "reason": "committed supply is absent; unknown is not zero",
                }
            )
        if not any(normalized.get(key) for key in ("contact_name", "email", "phone")):
            missing.append(
                {
                    "field": "buyer_contact",
                    "priority": "medium",
                    "reason": "no named business contact or contact method supplied",
                }
            )
        if normalized.get("duration_months") is None:
            missing.append(
                {"field": "duration", "priority": "medium", "reason": "duration is absent"}
            )
        if not normalized.get("required_date"):
            missing.append(
                {
                    "field": "need_date",
                    "priority": "medium",
                    "reason": "no independently stated required-power date",
                }
            )
        row_report = {
            "source": {
                "filename": preview.filename,
                "content_sha256": preview.content_hash,
                "sheet": source_row.sheet,
                "row_number": source_row.row_number,
                "row_kind": source_row.row_kind,
                "original_fields": list(source_row.raw),
            },
            "status": status,
            "company_match": company,
            "project_match": project,
            "probable_search_limited": search_limited if not metadata else False,
            "duplicate_hints": duplicate_refs.get((source_row.sheet, source_row.row_number), []),
            "verification": "unverified_source_assertions",
            "power_claims": {
                "reported_demand_mw": normalized.get("demand_mw"),
                "reported_demand_basis": "unverified_source_assertion",
                "temporary_demand_mw": (
                    normalized.get("demand_mw") if activity_specific_demand else None
                ),
                "reported_demand_range": normalized.get("demand_mw_range"),
                "temporary_demand_range": (
                    normalized.get("demand_mw_range") if activity_specific_demand else None
                ),
                "temporary_demand_basis": (
                    "unverified_activity_specific_source_assertion"
                    if activity_specific_demand
                    else "UNKNOWN_no_explicit_activity_specific_source_field"
                ),
                "facility_capacity_mw": normalized.get("facility_demand_mw"),
                "facility_capacity_range": normalized.get("facility_demand_mw_range"),
                "it_capacity_mw": normalized.get("it_capacity_mw"),
                "it_capacity_range": normalized.get("it_capacity_mw_range"),
                "committed_supply_mw": normalized.get("supply_mw"),
                "committed_supply_range": normalized.get("supply_mw_range"),
                "residual_gap_mw": None,
                "residual_gap_reason": (
                    "UNKNOWN until demand and committed supply are independently verified"
                ),
            },
            "promotion": {
                "eligible": False,
                "reason": (
                    "workbook assertions alone cannot verify identity, need, or qualification"
                ),
            },
            "missing_data": missing,
            "errors": source_row.errors,
        }
        if len(rows) < MAX_RECONCILIATION_OUTPUT_ROWS:
            rows.append(row_report)
    worksheets = preview.report.get("worksheets", [])
    source_preview_truncated = bool(
        preview.report.get("truncated") or preview.report.get("limit_reached")
    )
    return {
        "action": "reconcile",
        "read_only": True,
        "source": {
            "filename": preview.filename,
            "content_sha256": preview.content_hash,
            "sheets": worksheets[:MAX_RECONCILIATION_DUPLICATE_GROUPS],
            "sheets_omitted": max(0, len(worksheets) - MAX_RECONCILIATION_DUPLICATE_GROUPS),
            "field_mapping": {
                sheet.get("name"): sheet.get("mapped_columns", {})
                for sheet in worksheets[:MAX_RECONCILIATION_DUPLICATE_GROUPS]
            },
        },
        "complete": not source_preview_truncated
        and len(preview.rows) <= MAX_RECONCILIATION_OUTPUT_ROWS,
        "processed_all_preview_rows": True,
        "row_details_truncated": len(preview.rows) > len(rows),
        "summary": {
            **counts,
            "rows": len(preview.rows),
            "rows_included": len(rows),
            "rows_omitted": max(0, len(preview.rows) - len(rows)),
            "source_preview_truncated": source_preview_truncated,
            "duplicate_groups": duplicate_group_count,
            "duplicate_groups_included": len(duplicate_group_reports),
            "duplicate_groups_omitted": max(
                0, duplicate_group_count - len(duplicate_group_reports)
            ),
        },
        "duplicate_groups": duplicate_group_reports,
        "rows": rows,
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
    metadata_events = session.execute(
        select(
            ExternalImportEvent.id,
            ExternalImportEvent.actor,
            ExternalImportEvent.created_at,
            ExternalImportEvent.details["source_content_hash"].astext.label("source_content_hash"),
            ExternalImportEvent.details["parser_revision"].astext.label("parser_revision"),
            ExternalImportEvent.details["metadata_fingerprint"].astext.label(
                "metadata_fingerprint"
            ),
            ExternalImportEvent.details["target_count"].as_integer().label("target_count"),
            func.jsonb_path_query_array(
                ExternalImportEvent.details,
                literal_column("'$.hyperlink_hints[0 to 99]'::jsonpath"),
            ).label("hyperlink_hints"),
        )
        .where(
            ExternalImportEvent.batch_id == batch.id,
            ExternalImportEvent.action == "metadata_reparsed",
        )
        .order_by(ExternalImportEvent.created_at, ExternalImportEvent.id)
    ).all()
    sidecar_keys_by_sheet = _metadata_sidecar_keys(batch.report)
    hints_by_row: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for event in metadata_events:
        for hint in event.hyperlink_hints or []:
            key = (str(hint.get("sheet") or ""), int(hint.get("row_number") or 0))
            hints_by_row.setdefault(key, []).append(
                {
                    "url": hint["url"],
                    "target": hint["target"],
                    "column": hint["column"],
                    "verification_status": hint["verification_status"],
                    "parser_revision": event.parser_revision,
                    "event_id": str(event.id),
                }
            )
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
        for row in rows:
            raw_hints = [
                {
                    "url": target if _is_http_url(target) else None,
                    "target": target,
                    "column": column,
                    "verification_status": (
                        "UNVERIFIED_SOURCE_HINT"
                        if _is_http_url(target)
                        else "UNVERIFIED_UNSUPPORTED_HYPERLINK_TARGET"
                    ),
                    "parser_revision": batch.report.get(
                        "hyperlink_metadata_parser_revision"
                    ),
                    "event_id": None,
                }
                for key, container in row.raw.items()
                if _is_hyperlink_sidecar(
                    key,
                    container,
                    sidecar_keys=sidecar_keys_by_sheet.get(row.sheet, set()),
                )
                for column, target in container.items()
            ]
            row_hints = [*hints_by_row.get((row.sheet, row.row_number), []), *raw_hints]
            serialized.append(
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
                    "unverified_hyperlink_hints": row_hints[:MAX_METADATA_HINTS_IN_RESULT],
                    "unverified_hyperlink_hints_truncated": (
                        len(row_hints) > MAX_METADATA_HINTS_IN_RESULT
                    ),
                }
            )
    rolled_back = session.scalar(
        select(ExternalImportEvent.id).where(
            ExternalImportEvent.batch_id == batch.id,
            ExternalImportEvent.action == "rolled_back",
        )
    ) is not None
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
        "metadata_reparse_receipts": [
            {
                "event_id": str(event.id),
                "actor": event.actor,
                "source_content_hash": event.source_content_hash,
                "parser_revision": event.parser_revision,
                "metadata_fingerprint": event.metadata_fingerprint,
                "target_count": event.target_count,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "hyperlink_hints": event.hyperlink_hints or [],
                "hyperlink_hints_truncated": event.target_count > len(event.hyperlink_hints or []),
            }
            for event in metadata_events
        ],
        "recovered_unverified_hyperlink_hint_count": sum(
            event.target_count for event in metadata_events
        ),
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
        _append_metadata_reparse_if_unchanged(session, existing, preview, actor=actor)
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
                project = _project_match(normalized, company, catalog)
            errors = list(source_row.errors)
            is_company_only_contact = (
                not is_metadata
                and source_row.row_kind == "contact"
                and bool(
                    normalized.get("contact_name")
                    or normalized.get("email")
                    or normalized.get("phone")
                )
                and not normalized.get("project_name")
            )
            if is_company_only_contact:
                project = {
                    "status": "not_applicable",
                    "candidate_id": None,
                    "reasons": ["contact-only row has no supplied project relationship"],
                }
            status = (
                "ignored"
                if is_metadata
                else "invalid"
                if errors
                else "ambiguous"
                if "ambiguous" in (company["status"], project["status"])
                else "matched"
                if company["status"] == "matched"
                and (project["status"] == "matched" or project["status"] == "not_applicable")
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
                    "active": not errors and not is_metadata and status == "matched",
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
            details={
                "kind": "initial_stage",
                "row_count": len(preview.rows),
                "source_content_hash": preview.content_hash,
            },
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
