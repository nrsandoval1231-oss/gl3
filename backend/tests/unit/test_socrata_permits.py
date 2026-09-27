from datetime import UTC, date, datetime

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


@pytest.mark.parametrize("mutation", ["duplicate", "out_of_window", "empty_count", "off_host"])
def test_adapter_fails_closed_on_inconsistent_or_unsafe_result(mutation):
    row = {
        "permit_number": "P-1",
        "issue_date": datetime.now(UTC).date().isoformat(),
        "description": "Construction of manufacturing facility",
        "permit_type_desc": "Building Permit",
        "permit_class_mapped": "Commercial",
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
