from gridlens.domain.news_interpretation import (
    EVALUATOR_VERSION,
    assess_news,
    prospect_power_activity,
    signal_power_activity,
)


def test_retained_sample_signals_are_generic_physical_us_events() -> None:
    cases = [
        (
            "Applied Digital reveals $3.2bn Delta Forge 2 AI data center will be built in Alabama",
            "Operations could start by 2028",
            "Alabama",
        ),
        (
            "Hanwha Defense to establish $2.2B manufacturing campus in Arkansas",
            "The subsidiary will produce propellant charges on the U.S. Army's Pine Bluff "
            "Arsenal installation.",
            "Arkansas",
        ),
        (
            "Eli Lilly breaks ground on $6.5B Houston manufacturing plant",
            "Bechtel supports the project from Reston, Virginia.",
            "Houston, Texas",
        ),
        (
            "Sundt breaks ground on $92M Texas water project",
            "Work covers the Pecan Creek Water Reclamation Plant expansion.",
            "Texas",
        ),
    ]
    for title, summary, location in cases:
        result = assess_news(title, summary)
        assert (result.decision, result.tier, result.location) == ("accepted", "Signal", location)
        assert result.subject


def test_prospect_requires_two_explicit_site_and_activity_claims() -> None:
    result = assess_news(
        "Northstar begins construction at the Northstar Mesa data center in Texas",
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed.",
    )
    assert result.tier == "Prospect"
    assert result.demand_quote == "Northstar Mesa data center construction requires 42 MW."
    assert result.demand_mw == "42 MW"
    assert (
        result.supply_quote
        == "Power supply for Northstar Mesa data center construction is delayed."
    )


def test_adversarial_power_and_relationship_claims_do_not_promote() -> None:
    cases = [
        (
            "Oracle reports setbacks at Project Jupiter data center campus in New Mexico",
            "The 2.5GW campus capacity is expected online in 2028.",
        ),
        (
            "Oklo seeks interconnection for a Virginia project",
            "The 750-MW mixed technology generation project could be delayed.",
        ),
        (
            "Atlas builds a data center in Texas",
            "Atlas headquarters in Virginia needs 40 MW for operations.",
        ),
        (
            "Atlas builds a data center in Texas",
            "Atlas data center construction requires 40 MW. "
            "Adequate supply is available for construction.",
        ),
        (
            "Atlas builds a data center in Texas",
            "Atlas data center construction requires 40 MW. Power supply for another Atlas "
            "plant construction is delayed.",
        ),
    ]
    for title, summary in cases:
        assert assess_news(title, summary).tier != "Prospect"


def test_prospect_claims_reject_negation_speculation_other_site_and_contradiction() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    cases = [
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is not delayed.",
        "Northstar Mesa data center construction does not require 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed.",
        "Northstar Mesa data center construction might require 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed.",
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa Annex data center construction is delayed.",
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed. "
        "Northstar Mesa data center construction now has adequate supply.",
    ]
    for summary in cases:
        assert assess_news(title, summary).tier != "Prospect"


def test_new_mexico_is_a_us_state_not_an_international_mexico_match() -> None:
    result = assess_news("Atlas begins construction of a data center in New Mexico", None)
    assert (result.decision, result.tier, result.location) == ("accepted", "Signal", "New Mexico")


def test_actor_hq_geography_never_establishes_the_facility_location() -> None:
    cases = [
        (
            "Texas-based Atlas builds a manufacturing plant in Shanghai",
            "Atlas headquarters are in Dallas.",
        ),
        (
            "California-based Atlas expands a factory in Ontario",
            "Atlas headquarters are in Dallas.",
        ),
    ]
    for title, summary in cases:
        assert assess_news(title, summary).decision == "rejected"


def test_site_name_words_are_not_activity_and_claim_spans_must_differ() -> None:
    title = "Northstar begins construction at the Northstar Mesa manufacturing plant in Texas"
    phase_confusion = (
        "Northstar Mesa manufacturing plant construction requires 42 MW. "
        "Power supply for Northstar Mesa manufacturing plant commissioning is delayed."
    )
    same_span = (
        "Northstar Mesa manufacturing plant construction requires 42 MW and power supply "
        "for Northstar Mesa manufacturing plant construction is delayed."
    )
    assert assess_news(title, phase_confusion).tier != "Prospect"
    assert assess_news(title, same_span).tier != "Prospect"


def test_same_site_same_construction_adequate_supply_closes_but_operations_does_not() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    closed = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Northstar Mesa data center construction has adequate supply."
    )
    operating_only = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Northstar Mesa data center operations has adequate supply."
    )
    assert assess_news(title, closed).decision == "rejected"
    assert assess_news(title, operating_only).tier == "Signal"


def test_zero_or_negative_mw_is_not_an_actual_power_requirement() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    zero = (
        "Northstar Mesa data center construction requires 0 MW. "
        "Power supply for Northstar Mesa data center construction is delayed."
    )
    negative = (
        "Northstar Mesa data center construction requires -42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed."
    )
    assert assess_news(title, zero).tier == "Signal"
    assert assess_news(title, negative).tier == "Signal"


def test_affirmative_supply_grammar_and_exact_requirement_mw_are_narrow() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    positive = (
        "Northstar Mesa data center campus capacity is 200 MW, but Northstar Mesa data center "
        "construction requires about 42 MW. Power supply for Northstar Mesa data center "
        "construction is delayed."
    )
    ambiguous = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Northstar Mesa data center power supply has no constraint."
    )
    resolved = (
        "Northstar Mesa data center construction requires 42 MW. "
        "Power supply for Northstar Mesa data center construction is delayed but now adequate."
    )
    assessment = assess_news(title, positive)
    assert assessment.tier == "Prospect"
    assert assessment.demand_mw == "about 42 MW"
    assert assess_news(title, ambiguous).tier == "Signal"
    assert assess_news(title, resolved).tier != "Prospect"


def test_supply_adverse_predicate_must_be_a_complete_clause() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    demand = "Northstar Mesa data center construction requires 42 MW. "
    clauses = [
        "Power supply for Northstar Mesa data center construction is unavailable, but power "
        "supply for Northstar Mesa data center construction is now available.",
        "Power supply for Northstar Mesa data center construction is delayed, but now adequate.",
        "Power supply for Northstar Mesa data center construction is insufficient and secured.",
        "Power supply for Northstar Mesa data center construction is unavailable. "
        "Power supply for Northstar Mesa data center construction is now available.",
    ]
    for clause in clauses:
        assert assess_news(title, demand + clause).tier != "Prospect"


def test_demand_must_be_one_complete_exact_site_and_activity_clause() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    supply = "Power supply for Northstar Mesa data center construction is delayed."
    cases = [
        "Northstar Mesa data center operations requires 200 MW, while construction "
        "requires 42 MW. ",
        "Northstar Mesa data center construction has started, while Other Site requires 70 MW. ",
        "Northstar Mesa data center construction no longer requires 42 MW. ",
        "Northstar Mesa data center construction requires 42 MW, while Northstar Mesa data "
        "center construction requires 70 MW. ",
    ]
    for demand in cases:
        assert assess_news(title, demand + supply).tier == "Signal"


def test_exact_site_construction_clause_after_unrelated_capacity_still_promotes() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    summary = (
        "Northstar Mesa data center campus is rated at 200 MW, but Northstar Mesa data center "
        "construction requires 42 MW. Power supply for Northstar Mesa data center construction "
        "is delayed."
    )
    result = assess_news(title, summary)
    assert (result.tier, result.demand_mw) == ("Prospect", "42 MW")


def test_shared_clause_units_preserve_decimals_and_scope_resolution() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    decimal = (
        "Northstar Mesa data center construction requires 42.5 MW; Power supply for "
        "Northstar Mesa data center construction is unavailable."
    )
    fractional = (
        "Northstar Mesa data center construction requires 0.5 MW. Power supply for "
        "Northstar Mesa data center construction is delayed."
    )
    other_site = (
        "Northstar Mesa data center construction requires 42 MW; Other Site construction "
        "has adequate supply. Power supply for Northstar Mesa data center construction is delayed."
    )
    same_site = (
        "Northstar Mesa data center construction requires 42 MW; Northstar Mesa data center "
        "construction has adequate supply."
    )
    assert assess_news(title, decimal).demand_mw == "42.5 MW"
    assert assess_news(title, fractional).demand_mw == "0.5 MW"
    assert assess_news(title, other_site).tier == "Prospect"
    assert assess_news(title, same_site).decision == "rejected"


def test_resolution_only_blocks_the_same_power_activity() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    construction_prospect = (
        "Northstar Mesa data center construction requires 42 MW. Northstar Mesa data center "
        "operations has adequate supply. Power supply for Northstar Mesa data center construction "
        "is delayed."
    )
    construction_resolved = (
        "Northstar Mesa data center construction requires 42 MW. Northstar Mesa data center "
        "construction has adequate supply. Power supply for Northstar Mesa data center "
        "construction is delayed."
    )
    operations_resolved = (
        "Northstar Mesa data center operations requires 42 MW. Northstar Mesa data center "
        "operations has adequate supply. Power supply for Northstar Mesa data center operations "
        "is delayed."
    )
    operations_prospect = (
        "Northstar Mesa data center operations requires 42 MW. Northstar Mesa data center "
        "construction has adequate supply. Power supply for Northstar Mesa data center operations "
        "is delayed."
    )
    assert assess_news(title, construction_prospect).tier == "Prospect"
    assert assess_news(title, construction_resolved).decision == "rejected"
    assert assess_news(title, operations_resolved).decision == "rejected"
    assert assess_news(title, operations_prospect).tier == "Prospect"


def test_bound_candidate_phase_takes_priority_over_construction_event_for_resolution() -> None:
    title = "Northstar begins construction at the Northstar Mesa data center in Texas"
    summary = (
        "Northstar Mesa data center commissioning requires 42 MW. Northstar Mesa data center "
        "construction has adequate supply. Power supply for Northstar Mesa data center "
        "commissioning is delayed."
    )
    assert assess_news(title, summary).tier == "Prospect"


def test_signal_activity_helper_only_maps_supported_event_actions() -> None:
    assert signal_power_activity("opens") == "operations"
    assert signal_power_activity("builds") == "construction"
    assert signal_power_activity("will be built") == "construction"
    assert signal_power_activity("announces") is None


def test_public_power_activity_helper_enforces_the_same_site_and_phase_rule() -> None:
    subject = "Northstar Mesa manufacturing plant"
    demand = "Northstar Mesa manufacturing plant construction requires 42 MW."
    supply = "Power supply for Northstar Mesa manufacturing plant construction is delayed."
    wrong_phase = "Power supply for Northstar Mesa manufacturing plant commissioning is delayed."
    assert prospect_power_activity(subject, demand, supply) == "construction"
    assert prospect_power_activity(subject, demand, wrong_phase) is None


def test_cancellation_in_summary_overrides_affirmative_headline() -> None:
    result = assess_news(
        "Atlas will build a data center in Texas", "Atlas canceled the Texas data center project."
    )
    assert result.decision == "rejected"


def test_international_policy_and_recall_stay_rejected() -> None:
    cases = [
        (
            "Lego to expand manufacturing facility in Mexico",
            "The Monterrey site adds warehouse capacity.",
        ),
        (
            "Tower Semiconductor to establish an optical hub in Japan",
            "Expansion follows an investment pledge.",
        ),
        ("Virginia regulators plan cannabis license rules", "The policy sets cultivation limits."),
        ("Colorado cannabis firm recalls vapes", "A lab found a solvent in products."),
    ]
    for title, summary in cases:
        assert assess_news(title, summary).decision == "rejected"


def test_contract_and_dictionary_are_stable() -> None:
    result = assess_news("Atlas builds a plant in Alabama", None)
    assert EVALUATOR_VERSION == "rss-project-v6"
    assert set(result.as_dict()) == {
        "decision",
        "tier",
        "reason",
        "subject",
        "action",
        "location",
        "demand_quote",
        "demand_mw",
        "supply_quote",
        "missing_facts",
    }


def test_generic_actors_are_not_identifiable_project_subjects() -> None:
    titles = [
        "Investors plan to build a factory in Texas",
        "Developers plan to build a factory in Texas",
        "Officials plan to build a factory in Texas",
        "A company builds a factory in Texas",
        "A consortium builds a factory in Texas",
        "Construction begins at a factory in Texas",
    ]
    for title in titles:
        assert assess_news(title, None).decision == "rejected"


def test_named_actor_subjects_remain_identifiable() -> None:
    assert assess_news("Atlas builds a factory in Texas", None).tier == "Signal"
    assert (
        assess_news(
            "Northstar begins construction at the Northstar Mesa data center in Texas", None
        ).tier
        == "Signal"
    )
