import hashlib
import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ok_deq_public_review import (
    _OIL_GAS_FACILITY,
    HOST,
    LISTING_URL,
    MAX_RECORDS,
    _record,
    parse_listing,
    retrieve,
)
from gridlens.ingestion.registry import load_registry

FIXTURES = Path(__file__).parents[1] / "fixtures"
FIXTURE = FIXTURES / "ok-deq-oil-gas-discovery-excerpt.html"
MANIFEST = FIXTURES / "ok-deq-oil-gas-discovery-manifest.json"


def test_real_oklahoma_oil_gas_facility_rows_are_retained_as_discovery_evidence():
    fixture_bytes = FIXTURE.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["source_url"] == LISTING_URL
    assert manifest["original_listing_sha256"] == (
        "fbf0fddcc7614d0d7eef5465f1e628bb48de171f8c127c8733c01dce9c4fbb05"
    )
    assert manifest["fixture_sha256"] == hashlib.sha256(fixture_bytes).hexdigest()
    records = parse_listing(fixture_bytes)
    by_permit = {row["permit_no"]: row for row in records}

    assert set(by_permit) == {
        "2025-0673-TVR5",
        "2025-0662-C M-1",
        "2026-0504-C",
    }
    assert "2020-0146-TVR3" not in by_permit  # unrelated brick plant control
    assert by_permit["2025-0673-TVR5"]["company"] == "NATURAL GAS PIPELINE CO OF AMERICA"
    assert by_permit["2025-0673-TVR5"]["facility"] == "COMPRESSOR STATION 102"
    assert by_permit["2025-0673-TVR5"]["location"] == "Beaver County, OK"
    assert by_permit["2025-0673-TVR5"]["event_date"] == "2026-07-28"
    assert by_permit["2025-0662-C M-1"]["event_date"] == "2026-04-30"
    assert by_permit["2026-0504-C"]["event_date"] == "2026-10-28"
    assert by_permit["2026-0504-C"]["html_url"].endswith("id=1073280")

    for record in records:
        assert record["tags"] == []
        assert "hp" not in record["facility"].casefold()
        assert not any(key in record for key in ("equipment", "rating", "drive", "demand_mw"))


def test_facility_match_is_narrow_and_does_not_use_ambiguous_company_name():
    assert _OIL_GAS_FACILITY.search("Lippencott Compressor Station")
    assert _OIL_GAS_FACILITY.search("Kingfisher Natural Gas Processing Plant")
    assert not _OIL_GAS_FACILITY.search("Compressor Supply Factory")
    assert not _OIL_GAS_FACILITY.search("Air Compressor Manufacturing Station")
    assert not _OIL_GAS_FACILITY.search("Gas Plant")
    assert not _OIL_GAS_FACILITY.search("Saltwater Disposal")

    unrelated_company = b"""<html><body><table><tr>
    <th>Division</th><th>County</th><th>Company</th><th>Facility</th><th>Permit #</th>
    <th>Tier</th><th>Type</th><th>Step</th><th>Staff Name</th><th>Status</th>
    <th>Related Information</th></tr><tr><td>AQD</td><td>Oklahoma</td>
    <td>Air Compressor Supply Co</td><td>Manufacturing Facility</td><td>CTRL-1</td>
    <td>Tier I</td><td>Permit</td><td>Technical Review</td><td>Staff</td>
    <td>Under Review</td><td></td></tr></table></body></html>"""
    assert parse_listing(unrelated_company) == []


def test_discovery_records_remain_rejected_by_legacy_permit_assessment():
    rows = parse_listing(FIXTURE.read_bytes())
    for row in rows:
        # Build through the adapter's public record shape while retaining only the
        # source-reported listing values. No schedule, drive, or rating is added.
        permit_record = _record(row)
        assessment = assess_permit(permit_record, as_of=date(2026, 10, 30))
        assert "electric" not in permit_record["abstract"].casefold()
        assert "hp" not in permit_record["abstract"].casefold()
        assert assessment["decision"] == "rejected"
        assert assessment["reported_power_facts"] == []
        assert assessment["power_signals"] == []


def test_duplicate_permits_still_fail_closed():
    body = FIXTURE.read_text(encoding="utf-8")
    duplicate_row = body.split("<tr><td>AQD", 2)[2].split("</tbody>", 1)[0]
    duplicated = body.replace("</tbody>", f"<tr><td>AQD{duplicate_row}</tbody>")
    with pytest.raises(SourceParseError, match="duplicate permit number"):
        parse_listing(duplicated.encode())


def test_record_limit_still_bounds_matching_source_rows():
    body = FIXTURE.read_text(encoding="utf-8")
    template = next(row for row in re.findall(r"<tr\b.*?</tr>", body, re.S) if "2026-0504-C" in row)
    rows = "".join(
        template.replace("2026-0504-C", f"2026-{index:04}-C") for index in range(1, MAX_RECORDS + 2)
    )
    header = body.split("<tbody>", 1)[0]
    oversized = f"{header}<tbody>{rows}</tbody></table></body></html>".encode()
    with pytest.raises(SourceParseError, match="relevant row count exceeds its bound"):
        parse_listing(oversized)


def test_bounded_retrieval_keeps_real_discovery_rows_without_changing_source_guards():
    body = FIXTURE.read_bytes()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=body,
        )

    client = httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler))
    source = next(row for row in load_registry() if row["id"] == "oklahoma-deq-public-review")
    records = retrieve(source, client)

    assert len(records) == 3
    assert [row["document_number"] for row in records] == [
        "OKDEQ-2025-0673-TVR5",
        "OKDEQ-2025-0662-C-M-1",
        "OKDEQ-2026-0504-C",
    ]
    assert seen[0].url == LISTING_URL
    assert seen[0].url.host == HOST
    assert seen[0].headers["user-agent"].startswith("GridLens public source reader/")
    assert all(row["permit"]["power_signals"] == [] for row in records)
    assert all("equipment" not in row["abstract"].casefold() for row in records)
    assert MAX_RECORDS == 400
    client.close()
