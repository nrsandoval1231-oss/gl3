from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from gridlens.domain.air_permit_hours import classify_operating_hours
from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_egu_search import _record as egu_record
from gridlens.ingestion.adapters.tceq_egu_search import parse_results
from gridlens.ingestion.adapters.tceq_http import _route, read_tceq_response
from gridlens.ingestion.adapters.tceq_nsr_pending import (
    LISTING_URL,
    RELEVANT_NAME,
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


def test_malformed_date_isolated_when_application_project_identity_is_stable():
    body = FIXTURE.read_bytes().replace(b"11/07/2025", b"not-a-date", 1)
    rejected = []
    rows = parse_listing(body, TODAY, rejected=rejected)
    assert len(rows) + len(rejected) >= 20
    assert any(item["identity"] == "TCEQ-400428" for item in rejected)
    assert rejected[0]["error_code"] == "tceq_received_date"
    assert len(rows) >= 19


def test_missing_permit_is_isolated_when_application_project_identity_is_stable():
    body = FIXTURE.read_bytes().replace(b"<td>182126, GHGPSDTX263, PSDTX1688</td>", b"<td></td>", 1)
    rejected = []
    rows = parse_listing(body, TODAY, rejected=rejected)
    assert any(item["identity"] == "TCEQ-400428" for item in rejected)
    assert any(row["project"] != "400428" for row in rows)


def test_retrieve_keeps_valid_siblings_when_one_listing_row_has_bad_date(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")
    malformed = FIXTURE.read_bytes().replace(b"11/07/2025", b"not-a-date", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=malformed)

    records = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_summaries": 0}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert any(
        row.get("document_number") == "TCEQ-400428"
        and row.get("partial_snapshot")
        and row["rejected_record"]["error_code"] == "tceq_received_date"
        for row in records
    )
    assert any(not row.get("presence_only") for row in records)


def test_records_pdf_route_is_exact_and_rejects_untrusted_query_shapes():
    valid = (
        "https://records.tceq.texas.gov/cs/idcplg?"
        "IdcService=TCEQ_EXTERNAL_SEARCH_GET_FILE&Rendition=Web&dID=7474076"
    )
    assert "dID=7474076" in _route(valid, "record_pdf")
    for url in (
        valid + "&redirect=https://127.0.0.1/",
        valid.replace("dID=7474076", "dID=0"),
        valid.replace("dID=7474076", "dID=7474076&dID=7474077"),
        valid.replace("records.tceq.texas.gov", "records.tceq.texas.gov.evil.example"),
        valid.replace("https://records", "https://user@records"),
        valid.replace("/cs/idcplg", "/cs/../idcplg"),
    ):
        with pytest.raises(SourceParseError):
            _route(url, "record_pdf")


def test_records_pdf_route_checks_redirect_host_type_signature_and_size(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(policy, "_public_ip", lambda _host: "8.8.8.8")
    url = (
        "https://records.tceq.texas.gov/cs/idcplg?"
        "IdcService=TCEQ_EXTERNAL_SEARCH_GET_FILE&Rendition=Web&dID=7474076"
    )
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 test"
            )
        ),
    )
    headers, body = read_tceq_response(client, url, 100, route="record_pdf")
    assert headers["content-type"] == "application/pdf" and body.startswith(b"%PDF-")
    for content_type, payload, limit in (
        ("text/html", b"%PDF-1.7", 100),
        ("application/pdf", b"not pdf", 100),
        ("application/pdf", b"%PDF-" + b"x" * 20, 10),
    ):
        bad_client = httpx.Client(
            follow_redirects=False,
            transport=httpx.MockTransport(
                lambda _request, content_type=content_type, payload=payload: httpx.Response(
                    200, headers={"content-type": content_type}, content=payload
                )
            ),
        )
        with pytest.raises((SourceParseError, ValueError)):
            read_tceq_response(bad_client, url, limit, route="record_pdf")
    redirect_client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "https://evil.example/a.pdf"})
        ),
    )
    with pytest.raises(SourceParseError):
        read_tceq_response(redirect_client, url, 100, route="record_pdf")


def test_relative_and_wrapped_application_link_resolves_to_official_pdf():
    body = FIXTURE.read_bytes().replace(
        b"https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/407086-tc.pdf",
        b"/assets/public/permitting/air/reports/applications/407086-tc.\r\npdf",
        1,
    )
    row = parse_listing(body, TODAY)[0]
    assert row["application_url"] == (
        "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/407086-tc.pdf"
    )


def test_tceq_href_format_alias_preserves_project_identity_and_hash():
    row = rows()["LONGHORN DATA CENTER"]
    alias = {
        **row,
        "notice_href": "/permitting/air/newsourcereview/airpermits-pendingpermit-apps#400428",
        "application_href": "/assets/public/permitting/air/reports/applications/400428-tc.\r\npdf",
    }
    equivalent = {
        **row,
        "notice_url": "https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps#400428",
        "application_url": "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/400428-tc.pdf",
    }
    first, second = _record(equivalent, None), _record(alias, None)
    assert first["document_number"] == second["document_number"]
    assert first["source_hash"] == second["source_hash"]
    assert second["permit"]["source_link_hrefs"]["application"].endswith(".\r\npdf")


def test_official_hosts_are_an_exact_set_and_records_documents_are_official():
    from gridlens.ingestion.adapters.tceq_http import OFFICIAL_HOSTS
    from gridlens.ingestion.adapters.tceq_nsr_pending import _official

    assert OFFICIAL_HOSTS == {
        "www.tceq.texas.gov",
        "www2.tceq.texas.gov",
        "www15.tceq.texas.gov",
        "records.tceq.texas.gov",
        "permit-search.tceq.texas.gov",
    }
    assert "www6.tceq.texas.gov" not in OFFICIAL_HOSTS
    record = (
        "https://records.tceq.texas.gov/cs/idcplg?"
        "IdcService=TCEQ_EXTERNAL_SEARCH_GET_FILE&Rendition=Web&dID=8600163"
    )
    assert _official(record) == record
    www6_application = (
        "https://www6.tceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf"
    )
    www6_summary = (
        "https://www6.tceq.texas.gov/downloads/permitting/air/bilingual/"
        "pending-permit-notices/182126-pls-english.pdf"
    )
    for href in (
        record.replace("records.tceq.texas.gov", "records.tceq.texas.gov.evil.example"),
        record.replace("records.tceq.texas.gov", "evil.tceq.texas.gov"),
        "https://nottceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf",
        "https://www14.tceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf",
        "https://user@www2.tceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf",
        record + "&redirect=https://127.0.0.1/",
        www6_application,
        www6_summary,
    ):
        with pytest.raises(SourceParseError, match="outside the official host"):
            _official(href)


@pytest.mark.parametrize(
    "href",
    [
        "//attacker.example/assets/public/permitting/air/reports/applications/a.pdf",
        "https://user@www.tceq.texas.gov/assets/public/permitting/air/reports/applications/a.pdf",
        "http://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/a.pdf",
        "/private",
        "/assets/public/permitting/air/reports/applications/%2fprivate.pdf",
        "/assets/public/permitting/air/reports/applications/../../private.pdf",
    ],
)
def test_tceq_application_link_rejects_foreign_or_unsafe_urls(href: str):
    from gridlens.ingestion.adapters.tceq_nsr_pending import _official

    with pytest.raises(SourceParseError):
        _official(href)


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
        "city": "Odessa",
        "county": "Ector",
        "text": "",
        "purpose": "This permit will authorize a gas plant.",
    }
    rejected = assess_permit(_record(other, summary), as_of=TODAY)
    assert rejected["decision"] == "rejected" and "not a load-side" in rejected["reason"]


def test_retrieve_withholds_unsummarized_filings_and_records_partial_failures(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == httpx.URL(LISTING_URL).path:
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=FIXTURE.read_bytes()
            )
        return httpx.Response(404)

    failed = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_summaries": 2}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(requested) == 3  # listing plus two bounded summary attempts
    failures = [r for r in failed if r.get("presence_only")]
    assert len(failures) >= 2 and all(r["partial_snapshot"] for r in failures)
    assert sum(r["rejected_record"]["error_code"] == "http_status_404" for r in failures) == 2
    records = retrieve(
        {"id": SOURCE_ID, "endpoint": LISTING_URL, "query": {"max_summaries": 0}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    # Relevant filings without a fetched summary are withheld, never emitted unsited,
    # but still reported as listed so snapshot reconciliation does not mark them absent.
    withheld = [r for r in records if r.get("presence_only")]
    processed = [r for r in records if not r.get("presence_only")]
    assert withheld and {r["document_number"] for r in withheld} >= {"TCEQ-400428"}
    assert processed and all(
        not RELEVANT_NAME.search(r["permit"]["facility"] + " " + r["permit"]["applicant"])
        for r in processed
    )
    with pytest.raises(SourceParseError):
        retrieve({"id": "other", "endpoint": LISTING_URL})


# Excerpts of official Plain Language Summaries retrieved 2026-10-14.
ALIGNED_RENEWAL = (
    "Plain Language Summary for New Source Review (NSR) Renewal Certification Application for Air "
    "New Source Review Permit Number 131651 ... Aligned Data Centers REIT LLC (Aligned) "
    "(CN606478972) has submitted an application for renewal of permit number 131651. The ADC Plano "
    "(RN102319506) is a data center at 2800 Summit Avenue, Plano, Texas, Collin County. This "
    "renewal application will authorize the continued operation of twenty (20) diesel engine "
    "generators and five (5) diesel tanks. Aligned has certified there will be no changes to the "
    "permit."
)
FERMI = (
    "Application for Air New Source Review Permit Number 183462, GHGPSDTX271, and PSDTX1704 ... "
    "Fermi Equipment Holdco LLC (CN606413086) has submitted an initial permit application for "
    "Permit Numbers 183462,GHGPSDTX271, and PSDTX1704 to authorize construction of a new natural "
    "gas-fired power plant on their East Campus. The Fermi America Project Matador (RN112258678) "
    "site is located in Carson County on the north side of US Route 60, approximately 15 miles "
    "northeast of Amarillo, Texas. The Fermi America Project Matador East Campus will provide "
    "electricity to an on-site data center campus."
)


def _row(facility: str, applicant: str, permit: str) -> dict:
    return {
        "project": "1",
        "applicant": applicant,
        "facility": facility,
        "permits": [permit],
        "received": date(2026, 3, 27),
        "application_stage": "Technically Complete Application",
        "notice_url": "https://www.tceq.texas.gov/x#1",
        "application_url": "https://www.tceq.texas.gov/x.pdf",
    }


def test_renewal_without_change_is_not_a_signal():
    summary = summary_from_text(ALIGNED_RENEWAL, "131651")
    assert summary["renewal"] and summary["city"] == "Plano" and summary["county"] == "Collin"
    result = assess_permit(
        _record(_row("ADC PLANO", "ALIGNED DATA CENTERS REIT LLC", "131651"), summary),
        as_of=TODAY,
    )
    assert result["decision"] == "rejected" and "Renewal" in result["reason"]


def test_county_wording_and_on_site_data_center_power_plant():
    summary = summary_from_text(FERMI, "183462")
    assert summary["county"] == "Carson" and summary["city"] == "Amarillo"
    assert "on-site data center campus" in summary["purpose"]
    result = assess_permit(
        _record(
            _row(
                "FERMI AMERICA PROJECT MATADOR EAST CAMPUS",
                "FERMI EQUIPMENT HOLDCO, LLC",
                "183462",
            ),
            summary,
        ),
        as_of=TODAY,
    )
    assert result["decision"] == "accepted"
    assert result["location"] == "Amarillo, Carson County, TX"


# Official Plain Language Summary text extracted on 2026-10-23 from the PDFs linked
# in tests/fixtures/tceq-pending-summaries-excerpt.html.
RECORDED_PLS = (
    ("80273L004", "tceq-pls-80273l004.txt", "PORTABLE CRUSHER 2", "ALLEN KELLER CO. I., LLC"),
    (
        "173154L003",
        "tceq-pls-173154l003.txt",
        "DPR DATA CENTER TEMPORARY BATCH PLANT",
        "AMRIZE SOUTH CENTRAL INC.",
    ),
    ("131651", "tceq-pls-131651.txt", "ADC PLANO", "ALIGNED DATA CENTERS REIT LLC"),
)


def test_recorded_summaries_reach_the_hours_classifier():
    """The summary body is classified. These three official rows have no backup or BTM clause.

    A portable rock crusher is not bridge power: the portable rule needs a
    generator, turbine, or engine in the same sentence.
    """
    fixtures = Path(__file__).parents[1] / "fixtures"
    recorded = {}
    for permit, filename, facility, applicant in RECORDED_PLS:
        summary = summary_from_text((fixtures / filename).read_text(), permit)
        row = _row(facility, applicant, permit)
        hours = _record(row, summary)["permit"]["operating_hours"]
        body_only = _record(row, {**summary, "purpose": None})["permit"]["operating_hours"]
        assert body_only == hours
        recorded[permit] = hours

    portable = recorded["80273L004"]
    assert portable["classification"] is None
    assert portable["conflict"] is False
    assert portable["hours_per_year"] == []
    assert portable["evidence"] == []
    portable_summary = summary_from_text(
        (fixtures / "tceq-pls-80273l004.txt").read_text(), "80273L004"
    )
    # The facility name also says PORTABLE. The rock-crusher body still does not.
    from_body = _record(
        _row("CRUSHER 2", "ALLEN KELLER CO. I., LLC", "80273L004"), portable_summary
    )["permit"]["operating_hours"]
    assert from_body["classification"] is None
    assert from_body["evidence"] == []
    assert (
        _record(_row("CRUSHER 2", "ALLEN KELLER CO. I., LLC", "80273L004"), None)["permit"][
            "operating_hours"
        ]["classification"]
        is None
    )

    batch = recorded["173154L003"]
    assert batch["classification"] is None
    assert batch["conflict"] is False
    assert batch["hours_per_year"] == [8760]
    assert batch["evidence"] == [{"clause": "unclassified_hours", "quote": "8,760 hours per year"}]
    assert (
        _record(
            _row(
                "DPR DATA CENTER TEMPORARY BATCH PLANT",
                "AMRIZE SOUTH CENTRAL INC.",
                "173154L003",
            ),
            None,
        )["permit"]["operating_hours"]["evidence"]
        == []
    )

    plano = recorded["131651"]
    assert plano["classification"] is None
    assert plano["hours_per_year"] == []
    assert plano["evidence"] == []

    listing = parse_listing((fixtures / "tceq-nsr-pending-excerpt.html").read_bytes(), TODAY)
    assert len(listing) == 23
    assert [
        _record(row, None)["permit"]["operating_hours"]["classification"] for row in listing
    ] == [None] * 23

    facilities = [
        cell.get_text(" ", strip=True)
        for cell in BeautifulSoup(
            (fixtures / "tceq-pending-summaries-excerpt.html").read_text(), "html.parser"
        ).find_all("td")
        if "23.7955%" in (cell.get("style") or "")
    ]
    assert len(facilities) == 18
    facility_classes = [classify_operating_hours(name)["classification"] for name in facilities]
    assert facility_classes.count("bridge_temporary") == 0
    assert facility_classes.count(None) == 18
    assert "PORTABLE CRUSHER 2" in facilities

    updated, egu_rows = parse_results(
        (fixtures / "tceq-egu-search-excerpt.html").read_bytes(),
        unit_id="8340",
        unit_name="ELECTRIC GENERATING FACILITIES",
    )
    assert updated == "2026-10-22"
    assert len(egu_rows) == 3
    assert [
        egu_record(row, updated)["permit"]["operating_hours"]["classification"] for row in egu_rows
    ] == [None] * 3
    assert {hours["classification"] for hours in recorded.values()} == {None}
