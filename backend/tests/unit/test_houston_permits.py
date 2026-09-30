import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.houston_permits import HEADERS, INDEX, parse_report, retrieve


def workbook(*, duplicate=False, conflict=False, footer=True):
    rows = [
        ["Web eReport"],
        ["From: 2026/09/07 "],
        ["To : 2026/09/14 "],
        [],
        HEADERS,
        [
            "77002",
            "2026/09/09",
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
    sheet = "".join(
        "<row>"
        + "".join(
            f'<c r="{chr(65 + j)}{i + 1}" t="s"><v>{strings.index(value)}</v></c>'
            for j, value in enumerate(row)
        )
        + "</row>"
        for i, row in enumerate(rows)
    )
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
    return out.getvalue()


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
            "30 days old",
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
