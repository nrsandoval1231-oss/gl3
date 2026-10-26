from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.freeze_workbook_candidates import select_candidates  # noqa: E402


def _row(state: str, index: int) -> dict:
    row_id = f"{state}-{index}"
    state_offset = {"TX": 0.0, "OK": 0.05, "NM": 0.1}[state]
    return {
        "filename": "actual-workbook.xlsx",
        "content_hash": "a" * 64,
        "batch_id": f"batch-{state}",
        "id": row_id,
        "sheet": "Projects",
        "row_number": index + 2,
        "row_kind": "project",
        "normalized": {
            "state": state,
            "project_name": f"Site {state} {index}",
            "company_name": f"Developer {index}",
            "facility_demand_mw": 1 + index,
        },
        "raw": {
            "Latitude": 30 + state_offset + index / 1000,
            "Longitude": -100 - state_offset - index / 1000,
        },
        "errors": [],
        "match_status": "unmatched",
        "active": False,
    }


def test_frozen_selection_is_stable_and_keeps_each_selected_row_power():
    rows = [
        *(_row("TX", index) for index in range(15)),
        *(_row("OK", index) for index in range(7)),
        *(_row("NM", index) for index in range(7)),
    ]

    selected = select_candidates(rows)
    reordered = select_candidates(list(reversed(rows)))

    assert [item["staged_row_id"] for item in selected] == [
        item["staged_row_id"] for item in reordered
    ]
    expected_power = {row["id"]: row["normalized"]["facility_demand_mw"] for row in rows}
    assert len(selected) == 25
    assert all(
        item["facility_power_mw_assertion"] == expected_power[item["staged_row_id"]]
        for item in selected
    )
    assert {item["selection_stratum"] for item in selected} == {"TX", "OK", "NM"}
