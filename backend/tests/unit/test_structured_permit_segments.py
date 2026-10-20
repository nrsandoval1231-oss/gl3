from datetime import UTC, date, datetime

import httpx
import pytest

from gridlens.ingestion.adapters import boston_permits, socrata_permits
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry


def _definition(source_id: str) -> dict:
    return next(item for item in load_registry() if item["id"] == source_id)


def _response(payload: object) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)


def _seattle_row(row_id: int, day: date) -> dict:
    return {
        "permitnum": f"{row_id:05d}",
        "issueddate": f"{day.isoformat()}T12:00:00.000",
        "description": "Commercial electrical work",
        "permitclassmapped": "Non-Residential",
        "permittypemapped": "Building",
        "permittypedesc": "Commercial",
        "statuscurrent": "Issued",
        "originaladdress1": "1 Main Street",
        "link": "https://services.seattle.gov/permits/1",
    }


def test_socrata_overfull_day_resumes_with_stable_keyset_pages():
    source = _definition("seattle-building-permits")
    today = datetime.now(UTC).date()
    counts = iter((1001, 1001, 1001, 1001))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        if params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": next(counts)}])
        where = params["$where"]
        after = None
        if "permitnum > '" in where:
            after = int(where.split("permitnum > '", 1)[1].split("'", 1)[0])
        first = 1 if after is None else after + 1
        stop = min(first + 1000, 1002)
        return _response([_seattle_row(index, today) for index in range(first, stop)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = socrata_permits.retrieve_collection_segment(
            source, "issue_recent", today, today, {}, client
        )
        second = socrata_permits.retrieve_collection_segment(
            source, "issue_recent", today, today, first["cursor"], client
        )

    assert len(first["records"]) == 1000 and first["partial"] is False
    assert first["cursor"]["scanned"] == 1000
    assert len(second["records"]) == 1 and second["window_complete"] is True
    assert second["cursor"] == {}
    assert all("$offset" not in request.url.params for request in requests)
    assert "permitnum > '01000'" in requests[-2].url.params["$where"]


def test_socrata_modified_lane_keeps_old_issue_date_and_utc_system_field():
    source = _definition("chicago-building-permits")
    today = datetime.now(UTC).date()
    modified_at = f"{today.isoformat()}T10:15:30.123Z"
    row = {
        "id": "42",
        "issue_date": "2020-04-02T00:00:00.000",
        "work_description": "Electrical renovation",
        "work_type": "Electrical Work",
        "permit_type": "PERMIT - RENOVATION/ALTERATION",
        "permit_status": "Issued",
        "street_number": "1",
        "street_direction": "N",
        "street_name": "MAIN ST",
        "permit_": "1",
        "reported_cost": "10000",
        "pin_list": "123",
        ":updated_at": modified_at,
        "application_start_date": None,
        "permit_milestone": "Issued",
    }
    for index in range(1, 16):
        row[f"contact_{index}_type"] = None
        row[f"contact_{index}_name"] = None
    rows = [{**row, "id": row_id} for row_id in ("9", "10")]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        if params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": 2}])
        return _response(rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "modified_recent", today, today, {}, client
        )

    assert result["window_complete"] is True
    assert [record["document_number"] for record in result["records"]] == ["9", "10"]
    assert result["records"][0]["event_date"] == "2020-04-02"
    assert result["records"][0]["permit"]["source_modified_at"] == modified_at
    assert f"{today.isoformat()}T00:00:00.000Z" in requests[0].url.params["$where"]


def test_socrata_count_change_returns_partial_and_rewinds_date_cursor():
    source = _definition("seattle-building-permits")
    today = datetime.now(UTC).date()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.params.get("$select") == "count(*) AS row_count":
            calls += 1
            return _response([{"row_count": 1 if calls == 1 else 2}])
        return _response([_seattle_row(1, today)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_history", today, today, {}, client
        )

    assert result["partial"] is True
    assert result["error_class"] == "ResultCountChanged"
    assert result["cursor"] == {"day": today.isoformat(), "expected": 2, "scanned": 0}
    assert len(result["records"]) == 1


def test_socrata_empty_date_is_complete_without_requesting_rows():
    source = _definition("seattle-building-permits")
    today = datetime.now(UTC).date()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["$select"] == "count(*) AS row_count"
        return _response([{"row_count": 0}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_history", today, today, {}, client
        )

    assert result["records"] == []
    assert result["partial"] is False
    assert result["window_complete"] is True
    assert result["cursor"] == {}
    assert len(requests) == 1


def test_socrata_rejects_unsupported_lane_and_malformed_page():
    source = _definition("boston-building-permits")
    today = datetime.now(UTC).date()
    with httpx.Client(transport=httpx.MockTransport(lambda _: _response([]))) as client:
        with pytest.raises(SourceParseError, match="lane is unsupported"):
            boston_permits.retrieve_collection_segment(
                source, "modified_recent", today, today, {}, client
            )

    source = _definition("seattle-building-permits")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": 1}])
        return _response([{"permitnum": "00001"}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceParseError, match="schema changed"):
            socrata_permits.retrieve_collection_segment(
                source, "issue_history", today, today, {}, client
            )


def _boston_row(row_id: int, day: date) -> dict:
    return {
        "_id": row_id,
        "permitnumber": f"ALT{row_id:05d}",
        "issued_date": f"{day.isoformat()}T12:00:00",
        "worktype": "Electrical",
        "permittypedescr": "Commercial",
        "description": "Electrical renovation",
        "comments": "",
        "applicant": "Applicant",
        "expiration_date": "",
        "status": "Issued",
        "occupancytype": "Commercial",
        "address": "1 Main Street",
        "city": "Boston",
        "state": "MA",
        "declared_valuation": "10000",
        "sq_feet": "1000",
        "property_id": "p-1",
        "parcel_id": "parcel-1",
    }


def test_boston_overfull_day_uses_id_keyset_and_stable_issue_date():
    source = _definition("boston-building-permits")
    today = datetime.now(UTC).date()
    counts = iter((1001, 1001, 1001, 1001))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        sql = request.url.params["sql"]
        if "COUNT(*)" in sql:
            count = next(counts)
            return _response(
                {
                    "success": True,
                    "result": {"records": [{"row_count": count, "unique_permit_numbers": count}]},
                }
            )
        after = int(sql.split("_id > ", 1)[1].split(" ", 1)[0]) if "_id > " in sql else 0
        first = 1 if after == 0 else after + 1
        stop = min(first + 1000, 1002)
        return _response(
            {
                "success": True,
                "result": {"records": [_boston_row(index, today) for index in range(first, stop)]},
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = boston_permits.retrieve_collection_segment(
            source, "issue_recent", today, today, {}, client
        )
        second = boston_permits.retrieve_collection_segment(
            source, "issue_recent", today, today, first["cursor"], client
        )

    assert len(first["records"]) == 1000 and first["cursor"]["after_id"] == 1000
    assert len(second["records"]) == 1 and second["window_complete"] is True
    assert "_id > 1000" in requests[-2].url.params["sql"]
