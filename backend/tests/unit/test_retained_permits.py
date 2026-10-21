from gridlens.ingestion.adapters.retained_permits import (
    chicago_contacts,
    facts,
    source_native_project_identity,
    source_record_identifier,
)


def test_source_native_project_identity_requires_exact_supported_format_and_quote():
    rrc = "row: 0761171\nlease: HAUG-KIESCHNICK AC UNIT 33\nwell: 1H\n"
    identity = source_native_project_identity("texas-rrc-drilling-permits", rrc)
    assert identity is not None
    assert identity.value == "HAUG-KIESCHNICK AC UNIT 33, well 1H"
    assert identity.quote == "lease: HAUG-KIESCHNICK AC UNIT 33\nwell: 1H"
    assert identity.quote in rrc
    assert (
        source_native_project_identity("publisher-rss", rrc) is None
        and source_native_project_identity("texas-rrc-drilling-permits", "lease: ONLY\n") is None
    )
    assert (
        source_native_project_identity("texas-rrc-drilling-permits", "lease: A\nwell:\nrow: 123\n")
        is None
    )
    assert (
        source_native_project_identity("texas-rrc-drilling-permits", "lease:   \nwell: 1H\n")
        is None
    )

    austin = "description: Work for TXDOT project # 14-0914-04-362R.\n"
    identity = source_native_project_identity("austin-building-permits", austin)
    assert identity is not None
    assert identity.value == "TXDOT project # 14-0914-04-362R"
    assert identity.quote == austin.strip()
    assert source_native_project_identity("austin-building-permits", "TXDOT project # ???") is None


def test_source_record_identifier_is_limited_to_well_formed_supported_rows():
    assert (
        source_record_identifier("texas-rrc-drilling-permits", "row: 0761171\n").value == "0761171"
    )
    assert (
        source_record_identifier("austin-building-permits", "row: 2026-068264 EP\n").value
        == "2026-068264 EP"
    )
    assert source_record_identifier("publisher-rss", "row: 0761171\n") is None
    assert source_record_identifier("austin-building-permits", "row: **bad**\n") is None
    assert source_record_identifier("austin-building-permits", "row:\nlease: A\n") is None
    assert source_record_identifier("austin-building-permits", "row:   \nlease: A\n") is None


def test_source_boundary_duplicate_fields_and_unattributed_contacts():
    text = "contact_1_type: OWNER\ncontact_1_name: Alpha LLC\ncontact_1_name: Beta LLC"
    assert chicago_contacts(text) == []
    assert facts("publisher-rss", "Facility: Acme\n" + text) == []
    assert chicago_contacts("contact_1_type: OWNER\ncontact_1_name: DOE, JANE") == []


def test_boston_facts_keep_native_applicant_label_and_exact_citation():
    text = (
        "Permit number: ETS1895395\n"
        "Work type: Generators\n"
        "Permit type: Electrical\n"
        "Description: Generators Installation of (2) 375KW temporary generator\n"
        "Applicant (buying role unknown): Acme Services\n"
        "Status: Open\n"
        "Address: 1 Main Street\nCity: Boston\nState: MA"
    )
    parsed = facts("boston-building-permits", text)
    applicant = next(item for item in parsed if item["value"] == "Acme Services")
    assert applicant["label"] == "Applicant (role as applicant; buyer authority unknown)"
    assert applicant["quote"] == "Applicant (buying role unknown): Acme Services"
    assert all(item["quote"] in text for item in parsed)
    assert facts("publisher-rss", text) == []
    duplicate_applicant = facts(
        "boston-building-permits",
        text + "\nApplicant (buying role unknown): Different Name",
    )
    assert not any("Applicant" in item["label"] for item in duplicate_applicant)


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


def test_dallas_lp_business_and_contact_person_remain_separate_unknown_roles():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "lp_business_name: Example LP LLC\ncontact_type: Applicant\n"
        "applicant_full_name: Jane Doe\nrow: COM-NEW-26-000157"
    )
    doc = PublicDocument("https://dallascityhall.com/official.xlsx", "Dallas permit", text)
    rows = extract_retained_permit_organizations(doc, "dallas-monthly-permits")
    assert len(rows) == 1
    organization = rows[0]
    assert organization.organization == "Example LP LLC"
    assert organization.organization_relationship == "UNKNOWN"
    assert organization.person_name is None
    assert "separately listed Applicant person" in organization.reason
    assert organization.citations[0]["quote"] in text


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


def test_fort_worth_owner_of_record_is_project_scoped_and_cited_exactly():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    text = (
        "Project: ACS Data Center Phase I Substation\n"
        "Work description: Control House Permit Related to PB26-06650\n"
        "Owner of record: ACS DC HICKS FIELD ROAD LLC"
    )
    rows = extract_retained_permit_organizations(
        PublicDocument("https://data.fortworthtexas.gov/permit", "Permit", text),
        "fort-worth-development-permits",
    )
    assert len(rows) == 1
    assert rows[0].organization == "ACS DC HICKS FIELD ROAD LLC"
    assert rows[0].category == "owner_developer"
    assert rows[0].citations[0]["quote"] == "Owner of record: ACS DC HICKS FIELD ROAD LLC"
    assert "buying authority are UNKNOWN" in rows[0].reason


def test_georgia_owner_pattern_preserves_qts_proponent_and_tadg_owner_roles():
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    qts_text = (
        "Draft identity (page 1): Facility Name: QTS ATL3 Campus Facility Address: "
        "2883 Gordon Highway Augusta, Georgia 30909 Facility AIRS Number: 245-00212 "
        "is issued a Permit for the following: Construction of data center.\n"
        "Background Information QTS Atlanta III, LLC proposes to construct a new data center "
        "in Augusta, Richmond County under the name QTS ATL3 Campus. The proposed data center "
        "will consist of 224 diesel-fired critical emergency generators."
    )
    qts = extract_retained_permit_organizations(
        PublicDocument("https://epd.georgia.gov/permit", "QTS ATL3", qts_text),
        "georgia-air-draft-title-v",
    )
    assert any(
        row.organization == "QTS Atlanta III, LLC" and row.category == "construction_proponent"
        for row in qts
    )
    assert not any(row.category == "owner_developer" for row in qts)

    tadg_text = (
        "Facility Name: TADG – ATL02\n"
        "TA Digital Realty (TADG) – ATL02, which is owned by TA Ellenwood LLC, is a proposed "
        "greenfield facility. The facility will consist of diesel-fired emergency generators."
    )
    tadg = extract_retained_permit_organizations(
        PublicDocument("https://epd.georgia.gov/permit", "TADG ATL02", tadg_text),
        "georgia-air-draft-title-v",
    )
    owner = next(row for row in tadg if row.category == "owner_developer")
    assert owner.organization == "TA Ellenwood LLC"
    assert owner.citations[0]["quote"] == (
        "TA Digital Realty (TADG) – ATL02, which is owned by TA Ellenwood LLC"
    )
