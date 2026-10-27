import importlib
from uuid import uuid4

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
)
from gridlens.intelligence.project_contact_actions import (
    filter_project_contact_records,
    project_contact_actions,
    project_contact_people,
)

contact_actions_module = importlib.import_module("gridlens.intelligence.project_contact_actions")


def contact(**updates):
    row = {
        "claim_id": "claim-1",
        "company": "Acme",
        "name": None,
        "title": None,
        "role": "owner developer",
        "responsibility": "General company contact path",
        "purchasing_authority": "Requires confirmation for this power package",
        "methods": [],
        "sources": [
            {
                "url": "https://acme.example/contact",
                "verification_status": "Current retained support",
            }
        ],
    }
    row.update(updates)
    return row


def test_official_generic_route_is_contact_action_without_buyer_claim():
    result = project_contact_actions({"contacts": [contact()]})
    assert len(result) == 1
    assert result[0]["kind"] == "contact"
    assert result[0]["href"] == "https://acme.example/contact"
    assert result[0]["purchasing_authority"] == "No buyer authority established"


def test_named_methodless_person_has_no_action():
    row = contact(
        name="Jane Doe", title="Project Director", responsibility="Verified project responsibility"
    )
    assert project_contact_actions({"contacts": [row]}) == []


def test_rejects_unsafe_methods_and_preserves_person_attribution():
    sources = [
        {"url": "https://acme.example/team", "verification_status": "Current retained support"}
    ]
    first = contact(
        name="Jane Doe",
        title="Director",
        responsibility="Verified project responsibility",
        sources=sources,
        methods=[
            {
                "kind": "email",
                "href": "javascript:alert(1)",
                "source_url": "https://acme.example/team",
            }
        ],
    )
    second = contact(
        claim_id="claim-2",
        name="John Roe",
        title="Buyer",
        responsibility="Verified organizational responsibility",
        sources=sources,
        methods=[
            {
                "kind": "email",
                "href": "mailto:john@acme.example",
                "source_url": "https://acme.example/team",
            }
        ],
    )
    result = project_contact_actions({"contacts": [first, second]})
    assert len(result) == 1
    assert result[0]["name"] == "John Roe"
    assert result[0]["claim_id"] == "claim-2"


def test_withheld_suppressed_and_stale_claims_are_not_published():
    rows = [
        contact(suppressed=True),
        contact(claim_id="2", stale=True),
        contact(claim_id="3", withheld=True),
    ]
    assert project_contact_actions({"contacts": rows}) == []


def test_stale_source_claim_cannot_create_action():
    row = contact(
        sources=[
            {
                "url": "https://acme.example/contact",
                "verification_status": "Retained source; assess claim currency",
            }
        ]
    )
    assert project_contact_actions({"contacts": [row]}) == []


def test_eg_ai_rice_owner_phone_stays_generic_and_luis_gets_no_direct_action():
    # Shape from the fetched TDLR TABS2027002808 owner section: the phone is
    # stated under EG AI CORP; LUIS DIAZ is a separate owner contact label.
    source = [
        {
            "url": "https://www.tdlr.texas.gov/TABS/Search/Project/TABS2027002808",
            "title": "TABS project record",
            "verification_status": "Current retained support",
        }
    ]
    company_path = contact(
        company="EG AI CORP",
        methods=[{"kind": "phone", "href": "tel:+12816029714", "source_url": source[0]["url"]}],
        sources=source,
    )
    luis = contact(
        claim_id="luis",
        company="EG AI CORP",
        name="LUIS DIAZ",
        title="Owner Contact",
        responsibility="Verified organizational responsibility",
        sources=source,
    )
    result = project_contact_actions({"contacts": [company_path, luis]})
    assert len(result) == 1
    assert result[0]["kind"] == "call"
    assert result[0]["company"] == "EG AI CORP"
    assert result[0]["name"] is None
    assert result[0]["purchasing_authority"] == "Requires confirmation for this power package"


def test_cached_page_actions_and_people_are_filtered_by_new_suppressions(monkeypatch):
    company_id, person_id = uuid4(), uuid4()
    actions = [
        {
            "kind": "call",
            "href": "tel:+12816029714",
            "company_identity_id": str(company_id),
            "person_identity_id": None,
            "name": None,
        },
        {
            "kind": "email",
            "href": "mailto:luis@example.test",
            "company_identity_id": str(company_id),
            "person_identity_id": str(person_id),
            "name": "LUIS DIAZ",
        },
    ]
    people = [
        {
            "record_type": "contact_person",
            "company_identity_id": str(company_id),
            "person_identity_id": str(person_id),
            "name": "LUIS DIAZ",
        }
    ]
    records = actions + people

    def suppress_only(monkeypatch, keys):
        monkeypatch.setattr(
            contact_actions_module,
            "_ledger_states",
            lambda _session, requested: {key: "suppress" for key in requested & keys},
        )
        return filter_project_contact_records(object(), records)

    # A cached call is removed by a canonical phone ledger key, even though
    # its presentation kind is "call".
    phone_only = suppress_only(
        monkeypatch,
        {("method", global_method_suppression_key("phone", "tel:+12816029714"))},
    )
    assert [record.get("kind") for record in phone_only] == ["email", None]

    email_only = suppress_only(
        monkeypatch,
        {
            (
                "method",
                method_suppression_key(
                    company_id, "LUIS DIAZ", "email", "mailto:luis@example.test"
                ),
            )
        },
    )
    assert [record.get("kind") for record in email_only] == ["call", None]

    person_only = suppress_only(
        monkeypatch,
        {("person", person_suppression_key(company_id, "LUIS DIAZ"))},
    )
    assert [record.get("kind") for record in person_only] == ["call"]

    global_method_only = suppress_only(
        monkeypatch,
        {("method", global_method_suppression_key("email", "mailto:luis@example.test"))},
    )
    assert [record.get("kind") for record in global_method_only] == ["call", None]

    global_person_only = suppress_only(
        monkeypatch,
        {("person", global_person_suppression_key(person_id))},
    )
    assert [record.get("kind") for record in global_person_only] == ["call"]

    company_only = suppress_only(
        monkeypatch,
        {("company", company_suppression_key(company_id))},
    )
    assert company_only == []


def test_named_methodless_professional_is_exposed_separately():
    row = contact(
        name="Jane Doe", title="Project Director", responsibility="Verified project responsibility"
    )
    row["company_identity_id"] = "42a2b0d8-6294-49a2-b919-8d114955f722"
    row["person_identity_id"] = "42a2b0d8-6294-49a2-b919-8d114955f723"
    compact = {"contacts": [row]}
    assert project_contact_actions(compact) == []
    people = project_contact_people(compact)
    assert len(people) == 1
    assert people[0]["name"] == "Jane Doe"
    assert people[0]["title"] == "Project Director"
