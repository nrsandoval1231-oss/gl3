from uuid import uuid4

from gridlens.intelligence.account_shortlist import _physical_duplicate_components


def test_coverage_duplicate_does_not_override_distinct_validated_site_ids():
    first, second = uuid4(), uuid4()
    components = _physical_duplicate_components(
        {"same-permit-coverage": {first, second}},
        [
            {"project_id": first, "physical_identity": "data_center_campus:north"},
            {"project_id": second, "physical_identity": "data_center_campus:south"},
        ],
    )
    assert components == []


def test_same_validated_well_api_still_collapses_coverage_duplicate():
    first, second = uuid4(), uuid4()
    components = _physical_duplicate_components(
        {"same-permit-coverage": {first, second}},
        [
            {"project_id": first, "physical_identity": "us_well_api:4216500001"},
            {"project_id": second, "physical_identity": "us_well_api:4216500001"},
        ],
    )
    assert components == [{first, second}]


def test_coverage_duplicate_without_site_conflict_can_still_collapse():
    first, second = uuid4(), uuid4()
    components = _physical_duplicate_components(
        {"same-permit-coverage": {first, second}},
        [{"project_id": first}, {"project_id": second}],
    )
    assert components == [{first, second}]


def test_transitive_coverage_bridge_cannot_merge_conflicting_site_ids():
    north, bridge, south = uuid4(), uuid4(), uuid4()
    components = _physical_duplicate_components(
        {"permit-a": {north, bridge}, "permit-b": {bridge, south}},
        [
            {"project_id": north, "physical_identity": "data_center_campus:north"},
            {"project_id": bridge},
            {"project_id": south, "physical_identity": "data_center_campus:south"},
        ],
    )
    assert components == []


def test_permit_component_closes_over_all_projects_with_same_validated_well_api():
    permit_bp, permit_ep, other_permit = uuid4(), uuid4(), uuid4()
    shared_api = "us_well_api:4216500001"
    components = _physical_duplicate_components(
        {"paired-permit": {permit_bp, permit_ep}},
        [
            {"project_id": permit_bp, "physical_identity": shared_api},
            {"project_id": permit_ep, "physical_identity": shared_api},
            {"project_id": other_permit, "physical_identity": shared_api},
        ],
    )
    assert components == [{permit_bp, permit_ep, other_permit}]
