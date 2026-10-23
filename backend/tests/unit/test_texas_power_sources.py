import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.domain.signal_admission import admit_standalone
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.jeti_applications import API_URL, parse_index
from gridlens.ingestion.adapters.jeti_applications import retrieve as retrieve_jeti
from gridlens.ingestion.adapters.puct_large_load import (
    EXPORT_URL,
    FILINGS_URL,
    parse_export,
)
from gridlens.ingestion.adapters.puct_large_load import retrieve as retrieve_puct
from gridlens.ingestion.adapters.tceq_egu_search import (
    SEARCH_URL,
    START_URL,
    parse_results,
)
from gridlens.ingestion.adapters.tceq_egu_search import retrieve as retrieve_tceq
from gridlens.ingestion.registry import load_registry

FIXTURES = Path(__file__).parents[1] / "fixtures"
TODAY = date(2026, 10, 23)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _source(source_id: str) -> dict:
    return next(row for row in load_registry() if row["id"] == source_id)


def _xlsx(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    header = ("Control #", "Item #", "File Stamp", "Filing Party", "Filing Description")

    def cell(ref: str, value: str, *, number: bool) -> str:
        if number:
            return f'<c r="{ref}"><v>{value}</v></c>'
        escaped = value.replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    body: list[str] = []
    for index, values in enumerate((header, *rows), start=1):
        cells = "".join(
            cell(f"{column}{index}", value, number=(column == "C" and index > 1))
            for column, value in zip("ABCDE", values, strict=True)
        )
        body.append(f'<row r="{index}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def test_tceq_search_keeps_generator_rows_and_tags_only_explicit_language():
    updated, rows = parse_results(
        (FIXTURES / "tceq-egu-search-excerpt.html").read_bytes(),
        unit_id="8340",
        unit_name="ELECTRIC GENERATING FACILITIES",
    )
    assert updated == "2026-10-22"
    by_permit = {row["permit_number"]: row for row in rows}
    assert set(by_permit) == {"185729", "185001", "184000"}
    digital = by_permit["185729"]
    assert digital["location"] == "Taylor, Williamson County, TX"
    assert digital["event_date"] == "2026-10-14"
    assert digital["tags"] == []
    assert digital["data_center"] is False
    assert "1.1 MI" not in (digital["location"] or "")
    bridge = by_permit["185001"]
    assert bridge["tags"] == ["bridge"]
    assert bridge["data_center"] is True
    assert by_permit["184000"]["tags"] == []


def test_puct_export_dates_places_and_does_not_tag_a_bridge_name():
    body = _xlsx(
        [
            (
                "59142",
                "2",
                "46009",
                "GOOGLE LLC, LANCIUM LLC",
                "Joint Comments of Google LLC and Lancium LLC as it pertains to "
                "ERCOT's Large Load Process Reforms",
            ),
            (
                "59142",
                "9001",
                "46040",
                "FIXTURE ONLY",
                "Temporary power for the Fixture Data Center, Midland, TX",
            ),
            (
                "59142",
                "9002",
                "46041",
                "FIXTURE ONLY",
                "Comments on the Wheatland Bridge substation",
            ),
            (
                "59142",
                "9003",
                "46042",
                "FIXTURE ONLY",
                "bridge power until the utility connection, Odessa, TX",
            ),
        ]
    )
    rows = parse_export(body, control_number=59142)
    by_item = {row["item"]: row for row in rows}
    assert by_item["2"]["event_date"] == "2025-12-18"
    assert by_item["2"]["location"] is None
    assert by_item["2"]["tags"] == []
    assert by_item["9001"]["location"] == "Midland, TX"
    assert by_item["9001"]["tags"] == ["temporary"]
    assert by_item["9001"]["data_center"] is True
    assert by_item["9002"]["tags"] == []
    assert by_item["9003"]["tags"] == ["bridge"]
    assert by_item["9003"]["data_center"] is False


def test_jeti_index_links_pdfs_and_does_not_invent_a_site():
    rows = parse_index((FIXTURES / "jeti-applications-excerpt.json").read_bytes())
    by_id = {row["id"]: row for row in rows}
    assert by_id["J0001"]["event_date"] == "2024-02-16"
    assert by_id["J0001"]["data_center"] is False
    assert by_id["J9001"]["data_center"] is True
    assert by_id["J9001"]["documents"][0][1] == (
        "https://assets.comptroller.texas.gov/open-data/jeti/"
        "J9001/J9001-fixture-data-center-app.pdf"
    )
    broken = (
        (FIXTURES / "jeti-applications-excerpt.json")
        .read_text()
        .replace('"count": 2', '"count": 1')
    )
    with pytest.raises(SourceParseError, match="count does not match"):
        parse_index(broken.encode())


def _client(handler) -> httpx.Client:
    return httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler))


def test_fetches_use_per_request_headers_and_do_not_mutate_the_client():
    excerpt = (FIXTURES / "tceq-egu-search-excerpt.html").read_bytes()
    empty = (
        b"<html><body>Last Updated Date : 10/22/2026 "
        b"There are no projects matching this query.</body></html>"
    )
    seen: list[httpx.Request] = []

    def tceq(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<input name="_fuseaction=airpermits.validate_search_criteria">',
            )
        body = request.content.decode()
        content = excerpt if "unit_id=8340" in body else empty
        return httpx.Response(200, headers={"content-type": "text/html"}, content=content)

    client = _client(tceq)
    client.headers["Host"] = "preserve.example"
    records = retrieve_tceq(_source("texas-tceq-egu-registrations"), client)
    assert {row["document_number"] for row in records} == {
        "TCEQ-EGU-185729",
        "TCEQ-EGU-185001",
        "TCEQ-EGU-184000",
    }
    assert seen[0].url == START_URL
    assert seen[1].url == SEARCH_URL
    assert seen[1].headers["user-agent"].startswith("GridLens public source reader/")
    assert client.headers["Host"] == "preserve.example"
    center = next(row for row in records if row["document_number"] == "TCEQ-EGU-185001")
    accepted = assess_permit(center, as_of=TODAY)
    assert accepted["decision"] == "accepted"
    assert accepted["power_signals"] == ["bridge"]
    assert accepted["power_activity"] == "facility-expansion"
    plain = next(row for row in records if row["document_number"] == "TCEQ-EGU-184000")
    assert assess_permit(plain, as_of=TODAY)["decision"] == "rejected"

    puct_rows = {
        59142: _xlsx(
            [
                (
                    "59142",
                    "9001",
                    "46040",
                    "FIXTURE ONLY",
                    "Temporary power for the Fixture Data Center, Midland, TX",
                )
            ]
        ),
        58481: _xlsx(
            [
                (
                    "58481",
                    "1",
                    "46008",
                    "PUC EXECUTIVE DIRECTOR",
                    "Control number request for the large-load rule",
                )
            ]
        ),
    }

    def puct(request: httpx.Request) -> httpx.Response:
        control = 59142 if "ControlNumber=59142" in str(request.url) else 58481
        return httpx.Response(
            200,
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            },
            content=puct_rows[control],
        )

    puct_client = _client(puct)
    puct_client.headers["Host"] = "preserve.example"
    filings = retrieve_puct(_source("texas-puct-large-load-filings"), puct_client)
    assert {row["document_number"] for row in filings} == {"PUCT-59142-9001", "PUCT-58481-1"}
    assert puct_client.headers["Host"] == "preserve.example"
    located = next(row for row in filings if row["document_number"] == "PUCT-59142-9001")
    assert located["html_url"].startswith("https://interchange.puc.texas.gov/search/documents/")
    assessment = assess_permit(located, as_of=TODAY)
    assert assessment["decision"] == "accepted"
    assert assessment["location"] == "Midland, TX"
    admitted = admit_standalone(
        source_id="texas-puct-large-load-filings",
        family="official-utility-filings",
        retrieval_method="puct-interchange",
        accepted=True,
        activity=assessment["power_activity"],
        title=located["title"],
        abstract=located["abstract"],
        dated=True,
        citation_url=located["html_url"],
        identified_project=True,
    )
    assert admitted.admitted is True
    comment = next(row for row in filings if row["document_number"] == "PUCT-58481-1")
    assert assess_permit(comment, as_of=TODAY)["decision"] == "rejected"
    held = admit_standalone(
        source_id="texas-puct-large-load-filings",
        family="official-utility-filings",
        retrieval_method="puct-interchange",
        accepted=True,
        activity="facility-expansion",
        title=comment["title"],
        abstract=comment["abstract"],
        dated=True,
        citation_url=comment["html_url"],
        identified_project=False,
    )
    assert held.admitted is False

    def jeti(request: httpx.Request) -> httpx.Response:
        assert request.url == API_URL
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(FIXTURES / "jeti-applications-excerpt.json").read_bytes(),
        )

    projects = retrieve_jeti(_source("texas-jeti-applications"), _client(jeti))
    assert {row["document_number"] for row in projects} == {"JETI-J0001", "JETI-J9001"}
    data_center = next(row for row in projects if row["document_number"] == "JETI-J9001")
    rejected = assess_permit(data_center, as_of=TODAY)
    assert rejected["decision"] == "rejected"
    assert "project site" in rejected["reason"]
    assert data_center["permit"]["location"] is None


def test_registry_endpoints_match_the_verified_pages():
    assert _source("texas-tceq-egu-registrations")["endpoint"] == START_URL
    assert _source("texas-puct-large-load-filings")["endpoint"] == FILINGS_URL
    assert _source("texas-puct-large-load-filings")["query"]["control_numbers"] == [59142, 58481]
    assert _source("texas-jeti-applications")["endpoint"] == API_URL
    assert EXPORT_URL.format(control=59142).startswith("https://interchange.puc.texas.gov/")
