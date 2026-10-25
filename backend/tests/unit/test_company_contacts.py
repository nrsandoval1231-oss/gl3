from datetime import UTC, datetime
from uuid import uuid4

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument, parse_document
from gridlens.intelligence.buying_chain_extraction import Extracted, extract_company_contacts
from gridlens.intelligence.company_contacts import project_contacts


def test_html_retains_contact_targets_without_discarding_labels():
    doc = parse_document(
        "https://acme.example/contact",
        b"<html><title>Contact</title><body>Business contact directory "
        b'<a href="mailto:office@acme.example?subject=Hello">Email us</a>'
        b'<a href="tel:+15125550123">Call our office</a></body></html>',
        "text/html",
    )
    assert "Email us office@acme.example" in doc.text
    assert "Call our office +15125550123" in doc.text


def test_company_extraction_requires_explicit_attribution():
    org = Extracted("Acme", "owner_developer")
    doc = PublicDocument(
        "https://records.example/project",
        "Project announcement",
        "Acme email: office@acme.example\nOther email: other@other.example",
    )
    found = extract_company_contacts(doc, [org])
    assert len(found) == 1
    assert found[0].person_name is None
    assert [c["value"] for c in found[0].public_contacts] == ["office@acme.example"]
    assert (
        extract_company_contacts(PublicDocument(doc.url, doc.title, "office@acme.example"), [org])
        == []
    )


def candidate(company_id):
    quote = "Acme email: office@acme.example"
    return dict(
        id=uuid4(),
        company_identity_id=company_id,
        organization="Acme",
        category="owner_developer",
        organization_relationship="DIRECT",
        public_contacts=[
            dict(
                kind="email",
                value="office@acme.example",
                source_url="https://acme.example/contact",
                quote=quote,
                observed_at=datetime.now(UTC),
            )
        ],
        evidence=[
            dict(
                id=uuid4(),
                current_support=True,
                supports="public_contact",
                url="https://acme.example/contact",
                quote=quote,
                title="Contact",
                extraction_location="body",
            )
        ],
    )


def test_company_projection_deduplicates_preserves_sources_and_isolates_identities():
    company = uuid4()
    first, second = candidate(company), candidate(company)
    projects = {
        uuid4(): {"candidates": [first, candidate(uuid4())]},
        uuid4(): {"candidates": [second]},
    }
    result = project_contacts(company, projects)
    assert len(result.contacts) == 1
    assert len(result.contacts[0].project_ids) == 2
    assert len(result.contacts[0].sources) == 2
    assert result.research_required
    assert result.contacts[0].methods[0]["href"] == "mailto:office@acme.example"
    first["stale"] = True
    second["retracted"] = True
    assert not project_contacts(company, projects).contacts


def test_structured_directory_keeps_exact_company_provenance():
    import json

    row = {
        "@type": "Organization",
        "name": "Acme",
        "url": "https://acme.example",
        "email": "office@acme.example",
        "telephone": "+15125550123",
    }
    body = (
        "<html><title>Acme</title><body>Acme business contact directory"
        '<script type="application/ld+json">' + json.dumps(row) + "</script></body></html>"
    )
    doc = parse_document("https://acme.example/contact", body.encode(), "text/html")
    contacts = extract_company_contacts(doc, [Extracted("Acme", "owner_developer")])
    assert len(contacts[0].public_contacts) == 2
    assert all(c["quote"] in doc.text for c in contacts[0].public_contacts)
    assert not extract_company_contacts(doc, [Extracted("Other", "owner_developer")])
    from dataclasses import replace

    doc = replace(doc, url="https://third-party.example")
    assert not extract_company_contacts(doc, [Extracted("Acme", "owner_developer")])


def test_permit_name_without_role_is_not_a_relevant_buyer():
    company = uuid4()
    row = candidate(company)
    row["person_name"] = "Permit Applicant"
    result = project_contacts(company, {uuid4(): {"candidates": [row]}})
    assert result.research_required
