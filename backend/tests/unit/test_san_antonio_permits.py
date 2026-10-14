import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.san_antonio_permits import (
    RESOURCES,
    SEARCH_URL,
    SOURCE_ID,
    group_permits,
    parse_rows,
    record,
    retrieve,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
ISSUED = (FIXTURES / "san-antonio-issued-excerpt.json").read_bytes()
APPLICATIONS = (FIXTURES / "san-antonio-applications-excerpt.json").read_bytes()
TODAY = date(2026, 10, 14)
SOURCE = {"id": SOURCE_ID, "endpoint": SEARCH_URL, "query": {"window_days": 90}}


def issued():
    return {p["permit_no"]: p for p in group_permits(parse_rows(ISSUED), "issued")}


def test_trade_rows_group_per_permit_and_state_plane_coordinates_are_dropped():
    permits = issued()
    vantage = permits["COM-SIT-PMT25-40100446"]
    assert vantage["types"] == ["Comm Sitework Permit", "Electrical General Permit"]
    assert vantage["valuation"] == 3950000.0 and vantage["issued"] == "2026-02-13"
    assert (vantage["latitude"], vantage["longitude"]) == (29.477842, -98.698171)
    sat14 = permits["COM-RW-PMT26-41100031"]
    assert sat14["latitude"] is None and sat14["valuation"] == 90801000.0


def test_issued_new_data_center_permit_is_a_signal():
    item = record(issued()["COM-RW-PMT26-41100031"])
    assert evaluator_version(item) == "san-antonio-data-center-permit-v1"
    result = assess_permit(item, as_of=TODAY)
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["event_date"] == "2026-09-29"
    assert result["location"] == "3545 WISEMAN BLVD, San Antonio, TX 78251"
    assert "issued permit authorizes the work" in result["reason"]
    assert item["publication_date"] is None


def test_trade_application_without_work_type_is_not_admitted():
    apps = {p["permit_no"]: p for p in group_permits(parse_rows(APPLICATIONS), "applications")}
    result = assess_permit(record(apps["MEP-TRD-APP26-33118065"]), as_of=TODAY)
    assert result["decision"] == "rejected"


def test_retrieve_keeps_window_and_names_and_fails_on_partial_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        return httpx.Response(200, content=ISSUED if RESOURCES["issued"] in url else APPLICATIONS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = retrieve(SOURCE, client, today=TODAY)
    # Vantage (issued Feb), UHS (2025) and Bexar (submitted June 30) fall outside the
    # 90-day window; Babcock says "data processing center", not data center.
    assert [r["permit"]["row_id"] for r in records] == ["SAT-COM-RW-PMT26-41100031"]
    partial = json.loads(ISSUED)
    partial["result"]["total"] = 99
    with pytest.raises(SourceParseError, match="matched 99 rows"):
        parse_rows(json.dumps(partial).encode())
    with pytest.raises(SourceParseError, match="malformed"):
        parse_rows(json.dumps({"success": True, "result": {"records": [1], "total": 1}}).encode())
