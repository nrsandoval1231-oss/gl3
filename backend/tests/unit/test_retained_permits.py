from gridlens.ingestion.adapters.retained_permits import chicago_contacts, facts


def test_source_boundary_duplicate_fields_and_unattributed_contacts():
    text = "contact_1_type: OWNER\ncontact_1_name: Alpha LLC\ncontact_1_name: Beta LLC"
    assert chicago_contacts(text) == []
    assert facts("publisher-rss", "Facility: Acme\n" + text) == []
    assert chicago_contacts("contact_1_type: OWNER\ncontact_1_name: DOE, JANE") == []


def test_georgia_facility_is_not_inferred_to_be_owner_or_operator():
    output = facts(
        "georgia-air-draft-title-v",
        "Facility: Campus LLC\nLocation: County, Georgia\n"
        "Application number: 123\nApplication date: 2026-09-01",
    )
    assert len(output) == 4
    assert not any("owner" in fact["label"].lower() for fact in output)


def test_georgia_draft_identity_has_no_agency_people_or_guessed_ownership():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "Official narrative excerpt: Page 1: Jane Official, Director, 404-555-0100\n"
        "Draft identity (page 1): Facility Name: Example Campus LLC Facility Address: "
        "100 Main Road, Augusta, Georgia Mailing Address: 200 Office Road "
        "Facility AIRS Number: 04-13-123-0045 is issued a Permit for the following: "
        "Operation of a data center consisting of emergency generators\n"
    )
    doc = PublicDocument("https://epd.georgia.gov/permits", "Example", text)
    extracted = extract_retained_permit_organizations(doc, "georgia-air-draft-title-v")
    assert len(extracted) == 1
    assert extracted[0].organization == "Example Campus LLC"
    assert extracted[0].category == "permit_entity"
    assert extracted[0].person_name is None
    assert extracted[0].public_contacts == []
    assert extracted[0].citations[0]["quote"] in text
    values = facts("georgia-air-draft-title-v", text)
    assert any(f["value"] == "100 Main Road, Augusta, Georgia" for f in values)
    assert not any("200 Office" in f["value"] for f in values)
    assert facts("publisher-rss", text) == []


def test_named_construction_proponent_not_inferred_from_facility_or_agency_title():
    from gridlens.ingestion.adapters.retained_permits import georgia_proponent

    text = (
        "Page 1: Jeffrey Official, Director. Background Information "
        "QTS Atlanta III, LLC proposes to construct a new data center in Augusta, "
        "Richmond County under the name QTS ATL3 Campus."
    )
    result = georgia_proponent(text)
    assert result is not None and result[0] == "QTS Atlanta III, LLC"
    assert result[1] in text
    assert georgia_proponent(text.replace("proposes", "previously proposed")) is None
    assert georgia_proponent(text.replace("proposes", "does not propose")) is None


def test_austin_permit_people_and_listed_phone_do_not_invent_current_roles():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "contractor_company_name: Prism Electric Inc\n"
        "contractor_trade: Electrical Contractor\ncontractor_full_name: Blake Combs\n"
        "contractor_phone: 5129262000"
    )
    doc = PublicDocument("https://abc.austintexas.gov/permit", "Permit", text)
    rows = extract_retained_permit_organizations(doc, "austin-building-permits")
    organization, person = rows
    assert organization.organization_relationship == "DIRECT"
    assert organization.public_contacts[0]["kind"] == "permit-listed phone"
    assert person.person_name == "Blake Combs"
    assert person.title is None
    assert person.person_organization_relationship == "UNKNOWN"
    assert person.person_project_relationship == "UNKNOWN"
    assert person.public_contacts == []
    assert all(c["quote"] in text for row in rows for c in row.citations)
    assert len(facts("austin-building-permits", text)) == 4
    assert extract_retained_permit_organizations(doc, "publisher-rss") == []
    ambiguous = PublicDocument(doc.url, doc.title, text + "\ncontractor_company_name: Other Inc")
    assert extract_retained_permit_organizations(ambiguous, "austin-building-permits") == []


def test_applicant_affiliation_is_not_direct_project_organization_or_employment():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "applicant_org: Example Consultants\napplicant_full_name: Jane Doe\n"
        "applicant_phone: 5125550100"
    )
    doc = PublicDocument("https://abc.austintexas.gov/permit", "Permit", text)
    organization, person = extract_retained_permit_organizations(doc, "austin-building-permits")
    assert organization.organization_relationship == "UNKNOWN"
    assert organization.category == "unknown"
    assert person.person_organization_relationship == "UNKNOWN"
    assert person.person_project_relationship == "UNKNOWN"
    assert person.public_contacts == []
    assert organization.public_contacts[0]["kind"] == "permit-listed phone"
    assert "business/personal type are UNKNOWN" in organization.reason


def test_applicant_formatting_variant_cannot_retract_direct_contractor():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "contractor_company_name: Prism Electric Inc\n"
        "contractor_full_name: Blake Combs\napplicant_org: PRISM ELECTRIC INC.\n"
        "applicant_full_name: Blake Combs"
    )
    rows = extract_retained_permit_organizations(
        PublicDocument("https://abc.austintexas.gov/permit", "Permit", text),
        "austin-building-permits",
    )
    assert len(rows) == 2
    assert all(row.organization_relationship == "DIRECT" for row in rows)
