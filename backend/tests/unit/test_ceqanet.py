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


def test_relative_ceqanet_document_link_resolves_without_changing_identity():
    body = LISTING.replace(
        b'href="https://ceqanet.lci.ca.gov/2024100855/2"',
        b'href="/2024100855/2"',
    )
    row = next(item for item in parse_listing(body) if item["sch"] == "2024100855")
    assert row["url"] == "https://ceqanet.lci.ca.gov/2024100855/2"
    assert row["received"] == "2026-10-01"


def test_ceqanet_alias_href_does_not_change_record_identity_or_hash():
    row = elsinore_row()
    document = parse_document(ELSINORE)
    alias = {**row, "source_href": "/2026020574", "url": row["url"]}
    first, second = record(row, document), record(alias, document)
    assert first["document_number"] == second["document_number"]
    assert first["source_hash"] == second["source_hash"]
    assert second["permit"]["source_link_hrefs"]["CEQAnet document"] == "/2026020574"


@pytest.mark.parametrize("href", [
    "//attacker.example/2026080888",
    "https://user@ceqanet.lci.ca.gov/2026080888",
    "/2026080888?redirect=https://attacker.example",
    "/2026080888/../../private",
    "/raw/a/../2026100400",
    "/2026100400\n",
    "/2026100400\t",
])
def test_ceqanet_rejects_foreign_or_malformed_document_links(href: str):
    body = LISTING.replace(
        b'href="https://ceqanet.lci.ca.gov/2026100400"',
        f'href="{href}"'.encode(),
    )
    with pytest.raises(SourceParseError):
        parse_listing(body)


def test_document_page_gives_place_and_coordinates():
    document = parse_document(ELSINORE)
    assert document["lead_agency"] == "City of Lake Elsinore"
    assert (document["cities"], document["counties"]) == ("Lake Elsinore", "Riverside")
    assert (document["latitude"], document["longitude"]) == (33.685447, -117.326358)
    assert "one data center building" in document["description"]
    assert document["applicant"] == "V22 Investments, LLC"
    assert document["action_date"] is None


def test_lead_agency_is_not_the_applicant_and_origin_is_environmental_review():
    item = record(elsinore_row(), parse_document(ELSINORE))
    assert item["permit"]["applicant"] == "V22 Investments, LLC"
    assert item["permit"]["lead_agency"] == "City of Lake Elsinore"
    from gridlens.domain.signal_admission import admit_standalone, source_origin

    assert source_origin("environmental-review-filings", "ceqanet-data-centers") == (
        "Official environmental-review filing"
    )
    admission = admit_standalone(
        source_id=SOURCE_ID,
        family="environmental-review-filings",
        retrieval_method="ceqanet-data-centers",
        accepted=True,
        activity="facility-expansion",
        title=item["title"],
        abstract=item["abstract"],
    )
    assert admission.admitted and "not established" in admission.reason


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
    searches = [url for url in seen if url.startswith(SEARCH_URL)]
    # 2026-08-15..2026-10-14 is read in nine weekly slices to stay under CEQAnet's row cap.
    assert len(searches) == 9
    assert "StartRange=2026-08-15&EndRange=2026-08-21" in searches[0]
    assert "StartRange=2026-10-10&EndRange=2026-10-14" in searches[-1]


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
