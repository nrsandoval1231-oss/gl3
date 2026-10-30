"""Source and evidence rules for admitting a standalone opportunity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

POLICY_VERSION = "signal-admission-v2"
F17_RETAINED_ACCEPTED_REASON = (
    "Accepted a cited exact-source site record; load, dates, and supply remain unknown."
)

_PERMIT_METHODS = {
    "socrata-permits",
    "georgia-air-permits",
    "boston-ckan-permits",
    "houston-weekly-permits",
    "dallas-monthly-permits",
    "el-paso-new-commercial-permits",
    "rrc-drilling-permits",
    "tceq-nsr-pending",
    "tceq-temporary-batch-plants",
    "fort-worth-permits",
    "san-antonio-permits",
    "tdlr-tabs",
    "ok-deq-public-review",
    "cabq-building-permits",
    "tceq-egu-search",
    "tceq-construction-noi",
}
_ENVIRONMENTAL_REVIEW_FAMILY = "environmental-review-filings"
_ENVIRONMENTAL_REVIEW_METHODS = {"ceqanet-data-centers"}
_CULTIVATION_FAMILY = "cultivation-license-applications"
_CULTIVATION_METHOD = "ma-cultivation-applications"
_UTILITY_FAMILIES = {"official-utility-filings"}
_UTILITY_METHODS = {"utility-docket", "utility-filings"}
_PROCUREMENT_FAMILIES = {"temporary-power-procurement"}
_PROCUREMENT_METHODS = {"public-procurement", "procurement-notice"}
_PROCUREMENT_TERMS = (
    "temporary power",
    "temporary generator",
    "rental generator",
    "mobile generator",
    "load bank",
    "loadbank",
)
_PROCUREMENT_REQUEST_TERMS = (
    "request for quotation",
    "request for proposal",
    "solicitation",
    "bid due",
    "quotes due",
    "procurement notice",
)
_UTILITY_ACTIVITY = {
    "temporary-power",
    "bridge-power",
    "construction",
    "facility-expansion",
    "commissioning",
    "electrical-buildout",
    "utility-service",
}
_UTILITY_EVENT_TERMS = (
    "utility service",
    "energization",
    "substation",
    "transformer",
    "service agreement",
    "interconnection",
    "load service",
    "power allocation",
    "bridge power",
)


@dataclass(frozen=True)
class Admission:
    admitted: bool
    origin: str
    reason: str

    def as_basis(self, source_id: str, evidence_hash: str) -> dict[str, str]:
        return {
            "policy_version": POLICY_VERSION,
            "origin": self.origin,
            "reason": self.reason,
            "source_id": source_id,
            "evidence_hash": evidence_hash,
        }


def source_origin(family: str, retrieval_method: str) -> str:
    """Return a display-safe origin label based on registered source metadata."""
    if family == "ercot-impact-rfi":
        return {
            "ercot-impact-rfi-schema": "Public RFI question schema",
            "ercot-impact-rfi-aggregate": "Public RFI aggregate results",
            "ercot-impact-rfi-anonymized": "Public RFI anonymized results",
            "ercot-impact-rfi-project": "Public RFI project disclosure",
        }.get(retrieval_method, "Unverified RFI context")
    if family == "news" or retrieval_method == "publisher-rss":
        return "News context"
    if retrieval_method == "retained-document" and family == "retained-public-document":
        return "Retained public document; claimant statements are attributed, not adjudicated"
    if retrieval_method == "retained-document" and family == "retained-operator-publication":
        return "Retained operator publication; context, not procurement evidence"
    if family == "municipal-planning-news" or retrieval_method == "taylor-newsflash":
        return "Official planning context"
    if retrieval_method == "tdlr-tabs" and family == "construction-permits":
        # An accessibility-review registration, not a building permit.
        return "Official TDLR project registration"
    if retrieval_method in _PERMIT_METHODS and family == "construction-permits":
        return "Official permit"
    if retrieval_method in _ENVIRONMENTAL_REVIEW_METHODS and family == _ENVIRONMENTAL_REVIEW_FAMILY:
        return "Official environmental-review filing"
    if retrieval_method == _CULTIVATION_METHOD and family == _CULTIVATION_FAMILY:
        return "Official cultivation application"
    if family in _UTILITY_FAMILIES and retrieval_method in _UTILITY_METHODS:
        return "Official utility filing"
    if family in _PROCUREMENT_FAMILIES and retrieval_method in _PROCUREMENT_METHODS:
        return "Temporary-power solicitation"
    if family in {"economic-development-publication", "structured-government"}:
        return "Government research context"
    return "Source evidence"


def admit_standalone(
    *,
    source_id: str,
    family: str,
    retrieval_method: str,
    accepted: bool,
    activity: str | None,
    title: str,
    abstract: str | None,
    dated: bool = False,
    citation_url: str | None = None,
    identified_project: bool = False,
) -> Admission:
    """Check source authority and retained claim content before opportunity creation.

    The family/method pair is an explicit source-registry contract. A publisher RSS
    feed remains context even if it contains procurement-like words.
    """
    origin = source_origin(family, retrieval_method)
    if not accepted:
        return Admission(False, origin, "The current source version has no accepted assessment.")
    if retrieval_method == "retained-document":
        from gridlens.ingestion.adapters.retained_document import SOURCES

        policy = SOURCES.get(source_id)
        # Preserve the exact reviewed words while matching ordinary PDF line
        # wrapping consistently with the retained-document parser.
        text = re.sub(r"\s+", " ", f"{title} {abstract or ''}").casefold()
        exact_family = family == (
            "retained-operator-publication"
            if source_id == "f17-crusoe-impact"
            else "retained-public-document"
        )
        valid = bool(
            policy
            and exact_family
            and activity == policy["activity"]
            and dated
            and citation_url == policy["url"]
            and identified_project
            and policy["project_cue"].casefold() in text
            and policy["site_cue"].casefold() in text
            and all(cue.casefold() in text for cue in policy["location_cues"])
        )
        return Admission(
            valid,
            origin,
            F17_RETAINED_ACCEPTED_REASON
            if valid
            else "The retained document is not an exact reviewed source/site/activity record.",
        )
    if retrieval_method in _PERMIT_METHODS and family == "construction-permits":
        return Admission(True, origin, "Accepted evidence from an official permit source.")
    if retrieval_method == "spp-interconnection-queue" and family == "interconnection-queue":
        text = f"{title} {abstract or ''}".casefold()
        explicit_load = any(
            term in text
            for term in (
                "data center",
                "datacenter",
                "behind-the-meter",
                "behind the meter",
                "bridge power",
                "temporary power",
            )
        )
        if (
            activity in {"facility-expansion", "temporary-power", "bridge-power"}
            and explicit_load
            and dated
            and citation_url
            and citation_url.startswith("https://opsportal.spp.org/")
            and identified_project
        ):
            return Admission(
                True,
                "Official interconnection queue",
                "Accepted an SPP interconnection row that states a data-center or "
                "explicit temporary, bridge, or behind-the-meter load. Queue MW is "
                "generation injection, not site load.",
            )
        return Admission(
            False,
            "Official interconnection queue",
            "An SPP generation-interconnection row without a stated data-center or "
            "temporary, bridge, or behind-the-meter load stays queue evidence.",
        )
    if (
        retrieval_method in {"puct-interchange", "puct-docket-index"}
        and family == "official-utility-filings"
    ):
        text = f"{title} {abstract or ''}".casefold()
        explicit_load = any(
            term in text
            for term in (
                "data center",
                "datacenter",
                "behind-the-meter",
                "behind the meter",
                "bridge power",
                "temporary power",
            )
        )
        if (
            activity in {"facility-expansion", "temporary-power", "bridge-power"}
            and explicit_load
            and dated
            and citation_url
            and citation_url.startswith("https://interchange.puc.texas.gov/")
            and identified_project
        ):
            return Admission(
                True,
                "Official utility filing",
                "Accepted a PUCT large-load filing that names a data center or "
                "explicit temporary, bridge, or behind-the-meter power at a stated place.",
            )
        return Admission(
            False,
            "Official utility filing",
            "A PUCT filing without a stated place and an explicit data-center or "
            "temporary, bridge, or behind-the-meter load stays filing evidence.",
        )
    if retrieval_method in _ENVIRONMENTAL_REVIEW_METHODS and family == _ENVIRONMENTAL_REVIEW_FAMILY:
        return Admission(
            True,
            origin,
            "Accepted an official environmental-review filing that names a project site; "
            "construction, load and schedule are not established.",
        )
    if retrieval_method == _CULTIVATION_METHOD and family == _CULTIVATION_FAMILY:
        if (
            activity == "cultivation-license-application"
            and dated
            and citation_url
            and citation_url.startswith("https://masscannabiscontrol.com/resource/")
            and identified_project
        ):
            return Admission(
                True,
                origin,
                "Accepted a dated, site-identified CCC cultivation application event; "
                "construction, load, rental need, and authority remain unknown.",
            )
        return Admission(
            False,
            origin,
            "A dated CCC cultivation application and identified physical site are required.",
        )
    if family in _UTILITY_FAMILIES and retrieval_method in _UTILITY_METHODS:
        text = f"{title} {abstract or ''}"
        supported_action = bool(
            isinstance(activity, str)
            and activity in _UTILITY_ACTIVITY
            and any(term in text.casefold() for term in _UTILITY_EVENT_TERMS)
            and dated
            and citation_url
            and citation_url.startswith("https://")
            and identified_project
        )
        if supported_action:
            return Admission(
                True,
                origin,
                "Accepted dated evidence describes a concrete project-specific utility activity.",
            )
        return Admission(
            False,
            origin,
            (
                "A generic or undated utility record does not establish a "
                "project-specific power activity."
            ),
        )
    if family in _PROCUREMENT_FAMILIES and retrieval_method in _PROCUREMENT_METHODS:
        text = f"{title} {abstract or ''}".casefold()
        explicit_power = any(term in text for term in _PROCUREMENT_TERMS)
        explicit_request = any(term in text for term in _PROCUREMENT_REQUEST_TERMS)
        if (
            activity in {"temporary-power", "bridge-power"}
            and explicit_power
            and explicit_request
            and dated
            and citation_url
            and citation_url.startswith("https://")
            and identified_project
        ):
            return Admission(
                True,
                origin,
                (
                    "Accepted official solicitation explicitly requests temporary "
                    "power equipment or service."
                ),
            )
        return Admission(
            False,
            origin,
            "The official notice does not explicitly identify a temporary-power solicitation.",
        )
    return Admission(
        False,
        origin,
        "This source is retained as project context and cannot independently admit an opportunity.",
    )


def admitted_from_source(source: Any, assessment: dict[str, Any], evidence: Any) -> Admission:
    """Evaluate a persisted accepted assessment and its exact retained evidence."""
    if str(source.id) == "federal-register-eis" and assessment.get("native_equipment"):
        from gridlens.domain.ferc_equipment_interpretation import (
            assess_ferc_equipment,
            govinfo_document_identity,
        )

        native_fresh = assess_ferc_equipment(evidence.title, evidence.abstract)
        valid = bool(
            source.family == "structured-government"
            and source.retrieval_method == "json-api"
            and assessment.get("decision") == "accepted"
            and assessment.get("tier") == "Signal"
            and assessment.get("evidence_hash") == evidence.content_hash
            and govinfo_document_identity(evidence.url, evidence.published_at) is not None
            and govinfo_document_identity(evidence.url, evidence.published_at)
            == assessment.get("source_document_number")
            and isinstance(assessment.get("evidence"), dict)
            and assessment["evidence"].get("id") == str(evidence.id)
            and assessment["evidence"].get("url") == evidence.url
            and evidence.observed_at is not None
            and evidence.published_at is not None
            and evidence.published_at <= evidence.observed_at.date()
            and native_fresh
            and native_fresh.get("decision") == "accepted"
            and all(
                assessment.get(key) == native_fresh.get(key)
                for key in (
                    "subject",
                    "project_hint",
                    "location",
                    "power_activity",
                    "native_equipment",
                )
            )
        )
        return Admission(
            valid,
            "Official federal equipment proposal",
            (
                "Accepted a dated, source-bound single-site electric-equipment proposal; "
                "current status and power quantities remain unverified."
            )
            if valid
            else "FERC equipment requires exact current native site, source and evidence binding.",
        )
    if source.retrieval_method == "retained-document":
        from gridlens.ingestion.adapters.retained_document import SOURCES

        policy = SOURCES.get(str(source.id))
        if policy is None:
            return Admission(
                False,
                source_origin(source.family, source.retrieval_method),
                "Retained source hash and reviewed-page provenance are required.",
            )
        retained = (evidence.provenance or {}).get("retained_document", {})
        if not isinstance(retained, dict):
            return Admission(
                False,
                source_origin(source.family, source.retrieval_method),
                "Retained source hash and reviewed-page provenance are required.",
            )
        exact = bool(
            retained.get("sha256") == policy["sha256"]
            and retained.get("path") == policy["path"]
            and retained.get("source_site") == policy["location"]
            and bool(retained.get("project_name"))
            and retained.get("reviewed_spans")
            and assessment.get("evidence_hash") == evidence.content_hash
        )
        if not exact:
            return Admission(
                False,
                source_origin(source.family, source.retrieval_method),
                "Retained source hash and reviewed-page provenance are required.",
            )
        valid = bool(
            assessment.get("decision") == "accepted"
            and assessment.get("evidence_hash") == evidence.content_hash
            and assessment.get("subject") == retained.get("project_name")
            and assessment.get("location") == policy["location"]
            and assessment.get("power_activity") == policy["activity"]
            and evidence.url == policy["url"]
            and (evidence.published_at or evidence.event_date)
        )
        return Admission(
            valid,
            source_origin(source.family, source.retrieval_method),
            F17_RETAINED_ACCEPTED_REASON
            if valid
            else "Retained source assessment does not match its exact reviewed identity.",
        )
    if source.family == "news" and source.retrieval_method == "publisher-rss":
        # Re-evaluate the exact retained evidence; derived city/state names need
        # not appear verbatim in the source, but every derived field must match.
        from gridlens.domain.news_interpretation import assess_news, signal_power_activity

        fresh = assess_news(evidence.title, evidence.abstract)
        activity = signal_power_activity(fresh.action) or "project-discovery"
        valid = (
            fresh.decision == "accepted"
            and fresh.tier == "Signal"
            and assessment.get("decision") == "accepted"
            and assessment.get("tier") == "Signal"
            and assessment.get("evidence_hash") == evidence.content_hash
            and all(
                assessment.get(key) == getattr(fresh, key)
                for key in ("subject", "location", "action")
            )
            and assessment.get("power_activity") == activity
            and bool(fresh.subject and fresh.location and fresh.action)
            and bool(evidence.published_at or evidence.event_date)
            and bool(evidence.url and evidence.url.startswith("https://"))
        )
        return Admission(
            valid,
            "News context",
            "Accepted dated site-specific news discovery; power facts remain unknown."
            if valid
            else "News discovery requires an exact, dated, linked site assessment.",
        )
    evidence_text = f"{evidence.title} {evidence.abstract or ''}".casefold()
    subject = str(assessment.get("subject") or assessment.get("project_name") or "").strip()
    location = str(assessment.get("location") or "").strip()
    result = admit_standalone(
        source_id=str(source.id),
        family=str(source.family),
        retrieval_method=str(source.retrieval_method),
        accepted=(
            assessment.get("decision") == "accepted"
            and assessment.get("evidence_hash") == evidence.content_hash
        ),
        activity=(assessment.get("power_activity") or assessment.get("activity_key")),
        title=evidence.title,
        abstract=evidence.abstract,
        dated=bool(evidence.published_at or evidence.event_date),
        citation_url=evidence.url,
        identified_project=bool(
            subject
            and location
            and subject.casefold() in evidence_text
            and location.casefold() in evidence_text
        ),
    )
    return result
