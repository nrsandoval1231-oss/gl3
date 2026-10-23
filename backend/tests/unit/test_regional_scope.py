from gridlens.domain.regional_scope import classify_project_region


def test_explicit_regional_site_is_eligible_even_when_other_context_disagrees():
    decision = classify_project_region(
        "Abilene, Texas", {"headquarters": "San Jose, CA", "site": "Abilene, TX"}
    )
    assert (decision.status, decision.state, decision.reason) == (
        "ELIGIBLE",
        "TX",
        "project_site_in_region",
    )


def test_conflicting_explicit_project_site_states_are_held():
    decision = classify_project_region("Austin, TX", {"site": "Santa Clara, CA"})
    assert (decision.status, decision.state, decision.reason) == (
        "HOLD",
        None,
        "conflicting_project_site_states",
    )


def test_unknown_and_out_of_region_sites_never_enter_active_region():
    unknown = classify_project_region("Austin", {"headquarters": "Dallas, TX"})
    excluded = classify_project_region("Boston, Massachusetts", {})
    assert unknown.status == "HOLD"
    assert unknown.reason == "project_site_state_unknown"
    assert excluded.status == "EXCLUDED"
    assert excluded.state == "MA"


def test_supported_states_are_ordered_in_policy_constant():
    from gridlens.domain.regional_scope import REGIONAL_STATES

    assert REGIONAL_STATES == ("TX", "OK", "NM")


def test_state_words_in_narrative_and_city_only_are_not_location_proof():
    assert classify_project_region("Made in Texas").status == "HOLD"
    assert classify_project_region("Austin").status == "HOLD"


def test_explicit_state_overrides_ambiguous_city_name():
    decision = classify_project_region("Dallas, GA")
    assert (decision.status, decision.state) == ("EXCLUDED", "GA")


def test_multiple_sites_in_one_field_are_held():
    for location in ("Austin, TX / Tulsa, OK", "Austin, TX; Santa Clara, CA"):
        decision = classify_project_region(location)
        assert (decision.status, decision.state) == ("HOLD", None)


def test_postal_city_state_tokens_are_explicit_and_conflicts_are_held():
    for location, status, state in (
        ("Austin, TX", "ELIGIBLE", "TX"),
        ("Dallas, TX 75201", "ELIGIBLE", "TX"),
        ("Tulsa, OK 74103", "ELIGIBLE", "OK"),
        ("Las Cruces, NM 88001", "ELIGIBLE", "NM"),
        ("Atlanta, GA 30303", "EXCLUDED", "GA"),
        ("Austin, TX; Atlanta, GA", "HOLD", None),
        ("Austin, TX 78701; Tulsa, OK 74103", "HOLD", None),
        ("Made In Texas", "HOLD", None),
        ("Austin Texas", "HOLD", None),
    ):
        decision = classify_project_region(location)
        assert (decision.status, decision.state) == (status, state)


def test_postal_state_conflicts_across_physical_identity_fields_are_held():
    decision = classify_project_region("Austin, TX", {"site_address": "Atlanta, GA 30303"})
    assert (decision.status, decision.state, decision.reason) == (
        "HOLD",
        None,
        "conflicting_project_site_states",
    )


def test_root_reproduction_strings_are_classified_conservatively():
    cases = (
        ("Austin, TX; Atlanta GA", "HOLD", None),
        ("100 Main Street, Dallas TX 75201", "ELIGIBLE", "TX"),
        ("Austin TX / Atlanta, GA", "HOLD", None),
        ("Tulsa OK", "HOLD", None),
        ("Las Cruces NM", "HOLD", None),
    )
    for location, status, state in cases:
        decision = classify_project_region(location)
        assert (decision.status, decision.state) == (status, state)


def test_unpunctuated_uppercase_prose_requires_postal_structure():
    cases = (
        ("EVERYTHING IS OK", "HOLD", None),
        ("Everything Is OK", "HOLD", None),
        ("OK", "HOLD", None),
        ("THE PROJECT IS OK", "HOLD", None),
        ("SITE STATUS IS OK", "HOLD", None),
        ("TULSA OK", "HOLD", None),
        ("TULSA, OK", "ELIGIBLE", "OK"),
        ("Las Cruces, NM", "ELIGIBLE", "NM"),
        ("TULSA OK 74103", "ELIGIBLE", "OK"),
        ("LAS CRUCES NM 88001", "ELIGIBLE", "NM"),
        ("Austin, TX; Atlanta GA", "HOLD", None),
        ("Austin TX / Atlanta, GA", "HOLD", None),
        ("Austin, TX; Everything Is OK", "HOLD", None),
        ("Austin, TX; Austin TX", "ELIGIBLE", "TX"),
        ("Atlanta, GA and Austin, TX", "HOLD", None),
        ("Austin, TX and Atlanta, GA", "HOLD", None),
        ("Dallas, TX and Austin, TX", "ELIGIBLE", "TX"),
        ("Austin, TX; Atlanta Georgia", "HOLD", None),
        ("Atlanta Georgia and Austin, TX", "HOLD", None),
        ("Austin, TX and Atlanta Georgia", "HOLD", None),
        ("100 New York Avenue, Austin, TX", "ELIGIBLE", "TX"),
    )
    for location, status, state in cases:
        decision = classify_project_region(location)
        assert (decision.status, decision.state) == (status, state)


def test_la_salle_street_does_not_hold_an_illinois_site_as_louisiana():
    """An Illinois address was held because the street token LA looked like Louisiana."""
    street = "400 S LA SALLE ST, Chicago, IL"
    decision = classify_project_region(street)
    assert (decision.status, decision.state, decision.reason) == (
        "EXCLUDED",
        "IL",
        "project_site_outside_region",
    )
    split = classify_project_region("Chicago, IL", {"site_address": "400 S LA SALLE ST"})
    assert (split.status, split.state, split.reason) == (
        "EXCLUDED",
        "IL",
        "project_site_outside_region",
    )
    assert "LA" not in split.provenance["possible_state_suffixes"].get(
        "identity_facts.site_address", []
    )
    louisiana = classify_project_region("Baton Rouge, LA")
    named = classify_project_region("Baton Rouge, Louisiana")
    assert (louisiana.status, louisiana.state) == ("EXCLUDED", "LA")
    assert (named.status, named.state) == ("EXCLUDED", "LA")
    # A trailing state code is still a conflict. Only the mid-street token is ignored.
    conflict = classify_project_region("Austin, TX; Baton Rouge LA")
    assert (conflict.status, conflict.reason) == ("HOLD", "conflicting_project_site_states")


def test_owner_region_acceptance_matrix():
    cases = [
        ("Dallas, TX", {}, "ELIGIBLE", "TX"),
        ("Tulsa, OK", {}, "ELIGIBLE", "OK"),
        ("Albuquerque, NM", {}, "ELIGIBLE", "NM"),
        ("Boston, MA", {}, "EXCLUDED", "MA"),
        ("Santa Clara, CA", {}, "EXCLUDED", "CA"),
        ("Austin", {}, "HOLD", None),
        (None, {}, "HOLD", None),
        (None, {"headquarters": "Dallas, TX"}, "HOLD", None),
        (None, {"source_geography": "Texas"}, "HOLD", None),
        ("Austin, TX", {"site": "Tulsa, OK"}, "HOLD", None),
        ("Austin, TX / Tulsa, OK", {}, "HOLD", None),
        ("Austin, TX; Santa Clara, CA", {}, "HOLD", None),
        ("Made in Texas", {}, "HOLD", None),
        (
            "Abilene, TX",
            {"crossborder_supporting_evidence": "Santa Clara, CA"},
            "ELIGIBLE",
            "TX",
        ),
        ("Austin, TX", {"headquarters": "San Jose, CA"}, "ELIGIBLE", "TX"),
    ]
    for location, facts, expected_status, expected_state in cases:
        decision = classify_project_region(location, facts)
        assert (decision.status, decision.state) == (expected_status, expected_state)
