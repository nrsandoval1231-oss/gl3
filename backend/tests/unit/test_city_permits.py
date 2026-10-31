import io
import zipfile
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.dallas_permits import HEADERS, INDEX, parse_report, retrieve
from gridlens.ingestion.adapters.el_paso_permits import _row
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.houston_permit_details import retrieve_detail
from gridlens.ingestion.adapters.retained_permits import facts as permit_facts


def _workbook(rows: list[list[str]]) -> bytes:
    strings = [value for row in rows for value in row]
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    shared = (
        f'<sst xmlns="{ns}">'
        + "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
        + "</sst>"
    )
    sheet_rows = "".join(
        "<row>"
        + "".join(
            f'<c r="{chr(65 + index)}{row_number}" t="s"><v>{strings.index(value)}</v></c>'
            for index, value in enumerate(row)
        )
        + "</row>"
        for row_number, row in enumerate(rows, start=1)
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>{sheet_rows}</sheetData></worksheet>',
        )
    return output.getvalue()


def _dallas_row(record_id: str, record_type: str, use: str) -> list[str]:
    issue_date = (date(2026, 8, 10) - date(1899, 12, 30)).days
    return [
        record_type,
        record_id,
        str(issue_date - 2),
        str(issue_date),
        "100 MAIN ST",
        "Commercial",
        use,
        "",
        "120000",
        "1000000",
        "Applicant",
        "Alex Example",
        "Example LP Business LLC",
        "1",
        "LI",
    ]


def test_dallas_monthly_rows_keep_roles_events_and_scope_distinct():
    body = _workbook(
        [
            list(HEADERS),
            _dallas_row("CASE-1", "Commercial New Construction Permit", "Data Center"),
            _dallas_row("CASE-2", "Residential New Construction Permit", "Single Family"),
        ]
    )
    rows = parse_report(
        body,
        "https://dallascityhall.com/month.xlsx",
        report_month=date(2026, 8, 1),
        today=date(2026, 10, 1),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["document_number"] == "CASE-1"
    assert row["publication_date"] is None
    assert row["event_date"] == "2026-08-10"
    assert row["event_date_label"] == "Permit Issued Date"
    assert row["permit"]["status"] == "Unknown"
    assert row["permit"]["source_fields"]["description"] == (
        "Record Type + Proposed Land Use + Type of Work"
    )
    assert "lp_business_name: Example LP Business LLC" in row["abstract"]
    assert "applicant_org:" not in row["abstract"]
    assessment = assess_permit(row, as_of=date(2026, 10, 1))
    assert assessment["decision"] == "accepted"
    assert "activity-specific power requirement" in assessment["missing_facts"]
    assert "rental requirement" in assessment["rental_hypothesis"]


def test_dallas_latest_month_link_retrieval_and_host_bounds(monkeypatch):
    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 1, tzinfo=tz)

    # Retrieval shares the October 1 clock used by the adjacent parsing fixture.
    monkeypatch.setattr("gridlens.ingestion.adapters.dallas_permits.datetime", FixtureDateTime)
    body = _workbook(
        [list(HEADERS), _dallas_row("CASE-1", "Commercial New Construction Permit", "Data Center")]
    )
    page = (
        '<a href="/departments/pnv/Documents/AH%20Memos/'
        'Com-ResNew%20MonthlyReport2026-%20Aug.xlsx">'
        "August Permit Table</a>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == INDEX:
            return httpx.Response(200, text=page)
        assert request.url.host == "dallascityhall.com"
        return httpx.Response(200, content=body)

    rows = retrieve(
        {
            "id": "dallas-monthly-permits",
            "endpoint": INDEX,
            "retrieval_method": "dallas-monthly-permits",
        },
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert [row["document_number"] for row in rows] == ["CASE-1"]

    foreign = page.replace("/departments/pnv/Documents", "https://evil.example/files")

    def bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=foreign)

    with pytest.raises(SourceParseError, match="official host"):
        retrieve(
            {
                "id": "dallas-monthly-permits",
                "endpoint": INDEX,
                "retrieval_method": "dallas-monthly-permits",
            },
            httpx.Client(transport=httpx.MockTransport(bad_handler)),
        )


def test_el_paso_permit_identity_ignores_republished_objectid_and_keeps_status_roles():
    attributes = {
        "OBJECTID": 29339,
        "Status": "M",
        "Record_Typ": "",
        "B1_SPECIAL": "Emerus Lee Trevino",
        "B1_ALT_ID": "BCNN25-00099",
        "B1_APPL_ST": "Inspection",
        "OWNNAME": "",
        "ISSUEDATE": int(datetime(2026, 8, 31, tzinfo=UTC).timestamp() * 1000),
        "JOBVALUE": 0,
        "SITEADDR_S": "",
        "Address": "11213 GATEWAY WEST",
        "Descriptio": "",
    }
    first = _row(attributes, date(2026, 10, 1))
    republished = _row({**attributes, "OBJECTID": 29340}, date(2026, 10, 1))
    assert first["document_number"] == "BCNN25-00099"
    assert first["source_hash"] == republished["source_hash"]
    assert first["permit"]["object_id"] == 29339
    assert first["permit"]["application_status"] == "Inspection"
    assert first["permit"]["geocode_status"] == "M"
    assert first["permit"]["issuance_event"] == "issued"
    ambiguous = {
        **first,
        "permit": {
            **first["permit"],
            "description": "Emerus Lee Trevino",
            "work": None,
        },
    }
    assert assess_permit(ambiguous, as_of=date(2026, 10, 1))["decision"] == "rejected"


def test_houston_exact_sold_detail_keeps_source_roles_and_requires_exact_project():
    body = """<html><table>
      <tr><td>Project No:</td><td>26051624</td></tr>
      <tr><td>Date:</td><td>2026/09/02 00:00:00</td></tr>
      <tr><td>Job Address:</td><td>8930 GULF FWY A</td></tr>
      <tr><td>Permit Type:</td><td>Building</td></tr>
      <tr><td>Owner/Occupant:</td><td>*MERICHEM TECHNOLOGIES LLC</td></tr>
      <tr><td>Buyer:</td><td>SCHARUNOVYCH VIRNA</td></tr>
      <tr><td>Address:</td><td>2019 WOODLAND SPRINGS ST 77077</td></tr>
      <tr><td>Phone:</td><td>(281) 948-6344</td></tr>
    </table></html>"""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=body,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    doc = retrieve_detail(
        "26051624",
        "Building Pmt",
        event_date="2026-09-02",
        site_address="8930 GULF FWY",
        client=client,
    )
    assert requests[0].url.host == "cohtora.houstontx.gov"
    assert requests[0].url.params["PN"] == "26051624"
    assert requests[0].url.params["PT"] == "13"
    assert "detail_owner_occupant: *MERICHEM TECHNOLOGIES LLC" in doc.text
    assert "detail_buyer: SCHARUNOVYCH VIRNA" in doc.text
    assert "detail_buyer_phone: (281) 948-6344" in doc.text
    assert doc.published_at is None

    with pytest.raises(SourceParseError, match="project number did not match"):
        retrieve_detail(
            "26017927",
            "Building Pmt",
            event_date="2026-09-02",
            site_address="8930 GULF FWY",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )


@pytest.mark.parametrize("permit_type", ["", "Demolition"])
def test_houston_exact_sold_detail_rejects_missing_or_conflicting_type(permit_type):
    type_row = f"<tr><td>Permit Type:</td><td>{permit_type}</td></tr>" if permit_type else ""
    body = f"""<html><table>
      <tr><td>Project No:</td><td>26051624</td></tr>
      <tr><td>Date:</td><td>2026/09/02 00:00:00</td></tr>
      <tr><td>Job Address:</td><td>8930 GULF FWY A</td></tr>
      {type_row}
      <tr><td>Buyer:</td><td>SCHARUNOVYCH VIRNA</td></tr>
    </table></html>"""

    with pytest.raises(SourceParseError, match="detail type did not match"):
        retrieve_detail(
            "26051624",
            "Building Pmt",
            event_date="2026-09-02",
            site_address="8930 GULF FWY",
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, text=body, headers={"Content-Type": "text/html"}
                    )
                )
            ),
        )


def test_houston_permit_record_id_uses_source_record_fact_label():
    facts = permit_facts(
        "houston-weekly-permits",
        "row: 26051624\ndate: 2026-09-02\n"
        "event: sold\ntype: Building Pmt\naddress: 8930 GULF FWY A",
    )
    values = {item["label"]: item["value"] for item in facts}
    assert values["Source record"] == "26051624"
    assert "Permit / case" not in values


def test_houston_sale_event_is_not_projected_as_permit_issue_date():
    from gridlens.domain.permit_interpretation import assess_permit

    event_date = "2026-09-02"
    label = "Permit sale date (weekly Sold Permits report)"
    assessment = assess_permit(
        {
            "event_date": event_date,
            "event_date_label": label,
            "html_url": "https://cohtora.houstontx.gov/official/detail",
            "permit": {
                "source_type": "houston-weekly-permits",
                "row_id": "26051624",
                "address": "8930 GULF FWY A",
                "city": "Houston",
                "state": "TX",
                "description": "Convert warehouse to laboratory",
                "status": "Unknown",
                "permit_event": "Sold (approved)",
                "type": "Building Pmt",
                "source_fields": {"date": "Permit Date"},
            },
        }
    )
    assert assessment["issue_date"] is None
    assert assessment["issue_date_label"] is None
    assert assessment["event_date"] == event_date
    assert assessment["event_date_label"] == label


@pytest.mark.parametrize(
    ("source_type", "status", "event", "accepted"),
    [
        ("houston-weekly-permits", "Unknown", "sold", True),
        ("el-paso-new-commercial-permits", "Unknown", "issued", True),
        ("el-paso-new-commercial-permits", "Closed", "issued", False),
        ("el-paso-new-commercial-permits", "Cancelled", "issued", False),
    ],
)
def test_city_permit_event_semantics_keep_lifecycle_unknown(
    source_type: str, status: str, event: str, accepted: bool
):
    event_label = (
        "Permit sale date (weekly Sold Permits report)"
        if source_type == "houston-weekly-permits"
        else "ISSUEDATE (official layer issue-event field)"
    )
    record = {
        "event_date": "2026-08-31",
        "event_date_label": event_label,
        "html_url": "https://city.example/permit/1",
        "permit": {
            "source_type": source_type,
            "row_id": "CASE-1",
            "project": "CASE-1",
            "issuance_event": event,
            "status": status,
            "address": "100 MAIN ST",
            "city": "Houston" if source_type == "houston-weekly-permits" else "El Paso",
            "state": "TX",
            "description": "New construction of a data center building",
        },
    }
    result = assess_permit(record, as_of=date(2026, 10, 1))
    assert (result["decision"] == "accepted") is accepted
    expected_issue_date = None if source_type == "houston-weekly-permits" else "2026-08-31"
    assert result["issue_date"] == expected_issue_date
    assert result["issue_date_label"] == (
        None if source_type == "houston-weekly-permits" else event_label
    )
    assert result["event_date"] == "2026-08-31"
    assert result["event_date_label"] == event_label
    assert result["permit_event"] == event
    assert result["permit_status"] == status
