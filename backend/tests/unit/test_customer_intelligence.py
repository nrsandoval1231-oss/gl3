"""Source extraction and conservative portfolio resolution, independent of persistence."""

from copy import deepcopy
from datetime import date

from gridlens.domain.customer_intelligence import (
    extract_customer_facts,
    resolve_customer_intelligence,
)

TODAY = date(2026, 11, 12)
SOURCE = {
    "url": "https://owner.example/announcement",
    "evidence_id": "e1",
    "content_hash": "a" * 64,
    "published_at": "2026-10-01",
    "observed_at": "2026-11-12T00:00:00Z",
    "authority": "primary",
    "verification_status": "verified",
}


def extracted(text, project="p1", source=None):
    return extract_customer_facts(text, project_id=project, source=source or SOURCE)


def resolved(*packages):
    grouped = {}
    for package in packages:
        grouped.setdefault(package["project_id"], []).append(package)
    return resolve_customer_intelligence(
        [{"project_id": key, "facts": value} for key, value in grouped.items()], as_of=TODAY
    )


def test_explicit_capacity_types_and_exact_source_are_preserved():
    text = (
        "The campus development capacity is 1.2 GW. IT load is 600 MW. "
        "Utility service capacity is 800 MW."
    )
    facts = extracted(text)
    assert facts["version"] == "customer-facts-v1"
    assert [(c["capacity_type"], c["value_mw"]) for c in facts["capacity_claims"]] == [
        ("campus_development", "1200"),
        ("it_load", "600"),
        ("utility_service", "800"),
    ]
    assert all(c["quote"] in text and c["source"] == SOURCE for c in facts["capacity_claims"])
    assert facts["commissioning_inputs"] == []


def test_generic_project_or_temporary_power_does_not_become_build_capacity():
    assert (
        extracted("A 400 MW project needs 10 MW of bridge power. Temporary power: 8 MW.")[
            "capacity_claims"
        ]
        == []
    )


def test_negated_hypothetical_and_invalid_capacities_are_not_positive_facts():
    for text in (
        "The IT load is not 100 MW.",
        "The campus could support 200 MW.",
        "IT load: -20 MW.",
    ):
        assert extracted(text)["capacity_claims"] == []


def test_different_capacity_bases_are_never_added_together():
    result = resolved(extracted("IT load is 80 MW. Utility service capacity is 100 MW."))
    assert {t["basis"]: t["value_mw"] for t in result["capacity"]["totals"]} == {
        "it_load": "80",
        "utility_service": "100",
    }
    assert result["capacity"]["total_mw"] is None


def test_same_scope_syndicated_announcements_count_once():
    a = extracted("IT load is 80 MW.")
    b = extracted(
        "IT load is 80 MW.",
        source={**SOURCE, "evidence_id": "e2", "url": "https://news.example/reprint"},
    )
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] == "80"


def test_verified_primary_is_not_overwritten_by_newer_weaker_article():
    a = extracted("IT load is 80 MW.")
    b = extracted(
        "IT load is 160 MW.",
        source={
            **SOURCE,
            "evidence_id": "e2",
            "authority": "secondary",
            "verification_status": "reported",
            "published_at": "2026-11-11",
        },
    )
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] == "80"
    assert result["capacity"]["superseded_claim_ids"]


def test_equal_authority_conflict_is_not_resolved_by_observation_time():
    a = extracted("IT load is 80 MW.")
    b = extracted(
        "IT load is 160 MW.",
        source={**SOURCE, "evidence_id": "e2", "observed_at": "2026-11-12T01:00:00Z"},
    )
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] is None
    assert result["capacity"]["status"] == "conflict"


def test_explicit_later_revision_preserves_superseded_claim():
    a = extracted("IT load is 80 MW.")
    b = extracted(
        "Revised IT load is 160 MW.",
        source={**SOURCE, "evidence_id": "e2", "published_at": "2026-11-01"},
    )
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] == "160"
    assert result["capacity"]["superseded_claim_ids"] == [a["capacity_claims"][0]["fact_id"]]


def test_unknown_project_overlap_abstains_instead_of_summing():
    result = resolved(extracted("IT load is 80 MW.", "p1"), extracted("IT load is 160 MW.", "p2"))
    total = result["capacity"]["totals"][0]
    assert total["value_mw"] is None
    assert total["status"] == "unknown_overlap"


def test_explicit_disjoint_scopes_can_be_summed():
    a, b = extracted("IT load is 80 MW.", "p1"), extracted("IT load is 160 MW.", "p2")
    a["capacity_claims"][0]["disjoint_scope_ids"] = ["p2:site"]
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] == "240"


def test_campus_includes_phase_and_is_not_added_to_it():
    a = extracted("IT load is 200 MW.")
    b = deepcopy(a)
    b["capacity_claims"][0].update(
        fact_id="phase1",
        scope_id="p1:phase:1",
        phase_id="1",
        value_mw="50",
        capacity_type="individual_phase",
    )
    a["capacity_claims"][0]["includes_scope_ids"] = ["p1:phase:1"]
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["value_mw"] == "200"
    assert result["capacity"]["excluded_claim_ids"] == ["phase1"]


def test_quarter_year_month_and_actual_dates_keep_precision():
    facts = extracted(
        "Construction is expected to start in Q3 2027. First energization is expected in 2028. "
        "Full operations are targeted for March 2029. Construction began on 2026-10-02."
    )
    assert [(c["event_type"], c["label"], c["precision"]) for c in facts["timeline_claims"]] == [
        ("announced_construction_start", "Q3 2027", "quarter"),
        ("expected_first_energization", "2028", "year"),
        ("full_operational_target", "March 2029", "month"),
        ("actual_construction_start", "2026-10-02", "day"),
    ]
    result = resolved(facts)
    assert result["timelines"]["construction_start"]["label"] == "2026-10-02"
    assert result["timelines"]["expected_energization"]["label"] == "2028"


def test_operational_target_and_permit_dates_do_not_become_energization():
    result = resolved(
        extracted("Permit issued on 2026-09-01. Full operations are targeted for 2028.")
    )
    assert result["timelines"]["expected_energization"] is None
    assert result["timelines"]["construction_start"] is None


def test_project_mismatch_stale_and_source_less_facts_are_withheld():
    p = extracted("IT load is 100 MW.")
    p["capacity_claims"][0]["project_id"] = "other"
    assert resolved(p)["capacity"]["total_mw"] is None
    for source in ({"url": ""}, {**SOURCE, "current": False}):
        assert (
            resolved(extracted("IT load is 100 MW.", source=source))["capacity"]["total_mw"] is None
        )


def test_missing_values_remain_unknown_and_priority_explains_confidence():
    result = resolved(extracted("Plans have been announced."))
    assert result["capacity"]["status"] == "insufficient_data"
    assert result["capacity"]["total_mw"] is None
    assert result["priority"]["confidence"] == 0
    assert "research" in result["recommended_next_action"].lower()
    assert result["priority"]["components"]


def test_unverified_large_project_cannot_automatically_outrank_verified_actionable():
    large = resolved(
        extracted(
            "IT load is 1000 MW.",
            source={**SOURCE, "authority": "secondary", "verification_status": "unverified"},
        )
    )
    small = resolved(extracted("IT load is 80 MW. Construction is expected to start in Q1 2027."))
    assert small["priority"]["score"] > large["priority"]["score"]


def test_result_is_deterministic_and_json_friendly():
    import json

    a = extracted("IT load is 80 MW. Construction begins in Q1 2027.")
    b = extracted("Utility service capacity is 100 MW.")
    assert resolved(a, b) == resolved(b, a)
    json.dumps(resolved(a, b))


def test_capacity_qualifiers_are_not_converted_to_exact_total():
    result = resolved(extracted("IT load is up to 100 MW."))
    assert result["capacity"]["total_mw"] is None
    assert result["capacity"]["totals"][0]["status"] == "upper_bound"
    approximate = resolved(extracted("IT load is approximately 80 MW."))
    assert approximate["capacity"]["totals"][0]["qualifier"] == "approximate"


def test_alternatives_and_ranges_are_not_extracted_as_exact_points():
    for text in (
        "IT load is 80 MW or 100 MW.",
        "IT load is 80 MW to 100 MW.",
        "IT load is between 80 MW and 100 MW.",
        "IT load is at least 80 MW.",
    ):
        assert extracted(text)["capacity_claims"] == []


def test_contradictory_inclusion_cannot_hide_a_larger_phase():
    campus = extracted("IT load is 20 MW.")
    phase = deepcopy(campus)
    phase["capacity_claims"][0].update(
        fact_id="phase", scope_id="p1:phase:1", value_mw="50", capacity_type="individual_phase"
    )
    campus["capacity_claims"][0]["includes_scope_ids"] = ["p1:phase:1"]
    result = resolved(campus, phase)
    assert result["capacity"]["totals"][0]["status"] == "conflict"
    assert result["capacity"]["totals"][0]["value_mw"] is None


def test_partial_capacity_is_explicitly_not_a_company_total():
    a = extracted("IT load is 80 MW.", "p1")
    b = extracted("Timing remains unknown.", "p2")
    result = resolved(a, b)
    assert result["capacity"]["total_mw"] is None
    assert result["capacity"]["totals"][0]["value_mw"] == "80"
    assert result["capacity"]["totals"][0]["complete"] is False
    assert result["capacity"]["coverage"] == {"projects_with_capacity": 1, "projects_total": 2}


def test_future_source_and_invalid_actual_date_are_withheld():
    future = extracted("IT load is 100 MW.", source={**SOURCE, "published_at": "2027-01-01"})
    assert resolved(future)["capacity"]["total_mw"] is None
    assert (
        resolved(extracted("Construction began on 2027-01-01."))["timelines"]["construction_start"]
        is None
    )
    assert extracted("Construction began on 2026-02-30.")["timeline_claims"] == []


def test_phase_scope_is_retained_without_claiming_campus_capacity():
    facts = extracted(
        "Phase 2 IT load is 50 MW. Phase 2 first energization is expected in Q2 2028."
    )
    claim = facts["capacity_claims"][0]
    assert (claim["capacity_type"], claim["basis"], claim["scope_id"]) == (
        "individual_phase",
        "it_load",
        "p1:phase:2",
    )
    assert facts["timeline_claims"][0]["event_type"] == "phase_energization"


def test_resolver_does_not_mutate_source_packages():
    facts = extracted("IT load is 100 MW.")
    original = deepcopy(facts)
    resolved(facts)
    assert facts == original


def commissioning_package(project):
    package = extracted("IT load is 100 MW.", project)
    ref = {
        "project_id": project,
        "url": "https://owner.example/test-plan",
        "verification_status": "verified",
    }
    package["commissioning_inputs"] = [
        {
            "project_id": project,
            "block_id": "block-1",
            "load_scope_id": "load-1",
            "sequence_stage": "test-1",
            "rating": "2",
            "unit": "MW",
            "rating_basis": "electrical_input",
            "installed_units": 4,
            "concurrent_units": 2,
            "test_fraction": "0.75",
            "evidence": {"rating": [ref], "test_fraction": [ref], "sequence": [ref]},
        }
    ]
    return package


def test_supported_commissioning_plan_is_calculated_and_not_rental_demand():
    result = resolved(commissioning_package("p1"))
    assert result["commissioning"]["status"] == "estimated"
    assert result["commissioning"]["base_mw"] == "3"
    assert "not verified customer demand" in " ".join(result["commissioning"]["limitations"])


def test_multi_project_commissioning_peaks_are_not_summed():
    result = resolved(commissioning_package("p1"), commissioning_package("p2"))
    assert result["commissioning"]["status"] == "insufficient_data"
    assert result["commissioning"]["base_mw"] is None
    assert len(result["commissioning"]["projects"]) == 2


def test_wrong_project_commissioning_plan_is_withheld():
    package = commissioning_package("p1")
    package["commissioning_inputs"][0]["project_id"] = "p2"
    assert resolved(package)["commissioning"]["status"] == "insufficient_data"


def test_overflow_does_not_publish_a_partial_total_or_timeline():
    a = extracted("IT load is 80 MW. Construction starts in 2027.")
    b = {
        "version": "customer-facts-v1",
        "project_id": "p1",
        "overflow": True,
        "limitations": ["too many source claims"],
    }
    result = resolved(a, b)
    assert result["capacity"]["total_mw"] is None
    assert result["capacity"]["status"] == "insufficient_data"
    assert result["timelines"]["construction_start"] is None
    assert "too many source claims" in result["limitations"]


def test_only_phase_capacity_cannot_claim_full_company_total():
    result = resolved(extracted("Phase 1 IT load is 50 MW."))
    assert result["capacity"]["totals"][0]["complete"] is False
    assert result["capacity"]["total_mw"] is None


def test_upper_bound_and_exact_same_number_remain_distinct_assertions():
    a = extracted("IT load is up to 100 MW.")
    b = extracted("IT load is 100 MW.", source={**SOURCE, "evidence_id": "e2"})
    result = resolved(a, b)
    assert result["capacity"]["totals"][0]["status"] == "conflict"
    assert result["capacity"]["total_mw"] is None


def test_real_campus_phrasing_supports_units_and_does_not_infer_it_load():
    # Vantage Frontier owner announcement, August 19 2025.
    facts = extracted(
        "Vantage Data Centers announced its largest investment to date of over $25 billion "
        "to develop a mega-scale 1.4GW data center campus in Shackelford County, Texas."
    )
    assert [(c["basis"], c["value_mw"]) for c in facts["capacity_claims"]] == [
        ("campus_development", "1400")
    ]


def test_real_critical_it_load_does_not_add_lease_and_option_allocations():
    # Applied Digital Ellendale lease announcement, June 2 2025.
    facts = extracted(
        "Applied Digital will deliver 250 megawatts (MW) of critical IT load "
        "under lease agreements. "
        "CoreWeave retains the option to access an additional 150 MW of critical IT load. "
        "Applied Digital’s Ellendale campus is designed to host 400 MW of critical IT load."
    )
    assert [(c["basis"], c["value_mw"]) for c in facts["capacity_claims"]] == [("it_load", "400")]


def test_real_utility_supply_does_not_become_campus_or_it_load():
    # Mississippi Development Authority, Compass Meridian, January 9 2025.
    facts = extracted(
        "Mississippi Power will supply approximately 500 megawatts of power to the facility."
    )
    assert [(c["basis"], c["value_mw"], c["qualifier"]) for c in facts["capacity_claims"]] == [
        ("utility_service", "500", "approximate")
    ]


def test_offsite_renewable_project_is_not_a_data_center_capacity():
    # Microsoft Wisconsin update: the solar project supports renewable matching.
    assert (
        extracted(
            "This includes a new 250 MW solar project in Portage County that is under "
            "construction to support this commitment."
        )["capacity_claims"]
        == []
    )


def test_real_gross_campus_and_initial_building_are_not_confused():
    # QTS Hillsboro announcement, February 18 2020.
    facts = extracted(
        "The initial development will feature construction of a data center and "
        "27 megawatts of gross power capacity. "
        "The site can ultimately support five mega data centers and more than "
        "250 megawatts of gross power capacity."
    )
    claims = facts["capacity_claims"]
    assert {c["value_mw"] for c in claims} == {"27", "250"}
    assert all(c["basis"] == "campus_development" for c in claims)
    assert next(c for c in claims if c["value_mw"] == "250")["qualifier"] == "more_than"
    assert resolved(facts)["capacity"]["total_mw"] is None


def test_real_construction_sentence_preserves_source_month():
    # Crusoe Abilene announcement, March 18 2025.
    facts = extracted("Crusoe began constructing the AI data center in Abilene in June 2024.")
    claim = facts["timeline_claims"][0]
    assert (claim["event_type"], claim["label"], claim["precision"]) == (
        "actual_construction_start",
        "June 2024",
        "month",
    )


def test_common_future_construction_and_energization_language_preserves_precision():
    facts = extracted(
        "Construction will begin in Q2 2027. "
        "The initial phase is expected to be energized in the first half of 2028."
    )
    assert [(c["event_type"], c["precision"]) for c in facts["timeline_claims"]] == [
        ("announced_construction_start", "quarter"),
        ("phase_energization", "half_year"),
    ]
    assert facts["timeline_claims"][1]["label"] == "first half of 2028"


def test_real_total_power_capacity_is_distinct_from_global_company_footprint():
    facts = extracted(
        "The second phase includes six additional buildings, bringing the total facility "
        "to eight buildings and a total power capacity of 1.2 gigawatts (GW). "
        "Crusoe's total data center footprint will reach more than 1.6 GW under operations "
        "and construction with a pipeline exceeding 10 GW in development."
    )
    assert [(c["basis"], c["value_mw"]) for c in facts["capacity_claims"]] == [
        ("campus_development", "1200")
    ]


def test_parser_overflow_is_explicit_and_never_partial():
    facts = extracted("IT load is 100 MW. " + "a" * 200_000)
    assert facts["overflow"] is True
    assert resolved(facts)["capacity"]["total_mw"] is None


def test_adversarial_range_lower_bound_and_date_alternatives_never_become_exact():
    assert extracted("Orion has 100 to 200 MW of IT load.")["capacity_claims"] == []
    lower = extracted("Orion has more than 100 MW of IT load.")["capacity_claims"][0]
    assert lower["qualifier"] == "more_than"
    for text in (
        "Orion construction is expected to start in 2027 or 2028.",
        "Orion first energization is expected in 2027-2028.",
    ):
        assert extracted(text)["timeline_claims"] == []


def test_site_construction_before_phase_event_is_not_assigned_to_phase():
    claims = extracted(
        "Orion construction starts in 2027 and Phase 2 first energization is expected in 2028."
    )["timeline_claims"]
    assert [(c["event_type"], c["scope_id"]) for c in claims] == [
        ("announced_construction_start", "p1:site"),
        ("phase_energization", "p1:phase:2"),
    ]


def test_real_phase_it_total_keeps_inclusion_evidence_and_utility_separate():
    # DataBank Red Oak campus owner announcement.
    facts = extracted(
        "The Phase 1 design of the site will feature 4 buildings and a 400MW sub-station "
        "from Oncor that can deliver up to 240MW of critical IT power with the ability "
        "to increase this in Phase 2 for a total of 480MW across all 8 buildings."
    )
    total = next(c for c in facts["capacity_claims"] if c["value_mw"] == "480")
    assert (total["basis"], total["scope_id"]) == ("it_load", "p1:site")
    assert total["includes_scope_ids"] == ["p1:phase:1", "p1:phase:2"]
    it_total = next(t for t in resolved(facts)["capacity"]["totals"] if t["basis"] == "it_load")
    assert it_total["value_mw"] == "480"


def test_real_power_agreement_is_service_capacity_not_it():
    # Calpine/CyrusOne Bosque announcement, July 30 2025.
    facts = extracted(
        "Calpine announced a new 190-megawatt (MW) agreement with CyrusOne, a leading "
        "global data center developer and operator, to serve a new data center "
        "adjacent to the Thad Hill Energy Center in Bosque County, Texas."
    )
    assert [(c["basis"], c["value_mw"]) for c in facts["capacity_claims"]] == [
        ("utility_service", "190")
    ]


def test_ready_for_service_is_preserved_but_never_assumed_first_energization():
    facts = extracted("The site has an initial Ready for Service date of Q2-2026.")
    claim = facts["timeline_claims"][0]
    assert (claim["event_type"], claim["label"], claim["precision"]) == (
        "ready_for_service",
        "Q2-2026",
        "quarter",
    )
    assert resolved(facts)["timelines"]["expected_energization"] is None


def test_explicit_operational_target_is_not_electrical_energization():
    facts = extracted(
        "The facility is currently under construction and expected to be operational "
        "by the fourth quarter of 2026."
    )
    assert facts["timeline_claims"][0]["event_type"] == "operational_target"
    assert resolved(facts)["timelines"]["expected_energization"] is None


def test_approximate_year_part_label_is_never_promoted_to_exact_month_or_day():
    facts = extracted("Construction commenced in early 2024.")
    claim = facts["timeline_claims"][0]
    assert (claim["label"], claim["precision"]) == ("early 2024", "approximate_year")
    assert claim["start"] == "2024-01-01"
    assert claim["end"] == "2024-12-31"


def test_named_initial_phase_keeps_literal_scope_without_inventing_phase_number():
    facts = extracted("The initial phase is expected to be energized in the first half of 2025.")
    claim = facts["timeline_claims"][0]
    assert claim["scope_id"] == "p1:phase:initial"
    assert claim["event_type"] == "phase_energization"


def test_historical_acquisition_comparisons_do_not_become_target_project_capacity():
    facts = extracted(
        "This announcement follows its acquisition of a 120MW campus in Atlanta "
        "and a 192MW campus in Northern Virginia."
    )
    assert facts["capacity_claims"] == []


def test_lower_bound_total_preserves_qualifier_and_never_claims_exact_total():
    result = resolved(extracted("IT load is more than 100 MW."))
    total = result["capacity"]["totals"][0]
    assert total["status"] == "lower_bound"
    assert total["qualifier"] == "more_than"
    assert result["capacity"]["total_mw"] is None


def test_inclusion_conflict_sets_top_level_conflict_state():
    a = extracted("IT load is 20 MW.")
    b = deepcopy(a)
    b["capacity_claims"][0].update(fact_id="phase", scope_id="p1:phase:1", value_mw="50")
    a["capacity_claims"][0]["includes_scope_ids"] = ["p1:phase:1"]
    assert resolved(a, b)["capacity"]["status"] == "conflict"


def test_disjoint_upper_and_lower_bounds_cannot_form_a_bounded_portfolio_sum():
    a = extracted("IT load is up to 100 MW.", "p1")
    b = extracted("IT load is more than 200 MW.", "p2")
    a["capacity_claims"][0]["disjoint_scope_ids"] = ["p2:site"]
    total = resolved(a, b)["capacity"]["totals"][0]
    assert total["status"] == "mixed_bounds"
    assert total["value_mw"] is None
    assert total["complete"] is False


def test_operational_deadline_is_distinct_from_an_event_within_the_year():
    deadline = extracted("The facility is expected to be operational by 2027.")
    within = extracted("The facility is expected to be operational in 2027.")
    a, b = deadline["timeline_claims"][0], within["timeline_claims"][0]
    assert a["qualifier"] == "deadline"
    assert a["display_label"] == "by 2027"
    assert a["earliest"] is None
    assert a["latest"] == "2027-12-31"
    assert b["qualifier"] == "within"
    assert b["display_label"] == "2027"
    assert resolved(deadline, within)["timelines"]["conflicts"]
