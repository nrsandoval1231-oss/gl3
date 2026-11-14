from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.regulatory_project_organizations import (
    extract_regulatory_project_organizations,
)

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
SEC_URL = "https://www.sec.gov/Archives/edgar/data/123456/000012345624000001/example.htm"


def project(*, aliases=("North Campus",), name="North Campus"):
    return SimpleNamespace(
        name=name,
        identity_facts={"project_aliases": list(aliases)},
    )


def sec_document(
    *,
    issuer="Example Compute LLC",
    alias="Example Compute",
    domain="examplecompute.com",
    observed_at=NOW - timedelta(hours=1),
    published_at=date(2026, 10, 1),
):
    text = (
        f"COMPANY CONFORMED NAME: {issuer}\n"
        "IRS NUMBER: 12-3456789\n"
        f'{issuer} is also known as "{alias}".\n'
        f"Our website is https://www.{domain}.\n"
    )
    return PublicDocument(
        SEC_URL,
        "Example Compute annual report",
        text,
        published_at=published_at,
        observed_at=observed_at,
    )


def project_document(
    text,
    *,
    url="https://ir.examplecompute.com/news/north-campus",
    publisher="Example Compute LLC",
):
    retained_text = f"Publisher: {publisher}\n{text}" if publisher else text
    return PublicDocument(
        url,
        "North Campus update",
        retained_text,
        published_at=date(2025, 6, 2),
        observed_at=NOW - timedelta(hours=1),
    )


def extract(text, *, sec=None, aliases=("North Campus",), url=None):
    document = project_document(text, url=url or "https://ir.examplecompute.com/news/north-campus")
    return extract_regulatory_project_organizations(
        project(aliases=aliases),
        document,
        [sec or sec_document()],
        now=NOW,
    )


def test_exact_sec_defined_alias_and_domain_proof_support_direct_developer_role():
    text = "Example Compute designed North Campus for high-density computing."
    result = extract(text)

    assert len(result) == 1
    organization = result[0]
    assert (organization.organization, organization.category) == (
        "Example Compute LLC",
        "owner_developer",
    )
    assert organization.organization_relationship == "DIRECT"
    assert "does not establish legal ownership" in organization.reason
    assert organization.citations[0]["quote"] == "Publisher: Example Compute LLC"
    assert organization.citations[0]["supports"] == "project_organization"
    assert organization.citations[1]["quote"] == text


def test_native_possessive_site_relation_needs_explicit_design_assertion():
    assert not extract("Example Compute’s North Campus is designed to host critical IT load.")
    assert not extract("Example Compute’s North Campus has 400 MW of IT load.")
    assert extract("North Campus is designed by Example Compute to host critical IT load.")


@pytest.mark.parametrize(
    "text",
    [
        "Example Compute may develop North Campus next year.",
        "Example Compute formerly developed North Campus.",
        "Example Compute designed South Campus in another county.",
        "Another company designed North Campus for Example Compute.",
        "Example Compute is the architect for North Campus.",
        "Example Compute designed North Campus as architect for its subsidiary.",
        "Example Compute designed North Campus on behalf of Parent Holdings.",
        "The source says Example Compute designed North Campus.",
    ],
)
def test_rejects_unbound_uncertain_foreign_or_nondeveloper_relations(text):
    assert not extract(text)


@pytest.mark.parametrize(
    "text",
    [
        "Example Compute designed North Campus East for high-density computing.",
        "North Campus is designed by Example Compute LLC.",
        "North Campus is designed by Example Compute, LLC.",
    ],
)
def test_site_and_actor_names_require_exact_boundaries(text):
    assert not extract(text)


def test_sec_defined_alias_is_required_and_brand_to_issuer_expansion_is_not_inferred():
    wrong_issuer = sec_document(issuer="Other Compute LLC", alias="Example Compute")
    assert not extract("Example Compute designed North Campus.", sec=wrong_issuer)

    applied = project_document(
        "Applied Digital designed Ellendale for deployment speed.",
        url="https://ir.applieddigital.com/news/ellendale",
        publisher=None,
    )
    applied_sec = sec_document(
        issuer="Applied Digital Corporation",
        alias="Applied Digital Corporation",
        domain="applieddigital.com",
    )
    result = extract_regulatory_project_organizations(
        SimpleNamespace(
            name="Ellendale Campus",
            identity_facts={"project_aliases": ["Ellendale Campus"]},
        ),
        applied,
        [applied_sec],
        now=NOW,
    )
    assert result == []


def test_exact_publisher_field_joins_bare_stem_to_verified_legal_issuer_locally():
    text = "Announcement :: Applied Digital Corporation (APLD)\n"
    text += (
        "Applied Digital designed Ellendale for deployment speed. Applied Digital’s "
        "Ellendale campus is designed to host 400 MW of critical IT load."
    )
    document = project_document(
        text,
        url="https://ir.applieddigital.com/news/ellendale",
        publisher=None,
    )
    sec = sec_document(
        issuer="Applied Digital Corporation",
        alias="Applied Digital Corporation",
        domain="applieddigital.com",
    )
    result = extract_regulatory_project_organizations(
        SimpleNamespace(
            name="Ellendale Campus",
            location="Ellendale, North Dakota",
            identity_facts={"project_aliases": ["Ellendale"]},
        ),
        document,
        [sec],
        now=NOW,
    )

    assert len(result) == 1
    assert result[0].organization == "Applied Digital Corporation"
    assert {item["supports"] for item in result[0].citations} == {
        "project_organization",
        "organization_category",
    }
    assert all(item["quote"] in document.text for item in result[0].citations)


@pytest.mark.parametrize(
    ("role_sentence", "site_confirmation"),
    [
        (
            "Example Compute designed Ellendale city hall for deployment speed.",
            "Example Compute’s Ellendale campus is designed to host 400 MW.",
        ),
        (
            "Example Compute designed Ellendale for deployment speed.",
            "Example Compute’s Ellendale Campus East is designed to host 400 MW.",
        ),
    ],
)
def test_short_site_alias_cannot_bind_city_hall_or_sibling_campus(role_sentence, site_confirmation):
    text = f"Announcement :: Example Compute LLC (EXMP)\n{role_sentence} {site_confirmation}"
    document = project_document(
        text,
        url="https://ir.examplecompute.com/news/ellendale",
        publisher=None,
    )
    result = extract_regulatory_project_organizations(
        SimpleNamespace(
            name="Ellendale Campus",
            location="Ellendale, North Dakota",
            identity_facts={"project_aliases": ["Ellendale"]},
        ),
        document,
        [sec_document()],
        now=NOW,
    )
    assert result == []


def test_rejects_wrong_publisher_domain_stale_or_future_sec_proof():
    text = "Example Compute designed North Campus for high-density computing."
    wrong_domain = sec_document(domain="unrelated.example")
    stale = sec_document(observed_at=NOW - timedelta(days=31))
    future = sec_document(published_at=date(2027, 1, 1))

    assert not extract(text, sec=wrong_domain)
    assert not extract(text, sec=stale)
    assert not extract(text, sec=future)


def test_rejects_ambiguous_multiple_publisher_identity_fields():
    document = project_document(
        "Example Compute designed North Campus for high-density computing.\n"
        "Publisher: Other Compute LLC"
    )
    assert not extract_regulatory_project_organizations(
        project(), document, [sec_document()], now=NOW
    )


def test_requires_exact_native_project_alias_and_subdomain_boundary():
    text = "Example Compute designed North Campus for high-density computing."
    project_source = project(aliases=("North Campus East",), name="Unknown Project")
    document = project_document(text)
    assert not extract_regulatory_project_organizations(
        project_source,
        document,
        [sec_document()],
        now=NOW,
    )

    valid = extract(
        text,
        url="https://ir.examplecompute.com/news/north-campus",
    )
    invalid = extract(
        text,
        url="https://examplecompute.com.attacker.example/news/north-campus",
    )
    assert valid
    assert invalid == []
