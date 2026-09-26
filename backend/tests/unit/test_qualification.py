from gridlens.domain.qualification import (
    assess_nc_commerce_signal,
    assess_signal,
    nc_commerce_location,
)
from gridlens.intelligence.matching import interpret


def test_specific_mine_development_is_signal_with_unknowns():
    rationale = assess_signal(
        "Roca Honda Mine: Notice of Availability",
        "Proposed Mine Plan of Operations for development includes dewatering "
        "and ventilation shafts.",
    )
    assert rationale and "unknown" in rationale.lower()


def test_broad_mining_policy_and_renewal_do_not_promote():
    assert (
        assess_signal("National Mining Program", "Proposed operations at mines are considered.")
        is None
    )
    assert (
        assess_signal(
            "Crow Butte Project license renewal", "Continued operation of an existing facility."
        )
        is None
    )


def test_generic_permit_or_cancellation_is_not_a_development_signal():
    assert (
        assess_signal(
            "State mining permit notice", "A permit has been renewed for ongoing activity."
        )
        is None
    )
    assert assess_signal("Silver Mine Project", "The proposed development was canceled.") is None


def test_nc_physical_facility_expansion_is_a_signal_and_keeps_explicit_county():
    title = (
        "National Steel Fabrication Company Plans a $19 Million Manufacturing Expansion "
        "in Fayetteville"
    )
    excerpt = (
        "Today Governor Josh Stein announced SteelFab, Inc., a steel fabrication company, "
        "will add jobs in Cumberland County. The company will invest to expand operations "
        "in Fayetteville."
    )
    assert assess_nc_commerce_signal(title, excerpt)
    assert nc_commerce_location(excerpt) == "Cumberland County, North Carolina"
    result = interpret({"source_id": "nc-commerce", "title": title, "abstract": excerpt})
    assert result and result["activity_key"] == "facility-expansion"
    assert result["name"] == title  # No unsupported company-name substitution.


def test_nc_jobs_grants_and_generic_awards_do_not_create_signals():
    assert (
        assess_nc_commerce_signal(
            "Governor Announces New Jobs and Grant Awards",
            "A grant program will support small businesses and create 200 new jobs.",
        )
        is None
    )


def test_nc_aggregate_program_statistics_are_not_project_signals():
    title = (
        "North Carolina Reports $500 Million in New Investments, 300 New Businesses, "
        "and Nearly 2,500 New Jobs through Main Street Program"
    )
    abstract = (
        "The NC Main Street & Rural Planning Center reported today that since the "
        "inception of the Main Street program, communities leveraged investment. "
        "This supported more than 8,700 building rehabilitations and thousands of jobs."
    )
    assert assess_nc_commerce_signal(title, abstract) is None


def test_nc_supported_site_expansion_titles_remain_signals():
    steel_fab = (
        "National Steel Fabrication Company Plans a $19 Million Manufacturing Expansion "
        "in Fayetteville",
        "Today Governor announced SteelFab, Inc. will add jobs in Cumberland County. "
        "The company will invest to expand operations in Fayetteville.",
    )
    boat_campus = (
        "Boat Manufacturer to Create 179 Jobs for a $6 Million Production Campus "
        "in Beaufort County",
        "Boater’s World Manufacturing Group, LLC will create jobs in Beaufort County. "
        "The company says it will invest to establish a boat manufacturing campus in Chocowinity.",
    )
    assert assess_nc_commerce_signal(*steel_fab)
    assert assess_nc_commerce_signal(*boat_campus)
    assert (
        assess_nc_commerce_signal(
            "Company Cancels Manufacturing Expansion",
            "The company canceled its plan to expand operations at a new facility.",
        )
        is None
    )


def test_federal_register_project_display_name_and_state_come_from_explicit_title():
    row = {
        "title": (
            "Mount Taylor Ranger District, Cibola National Forest; New Mexico; "
            "Roca Honda Mine Project"
        ),
        "abstract": (
            "Proposed Mine Plan of Operations would develop the mine with dewatering "
            "infrastructure."
        ),
    }
    result = interpret(row)
    assert result and result["name"] == "Roca Honda Mine Project"
    assert result["location"] == "New Mexico"
