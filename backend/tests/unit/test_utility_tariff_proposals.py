"""Prevent proposal metadata from becoming operative/project-specific obligations."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def parse(payload):
    from gridlens.domain.utility_tariff_proposals import TariffProposal

    return TariffProposal.model_validate(payload)


@pytest.fixture
def record():
    return json.loads(
        (Path(__file__).parents[3] / "config/tariffs/xcel-sps-tx-60332.json").read_text()
    )


def test_proposal_roundtrip_preserves_status_dates_and_qualified_scope(record):
    proposal = parse(record)
    output = json.loads(proposal.model_dump_json())
    assert output == record
    assert output["status"] == "proposed_pending"
    assert output["applicability"]["threshold_mw"] == 75
    assert output["applicability"]["territory"] == "SPS Texas retail service territory"
    assert output["proposed_effective_date"] == "2026-10-30"
    assert output["filing_date"] == "2026-09-25"
    assert output["announcement_date"] == "2026-09-28"


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "approved"),
        ("effective_date", "2026-10-30"),
        ("project_id", "some-project"),
        ("customer_committed", True),
    ],
)
def test_rejects_operative_status_and_project_facts(record, field, value):
    record[field] = value
    with pytest.raises(ValidationError):
        parse(record)


def test_unknown_applicability_is_not_filled_from_other_rules(record):
    record["applicability"] = None
    assert parse(record).applicability is None


@pytest.mark.parametrize("field", ["source_id", "location"])
def test_missing_or_dangling_citation_is_rejected(record, field):
    record["terms"][0]["citation"][field] = "missing" if field == "source_id" else " "
    with pytest.raises(ValidationError):
        parse(record)


def test_announcement_cannot_substantiate_threshold_or_territory(record):
    record["applicability"]["citation"]["source_id"] = "announcement"
    with pytest.raises(ValidationError, match="filing"):
        parse(record)


@pytest.mark.parametrize("mw", [0, -75, True, "75", float("inf")])
def test_threshold_rejects_invalid_values(record, mw):
    record["applicability"]["threshold_mw"] = mw
    with pytest.raises(ValidationError):
        parse(record)


def test_duplicate_terms_and_sources_do_not_silently_overwrite(record):
    record["terms"].append(record["terms"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        parse(record)


def test_future_rate_design_remains_distinct_from_proposed_commercial_terms(record):
    output = parse(record).model_dump()
    phases = {term["key"]: term["stage"] for term in output["terms"]}
    assert phases["incremental_cost_allocation"] == "future_rate_case_intent"
    assert phases["direct_interconnection_costs"] == "proposed_tariff"
    assert phases["minimum_bill"] == "proposed_tariff"


def test_requested_effective_date_passing_does_not_activate(record):
    record["as_of_date"] = "2026-11-01"
    assert parse(record).status == "proposed_pending"


def test_duplicate_source_ids_are_rejected(record):
    record["sources"].append(record["sources"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        parse(record)


def test_unretrieved_future_source_cannot_support_past_review(record):
    record["sources"][0]["retrieved_date"] = "2026-10-08"
    with pytest.raises(ValidationError, match="dates"):
        parse(record)


def test_announcement_is_not_upgraded_to_filed_economic_terms(record):
    record["terms"][0]["citation"]["source_id"] = "announcement"
    with pytest.raises(ValidationError, match="filing"):
        parse(record)


def test_real_loader_rejects_unknown_fields_and_reads_reviewed_record(record, tmp_path):
    from gridlens.domain.utility_tariff_proposals import load_proposal

    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(record))
    assert load_proposal(path).status == "proposed_pending"
    record["applicability"]["automatic_eligibility"] = True
    path.write_text(json.dumps(record))
    with pytest.raises(ValidationError):
        load_proposal(path)
