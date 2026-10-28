import hashlib
import io
import json
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
    address="1 Example Road",
    description="New data center construction",
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
            address,
            description,
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


def test_serial_and_text_dates_have_the_same_semantic_hash_and_duplicate_identity():
    _, text_rows = parse_report(workbook(), INDEX, today=date(2026, 9, 30))
    _, serial_rows = parse_report(workbook(serial_dates=True), INDEX, today=date(2026, 9, 30))
    assert serial_rows[0]["source_hash"] == text_rows[0]["source_hash"]
    _, duplicate_rows = parse_report(
        workbook(serial_dates=True, duplicate=True), INDEX, today=date(2026, 9, 30)
    )
    assert len(duplicate_rows) == 1
    legacy_material = [
        "77002",
        "2026/09/09",
        "Building Pmt",
        "123",
        "1 Example Road",
        "New data center construction",
    ]
    assert (
        text_rows[0]["source_hash"]
        == hashlib.sha256(json.dumps(legacy_material, ensure_ascii=False).encode()).hexdigest()
    )


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
        parse_report(workbook(week_end="2026/09/15"), INDEX, today=date(2026, 9, 30))


def _retrieval_client(start, end, first, second):
    first_url = f"https://{INDEX.split('/')[2]}/sites/g/files/first.xlsx"
    second_url = f"https://{INDEX.split('/')[2]}/sites/g/files/second.xlsx"
    listing = (
        f'<a href="{first_url}">{start:%B} {start.day}, {start.year}</a>'
        f'<a href="{second_url}">{end:%B} {end.day}, {end.year}</a>'
    )

    def handler(request):
        if str(request.url) == INDEX:
            return httpx.Response(200, headers={"content-type": "text/html"}, text=listing)
        body = first if request.url.path.endswith("first.xlsx") else second
        return httpx.Response(
            200,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            content=body,
        )

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_retrieve_deduplicates_overlapping_string_and_serial_date_reports():
    end = datetime.now(UTC).date()
    start = end - timedelta(days=7)
    issued = start + timedelta(days=2)
    params = {
        "week_start": start.strftime("%Y/%m/%d"),
        "week_end": end.strftime("%Y/%m/%d"),
        "event_date": issued.strftime("%Y/%m/%d"),
    }
    text_report = workbook(**params)
    serial_report = workbook(serial_dates=True, **params)
    records = retrieve(
        {"id": "houston-weekly-permits", "endpoint": INDEX},
        _retrieval_client(start, end, text_report, serial_report),
    )
    assert len(records) == 1
    assert records[0]["document_number"] == f"123:Building Pmt:{issued.isoformat()}"


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [("address", "2 Example Road"), ("description", "Changed permit work")],
)
def test_retrieve_keeps_true_overlapping_report_conflicts_visible(field, changed_value):
    end = datetime.now(UTC).date()
    start = end - timedelta(days=7)
    issued = start + timedelta(days=2)
    params = {
        "week_start": start.strftime("%Y/%m/%d"),
        "week_end": end.strftime("%Y/%m/%d"),
        "event_date": issued.strftime("%Y/%m/%d"),
    }
    first = workbook(**params)
    second = workbook(**{**params, field: changed_value})
    with pytest.raises(SourceParseError, match="overlapping reports conflict"):
        retrieve(
            {"id": "houston-weekly-permits", "endpoint": INDEX},
            _retrieval_client(start, end, first, second),
        )


def test_retrieve_preserves_distinct_permit_dates_as_distinct_identities():
    end = datetime.now(UTC).date()
    start = end - timedelta(days=7)
    first_date = start + timedelta(days=2)
    next_date = start + timedelta(days=3)
    params = {
        "week_start": start.strftime("%Y/%m/%d"),
        "week_end": end.strftime("%Y/%m/%d"),
    }
    records = retrieve(
        {"id": "houston-weekly-permits", "endpoint": INDEX},
        _retrieval_client(
            start,
            end,
            workbook(event_date=first_date.strftime("%Y/%m/%d"), **params),
            workbook(event_date=next_date.strftime("%Y/%m/%d"), **params),
        ),
    )
    assert {row["event_date"] for row in records} == {
        first_date.isoformat(),
        next_date.isoformat(),
    }


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
