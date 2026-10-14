from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.ceqanet import (
    SEARCH_URL,
    SOURCE_ID,
    parse_document,
    parse_listing,
    record,
    retrieve,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError

FIXTURES = Path(__file__).parents[1] / "fixtures"
LISTING = (FIXTURES / "ceqanet-search-excerpt.html").read_bytes()
ELSINORE = (FIXTURES / "ceqanet-document-2026020574-excerpt.html").read_bytes()
TODAY = date(2026, 10, 14)
SOURCE = {
    "id": SOURCE_ID,
    "endpoint": SEARCH_URL,
    "query": {"development_types": ["Industrial"], "window_days": 60, "max_documents": 10},
}


def elsinore_row():
    return next(row for row in parse_listing(LISTING) if row["sch"] == "2026020574")


def test_listing_rows_and_count_check():
    rows = parse_listing(LISTING)
    assert [row["sch"] for row in rows] == ["2026100400", "2024100855", "2026020574"]
    assert rows[1]["url"] == "https://ceqanet.lci.ca.gov/2024100855/2"
    assert rows[1]["title"] == "E&P Technology Way Project"
    with pytest.raises(SourceParseError, match="listed 4 documents"):
        parse_listing(LISTING.replace(b"3 document(s) found", b"4 document(s) found"))


def test_document_page_gives_place_and_coordinates():
    document = parse_document(ELSINORE)
    assert document["lead_agency"] == "City of Lake Elsinore"
    assert (document["cities"], document["counties"]) == ("Lake Elsinore", "Riverside")
    assert (document["latitude"], document["longitude"]) == (33.685447, -117.326358)
    assert "one data center building" in document["description"]


def test_description_only_data_center_is_signal_with_caveat():
    item = record(elsinore_row(), parse_document(ELSINORE))
    assert evaluator_version(item) == "ceqanet-data-center-v1"
    result = assess_permit(item, as_of=TODAY)
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["location"] == "Lake Elsinore, Riverside County, CA"
    assert result["event_date"] == "2026-02-13"
    assert "only in its description" in result["reason"]


def test_moratorium_is_rejected():
    row = {**elsinore_row(), "title": "Moratorium prohibiting new data center applications"}
    document = {**parse_document(ELSINORE), "title": row["title"]}
    result = assess_permit(record(row, document), as_of=TODAY)
    assert result["decision"] == "rejected" and "moratorium" in result["reason"]


def test_retrieve_keeps_only_data_center_documents():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url.startswith(SEARCH_URL):
            assert "StartRange=2026-08-15" in url and "EndRange=2026-10-14" in url
            return httpx.Response(200, content=LISTING)
        if url.endswith("/2026020574"):
            return httpx.Response(200, content=ELSINORE)
        # Other documents do not name a data center.
        return httpx.Response(
            200,
            content=ELSINORE.replace(b"one data center building", b"one warehouse building")
            .replace(b"2026020574", url.rsplit("/", 1)[-1].encode()),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = retrieve(SOURCE, client, today=TODAY)
    assert [r["permit"]["row_id"] for r in records] == ["CEQA-2026020574-2026020574"]


def test_retrieve_fails_visibly_when_pages_fail():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, content=LISTING)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceParseError, match="failed for 3 of 3"):
        retrieve(SOURCE, client, today=TODAY)
    with pytest.raises(SourceParseError, match="query bounds"):
        retrieve({**SOURCE, "query": {**SOURCE["query"], "window_days": 365}}, client)
