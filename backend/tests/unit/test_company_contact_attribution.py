from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import document_content_hash
from gridlens.intelligence.company_contact_attribution import (
    _exact_houston_project_contact,
    _fact_matches_method,
    filter_unbound_company_contacts,
    supported_contact_facts,
)

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


def _source(url: str, title: str, excerpt: str, reason: str) -> SimpleNamespace:
    document = PublicDocument(url, title, excerpt, observed_at=NOW)
    return SimpleNamespace(
        url=url,
        title=title,
        excerpt=excerpt,
        project_match_reason=reason,
        content_hash=document_content_hash(document),
        extraction_location="",
        published_at=None,
        observed_at=NOW,
    )


def test_rrc_registry_formatted_phone_becomes_exact_normalized_native_fact():
    number = "123456"
    url = (
        "https://webapps2.rrc.texas.gov/EWA/organizationResultsDrillDownAction.do"
        f"?methodToCall=searchByOperatorNo&operatorNo={number}"
    )
    excerpt = (
        "Organization Operator Query Results\n"
        f"Operator Number: {number}\n"
        "Operator Name: EOG Resources\n"
        "Organization Phone No: (713) 651-7000"
    )
    source = _source(
        url,
        "RRC registry result",
        excerpt,
        "exact-number public rrc operator registry organization phone.",
    )
    identity = SimpleNamespace(id=uuid4(), rrc_operator_number=number)
    facts = supported_contact_facts(
        None,
        source,
        organization="EOG Resources",
        identity=identity,
        project=None,
        retained_context=None,
        candidate={"person_name": None},
    )
    fact = next(iter(facts))
    assert fact.company_id == str(identity.id)
    assert fact.person_name is None
    assert fact.method_kind == "phone"
    assert fact.method_value == "7136517000"
    assert fact.quote == "Organization Phone No: (713) 651-7000"
    assert fact.source_hash == source.content_hash
    candidate = {
        "company_identity_id": str(identity.id),
        "person_name": None,
        "title": None,
        "category": None,
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "UNKNOWN",
        "person_project_relationship": "UNKNOWN",
    }
    valid_method = {
        "kind": "phone",
        "value": "(713) 651-7000",
        "source_url": url,
        "quote": fact.quote,
    }
    assert _fact_matches_method(fact, valid_method, candidate, str(identity.id))
    assert not _fact_matches_method(
        fact,
        {**valid_method, "value": "(713) 999-0100"},
        candidate,
        str(identity.id),
    )
    assert not _fact_matches_method(
        fact,
        valid_method,
        {**candidate, "person_name": "Jordan Smith"},
        str(identity.id),
    )


def test_houston_binding_requires_exact_https_origin_and_native_form_parameters():
    query = urlencode(
        {
            "IBIF_webapp": "/ibi_apps",
            "IBIC_server": "EDASERVE",
            "IBIWF_msgviewer": "OFF",
            "IBIAPP_app": "soldpermits",
            "IBIF_ex": "sold_permit_d",
            "CLICKED_ON": "",
            "PN": "26051624",
            "PT": "13",
        }
    )
    url = f"https://cohtora.houstontx.gov/ibi_apps/WFServlet.ibfs?{query}"
    excerpt = (
        "detail_project: 26051624\n"
        "detail_date: 2026-09-02\n"
        "detail_site_address: 8930 GULF FWY A 77017\n"
        "detail_permit_type: Building Pmt\n"
        "detail_buyer: *ACME LLC\n"
        "detail_buyer_phone: (713) 555-0100"
    )
    source = _source(
        url,
        "Houston sold permit detail",
        excerpt,
        "exact houston sold permit project, permit type, date and site match the selected project.",
    )
    project = SimpleNamespace(
        source_id="houston-weekly-permits",
        external_id="26051624:Building Pmt:2026-09-02",
        location="8930 GULF FWY A, Houston, TX",
    )
    assert _exact_houston_project_contact(source, project, organization="ACME LLC")

    for altered_url in (
        url.replace("https://", "http://"),
        url.replace("cohtora.houstontx.gov/", "cohtora.houstontx.gov:8443/"),
        url.replace("https://cohtora.houstontx.gov/", "https://user@cohtora.houstontx.gov/"),
        url.replace("IBIF_ex=sold_permit_d", "IBIF_ex=other"),
        url + "&unpaired",
    ):
        altered = SimpleNamespace(**source.__dict__)
        altered.url = altered_url
        assert not _exact_houston_project_contact(altered, project, organization="ACME LLC")


def test_unlinked_site_person_is_dropped_but_company_project_claim_remains():
    person = {
        "company_identity_id": None,
        "organization": "Acme LLC",
        "person_name": "Alice Smith",
        "title": "Project Director",
        "public_contacts": [
            {
                "kind": "email",
                "value": "alice@acme.example",
                "source_url": "https://acme.example/team",
                "quote": "Alice Smith email: alice@acme.example",
            }
        ],
        "evidence": [
            {
                "supports": "organization_person_role",
                "quote": "Alice Smith is Project Director at Acme LLC.",
            },
            {
                "supports": "public_contact",
                "quote": "Alice Smith email: alice@acme.example",
            },
        ],
    }
    organization = {
        "company_identity_id": None,
        "organization": "Acme LLC",
        "person_name": None,
        "person_identity_id": "unverified-person-id",
        "title": "Project Director",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT",
        "person_project_relationship": "DIRECT",
        "public_contacts": [
            {
                "kind": "email",
                "value": "office@acme.example",
                "source_url": "https://acme.example/contact",
                "quote": "Email: office@acme.example",
            }
        ],
        "evidence": [
            {"supports": "project_organization", "quote": "Acme LLC is the project developer."},
            {"supports": "public_contact", "quote": "Email: office@acme.example"},
        ],
    }
    view = {"candidates": [person, organization]}

    filter_unbound_company_contacts(None, [view])

    assert view["candidates"] == [organization]
    assert organization["organization_relationship"] == "DIRECT"
    assert organization["person_identity_id"] is None
    assert organization["title"] is None
    assert organization["person_organization_relationship"] == "UNKNOWN"
    assert organization["person_project_relationship"] == "UNKNOWN"
    assert organization["public_contacts"] == []
    assert [row["supports"] for row in organization["evidence"]] == ["project_organization"]


def test_unlinked_person_candidate_keeps_only_its_current_project_organization_facet():
    combined = {
        "company_identity_id": None,
        "organization": "Acme LLC",
        "person_name": "Alice Smith",
        "person_identity_id": "unverified-person-id",
        "title": "Project Director",
        "category": "owner_developer",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT",
        "person_project_relationship": "DIRECT",
        "public_contacts": [{"kind": "phone", "value": "(555) 010-0000"}],
        "evidence": [
            {
                "supports": "project_organization",
                "quote": "Acme LLC is the project developer.",
                "current_support": True,
            },
            {
                "supports": "organization_person_role",
                "quote": "Alice Smith is Project Director at Acme LLC.",
                "current_support": True,
            },
            {"supports": "public_contact", "quote": "Phone: (555) 010-0000"},
        ],
    }
    view = {"candidates": [combined]}

    filter_unbound_company_contacts(None, [view])

    assert view["candidates"] == [combined]
    assert combined["person_name"] is None
    assert combined["person_identity_id"] is None
    assert combined["title"] is None
    assert combined["organization_relationship"] == "DIRECT"
    assert combined["person_organization_relationship"] == "UNKNOWN"
    assert combined["person_project_relationship"] == "UNKNOWN"
    assert combined["public_contacts"] == []
    assert [row["supports"] for row in combined["evidence"]] == ["project_organization"]


def test_unlinked_mixed_organization_text_redacts_rejected_person_and_methods():
    person_evidence = {
        "id": "evidence-current-1",
        "current_source_version_id": "evidence-current-1",
        "url": "https://example.test/Alice Smith/contact?email=alice@acme.example",
        "supports": "project_organization",
        "quote": (
            "Acme LLC is the project developer; Alice Smith can be reached at alice@acme.example."
        ),
        "current_support": True,
    }
    contact_evidence = {
        "id": "evidence-current-1",
        "current_source_version_id": "evidence-current-1",
        "url": person_evidence["url"],
        "supports": "permit_listed_contact",
        "quote": "Alice Smith phone (713) 555-0100",
        "current_support": True,
    }
    person = {
        "company_identity_id": None,
        "organization": "Acme LLC",
        "person_name": "Alice Smith",
        "person_identity_id": "unverified-person-id",
        "title": "Project Director",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT",
        "person_project_relationship": "DIRECT",
        "public_contacts": [
            {
                "kind": "email",
                "value": "alice@acme.example",
                "source_url": person_evidence["url"],
                "quote": "Alice Smith email: alice@acme.example",
            }
        ],
        "evidence": [person_evidence, contact_evidence],
    }
    organization = {
        "company_identity_id": None,
        "organization": "Acme LLC",
        "person_name": None,
        "title": "Project Director",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "UNKNOWN",
        "person_project_relationship": "UNKNOWN",
        "public_contacts": [
            {
                "kind": "phone",
                "value": "(713) 555-0100",
                "source_url": person_evidence["url"],
                "quote": "Acme LLC contact (713) 555-0100",
            }
        ],
        "evidence": [
            {
                **person_evidence,
                "quote": (
                    "Acme LLC is the project developer; Alice Smith can be reached at "
                    "alice@acme.example or (713) 555-0100."
                ),
            },
            {
                **person_evidence,
                "supports": "organization_category",
                "quote": ("Acme LLC is the project developer; Public contact: alice@acme.example."),
            },
            contact_evidence,
        ],
    }
    raw_person_quote = person_evidence["quote"]
    raw_org_quote = organization["evidence"][0]["quote"]
    view = {"candidates": [person, organization]}

    filter_unbound_company_contacts(None, [view])

    assert view["candidates"] == [organization]
    assert organization["organization"] == "Acme LLC"
    assert organization["public_contacts"] == []
    assert [row["supports"] for row in organization["evidence"]] == [
        "project_organization",
        "organization_category",
    ]
    category_citation = organization["evidence"][1]
    assert category_citation["current_support"] is True
    assert "[redacted]" in category_citation["quote"]
    projected = repr(organization)
    for token in (
        "Alice Smith",
        "Project Director",
        "alice@acme.example",
        "(713) 555-0100",
        "/Alice Smith/contact",
    ):
        assert token not in projected
    assert "Acme LLC" in projected
    assert person_evidence["quote"] == raw_person_quote
    assert raw_org_quote not in projected
