import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.ercot_large_load_status import HUB_URL, parse_status_text
from gridlens.ingestion.adapters.ercot_large_load_status import retrieve as retrieve_ercot
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.jeti_agreements import LISTING_PDF, parse_listing_text
from gridlens.ingestion.adapters.jeti_agreements import retrieve as retrieve_jeti_agreements
from gridlens.ingestion.adapters.puct_docket_index import parse_export, parse_search
from gridlens.ingestion.adapters.puct_docket_index import retrieve as retrieve_dockets
from gridlens.ingestion.adapters.puct_large_load import filings_match_export
from gridlens.ingestion.adapters.tceq_construction_noi import parse_results
from gridlens.ingestion.adapters.tceq_construction_noi import retrieve as retrieve_noi
from gridlens.ingestion.adapters.tceq_http import OFFICIAL_HOSTS, _route
from gridlens.ingestion.registry import load_registry

FIXTURES = Path(__file__).parents[1] / "fixtures"
TODAY = date(2026, 10, 23)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _source(source_id: str) -> dict:
    return next(row for row in load_registry() if row["id"] == source_id)


def _pdf(text: str) -> bytes:
    flattened = " ".join(text.split())
    escaped = flattened.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 9 Tf 36 760 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(body)


def _docket_xlsx(rows: list[tuple[str, str, str, str]]) -> bytes:
    header = ("Control #", "Filings", "Utility", "Description (Case Style)")

    def cell(ref: str, value: str, *, number: bool) -> str:
        if number:
            return f'<c r="{ref}"><v>{value}</v></c>'
        escaped = value.replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    body = []
    for index, values in enumerate((header, *rows), start=1):
        cells = "".join(
            cell(f"{column}{index}", value, number=column == "B" and index > 1)
            for column, value in zip("ABCD", values, strict=True)
        )
        body.append(f'<row r="{index}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    strings = f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{_NS}" count="0"></sst>'
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", sheet)
        book.writestr("xl/sharedStrings.xml", strings)
    return buffer.getvalue()


def _docket_html(rows: list[tuple[str, str, str, str]]) -> bytes:
    rendered = []
    for control, filings, utility, description in rows:
        rendered.append(
            '<tr><td><a href="/search/filings/?ControlNumber='
            f'{control}">{control}</a></td><td>{filings}</td><td>{utility}</td>'
            f"<td>{description}</td></tr>"
        )
    return (f"<p>{len(rows)} record(s) found.</p><table>{''.join(rendered)}</table>").encode()


def test_exact_tceq_hosts_do_not_match_a_lookalike_suffix():
    assert "evil.tceq.texas.gov" not in OFFICIAL_HOSTS
    assert "www6.tceq.texas.gov" not in OFFICIAL_HOSTS
    assert not any(host.endswith(".tceq.texas.gov.evil.example") for host in OFFICIAL_HOSTS)
    pdf = (
        "https://permit-search.tceq.texas.gov/downloads/permitting/air/bilingual/"
        "pending-permit-notices/182126-pls-english.pdf"
    )
    assert _route(pdf, "pdf") == pdf
    with pytest.raises(SourceParseError):
        _route(
            pdf.replace("permit-search.tceq.texas.gov", "permit-search.tceq.texas.gov.evil"),
            "pdf",
        )
    www6_pdf = pdf.replace("permit-search.tceq.texas.gov", "www6.tceq.texas.gov")
    with pytest.raises(SourceParseError):
        _route(www6_pdf, "pdf")


def test_filings_list_must_match_the_excel_export():
    with pytest.raises(SourceParseError, match="disagree"):
        filings_match_export(
            {"1": {"party": "ERCOT", "description": "Status", "event_date": "2026-01-01"}},
            [
                {
                    "item": "1",
                    "party": "ERCOT",
                    "description": "Different text",
                    "event_date": "2026-01-01",
                }
            ],
        )


def test_docket_index_cross_checks_html_and_excel_and_names_el_paso():
    rows = [
        (
            "58481",
            "219",
            "PUC RULES & PROJECTS",
            "RULEMAKING TO IMPLEMENT LARGE LOAD INTERCONNECTION STANDARDS",
        ),
        (
            "56903",
            "57",
            "EL PASO ELECTRIC COMPANY",
            "APPLICATION FOR A NEW DATA CENTER TO BE LOCATED IN EL PASO TEXAS",
        ),
    ]
    assert parse_search(_docket_html(rows)) == parse_export(_docket_xlsx(rows))
    large = _docket_html([rows[0]])
    data_center = _docket_html([rows[1]])
    books = {
        "large%20load": _docket_xlsx([rows[0]]),
        "data%20center": _docket_xlsx([rows[1]]),
    }
    pages = {"large%20load": large, "data%20center": data_center}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url)
        key = "data%20center" if "data%20center" in url else "large%20load"
        if "exportdockets" in url:
            return httpx.Response(
                200,
                headers={
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                },
                content=books[key],
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=pages[key])

    records = retrieve_dockets(
        _source("texas-puct-large-load-dockets"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )
    replay = retrieve_dockets(
        _source("texas-puct-large-load-dockets"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )
    by_id = {row["document_number"]: row for row in records}
    assert [(row["document_number"], row["source_hash"]) for row in records] == [
        (row["document_number"], row["source_hash"]) for row in replay
    ]
    assert set(by_id) == {"PUCT-DOCKET-58481", "PUCT-DOCKET-56903"}
    assert by_id["PUCT-DOCKET-58481"]["permit"]["location"] is None
    assert by_id["PUCT-DOCKET-56903"]["permit"]["location"] == "EL PASO, TX"
    assert by_id["PUCT-DOCKET-56903"]["permit"]["data_center"] is True
    assert by_id["PUCT-DOCKET-56903"]["event_date"] is None
    assert assess_permit(by_id["PUCT-DOCKET-56903"], as_of=TODAY)["decision"] == "rejected"
    assert [request.url.path for request in requests[:4]] == [
        "/search/dockets/",
        "/search/exportdockets/",
        "/search/dockets/",
        "/search/exportdockets/",
    ]
    assert [request.url.params["Description"] for request in requests[:4]] == [
        "large load",
        "large load",
        "data center",
        "data center",
    ]
    assert all(request.url.params["ItemMatch"] == "Equal" for request in requests)
    assert len(requests) == 8


def test_docket_index_uses_current_direct_search_endpoint_and_equal_match():
    from gridlens.ingestion.adapters.puct_docket_index import (
        SEARCH_URL,
        _export_url,
        _search_url,
    )

    assert SEARCH_URL == (
        "https://interchange.puc.texas.gov/search/dockets/?UtilityType=E&"
        "ItemMatch=Equal&DocumentType=ALL&Description=large%20load&SortOrder=Ascending"
    )
    assert _search_url("data center") == (
        "https://interchange.puc.texas.gov/search/dockets/?UtilityType=E&"
        "ItemMatch=Equal&DocumentType=ALL&Description=data%20center&SortOrder=Ascending"
    )
    assert _export_url("data center") == (
        "https://interchange.puc.texas.gov/search/exportdockets/?UtilityType=E&"
        "ItemMatch=Equal&DocumentType=ALL&Description=data%20center&"
        "SortBy=ControlNumber&SortOrder=Ascending"
    )
    from gridlens.ingestion.registry import load_registry

    source = next(item for item in load_registry() if item["id"] == "texas-puct-large-load-dockets")
    assert source["endpoint"] == SEARCH_URL


def test_ercot_status_pdf_keeps_queue_totals_and_not_a_project_site():
    text = (
        "Large Load Interconnection Status Update March 13, 2026 "
        "ERCOT has recently received 137 new LLI submissions. Preliminary review indicates "
        "these total approximately 140,000 MW of new Large Load by 2036. "
        "Of the 9042 MW that have received Approval to Energize, ERCOT has observed a "
        "non-simultaneous monthly peak consumption of 3883 MW. "
        "ERCOT has observed a simultaneous monthly peak consumption of 3801 MW."
    )
    parsed = parse_status_text(text)
    assert parsed["event_date"] == "2026-03-13"
    assert parsed["facts"]["new_submissions"] == 137
    assert parsed["facts"]["approved_to_energize_mw"] == 9042

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == HUB_URL:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<h1>Large Load Integration</h1>",
            )
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=_pdf(text))

    records = retrieve_ercot(
        _source("texas-ercot-large-load-status"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )
    assert len(records) == 1
    assert records[0]["permit"]["location"] is None
    assert records[0]["permit"]["stated_queue_totals"]["observed_simultaneous_mw"] == 3801
    assert assess_permit(records[0], as_of=TODAY)["decision"] == "rejected"
    assert "project site" in assess_permit(records[0], as_of=TODAY)["reason"]


def test_jeti_governor_listing_keeps_places_and_blank_announced_dates():
    text = (FIXTURES / "jeti-governor-listing.txt").read_text()
    rows = parse_listing_text(text)
    by_id = {row["id"]: row for row in rows}
    assert by_id["J0001"]["location"] == "Houston, TX"
    assert by_id["J0001"]["event_date"] == "2025-01-29"
    assert by_id["J0001"]["status"] == "contracted"
    assert "Consolidated ISD" in by_id["J0009"]["school_district"]
    assert by_id["J0009"]["location"] == "Orange, TX"
    assert by_id["J0020"]["event_date"] is None
    assert by_id["J0020"]["expiration"] == "2042-12-31"
    assert by_id["J0022"]["location"] == "Reeves County, TX"
    assert by_id["J0024"]["status"] == "approved and negotiating"
    assert by_id["J0024"]["location"] == "Brownsville, TX"
    assert by_id["J0028"]["event_date"] is None
    assert by_id["J0050"]["location"] == "Fort Bend County, TX"
    contracted = {row["id"] for row in rows if row["status"] == "contracted"}
    page = "".join(f"<th>{item}</th>" for item in sorted(contracted)).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LISTING_PDF:
            return httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=_pdf(text)
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=page)

    records = retrieve_jeti_agreements(
        _source("texas-jeti-agreements"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )
    houston = next(row for row in records if row["document_number"] == "JETI-AGREEMENT-J0001")
    assert houston["permit"]["location"] == "Houston, TX"
    assert assess_permit(houston, as_of=TODAY)["decision"] == "rejected"


def test_construction_noi_uses_city_and_county_and_keeps_directions_out_of_place():
    href = (
        "index.cfm?fuseaction=home.permit_summary&amp;lgl_ident_txt=TXR1502UT"
        "&amp;permit_type_code=SWC"
    )
    page = f"""
    <p>Your search returned 1 records.</p>
    <span>1-1 of 1 Records</span>
    <table>
      <tr><th>Auth #</th></tr>
      <tr>
        <td><a href="{href}">TXR1502UT</a></td>
        <td>NTT TX-4 DATA CENTER</td>
        <td>Structure Tone Southwest, LLC</td>
        <td>1541</td>
        <td>0820</td>
        <td>DALLAS</td>
        <td>4</td>
        <td>GARLAND</td>
        <td>SOUTHEAST OF TELECOM ROAD AND CO RD 1</td>
      </tr>
    </table>
    """.encode()
    rows = parse_results(page)
    assert rows[0]["auth"] == "TXR1502UT"
    assert rows[0]["summary_url"].startswith("https://www2.tceq.texas.gov/wq_dpa/index.cfm?")
    calls = {"advanced": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"TXR150000 - Construction (NOI & Waiver)",
            )
        body = request.content.decode()
        if "permit_info_search" in body:
            calls["advanced"] += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<input name="_fuseaction=home.validate_search_crit">',
            )
        content = page if "phys_name=data+center" in body else b"Your search returned 0 records."
        return httpx.Response(200, headers={"content-type": "text/html"}, content=content)

    records = retrieve_noi(
        _source("texas-tceq-construction-noi"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )
    assert calls["advanced"] == 1
    assert len(records) == 1
    assert records[0]["permit"]["location"] == "GARLAND, DALLAS County, TX"
    assert "CO RD" not in records[0]["permit"]["location"]
    assert "CO RD" in records[0]["permit"]["description"]
    assert records[0]["event_date"] is None
    assert records[0]["permit"]["operating_hours"]["rule_id"] == "air-permit-operating-hours-v1"
    rejected = assess_permit(records[0], as_of=TODAY)
    assert rejected["decision"] == "rejected"
    assert "event date" in rejected["reason"]
    with pytest.raises(SourceParseError, match="outside the official search host"):
        parse_results(page.replace(b"index.cfm?", b"https://evil.example/index.cfm?"))


def _construction_noi_source_row(auth: str, sic: str, segment: str) -> dict[str, str]:
    return {
        "auth": auth,
        "site_name": "CORE SCIENTIFIC DATA CENTER EXPANSION",
        "permittee": "T5 Construction, Llc",
        "sic": sic,
        "segment": segment,
        "county": "DENTON",
        "region": "4",
        "city": "DENTON",
        "site_location": "8171 JIM CHRISTAL RD DENTON TX 76207 3719",
    }


def _construction_noi_page(rows: list[dict[str, str]]) -> bytes:
    if not rows:
        return b"Your search returned 0 records."
    rendered = []
    for row in rows:
        auth = row["auth"]
        cells = [
            f'<td><a href="index.cfm?fuseaction=home.permit_summary&amp;'
            f'lgl_ident_txt={auth}">{auth}</a></td>'
        ]
        cells.extend(
            f"<td>{row[key]}</td>"
            for key in (
                "site_name",
                "permittee",
                "sic",
                "segment",
                "county",
                "region",
                "city",
                "site_location",
            )
        )
        rendered.append(f"<tr>{''.join(cells)}</tr>")
    count = len(rows)
    return (
        f"<p>Your search returned {count} records.</p>"
        f"<span>1-{count} of {count} Records</span>"
        f"<table>{''.join(rendered)}</table>"
    ).encode()


def _retrieve_construction_noi_pages(pages: dict[str, list[dict[str, str]]]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"TXR150000 - Construction (NOI & Waiver)",
            )
        body = request.content.decode()
        if "permit_info_search" in body:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<input name="_fuseaction=home.validate_search_crit">',
            )
        term = parse_qs(body).get("phys_name", [""])[0]
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=_construction_noi_page(pages[term]),
        )

    return retrieve_noi(
        _source("texas-tceq-construction-noi"),
        httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler)),
    )


def test_construction_noi_retains_actual_repeated_classification_rows_deterministically():
    variants = [
        _construction_noi_source_row("TXR1528SY", sic, segment)
        for sic, segment in (
            ("1542", "0802"),
            ("1542", "0823"),
            ("7374", "0802"),
            ("7374", "0823"),
        )
    ]
    pages = {"data center": [*variants, variants[0]], "datacenter": []}

    records = _retrieve_construction_noi_pages(pages)
    replay = _retrieve_construction_noi_pages(
        {"data center": list(reversed(pages["data center"])), "datacenter": []}
    )
    record = records[0]
    classifications = record["permit"]["source_classification_rows"]

    assert len(records) == 1
    assert [(item["sic"], item["segment"]) for item in classifications] == [
        ("1542", "0802"),
        ("1542", "0823"),
        ("7374", "0802"),
        ("7374", "0823"),
    ]
    assert all(item["search_terms"] == ["data center"] for item in classifications)
    assert "Source classification rows:" in record["abstract"]
    assert record["event_date"] is None
    assert assess_permit(record, as_of=TODAY)["decision"] == "rejected"
    assert [(row["document_number"], row["source_hash"]) for row in records] == [
        (row["document_number"], row["source_hash"]) for row in replay
    ]
    fewer = _retrieve_construction_noi_pages({"data center": variants[:-1], "datacenter": []})
    assert record["source_hash"] != fewer[0]["source_hash"]


def test_construction_noi_tracks_classification_provenance_across_search_terms():
    one = {
        "auth": "TXR1588WJ",
        "site_name": "NEXUS DATA CENTER HUBBARD",
        "permittee": "Nexus Hubbard Power, LLC",
        "sic": "4911",
        "segment": "0836",
        "county": "HILL",
        "region": "9",
        "city": "HUBBARD",
        "site_location": "880 STATE HIGHWAY 171 HUBBARD TX 76648 2847",
    }
    two = {**one, "sic": "7374"}

    records = _retrieve_construction_noi_pages({"data center": [one], "datacenter": [two]})

    assert records[0]["permit"]["source_classification_rows"] == [
        {"sic": "4911", "segment": "0836", "search_terms": ["data center"]},
        {"sic": "7374", "segment": "0836", "search_terms": ["datacenter"]},
    ]


def test_construction_noi_still_rejects_nonclassification_duplicate_conflicts():
    first = _construction_noi_source_row("TXR1528SY", "1542", "0802")
    conflict = {**first, "sic": "7374", "site_location": "DIFFERENT SITE"}

    with pytest.raises(SourceParseError, match="authorization was returned with a conflict"):
        _retrieve_construction_noi_pages({"data center": [first, conflict], "datacenter": []})


def _tceq_result_page(row_count: int, declared_count: str, paging: str) -> bytes:
    rows = []
    for index in range(row_count):
        auth = f"TXR15{index:04d}"
        summary_link = (
            f'<td><a href="index.cfm?fuseaction=home.permit_summary&amp;'
            f'lgl_ident_txt={auth}">{auth}</a></td>'
        )
        rows.append(
            "<tr>"
            + summary_link
            + f"<td>Data Center {index}</td><td>Permittee {index}</td>"
            + "<td>1541</td><td>0820</td><td>TRAVIS</td><td>11</td>"
            + f"<td>AUSTIN</td><td>Site {index}</td></tr>"
        )
    return (
        f"<p>Your search returned {declared_count} records.</p>"
        f"<span>{paging}</span><table>{''.join(rows)}</table>"
    ).encode()


def test_construction_noi_decodes_entity_spacing_for_complete_count_only():
    page = _tceq_result_page(46, "46", "1&nbsp;-&nbsp;46 of 46 Records")

    rows = parse_results(page)

    assert len(rows) == 46
    assert rows[0]["auth"] == "TXR150000"
    assert rows[-1]["auth"] == "TXR150045"
    assert rows[0]["summary_url"].startswith("https://www2.tceq.texas.gov/wq_dpa/index.cfm?")


@pytest.mark.parametrize(
    ("row_count", "declared", "paging", "message"),
    [
        (46, "46", "1&nbsp;-&nbsp;45 of 46 Records", "paginated or its count disagrees"),
        (46, "45", "1&nbsp;-&nbsp;46 of 46 Records", "paginated or its count disagrees"),
        (45, "46", "1&nbsp;-&nbsp;46 of 46 Records", "count does not match its rows"),
        (1, "4x", "1&nbsp;-&nbsp;1 of 1 Records", "did not state a record count"),
    ],
)
def test_construction_noi_rejects_incomplete_or_malformed_count(
    row_count: int, declared: str, paging: str, message: str
):
    with pytest.raises(SourceParseError, match=message):
        parse_results(_tceq_result_page(row_count, declared, paging))


@pytest.mark.parametrize(
    ("href", "message"),
    [
        (
            "https://www2.tceq.texas.gov.evil.example/wq_dpa/index.cfm?"
            "fuseaction=home.permit_summary&amp;lgl_ident_txt=TXR150000",
            "outside the official search host",
        ),
        (
            "https://www2.tceq.texas.gov/wq_dpa/index.cfm?"
            "fuseaction=home.permit_summary&amp;lgl_ident_txt=TXR150001",
            "not that authorization's summary",
        ),
    ],
)
def test_construction_noi_preserves_official_authorization_link_binding(href: str, message: str):
    page = _tceq_result_page(1, "1", "1&nbsp;-&nbsp;1 of 1 Records")
    page = page.replace(
        b"index.cfm?fuseaction=home.permit_summary&amp;lgl_ident_txt=TXR150000",
        href.encode(),
    )

    with pytest.raises(SourceParseError, match=message):
        parse_results(page)
