from uuid import uuid4

import pytest

from gridlens.domain.ercot_impact_rfi import RFIRecord, classify_scope
from gridlens.domain.signal_admission import admit_standalone, source_origin


def record(**updates):
    return RFIRecord.model_validate(
        {
            "publication_state": "public_project_disclosure",
            "project_identity_key": "test-site",
            "evidence_id": str(uuid4()),
            "evidence_hash": "a" * 64,
            "claims": {},
            **updates,
        }
    )


@pytest.mark.parametrize(
    "mw,expected",
    [
        (24.9, "OUTSIDE"),
        (25, "MEDIUM_REQUIRED"),
        (74.9, "MEDIUM_REQUIRED"),
        (75, "BATCH_ZERO_REQUIRED"),
    ],
)
def test_thresholds(mw, expected):
    assert (
        classify_scope(
            peak_requested_load_mw=mw,
            ercot_region=True,
            not_yet_energized=True,
            substantiated_load=True,
            medium_load_reported=True,
            batch_zero_classification="base_load",
        )
        == expected
    )


def test_unknown_is_not_false_and_newly_substantiated_is_voluntary():
    assert classify_scope(peak_requested_load_mw=30) == "UNKNOWN"
    assert (
        classify_scope(
            peak_requested_load_mw=30,
            ercot_region=True,
            not_yet_energized=True,
            substantiated_load=True,
            medium_load_reported=False,
            newly_substantiated=True,
        )
        == "MEDIUM_VOLUNTARY"
    )


def test_schema_and_aggregate_cannot_contain_project_answers():
    for state in ("public_question_schema", "public_aggregate", "public_anonymized"):
        with pytest.raises(ValueError):
            record(
                publication_state=state,
                claims={"developer": {"value": "Example", "quote": "Example"}},
            )
        with pytest.raises(ValueError):
            record(publication_state=state)


def test_confidential_response_not_supported():
    with pytest.raises(ValueError):
        record(publication_state="restricted_response")


@pytest.mark.parametrize("value", [[], {}, True, 75])
def test_batch_zero_classification_rejects_nontext(value):
    with pytest.raises(ValueError):
        record(claims={"batch_zero_classification": {"value": value, "quote": "base load"}})


def test_metadata_requires_quote_and_known_field():
    with pytest.raises(ValueError):
        record(claims={"developer": {"value": "Example", "quote": ""}})
    with pytest.raises(ValueError):
        record(claims={"invented_field": {"value": "Example", "quote": "Example"}})
    assert record(
        claims={"regional_water_planning_group": {"value": "Region C", "quote": "Region C"}}
    )


@pytest.mark.parametrize(
    "method",
    [
        "ercot-impact-rfi-schema",
        "ercot-impact-rfi-aggregate",
        "ercot-impact-rfi-anonymized",
        "ercot-impact-rfi-project",
    ],
)
def test_rfi_context_cannot_admit_opportunity(method):
    result = admit_standalone(
        source_id="ercot-impact",
        family="ercot-impact-rfi",
        retrieval_method=method,
        accepted=True,
        activity="bridge-power",
        title="Example interconnection",
        abstract="25 MW",
        dated=True,
        citation_url="https://www.ercot.com/",
        identified_project=True,
    )
    assert not result.admitted
    assert "RFI" in source_origin("ercot-impact-rfi", method)
