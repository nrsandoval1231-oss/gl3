"""Source and evidence rules for admitting a standalone opportunity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

POLICY_VERSION = "signal-admission-v1"

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
    "ceqanet-data-centers",
}
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
    if family == "municipal-planning-news" or retrieval_method == "taylor-newsflash":
        return "Official planning context"
    if retrieval_method in _PERMIT_METHODS and family == "construction-permits":
        return "Official permit"
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
    if retrieval_method in _PERMIT_METHODS and family == "construction-permits":
        return Admission(True, origin, "Accepted evidence from an official permit source.")
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
