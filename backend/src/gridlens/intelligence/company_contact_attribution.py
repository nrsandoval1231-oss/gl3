"""Conservative company identity checks for website-derived contact claims.

Names, footers, and imported domains are discovery hints. A website contact is
attributable to an RRC company identity only when the same publisher/employer
scope explicitly declares that identity's operator number. Exact-number native
RRC contact sources are separately bound by their retrieval parsers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from uuid import UUID
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.buying_chain_public import (
    validate_public_url,
)
from gridlens.persistence.models import BuyingChainEvidence, CompanyIdentity, Project

_NATIVE_IDENTITY_SOURCE_REASONS = {
    "exact-number public rrc operator registry organization phone.",
    "exact rrc operator-number p5 row; normal organization phone field.",
}
_PROJECT_SCOPED_NATIVE_SOURCE_REASONS = {
    "exact houston sold permit project, permit type, date and site match the selected project."
}
_WEBSITE_CONTACT_SOURCE_REASON = "self-identified official organization contact page."


def _subject_to_site_identity_policy(source: BuyingChainEvidence) -> bool:
    reason = source.project_match_reason.casefold()
    return reason == _WEBSITE_CONTACT_SOURCE_REASON or reason in (
        _NATIVE_IDENTITY_SOURCE_REASONS | _PROJECT_SCOPED_NATIVE_SOURCE_REASONS
    )


def _brand_key(value: str) -> str:
    return re.sub(r"(?:inc|incorporated|llc|corp|corporation|ltd)$", "", _normal(value))


def _normal(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _identifier_values(value: object) -> set[str]:
    rows = value if isinstance(value, list) else [value]
    matches: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = " ".join(
            str(row.get(key) or "") for key in ("propertyID", "name", "description")
        ).casefold()
        identifier = str(row.get("value") or "").strip()
        if "operator" in label and "rrc" in label and re.fullmatch(r"\d{6}", identifier):
            matches.add(identifier)
    return matches


def document_declares_operator_identity(
    document: object, *, organization: str, operator_number: str
) -> bool:
    """Require an operator ID explicitly scoped to the site's publisher/employer."""
    if not re.fullmatch(r"\d{6}", operator_number):
        return False
    try:
        url = validate_public_url(str(getattr(document, "url")))
    except (TypeError, ValueError):
        return False
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    structured_numbers: set[str] = set()
    structured_rows = getattr(document, "structured", ())
    for row in structured_rows:
        if not isinstance(row, dict) or row.get("@type") != "Organization":
            continue
        name = row.get("name")
        official_url = row.get("url")
        if not isinstance(name, str) or not isinstance(official_url, str):
            continue
        try:
            declared = urlsplit(validate_public_url(official_url))
        except ValueError:
            continue
        if (
            _brand_key(name) == _brand_key(organization)
            and (declared.hostname or "").casefold().removeprefix("www.") == host
            and declared.path == "/"
            and not declared.query
        ):
            structured_numbers.update(_identifier_values(row.get("identifier")))
    if structured_numbers:
        return structured_numbers == {operator_number}

    lines = str(getattr(document, "text", "")).splitlines()
    company_fields = re.compile(
        r"^\s*(?:company(?:\s+name)?|legal\s+name|organization|operator\s+name|"
        r"employer|publisher)\s*:\s*(?P<name>[^\n]{2,200}?)\s*$",
        re.I,
    )
    operator_fields = re.compile(
        r"^\s*(?:RRC\s+)?operator\s+(?:number|no\.?|#)\s*:\s*(?P<number>\d{6})\s*$",
        re.I,
    )
    scoped_numbers: set[str] = set()
    for index, line in enumerate(lines):
        operator_match = operator_fields.fullmatch(line)
        if not operator_match:
            continue
        # The exact legal name and identifier must be adjacent publisher or
        # employer fields; a directory mention elsewhere on the page is not a
        # binding for page-wide contact methods.
        for neighbor in lines[max(0, index - 2) : min(len(lines), index + 3)]:
            company_match = company_fields.fullmatch(neighbor)
            if company_match and _brand_key(company_match.group("name")) == _brand_key(
                organization
            ):
                scoped_numbers.add(operator_match.group("number"))
                break
    return scoped_numbers == {operator_number}


def _exact_houston_project_contact(
    session: Session, source: BuyingChainEvidence, project_id: str
) -> bool:
    if source.project_match_reason.casefold() not in _PROJECT_SCOPED_NATIVE_SOURCE_REASONS:
        return False
    try:
        url = validate_public_url(source.url)
    except ValueError:
        return False
    parsed_url = urlsplit(url)
    if (parsed_url.hostname or "").casefold() != "cohtora.houstontx.gov":
        return False
    project = session.get(Project, UUID(project_id))
    if project is None or project.source_id != "houston-weekly-permits":
        return False
    parts = project.external_id.split(":")
    if len(parts) != 3 or not parts[0].isdigit():
        return False
    fields = dict(
        re.findall(r"(?m)^([a-z_]+):\s*(.*?)\s*$", source.excerpt)
    )
    if fields.get("detail_project") != parts[0] or fields.get("detail_date") != parts[2]:
        return False
    site = re.sub(r"\s+", " ", fields.get("detail_site_address", "")).casefold()
    expected = re.sub(r"\s+", " ", (project.location or "").split(", Houston", 1)[0]).casefold()
    if not site.startswith(expected):
        return False
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import document_content_hash

    return source.content_hash == document_content_hash(
        PublicDocument(
            source.url,
            source.title,
            source.excerpt,
            extraction_location=source.extraction_location,
            published_at=source.published_at,
            observed_at=source.observed_at,
        )
    )


def source_is_identity_bound(
    session: Session,
    source: BuyingChainEvidence,
    *,
    company_id: str,
    organization: str,
    project_id: str,
) -> bool:
    """Check one current contact/role source against its canonical company ID."""
    identity = session.get(CompanyIdentity, company_id)
    if identity is None:
        return False
    if _exact_houston_project_contact(session, source, project_id):
        return True
    if source.project_match_reason.casefold() in _NATIVE_IDENTITY_SOURCE_REASONS:
        # These source records are produced only by exact-number native parsers.
        return bool(
            identity.rrc_operator_number
            and re.search(rf"(?<!\d){re.escape(identity.rrc_operator_number)}(?!\d)", source.excerpt)
        )
    if identity.rrc_operator_number is None:
        return False
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument

    document = PublicDocument(source.url, source.title, source.excerpt)
    return document_declares_operator_identity(
        document,
        organization=organization,
        operator_number=identity.rrc_operator_number,
    )


def document_matches_company_identity(
    session: Session,
    document: object,
    *,
    company_id: UUID,
    organization: str,
) -> bool:
    """Require a fetched publisher page to state the target stable operator ID."""
    identity = session.get(CompanyIdentity, company_id)
    return bool(
        identity
        and identity.rrc_operator_number
        and document_declares_operator_identity(
            document,
            organization=organization,
            operator_number=identity.rrc_operator_number,
        )
    )


def filter_unbound_company_contacts(session: Session, views: Iterable[dict]) -> None:
    """Hide website contacts/roles lacking identity proof from current projections.

    The claim and evidence rows remain append-only history. This projection
    guard applies uniformly to account, project, export, and contact consumers
    that read through ``buying_chain_view(s)``.
    """
    candidates = [
        candidate
        for view in views
        for candidate in view.get("candidates", [])
        if candidate.get("company_identity_id")
    ]
    evidence_ids: set[object] = set()
    for candidate in candidates:
        for citation in candidate.get("evidence", []):
            evidence_ids.add(citation.get("id"))
            evidence_ids.add(citation.get("current_source_version_id"))
    parsed_ids = []
    for value in evidence_ids:
        try:
            parsed_ids.append(value if isinstance(value, UUID) else UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    sources = {
        str(source.id): source
        for source in session.scalars(
            select(BuyingChainEvidence).where(BuyingChainEvidence.id.in_(set(parsed_ids)))
        )
    } if parsed_ids else {}

    for view in views:
        project_id = str(view.get("project_id") or "")
        kept = []
        for candidate in view.get("candidates", []):
            company_id = candidate.get("company_identity_id")
            if not company_id:
                kept.append(candidate)
                continue
            organization = str(candidate.get("organization") or "")
            source_for_citation: dict[tuple[str, str], BuyingChainEvidence] = {}
            verified_role_urls: set[str] = set()
            verified_contact_urls: set[str] = set()
            for citation in candidate.get("evidence", []):
                support = citation.get("supports")
                if support not in {
                    "public_contact",
                    "permit_listed_contact",
                    "organization_person_role",
                    "person_project_assignment",
                }:
                    continue
                source = sources.get(str(citation.get("id"))) or sources.get(
                    str(citation.get("current_source_version_id"))
                )
                if source is None:
                    continue
                if not _subject_to_site_identity_policy(source):
                    # Strong source-native project evidence (for example, an
                    # exact TDLR owner/contact extraction) keeps its existing
                    # parser and identity-link proof. This policy is for
                    # contact-discovery website pages and exact-ID native RRC.
                    source_for_citation[(support, str(citation.get("url") or ""))] = source
                    if support in {"public_contact", "permit_listed_contact"}:
                        verified_contact_urls.add(str(citation.get("url") or ""))
                    else:
                        verified_role_urls.add(str(citation.get("url") or ""))
                    continue
                if not source_is_identity_bound(
                    session,
                    source,
                    company_id=str(company_id),
                    organization=organization,
                    project_id=project_id,
                ):
                    continue
                url = str(citation.get("url") or "")
                source_for_citation[(support, url)] = source
                if support in {"public_contact", "permit_listed_contact"}:
                    verified_contact_urls.add(url)
                else:
                    verified_role_urls.add(url)

            candidate["public_contacts"] = [
                contact
                for contact in candidate.get("public_contacts", [])
                if str(contact.get("source_url") or "") in verified_contact_urls
            ]
            candidate["evidence"] = [
                citation
                for citation in candidate.get("evidence", [])
                if citation.get("supports")
                not in {
                    "public_contact",
                    "organization_person_role",
                    "person_project_assignment",
                }
                or (citation.get("supports"), str(citation.get("url") or ""))
                in source_for_citation
            ]
            if candidate.get("person_name") and not verified_role_urls:
                continue
            kept.append(candidate)
        view["candidates"] = kept
