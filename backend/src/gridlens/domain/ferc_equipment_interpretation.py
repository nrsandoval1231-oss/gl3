"""Deterministic, site-scoped interpretation of native FERC equipment evidence.

The notice party is an attribution, not verified corporate identity. Admission
identifies a historical proposed equipment requirement, never current procurement.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from gridlens.domain.regional_scope import classify_project_region
from gridlens.ingestion.parsers.ferc_equipment import VERSION, extract_ferc_equipment

SOURCE_ID = "federal-register-eis"
EVALUATOR_VERSION = (
    "ferc-equipment-" + hashlib.sha256(("assessment-v1:" + VERSION).encode()).hexdigest()[:16]
)
_PDF = re.compile(r"/content/pkg/FR-(\d{4}-\d{2}-\d{2})/pdf/(\d{4}-\d{5})\.pdf")
_TITLE = re.compile(
    r"(?P<party>[^;\n]{3,250});\s*Notice of Availability of the Environmental Assessment "
    r"for the Proposed (?P<project>[^;\n]{3,250}) Project",
    re.I,
)


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
    return isinstance(title, str) and _TITLE.fullmatch(" ".join(title.split())) is not None


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
    if not isinstance(title, str) or _TITLE.fullmatch(" ".join(title.split())) is None:
        return None
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    if not re.search(r"\bFederal Energy Regulatory Commission\b|\bFERC\b", abstract, re.I):
        return None
    extracted = extract_ferc_equipment(abstract, title=title)
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
