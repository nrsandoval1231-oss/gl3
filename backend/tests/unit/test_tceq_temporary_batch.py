from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_temporary_batch import (
    LISTING_URL,
    SOURCE_ID,
    TEMPORARY,
    notice_from_text,
    parse_listing,
    record,
    retrieve,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tceq-pending-summaries-excerpt.html"
TODAY = date(2026, 10, 14)
# Excerpt of the official 173154L003 notice (NAPD), retrieved 2026-10-14.
DPR_NOTICE = (
    "Air Quality Standard Permit for Concrete Batch Plants Proposed Registration No. 173154L003 "
    "Application. Amrize South Central, Inc., has applied to the Texas Commission on Environmental "
    "Quality (TCEQ) for an Air Quality Standard Permit, Registration No. 173154L003, which would "
    "authorize construction of a temporary concrete batch plant located at the following driving "
    "directions: heading south on US Highway 67, take exit toward Railport and Miller Road. Turn "
    "right on to Miller Road and go 1.8 miles on Miller Road. The location will be on the right, "
    "Midlothian, Ellis County, Texas 76065. ... "
    "https://gisweb.tceq.texas.gov/LocationMapper/?marker=-97.065,32.474556&level=13. ... "
    "This application was submitted to the TCEQ on May 14, 2026. ... "
    "Notice Issuance Date: May 28, 2026"
)


def rows():
    return {row["facility"]: row for row in parse_listing(FIXTURE.read_bytes())}


def test_listing_keeps_project_ids_and_flags_only_temporary_batch_plants():
    parsed = rows()
    dpr = parsed["DPR DATA CENTER TEMPORARY BATCH PLANT"]
    assert dpr["registration"] == "173154L003" and dpr["project"].isdigit()
    temporary = [name for name in parsed if TEMPORARY.search(name)]
    assert sorted(temporary) == [
        "DPR DATA CENTER TEMPORARY BATCH PLANT",
        "PROJECT APEX TEMPORARY CONCRETE BATCH PLANTS",
    ]
    with pytest.raises(SourceParseError, match="concrete batch plant section"):
        parse_listing(b"<html><table></table></html>")


def test_notice_gives_dates_site_and_coordinates():
    notice = notice_from_text(DPR_NOTICE, "173154L003")
    assert notice["submitted"] == "2026-05-14" and notice["issued"] == "2026-05-28"
    assert (notice["city"], notice["county"]) == ("Midlothian", "Ellis")
    assert (notice["latitude"], notice["longitude"]) == (32.474556, -97.065)
    with pytest.raises(SourceParseError):
        notice_from_text(DPR_NOTICE, "999999")


def test_data_center_batch_plant_is_a_construction_signal():
    item = record(
        rows()["DPR DATA CENTER TEMPORARY BATCH PLANT"],
        notice_from_text(DPR_NOTICE, "173154L003"),
    )
    assert evaluator_version(item) == "tceq-temporary-batch-v1"
    result = assess_permit(item, as_of=TODAY)
    assert result["decision"] == "accepted" and result["tier"] == "Signal"
    assert result["location"] == "Midlothian, Ellis County, TX"
    assert result["event_date"] == "2026-05-14"
    assert "not the project owner or GC" in result["reason"]


def test_unnamed_temporary_plant_stays_evidence():
    row = {
        "project": "1",
        "applicant": "Example Ready Mix",
        "facility": "PORTABLE TEMPORARY CBP 3",
        "registration": "173154L003",
    }
    result = assess_permit(record(row, notice_from_text(DPR_NOTICE, "173154L003")), as_of=TODAY)
    assert result["decision"] == "rejected"


def test_retrieve_withholds_failed_notices_and_reports_partial_snapshot(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == httpx.URL(LISTING_URL).path:
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=FIXTURE.read_bytes()
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    failed = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_notices": 5}}, client
    )
    assert len(failed) == 2 and all(
        r["partial_snapshot"] and r["rejected_record"]["error_code"] == "http_status_404"
        for r in failed
    )
    records = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_notices": 0}}, client
    )
    assert len(records) == 2 and all(r["presence_only"] and r["partial_snapshot"] for r in records)
