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


def test_explicit_project_state_wins_city_fallback() -> None:
    columbus = assess_news("Atlas builds Columbus plant in Georgia", None)
    assert (columbus.decision, columbus.tier, columbus.location) == (
        "accepted",
        "Signal",
        "Georgia",
    )


def test_explicit_foreign_project_site_wins_us_state_token_and_hq_control() -> None:
    foreign_site = assess_news(
        "Acme begins construction on Georgia factory near Monterrey, Mexico", None
    )
    assert foreign_site.decision == "rejected"
    assert foreign_site.location is None

    partner_abroad = assess_news(
        "Atlas builds a factory in Texas with partners in Tokyo, Japan", None
    )
    assert (partner_abroad.decision, partner_abroad.tier, partner_abroad.location) == (
        "accepted",
        "Signal",
        "Texas",
    )

    # A foreign actor headquarters does not override a project explicitly in Texas.
    domestic_site = assess_news("Japan-based Atlas builds a factory in Texas", None)
    assert (domestic_site.decision, domestic_site.tier, domestic_site.location) == (
        "accepted",
        "Signal",
        "Texas",
    )


def test_actor_hq_geography_never_establishes_the_facility_location() -> None:
    cases = [
        (
            "Texas-based Atlas builds a data center in Japan",
            "Atlas headquarters are in Dallas.",
        ),
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


def test_project_linked_city_precedes_nearby_developer_or_customer_state() -> None:
    cases = [
        ("California developer Atlas builds Austin data center", "Austin, Texas"),
        (
            "Atlas builds a factory for customers in California at its site in Phoenix, Arizona",
            "Phoenix, Arizona",
        ),
        ("Atlas builds Phoenix data center in Arizona", "Phoenix, Arizona"),
        ("Atlas builds Austin's first large liquid-cooled data center", "Austin, Texas"),
    ]
    for title, location in cases:
        result = assess_news(title, None)
        assert (result.decision, result.tier, result.location) == ("accepted", "Signal", location)


def test_domestic_city_site_precedes_foreign_partner_location() -> None:
    cases = [
        "Atlas builds a factory in Austin with partners in Tokyo, Japan",
        "Atlas builds Austin factory with partners in Tokyo, Japan",
        "Atlas builds a factory in Austin, TX with partners in Tokyo, Japan",
    ]
    for title in cases:
        result = assess_news(title, None)
        assert (result.decision, result.tier, result.location) == (
            "accepted",
            "Signal",
            "Austin, Texas",
        )

    foreign_site = assess_news(
        "California developer Atlas builds factory with partners at a site near Tokyo, Japan",
        None,
    )
    assert foreign_site.decision == "rejected"
    assert foreign_site.location is None


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
    assert EVALUATOR_VERSION == "rss-project-v10"
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


def test_site_and_milestone_news_v7_preserves_retained_project_events() -> None:
    cases = [
        (
            "Northrop Grumman, Air Force start on $4.5B expansion",
            "With cash from the One Big Beautiful Bill, the California build will add more "
            "than 1 million square feet to produce B-21 Raider machines.",
            "California",
        ),
        (
            "GlobalFoundries to build and operate two new chip fabs in NY as part of $21bn "
            "US-Japan deal",
            "First facility is expected to be operational in 2029",
            "New York",
        ),
        (
            "GlobalFoundries building $21B New York fabs under US-Japan trade deal",
            "The multibillion-dollar agreement will accelerate U.S. semiconductor manufacturing, "
            "strengthen critical supply chains and support growing automotive and industrial "
            "demand, GlobalFoundries said.",
            "New York",
        ),
        (
            "Flintco-Mortenson JV begins concrete deck at $900M Oklahoma City NBA arena",
            "The construction team on the future home of the Oklahoma City Thunder also started "
            "work on the loading dock walls on the east side of the venue.",
            "Oklahoma City, Oklahoma",
        ),
        (
            "Application filed for 3.3 million sq ft data center campus in Augusta, Georgia",
            "Project targeting 2028/2029 go live date",
            "Augusta, Georgia",
        ),
        (
            "IURC approves AES Indiana plan for $1.3bn solar, storage, and transmission project "
            "for Google data center in Monrovia",
            "Google is expected to pay for all the costs associated with the project",
            "Monrovia, Indiana",
        ),
    ]
    for title, summary, location in cases:
        result = assess_news(title, summary)
        assert (result.decision, result.tier, result.location) == (
            "accepted",
            "Signal",
            location,
        ), (title, result.reason)
        assert result.demand_mw is None
        assert signal_power_activity(result.action) == "construction"


def test_v7_does_not_turn_speculative_or_system_power_stories_into_site_events() -> None:
    cases = [
        (
            "400MW data center eyed at old Navy cyber site in San Diego, California",
            "Manchester Financial Group exploring potential of data center at NAVWAR HQ",
        ),
        (
            "AEP signs 960-MW Indiana nuclear pact with Amazon, X-energy",
            "If the project is developed, Amazon would purchase the power under a long-term "
            "contract that covers the cost of the facility and its operations, the companies said.",
        ),
        (
            "Georgia electric cooperative plans 50-MW home battery deployment",
            "Central Georgia Electric Membership Corporation plans to use the batteries to reduce "
            "system peaks and energy costs as hyperscale data centers seek to connect to its grid.",
        ),
    ]
    for title, summary in cases:
        assert assess_news(title, summary).decision == "rejected", title


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


def test_early_stage_us_data_center_events_from_retained_headlines_are_signals() -> None:
    # Retained production headlines (DCD, 2026-10) previously rejected as having no
    # concrete project action. Land, financing, a dated power contract for a planned
    # site, and site conversion each precede groundbreaking.
    cases = [
        (
            "Microsoft acquires 600 acres of land for data center in Woodward, Iowa",
            "Local residents raise concerns",
            "Woodward, Iowa",
        ),
        (
            "Digi Power X secures $200m in debt financing for Alabama data center project",
            "Will support the development of a 40MW data center in Columbiana, Alabama",
            "Alabama",
        ),
        (
            "Microsoft signs 20-year power deal with Indiana utility NiSource for planned "
            "data center in the state",
            "Will commence in 2028",
            "Indiana",
        ),
        (
            "Valor Energy acquires computing site in Youngstown, Ohio",
            "Company looks to pivot 18MW site into an AI data center",
            "Youngstown, Ohio",
        ),
    ]
    for title, summary, location in cases:
        result = assess_news(title, summary)
        assert (result.decision, result.tier, result.location) == (
            "accepted",
            "Signal",
            location,
        ), (title, result.reason)
        assert result.subject
        assert result.demand_mw is None
        # The ingestion path requires an accepted Signal to bind one power activity.
        assert signal_power_activity(result.action) == "construction"


def test_named_commercial_construction_start_is_a_signal() -> None:
    result = assess_news(
        "DPR breaks ground on $230M Kaiser Permanente project in Colorado",
        "The contractor will use prefabricated and modular construction to build the "
        "offices, cutting down on jobsite complexity.",
    )
    assert (result.decision, result.tier, result.location) == ("accepted", "Signal", "Colorado")
    assert result.subject == "Kaiser Permanente project"


def test_city_state_and_fort_worth_location_are_retained_without_power_inference() -> None:
    result = assess_news(
        "Meta acquires 100 acres of land for planned data center in Fort Worth, Texas",
        "The site is under evaluation.",
    )
    assert (result.decision, result.tier, result.location) == (
        "accepted",
        "Signal",
        "Fort Worth, Texas",
    )
    assert result.demand_mw is None
    assert result.missing_facts == [
        "activity-specific power requirement",
        "supply suitability",
        "start window",
        "duration",
    ]


def test_early_stage_lookalikes_stay_rejected() -> None:
    cases = [
        # Company acquisitions, not sites.
        ("CBRE acquires data center services firm Onnec", "Initial purchase price of $610 million"),
        # Exploratory or speculative site interest.
        (
            "400MW data center eyed at old Navy cyber site in San Diego, California",
            "Manchester Financial Group exploring potential of data center at NAVWAR HQ",
        ),
        (
            "Google explores data center site in Roanoke County, Virginia",
            "Evaluates the Wood Haven Technology Park as a site for project",
        ),
        # Power contract without a planned/new site is supply reporting.
        (
            "Meta signs power deal with Texas utility for existing data centers",
            "The agreement covers current operations",
        ),
        # Financing a company, not a site.
        ("Lambda secures $500m in financing", "The AI cloud firm will expand its team"),
        # Non-US.
        (
            "DataVault secures $50m in financing for data center in Auckland, New Zealand",
            "First phase due live next year",
        ),
    ]
    for title, summary in cases:
        assert assess_news(title, summary).decision == "rejected", title


def test_filed_build_and_joint_venture_groundbreakings_are_unknown_power_signals() -> None:
    cases = [
        (
            "Turner-FH joint venture breaks ground on Colorado hospital",
            "The build for AdventHealth in Louisville carries a price tag of $475 million, "
            "according to Becker’s Hospital Review.",
        ),
        (
            "Soluna files to build 112MW data center building in Willacy, Texas",
            "Will span a single building totaling 471,884 sq ft",
        ),
        (
            "JE Dunn-Alberici JV breaks ground on $3.2B Texas shipyard",
            "The greenfield shipyard built for military contractor Saronic is "
            "the first in the U.S. "
            "since World War II, according to the construction joint venture.",
        ),
    ]
    for title, abstract in cases:
        result = assess_news(title, abstract)
        assert result.decision == "accepted" and result.tier == "Signal", title
        assert result.demand_mw is None and result.demand_quote is None
        assert result.supply_quote is None
        assert "activity-specific power requirement" in result.missing_facts
        assert "supply suitability" in result.missing_facts


def test_new_event_forms_keep_location_and_speculation_guards() -> None:
    cases = [
        ("Atlas JV may break ground on a Texas shipyard", "Plans are being explored."),
        ("Atlas JV breaks ground on a shipyard in Canada", "Its office is in Texas."),
        ("Atlas files to build a data center", "The company is based in Texas."),
        ("Atlas JV cancels groundbreaking on Texas shipyard", "The project was halted."),
        ("Atlas JV recruits staff for Texas shipyard", "The facility opened years ago."),
    ]
    for title, abstract in cases:
        assert assess_news(title, abstract).decision == "rejected", title


def test_event_family_table_v9_retained_examples_and_matched_negatives() -> None:
    # Each row is a retained project example and a company-level, speculative,
    # overseas, or otherwise non-project contrast for the same event family.
    families = [
        (
            "filing",
            "Stack files for second building at Lancaster campus, Texas",
            "Company looks to start work in March",
            "Atlas files for a patent in Texas",
            "",
        ),
        (
            "sale",
            "Alcoa sells New York aluminum smelter to data center developer for $315 million",
            "Company doesn’t name buyer",
            "Atlas sells a company in Texas",
            "",
        ),
        (
            "financing",
            "Digi Power X secures $200m in debt financing for Alabama data center project",
            "Will support the development of a data center",
            "Atlas secures $500m in financing",
            "",
        ),
        (
            "power",
            "Google expands partnership with Entergy Arkansas, will fund renewable energy "
            "and grid upgrades for West Memphis data center",
            "Inks 440MW PPA",
            "Atlas signs power deal with Texas utility for existing data centers",
            "",
        ),
        (
            "conversion",
            "Valor Energy acquires computing site in Youngstown, Ohio",
            "Company looks to pivot 18MW site into an AI data center",
            "Atlas explores data center site in Roanoke County, Virginia",
            "",
        ),
        (
            "restoration",
            "NYC’s Plaza Hotel to close in 2027 for multiyear facade restoration",
            "The New York icon will shut down for at least four years",
            "Atlas considers facade restoration for a hotel in Texas",
            "",
        ),
    ]
    for family, positive, summary, negative, negative_summary in families:
        actual = assess_news(positive, summary)
        assert (actual.decision, actual.tier) == ("accepted", "Signal"), (family, actual)
        assert actual.demand_mw is None and actual.demand_quote is None
        assert actual.supply_quote is None
        assert assess_news(negative, negative_summary).decision == "rejected", family


def test_event_family_v9_renamed_passive_crossfield_and_guards() -> None:
    positives = [
        (
            "Atlas sells smelter to data center developer",
            "The smelter in Albany, New York will become a data center.",
        ),
        ("Atlas smelter sold in New York to data center developer", ""),
        (
            "Metro Hotel to close in 2027 for multiyear facade restoration",
            "The hotel in Houston, Texas requires major repairs.",
        ),
    ]
    negatives = [
        ("Atlas explores selling New York smelter to data center developer", ""),
        (
            "Atlas sells smelter in Canada to data center developer",
            "The smelter in Houston, Texas is unrelated.",
        ),
        ("Atlas sells smelter to data center developer", "The company is based in Texas."),
        ("Atlas recruits staff for Texas shipyard", "The facility opened years ago."),
        ("Atlas cancels plans to build a data center in Texas", ""),
    ]
    for title, summary in positives:
        result = assess_news(title, summary)
        assert result.tier == "Signal", (title, result.reason)
        assert result.demand_mw is None and result.supply_quote is None
    for title, summary in negatives:
        assert assess_news(title, summary).decision == "rejected", title


def test_site_sale_and_grid_commitment_do_not_claim_construction_phase() -> None:
    for title in (
        "Alcoa sells New York aluminum smelter to data center developer for $315 million",
        "Google expands partnership with Entergy Arkansas, will fund renewable energy "
        "and grid upgrades for West Memphis data center",
    ):
        result = assess_news(title, "")
        assert result.tier == "Signal"
        assert signal_power_activity(result.action) is None
        assert result.demand_mw is None and result.supply_quote is None
