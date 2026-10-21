"""Commercial presentation never manufactures accepted facts or contact methods."""

from copy import deepcopy
from uuid import uuid4

import pytest

from gridlens.domain.opportunity_intelligence import (
    assemble_card,
    contact_projection,
    normalize_gap,
)


def item():
    return {
        "id": str(uuid4()),
        "project_id": str(uuid4()),
        "name": "Example project",
        "tier": "Signal",
        "activity": "construction",
        "location": "Dallas, TX",
        "evidence": [
            {
                "id": str(uuid4()),
                "title": "Official permit",
                "url": "https://city.test/p",
                "abstract": "Example project construction",
                "assessment_current": True,
                "content_hash": "a" * 64,
            }
        ],
    }


def test_completeness_never_promotes_or_turns_facility_load_into_power_gap():
    record = item()
    record["reported_power_facts"] = ["200 MW total campus capacity"]
    card = assemble_card(record, {}, {"disposition": "WATCH"}, [], research_enabled=False)
    assert card.qualification == "Signal"
    assert card.power_gap is None
    assert next(f for f in card.fields if f.key == "required_mw").value is None
    assert all(f.status != "Not publicly available" for f in card.research_gaps)
    assert all("disabled" in f.basis for f in card.research_gaps)


def test_failed_research_is_not_proof_information_is_not_public():
    card = assemble_card(
        item(), {}, {}, [{"category": "load", "status": "FAILED"}], research_enabled=True
    )
    field = next(f for f in card.fields if f.key == "required_mw")
    assert field.status == "Research in progress"
    assert "failed" in field.basis
    assert field.value is None


@pytest.mark.parametrize("scalar", [False, True])
def test_official_and_operator_gap_shapes_keep_same_arithmetic_and_provenance(scalar):
    record = item()
    record.update(
        tier="Lead",
        qualification_version="qualified-v1",
        start_window="2027-01-01",
        duration="30 days",
    )
    gap = (
        {
            "suitable_supply_fact_id": "operator-fact",
            "required_mw": "5",
            "available_mw": "2",
            "remaining_mw": "3",
        }
        if scalar
        else {
            "required_mw_min": "4",
            "required_mw_max": "5",
            "available_mw_min": "1",
            "available_mw_max": "2",
            "remaining_mw_min": "2",
            "remaining_mw_max": "4",
            "basis_quote": "Suitable supply covers the entire activity interval.",
        }
    )
    record["qualified_remaining_gap"] = gap
    normalized = normalize_gap(record)
    assert normalized and normalized["duration"] == "30 days"
    assert normalized["remaining_mw_min"] == ("3" if scalar else "2")
    if scalar:
        assert normalized["suitable_supply_fact_id"] == "operator-fact"
    changed = deepcopy(record)
    changed["qualified_remaining_gap"]["remaining_mw_min"] = "99"
    assert normalize_gap(changed) is None
    for tier in ("Signal", "Prospect"):
        assert normalize_gap({**record, "tier": tier}) is None
    assert normalize_gap({**record, "conflict_state": "CONFLICT"}) is None


def party():
    return {
        "id": str(uuid4()),
        "organization": "Example EPC",
        "person_name": "Alex Example",
        "title": "Project manager",
        "category": "epc",
        "organization_relationship": "DIRECT",
        "person_organization_relationship": "DIRECT",
        "person_project_relationship": "DIRECT",
        "evidence": [
            {
                "id": str(uuid4()),
                "current_support": True,
                "supports": "public_contact",
                "url": "https://epc.test/contact",
                "quote": "Business: alex@epc.test",
            }
        ],
        "public_contacts": [
            {
                "kind": "email",
                "value": "alex@epc.test",
                "source_url": "https://epc.test/contact",
                "quote": "Business: alex@epc.test",
            }
        ],
    }


def test_contact_actions_require_exact_current_contact_quote_and_do_not_assert_authority():
    candidate = party()
    contacts = contact_projection({"candidates": [candidate]})
    assert contacts[0].methods[0]["href"] == "mailto:alex@epc.test"
    assert contacts[0].purchasing_authority.startswith("Requires confirmation")
    candidate["public_contacts"][0]["value"] = "invented@epc.test"
    assert contact_projection({"candidates": [candidate]})[0].methods == []
    candidate["evidence"][0]["current_support"] = False
    assert contact_projection({"candidates": [candidate]}) == []


def test_contractor_is_never_customer_and_project_identity_remains_distinct():
    a, b = item(), item()
    chain = {"candidates": [party()]}
    cards = [assemble_card(i, chain, {}, [], research_enabled=True) for i in (a, b)]
    assert cards[0].project_id != cards[1].project_id
    for card in cards:
        assert next(f for f in card.fields if f.key == "customer").value is None
        assert card.contacts[0].company == "Example EPC"


def test_conflicting_dates_never_display_verified_even_with_canonical_value():
    record = item()
    record.update(
        start_window="2027-01-01",
        conflict_state="CONFLICT",
        research_state={"activity_start": {"status": "CONFLICT", "claims": []}},
    )
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    field = next(f for f in card.fields if f.key == "start")
    assert field.value is None and field.status == "Conflicting evidence"


def test_supported_public_load_uses_exact_claim_without_changing_signal_qualification():
    record = item()
    evidence = record["evidence"][0]
    evidence["abstract"] = "Example project construction requires 2 MW."
    record["research_state"] = {
        "activity_load_mw": {
            "status": "SUPPORTED",
            "value": "2",
            "claims": [
                {
                    "evidence_id": evidence["id"],
                    "evidence_hash": evidence["content_hash"],
                    "quote": evidence["abstract"],
                }
            ],
        }
    }
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    field = next(f for f in card.fields if f.key == "required_mw")
    assert field.value == "2 MW (source-reported)"
    assert field.sources[0].passage == evidence["abstract"]
    assert card.qualification == "Signal" and card.power_gap is None
    record["research_state"]["activity_load_mw"]["claims"][0]["evidence_hash"] = "wrong"
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    assert next(f for f in card.fields if f.key == "required_mw").value is None


def test_unrelated_operator_fact_cannot_ground_demand_and_missing_contacts_are_gaps():
    record = item()
    record["required_mw"] = "9 MW"
    record["operator_fact_refs"] = [
        {
            "fact_version_id": str(uuid4()),
            "content_hash": "a" * 64,
            "fact_type": "buyer",
            "value": {"organization": "Buyer"},
        }
    ]
    card = assemble_card(record, {}, {}, [], research_enabled=True)
    assert next(f for f in card.fields if f.key == "required_mw").value is None
    assert {"contact_path", "project_contact"}.issubset({f.key for f in card.research_gaps})


def test_public_chain_document_has_namespaced_reference_without_fake_evidence_fk():
    contact = contact_projection({"candidates": [party()]})[0]
    assert contact.sources[0].reference.startswith("buying-chain:")
    assert contact.sources[0].retained_evidence_id is None


def test_expanded_planning_is_opt_in_and_known_owner_prevents_repeated_identity_research():
    from gridlens.domain.pursuit_research import plan_questions

    card = {
        "disposition": "ACTION NOW",
        "owner_organizations": ["Actual Owner"],
        "organization": "EPC First",
        "organization_role": "epc",
        "facts": [],
        "stage": {"stage": "construction", "evidence_id": "source"},
    }
    assert plan_questions(card) == []
    planned = plan_questions(card, enrich=True)
    assert len(planned) <= 2
    assert all(q["category"] not in {"identity", "suitability"} for q in planned)
    card["owner_organizations"] = []
    assert plan_questions(card, enrich=True)[0]["category"] == "identity"


def test_display_enrichment_preserves_legacy_research_fingerprint():
    from gridlens.domain.commercial_triage import _semantic_card

    legacy = {
        "id": "need",
        "organization": "Owner",
        "operator_fact_refs": [
            {
                "need_id": "need",
                "fact_version_id": "fact",
                "content_hash": "hash",
                "authority": "User-confirmed",
            }
        ],
    }
    enriched = deepcopy(legacy)
    enriched.update(owner_organizations=["Owner"], intelligence_card={"policy_version": "v1"})
    enriched["operator_fact_refs"][0].update(fact_type="demand", value={"mw": "5"})
    assert _semantic_card(enriched) == legacy


def test_rental_intermediary_is_not_recommended_as_customer_contact():
    candidate = party()
    candidate["category"] = "rental_intermediary"
    assert contact_projection({"candidates": [candidate]}) == []
