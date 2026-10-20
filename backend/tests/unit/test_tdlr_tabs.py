import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tdlr_tabs import (
    PROJECT_URL,
    SEARCH_URL,
    SOURCE_ID,
    parse_project,
    parse_search,
    record,
    retrieve,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
PAGE = (FIXTURES / "tdlr-tabs-project-TABS2026009183-excerpt.html").read_bytes()
SEARCH = (FIXTURES / "tdlr-tabs-search-shape.json").read_bytes()
NUMBER = "TABS2026009183"
TODAY = date(2026, 1, 20)
SOURCE = {
    "id": SOURCE_ID,
    "endpoint": SEARCH_URL,
    "query": {"window_days": 90, "name_terms": ["data center"]},
}


def project():
    return parse_project(PAGE, NUMBER)


def test_project_page_fields():
    parsed = project()
    assert parsed["name"] == "Databank Red Oak - DFW13"
    assert parsed["address"] == "Stainback Rd, Red Oak, TX 75154"
    assert parsed["county"] == "Ellis"
    assert (parsed["registered"], parsed["start"], parsed["completion"]) == (
        "2026-01-05",
        "2026-03-01",
        "2027-12-31",
    )
    assert parsed["cost"] == "$325,000,000" and parsed["work_type"] == "New Construction"
    assert parsed["owner"] == "DB Data Center Red Oak, LLC"
    assert parsed["design_firm"] == "JHET Architects, PLLC"
    assert parsed["status"] == "Project Registered"
    with pytest.raises(SourceParseError, match="lacks its number"):
        parse_project(PAGE, "TABS2026000001")


def test_new_construction_is_a_signal_with_reported_dates_as_estimates():
    item = record(project())
    assert evaluator_version(item) == "tdlr-tabs-data-center-v1"
    assert item["publication_date"] is None
    result = assess_permit(item, as_of=date(2026, 10, 14))
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["event_date"] == "2026-01-05"
    assert result["location"] == "Stainback Rd, Red Oak, TX 75154 (Ellis County)"
    assert "registrant's estimates" in result["reason"]


def test_renovation_closed_and_finished_projects_are_rejected():
    for change, phrase in (
        ({"work_type": "Renovation/Alteration"}, "not new construction"),
        ({"status": "Project Closed"}, "closed or already inspected"),
        ({"status": "Inspection Complete"}, "closed or already inspected"),
        ({"completion": "2026-06-30"}, "has passed"),
    ):
        result = assess_permit(record({**project(), **change}), as_of=date(2026, 10, 14))
        assert result["decision"] == "rejected" and phrase in result["reason"]


def test_retrieve_posts_the_search_form_and_reads_each_project():
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
            return httpx.Response(200, content=SEARCH)
        assert str(request.url) == PROJECT_URL.format(number=NUMBER)
        return httpx.Response(200, content=PAGE)

    records = retrieve(SOURCE, httpx.Client(transport=httpx.MockTransport(handler)), today=TODAY)
    assert [r["permit"]["row_id"] for r in records] == [f"TABS-{NUMBER}"]
    assert posts[0]["ProjectName"] == ["data center"]
    assert posts[0]["RegistrationDateBegin"] == ["10/22/2025"]
    assert posts[0]["length"] == ["100"]


def test_search_failures_are_visible():
    with pytest.raises(SourceParseError, match="recordsFiltered"):
        parse_search(b'{"data": []}')
    with pytest.raises(SourceParseError, match="project number"):
        parse_search(json.dumps({"recordsFiltered": 1, "data": [{"ProjectNumber": "x"}]}).encode())
    too_many = json.loads(SEARCH)
    too_many["recordsFiltered"] = 999

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(too_many).encode())

    with pytest.raises(SourceParseError, match="matched 999"):
        retrieve(SOURCE, httpx.Client(transport=httpx.MockTransport(handler)), today=TODAY)
    future_page = PAGE.replace(b"1/5/2026", b"3/5/2026")

    def future(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SEARCH if request.method == "POST" else future_page)

    with pytest.raises(SourceParseError, match="after the run date"):
        retrieve(SOURCE, httpx.Client(transport=httpx.MockTransport(future)), today=TODAY)


def test_origin_is_a_registration_and_source_ships_disabled():
    from gridlens.domain.signal_admission import source_origin

    assert source_origin("construction-permits", "tdlr-tabs") == (
        "Official TDLR project registration"
    )
    registry = json.loads(
        (Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json").read_text()
    )
    entry = next(s for s in registry["sources"] if s["id"] == SOURCE_ID)
    assert entry["enabled"] is False
