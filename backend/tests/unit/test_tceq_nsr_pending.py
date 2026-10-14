from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_nsr_pending import (
    LISTING_URL,
    SOURCE_ID,
    _record,
    parse_listing,
    retrieve,
    summary_from_text,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tceq-nsr-pending-excerpt.html"
TODAY = date(2026, 10, 14)
# Text extracted from the official 182126 Plain Language Summary PDF on 2026-10-14.
LONGHORN_SUMMARY = (
    "Plain Language Summary for New Source Review (NSR) Initial Application for Air New Source "
    "Review Permit Number 182126, GHGPSDTX263 and PSDTX1688 ... Crusoe Energy Systems LLC "
    "(CN606257079) has submitted an application for an initial permit 182126, GHGPSDTX263, and "
    "PSDTX1688. The Longhorn Data Center (RN112029061) will generate electricity at 32.50792, "
    "-99.77722, Abilene, Taylor County. This permit will authorize additional power generation "
    "equipment for onsite consumption in data center buildings. Crusoe Energy Systems LLC has "
    "listed in the application the pollutants"
)


def rows():
    return {row["facility"]: row for row in parse_listing(FIXTURE.read_bytes(), TODAY)}


def test_listing_rows_keep_stable_project_permits_and_received_date():
    parsed = rows()
    longhorn = parsed["LONGHORN DATA CENTER"]
    assert longhorn["project"] == "400428"
    assert longhorn["applicant"] == "CRUSOE ENERGY SYSTEMS LLC"
    assert longhorn["permits"] == ["182126", "GHGPSDTX263", "PSDTX1688"]
    assert longhorn["received"] == date(2025, 11, 7)
    assert longhorn["application_url"].startswith("https://www.tceq.texas.gov/")
    assert len(parsed) >= 20


def test_listing_changes_fail_visibly():
    with pytest.raises(SourceParseError, match="heading"):
        parse_listing(b"<html><h2>Login</h2></html>", TODAY)
    body = FIXTURE.read_bytes().replace(b"11/07/2025", b"11/07/2031")
    with pytest.raises(SourceParseError, match="future"):
        parse_listing(body, TODAY)


def test_summary_site_and_purpose():
    summary = summary_from_text(LONGHORN_SUMMARY, "182126")
    assert summary["city"] == "Abilene" and summary["county"] == "Taylor"
    assert summary["regulated_entity"] == "RN112029061"
    assert (summary["latitude"], summary["longitude"]) == (32.50792, -99.77722)
    assert "onsite consumption in data center buildings" in summary["purpose"]
    with pytest.raises(SourceParseError):
        summary_from_text(LONGHORN_SUMMARY, "999999")


def test_data_center_onsite_generation_is_a_signal_not_a_supply_answer():
    record = _record(rows()["LONGHORN DATA CENTER"], summary_from_text(LONGHORN_SUMMARY, "182126"))
    assert evaluator_version(record) == "tceq-nsr-pending-v1"
    result = assess_permit(record, as_of=TODAY)
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["location"] == "Abilene, Taylor County, TX"
    assert result["power_activity"] == "facility-expansion"
    assert result["action"] == "proposed onsite power generation for on-site load"
    assert "proposed supply, not proof of adequate power" in result["reason"]
    assert result["event_date"] == "2025-11-07"
    assert result["coordinates"] == [32.50792, -99.77722]


def test_unsited_or_non_load_filings_stay_evidence():
    parsed = rows()
    unsited = assess_permit(_record(parsed["LONGHORN DATA CENTER"], None), as_of=TODAY)
    assert unsited["decision"] == "rejected" and "did not yield a site" in unsited["reason"]
    other = next(
        row
        for row in parsed.values()
        if "DATA CENTER" not in f"{row['applicant']} {row['facility']}"
    )
    summary = {
        "city": "Odessa", "county": "Ector", "text": "",
        "purpose": "This permit will authorize a gas plant.",
    }
    rejected = assess_permit(_record(other, summary), as_of=TODAY)
    assert rejected["decision"] == "rejected" and "not a load-side" in rejected["reason"]


def test_retrieve_bounds_summary_fetches_and_survives_a_missing_pdf():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == LISTING_URL:
            return httpx.Response(200, content=FIXTURE.read_bytes())
        return httpx.Response(404)

    records = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_summaries": 2}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(records) >= 20
    assert len(requested) == 3  # listing plus two bounded summary attempts
    assert all(record["permit"]["summary_fetched"] is False for record in records)
    with pytest.raises(SourceParseError):
        retrieve({"id": "other", "endpoint": LISTING_URL})
