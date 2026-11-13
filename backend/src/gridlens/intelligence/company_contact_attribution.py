"""Conservative attribution checks for website-derived company contact claims.

Public company pages qualify only when a fresh SEC filing independently binds
the canonical company identity to the page's exact domain. Native RRC and
retained project-source facts keep their existing provenance checks.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from gridlens.intelligence.regulatory_company_identity import CompanyDomainProofContext

_NATIVE_IDENTITY_SOURCE_REASONS = {
    "exact-number public rrc operator registry organization phone.",
    "exact rrc operator-number p5 row; normal organization phone field.",
}
_PROJECT_SCOPED_NATIVE_SOURCE_REASONS = {
    "exact houston sold permit project, permit type, date and site match the selected project."
}
_CONTACT_BEARING_SUPPORTS = frozenset(
    {
        "public_contact",
        "permit_listed_contact",
        "organization_person_role",
        "person_project_assignment",
    }
)


@dataclass(frozen=True)
class NativeContactFact:
    company_id: str
    source_url: str
    source_hash: str
    support: str
    quote: str
    person_name: str | None
    title: str | None
    category: str | None
    organization_relationship: str | None
    person_organization_relationship: str | None
    person_project_relationship: str | None
    method_kind: str | None = None
    method_value: str | None = None


def _normalized_method(kind: object, value: object) -> tuple[str, str] | None:
    method_kind = str(kind or "").strip().casefold()
    literal = str(value or "").strip()
    if method_kind in {"phone", "telephone", "call"} or "phone" in method_kind:
        if not re.fullmatch(r"\+?[0-9(). -]{7,30}", literal):
            return None
        digits = re.sub(r"\D", "", literal)
        if not 7 <= len(digits) <= 15:
            return None
        return "phone", digits
    if method_kind == "email" and re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", literal
    ):
        return "email", literal.casefold()
    return None


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
        url = validate_public_url(str(getattr(document, "url", "")))
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
        parsed_url.scheme != "https"
        or parsed_url.netloc != "cohtora.houstontx.gov"
        or parsed_url.path != "/ibi_apps/WFServlet.ibfs"
    ):
        return False
    if project is None or project.source_id != "houston-weekly-permits":
        return False
    parts = project.external_id.split(":")
    if len(parts) != 3 or not parts[0].isdigit():
        return False
    from urllib.parse import parse_qs

    try:
        query = parse_qs(parsed_url.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    from gridlens.ingestion.adapters.houston_permit_details import (
        SUPPORTED_TYPES,
        response_type_code,
    )

    expected_type_code = SUPPORTED_TYPES.get(parts[1])
    expected_query = {
        "IBIF_webapp": ["/ibi_apps"],
        "IBIC_server": ["EDASERVE"],
        "IBIWF_msgviewer": ["OFF"],
        "IBIAPP_app": ["soldpermits"],
        "IBIF_ex": ["sold_permit_d"],
        "CLICKED_ON": [""],
        "PN": [parts[0]],
        "PT": [expected_type_code],
    }
    if expected_type_code is None or query != expected_query:
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
    candidate: dict,
    domain_proof_context: CompanyDomainProofContext | None = None,
) -> set[NativeContactFact]:
    """Return exact native-parser method and role facts for a canonical company."""
    if identity is None:
        return set()

    def fact(
        support: str,
        quote: str,
        *,
        parsed: object | None = None,
        method: tuple[str, str] | None = None,
    ) -> NativeContactFact:
        return NativeContactFact(
            company_id=str(identity.id),
            source_url=source.url,
            source_hash=source.content_hash,
            support=support,
            quote=quote,
            person_name=getattr(parsed, "person_name", None),
            title=getattr(parsed, "title", None),
            category=getattr(parsed, "category", None),
            organization_relationship=getattr(parsed, "organization_relationship", None),
            person_organization_relationship=getattr(
                parsed, "person_organization_relationship", None
            ),
            person_project_relationship=getattr(parsed, "person_project_relationship", None),
            method_kind=method[0] if method else None,
            method_value=method[1] if method else None,
        )

    if source.project_match_reason.casefold() in _PROJECT_SCOPED_NATIVE_SOURCE_REASONS:
        if not _exact_houston_project_contact(source, project, organization=organization):
            return set()
        fields = dict(re.findall(r"(?m)^([a-z_]+):\s*(.*?)\s*$", source.excerpt))
        quote = f"detail_buyer_phone: {fields.get('detail_buyer_phone', '')}"
        normalized_method = _normalized_method("phone", fields.get("detail_buyer_phone"))
        return (
            {fact("permit_listed_contact", quote, method=normalized_method)}
            if fields.get("detail_buyer_phone") and normalized_method
            else set()
        )
    if source.project_match_reason.casefold() in _NATIVE_IDENTITY_SOURCE_REASONS:
        native_method = _exact_native_rrc_contact(
            source, identity.rrc_operator_number, organization
        )
        normalized_method = (
            _normalized_method(native_method[0], native_method[1]) if native_method else None
        )
        return (
            {
                fact(
                    "public_contact",
                    native_method[2],
                    method=normalized_method,
                )
            }
            if native_method and normalized_method
            else set()
        )
    if source.retained_evidence_id is None and project is not None:
        now = datetime.now(UTC)
        from gridlens.domain.evaluation_clock import evaluation_now

        now = evaluation_now(now)
        observed_at = (
            source.observed_at.replace(tzinfo=UTC)
            if source.observed_at.tzinfo is None
            else source.observed_at.astimezone(UTC)
        )
        last_seen_at = (
            source.last_seen_at.replace(tzinfo=UTC)
            if source.last_seen_at.tzinfo is None
            else source.last_seen_at.astimezone(UTC)
        )
        if (
            not _source_hash_is_current(source)
            or observed_at > last_seen_at
            or last_seen_at > now
            or now - last_seen_at > timedelta(days=30)
        ):
            return set()
        try:
            from gridlens.intelligence.regulatory_company_identity import (
                verified_company_domain_matches,
            )

            if not verified_company_domain_matches(
                session,
                document=source,
                company_id=identity.id,
                organization=organization,
                now=now,
                context=domain_proof_context,
            ):
                return set()
        except (LookupError, TypeError, ValueError):
            return set()

        from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
        from gridlens.intelligence.buying_chain_extraction import (
            Extracted,
            extract_company_contacts,
            extract_people,
        )

        doc = PublicDocument(
            source.url,
            source.title,
            source.excerpt,
            source.published_at,
            source.last_seen_at,
            extraction_location=source.extraction_location,
        )
        seed = Extracted(
            organization=organization,
            category=str(candidate.get("category") or "owner"),
            organization_relationship=str(candidate.get("organization_relationship") or "DIRECT"),
            person_organization_relationship="UNKNOWN",
            person_project_relationship="UNKNOWN",
        )
        verified: set[NativeContactFact] = set()
        for parsed in extract_people(
            doc,
            [seed],
            project,
            project_scoped=False,
            today=now.date(),
            verified_official_roster=True,
        ):
            for citation in parsed.citations:
                citation_quote = citation.get("quote")
                if (
                    citation.get("supports") == "organization_person_role"
                    and citation.get("url") == source.url
                    and isinstance(citation_quote, str)
                    and citation_quote in source.excerpt
                ):
                    verified.add(
                        fact(
                            "organization_person_role",
                            citation_quote,
                            parsed=parsed,
                        )
                    )
        for parsed in extract_company_contacts(doc, [seed]):
            for citation in parsed.citations:
                citation_quote = citation.get("quote")
                if (
                    citation.get("supports") == "public_contact"
                    and citation.get("url") == source.url
                    and isinstance(citation_quote, str)
                    and citation_quote in source.excerpt
                ):
                    for method in parsed.public_contacts:
                        if method.get("quote") != citation_quote:
                            continue
                        normalized = _normalized_method(method.get("kind"), method.get("value"))
                        if normalized:
                            verified.add(
                                fact(
                                    "public_contact",
                                    citation_quote,
                                    parsed=parsed,
                                    method=normalized,
                                )
                            )
        return verified
    return _current_project_native_source(
        session,
        source,
        project,
        retained_context,
        identity=identity,
        organization=organization,
        candidate=candidate,
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
) -> tuple[str, str, str] | None:
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
        if not valid:
            return None
        quote = phones[0]
        value = quote.split(":", 1)[1].strip()
        return ("phone", value, quote)

    try:
        url = validate_public_url(source.url)
    except ValueError:
        return None
    fields = dict(re.findall(r"(?m)^([^:\r\n]+):\s*(.*?)\s*$", source.excerpt))
    from gridlens.ingestion.adapters.rrc_operator_directory import is_rrc_directory_workbook_url

    valid_p5 = (
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
    return ("phone", fields["Phone"], f"Phone: {fields['Phone']}") if valid_p5 else None


def _current_project_native_source(
    session: Session,
    source: BuyingChainEvidence,
    project: Project | None,
    retained_context: tuple[Evidence, Observation, Interpretation, Source] | None,
    *,
    identity: CompanyIdentity,
    organization: str,
    candidate: dict,
) -> set[NativeContactFact]:
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
    supported: set[NativeContactFact] = set()
    for parsed in parsed_claims:
        if (
            _brand_key(parsed.organization) != _brand_key(organization)
            or parsed.person_name != candidate.get("person_name")
            or parsed.title != candidate.get("title")
            or parsed.category != candidate.get("category")
            or parsed.organization_relationship != candidate.get("organization_relationship")
            or parsed.person_organization_relationship
            != candidate.get("person_organization_relationship")
            or parsed.person_project_relationship != candidate.get("person_project_relationship")
        ):
            continue
        for citation in parsed.citations:
            support = str(citation.get("supports"))
            quote = str(citation.get("quote") or "")
            if citation.get("url") != source.url or support not in {
                "public_contact",
                "organization_person_role",
                "person_project_assignment",
                "permit_listed_contact",
            }:
                continue
            if support != "public_contact":
                supported.add(
                    NativeContactFact(
                        company_id=str(identity.id),
                        source_url=source.url,
                        source_hash=source.content_hash,
                        support=support,
                        quote=quote,
                        person_name=parsed.person_name,
                        title=parsed.title,
                        category=parsed.category,
                        organization_relationship=parsed.organization_relationship,
                        person_organization_relationship=parsed.person_organization_relationship,
                        person_project_relationship=parsed.person_project_relationship,
                    )
                )
                continue
            for method_row in parsed.public_contacts:
                method = _normalized_method(method_row.get("kind"), method_row.get("value"))
                if (
                    method
                    and method_row.get("source_url") == source.url
                    and method_row.get("quote") == quote
                ):
                    supported.add(
                        NativeContactFact(
                            company_id=str(identity.id),
                            source_url=source.url,
                            source_hash=source.content_hash,
                            support=support,
                            quote=quote,
                            person_name=parsed.person_name,
                            title=parsed.title,
                            category=parsed.category,
                            organization_relationship=parsed.organization_relationship,
                            person_organization_relationship=parsed.person_organization_relationship,
                            person_project_relationship=parsed.person_project_relationship,
                            method_kind=method[0],
                            method_value=method[1],
                        )
                    )
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
    now: datetime | None = None,
) -> bool:
    """Require current SEC EIN/domain proof before a company's page is trusted."""
    from gridlens.intelligence.regulatory_company_identity import (
        verified_company_domain_matches,
    )

    return verified_company_domain_matches(
        session,
        document=document,
        company_id=company_id,
        organization=organization,
        now=now,
    )


def _fact_matches_candidate(fact: NativeContactFact, candidate: dict, company_id: str) -> bool:
    return (
        fact.company_id == company_id
        and fact.person_name == candidate.get("person_name")
        and (fact.title is None or fact.title == candidate.get("title"))
        and (fact.category is None or fact.category == candidate.get("category"))
        and (
            fact.organization_relationship is None
            or fact.organization_relationship == candidate.get("organization_relationship")
        )
        and (
            fact.person_organization_relationship is None
            or fact.person_organization_relationship
            == candidate.get("person_organization_relationship")
        )
        and (
            fact.person_project_relationship is None
            or fact.person_project_relationship == candidate.get("person_project_relationship")
        )
    )


def _fact_matches_method(
    fact: NativeContactFact, method_record: dict, candidate: dict, company_id: str
) -> bool:
    normalized = _normalized_method(method_record.get("kind"), method_record.get("value"))
    return bool(
        normalized
        and fact.support in {"public_contact", "permit_listed_contact"}
        and fact.source_url == str(method_record.get("source_url") or "")
        and fact.quote == str(method_record.get("quote") or "")
        and fact.method_kind == normalized[0]
        and fact.method_value == normalized[1]
        and _fact_matches_candidate(fact, candidate, company_id)
    )


def _citation_key(citation: dict) -> tuple[str, str, str]:
    return (
        str(citation.get("supports") or ""),
        str(citation.get("url") or ""),
        str(citation.get("quote") or ""),
    )


def _citation_locator(citation: dict) -> tuple[str, str]:
    return (
        str(citation.get("current_source_version_id") or citation.get("id") or ""),
        str(citation.get("url") or ""),
    )


def _contact_values(contacts: object) -> set[str]:
    if not isinstance(contacts, list):
        return set()
    return {
        value.strip()
        for contact in contacts
        if isinstance(contact, dict)
        and isinstance((value := contact.get("value")), str)
        and value.strip()
    }


def _safe_projection_text(value: object, hidden_terms: set[str]) -> object:
    """Redact rejected actor/contact text from the public view only."""
    from gridlens.intelligence.saved_history_privacy import (
        _redact,
        _redact_all_contact_tokens,
    )

    return _redact_all_contact_tokens(_redact(value, hidden_terms, set(), set()))


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
        if not candidate.get("company_identity_id"):
            continue
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
    from gridlens.intelligence.regulatory_company_identity import (
        CompanyDomainProofContext,
        load_company_domain_proof_context,
    )

    needs_domain_proof = any(
        citation.get("supports")
        in {"public_contact", "organization_person_role", "person_project_assignment"}
        and (
            source := sources.get(
                str(citation.get("current_source_version_id") or citation.get("id") or "")
            )
        )
        is not None
        and source.retained_evidence_id is None
        and source.project_match_reason.casefold() not in _NATIVE_IDENTITY_SOURCE_REASONS
        and source.project_match_reason.casefold() not in _PROJECT_SCOPED_NATIVE_SOURCE_REASONS
        for candidate in candidates
        for citation in candidate.get("evidence", [])
    )
    domain_context = (
        load_company_domain_proof_context(session, identity_ids)
        if needs_domain_proof
        else CompanyDomainProofContext()
    )
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
                & (Interpretation.content_hash == Observation.content_hash),
            )
            .join(Source, Source.id == Observation.source_id)
            .where(Evidence.id.in_(retained_ids))
        ).all()
        retained_contexts = {}
        for evidence, observation, interpretation, source in rows:
            assessment = interpretation.assessment or {}
            if (
                interpretation.content_hash != observation.content_hash
                or assessment.get("semantic_hash") != observation.content_hash
                or assessment.get("evidence_hash") != evidence.content_hash
            ):
                continue
            retained_contexts[evidence.id] = (evidence, observation, interpretation, source)

    for view in views:
        project_id = str(view.get("project_id") or "")
        project = projects.get(project_id)
        blocked_terms_by_company: dict[str, set[str]] = defaultdict(set)
        blocked_terms_by_source: dict[tuple[str, str], set[str]] = defaultdict(set)
        local_terms_by_candidate: dict[int, set[str]] = defaultdict(set)
        allowed_citations_by_candidate: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
        existing_project_organizations = {
            _brand_key(str(candidate.get("organization") or ""))
            for candidate in view.get("candidates", [])
            if not candidate.get("person_name")
            and any(
                citation.get("supports") == "project_organization"
                and citation.get("current_support")
                for citation in candidate.get("evidence", [])
            )
        }
        kept = []
        for candidate in view.get("candidates", []):
            company_id = candidate.get("company_identity_id")
            if not company_id:
                original_contacts = list(candidate.get("public_contacts") or [])
                if candidate.get("person_name"):
                    rejected_terms = {
                        str(candidate[key]).strip()
                        for key in ("person_name", "title")
                        if isinstance(candidate.get(key), str) and candidate[key].strip()
                    }
                    rejected_terms.update(_contact_values(original_contacts))
                    local_terms_by_candidate[id(candidate)].update(rejected_terms)
                    for citation in candidate.get("evidence", []):
                        blocked_terms_by_source[_citation_locator(citation)].update(rejected_terms)
                    organization_evidence = [
                        citation
                        for citation in candidate.get("evidence", [])
                        if citation.get("supports") == "project_organization"
                        and citation.get("current_support")
                    ]
                    if not organization_evidence:
                        continue
                    if _brand_key(str(candidate.get("organization") or "")) in (
                        existing_project_organizations
                    ):
                        continue
                    # Preserve the supported project-organization facet, but
                    # do not publish an unbound person, title, role or method.
                    candidate["person_name"] = None
                    candidate["person_identity_id"] = None
                    candidate["title"] = None
                    candidate["person_organization_relationship"] = "UNKNOWN"
                    candidate["person_project_relationship"] = "UNKNOWN"
                    candidate["public_contacts"] = []
                    candidate["reason"] = (
                        "Project organization relationship is source-supported; "
                        "named-person attribution is unavailable."
                    )
                    candidate["evidence"] = organization_evidence
                    existing_project_organizations.add(
                        _brand_key(str(candidate.get("organization") or ""))
                    )
                    kept.append(candidate)
                    continue
                candidate["public_contacts"] = []
                local_terms_by_candidate[id(candidate)].update(_contact_values(original_contacts))
                candidate["evidence"] = [
                    citation
                    for citation in candidate.get("evidence", [])
                    if citation.get("supports")
                    not in {
                        "public_contact",
                        "permit_listed_contact",
                        "organization_person_role",
                        "person_project_assignment",
                    }
                ]
                candidate["person_identity_id"] = None
                candidate["title"] = None
                candidate["person_organization_relationship"] = "UNKNOWN"
                candidate["person_project_relationship"] = "UNKNOWN"
                kept.append(candidate)
                continue
            organization = str(candidate.get("organization") or "")
            original_contacts = list(candidate.get("public_contacts") or [])
            original_citations = list(candidate.get("evidence") or [])
            source_for_citation: dict[tuple[str, str, str], set[NativeContactFact]] = {}
            verified_role_facts: set[NativeContactFact] = set()
            verified_method_facts: set[NativeContactFact] = set()
            for citation in candidate.get("evidence", []):
                support = citation.get("supports")
                if support not in {
                    "public_contact",
                    "permit_listed_contact",
                    "organization_person_role",
                    "person_project_assignment",
                }:
                    continue
                source = sources.get(str(citation.get("current_source_version_id"))) or sources.get(
                    str(citation.get("id"))
                )
                if source is None:
                    continue
                source_version_id = str(
                    citation.get("current_source_version_id") or citation.get("id") or ""
                )
                if str(source.id) != source_version_id:
                    continue
                facts = supported_contact_facts(
                    session,
                    source,
                    organization=organization,
                    identity=identities.get(str(company_id)),
                    project=project,
                    candidate=candidate,
                    retained_context=(
                        retained_contexts.get(source.retained_evidence_id)
                        if source.retained_evidence_id
                        else None
                    ),
                    domain_proof_context=domain_context,
                )
                quote = str(citation.get("quote") or "")
                matched_facts = {
                    fact
                    for fact in facts
                    if fact.support == str(support)
                    and fact.quote == quote
                    and fact.source_url == str(citation.get("url") or "")
                    and _fact_matches_candidate(fact, candidate, str(company_id))
                }
                if not matched_facts:
                    continue
                if source.retained_evidence_id is None and support not in {
                    "public_contact",
                    "permit_listed_contact",
                    "project_organization",
                    "organization_person_role",
                }:
                    # Non-retained project-role claims are allowed only when
                    # supported_contact_facts re-extracted them from a fresh,
                    # independently SEC-bound official company domain. Keep
                    # the native permit-listed method path intact.
                    continue
                url = str(citation.get("url") or "")
                source_for_citation[(str(support), url, quote)] = matched_facts
                if support in {"public_contact", "permit_listed_contact"}:
                    verified_method_facts.update(matched_facts)
                else:
                    verified_role_facts.update(matched_facts)

            allowed_contacts = [
                contact
                for contact in original_contacts
                if any(
                    _fact_matches_method(fact, contact, candidate, str(company_id))
                    for fact in verified_method_facts
                )
            ]
            candidate["public_contacts"] = allowed_contacts
            rejected_method_values = _contact_values(
                [contact for contact in original_contacts if contact not in allowed_contacts]
            )
            blocked_terms_by_company[str(company_id)].update(rejected_method_values)
            local_terms_by_candidate[id(candidate)].update(rejected_method_values)
            allowed_citations_by_candidate[id(candidate)].update(source_for_citation)
            candidate["evidence"] = [
                citation
                for citation in candidate.get("evidence", [])
                if citation.get("supports") not in _CONTACT_BEARING_SUPPORTS
                or _citation_key(citation) in source_for_citation
            ]
            if candidate.get("person_name") and not verified_role_facts:
                rejected_terms = {
                    str(candidate[key]).strip()
                    for key in ("person_name", "title")
                    if isinstance(candidate.get(key), str) and candidate[key].strip()
                }
                blocked_terms_by_company[str(company_id)].update(rejected_terms)
                local_terms_by_candidate[id(candidate)].update(rejected_terms)
                for citation in original_citations:
                    blocked_terms_by_source[_citation_locator(citation)].update(rejected_terms)
                continue
            if candidate.get("title") and not any(
                fact.title == candidate.get("title") for fact in verified_role_facts
            ):
                rejected_title = str(candidate["title"]).strip()
                if rejected_title:
                    blocked_terms_by_company[str(company_id)].add(rejected_title)
                    local_terms_by_candidate[id(candidate)].add(rejected_title)
                candidate["title"] = None
            kept.append(candidate)
        for candidate in kept:
            company_terms = blocked_terms_by_company.get(
                str(candidate.get("company_identity_id") or ""), set()
            )
            local_terms = local_terms_by_candidate.get(id(candidate), set())
            candidate_terms = company_terms | local_terms
            if isinstance(candidate.get("reason"), str):
                candidate["reason"] = _safe_projection_text(candidate["reason"], candidate_terms)
            candidate["evidence"] = [
                citation
                if _citation_key(citation)
                in allowed_citations_by_candidate.get(id(candidate), set())
                else _safe_projection_text(
                    citation,
                    candidate_terms
                    | blocked_terms_by_source.get(_citation_locator(citation), set()),
                )
                for citation in candidate.get("evidence", [])
            ]
        view["candidates"] = kept
