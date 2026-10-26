import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from gridlens.domain.buying_chain import current_role, person_project_relationship
from gridlens.ingestion.adapters.buying_chain_public import (
    PublicDocument,
    PublicPersonCard,
    _public_ip,
    parse_document,
    validate_public_url,
)
from gridlens.intelligence.buying_chain_extraction import (
    Extracted,
    _official_profile,
    document_content_hash,
    document_key,
    extract_organizations,
    extract_people,
    project_document_match,
)
from gridlens.persistence.models import Project

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def project():
    return Project(
        id=uuid4(),
        identity_key="orion",
        name="Orion Data Center",
        location="Austin, TX",
        source_id="test",
        external_id="42",
        identity_facts={},
    )


def doc(text, *, url="https://acme.com/team", published=date(2026, 9, 20), title="Acme team"):
    return PublicDocument(url, title, text, published, NOW)


def people(text, **kwargs):
    return extract_people(
        doc(text, **kwargs),
        [Extracted("Acme", "general_contractor")],
        project(),
        project_scoped=True,
        today=NOW.date(),
    )


def test_no_company_only_project_match():
    assert not project_document_match(project(), doc("Acme is headquartered in Austin, TX."))[0]


@pytest.mark.parametrize(
    "text",
    [
        "Acme is the general contractor for Orion Data Center in Dallas, TX. "
        "Its headquarters are in Austin, TX.",
        "Acme is the general contractor for Orion Data Center in Dallas, TX, "
        "and its headquarters are in Austin, TX.",
        "Acme is the general contractor for Orion Data Center West in Austin, TX.",
        "Acme is the general contractor for Orion Data Center-West in Austin, TX.",
        "Acme is the general contractor for Orion Data Center Phase 2 in Austin, TX.",
    ],
)
def test_wrong_geography_or_sibling_name_cannot_establish_project_relationship(text):
    source = doc(text)
    assert not project_document_match(project(), source)[0]
    assert extract_organizations(source, project()) == []


def test_explicit_wrong_geography_blocks_matching_title():
    source = doc(
        "Acme is the general contractor for Orion Data Center in Dallas, TX.",
        title="Orion Data Center, Austin, TX",
    )
    assert not project_document_match(project(), source)[0]
    assert extract_organizations(source, project()) == []


def test_headquarters_location_cannot_complete_a_project_name_match():
    source = doc(
        "Orion Data Center. Acme is headquartered in Austin, TX.",
        title="Orion Data Center",
    )
    assert not project_document_match(project(), source)[0]


def test_exact_project_with_own_geography_still_matches():
    source = doc("Acme is the general contractor for Orion Data Center in Austin, TX.")
    assert project_document_match(project(), source)[0]
    assert extract_organizations(source, project())[0].organization_relationship == "DIRECT"


def test_exact_declared_project_alias_still_matches():
    selected = project()
    selected.identity_facts = {"project_aliases": ["Orion Campus"]}
    source = doc("Acme is the general contractor for Orion Campus in Austin, TX.")
    assert project_document_match(selected, source)[0]
    assert extract_organizations(source, selected)[0].organization_relationship == "DIRECT"


def test_named_physical_site_remains_sufficient_without_facility_keyword():
    selected = project()
    selected.name = "Orion Expansion"
    selected.location = "123 Main St, Austin, TX"
    source = doc("Orion Expansion at 123 Main St, Austin, TX.")
    assert project_document_match(selected, source)[0]


def test_same_street_cannot_override_conflicting_city():
    selected = project()
    selected.identity_facts = {"site": "123 Main St"}
    source = doc("Orion Data Center at 123 Main St, Dallas, TX.")
    assert not project_document_match(selected, source)[0]


def test_document_identity_matches_retained_hash_and_tracks_metadata():
    source = doc("Identical retained text")
    expected = hashlib.sha256(
        json.dumps(
            {"text": source.text, "title": source.title, "published": source.published_at},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    assert document_content_hash(source) == expected
    assert document_key(source) == source.url + ":" + expected
    assert document_key(replace(source, observed_at=NOW.replace(hour=12))) == document_key(source)
    assert document_key(replace(source, title="Changed title")) != document_key(source)
    assert document_key(replace(source, published_at=None)) != document_key(source)
    assert document_key(replace(source, url="https://acme.com/about")) != document_key(source)


def test_official_mes_person_cards_bind_literal_methods_and_keep_company_identity_separate():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mes_team_person_cards.html"
    source = parse_document(
        "https://www.mesltdtx.com/team",
        fixture.read_bytes(),
        "text/html",
    )
    source = replace(source, observed_at=NOW)
    assert len(source.person_cards) == 3
    assert [(card.name, card.title) for card in source.person_cards] == [
        ("Josh Spaw", "Project Manager"),
        ("Justin Flippin", "Project Manager"),
        ("Christopher Brannon", "Purchasing Manager"),
    ]

    from gridlens.intelligence.company_contact_discovery import (
        _person_card_method_keys,
        _self_identified_company_site,
    )

    organization = Extracted(
        "Masters Electrical Services",
        "electrical_contractor",
        organization_relationship="DIRECT",
    )
    assert _self_identified_company_site(source, organization.organization)
    assert _person_card_method_keys([source]) == {
        (source.url, "email", "jspaw@mesltdtx.com"),
        (source.url, "email", "jflippin@mesltdtx.com"),
        (source.url, "email", "cbrannon@mesltdtx.com"),
    }
    result = extract_people(
        source,
        [organization],
        project(),
        project_scoped=False,
        today=NOW.date(),
        verified_official_roster=True,
    )
    by_name = {item.person_name: item for item in result}
    expected = {
        "Josh Spaw": "jspaw@mesltdtx.com",
        "Justin Flippin": "jflippin@mesltdtx.com",
        "Christopher Brannon": "cbrannon@mesltdtx.com",
    }
    assert set(by_name) == set(expected)
    for name, email in expected.items():
        person = by_name[name]
        assert person.public_contacts == [
            {
                "kind": "email",
                "value": email,
                "source_url": source.url,
                "quote": next(
                    card.contact_text for card in source.person_cards if card.name == name
                ),
                "observed_at": NOW.isoformat(),
            }
        ]
        assert person.person_organization_relationship == "CURRENT"
        assert person.person_project_relationship == "ROLE_SUPPORTED"
        assert person.citations[-1]["quote"] == person.public_contacts[0]["quote"]
        assert person.public_contacts[0]["quote"] in source.text
    assert by_name["Christopher Brannon"].category == "procurement"
    assert all(person.person_project_relationship != "DIRECT" for person in by_name.values())
    assert "info@mesltdtx.com" not in {
        contact["value"] for person in by_name.values() for contact in person.public_contacts
    }


def _one_person_card_html(
    *, href="mailto:jane@example.com", label="Contact Jane by Email", title="Project Manager"
):
    return f"""<!doctype html><html><head><title>Example Corp Team</title></head><body>
    <main><h1>Example Corp Team</h1><div><h3>Jane Doe, {title}</h3>
    <p><a href="{href}">{label}</a></p></div>
    <footer>© 2026 Example Corp. All rights reserved.</footer></main></body></html>"""


@pytest.mark.parametrize(
    ("href", "label"),
    [
        ("mailto:jane@example.com?cc=other@example.com", "Contact Jane by Email"),
        ("mailto:jane@example.com%0d%0abcc:other@example.com", "Contact Jane by Email"),
        ("mailto:jane@example.com,other@example.com", "Contact Jane by Email"),
        ("mailto:jane@example.com", "Contact Alice by Email"),
        ("tel:+15550101010?ext=2", "Contact Jane by Phone"),
    ],
)
def test_person_card_rejects_unsafe_or_conflicting_literal_links(href, label):
    source = parse_document(
        "https://example.com/team",
        _one_person_card_html(href=href, label=label).encode(),
        "text/html",
    )
    assert source.person_cards == ()


def test_person_card_rejects_ambiguous_partial_stale_negated_and_wrong_publisher_cases():
    from gridlens.intelligence.company_contact_discovery import _self_identified_company_site

    base = parse_document(
        "https://example.com/team",
        _one_person_card_html().encode(),
        "text/html",
    )
    organization = Extracted("Example Corp", "electrical_contractor")
    selected_project = project()

    multiple_headings = _one_person_card_html().replace(
        "<h3>Jane Doe, Project Manager</h3>",
        "<h3>Jane Doe, Project Manager</h3><h4>More Staff</h4>",
    )
    multiple_methods = _one_person_card_html().replace(
        "</p></div>",
        '<a href="mailto:alt@example.com">Contact Jane by Email</a></p></div>',
    )
    partial = _one_person_card_html().replace(
        '<a href="mailto:jane@example.com">Contact Jane by Email</a>', "Jane Doe"
    )
    for html in (multiple_headings, multiple_methods, partial):
        assert (
            parse_document("https://example.com/team", html.encode(), "text/html").person_cards
            == ()
        )

    negated = parse_document(
        "https://example.com/team",
        _one_person_card_html(title="Former Project Manager").encode(),
        "text/html",
    )
    assert negated.person_cards
    negated_roles = extract_people(
        negated,
        [organization],
        selected_project,
        project_scoped=False,
        today=NOW.date(),
        verified_official_roster=True,
    )
    assert negated_roles == []

    stale_observation = replace(base, observed_at=NOW - timedelta(days=366))
    stale_publication = replace(base, published_at=date(2024, 1, 1))
    for stale in (stale_observation, stale_publication):
        people = extract_people(
            stale,
            [organization],
            selected_project,
            project_scoped=False,
            today=NOW.date(),
            verified_official_roster=True,
        )
        assert not any(person.public_contacts for person in people)

    unrelated = replace(
        base,
        url="https://directory.example/team",
        title="Directory Services Team",
        text=base.text.replace("© 2026 Example Corp", "© 2026 Directory Services"),
    )
    assert not _self_identified_company_site(unrelated, organization.organization)
    assert (
        extract_people(
            unrelated,
            [organization],
            selected_project,
            project_scoped=False,
            today=NOW.date(),
        )
        == []
    )


def test_person_card_association_is_in_semantic_hash_and_reconstructible_from_marker():
    source = replace(
        parse_document(
            "https://example.com/team",
            _one_person_card_html().encode(),
            "text/html",
        ),
        observed_at=NOW,
    )
    card = source.person_cards[0]
    persisted = PublicDocument(
        source.url,
        source.title,
        source.text,
        source.published_at,
        source.observed_at,
        source.extraction_location,
    )
    assert document_content_hash(source) == document_content_hash(persisted)
    reassigned = replace(
        source,
        person_cards=(
            PublicPersonCard(
                card.heading_text,
                card.contact_text,
                "mailto:other@example.com",
                card.name,
                card.title,
            ),
        ),
    )
    assert reassigned.text == source.text
    assert document_content_hash(reassigned) != document_content_hash(source)
    assert document_content_hash(replace(source, person_cards=())) == document_content_hash(source)
    assert document_content_hash(
        replace(source, person_cards=(), extraction_location="public page text")
    ) != document_content_hash(source)


def test_wrong_project_same_document_and_same_sentence_do_not_assign_organization():
    for text in [
        "Orion Data Center in Austin, TX.\n"
        "Acme is the general contractor for Vega Plant in Dallas.",
        "Acme is the general contractor for Vega Plant, "
        "while BuildCo handles Orion Data Center in Austin, TX.",
    ]:
        assert extract_organizations(doc(text), project()) == []


def test_explicit_organization_relation_and_removal():
    positive = extract_organizations(
        doc("Acme is the general contractor for Orion Data Center."), project()
    )
    assert positive[0].organization == "Acme"
    assert positive[0].organization_relationship == "DIRECT"
    negative = extract_organizations(
        doc("Acme was the general contractor for Orion Data Center, but was removed in June."),
        project(),
    )
    assert negative[0].organization_relationship == "UNKNOWN"


def test_no_longer_working_on_project_keeps_organization_unknown():
    source = doc(
        "Acme was general contractor for Orion Data Center in Austin, TX "
        "but no longer works on this project."
    )
    result = extract_organizations(source, project())
    assert result[0].organization_relationship == "UNKNOWN"
    assert result[0].evidence_strength == "Low"


def test_employment_never_silently_means_direct_assignment():
    result = people("Alice Smith is Project Director at Acme.")
    assert result[0].person_project_relationship == "ROLE_SUPPORTED"
    quoted = people(
        "Alice Smith is Project Director at Acme, and she commented on Orion Data Center "
        "without being assigned to it."
    )
    assert quoted[0].person_project_relationship != "DIRECT"


def test_explicit_individual_assignment_is_direct():
    result = people("Alice Smith is Project Director at Acme, on Orion Data Center.")
    assert result[0].person_project_relationship == "DIRECT"
    assert any(c["supports"] == "person_project_assignment" for c in result[0].citations)


@pytest.mark.parametrize("target", ["Orion Data Center West", "Orion Data Center in Dallas, TX"])
def test_sibling_or_wrong_geography_cannot_assign_person(target):
    result = people(f"Alice Smith is Project Director at Acme, on {target}.")
    assert result[0].person_project_relationship != "DIRECT"
    assert not any(c["supports"] == "person_project_assignment" for c in result[0].citations)


def test_negated_person_role_stays_unknown():
    result = people("Alice Smith is not Project Director at Acme.")
    assert result[0].person_organization_relationship == "UNKNOWN"
    assert result[0].person_project_relationship == "UNKNOWN"


def test_stale_title_keeps_employment_and_assignment_unknown():
    result = people(
        "Alice Smith is Project Director at Acme, on Orion Data Center.", published=date(2023, 1, 1)
    )
    assert result[0].person_organization_relationship == "UNKNOWN"
    assert result[0].person_project_relationship == "UNKNOWN"


def test_official_current_roster_does_not_invent_publication_date():
    source = doc("Alice Smith, President", published=None)
    result = extract_people(
        source,
        [Extracted("Acme", "general_contractor")],
        project(),
        project_scoped=False,
        today=NOW.date(),
    )
    assert result[0].person_organization_relationship == "CURRENT"
    assert result[0].person_project_relationship == "ROLE_SUPPORTED"
    assert source.published_at is None


@pytest.mark.parametrize(
    ("title", "heading"),
    [("Acme leadership", "Former leadership"), ("Acme retired leadership", "Leadership")],
)
def test_historical_leadership_context_cannot_become_current_roster(title, heading):
    source = doc(
        heading + "\nAlice Smith, President",
        url="https://acme.com/leadership",
        title=title,
        published=None,
    )
    assert not _official_profile(source, "Acme")
    assert (
        extract_people(
            source,
            [Extracted("Acme", "general_contractor")],
            project(),
            project_scoped=False,
            today=NOW.date(),
        )
        == []
    )


@pytest.mark.parametrize("organization", ["Gurtz Electric Co.", "GURTZ ELECTRIC COMPANY"])
def test_official_biography_heading_does_not_join_name_or_split_title_at_of(organization):
    source = doc(
        "Construction Operations\nDavid Steffenhagen serves as Director of Construction Operations "
        "at Gurtz Electric Co., overseeing electrical and low voltage construction operations, "
        "preconstruction, prefabrication and manufacturing across the company’s growing "
        "portfolio of projects.",
        url="https://gurtzelectric.com/david-steffenhagen/",
        title="David Steffenhagen – Gurtz Electric Co.",
        published=None,
    )
    assert _official_profile(source, organization)
    result = extract_people(
        source,
        [Extracted(organization, "electrical_contractor")],
        project(),
        project_scoped=False,
        today=NOW.date(),
    )
    assert len(result) == 1
    assert result[0].person_name == "David Steffenhagen"
    assert result[0].title == "Director of Construction Operations"
    assert result[0].person_organization_relationship == "CURRENT"
    assert result[0].person_project_relationship == "ROLE_SUPPORTED"


def test_legal_suffix_alias_preserves_assignment_and_rejects_other_employers():
    result = people("Alice Smith is Project Director at Acme, Inc., on Orion Data Center.")
    assert result[0].person_project_relationship == "DIRECT"
    assert people("Alice Smith is Project Director at Acme Builders.") == []


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.evil.example/team",
        "https://acme.com/archive",
        "https://acme.com/news/old",
        "https://directory.com/acme",
    ],
)
def test_fake_or_archive_roster_is_not_current(url):
    assert not _official_profile(doc("Alice Smith, President", url=url, published=None), "Acme")


def test_undated_biography_without_official_identity_stays_unknown():
    assert (
        people(
            "Alice Smith is Project Director at Acme.",
            url="https://directory.example/alice",
            published=None,
        )[0].person_project_relationship
        == "UNKNOWN"
    )


def test_another_person_email_is_not_assigned():
    result = people(
        "Alice Smith is Project Director at Acme; "
        "for inquiries contact Bob Jones at bob@acme.example"
    )
    assert result[0].public_contacts == []


@pytest.mark.parametrize(
    ("statement", "kind", "value"),
    [
        ("Alice Smith email: alice@acme.example", "email", "alice@acme.example"),
        ("Alice Smith can be reached at alice@acme.example.", "email", "alice@acme.example"),
        ("Alice Smith can be reached at +1 (312) 555-0123.", "phone", "+1 (312) 555-0123"),
    ],
)
def test_exact_named_public_business_contact_has_retained_provenance(statement, kind, value):
    result = people("Alice Smith is Project Director at Acme.\n" + statement)
    assert result[0].public_contacts == [
        {
            "kind": kind,
            "value": value,
            "source_url": "https://acme.com/team",
            "quote": statement,
            "observed_at": NOW.isoformat(),
        }
    ]
    assert any(c["supports"] == "public_contact" for c in result[0].citations)


@pytest.mark.parametrize(
    "statement",
    [
        "Bob Jones email: bob@acme.example",
        "Bob Jones can be reached at +1 (312) 555-0123.",
        "Alice Smith\nemail: alice@acme.example",
        "Contact: info@acme.example",
        "Alice Smith can be reached at Bob Jones email: bob@acme.example",
        "Alice Smith cannot be reached at alice@acme.example",
    ],
)
def test_unattributed_or_other_person_contact_is_not_attached(statement):
    result = people("Alice Smith is Project Director at Acme.\n" + statement)
    assert result[0].public_contacts == []


def test_oil_gas_asset_specific_role_is_preserved():
    result = extract_people(
        doc("Alice Smith is Drilling Operations Manager at Acme."),
        [Extracted("Acme", "asset_operator")],
        project(),
        project_scoped=False,
        today=NOW.date(),
    )
    assert result[0].category == "field_operations"
    assert result[0].person_project_relationship == "ROLE_SUPPORTED"


def test_structured_chicago_requires_official_origin_exact_record_and_site():
    p = Project(
        id=uuid4(),
        name="Chicago permit 42",
        source_id="chicago-building-permits",
        external_id="42",
        location="333 E HURON ST, Chicago, IL",
        identity_facts={},
    )
    raw = (
        b'[{"id":"42","street_number":"333","street_direction":"E",'
        b'"street_name":"HURON ST","issue_date":"2026-09-01"}]'
    )
    official = parse_document(
        "https://data.cityofchicago.org/resource/ydr8-5enu.json", raw, "application/json"
    )
    assert project_document_match(p, official)[0]
    assert official.published_at is None
    spoof = parse_document("https://arbitrary.example/claim", raw, "application/json")
    assert not project_document_match(p, spoof)[0]
    p.external_id = "43"
    assert not project_document_match(p, official)[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://user:pass@example.com/",
        "https://example.com:444/",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_dns_mixed_public_private_rejected(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("8.8.8.8", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError):
        _public_ip("public.example")


def test_relationship_policy_requires_current_role_and_org_link():
    assert not current_role(None, NOW.date())
    assert (
        person_project_relationship(
            organization_direct=False, current_role=True, relevant_role=True, direct_assignment=True
        )
        == "UNKNOWN"
    )


def test_exact_permit_id_does_not_override_conflicting_street_number_prefix():
    p = Project(
        id=uuid4(),
        name="Chicago permit 42",
        source_id="chicago-building-permits",
        external_id="42",
        location="3333 E HURON ST, Chicago, IL",
        identity_facts={},
    )
    source = parse_document(
        "https://data.cityofchicago.org/resource/ydr8-5enu.json",
        b'[{"id":"42","street_number":"333","street_direction":"E","street_name":"HURON ST"}]',
        "application/json",
    )
    assert not project_document_match(p, source)[0]


def test_permit_name_is_not_role_conflict_or_another_persons_evidence():
    from gridlens.intelligence.buying_chain import _deduplicate
    from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

    permit = doc(
        "contractor_company_name: Acme\ncontractor_trade: General Contractor\n"
        "contractor_full_name: Blake Combs"
    )
    parties = extract_retained_permit_organizations(permit, "austin-building-permits")
    team = doc(
        "Blake Combs serves as Project Manager at Acme.\n"
        "Alice Smith serves as Project Manager at Acme."
    )
    roles = extract_people(team, parties, project(), project_scoped=False, today=NOW.date())
    assert len(roles) == 2
    assert all(not any(c["supports"] == "permit_listed_person" for c in p.citations) for p in roles)
    for order in ([*parties, *roles], [*roles, *parties]):
        people_rows = [p for p in _deduplicate(order) if p.person_name]
        assert len(people_rows) == 2
        assert all(p.person_organization_relationship == "CURRENT" for p in people_rows)
        assert all(p.person_project_relationship == "ROLE_SUPPORTED" for p in people_rows)
