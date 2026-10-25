"""Conservative explicit relation extraction; unrecognized prose stays unresolved.

A scoped project document proves organization involvement. A separate current
organization profile can support a relevant role, never a project assignment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

from gridlens.domain.buying_chain import (
    Category,
    current_role,
    person_project_relationship,
)
from gridlens.domain.pursuit_research import fingerprint
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_permits import (
    GEORGIA,
    chicago_contacts,
    fort_worth_owner,
    georgia_identity,
    georgia_named_owner,
    georgia_proponent,
)
from gridlens.ingestion.adapters.retained_permits import (
    fields as permit_fields,
)
from gridlens.intelligence.project_identity import (
    conflicting_geography,
    decide_project_match,
    normalized_identity,
    same_physical_site,
)
from gridlens.persistence.models import Project

_ROLE_WORDS = {
    "electrical contractor": Category.ELECTRICAL,
    "general contractor": Category.GC,
    "epc contractor": Category.EPC,
    "engineering, procurement and construction contractor": Category.EPC,
    "commissioning contractor": Category.COMMISSIONING,
    "commissioning firm": Category.COMMISSIONING,
    "owner": Category.OWNER,
    "developer": Category.OWNER,
    "operator": Category.OPERATOR,
    "construction manager": Category.GC,
}
_ROLE_PATTERN = "|".join(re.escape(value) for value in _ROLE_WORDS)
_NAME = r"[A-Z][A-Za-zÀ-ž'’.-]+(?:[ \t]+[A-Z][A-Za-zÀ-ž'’.-]+){1,3}"
_ORG = r"[A-Z][A-Za-z0-9&'’.,/-]*(?:\s+[A-Za-z0-9&'’.,/-]+){0,9}?"
_AMBIGUOUS = re.compile(
    r"\b(?:may|might|could|rumou?red|possible|proposed|former|previous|retired|left|"
    r"removed|withdrawn|terminated|replaced|no longer|not|never)\b",
    re.I,
)
_RENTAL = re.compile(r"\b(?:rental|equipment hire)\b", re.I)
_TDLR_SOURCE = "texas-tdlr-tabs-data-centers"
_TDLR_NUMBER = re.compile(r"^TABS-(TABS\d{10})$")


@dataclass
class Extracted:
    organization: str
    category: str
    person_name: str | None = None
    title: str | None = None
    organization_relationship: str = "DIRECT"
    person_organization_relationship: str = "UNKNOWN"
    person_project_relationship: str = "UNKNOWN"
    evidence_strength: str = "High"
    reason: str = "Organization involvement is explicitly reported for the selected project."
    citations: list[dict] = field(default_factory=list)
    public_contacts: list[dict] = field(default_factory=list)


def organization_key(value: str) -> str:
    clean = normalized_identity(value)
    # Only legal-name suffix spelling equivalences; never fuzzy company matching.
    return re.sub(r"(?:\s+(?:company|co|incorporated|inc|llc|ltd|limited))+$", "", clean).strip()


def _employer_pattern(organization: str) -> str:
    """Anchor the company name, allowing only the existing legal-suffix equivalences."""
    suffix = r"(?:company|co|incorporated|inc|llc|ltd|limited)"
    core = re.sub(rf"(?:[ \t,.]+{suffix}\.?)+$", "", organization.strip(), flags=re.I)
    return re.escape(core) + rf"(?:[ \t,]+{suffix}\.?)*"


def document_content_hash(doc: PublicDocument) -> str:
    """Canonical retained version identity, including role-freshness metadata."""
    content = {"text": doc.text, "title": doc.title, "published": doc.published_at}
    if doc.retained_version is not None:
        # Identical excerpt text can belong to a different accepted observation
        # version (e.g. changed PDF hash or extraction metadata). Keep its binding.
        content["retained_version"] = doc.retained_version
    return fingerprint(content)


def document_key(doc: PublicDocument) -> str:
    return doc.url + ":" + document_content_hash(doc)


def _project_name_pattern(project: Project) -> str:
    names = sorted(
        (name for name in _project_names(project) if len(normalized_identity(name).split()) >= 2),
        key=len,
        reverse=True,
    )
    # A word boundary alone accepts sibling names such as "Orion Data Center West".
    # Only a complete name followed by punctuation or supported prose is recognized.
    return (
        r"(?<![\w-])(?:" + "|".join(re.escape(name) for name in names) + r")(?![\w-])"
        r"(?=$|[.,;:!?]|\s+(?:in|at|on|is|was|will|has|had|but|and|for|with)\b)"
        if names
        else r"(?!)"
    )


def _local_geography(suffix: str, project: Project) -> tuple[bool, bool, bool]:
    """Match only a location immediately attached to this exact project reference.

    Unsupported explicit locations remain unresolved rather than borrowing a city
    from a headquarters statement, another clause, or the document title.
    """
    locator = re.match(r"\s*(?:(?:in|at)\s+|,(?!\s*(?:but|and|on|for|with)\b)\s*)", suffix, re.I)
    if not locator:
        return False, False, False
    location = re.split(
        r"[;.!?\n]|,?\s+(?:but|and|while|where|which)\b",
        suffix[locator.end() :],
        maxsplit=1,
        flags=re.I,
    )[0].strip(" ,")
    selected = [(project.identity_facts or {}).get("site"), project.location]
    if conflicting_geography(project.location, location):
        return False, True, False
    same_site = any(site and same_physical_site(site, location) for site in selected)
    matched = any(
        site
        and (
            same_physical_site(site, location)
            or re.match(
                re.escape(normalized_identity(site)) + r"(?:$|\s)", normalized_identity(location)
            )
        )
        for site in selected
    )
    return matched, not matched, same_site


def _explicit_project_target(suffix: str, project: Project) -> bool:
    prefix = re.match(r"\s*,?\s*(?:for|on|at)\s+(?:the\s+)?", suffix, re.I)
    if not prefix:
        return False
    target = re.match(_project_name_pattern(project), suffix[prefix.end() :], re.I)
    return bool(target and not _local_geography(suffix[prefix.end() + target.end() :], project)[1])


def _citation(doc: PublicDocument, quote: str, supports: str) -> dict:
    if quote not in doc.text:
        raise ValueError("Citation is not an exact retained source excerpt")
    return {"url": doc.url, "quote": quote, "supports": supports, "document_key": document_key(doc)}


def _sentences(text: str) -> list[str]:
    # Preserve exact quote bytes rather than reconstructing claims from fragments.
    return [part.strip() for part in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])", text) if part.strip()]


def _project_names(project: Project) -> list[str]:
    facts = project.identity_facts or {}
    return list(dict.fromkeys([project.name, *facts.get("project_aliases", [])]))


def project_document_match(project: Project, doc: PublicDocument) -> tuple[bool, str]:
    """No company-only match. Reuse GL3-016 site/name or stable identity gates."""
    if doc.structured:
        origin = urlsplit(doc.url)
        if (
            project.source_id == "chicago-building-permits"
            and origin.scheme == "https"
            and origin.hostname == "data.cityofchicago.org"
            and origin.path == "/resource/ydr8-5enu.json"
        ):
            matching = [row for row in doc.structured if str(row.get("id")) == project.external_id]
            if len(matching) != 1 or len(doc.structured) != 1:
                return False, "Official record does not identify exactly the selected permit."
            row = matching[0]
            site = " ".join(
                str(row.get(key, ""))
                for key in (
                    "street_number",
                    "street_direction",
                    "street_name",
                )
            ).strip()
            selected_site = (project.identity_facts or {}).get("site") or project.location
            # Exact existing source identity is authoritative, but explicit site conflict blocks it.
            conflict = bool(
                site
                and selected_site
                and not re.search(
                    r"(?<!\w)" + re.escape(normalized_identity(site)) + r"(?!\w)",
                    normalized_identity(selected_site),
                )
            )
            decision = decide_project_match(same_source_id=True, conflicting_geography=conflict)
            return decision.decision == "matched", decision.reason
        return False, "Structured source identity is unsupported for this selected project."
    names = [
        name for name in _project_names(project) if len(normalized_identity(name).split()) >= 2
    ]
    # A city is not a physical site. Full distinctive project name + explicit city/state
    # is a source relationship, but generic company-name-only pages are insufficient.
    facility_name = any(
        re.search(
            r"\b(?:project|campus|plant|terminal|well|mine|facility|"
            r"data center|permit)\b",
            name,
            re.I,
        )
        for name in names
    )
    references = [
        _local_geography(sentence[match.end() :], project)
        for sentence in _sentences(doc.title + "\n" + doc.text)
        for match in re.finditer(_project_name_pattern(project), sentence, re.I)
    ]
    decision = decide_project_match(
        same_project_name=bool(references),
        same_address=any(same_site for _, _, same_site in references),
        explicit_relationship=facility_name and any(matched for matched, _, _ in references),
        conflicting_geography=any(conflict for _, conflict, _ in references),
    )
    return decision.decision == "matched", decision.reason


CHICAGO_CATEGORIES = {
    "CONTRACTOR-ELECTRICAL": Category.ELECTRICAL,
    "CONTRACTOR-GENERAL CONTRACTOR": Category.GC,
    "OWNER": Category.OWNER,
    "OWNER OCCUPIED": Category.OWNER,
    "OWNER AS ARCHITECT": Category.OWNER,
}


def _extract_tdlr_retained_owner(doc: PublicDocument, project: Project) -> list[Extracted]:
    """Resolve only the literal Owner field on the selected official TABS project page."""
    project_number = _TDLR_NUMBER.fullmatch(project.external_id or "")
    try:
        parts = urlsplit(doc.url)
        port = parts.port
    except ValueError:
        return []
    if (
        project.source_id != _TDLR_SOURCE
        or not project_number
        or parts.scheme != "https"
        or parts.hostname != "www.tdlr.texas.gov"
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.path != f"/TABS/Search/Project/{project_number.group(1)}"
        or parts.query
        or parts.fragment
    ):
        return []

    def field_values(label: str) -> list[str]:
        return re.findall(rf"^{re.escape(label)}:[ \t]*(.*?)[ \t]*$", doc.text, re.M)

    project_fields = field_values("Project")
    location_fields = field_values("Location")
    owner_lines = re.findall(r"^Owner:[ \t]*[^\r\n]*$", doc.text, re.M)
    if len(project_fields) != 1 or len(location_fields) != 1 or len(owner_lines) != 1:
        return []

    source_project = project_fields[0]
    selected_names = _project_names(project)
    project_name_matches = any(
        re.fullmatch(re.escape(name) + r"(?:\s+\([^\r\n]*\))?", source_project, re.I)
        for name in selected_names
        if name
    )
    source_location = location_fields[0]
    if not project_name_matches or normalized_identity(source_location) in {
        "",
        "not stated",
        "unknown",
    }:
        return []
    selected_sites = [(project.identity_facts or {}).get("site"), project.location]
    if not any(
        normalized_identity(source_location) == normalized_identity(site)
        or same_physical_site(source_location, site)
        for site in selected_sites
        if site
    ):
        return []

    owner_line = owner_lines[0]
    organization = owner_line.removeprefix("Owner:").strip()
    owner_key = normalized_identity(organization)
    if (
        not organization
        or len(organization) > 200
        or owner_key in {"not stated", "unknown", "none", "n a", "na", "not available"}
        or not re.search(r"[A-Za-z]", organization)
        or _RENTAL.search(organization)
    ):
        return []

    return [
        Extracted(
            organization,
            Category.OWNER.value,
            organization_relationship="DIRECT",
            reason=(
                "TDLR lists this organization as owner of the registered project; this does not "
                "establish purchasing authority, current operational status, a supply gap, or "
                "temporary-power demand."
            ),
            citations=[_citation(doc, owner_line, "project_organization")],
        )
    ]


def extract_retained_permit_organizations(
    doc: PublicDocument, source_id: str, *, project: Project | None = None
) -> list[Extracted]:
    from gridlens.ingestion.adapters.retained_document import retained_organization_claims

    f17 = retained_organization_claims(
        source_id,
        url=doc.url,
        text=doc.text,
        retained_version=doc.retained_version,
        extraction_location=doc.extraction_location,
        structured=doc.structured,
    )
    if f17 is not None:
        return [
            Extracted(
                claim.organization,
                {
                    "owner": Category.OWNER.value,
                    "unknown": Category.UNKNOWN.value,
                    "operator": Category.OPERATOR.value,
                }[claim.role],
                organization_relationship=claim.relationship,
                evidence_strength=claim.evidence_strength,
                reason=claim.reason,
                citations=[_citation(doc, quote, supports) for quote, supports in claim.quotes],
            )
            for claim in f17
        ]
    if source_id == _TDLR_SOURCE:
        return _extract_tdlr_retained_owner(doc, project) if project is not None else []
    if source_id == "ma-ccc-cultivation-applications":
        applicant = permit_fields(source_id, doc.text).get("applicant_org")
        if not applicant or _RENTAL.search(applicant[0]):
            return []

        return [
            Extracted(
                applicant[0],
                Category.UNKNOWN.value,
                organization_relationship="DIRECT",
                reason=(
                    "Organization is explicitly listed as applicant on the CCC cultivation "
                    "application; applicant role does not establish owner/operator status, "
                    "current construction, buyer identity, or buying authority."
                ),
                citations=[_citation(doc, applicant[1], "project_organization")],
            )
        ]
    if source_id == "texas-rrc-drilling-permits":
        operator = permit_fields(source_id, doc.text).get("operator")
        return (
            [
                Extracted(
                    operator[0],
                    Category.OPERATOR.value,
                    organization_relationship="DIRECT",
                    reason=(
                        "Operator named on the W-1 well permit; "
                        "current buying authority, people and contacts are UNKNOWN."
                    ),
                    citations=[_citation(doc, operator[1], "project_organization")],
                )
            ]
            if operator
            else []
        )
    if source_id == "austin-building-permits":
        parsed = permit_fields(source_id, doc.text)
        result = []
        for prefix, organization_field, person_field in (
            ("contractor", "contractor_company_name", "contractor_full_name"),
            ("applicant", "applicant_org", "applicant_full_name"),
        ):
            organization = parsed.get(organization_field)
            if not organization or _RENTAL.search(organization[0]):
                continue
            if prefix == "applicant" and organization_key(organization[0]) == organization_key(
                parsed.get("contractor_company_name", ("", ""))[0]
            ):
                # Exact contractor relationship exists; applicant facts remain.
                continue
            trade = parsed.get("contractor_trade") if prefix == "contractor" else None
            relationship = "DIRECT" if prefix == "contractor" else "UNKNOWN"
            category = {
                "Electrical Contractor": Category.ELECTRICAL.value,
                "General Contractor": Category.GC.value,
            }.get(trade[0] if trade else "", Category.UNKNOWN.value)
            citations = [_citation(doc, organization[1], "project_organization")]
            if trade:
                citations.append(_citation(doc, trade[1], "organization_category"))
            phone = parsed.get(prefix + "_phone")
            contacts = []
            if phone and re.fullmatch(r"[+()0-9 .-]{10,24}", phone[0]):
                citations.append(_citation(doc, phone[1], "permit_listed_contact"))
                contacts.append(
                    {
                        "kind": "permit-listed phone",
                        "value": phone[0],
                        "source_url": doc.url,
                        "quote": phone[1],
                        "observed_at": doc.observed_at.isoformat(),
                    }
                )
            reason = (
                (
                    "Permit-listed contractor"
                    if prefix == "contractor"
                    else "Applicant-associated organization; project role is UNKNOWN"
                )
                + "; current employment, project assignment "
                "and buying authority are UNKNOWN. Phone is a public permit field; "
                "phone ownership and business/personal type are UNKNOWN."
            )
            result.append(
                Extracted(
                    organization[0],
                    category,
                    organization_relationship=relationship,
                    reason=reason,
                    citations=citations,
                    public_contacts=contacts,
                )
            )
            person = parsed.get(person_field)
            if (
                person
                and re.fullmatch(_NAME, person[0])
                and organization_key(person[0]) != organization_key(organization[0])
                and not re.search(
                    r"\b(?:LLC|Inc|Corp|Company|Construction|Electric|Contracting)\b",
                    person[0],
                    re.I,
                )
            ):
                result.append(
                    Extracted(
                        organization[0],
                        category,
                        person_name=person[0],
                        organization_relationship=relationship,
                        reason=reason,
                        evidence_strength="Low",
                        citations=[*citations, _citation(doc, person[1], "permit_listed_person")],
                    )
                )
        return result
    if source_id == "dallas-monthly-permits":
        parsed = permit_fields(source_id, doc.text)
        organization = parsed.get("lp_business_name")
        if not organization or _RENTAL.search(organization[0]):
            return []
        role = parsed.get("contact_type", ("Applicant", ""))[0]
        return [
            Extracted(
                organization[0],
                Category.UNKNOWN.value,
                organization_relationship="UNKNOWN",
                reason=(
                    "LP Business Name is retained exactly as published by Dallas; its role on "
                    f"this project, including any relation to the separately listed "
                    f"{role} person, "
                    "current work and buying authority are UNKNOWN."
                ),
                citations=[_citation(doc, organization[1], "permit_listed_organization")],
            )
        ]
    if source_id == "houston-weekly-permits":
        parsed = permit_fields(source_id, doc.text)
        buyer = parsed.get("detail_buyer")
        if not buyer or not re.search(
            r"\b(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Company|Ltd\.?|Limited|LLP|L\.P\.)\b",
            buyer[0],
            re.I,
        ):
            return []
        phone = parsed.get("detail_buyer_phone")
        contacts = []
        citations = [_citation(doc, buyer[1], "project_organization")]
        if phone and re.fullmatch(r"[+()0-9 .-]{10,24}", phone[0]):
            citations.append(_citation(doc, phone[1], "permit_listed_contact"))
            contacts.append(
                {
                    "kind": (
                        "permit-listed buyer phone; ownership and business/personal type unknown"
                    ),
                    "value": phone[0],
                    "source_url": doc.url,
                    "quote": phone[1],
                    "observed_at": doc.observed_at.isoformat(),
                }
            )
        buyer_address = parsed.get("detail_buyer_address")
        if buyer_address:
            citations.append(_citation(doc, buyer_address[1], "permit_listed_address"))
        return [
            Extracted(
                buyer[0].lstrip("* "),
                Category.UNKNOWN.value,
                organization_relationship="ROLE_SUPPORTED",
                reason=(
                    "Exact Houston Sold Permit Search detail lists this organization as Buyer. "
                    "Owner/Occupant is retained as a separate field; project assignment, current "
                    "involvement and buying authority beyond the listed permit role are UNKNOWN. "
                    "Phone and address are permit-listed business-contact fields; ownership and "
                    "business/personal status are UNKNOWN."
                ),
                citations=citations,
                public_contacts=contacts,
            )
        ]
    if source_id == "el-paso-new-commercial-permits":
        parsed = permit_fields(source_id, doc.text)
        owner = parsed.get("owner_name")
        if not owner or _RENTAL.search(owner[0]):
            return []
        if not re.search(
            r"\b(?:LLC|L\.L\.C\.|Inc\.?|Corp\.?|Corporation|Company|LP|L\.P\.)\b",
            owner[0],
            re.I,
        ):
            return []
        return [
            Extracted(
                owner[0],
                Category.OWNER.value,
                reason=(
                    "Organization named in the official permit owner field; current operation, "
                    "responsibility for construction power and buying authority are UNKNOWN."
                ),
                citations=[_citation(doc, owner[1], "permit_listed_owner")],
            )
        ]
    if source_id in {"fort-worth-development-permits", "fort-worth-permits"}:
        owner = fort_worth_owner(source_id, doc.text)
        if not owner:
            return []
        return [
            Extracted(
                owner[0],
                Category.OWNER.value,
                reason=(
                    "Organization named in the Fort Worth permit's explicit Owner of record field; "
                    "current operation, responsibility for temporary power and buying authority "
                    "are UNKNOWN."
                ),
                citations=[_citation(doc, owner[1], "permit_listed_owner")],
            )
        ]
    if source_id == GEORGIA:
        proponent = georgia_proponent(doc.text)
        proponents = (
            [
                Extracted(
                    proponent[0],
                    "construction_proponent",
                    reason=(
                        "Named construction proponent in the permit narrative; "
                        "buying authority is UNKNOWN."
                    ),
                    citations=[_citation(doc, proponent[1], "project_organization")],
                )
            ]
            if proponent
            else []
        )
        owner = georgia_named_owner(source_id, doc.text)
        owned = (
            [
                Extracted(
                    owner[0],
                    Category.OWNER.value,
                    reason=(
                        "Organization explicitly identified as owner of the named Georgia permit "
                        "facility; current operation, responsibility for temporary power and "
                        "buying authority are UNKNOWN."
                    ),
                    citations=[_citation(doc, owner[1], "permit_listed_owner")],
                )
            ]
            if owner
            else []
        )
        return (
            proponents
            + owned
            + [
                Extracted(
                    value,
                    "permit_entity",
                    reason=(
                        "Facility name on the draft permit; ownership, current operation "
                        "and buying authority are UNKNOWN."
                    ),
                    citations=[_citation(doc, quote, "project_organization")],
                )
                for label, value, quote in georgia_identity(doc.text)
                if label == "Draft permit entity"
                and re.search(r"\b(?:LLC|Inc\.?|Corporation|Company)\b", value, re.I)
            ]
        )
    if source_id != "chicago-building-permits":
        return []
    return [
        Extracted(
            name,
            CHICAGO_CATEGORIES[kind.upper()].value,
            citations=[
                _citation(doc, name_quote, "project_organization"),
                _citation(doc, type_quote, "organization_category"),
            ],
        )
        for name, kind, name_quote, type_quote in chicago_contacts(doc.text)
        if kind.upper() in CHICAGO_CATEGORIES and not _RENTAL.search(name)
    ]


def extract_organizations(doc: PublicDocument, project: Project) -> list[Extracted]:
    found: list[Extracted] = []
    if doc.structured:
        for row in doc.structured:
            for number in range(1, 16):
                kind = str(row.get(f"contact_{number}_type", ""))
                name = str(row.get(f"contact_{number}_name", "")).strip()
                category = CHICAGO_CATEGORIES.get(kind.upper())
                if name and category and not _RENTAL.search(name):
                    # Preserve complete field pairs as exact JSON; sorted JSON fields may be apart.
                    name_quote = f'"contact_{number}_name": {json.dumps(name, ensure_ascii=False)}'
                    type_quote = f'"contact_{number}_type": {json.dumps(kind, ensure_ascii=False)}'
                    found.append(
                        Extracted(
                            name,
                            category.value,
                            citations=[
                                _citation(doc, name_quote, "project_organization"),
                                _citation(doc, type_quote, "organization_category"),
                            ],
                        )
                    )
        return found
    for sentence in _sentences(doc.text):
        patterns = (
            rf"^(?P<role>{_ROLE_PATTERN})\s*:\s*(?P<org>[^;\n]{{2,100}})$",
            rf"(?P<org>{_ORG})\s+(?:is|was|serves as|will serve as|has been selected as|"
            rf"was selected as|is serving as)\s+(?:the\s+)?(?P<role>{_ROLE_PATTERN})\b",
            rf"(?P<role>{_ROLE_PATTERN})\s+(?P<org>[A-Z][A-Za-z0-9&'’.,/-]*"
            rf"(?:\s+[A-Z][A-Za-z0-9&'’.,/-]*){{0,7}})",
        )
        for pattern in patterns:
            match = re.search(pattern, sentence, re.I if pattern.startswith("^") else 0)
            if not match:
                continue
            # The relation's own clause must point at this project. Another project
            # elsewhere in a sentence/document cannot lend its identity to this contractor.
            relation_tail = sentence[match.end() :]
            if not _explicit_project_target(relation_tail, project):
                continue
            organization = match.group("org").strip(" ,.;")
            organization = re.sub(r"^(?:The|the)\s+", "", organization)
            role = match.group("role").casefold()
            if len(organization) < 2 or _RENTAL.search(organization):
                continue
            ambiguous = bool(_AMBIGUOUS.search(sentence))
            found.append(
                Extracted(
                    organization,
                    _ROLE_WORDS[role].value,
                    organization_relationship="UNKNOWN" if ambiguous else "DIRECT",
                    evidence_strength="Low" if ambiguous else "High",
                    reason="Ambiguous organization involvement remains UNKNOWN."
                    if ambiguous
                    else "Project involvement is explicit; purchasing authority is UNKNOWN.",
                    citations=[_citation(doc, sentence, "project_organization")],
                )
            )
            break
    return found


def _official_profile(doc: PublicDocument, organization: str) -> bool:
    parts = urlsplit(doc.url)
    host = (parts.hostname or "").removeprefix("www.")
    labels = host.split(".")
    org_key = organization_key(organization)
    domain_key = re.sub(r"[^a-z0-9]", "", org_key)
    origin_matches = (
        len(labels) == 2
        and labels[1] in {"com", "org", "net"}
        and re.sub(r"[^a-z0-9]", "", labels[0]) == domain_key
    )
    identity_in_title = org_key in normalized_identity(doc.title)
    path = parts.path.strip("/")
    roster_path = path in {"about", "about-us", "team", "leadership", "management", "our-team"}
    profile_sentence = re.search(rf"(?P<name>{_NAME}) serves as ", doc.text)
    person_path = bool(
        profile_sentence
        and normalized_identity(path) == normalized_identity(profile_sentence.group("name"))
    )
    archive = re.search(r"(?:archive|former|retired|/20\d\d/)", doc.url, re.I)
    historical_title = re.search(r"\b(?:former|retired|previous|past)\b", doc.title, re.I)
    historical_heading = re.search(
        r"^\s*(?:former|retired|previous|past)\s+(?:leadership|leaders|management|team|staff)\b",
        doc.text,
        re.I | re.M,
    )
    return bool(
        origin_matches
        and identity_in_title
        and (roster_path or person_path)
        and doc.published_at is None
        and not archive
        and not historical_title
        and not historical_heading
    )


def _role_category(title: str, organization_category: str) -> str | None:
    lower = title.casefold()
    if any(
        term in lower
        for term in (
            "construction",
            "project manager",
            "project director",
            "project executive",
            "preconstruction",
            "superintendent",
            "infrastructure development",
        )
    ):
        return (
            organization_category
            if organization_category
            in {
                Category.ELECTRICAL,
                Category.GC,
                Category.EPC,
                Category.COMMISSIONING,
            }
            else Category.OWNER_CONSTRUCTION.value
        )
    if any(term in lower for term in ("procurement", "purchasing", "supply chain")):
        return Category.PROCUREMENT.value
    if any(term in lower for term in ("energy", "power", "electrical", "distributed generation")):
        return (
            Category.OWNER_ENERGY.value
            if organization_category == Category.OWNER
            else organization_category
        )
    if "commission" in lower:
        return Category.COMMISSIONING.value
    if any(
        term in lower
        for term in (
            "field operations",
            "production operations",
            "drilling",
            "completions",
            "facilities engineer",
            "facilities engineering",
        )
    ):
        return Category.FIELD_OPERATIONS.value
    if lower == "operations manager" and organization_category == Category.OPERATOR:
        return Category.FIELD_OPERATIONS.value
    if lower in {"coo", "chief operating officer"} and organization_category in {
        Category.OWNER,
        Category.OPERATOR,
    }:
        return Category.OWNER_CONSTRUCTION.value
    if organization_category in {
        Category.ELECTRICAL,
        Category.GC,
        Category.EPC,
        Category.COMMISSIONING,
    } and re.fullmatch(r"(?:president|ceo|chief executive officer|vice president|svp)", lower):
        return organization_category
    return None


def _published_roster_title(title: str) -> bool:
    """Require an occupational title, not adjacent marketing/action copy."""
    return bool(
        re.match(
            r"^(?:CEO|COO|CFO|CTO|EVP|SVP|VP|Vice President|President|"
            r"Chief\s+\w+|Director|Manager|Head|Superintendent|"
            r"Facilities\s+Engineer(?:ing)?|Electrical\s+Construction|"
            r"Power\s+Procurement|Distributed\s+Generation|"
            r"Infrastructure\s+Development|Operations\s+Manager|"
            r"Field\s+Operations|"
            r"Procurement|Supply\s+Chain|Construction\s+(?:Manager|Director)|"
            r"Project\s+(?:Manager|Director|Executive))\b",
            title.strip(),
            re.I,
        )
    )


def _public_contacts(doc: PublicDocument, person_name: str) -> list[dict]:
    """Accept only complete, literal, same-clause named contact statements."""
    name = re.escape(person_name)
    email = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}"
    phone = r"(?:\+1[ .-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[ .-]?[2-9]\d{2}[ .-]?\d{4}"
    patterns = (
        ("email", rf"{name}[ \t]+(?:email:[ \t]*|can be reached at[ \t]+)({email})\.?"),
        ("phone", rf"{name}[ \t]+can be reached at[ \t]+({phone})\.?"),
    )
    contacts = []
    for sentence in _sentences(doc.text):
        for raw_clause in sentence.split(";"):
            clause = raw_clause.strip()
            for kind, pattern in patterns:
                match = re.fullmatch(pattern, clause)
                if match:
                    contact = {
                        "kind": kind,
                        "value": match.group(1),
                        "source_url": doc.url,
                        "quote": clause,
                        "observed_at": doc.observed_at.isoformat(),
                    }
                    if contact not in contacts:
                        contacts.append(contact)
    return contacts


def extract_company_contacts(
    doc: PublicDocument, organizations: list[Extracted]
) -> list[Extracted]:
    """Require explicit company attribution, never assign a page's arbitrary addresses.

    A published company method is a generic route, not a named buyer. Retain the
    original project relationship citations together with each literal method.
    """
    results = []
    for org in organizations:
        if org.person_name or org.organization_relationship != "DIRECT":
            continue
        contacts = _public_contacts(doc, org.organization)
        for row in doc.structured:
            # Explicit self-published organization schema; not fuzzy domain inference.
            if (
                not isinstance(row, dict)
                or row.get("@type") != "Organization"
                or row.get("name") != org.organization
                or not isinstance(row.get("url"), str)
                or urlsplit(row["url"]).hostname != urlsplit(doc.url).hostname
            ):
                continue
            quote = json.dumps(row, sort_keys=True, ensure_ascii=False)
            if quote not in doc.text:
                continue
            points = row.get("contactPoint", [])
            points = points if isinstance(points, list) else [points]
            for point in [row, *points]:
                if not isinstance(point, dict):
                    continue
                for field_name, kind in (("email", "email"), ("telephone", "phone")):
                    value = point.get(field_name)
                    if not isinstance(value, str):
                        continue
                    # Syntax/action validation is shared with the API projection.
                    contacts.append(
                        {
                            "kind": kind,
                            "value": value,
                            "source_url": doc.url,
                            "quote": quote,
                            "observed_at": doc.observed_at.isoformat(),
                        }
                    )
        if not contacts:
            continue
        results.append(
            Extracted(
                organization=org.organization,
                category=org.category,
                reason="Published company method; purchasing authority requires confirmation.",
                citations=[
                    *org.citations,
                    *[_citation(doc, c["quote"], "public_contact") for c in contacts],
                ],
                public_contacts=contacts,
            )
        )
    return results


def extract_people(
    doc: PublicDocument,
    organizations: list[Extracted],
    project: Project,
    *,
    project_scoped: bool,
    today: date,
    verified_official_roster: bool = False,
) -> list[Extracted]:
    found = []
    # Text nodes are often split around heading tags. Join only adjacent lines;
    # the exact original source remains the citation (no generated quote).
    lines = doc.text.splitlines()
    adjacent_roster = [
        f"{name}\n{title}"
        for name, title in zip(lines, lines[1:], strict=False)
        if verified_official_roster and re.fullmatch(_NAME, name)
    ]
    for sentence in [*_sentences(doc.text), *adjacent_roster]:
        for org in organizations:
            if org.person_name is not None:
                continue  # Permit-listed people cannot lend citations to another person.
            normalized_sentence = organization_key(sentence)
            org_name = organization_key(org.organization)
            official = (
                _official_profile(doc, org.organization) or verified_official_roster
            ) and 0 <= (today - doc.observed_at.date()).days <= 365
            roster = re.fullmatch(
                rf"(?P<name>{_NAME})(?:,\s*|\n)(?P<title>[^;\n]{{3,80}})",
                sentence,
            )
            if official and roster:
                title = roster.group("title").strip()
                category = _role_category(title, org.category)
                if category and _published_roster_title(title) and not _AMBIGUOUS.search(sentence):
                    contacts = _public_contacts(doc, roster.group("name"))
                    found.append(
                        Extracted(
                            org.organization,
                            category,
                            roster.group("name"),
                            title,
                            org.organization_relationship,
                            "CURRENT",
                            "ROLE_SUPPORTED"
                            if org.organization_relationship == "DIRECT"
                            else "UNKNOWN",
                            "Medium",
                            "Current roster; project assignment and buying authority are UNKNOWN.",
                            [
                                *org.citations,
                                _citation(doc, sentence, "organization_person_role"),
                                *[_citation(doc, c["quote"], "public_contact") for c in contacts],
                            ],
                            contacts,
                        )
                    )
                continue
            if not org_name or org_name not in normalized_sentence:
                continue
            pattern = (
                rf"(?P<name>{_NAME})(?:\s+serves as|\s+is|,)\s+"
                rf"(?P<title>[^.;\n]{{3,120}}?)\s+(?:at|of|for)\s+"
                rf"(?P<org>(?i:{_employer_pattern(org.organization)}))"
                rf"(?=$|[,.;]|\s+(?:for|on)\b)"
            )
            match = re.search(pattern, sentence)
            if not match:
                continue
            reported_org = match.group("org")
            if organization_key(reported_org) != org_name:
                continue
            role_suffix = sentence[match.end("org") :]

            title = match.group("title").strip(" ,")
            category = _role_category(title, org.category)
            if not category:
                continue  # Do not turn generic corporate leadership into a contact list.
            ambiguous = bool(_AMBIGUOUS.search(sentence))
            fresh = current_role(doc.published_at, today) or official
            # A quote about the project is not an assignment. Require explicit role/assignment
            # language plus selected-project name or a scoped 'for/on this/the project'.
            assignment = bool(
                project_scoped
                and _explicit_project_target(role_suffix, project)
                and re.search(
                    r"\b(?:project manager|project director|superintendent)\b", title, re.I
                )
                and not re.search(r"\b(?:not|no|without|never|unassigned)\b", sentence, re.I)
            )

            relation = person_project_relationship(
                organization_direct=org.organization_relationship == "DIRECT",
                current_role=fresh,
                relevant_role=True,
                direct_assignment=assignment,
                ambiguous=ambiguous,
            )
            citations = [*org.citations, _citation(doc, sentence, "organization_person_role")]
            if assignment:
                citations.append(_citation(doc, sentence, "person_project_assignment"))
            contacts = _public_contacts(doc, match.group("name")) if fresh and not ambiguous else []
            citations.extend(_citation(doc, c["quote"], "public_contact") for c in contacts)
            found.append(
                Extracted(
                    org.organization,
                    category,
                    match.group("name"),
                    title,
                    org.organization_relationship,
                    "CURRENT" if fresh and not ambiguous else "UNKNOWN",
                    relation,
                    "High"
                    if relation == "DIRECT"
                    else "Medium"
                    if relation == "ROLE_SUPPORTED"
                    else "Low",
                    "Explicit current project assignment; purchasing authority remains unverified."
                    if relation == "DIRECT"
                    else "Current role; project assignment and buying authority are UNKNOWN."
                    if relation == "ROLE_SUPPORTED"
                    else "Stale or ambiguous role; current assignment is UNKNOWN.",
                    citations,
                    contacts,
                )
            )
    return found
