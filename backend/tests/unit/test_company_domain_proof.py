from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.intelligence.company_domain_proof import (
    extract_company_domain_proof,
    parse_sec_domain_assertion,
)

ORG = "Example Compute, Inc."
EIN = "12-3456789"
HASH = "a" * 64
BASE = """COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
Our website is https://www.examplecompute.com.
The information on our website is not part of this filing.
"""


def source(
    text: str = BASE,
    url: str = "https://www.sec.gov/Archives/edgar/data/123456/000012345624000001/example-2024.htm",
):
    return SimpleNamespace(url=url, excerpt=text, content_hash=HASH)


def test_sec_filing_proves_only_explicit_issuer_domain_with_offsets_and_source_hash():
    evidence = source()
    proof = parse_sec_domain_assertion(evidence, organization=ORG, expected_ein=EIN)

    assert proof is not None
    assert proof.issuer_name == ORG
    assert proof.ein == "123456789"
    assert proof.domain == "examplecompute.com"
    assert evidence.excerpt[proof.start_offset : proof.end_offset] == proof.quote
    assert proof.quote == "Our website is https://www.examplecompute.com."
    assert proof.source_url == evidence.url
    assert proof.source_hash == HASH


def test_company_label_website_field_and_cover_page_issuer_are_supported():
    text = """Example Compute, Inc. (Exact name of registrant as specified in its charter)
(I.R.S. Employer Identification No.)
12-3456789
Example Compute, Inc. website: https://www.examplecompute.com/
"""
    proof = parse_sec_domain_assertion(source(text), organization=ORG)
    assert proof is not None
    assert proof.domain == "examplecompute.com"
    assert proof.ein == "123456789"
    assert "Example Compute, Inc. website:" in proof.quote


def test_sec_markdown_cover_table_and_internet_address_clause_are_supported():
    text = """Commission File Number 001-00001

EXAMPLE COMPUTE, INC.
|     |     |     |
| --- | --- | --- |
| Washington |  | 12-3456789 |
| (STATE OF INCORPORATION) |  | (I.R.S. ID) |
Our Internet address is www.examplecompute.com.
"""
    proof = parse_sec_domain_assertion(source(text), organization=ORG)
    assert proof is not None
    assert proof.domain == "examplecompute.com"
    assert proof.ein == "123456789"
    assert proof.quote == "Our Internet address is www.examplecompute.com."


@pytest.mark.parametrize(
    ("issuer", "ein", "statement", "domain"),
    [
        (
            "MICROSOFT CORPORATION",
            "91-1144442",
            "Our Internet address is www.microsoft.com.",
            "microsoft.com",
        ),
        (
            "APPLIED DIGITAL CORPORATION",
            "95-4863690",
            "Our principal website address is www.applieddigital.com.",
            "applieddigital.com",
        ),
        (
            "EQUINIX, INC.",
            "77-0487526",
            "You may also obtain copies of our annual reports on Form 10-K, our quarterly reports "
            "on Form 10-Q and our current reports on Form 8-K, including exhibits, and any "
            "amendments to such reports, free of charge by visiting the Investor Relations page "
            "on our website, www.equinix.com.",
            "equinix.com",
        ),
    ],
)
def test_public_sec_filing_format_examples(issuer, ein, statement, domain):
    text = f"""Commission File Number 001-00001

{issuer}
(Exact name of registrant as specified in its charter)
| Delaware | | {ein} |
| (STATE OF INCORPORATION) | | (I.R.S. Employer Identification No.) |
{statement}
"""
    proof = parse_sec_domain_assertion(source(text), organization=issuer)
    assert proof is not None
    assert proof.domain == domain


@pytest.mark.parametrize(
    ("issuer", "ein", "website", "domain"),
    [
        (
            "APPLIED DIGITAL CORPORATION",
            "95-4863690",
            "Our principal website address is www.applieddigital.com.",
            "applieddigital.com",
        ),
    ],
)
def test_real_filing_cover_and_first_party_website_patterns(issuer, ein, website, domain):
    text = f"""Commission File Number 001-00001

{issuer}
(Exact name of registrant as specified in its charter)
| Nevada | {ein} |
| (STATE OF INCORPORATION) | (I.R.S. Employer Identification No.) |
{website}
"""
    proof = parse_sec_domain_assertion(source(text), organization=issuer)
    assert proof is not None
    assert proof.domain == domain
    assert proof.issuer_name == issuer


@pytest.mark.parametrize(
    "statement",
    [
        "Our subsidiary reports: Our website is https://subsidiary.example.",
        "In an exhibit, Beta LLC states: Our website is https://beta.example.",
        "Beta LLC states: Our website is https://beta.example.",
        "Beta LLC reports:\nOur website is https://beta.example.",
        "Beta LLC:\n\nOur website is https://beta.example.",
        "Our website is https://old.example, which is no longer our official website.",
        "Our website is https://old.example. This is no longer our official website.",
        "Our website is https://old.example. This is no longer the official website.",
        "Our website is https://old.example.\n\nThis is no longer the official website.",
    ],
)
def test_rejects_quoted_foreign_and_superseded_first_person_website_statements(statement):
    text = f"""COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
{statement}
"""
    assert parse_sec_domain_assertion(source(text), organization=ORG, expected_ein=EIN) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sec.gov.attacker.example/Archives/edgar/data/123456/000012345624000001/example.htm",
        "https://sec.gov@attacker.example/Archives/edgar/data/123456/000012345624000001/example.htm",
        "https://sec.gov:443/Archives/edgar/data/123456/000012345624000001/example.htm",
        "https://sec.gov/Archives/edgar/data/123456/000012345624000001/example.htm?download=1",
        "https://sec.gov/Archives/edgar/data/123456/000012345624000001/example.htm#section",
        "http://www.sec.gov/Archives/edgar/data/123456/000012345624000001/example.htm",
        "https://sec.gov/Archives/edgar/data/123456/000012345624000001/",
        "https://www.sec.gov.evil/Archives/edgar/data/123456/000012345624000001/example.htm",
    ],
)
def test_rejects_sec_url_spoofing_and_noncanonical_url_parts(url: str):
    assert parse_sec_domain_assertion(source(url=url), organization=ORG, expected_ein=EIN) is None


@pytest.mark.parametrize(
    "text",
    [
        BASE.replace("12-3456789", "98-7654321"),
        BASE + "IRS NUMBER: 98-7654321\n",
        BASE.replace("Example Compute, Inc.", "Other Compute LLC", 1),
        BASE + "COMPANY CONFORMED NAME: Other Compute LLC\n",
        BASE.replace(
            "Our website is https://www.examplecompute.com.",
            "Our website is not https://www.customer-site.example.",
        ),
        """COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
Customer website: https://customer.example
""",
        """COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
Our website is https://www.examplecompute.com. Our website is https://other.example.
""",
        """COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
Other Compute LLC website: https://other.example
""",
    ],
)
def test_rejects_foreign_ein_issuer_negation_customer_site_and_multiple_authorities(text: str):
    assert parse_sec_domain_assertion(source(text), organization=ORG, expected_ein=EIN) is None


def test_unbound_website_or_generic_footer_is_not_domain_proof():
    text = """COMPANY CONFORMED NAME: Example Compute, Inc.
IRS NUMBER: 12-3456789
For more information visit https://examplecompute.com.
"""
    assert parse_sec_domain_assertion(source(text), organization=ORG) is None


def test_bootstrap_requires_one_unambiguous_ein_even_without_expected_ein():
    assert parse_sec_domain_assertion(source(), organization=ORG) is not None
    text = BASE + "IRS NUMBER: 98-7654321\n"
    assert parse_sec_domain_assertion(source(text), organization=ORG) is None


def test_legal_form_must_match_or_be_an_explicit_sec_defined_alias():
    assert (
        parse_sec_domain_assertion(source(), organization="Example Compute LLC", expected_ein=EIN)
        is None
    )
    alias_text = BASE.replace(
        "IRS NUMBER:",
        'Example Compute, Inc. is also known as "Example Compute".\nIRS NUMBER:',
    )
    alias = parse_sec_domain_assertion(
        source(alias_text), organization="Example Compute", expected_ein=EIN
    )
    assert alias is not None
    borrowed_alias = (
        BASE.replace(
            "IRS NUMBER:",
            "IRS NUMBER:",
        )
        + 'Example Compute, Inc. Our subsidiary Beta LLC is also known as "Example Compute".\n'
    )
    assert (
        parse_sec_domain_assertion(
            source(borrowed_alias), organization="Example Compute", expected_ein=EIN
        )
        is None
    )


def test_typed_ein_identifier_must_belong_to_canonical_company():
    identity_id = uuid4()
    identity = SimpleNamespace(id=identity_id)
    identifier = SimpleNamespace(
        entity_type="company",
        identifier_type="ein",
        company_identity_id=identity_id,
        person_identity_id=None,
        normalized_value=EIN,
    )
    proof = extract_company_domain_proof(
        source(), identity=identity, organization=ORG, identifiers=[identifier]
    )
    assert proof is not None
    assert proof.company_identity_id == identity_id

    foreign_identifier = SimpleNamespace(**{**identifier.__dict__, "company_identity_id": uuid4()})
    assert (
        extract_company_domain_proof(
            source(), identity=identity, organization=ORG, identifiers=[foreign_identifier]
        )
        is None
    )
