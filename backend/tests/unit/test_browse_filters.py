from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from gridlens.api.app import (
    _filter_opportunity_summaries,
    _normalized_browse_filters,
    _validate_browse_query,
)
from gridlens.domain.commercial_triage import _priority


def _filters(**updates):
    values = {
        "tier": "Signal",
        "decision": "ALL",
        "geography": None,
        "industry": None,
        "activity": None,
        "timing": None,
        "mw_status": None,
        "mw_min": None,
        "mw_max": None,
        "priority_segment": None,
        "search": None,
    }
    values.update(updates)
    return _normalized_browse_filters(**values)


def _summary(**updates):
    return {
        "id": uuid4(),
        "location": "Chicago, IL",
        "asset_type": "data_center",
        "activity": "facility-expansion",
        "start_window": "6-12 months",
        "required_mw": "300 kW to 1 MW",
        "_priority_segment": 0,
        **updates,
    }


def test_dimensions_use_exact_normalized_project_and_need_values():
    rows = [
        _summary(),
        _summary(location=None),
        _summary(asset_type="unmapped stored asset type", activity="other"),
    ]
    assert _filter_opportunity_summaries(rows, _filters(geography="  ＣＨＩＣＡＧＯ,   IL ")) == [
        rows[0],
        rows[2],
    ]
    assert _filter_opportunity_summaries(rows, _filters(geography="UNKNOWN")) == [rows[1]]
    assert _filter_opportunity_summaries(rows, _filters(industry="unmapped stored asset type")) == [
        rows[2]
    ]
    assert _filter_opportunity_summaries(rows, _filters(activity="facility-expansion")) == [
        rows[0],
        rows[1],
    ]


def test_timing_and_mw_filters_use_effective_summary_only_and_inclusive_overlap():
    rows = [
        _summary(),
        _summary(start_window="Unknown", required_mw=None),
        _summary(start_window=None, required_mw="prose about demand"),
    ]
    assert _filter_opportunity_summaries(rows, _filters(timing="KNOWN")) == [rows[0]]
    assert _filter_opportunity_summaries(rows, _filters(timing="UNKNOWN")) == [rows[1], rows[2]]
    assert _filter_opportunity_summaries(rows, _filters(mw_status="KNOWN")) == [rows[0]]
    assert _filter_opportunity_summaries(rows, _filters(mw_status="UNKNOWN")) == [rows[1], rows[2]]
    assert _filter_opportunity_summaries(rows, _filters(mw_min="0.5", mw_max="0.5")) == [rows[0]]
    assert _filter_opportunity_summaries(rows, _filters(mw_max="0.2999")) == []


def test_priority_segment_is_exact_value_and_workflow_status_does_not_filter():
    rows = [_summary(_priority_segment=0), _summary(_priority_segment=8)]
    assert _filter_opportunity_summaries(rows, _filters(priority_segment="0")) == [rows[0]]
    statuses = [rows[0] | {"workflow_status": "Closed"}, rows[1] | {"workflow_status": "New"}]
    assert _filter_opportunity_summaries(statuses, _filters()) == statuses
    for value in ("high", "9", "1.5", "-1"):
        with pytest.raises(HTTPException) as invalid:
            _filters(priority_segment=value)
        assert invalid.value.status_code == 422


def test_canonical_priority_filter_supports_each_existing_segment_without_new_bands():
    cases = [
        {"asset_type": "data_center", "_priority_features": {"lifecycle_phase": True}},
        {
            "asset_type": "data_center",
            "_priority_features": {
                "lifecycle_phase": True,
                "evidence_commissioning": True,
            },
        },
        {"activity": "natural-gas", "_priority_features": {"lifecycle_producing": True}},
        {"activity": "construction", "_priority_features": {"evidence_scope": True}},
        {"asset_type": "data_center", "_priority_features": {"evidence_commissioning": True}},
        {"asset_type": "data_center", "_priority_features": {"evidence_construction": True}},
        {"asset_type": "data_center", "_priority_features": {}},
        {"activity": "oil-field", "_priority_features": {}},
        {"activity": "construction", "_priority_features": {}},
    ]
    segments = []
    for index, features in enumerate(cases):
        row = {
            "id": uuid4(),
            "project_id": uuid4(),
            "name": f"Synthetic priority {index}",
            "activity": "construction",
            "location": "Test City",
            **features,
        }
        segments.append(_priority(row)[0])
    assert segments == list(range(9))
    rows = [_summary(_priority_segment=segment) for segment in segments]
    selected_counts = [
        len(_filter_opportunity_summaries(rows, _filters(priority_segment=str(segment))))
        for segment in range(9)
    ]
    assert selected_counts == [1] * 9


@pytest.mark.parametrize(
    "updates",
    [
        {"timing": "NEXT_QUARTER"},
        {"mw_status": "UNKNOWN", "mw_min": "0"},
        {"mw_min": "2", "mw_max": "1"},
        {"mw_min": "NaN"},
        {"tier": "O&G"},
    ],
)
def test_unsupported_or_malformed_filter_values_fail_closed(updates):
    with pytest.raises(HTTPException) as invalid:
        _filters(**updates)
    assert invalid.value.status_code == 422


def test_unrecognized_query_keys_do_not_silently_bypass_filters():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/opportunities",
        "root_path": "",
        "scheme": "http",
        "query_string": b"status=QUALIFIED",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 123),
    }
    with pytest.raises(HTTPException) as invalid:
        _validate_browse_query(Request(scope))
    assert invalid.value.status_code == 422
    assert invalid.value.detail["unsupported"] == ["status"]
