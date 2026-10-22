"""Decision boundaries for typed source reports and executable route planning."""

from datetime import date
from uuid import uuid4

import pytest

from gridlens.domain.commercial_presentation import commercial_size_status
from gridlens.domain.commercial_triage import build_card
from gridlens.domain.pursuit_research import blocker_resolved, plan_questions
from gridlens.intelligence.research_routing import routing_context


def field(value, status="SUPPORTED"):
    return {
        "status": status,
        "value": value,
        "claims": [
            {
                "quote": f"Exact project report: {value}",
                "evidence_id": str(uuid4()),
                "evidence_hash": "a" * 64,
                "as_of": "2026-10-04",
                "evidence": {"url": "https://publisher.example/project"},
            }
        ],
    }


def test_cited_construction_never_resolves_commissioning_or_qualifies_load():
    card = {"research_state": {"phase": field("construction_active")}, "required_mw": None}
    assert blocker_resolved("phase", card)
    assert not blocker_resolved("commissioning", card)
    assert not blocker_resolved("load", card)
    assert card["required_mw"] is None


def test_energization_alone_does_not_answer_sufficient_supply_question():
    card = {"research_state": {"permanent_service": field("energized")}}
    assert not blocker_resolved("supply", card)
    card["research_state"]["supply_adequacy"] = field("adequate")
    assert blocker_resolved("supply", card)
    card["research_state"]["supply_adequacy"] = field(None, "CONFLICT")
    assert not blocker_resolved("supply", card)


def test_suitability_components_resolve_independently_and_complete_only_together():
    card = {"research_state": {"voltage": field("480 V, 3 phase")}}
    assert blocker_resolved("voltage", card)
    assert not blocker_resolved("fuel", card)
    assert not blocker_resolved("load_profile", card)
    assert not blocker_resolved("suitability", card)
    card["research_state"]["fuel_availability"] = field("available")
    assert blocker_resolved("fuel", card)
    assert not blocker_resolved("suitability", card)
    card["research_state"]["load_profile"] = field("continuous")
    assert blocker_resolved("suitability", card)
    card["research_state"]["voltage"] = field(None, "CONFLICT")
    assert not blocker_resolved("voltage", card)
    assert not blocker_resolved("suitability", card)


def test_facility_demand_resolves_only_from_its_exact_typed_report():
    card = {"research_state": {"facility_scale_mw": field("196")}}
    assert not blocker_resolved("facility_demand", card)
    card["research_state"]["facility_demand_mw"] = field("12")
    assert blocker_resolved("facility_demand", card)


def test_conflict_resolution_requires_every_original_conflicting_field_supported():
    card = {"research_state": {"phase": field("construction_active")}}
    assert not blocker_resolved("conflict", card)
    assert not blocker_resolved(
        "conflict", card, {"conflict_fields": ["phase", "permanent_service"]}
    )
    assert blocker_resolved("conflict", card, {"conflict_fields": ["phase"]})
    card["research_state"]["phase"] = field(None, "UNKNOWN")
    assert not blocker_resolved("conflict", card, {"conflict_fields": ["phase"]})


def test_reported_exact_load_excludes_answered_question_without_writing_power_need():
    card = {
        "disposition": "RESEARCH",
        "required_mw": None,
        "research_state": {"activity_load_mw": field("0.5")},
        "facts": [{"text": "Temporary power", "evidence_id": "citation"}],
        "stage": {"stage": "construction_active", "evidence_id": "phase"},
        "contacts": [{"kind": "public project phone", "value": "5550100"}],
        "start_window": "2026-11-01",
        "supply": "Unknown",
    }
    assert blocker_resolved("load", card)
    legacy_questions = plan_questions(card)
    expanded_categories = {
        "facility_demand",
        "fuel",
        "voltage",
        "load_profile",
        "procurement",
        "utility_obstacle",
    }
    assert [q["category"] for q in legacy_questions] == ["supply"]
    assert not expanded_categories.intersection(q["category"] for q in legacy_questions)
    assert any(q["category"] == "facility_demand" for q in plan_questions(card, enrich=True))
    assert card["required_mw"] is None


@pytest.mark.parametrize(
    ("phase", "supply", "expected"),
    [
        ("completed", None, "REJECT"),
        ("cancelled", None, "REJECT"),
        ("paused", None, "WATCH"),
        ("construction_active", "adequate", "REJECT"),
    ],
)
def test_supported_adverse_reports_change_commercial_state_without_changing_tier(
    phase, supply, expected
):
    state = {"phase": field(phase)}
    if supply:
        state["supply_adequacy"] = field(supply)
    item = {
        "id": uuid4(),
        "project_id": uuid4(),
        "name": "Synthetic exact project",
        "tier": "Signal",
        "activity": "construction",
        "research_state": state,
        "required_mw": None,
        "evidence": [],
    }
    card = build_card(item, None, date(2026, 10, 4))
    assert card["disposition"] == expected
    assert card["tier"] == "Signal" and card["required_mw"] is None
    assert card["facts"][0]["evidence_id"] == state["phase"]["claims"][0]["evidence_id"]


def test_conflicting_report_does_not_turn_one_adverse_claim_into_rejection():
    item = {
        "id": uuid4(),
        "project_id": uuid4(),
        "tier": "Signal",
        "research_state": {"phase": field(None, "CONFLICT"), "supply_adequacy": field("adequate")},
        "evidence": [],
    }
    assert build_card(item, None, date(2026, 10, 4))["disposition"] == "RESEARCH"


@pytest.mark.parametrize(
    ("quantity", "status"),
    [
        ("299 kW", "below_floor"),
        ("0.299 MW", "below_floor"),
        ("300 kW", "at_or_above_floor"),
        ("0.3 MW", "at_or_above_floor"),
        ("0.1 to 0.299 MW", "below_floor"),
        ("0.3 to 1 MW", "at_or_above_floor"),
        ("0.1 to 0.5 MW", "unknown"),
        ("1 to 0.2 MW", "unknown"),
        ("up to 0.299 MW", "unknown"),
        ("campus 20 MW", "unknown"),
    ],
)
def test_inclusive_floor_uses_exact_supported_units_and_conservative_intervals(quantity, status):
    assert commercial_size_status(quantity, "construction", None, []) == status


def test_routing_fingerprint_changes_with_registry_configuration_and_observes_freshness():
    source = {
        "source_id": "austin-building-permits",
        "external_id": "123",
        "url": "https://example.test/123",
        "family": "construction-permits",
        "retrieval_method": "socrata-permits",
        "definition": {"parser": "v1"},
    }
    first = routing_context("buyer", [source])
    second = routing_context("buyer", [{**source, "definition": {"parser": "v2"}}])
    assert first["selected_source_fingerprint"] != second["selected_source_fingerprint"]
    assert first["freshness_hours"] == 72
    assert first["route_plan"][0]["kind"] == "retained"
    assert first["route_plan"][1]["kind"] == "registered"


def test_rrc_form_download_is_explicitly_unavailable_without_form_submission():
    plan = routing_context(
        "phase",
        [
            {
                "source_id": "texas-rrc-drilling-permits",
                "external_id": "123",
                "url": "https://rrc.texas.gov/record",
                "family": "drilling-permits",
                "retrieval_method": "rrc-drilling-permits",
            }
        ],
    )
    assert plan["route_plan"][1]["status"] == "UNAVAILABLE"
    assert "form" in plan["route_plan"][1]["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "Orion Data Center lists Acme Electric as contractor. "
        "Acme also offers temporary power for customers.",
        "The Orion Data Center construction team is investigating "
        "whether temporary power is needed.",
        "Orion Data Center construction permit lists temporary power as an optional alternative.",
        "Temporary power scope remains to be determined.",
        "Temporary power installation is under consideration.",
        "Historical example of temporary power construction.",
    ],
)
def test_offerings_and_unconfirmed_scope_do_not_resolve_project_requirement(text):
    assert not blocker_resolved("power_need", {"facts": [{"text": text, "evidence_id": "cited"}]})


@pytest.mark.parametrize("current_marker", [None, True, False])
def test_native_conflict_resolution_requires_current_canonical_clearance(current_marker):
    before = {
        "disposition": "RESEARCH",
        "conflict_state": "CONFLICT",
        "qualification_conflict": True,
    }
    planned = plan_questions(before)[0]
    assert planned["category"] == "conflict"
    assert planned["native_qualification_conflict"] is True
    current = {"qualification_conflict": current_marker, "conflict_state": "Not assessed"}
    assert blocker_resolved("conflict", current, planned) is (current_marker is False)
    current["conflict_state"] = "CONFLICT"
    assert not blocker_resolved("conflict", current, planned)


def test_native_clearance_does_not_replace_original_typed_conflict_answers():
    context = {"native_qualification_conflict": True, "conflict_fields": ["phase"]}
    current = {"qualification_conflict": False, "conflict_state": "Not assessed"}
    assert not blocker_resolved("conflict", current, context)
    current["research_state"] = {"phase": field("construction_active")}
    assert blocker_resolved("conflict", current, context)
    assert not blocker_resolved("conflict", current, {"conflict_fields": []})
