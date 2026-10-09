"""Paraphrased facility-scope cases; these are not production project records."""

from gridlens.domain.lifecycle import classify_event


def test_adjacent_microgrid_milestones_do_not_advance_the_data_center_campus():
    assert (
        classify_event(
            "Project Jupiter data center update",
            "The adjacent microgrid building permit was issued and construction started.",
        )
        is None
    )


def test_pending_air_permit_procedure_is_not_campus_permit_or_construction():
    for abstract in (
        "A hearing officer was appointed for the data center's separate air permit.",
        "The court allowed the air permit proceeding to resume; the campus permit remains pending.",
        "The air permit hearing was stayed while procedural review continues.",
    ):
        assert classify_event("Project Jupiter data center permitting update", abstract) is None


def test_force_majeure_and_possible_power_delay_are_not_completed_milestones():
    assert (
        classify_event(
            "Project Jupiter data center update",
            "A force majeure notice cites possible power delays; no campus milestone is reported.",
        )
        is None
    )


def test_pending_utility_service_request_is_not_energization():
    assert (
        classify_event(
            "Project Jupiter data center campus",
            "Utility service was requested and remains pending.",
        )
        is None
    )


def test_positive_campus_permit_survives_adjacent_microgrid_procedure():
    event = classify_event(
        "Project Jupiter data center update",
        "The data center campus received its building permit. "
        "The separate microgrid air permit remains pending.",
    )
    assert event is not None
    assert (event.event_type, event.state) == ("building_permit_issued", "permitting")


def test_positive_campus_energization_survives_adjacent_force_majeure_report():
    event = classify_event(
        "Project Jupiter campus update",
        "The Project Jupiter data center campus was energized. "
        "A force majeure notice separately cites possible future power delays.",
        project_name="Project Jupiter campus",
        project_identity_key="project-jupiter-campus",
    )
    assert event is not None
    assert (event.event_type, event.state) == ("utility_service", "utility_energization")


def test_proposed_pending_delayed_stayed_and_conditional_events_do_not_advance_state():
    for wording in (
        "The data center campus building permit is proposed.",
        "The data center campus building permit is pending.",
        "The data center campus construction is delayed.",
        "The data center campus building permit was stayed.",
        "The data center campus energization is conditional on utility approval.",
        "Air permit application narrative: the facility proposes to construct a data center "
        "campus.",
        "Data center air permit application received for construction and operation of generators.",
        "Draft air permit issued for construction and operation of a data center facility.",
    ):
        assert classify_event("Project Jupiter data center update", wording) is None


def test_draft_air_permit_construction_does_not_hide_achieved_campus_permit():
    event = classify_event(
        "Project Jupiter data center and air permit update",
        "Project Jupiter's data center campus received its building permit. "
        "The draft air permit authorizes "
        "construction and operation of emergency generators.",
        project_name="Project Jupiter campus",
        project_identity_key="project-jupiter-campus",
    )
    assert event is not None and event.event_type == "building_permit_issued"
    assert event.state == "permitting"


def test_another_named_campus_event_cannot_advance_jupiter():
    event = classify_event(
        "Project Jupiter data center permitting update",
        "Project Atlas data center campus received a building permit. Project Jupiter's campus "
        "permit remains pending; the adjacent microgrid air permit is also pending.",
        project_name="Project Jupiter campus",
        project_identity_key="project-jupiter-campus",
    )
    assert event is None


def test_standalone_issued_campus_permit_and_actual_energization_still_classify():
    permit = classify_event("Building permit issued for Project Jupiter data center campus")
    energization = classify_event("Project Jupiter data center campus was energized")

    assert permit is not None
    assert (permit.event_type, permit.state) == ("building_permit_issued", "permitting")
    assert energization is not None and energization.state == "utility_energization"


def test_ordinary_multi_campus_report_binds_only_jupiter_event_clause():
    event = classify_event(
        "Project Jupiter data center update",
        "Project Atlas campus building permit was issued; "
        "Project Jupiter data center development agreement was approved.",
        project_name="Project Jupiter campus",
        project_identity_key="jupiter-campus-us-nm",
    )

    assert event is not None
    assert (event.event_type, event.state) == ("project_formation", "site_control_planning")


def test_permit_only_electrical_text_is_permitting_not_electrical_buildout():
    event = classify_event(
        "Project Jupiter data center electrical update",
        "An electrical permit was issued for the Project Jupiter data center campus.",
        project_name="Project Jupiter campus",
        project_identity_key="jupiter-campus-us-nm",
    )

    assert event is not None
    assert (event.event_type, event.state) == ("electrical_permit_issued", "permitting")


def test_typed_target_does_not_lend_permit_milestone_to_named_warehouse():
    assert (
        classify_event(
            "Austin building permit TRANSITION-TEST-1 - Electrical Permit",
            "Construct new warehouse.",
            project_name="Austin permit TRANSITION-TEST-1",
            project_identity_key="permit:transition-test-1",
            project_asset_type="data_center",
            reported_permit_event="electrical_permit_issued",
        )
        is None
    )


def test_explicit_campus_clause_remains_supported_beside_separate_warehouse_clause():
    event = classify_event(
        "Project Jupiter data center update",
        "Project Jupiter data center campus received its electrical permit. "
        "A separate warehouse is proposed on the neighboring lot.",
        project_name="Project Jupiter campus",
        project_identity_key="project-jupiter-campus",
        project_asset_type="data_center",
    )
    assert event is not None
    assert (event.event_type, event.state) == ("electrical_permit_issued", "permitting")


def test_physical_construction_and_electrical_work_remain_achieved_states():
    construction = classify_event(
        "Project Jupiter data center update",
        "Project Jupiter data center construction has started.",
        project_name="Project Jupiter campus",
        project_identity_key="jupiter-campus-us-nm",
    )
    electrical = classify_event(
        "Project Jupiter data center update",
        "The Project Jupiter campus transformer installation is underway.",
        project_name="Project Jupiter campus",
        project_identity_key="jupiter-campus-us-nm",
    )

    assert construction is not None and construction.state == "construction"
    assert electrical is not None and electrical.state == "electrical_buildout"


def test_bare_construction_wording_does_not_establish_physical_work():
    assert (
        classify_event(
            "Project Jupiter data center update",
            "Project Jupiter data center construction in Austin, TX.",
            project_name="Project Jupiter campus",
            project_identity_key="jupiter-campus-us-nm",
        )
        is None
    )
