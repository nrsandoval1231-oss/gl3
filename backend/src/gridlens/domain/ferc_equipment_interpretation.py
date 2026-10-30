"""Deterministic, site-scoped interpretation of native FERC equipment evidence.

The notice party is an attribution, not verified corporate identity. Admission
identifies a historical proposed equipment requirement, never current procurement.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from gridlens.domain.regional_scope import classify_project_region
from gridlens.ingestion.parsers.ferc_equipment import (
    VERSION,
    extract_ferc_equipment,
    parse_ferc_notice_title,
)

SOURCE_ID = "federal-register-eis"
EVALUATOR_VERSION = (
    "ferc-equipment-" + hashlib.sha256(("assessment-v1:" + VERSION).encode()).hexdigest()[:16]
)
_PDF = re.compile(r"/content/pkg/FR-(\d{4}-\d{2}-\d{2})/pdf/(\d{4}-\d{5})\.pdf")


def _notice_title(title: object) -> tuple[str, str, str] | None:
    return parse_ferc_notice_title(title) if isinstance(title, str) else None


def govinfo_document_identity(url: str | None, published: date | str | None) -> str | None:
    """Return the exact native document ID, or reject a noncanonical citation."""
    if not isinstance(url, str) or not isinstance(published, date | str):
        return None
    try:
        day = date.fromisoformat(published) if isinstance(published, str) else published
        parts = urlsplit(url)
        match = _PDF.fullmatch(parts.path)
        valid = (
            parts.scheme == "https"
            and parts.netloc == "www.govinfo.gov"
            and not parts.query
            and not parts.fragment
            and "?" not in url
            and "#" not in url
            and match is not None
            and match.group(1) == day.isoformat()
        )
    except (ValueError, TypeError):
        return None
    return match.group(2) if valid and match is not None else None


def is_ferc_equipment_title(title: object) -> bool:
    return _notice_title(title) is not None


def is_ferc_equipment_candidate(record: dict[str, Any]) -> bool:
    """Bound PDF inspection by source-native metadata; this is not admission."""
    title = record.get("title")
    if not is_ferc_equipment_title(title):
        return False
    document = govinfo_document_identity(record.get("pdf_url"), record.get("publication_date"))
    if document is None or document != record.get("document_number"):
        return False
    # The registered source and actual notice content are checked independently
    # by service/admission. A project title alone asserts neither demand nor region.
    return True


def assess_ferc_equipment(title: str, abstract: str | None) -> dict[str, Any] | None:
    """Identify exactly one proposed electric-equipment site, without assigning MW."""
    title_identity = _notice_title(title)
    if title_identity is None:
        return None
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    if not re.search(r"\bFederal Energy Regulatory Commission\b|\bFERC\b", abstract, re.I):
        return None
    extracted = extract_ferc_equipment(abstract, title=title)
    extracted.notice_kind = title_identity[2]
    selected = [
        site
        for site in extracted.sites
        if any(
            claim.drive == "electric"
            and claim.lifecycle_status in {"new", "proposed"}
            and claim.equipment_type in {"pump", "compressor"}
            for claim in site.claims
        )
    ]
    rejected: dict[str, Any] = {
        "decision": "unknown",
        "tier": None,
        "reason": (
            "Native notice does not establish exactly one unambiguous "
            "proposed electric-equipment site."
        ),
        "subject": None,
        "project_hint": None,
        "location": None,
        "power_activity": None,
        "activity_key": None,
        "native_equipment": {"extractor_version": extracted.extractor_version},
    }
    site_scopes = [
        (" ".join(site.facility.split()).casefold(), " ".join(site.location.split()).casefold())
        for site in extracted.sites
    ]
    if len(site_scopes) != len(set(site_scopes)):
        return {
            **rejected,
            "reason": "Duplicate or conflicting physical-site sections require investigation.",
        }
    if extracted.truncated or len(selected) != 1 or not extracted.source_party_name:
        return rejected
    site = selected[0]
    region = classify_project_region(site.location)
    if region.status != "ELIGIBLE":
        return {
            **rejected,
            "reason": "The stated equipment site is outside TX/OK/NM or unresolved.",
        }
    # Applicant-name disagreement stays an explicit investigation question; it
    # cannot establish a legal company identity. Structural scope failures cannot
    # be repaired by choosing one of the surviving parsed sites.
    if extracted.issues:
        return {
            **rejected,
            "reason": "Resolve unsupported or contradictory source equipment scope.",
        }
    identity = [extracted.source_party_name, site.facility, site.location]
    site_key = hashlib.sha256(
        json.dumps([" ".join(value.split()).casefold() for value in identity]).encode()
    ).hexdigest()
    reason = (
        f"The dated FERC notice reports proposed electric equipment at {site.facility} "
        f"({site.location}). This is a source-date proposal; current status, electrical "
        "demand, procurement, buyer and utility supply remain unverified."
    )
    return {
        "decision": "accepted",
        "tier": "Signal",
        "subject": site.facility,
        "project_hint": site.facility,
        "location": site.location,
        "power_activity": "facility-expansion",
        "activity_key": "facility-expansion",
        "reason": reason,
        "action": reason,
        "native_equipment": {
            "extractor_version": extracted.extractor_version,
            "notice_kind": extracted.notice_kind,
            "docket_context": source_docket_context(extracted, abstract),
            "project_activities": source_project_activities(extracted, abstract),
            "site_key": site_key,
            "heading": {
                "quote": site.heading_quote,
                "start": site.heading_start,
                "end": site.heading_end,
            },
            "company_attribution": {
                "value": extracted.source_party_name,
                "quote": extracted.source_party_quote,
                "start": extracted.source_party_start,
                "end": extracted.source_party_end,
                "source": "title",
            },
            "body_applicant_attribution": {
                "value": extracted.body_applicant_name,
                "quote": extracted.body_applicant_quote,
                "start": extracted.body_applicant_start,
                "end": extracted.body_applicant_end,
                "source": "abstract",
            },
            "scope": "identified_equipment_assertion",
            "complete_site_schedule": False,
            "current_status": "UNKNOWN",
            "company_identity": "UNKNOWN",
            "issues": extracted.attribution_issues,
        },
    }


def _validated_span(text: str, item: dict[str, Any]) -> bool:
    quote, start, end = item.get("quote"), item.get("start"), item.get("end")
    return (
        isinstance(quote, str)
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= len(text)
        and text[start:end] == quote
    )


def source_docket_context(extracted, text: str) -> dict[str, Any]:
    references = [dict(item) for item in extracted.docket_references]
    valid = bool(references) and all(_validated_span(text, item) for item in references)
    full_ids = {item.get("normalized_full") for item in references if item.get("normalized_full")}
    roots = {item.get("normalized_root") for item in references}
    unique_full = next(iter(full_ids)) if len(full_ids) == 1 else None
    family_consistent = len(roots) == 1 and all(item.get("normalized_root") for item in references)
    usable = bool(
        valid and family_consistent and len(full_ids) <= 1 and not extracted.docket_issues
    )
    issues = list(extracted.docket_issues)
    if not valid and references:
        issues.append("Docket source-span mismatch; docket identity is unresolved.")
    if len(full_ids) > 1 or not family_consistent:
        issues.append("Docket references conflict; docket identity is unresolved.")
    return {
        "status": "SOURCE_BOUND" if usable else "UNKNOWN",
        "normalized_full": unique_full if usable else None,
        "normalized_root": next(iter(roots)) if usable and roots else None,
        "identity_level": "full"
        if usable and unique_full
        else "root_only"
        if usable
        else "unknown",
        "references": references,
        "issues": sorted(set(issues)),
    }


def source_project_activities(extracted, text: str) -> list[dict[str, Any]]:
    return [
        {
            "activity": activity.activity,
            "quote": activity.quote,
            "start": activity.start,
            "end": activity.end,
            "scope": "context_only",
        }
        for activity in extracted.project_activities
        if _validated_span(text, asdict(activity))
    ]
