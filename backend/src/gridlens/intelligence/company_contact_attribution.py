"""Conservative company identity checks for website-derived contact claims.

Names, footers, page-supplied operator IDs, and imported domains are discovery
hints. The current schema has no authoritative company-domain binding, so
company websites cannot currently establish an RRC company's identity. Exact
native RRC and retained project-source records are checked against their native
provenance before their contact claims remain visible.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.buying_chain_public import (
    PublicDocument,
    validate_public_url,
)
from gridlens.persistence.models import (
    BuyingChainEvidence,
    CompanyIdentity,
    Evidence,
    Interpretation,
    Observation,
    Project,
    Source,
)

_NATIVE_IDENTITY_SOURCE_REASONS = {
    "exact-number public rrc operator registry organization phone.",
    "exact rrc operator-number p5 row; normal organization phone field.",
}
_PROJECT_SCOPED_NATIVE_SOURCE_REASONS = {
    "exact houston sold permit project, permit type, date and site match the selected project."
}


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


def document_claims_operator_identity(
    document: object, *, organization: str, operator_number: str
) -> bool:
    """Read an explicitly scoped site claim; this is not independent ID proof."""
    if not re.fullmatch(r"\d{6}", operator_number):
        return False
    try:
        url = validate_public_url(str(document.url))
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
    source: BuyingChainEvidence,
    project: Project | None,
    *,
    organization: str,
) -> bool:
    if source.project_match_reason.casefold() not in _PROJECT_SCOPED_NATIVE_SOURCE_REASONS:
        return False
    try:
        url = validate_public_url(source.url)
    except ValueError:
        return False
    parsed_url = urlsplit(url)
    if (
        parsed_url.hostname or ""
    ).casefold() != "cohtora.houstontx.gov" or parsed_url.path != "/ibi_apps/WFServlet.ibfs":
        return False
    if project is None or project.source_id != "houston-weekly-permits":
        return False
    parts = project.external_id.split(":")
    if len(parts) != 3 or not parts[0].isdigit():
        return False
    from urllib.parse import parse_qs

    query = parse_qs(parsed_url.query, strict_parsing=True)
    from gridlens.ingestion.adapters.houston_permit_details import (
        SUPPORTED_TYPES,
        response_type_code,
    )

    expected_type_code = SUPPORTED_TYPES.get(parts[1])
    if (
        expected_type_code is None
        or query.get("PN") != [parts[0]]
        or query.get("PT") != [expected_type_code]
    ):
        return False
    fields = dict(re.findall(r"(?m)^([a-z_]+):\s*(.*?)\s*$", source.excerpt))
    if (
        fields.get("detail_project") != parts[0]
        or fields.get("detail_date") != parts[2]
        or response_type_code(fields.get("detail_permit_type", "")) != expected_type_code
        or _brand_key(fields.get("detail_buyer", "")) != _brand_key(organization)
    ):
        return False
    site = re.sub(r"\s+", " ", fields.get("detail_site_address", "")).casefold()
    expected = re.sub(r"\s+", " ", (project.location or "").split(", Houston", 1)[0]).casefold()
    if not site or not expected or not site.startswith(expected):
        return False
    from gridlens.intelligence.buying_chain import document_content_hash

    computed = document_content_hash(
        PublicDocument(
            source.url,
            source.title,
            source.excerpt,
            extraction_location=source.extraction_location,
            published_at=source.published_at,
            observed_at=source.observed_at,
        )
    )
    return source.content_hash == computed


def supported_contact_facts(
    session: Session,
    source: BuyingChainEvidence,
    *,
    organization: str,
    identity: CompanyIdentity | None,
    project: Project | None,
    retained_context: tuple[Evidence, Observation, Interpretation, Source] | None,
    person_name: str | None,
) -> set[tuple[str, str]]:
    """Return only exact contact/role facts revalidated by native parsers."""
    if identity is None:
        return set()
    if source.project_match_reason.casefold() in _PROJECT_SCOPED_NATIVE_SOURCE_REASONS:
        if not _exact_houston_project_contact(source, project, organization=organization):
            return set()
        fields = dict(re.findall(r"(?m)^([a-z_]+):\s*(.*?)\s*$", source.excerpt))
        quote = f"detail_buyer_phone: {fields.get('detail_buyer_phone', '')}"
        return {("permit_listed_contact", quote)} if fields.get("detail_buyer_phone") else set()
    if source.project_match_reason.casefold() in _NATIVE_IDENTITY_SOURCE_REASONS:
        quote = _exact_native_rrc_contact(source, identity.rrc_operator_number, organization)
        return {("public_contact", quote)} if quote else set()
    return _current_project_native_source(
        session,
        source,
        project,
        retained_context,
        organization=organization,
        person_name=person_name,
    )


def _source_hash_is_current(
    source: BuyingChainEvidence, *, retained_version: str | None = None
) -> bool:
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import document_content_hash

    document = PublicDocument(
        source.url,
        source.title,
        source.excerpt,
        extraction_location=source.extraction_location,
        published_at=source.published_at,
        observed_at=source.observed_at,
        retained_version=retained_version,
    )
    return document_content_hash(document) == source.content_hash


def _exact_native_rrc_contact(
    source: BuyingChainEvidence,
    operator_number: str | None,
    organization: str,
) -> str | None:
    if not operator_number or not re.fullmatch(r"\d{6}", operator_number):
        return None
    if not _source_hash_is_current(source):
        return None
    lines = [line.strip() for line in source.excerpt.splitlines()]
    if (
        source.project_match_reason.casefold()
        == "exact-number public rrc operator registry organization phone."
    ):
        expected_url = (
            "https://webapps2.rrc.texas.gov/EWA/organizationResultsDrillDownAction.do"
            f"?methodToCall=searchByOperatorNo&operatorNo={operator_number}"
        )
        if source.url != expected_url or not any(
            re.fullmatch(r"Organization\s+Operator\s+Query\s+Results", line, re.I) for line in lines
        ):
            return None
        numbers = re.findall(
            r"^Operator\s*(?:Number|No\.?|#):\s*(\d{6})\s*$",
            source.excerpt,
            re.I | re.M,
        )
        names = re.findall(r"^Operator\s*Name:\s*(.+?)\s*$", source.excerpt, re.I | re.M)
        phones = [
            line
            for line in lines
            if re.fullmatch(r"Organization\s+Phone\s+No\.?:\s*[+()0-9 .-]{10,24}", line, re.I)
        ]
        valid = (
            numbers == [operator_number]
            and len(names) == 1
            and _brand_key(names[0]) == _brand_key(organization)
            and len(phones) == 1
            and re.fullmatch(
                r"(?:\+?1[ .-]?)?(?:\(?[2-9]\d{2}\)?[ .-]?){2}\d{4}",
                phones[0].split(":", 1)[1].strip(),
            )
            is not None
        )
        return phones[0] if valid else None

    try:
        url = validate_public_url(source.url)
    except ValueError:
        return None
    fields = dict(re.findall(r"(?m)^([^:\r\n]+):\s*(.*?)\s*$", source.excerpt))
    from gridlens.ingestion.adapters.rrc_operator_directory import is_rrc_directory_workbook_url

    valid = (
        (urlsplit(url).hostname or "").casefold() == "www.rrc.texas.gov"
        and is_rrc_directory_workbook_url(url)
        and source.title == "RRC Oil & Gas P5 directory organization phone"
        and re.fullmatch(r"RRC P5 directory worksheet row [1-9]\d*", source.extraction_location)
        and "Oil & Gas P5 directory row" in source.excerpt
        and fields.get("Org Number") == operator_number
        and fields.get("Org Name") is not None
        and _brand_key(fields["Org Name"]) == _brand_key(organization)
        and fields.get("P5 Status") in {"Active", "ActiveExtension"}
        and fields.get("Phone") is not None
        and re.fullmatch(r"[0-9a-f]{64}", fields.get("Workbook SHA-256", "")) is not None
    )
    return f"Phone: {fields['Phone']}" if valid else None


def _current_project_native_source(
    session: Session,
    source: BuyingChainEvidence,
    project: Project | None,
    retained_context: tuple[Evidence, Observation, Interpretation, Source] | None,
    *,
    organization: str,
    person_name: str | None,
) -> set[tuple[str, str]]:
    if source.retained_evidence_id is None or project is None or retained_context is None:
        return set()
    evidence, observation, interpretation, native_source = retained_context
    from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    if source.excerpt != f"{evidence.title}\n{evidence.abstract or ''}":
        return set()
    document = PublicDocument(
        evidence.url,
        evidence.title,
        source.excerpt,
        evidence.published_at,
        evidence.observed_at,
        evidence.extraction_location,
        retained_version=evidence.content_hash,
    )
    parsed_claims = extract_retained_permit_organizations(
        document, native_source.id, project=project
    )
    supported = {
        (str(citation.get("supports")), str(citation.get("quote")))
        for parsed in parsed_claims
        if _brand_key(parsed.organization) == _brand_key(organization)
        and (not person_name or parsed.person_name == person_name)
        for citation in parsed.citations
        if citation.get("url") == source.url
        and citation.get("supports")
        in {
            "public_contact",
            "organization_person_role",
            "person_project_assignment",
            "permit_listed_contact",
        }
    }
    current = bool(
        source.project_id == project.id
        and source.url == evidence.url
        and _source_hash_is_current(source, retained_version=evidence.content_hash)
        and _retained_evidence_current_for_project(
            session,
            project,
            evidence,
            observation=observation,
            interpretation=interpretation,
            source=native_source,
            preloaded=True,
        )
    )
    if not current:
        return set()
    return supported


def document_matches_company_identity(
    session: Session,
    document: object,
    *,
    company_id: UUID,
    organization: str,
) -> bool:
    """Require independent current evidence binding the domain to the company ID.

    The current schema has no authoritative company-domain assertion. A page's
    own operator number and company footer are self-claims, while imported
    domains are discovery hints. Until a source-backed domain producer exists,
    public company websites cannot satisfy this attribution check.
    """
    del session, document, company_id, organization
    return False


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
    sources = (
        {
            str(source.id): source
            for source in session.scalars(
                select(BuyingChainEvidence).where(BuyingChainEvidence.id.in_(set(parsed_ids)))
            )
        }
        if parsed_ids
        else {}
    )
    identity_ids = {
        UUID(str(candidate["company_identity_id"]))
        for candidate in candidates
        if candidate.get("company_identity_id")
    }
    project_ids = {UUID(str(view["project_id"])) for view in views if view.get("project_id")}
    identities = (
        {
            str(identity.id): identity
            for identity in session.scalars(
                select(CompanyIdentity).where(CompanyIdentity.id.in_(identity_ids))
            )
        }
        if identity_ids
        else {}
    )
    projects = (
        {
            str(project.id): project
            for project in session.scalars(select(Project).where(Project.id.in_(project_ids)))
        }
        if project_ids
        else {}
    )
    retained_ids = {
        source.retained_evidence_id
        for source in sources.values()
        if source.retained_evidence_id is not None
    }
    retained_contexts: dict[UUID, tuple[Evidence, Observation, Interpretation, Source]] = {}
    if retained_ids:
        rows = session.execute(
            select(Evidence, Observation, Interpretation, Source)
            .join(Observation, Observation.id == Evidence.observation_id)
            .join(
                Interpretation,
                (Interpretation.observation_id == Observation.id)
                & (Interpretation.content_hash == Evidence.content_hash),
            )
            .join(Source, Source.id == Observation.source_id)
            .where(Evidence.id.in_(retained_ids))
        ).all()
        retained_contexts = {
            evidence.id: (evidence, observation, interpretation, source)
            for evidence, observation, interpretation, source in rows
        }

    for view in views:
        project_id = str(view.get("project_id") or "")
        project = projects.get(project_id)
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
                facts = supported_contact_facts(
                    session,
                    source,
                    organization=organization,
                    identity=identities.get(str(company_id)),
                    project=project,
                    person_name=(
                        str(candidate.get("person_name")) if candidate.get("person_name") else None
                    ),
                    retained_context=(
                        retained_contexts.get(source.retained_evidence_id)
                        if source.retained_evidence_id
                        else None
                    ),
                )
                if (str(support), str(citation.get("quote") or "")) not in facts:
                    continue
                if source.retained_evidence_id is None and support not in {
                    "public_contact",
                    "permit_listed_contact",
                    "project_organization",
                }:
                    # Native RRC/Houston contact records cannot establish a
                    # person's employment or project assignment.
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
                or (citation.get("supports"), str(citation.get("url") or "")) in source_for_citation
            ]
            if candidate.get("person_name") and not verified_role_urls:
                continue
            kept.append(candidate)
        view["candidates"] = kept
