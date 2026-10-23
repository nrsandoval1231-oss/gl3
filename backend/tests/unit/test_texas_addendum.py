import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

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

    def handler(request: httpx.Request) -> httpx.Response:
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
    by_id = {row["document_number"]: row for row in records}
    assert set(by_id) == {"PUCT-DOCKET-58481", "PUCT-DOCKET-56903"}
    assert by_id["PUCT-DOCKET-58481"]["permit"]["location"] is None
    assert by_id["PUCT-DOCKET-56903"]["permit"]["location"] == "EL PASO, TX"
    assert by_id["PUCT-DOCKET-56903"]["permit"]["data_center"] is True
    assert by_id["PUCT-DOCKET-56903"]["event_date"] is None
    assert assess_permit(by_id["PUCT-DOCKET-56903"], as_of=TODAY)["decision"] == "rejected"


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
