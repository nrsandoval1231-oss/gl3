import pytest

from gridlens.intelligence.project_identity import (
    incoming_match_keys,
    location_match_key,
    project_match_keys,
    same_physical_site,
    site_match_key,
)

SITES = [
    "100 Main Street, Austin, TX",
    "100 MAIN ST Austin TX",
    "Site address: 100 Main Street, Austin, TX",
    "200 Oak Road, Houston, TX",
    "Austin, TX",
    "",
    None,
    "Parcel 12 lot 4",
    "12 Elm Court, Reno, NV and 14 Elm Court, Reno, NV",
]


@pytest.mark.parametrize("left", SITES)
@pytest.mark.parametrize("right", SITES)
def test_site_key_is_exactly_same_physical_site(left, right):
    left_key, right_key = site_match_key(left), site_match_key(right)
    assert same_physical_site(left, right) == (left_key is not None and left_key == right_key)


def test_project_keys_cover_name_alias_site_location_and_asset():
    keys = project_match_keys(
        "Alpha, LLC",
        "100 Main Street, Austin, TX",
        {"project_aliases": ["Alpha One", 3], "asset_identity": ["us_well_api", "1"]},
    )
    assert keys == sorted(
        [
            "n:alpha llc",
            "n:alpha one",
            "s:100 main street austin tx",
            "l:100 main street austin tx",
            'x:["us_well_api", "1"]',
        ]
    )
    assert incoming_match_keys(
        names=["ALPHA one"], sites=["x 100 Main St. Austin"], asset_identity=("us_well_api", "1")
    ) == ["n:alpha one", "s:100 main st", 'x:["us_well_api", "1"]']
    assert location_match_key("Austin, TX") is None


def test_unexpected_shapes_yield_unknown_keys_never_a_guess():
    assert project_match_keys("A", None, {"project_aliases": "Alpha"}) is None
    assert project_match_keys("A", None, {"site": 5}) is None
    assert project_match_keys("A", None, None) == ["n:a"]
