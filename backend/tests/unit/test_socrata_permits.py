from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.socrata_permits import MAPS, retrieve
from gridlens.ingestion.registry import load_registry


def source(source_id: str):
    return next(row for row in load_registry() if row["id"] == source_id)


def test_city_maps_and_counted_ordered_pagination():
    assert MAPS["austin-building-permits"]["row"] == "permit_number"
    assert MAPS["seattle-building-permits"]["row"] == "permitnum"
    assert MAPS["chicago-building-permits"]["row"] == "id"
    requests = []
    today = datetime.now(UTC).date().isoformat() + "T00:00:00.000"
    rows = [
        {
            "permit_number": f"P-{i:04}",
            "issue_date": today,
            "description": "New manufacturing facility construction",
            "permit_type_desc": "Building Permit",
            "permit_class_mapped": "Commercial",
            "statusdate": datetime.now(UTC).date().isoformat(),
            "work_class": "New",
            "status_current": "Active",
            "original_address1": "1 Industry Way",
            "original_city": "AUSTIN",
            "original_state": "TX",
            "project_id": str(i),
            "link": {"url": "https://abc.austintexas.gov/permit/1"},
        }
        for i in range(1001)
    ]

    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        if "$select" in params:
            return httpx.Response(200, json=[{"row_count": "1001"}])
        offset = int(params["$offset"])
        return httpx.Response(200, json=rows[offset : offset + 1000])

    result = retrieve(
        source("austin-building-permits"), httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert len(result) == 1001
    assert [int(req["$offset"]) for req in requests if "$offset" in req] == [0, 1000]
    assert requests[1]["$order"] == "issue_date ASC,permit_number ASC"
    assert result[0]["event_date"] == today[:10]
    assert result[0]["permit"]["row_id"] == "P-0000"


def test_old_austin_permit_status_change_is_included_by_official_status_date():
    definition = source("austin-building-permits")
    row = {
        "permit_number": "OLD-1",
        "issue_date": "2020-05-10",
        "statusdate": datetime.now(UTC).date().isoformat(),
        "description": "New industrial facility construction",
        "permit_type_desc": "Building Permit",
        "permit_class_mapped": "Commercial",
        "status_current": "Active",
        "original_address1": "1 Industry Way",
        "original_city": "Austin",
        "original_state": "TX",
    }
    requests = []

    def retrieve_row():
        def handler(request):
            params = dict(request.url.params)
            requests.append(params)
            return httpx.Response(
                200,
                json=[{"row_count": "1"}] if "$select" in params else [dict(row)],
            )

        return retrieve(definition, httpx.Client(transport=httpx.MockTransport(handler)))[0]

    active = retrieve_row()
    row["status_current"] = "Withdrawn"
    withdrawn = retrieve_row()
    assert active["event_date"] == "2020-05-10"
    assert active["permit"]["status"] == "Active"
    assert withdrawn["permit"]["status"] == "Withdrawn"
    assert active["source_hash"] != withdrawn["source_hash"]
    assert all("statusdate >=" in request["$where"] for request in requests)
    assert all("issue_date IS NOT NULL" in request["$where"] for request in requests)


def test_recent_austin_permit_allows_socrata_to_omit_null_statusdate():
    definition = source("austin-building-permits")
    row = {
        "permit_number": "RECENT-NULL-STATUSDATE",
        "issue_date": datetime.now(UTC).date().isoformat(),
        "description": "New industrial facility construction",
        "permit_type_desc": "Building Permit",
        "permit_class_mapped": "Commercial",
        "status_current": "Active",
        "original_address1": "2 Industry Way",
        "original_city": "Austin",
        "original_state": "TX",
    }

    def handler(request):
        params = dict(request.url.params)
        return httpx.Response(
            200,
            json=[{"row_count": "1"}] if "$select" in params else [row],
        )

    result = retrieve(definition, httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(result) == 1
    assert result[0]["permit"]["status"] == "Active"


def test_old_chicago_permit_status_change_uses_selected_socrata_updated_at():
    definition = source("chicago-building-permits")
    row = {
        "id": "OLD-CHICAGO-1",
        "issue_date": "2020-05-10T00:00:00",
        ":updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "work_description": "New industrial facility construction",
        "work_type": "NEW CONSTRUCTION",
        "permit_type": "PERMIT - NEW CONSTRUCTION",
        "permit_status": "ACTIVE",
        "street_number": "1",
        "street_direction": "",
        "street_name": "INDUSTRY WAY",
    }
    page_requests = []

    def retrieve_row():
        def handler(request):
            params = dict(request.url.params)
            if params.get("$select") == "count(*) AS row_count":
                return httpx.Response(200, json=[{"row_count": "1"}])
            page_requests.append(params)
            return httpx.Response(200, json=[dict(row)])

        return retrieve(definition, httpx.Client(transport=httpx.MockTransport(handler)))[0]

    active = retrieve_row()
    row["permit_status"] = "EXPIRED"
    row[":updated_at"] = (
        (datetime.now(UTC) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    expired = retrieve_row()
    assert active["event_date"] == "2020-05-10"
    assert active["permit"]["status"] == "ACTIVE"
    assert active["permit"]["source_modified_at"]
    assert expired["permit"]["status"] == "EXPIRED"
    assert active["source_hash"] != expired["source_hash"]
    assert all(
        "work_description" in params["$select"]
        and ":updated_at" in params["$select"]
        and "*" not in params["$select"]
        for params in page_requests
    )
    assert all(":updated_at >=" in params["$where"] for params in page_requests)
    assert all(":updated_at <=" in params["$where"] for params in page_requests)
    assert all("issue_date IS NOT NULL" in params["$where"] for params in page_requests)


@pytest.mark.parametrize("mutation", ["duplicate", "out_of_window", "empty_count", "off_host"])
def test_adapter_fails_closed_on_inconsistent_or_unsafe_result(mutation):
    row = {
        "permit_number": "P-1",
        "issue_date": datetime.now(UTC).date().isoformat(),
        "description": "Construction of manufacturing facility",
        "permit_type_desc": "Building Permit",
        "permit_class_mapped": "Commercial",
        "statusdate": datetime.now(UTC).date().isoformat(),
        "work_class": "New",
        "original_address1": "1 Main St",
        "original_city": "Austin",
        "original_state": "TX",
        "link": {"url": "https://attacker.example/fake"},
    }

    def handler(request):
        params = dict(request.url.params)
        if "$select" in params:
            return httpx.Response(
                200, json=[{"row_count": "0" if mutation == "empty_count" else "1"}]
            )
        if mutation == "duplicate":
            return httpx.Response(200, json=[row, row])
        if mutation == "out_of_window":
            row["issue_date"] = "2020-01-01"
            row["statusdate"] = "2020-01-01"
        return httpx.Response(200, json=[row])

    if mutation == "off_host":
        value = retrieve(
            source("austin-building-permits"), httpx.Client(transport=httpx.MockTransport(handler))
        )[0]
        assert value["html_url"] == source("austin-building-permits")["endpoint"]
    else:
        with pytest.raises(SourceParseError):
            retrieve(
                source("austin-building-permits"),
                httpx.Client(transport=httpx.MockTransport(handler)),
            )


@pytest.mark.parametrize(
    "description,status,expected",
    [
        (
            "Convert existing office tower into a data center with new power and cooling systems",
            "Issued",
            "accepted",
        ),
        (
            "Interior alterations to existing data center with new equipment and MEP upgrades",
            "ACTIVE",
            "accepted",
        ),
        (
            "Construct warehouse buildings 3 and 4 for industrial distribution",
            "Issued",
            "accepted",
        ),
        ("Manufacturing production remodel of 128000 square feet", "Issued", "accepted"),
        ("Office tenant improvements and interior alterations", "ACTIVE", "rejected"),
        ("Hospital executive suite office alterations", "ACTIVE", "rejected"),
        ("Data center lighting replacement only", "ACTIVE", "rejected"),
        ("Construct new data center", "COMPLETE", "rejected"),
        ("Construction type: office; does not authorize any construction", "ACTIVE", "rejected"),
        (
            "Construct alterations to convert warehouse to restaurant and occupy per plan",
            "ACTIVE",
            "rejected",
        ),
        ("Replace lighting in laboratory. TYPE IA CONSTRUCTION.", "ACTIVE", "rejected"),
        (
            "New construction of hospital with associated mechanical electrical and plumbing work",
            "ACTIVE",
            "accepted",
        ),
    ],
)
def test_permit_interpretation_is_conservative(description, status, expected):
    assessment = assess_permit(
        {
            "event_date": date.today().isoformat(),
            "html_url": "https://data.example/row/1",
            "permit": {
                "row_id": "1",
                "address": "1 Main St",
                "city": "Chicago",
                "state": "IL",
                "description": description,
                "status": status,
                "class": "Non-Residential",
                "source_fields": {"description": "work_description"},
            },
        }
    )
    assert assessment["decision"] == expected
    if expected == "accepted":
        assert assessment["tier"] == "Signal"
        assert assessment["missing_facts"]
        assert "power" in assessment["reason"]


def test_chicago_express_electrical_retains_scope_parcel_and_contractor():
    requests = []
    row = {
        "id": "SYNTHETIC-ELECTRICAL-1",
        "issue_date": date.today().isoformat(),
        "permit_type": "PERMIT – EXPRESS PERMIT PROGRAM",
        "work_type": "Electrical Work",
        "work_description": "Install temporary 60 kW diesel generator.",
        "permit_status": "ACTIVE",
        "street_number": "100",
        "street_name": "TEST WAY",
        "pin_list": "TEST-PARCEL",
        "contact_4_type": "ELECTRICAL CONTRACTOR",
        "contact_4_name": "Synthetic Electric",
        "permit_": "TEST-CASE",
    }

    def handler(request):
        requests.append(request)
        if "count(*)" in request.url.params.get("$select", ""):
            return httpx.Response(200, json=[{"row_count": "1"}])
        return httpx.Response(200, json=[row])

    result = retrieve(
        source("chicago-building-permits"), httpx.Client(transport=httpx.MockTransport(handler))
    )[0]
    assert "work_type='Electrical Work'" in requests[0].url.params["$where"]
    assert "Synthetic Electric" in result["abstract"]
    assert "TEST-PARCEL" in result["abstract"]
    assert "SYNTHETIC-ELECTRICAL-1" in result["html_url"]
    assert result["permit"]["source_fields"]["contact_4_name"] == "contact_4_name"
    assert assess_permit(result)["decision"] == "accepted"
