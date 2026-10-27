import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.houston_permits import HEADERS, INDEX, parse_report, retrieve


def workbook(
    *,
    duplicate=False,
    conflict=False,
    footer=True,
    serial_dates=False,
    date_system=1900,
    event_date="2026/09/09",
    week_start="2026/09/07",
    week_end="2026/09/14",
):
    rows = [
        ["Web eReport"],
        [f"From: {week_start} "],
        [f"To : {week_end} "],
        [],
        HEADERS,
        [
            "77002",
            event_date,
            "Building Pmt",
            "123",
            "1 Example Road",
            "New data center construction",
        ],
    ]
    if duplicate:
        rows.append([*rows[-1][:-1], "Conflicting site scope" if conflict else rows[-1][-1]])
    if footer:
        rows.extend(
            [
                [line]
                for line in (
                    "* Information provided to City by applicant on the building permit. "
                    "The City does not confirm or verify statement",
                    "by applicant. If you believe the project does not meet the deed restrictions "
                    "for this property, please contact ",
                    "the City of Houston's Deed Restriction Hotline at 713.437.6769.",
                )
            ]
        )
    strings = [value for row in rows for value in row]
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_rows = []
    for i, row in enumerate(rows):
        cells = []
        for j, value in enumerate(row):
            ref = f"{chr(65 + j)}{i + 1}"
            if serial_dates and i == 5 and j == 1:
                epoch = date(1904, 1, 1) if date_system == 1904 else date(1899, 12, 30)
                serial = (date.fromisoformat(event_date.replace("/", "-")) - epoch).days
                cells.append(f'<c r="{ref}"><v>{serial}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="s"><v>{strings.index(value)}</v></c>')
        sheet_rows.append("<row>" + "".join(cells) + "</row>")
    sheet = "".join(sheet_rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}">'
            + "".join("<si><t>" + escape(value) + "</t></si>" for value in strings)
            + "</sst>",
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>{sheet}</sheetData></worksheet>',
        )
        workbook_properties = '<workbookPr date1904="1"/>' if date_system == 1904 else ""
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{workbook_properties}</workbook>",
        )
    return out.getvalue()


@pytest.mark.parametrize("date_system", [1900, 1904])
def test_report_accepts_excel_serial_permit_dates(date_system):
    end, rows = parse_report(
        workbook(serial_dates=True, date_system=date_system),
        INDEX,
        today=date(2026, 9, 30),
    )
    assert end == date(2026, 9, 14)
    assert rows[0]["event_date"] == "2026-09-09"


def test_report_accepts_listing_date_at_either_week_boundary():
    end, rows = parse_report(
        workbook(event_date="2026/09/14"),
        INDEX,
        today=date(2026, 9, 30),
        listed_week_start=date(2026, 9, 14),
    )
    assert end == date(2026, 9, 14)
    assert rows[0]["event_date"] == "2026-09-14"


def test_report_rejects_unrelated_listing_date_and_nonweekly_interval():
    with pytest.raises(SourceParseError, match="listed sale week"):
        parse_report(
            workbook(),
            INDEX,
            today=date(2026, 9, 30),
            listed_week_start=date(2026, 9, 8),
        )
    with pytest.raises(SourceParseError, match="date interval"):
        parse_report(
            workbook(week_end="2026/09/15"), INDEX, today=date(2026, 9, 30)
        )


def test_report_duplicates_are_exact_only_and_preserve_unknowns():
    end, rows = parse_report(workbook(duplicate=True), INDEX, today=date(2026, 9, 30))
    assert end == date(2026, 9, 14) and len(rows) == 1
    assert rows[0]["permit"]["status"] == "Unknown"
    assert rows[0]["event_date"] == "2026-09-09"
    assert rows[0]["document_number"] == "123:Building Pmt:2026-09-09"
    with pytest.raises(SourceParseError, match="duplicate identity"):
        parse_report(workbook(duplicate=True, conflict=True), INDEX, today=date(2026, 9, 30))
    with pytest.raises(SourceParseError, match="footer"):
        parse_report(workbook(footer=False), INDEX, today=date(2026, 9, 30))
    with pytest.raises(SourceParseError, match="parse failed"):
        parse_report(b"not a workbook", INDEX, today=date(2026, 9, 30))


def test_source_refuses_foreign_download_and_stale_listing():
    today = datetime.now(UTC).date()
    for stamp, url, error in (
        (today, "https://evil.example/file.xlsx", "official path"),
        (
            today - timedelta(days=31),
            "https://www.houstonpermittingcenter.org/sites/g/files/test.xlsx",
            "has not posted a weekly report since",
        ),
        (
            today + timedelta(days=3),
            "https://www.houstonpermittingcenter.org/sites/g/files/test.xlsx",
            "dated in the future",
        ),
    ):
        calls = []

        def handler(request, calls=calls, url=url, stamp=stamp):
            calls.append(str(request.url))
            return httpx.Response(200, text=f'<a href="{url}">{stamp:%B %d, %Y}</a>')

        with pytest.raises(SourceParseError, match=error):
            retrieve(
                {"id": "houston-weekly-permits", "endpoint": INDEX},
                httpx.Client(transport=httpx.MockTransport(handler)),
            )
        assert calls == [INDEX]
