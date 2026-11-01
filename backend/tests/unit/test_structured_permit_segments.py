import time
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from gridlens.ingestion.adapters import boston_permits, socrata_permits
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.structured_collection import _new_window


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


def _austin_row(row_id: int, day: date) -> dict:
    return {
        "permit_number": f"BP{row_id:05d}",
        "issue_date": f"{day.isoformat()}T12:00:00.000",
        "statusdate": f"{day.isoformat()}T12:30:00.000",
        "description": "Commercial electrical construction",
        "permit_class_mapped": "Commercial",
        "work_class": "Electrical",
        "permit_type_desc": "Electrical Permit",
        "status_current": "Issued",
        "original_address1": "1 Main Street",
        "original_city": "Austin",
        "original_state": "TX",
        "link": "https://data.austintexas.gov/permits/1",
        "project_id": "p-1",
        "total_job_valuation": "10000",
        "total_new_add_sqft": "1000",
    }


def test_modified_recent_window_honors_configured_window_days():
    source = _definition("chicago-building-permits")
    today = datetime.now(UTC).date()
    source["query"]["modified_window_days"] = 2
    assert _new_window("modified_recent", today, 90, source) == (today - timedelta(days=1), today)


def test_rrc_flare_history_bootstraps_ninety_days_in_seven_day_chunks():
    source = _definition("texas-rrc-flare-vent-exceptions")
    today = date(2026, 10, 1)
    start, end = _new_window("issue_history", today, 3, source)
    assert start == today - timedelta(days=89)
    assert end == start + timedelta(days=6)
    recent_start, recent_end = _new_window("issue_recent", today, 3, source)
    assert (recent_start, recent_end) == (date(2026, 9, 29), date(2026, 10, 1))


@pytest.mark.parametrize("lane", ["issue_recent", "modified_recent"])
def test_austin_sparse_recent_range_completes_seven_days_in_one_segment(lane):
    source = _definition("austin-building-permits")
    today = datetime.now(UTC).date()
    start = today - timedelta(days=6)
    rows = [_austin_row(index, start + timedelta(days=index)) for index in range(7)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        if params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": len(rows)}])
        return _response(rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(source, lane, start, today, {}, client)

    assert result["window_complete"] is True
    assert len(result["records"]) == 7
    assert result["cursor"] == {}
    page = next(
        request
        for request in requests
        if request.url.params.get("$select") != "count(*) AS row_count"
    )
    assert f"{start.isoformat()}T00:00:00.000" in page.url.params["$where"]
    assert f"{today.isoformat()}T23:59:59.999" in page.url.params["$where"]


def test_austin_dense_recent_range_shrinks_before_bounded_fetch():
    source = _definition("austin-building-permits")
    today = datetime.now(UTC).date()
    start = today - timedelta(days=6)
    rows = [_austin_row(1, start)]
    count_wheres: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("$select") == "count(*) AS row_count":
            count_wheres.append(params["$where"])
            return _response([{"row_count": 1001 if len(count_wheres) == 1 else 1}])
        return _response(rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_recent", start, today, {}, client
        )

    assert result["window_complete"] is False
    assert result["cursor"] == {"day": today.isoformat()}
    assert len(count_wheres) == 3  # Full range, shortened range, exact before/after check.
    assert f"{today.isoformat()}T23:59:59.999" in count_wheres[0]
    assert f"{(today - timedelta(days=1)).isoformat()}T23:59:59.999" in count_wheres[1]


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
    # Chicago IDs are opaque text (e.g. N2990649); the publisher orders them as text.
    rows = [{**row, "id": row_id} for row_id in ("10", "9")]
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
    assert [record["document_number"] for record in result["records"]] == ["10", "9"]
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
            return _response([{"row_count": 2}])
        return _response(
            [
                {"permitnum": "00001"},
                _seattle_row(2, today),
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_history", today, today, {}, client
        )
    assert result["partial"] is True
    assert result["partial_reason"] == "malformed_row"
    assert result["rejected_count"] == 1
    assert result["rejected_records"][0]["identity"] == "00001"
    assert [record["document_number"] for record in result["records"]] == ["00002"]
    assert result["cursor"] == {"day": today.isoformat(), "expected": 2, "scanned": 0}
    assert result["window_complete"] is False


def test_socrata_range_keyset_resumes_with_fixed_bounds_and_ordered_date():
    source = _definition("seattle-building-permits")
    start = datetime.now(UTC).date() - timedelta(days=1)
    end = start + timedelta(days=1)
    after_value = f"{start.isoformat()}T12:00:00.000"
    cursor = {
        "day": start.isoformat(),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "expected": 1001,
        "scanned": 1000,
        "after_value": after_value,
        "after_id": "01000",
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": 1001}])
        return _response([_seattle_row(1001, end)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_recent", start, end, cursor, client
        )

    assert result["window_complete"] is True
    assert result["cursor"] == {}
    assert "permitnum > '01000'" in requests[-2].url.params["$where"]
    assert f"{start.isoformat()}T00:00:00.000" in requests[-2].url.params["$where"]
    assert f"{end.isoformat()}T23:59:59.999" in requests[-2].url.params["$where"]


def test_socrata_range_count_mutation_resets_same_fixed_range():
    source = _definition("seattle-building-permits")
    start = datetime.now(UTC).date() - timedelta(days=1)
    end = start + timedelta(days=1)
    counts = iter((1, 2))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("$select") == "count(*) AS row_count":
            return _response([{"row_count": next(counts)}])
        return _response([_seattle_row(1, start)])

    cursor = {
        "day": start.isoformat(),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "expected": 1,
        "scanned": 0,
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = socrata_permits.retrieve_collection_segment(
            source, "issue_recent", start, end, cursor, client
        )

    assert result["partial"] is True
    assert result["error_class"] == "ResultCountChanged"
    assert result["cursor"] == {**cursor, "expected": 2, "scanned": 0}
    assert len(requests) == 3  # Count before, one bounded page, count after.


def test_socrata_range_honors_deadline_before_public_request():
    source = _definition("austin-building-permits")
    today = datetime.now(UTC).date()
    requests: list[httpx.Request] = []

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), _response([{"row_count": 0}]))[1]
        )
    ) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            socrata_permits.retrieve_collection_segment(
                source,
                "issue_recent",
                today,
                today,
                {},
                client,
                deadline=time.monotonic() - 1,
            )
    assert requests == []


def test_socrata_range_rejects_oversized_count_response():
    source = _definition("austin-building-permits")
    today = datetime.now(UTC).date()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-length": str(2_000_001)},
            content=b"[]",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceParseError, match="count failed: ResponseTooLarge"):
            socrata_permits.retrieve_collection_segment(
                source, "issue_recent", today, today, {}, client
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


def test_flare_collection_day_uses_texas_calendar_at_utc_midnight():
    from gridlens.ingestion.structured_collection import collection_day

    source = _definition("texas-rrc-flare-vent-exceptions")
    assert collection_day(source, datetime(2026, 11, 1, 1, tzinfo=UTC)) == date(2026, 10, 31)
    assert collection_day(source, datetime(2026, 11, 1, 7, tzinfo=UTC)) == date(2026, 11, 1)
