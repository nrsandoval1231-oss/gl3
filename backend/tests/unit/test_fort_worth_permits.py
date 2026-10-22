import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.fort_worth_permits import (
    QUERY_URL,
    SOURCE_ID,
    group_permits,
    parse_rows,
    query_url,
    record,
    retrieve,
)

FIXTURE = (Path(__file__).parents[1] / "fixtures" / "fort-worth-permits-excerpt.json").read_bytes()
TODAY = date(2026, 10, 14)
SOURCE = {"id": SOURCE_ID, "endpoint": QUERY_URL, "query": {"window_days": 90}}


def permits():
    return {permit["permit_no"]: permit for permit in group_permits(parse_rows(FIXTURE))}


def test_rows_group_per_permit_and_drop_placeholder_addresses():
    grouped = permits()
    assert sorted(grouped) == ["PB26-08604", "PB26-11057", "PB26-11109", "PB26-13010"]
    acs = grouped["PB26-08604"]
    assert acs["project"] == "ACS Data Center - DFW 12"
    assert acs["addresses"] == ["10200 HICKS FIELD RD, Fort Worth, TX 76131"]
    assert acs["owners"] == ["ACS DC HICKS FIELD ROAD LLC"]
    assert acs["filed"] == "2026-06-16" and acs["job_value"] == "327000000"
    edged = grouped["PB26-11109"]
    assert edged["work"] == "488,628 SF 196MW data center"
    assert len(edged["addresses"]) == 2


def test_new_data_center_permit_is_a_signal_with_reported_mw():
    item = record(permits()["PB26-11109"])
    assert evaluator_version(item) == "fort-worth-data-center-permit-v1"
    result = assess_permit(item, as_of=TODAY)
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["event_date"] == "2026-08-03"
    assert "not an issued permit" in result["reason"]
    assert any("196" in fact for fact in result["reported_power_facts"])


def test_substation_is_accepted_and_renovation_is_rejected():
    substation = assess_permit(record(permits()["PB26-11057"]), as_of=TODAY)
    assert substation["decision"] == "accepted"
    assert substation["action"] == "data-center substation permit"
    renovation = assess_permit(record(permits()["PB26-13010"]), as_of=TODAY)
    assert renovation["decision"] == "rejected" and "Remodel permit" in renovation["reason"]


def test_terminal_status_and_out_of_scope_subtypes_are_rejected():
    for status in ("Cancelled", "Void", "Withdrawn", "Expired"):
        permit = {**permits()["PB26-11109"], "status": status}
        result = assess_permit(record(permit), as_of=TODAY)
        assert result["decision"] == "rejected" and status in result["reason"]
    demolition = {**permits()["PB26-11109"], "subtype": "Demolition"}
    assert assess_permit(record(demolition), as_of=TODAY)["decision"] == "rejected"
    assert record(permits()["PB26-11109"])["publication_date"] is None


def test_malformed_features_fail_the_run():
    for bad in ([1], [{"attributes": None}], [{"attributes": {"Permit_No": ""}}]):
        with pytest.raises(SourceParseError, match="malformed"):
            parse_rows(json.dumps({"features": bad}).encode())


def test_retrieve_queries_the_window_and_fails_on_truncation():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=FIXTURE)

    records = retrieve(SOURCE, httpx.Client(transport=httpx.MockTransport(handler)), today=TODAY)
    assert {r["permit"]["row_id"] for r in records} == {
        "FTW-PB26-08604",
        "FTW-PB26-11057",
        "FTW-PB26-11109",
        "FTW-PB26-13010",
    }
    assert seen == [query_url(date(2026, 7, 16))]
    assert "File_Date+%3E%3D+DATE+%272026-07-16%27" in seen[0]
    truncated = json.dumps({"exceededTransferLimit": True, "features": []}).encode()
    with pytest.raises(SourceParseError, match="row limit"):
        parse_rows(truncated)
    with pytest.raises(SourceParseError, match="window"):
        retrieve({**SOURCE, "query": {"window_days": 365}}, httpx.Client())
