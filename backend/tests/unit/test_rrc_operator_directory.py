from __future__ import annotations

import hashlib
import io
import time
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import Workbook

from gridlens.ingestion.adapters.rrc_operator_directory import (
    CACHE_TTL_SECONDS,
    _reset_cache_for_tests,
    is_rrc_directory_workbook_url,
    load_current_directory,
    parse_directory_workbook,
    select_directory_link,
)
from gridlens.intelligence.company_contact_discovery import (
    _rrc_directory_contact,
    _split_native_directory_urls,
)

NOW = datetime(2026, 10, 27, 19, 0, tzinfo=UTC)
INDEX_URL = (
    "https://www.rrc.texas.gov/oil-and-gas/research-and-statistics/"
    "operator-information/oil-gas-directory-operator-contact/"
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx",
            True,
        ),
        (
            "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26-txt.txt",
            False,
        ),
        (
            "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx?x=1",
            False,
        ),
        (
            "https://evil.example/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx",
            False,
        ),
    ],
)
def test_native_p5_workbook_predicate_only_accepts_canonical_fixed_host(url, expected):
    assert is_rrc_directory_workbook_url(url) is expected


def test_native_candidate_split_preserves_non_p5_hints_and_requires_rrc_identity():
    p5_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    generic_urls = [f"https://company.example/page-{index}" for index in range(4)]
    candidates = [p5_url, *generic_urls]

    filtered, has_native_intent = _split_native_directory_urls(candidates, native_eligible=True)
    assert filtered == generic_urls
    assert has_native_intent is True
    assert _split_native_directory_urls(candidates, native_eligible=False) == (candidates, False)
    assert _split_native_directory_urls([p5_url], native_eligible=True) == ([], True)


def _workbook(
    *,
    duplicate: bool = False,
    emergency_only: bool = False,
    status: str = "Active",
    alter_header: bool = False,
    country: str = "USA",
    header_timestamp: str = "10/27/2026 12:01:48 PM",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Oil and Gas Directory"
    sheet.append([header_timestamp])
    sheet.append([None, None, "Railroad Commission of Texas Oil & Gas P5"])
    sheet.append(
        [
            "Organization Number" if alter_header else "Org Number",
            "Org Name",
            "",
            "First Address Line",
            "Second Address Line",
            "Apt/Suite and #",
            "City",
            "State",
            "Zip",
            "Country",
            "Phone",
            "Emergency",
            "Mail Ret'd by PO",
            "P5 Status",
        ]
    )
    phone = "" if emergency_only else "8179283260"
    sheet.append(
        [
            "102606",
            "DE V Operating, LLC",
            "",
            "PO BOX 1",
            "",
            "",
            "DALLAS",
            "TX",
            "75001",
            country,
            phone,
            "8179289999",
            "No",
            status,
        ]
    )
    if duplicate:
        sheet.append(
            [
                "102606",
                "DE V Operating, LLC",
                "",
                "PO BOX 2",
                "",
                "",
                "DALLAS",
                "TX",
                "75001",
                "USA",
                "8179281111",
                "8179289999",
                "No",
                "Active",
            ]
        )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_select_directory_link_accepts_one_exact_official_xlsx_link():
    html = (
        b"<html><head><title>Oil &amp; Gas Directory - Operator Contact Information</title></head>"
        b"<body><p>Railroad Commission of Texas. "
        b"Information available in this query is updated nightly. "
        b"These downloadable files contain data as of October 27th, 2026.</p>"
        b'<a href="/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx">'
        b"Oil and Gas Directory, (Excel)</a>"
        b'<a href="/media/mz2knwg5/oil-and-gas-directory-10-27-26-txt.txt">ASCII</a>'
        b"</body></html>"
    )

    result = select_directory_link(html, INDEX_URL)

    assert result["url"] == (
        "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    )
    assert result["filename_date"] == "2026-10-27"
    assert result["landing_freshness_statement"] == (
        "Information available in this query is updated nightly. ; "
        "These downloadable files contain data as of October 27th, 2026."
    )


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/oil-and-gas-directory-10-27-26.xlsx",
        "http://www.rrc.texas.gov/media/a/oil-and-gas-directory-10-27-26.xlsx",
        "https://www.rrc.texas.gov/other/oil-and-gas-directory-10-27-26.xlsx",
        "https://www.rrc.texas.gov/media/a/oil-and-gas-directory-10-27-26.xlsx?download=1",
    ],
)
def test_select_directory_link_rejects_noncanonical_download_urls(href: str):
    html = (
        "<title>Oil &amp; Gas Directory - Operator Contact Information</title>"
        "<p>Railroad Commission of Texas</p>"
        f'<a href="{href}">Oil and Gas Directory (Excel)</a>'
    ).encode()

    with pytest.raises(ValueError):
        select_directory_link(html, INDEX_URL)


def test_select_directory_link_fails_closed_on_multiple_dated_workbooks():
    html = b"""<title>Oil &amp; Gas Directory - Operator Contact Information</title>
    <p>Railroad Commission of Texas</p>
    <a href="/media/a/oil-and-gas-directory-10-27-26.xlsx">Excel current</a>
    <a href="/media/b/oil-and-gas-directory-10-26-26.xlsx">Excel archive</a>"""

    with pytest.raises(ValueError, match="ambiguous"):
        select_directory_link(html, INDEX_URL)


def test_parse_workbook_keeps_raw_hash_and_dates_separate_from_observation():
    body = _workbook()
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"

    result = parse_directory_workbook(body, source_url, NOW)

    assert result["raw_sha256"] == hashlib.sha256(body).hexdigest()
    assert result["filename_date"] == "2026-10-27"
    assert result["workbook_header_date"] == "2026-10-27"
    assert result["workbook_header_timestamp"] == "10/27/2026 12:01:48 PM"
    assert result["observed_at"] == NOW.isoformat()
    assert result["landing_freshness_statement"] is None
    assert result["operators"]["102606"] == [
        {
            "operator_number": "102606",
            "organization": "DE V Operating, LLC",
            "country": "USA",
            "normal_phone": "8179283260",
            "status": "Active",
            "row_number": 4,
        }
    ]


@pytest.mark.parametrize(
    "header_timestamp",
    ["01/01/2020 12:00:00 PM", "11/01/2030 12:00:00 PM"],
)
def test_parse_workbook_rejects_stale_or_far_future_publisher_dates(header_timestamp):
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    with pytest.raises(ValueError, match="publisher date"):
        parse_directory_workbook(
            _workbook(header_timestamp=header_timestamp),
            source_url,
            NOW,
        )


def test_parse_workbook_never_retains_emergency_field_and_rejects_duplicates():
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    emergency_only = parse_directory_workbook(_workbook(emergency_only=True), source_url, NOW)
    assert emergency_only["operators"]["102606"][0]["normal_phone"] == ""
    assert "emergency_phone" not in emergency_only["operators"]["102606"][0]

    duplicate = parse_directory_workbook(_workbook(duplicate=True), source_url, NOW)
    assert len(duplicate["operators"]["102606"]) == 2


def test_contact_adapter_requires_exact_operator_brand_active_status_and_normal_phone():
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    snapshot = parse_directory_workbook(_workbook(), source_url, NOW)
    snapshot["landing_freshness_statement"] = (
        "Information available in this query is updated nightly. ; "
        "These downloadable files contain data as of October 27th, 2026."
    )

    result = _rrc_directory_contact(snapshot, "102606", "DE V OPERATING, LLC")
    assert result is not None
    doc, method = result
    assert method["kind"] == "phone"
    assert method["value"] == "8179283260"
    assert method["quote"] == "Phone: 8179283260"
    assert doc.published_at.isoformat() == "2026-10-27"
    assert doc.observed_at == NOW
    assert "Country: USA" in doc.text
    assert "Emergency: 8179289999" not in doc.text
    assert "Workbook SHA-256:" in doc.text
    assert "timezone unspecified" in doc.text

    assert _rrc_directory_contact(snapshot, "102606", "DE V OPERATING II, LLC") is None
    assert _rrc_directory_contact(snapshot, "102606", "DE V OPERATING, LLC") is not None
    assert _rrc_directory_contact(snapshot, "102607", "DE V OPERATING, LLC") is None

    snapshot["operators"]["102606"][0]["status"] = "Delinquent"
    assert _rrc_directory_contact(snapshot, "102606", "DE V OPERATING, LLC") is None

    snapshot = parse_directory_workbook(_workbook(emergency_only=True), source_url, NOW)
    assert _rrc_directory_contact(snapshot, "102606", "DE V OPERATING, LLC") is None


def test_contact_adapter_requires_explicit_supported_country():
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    for country in ("", "Mexico", "GB"):
        snapshot = parse_directory_workbook(
            _workbook(country=country),
            source_url,
            NOW,
        )
        assert _rrc_directory_contact(snapshot, "102606", "DE V OPERATING, LLC") is None


def test_non_rrc_research_digest_matches_legacy_shape(monkeypatch):
    import gridlens.intelligence.company_contact_discovery as discovery
    from gridlens.domain.pursuit_research import fingerprint

    anchor = {"anchor": "unchanged"}
    hints = {"urls": [], "fingerprint": "ignored-without-urls"}
    imports = []
    monkeypatch.setattr(discovery, "_anchor_digest", lambda *_args: anchor)
    monkeypatch.setattr(discovery, "_company_hyperlink_hints", lambda *_args: hints)
    monkeypatch.setattr(discovery, "_active_import_rows", lambda *_args: imports)
    session = type("Session", (), {"get": lambda *_args: None})()

    expected_legacy = fingerprint(
        {
            "anchor": anchor,
            "hyperlink_hints": None,
            "imports": [],
        }
    )
    actual = discovery._research_source_digest(session, object(), "not-an-rrc-id")

    assert actual == expected_legacy


def test_parse_workbook_rejects_unknown_status_and_changed_headers():
    source_url = "https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx"
    with pytest.raises(ValueError, match="status"):
        parse_directory_workbook(
            _workbook(status="UnrecognizedStatus"),
            source_url,
            NOW,
        )
    with pytest.raises(ValueError, match="headers"):
        parse_directory_workbook(_workbook(alter_header=True), source_url, NOW)


def test_directory_snapshot_cache_preserves_original_observation(monkeypatch):
    import gridlens.ingestion.adapters.rrc_operator_directory as directory

    calls = []
    snapshots = [
        {
            "operators": {},
            "observed_at": NOW.isoformat(),
            "workbook_header_date": "2026-10-27",
            "raw_sha256": "a" * 64,
        },
        {
            "operators": {},
            "observed_at": "2026-10-28T19:00:00+00:00",
            "workbook_header_date": "2026-10-28",
            "raw_sha256": "b" * 64,
        },
    ]

    def retrieve(*_args, **_kwargs):
        calls.append(True)
        return snapshots.pop(0)

    _reset_cache_for_tests()
    monkeypatch.setattr(directory, "run_isolated", retrieve)
    first = load_current_directory(deadline=time.monotonic() + 100, now=NOW)
    second = load_current_directory(deadline=time.monotonic() + 100, now=NOW)

    assert len(calls) == 1
    assert first["observed_at"] == second["observed_at"] == NOW.isoformat()
    assert second["raw_sha256"] == first["raw_sha256"]

    with pytest.raises(ValueError, match="publisher date"):
        load_current_directory(
            deadline=time.monotonic() + 100,
            now=NOW + timedelta(days=31),
        )
    assert len(calls) == 1  # The cache hit was rejected without another download.

    directory._cached_at = directory.time.monotonic() - CACHE_TTL_SECONDS - 1
    refreshed = load_current_directory(
        deadline=time.monotonic() + 100,
        now=datetime(2026, 10, 28, 19, 0, tzinfo=UTC),
    )
    assert len(calls) == 2
    assert refreshed["observed_at"] == "2026-10-28T19:00:00+00:00"
    _reset_cache_for_tests()
