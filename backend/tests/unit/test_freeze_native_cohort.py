from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.freeze_native_cohort import (  # noqa: E402
    _required_mw_interval,
    _temporary_activity_supported,
    select_frozen_candidates,
)


def _candidate(index: int, *, state: str | None = None, asset: str | None = None) -> dict:
    state = state or ("TX", "OK", "NM")[index % 3]
    asset = asset or ("data_center", "midstream", "industrial")[(index // 3) % 3]
    return {
        "project_id": f"project-{index:03d}",
        "name": f"Site {index}",
        "location": f"{100 + index} Main St, Sample City, {state}",
        "region_state": state,
        "region_status": "ELIGIBLE",
        "asset_type": asset,
        "source_evidence": [
            {
                "url": f"https://public.example.gov/projects/{index}",
                "observation_hash": f"source-hash-{index}",
                "evidence_hash": f"evidence-hash-{index}",
            }
        ],
        "active_power_needs": [],
        "buying_chain_claims": [],
    }


def test_native_freeze_is_stable_stratified_and_independent_of_contact_outcomes():
    candidates = [_candidate(index) for index in range(45)]
    selected = select_frozen_candidates(candidates, limit=25)
    shuffled = select_frozen_candidates(list(reversed(candidates)), limit=25)
    changed_outcomes = [
        {
            **candidate,
            "active_power_needs": [{"required_mw": "100", "activity_key": "temporary-power"}],
            "buying_chain_claims": [
                {"person_name": "Buyer", "public_contacts": [{"email": "buyer@example.com"}]}
            ],
        }
        for candidate in candidates
    ]
    rescored = select_frozen_candidates(changed_outcomes, limit=25)

    selected_ids = [candidate["project_id"] for candidate in selected]
    assert len(selected) == 25
    assert selected_ids == [candidate["project_id"] for candidate in shuffled]
    assert selected_ids == [candidate["project_id"] for candidate in rescored]
    assert {candidate["region_state"] for candidate in selected} == {"TX", "OK", "NM"}
    assert len({candidate["selection_stratum"] for candidate in selected}) > 3
    assert len({candidate["location_assertion_key"] for candidate in selected}) == 25


def test_native_freeze_collapses_precise_site_duplicate_and_skips_uncited_rows():
    original = _candidate(1)
    duplicate = {
        **_candidate(2),
        "project_id": "duplicate-project",
        "name": "Alternate name at same site",
        "location": original["location"],
        "region_state": original["region_state"],
    }
    uncited = {**_candidate(3), "project_id": "uncited", "source_evidence": []}
    out_of_scope = {**_candidate(4), "project_id": "out-of-scope", "region_state": "GA"}

    selected = select_frozen_candidates([original, duplicate, uncited, out_of_scope], limit=25)

    assert len(selected) == 1
    assert selected[0]["project_id"] in {original["project_id"], duplicate["project_id"]}
    assert selected[0]["qualification_status"] == "NOT_ADJUDICATED"


def test_county_code_location_is_coarse_and_does_not_collapse_distinct_permit_records():
    first = {
        **_candidate(10),
        "name": "Texas W-1 permit 0919088",
        "location": "RRC county code 317, Texas",
    }
    second = {
        **_candidate(11),
        "name": "Texas W-1 permit 0919206",
        "location": "RRC county code 317, Texas",
    }
    selected = select_frozen_candidates([first, second], limit=25)
    assert len(selected) == 2
    assert all("county_assertion" in item["location_assertion_key"] for item in selected)


def test_only_source_linked_need_power_with_units_and_explicit_bridge_rationale_counts():
    assert _required_mw_interval("0.3 MW") == (Decimal("0.3"), Decimal("0.3"))
    assert _required_mw_interval("300 kW") == (Decimal("0.300"), Decimal("0.300"))
    assert _required_mw_interval("0.2 to 0.4 MW") == (Decimal("0.2"), Decimal("0.4"))
    assert _required_mw_interval("facility demand 3 MW") is None
    assert not _temporary_activity_supported(
        [{"activity_key": "compression", "rationale": "Compression project"}]
    )
    assert not _temporary_activity_supported(
        [{"activity_key": "bridge-power", "rationale": "Power needs under review"}]
    )
    assert _temporary_activity_supported(
        [
            {
                "activity_key": "bridge-power",
                "rationale": "Temporary bridge power while grid upgrades finish",
            }
        ]
    )
