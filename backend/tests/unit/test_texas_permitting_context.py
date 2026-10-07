from datetime import date

import pytest

from gridlens.domain.texas_permitting import texas_permitting_context


def context(**overrides):
    inputs = dict(
        asset_type="data_center",
        site={"status": "SUPPORTED", "value": "Austin, TX"},
        as_of=date(2026, 10, 7),
    )
    return texas_permitting_context(**(inputs | overrides))


@pytest.mark.parametrize("day", [date(2026, 10, 19), date(2026, 10, 20)])
def test_reporting_deadline_never_expires_pause(day):
    record = context(as_of=day)[0]
    assert record["reporting_deadline"] == "2026-10-19"
    assert record["expires_on"] is None
    assert record["status"] == "directed_pause"
    assert record["verified_on"] == "2026-10-07"
    assert record["current_status_verification"] == "requires_refresh"


def test_pause_has_separate_authority_scope_condition_and_provenance():
    record = context()[0]
    assert record["id"] == "tx-tceq-data-center-permitting-pause-2026-09-21"
    assert record["policy_kind"] == "state_environmental_permitting_pause"
    assert record["issuing_authority"] == "Governor of Texas"
    assert record["implementing_agency"] == "TCEQ"
    assert record["effective_on"] == "2026-09-21"
    assert record["geographic_scope"] == "Texas statewide"
    assert record["minimum_mw"] is None
    assert "ERCOT" in record["completion_condition"]
    assert "further notice" in record["agency_implementation"]
    assert record["project_applicability"] == "regional_scope_match"
    assert record["project_permit_status"] == "UNKNOWN"
    assert {row["publisher"] for row in record["sources"]} == {
        "Office of the Texas Governor",
        "TCEQ",
    }
    assert all(row["url"].startswith("https://") for row in record["sources"])


@pytest.mark.parametrize(
    "site",
    [
        {"status": "UNKNOWN", "value": None},
        {"status": "CONFLICT", "value": "Austin, TX"},
        {"status": "SUPPORTED", "value": "100 Texas Street, Phoenix, AZ"},
        {"status": "SUPPORTED", "value": "El Paso"},
    ],
)
def test_no_regional_match_from_unknown_conflicting_or_incidental_texas(site):
    record = context(site=site)[0]
    assert record["project_applicability"] == "requires_verification"
    assert record["project_permit_status"] == "UNKNOWN"


@pytest.mark.parametrize("location", ["El Paso, Texas", "Dallas TX 75201", "Austin, TX 78701-1234"])
def test_statewide_scope_does_not_require_ercot_territory(location):
    assert (
        context(site={"status": "SUPPORTED", "value": location})[0]["project_applicability"]
        == "regional_scope_match"
    )


def test_policy_not_project_denial_and_does_not_mutate_site():
    site = {"status": "SUPPORTED", "value": "Austin, TX", "evidence": [{"id": "a"}]}
    result = context(site=site)
    result[0]["sources"].clear()
    assert context()[0]["sources"]
    assert site == {"status": "SUPPORTED", "value": "Austin, TX", "evidence": [{"id": "a"}]}
    assert "denial" in context()[0]["limitations"]


def test_directive_is_not_backdated():
    assert context(as_of=date(2026, 9, 20)) == []


@pytest.mark.parametrize("asset_type", ["compressor_station", "upstream_well"])
def test_other_industries_do_not_receive_data_center_policy(asset_type):
    assert context(asset_type=asset_type) == []


def test_unknown_asset_stays_unverified():
    assert context(asset_type="unknown")[0]["project_applicability"] == "requires_verification"
