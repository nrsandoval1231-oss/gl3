from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import document_content_hash
from gridlens.intelligence.company_contact_attribution import (
    _exact_houston_project_contact,
    _fact_matches_method,
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
