import hashlib
import time
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_well_lifecycle import (
    WellIdentity,
    parse_completion_packet,
    parse_w1_detail,
    retrieve_w1_detail,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "rrc_w1"


def _w1_page(
    *,
    api="31747395",
    permit="918069",
    operator="665748",
    operator_name="PIONEER NATURAL RES. USA, INC.",
    lease="GLASSCOCK-DICKENSON 44C",
    well="3H",
    county_code="317",
    county="MARTIN",
    spud="",
    completion="",
):
    fields = {
        "statusNoHndlr": permit,
        "apiNoHndlr": api,
        "operatorNoHndlr": operator,
        "operatorNameHndlr": operator_name,
        "leaseNameHndlr": lease,
        "wellNoHndlr": well,
        "countyCodeHndlr": county_code,
        "countyNameHndlr": county,
        "spudDtHndlr": spud,
        "completionDtHndlr": completion,
    }
    inputs = "".join(
        f'<input name="detailRecord.{key}.inputValue" value="{value}">'
        for key, value in fields.items()
    )
    return f"<title>Drilling Permit (W-1) Query</title>{inputs}".encode()


_EXPECTED = WellIdentity(
    api_number="31747395",
    permit_number="0918069",
    operator_number="665748",
    lease="GLASSCOCK-DICKENSON 44C",
    well_number="3H",
    county_code="317",
    county="Martin",
    operator_name="PIONEER NATURAL RES. USA, INC.",
)


def test_official_w1_empty_dates_remain_unknown_after_full_identity_match():
    result = parse_w1_detail(_w1_page(), _EXPECTED)
    assert result["source"] == "texas-rrc-w1-detail"
    assert result["identity"]["api"] == "31747395"
    assert result["asset_identity"]["value"] == "4231747395"
    assert result["identity"]["county"] == "MARTIN"
    assert result["spud_date"] is None
    assert result["rrc_w1_completion_date"] is None
    assert result["events"] == []


def test_official_w1_typed_dates_emit_only_their_named_lifecycle_events():
    result = parse_w1_detail(_w1_page(spud="09/25/2026", completion="10/03/2026"), _EXPECTED)
    assert result["spud_date"] == "2026-09-25"
    assert result["rrc_w1_completion_date"] == "2026-10-03"
    assert result["events"] == [
        {
            "kind": "spud",
            "label": "Drilling started",
            "date": "2026-09-25",
            "source": "texas-rrc-w1-detail",
            "evidence_refs": [],
        },
        {
            "kind": "rrc_w1_completion_date",
            "label": "RRC W-1 completion date",
            "date": "2026-10-03",
            "source": "texas-rrc-w1-detail",
            "evidence_refs": [],
        },
    ]


def test_two_captured_permits_for_one_oxy_well_keep_both_permit_ids_and_one_api_identity():
    identities = []
    for permit in ("0918877", "0918878"):
        body = (_FIXTURES / f"oxy-{permit[-6:]}-detail.html").read_bytes()
        result = parse_w1_detail(
            body,
            WellIdentity(
                api_number=None,
                permit_number=permit,
                operator_number="630555",
                lease="WEST SEMINOLE SA UNIT",
                well_number="604 R",
                county_code="165",
                county="GAINES",
                operator_name="OXY USA WTP LP",
            ),
        )
        identities.append(result["asset_identity"]["value"])
        assert result["identity"]["permit_number"] == permit
        assert result["spud_date"] is None
        assert result["rrc_w1_completion_date"] is None
    assert identities == ["4216538299", "4216538299"]


@pytest.mark.parametrize(
    "changes",
    [
        {"api": "31747396"},
        {"permit": "918070"},
        {"operator": "665749"},
        {"lease": "OTHER LEASE"},
        {"well": "4H"},
        {"county_code": "329"},
        {"county": "HOWARD"},
    ],
)
def test_w1_records_with_any_conflicting_identity_field_are_rejected(changes):
    with pytest.raises(SourceParseError, match="identity"):
        parse_w1_detail(_w1_page(**changes), _EXPECTED)


def test_approved_or_effective_dates_are_never_promoted_to_spud():
    page = (
        _w1_page()
        .decode()
        .replace(
            "</title>",
            '<input name="detailRecord.approvedDtHndlr.inputValue" value="09/24/2026"></title>',
        )
    )
    result = parse_w1_detail(page.encode(), _EXPECTED)
    assert result["spud_date"] is None
    assert result["events"] == []


def _completion_packet(
    *,
    api="165-38299",
    operator="OXY USA WTP LP (630555)",
    lease="WEST SEMINOLE SA UNIT",
    well="604R",
    county="GAINES",
    permit="804127",
):
    return f"""<title>Oil &amp; Gas Data Query</title>
    <th>Packet Summary Data</th>
    <td>Tracking No.: <strong>273201</strong></td>
    <td>Status: <strong>Approved (10/31/2022)</strong></td>
    <td>Operator Name: <strong>{operator}</strong></td>
    <td>Type Of Completion: <strong>Other/Recompletion</strong></td>
    <td>Completion or Recompletion Date: <strong>06/02/2016</strong></td>
    <td>Lease Name: <strong>{lease}</strong></td>
    <td>County: <strong>{county}</strong></td>
    <td>Well No.: <strong>{well}</strong></td>
    <td>API No.: <strong>{api}</strong></td>
    <td>Drilling Permit No: <strong>{permit}</strong></td>""".encode()


def test_completion_packet_joins_full_well_identity_and_preserves_historical_recompletion():
    expected = WellIdentity(
        api_number="16538299",
        permit_number="0918877",
        operator_number="630555",
        lease="WEST SEMINOLE SA UNIT",
        well_number="604R",
        county_code="329",
        county="GAINES",
    )
    result = parse_completion_packet(_completion_packet(), expected, evidence_ref="w2-evidence")
    assert result["asset_identity"]["value"] == "4216538299"
    assert result["related_drilling_permit"] == "804127"
    assert result["completion_date"] == "2016-06-02"
    assert result["events"] == [
        {
            "kind": "historical_recompletion",
            "label": "Recompletion reported (historical)",
            "date": "2016-06-02",
            "source": "texas-rrc-completion-packet",
            "evidence_refs": ["w2-evidence"],
        }
    ]


def test_completion_packet_rejects_api_or_other_identity_conflicts():
    expected = WellIdentity(
        api_number="16538299",
        permit_number="0918877",
        operator_number="630555",
        lease="WEST SEMINOLE SA UNIT",
        well_number="604R",
        county_code="329",
        county="GAINES",
    )
    with pytest.raises(SourceParseError, match="identity"):
        parse_completion_packet(_completion_packet(api="165-38300"), expected)


def test_completion_packet_citation_strips_session_and_action_tokens():
    expected = WellIdentity(
        api_number="16538299",
        permit_number="0918877",
        operator_number="630555",
        lease="WEST SEMINOLE SA UNIT",
        well_number="604R",
        county_code="329",
        county="GAINES",
    )
    result = parse_completion_packet(
        _completion_packet(),
        expected,
        source_url=(
            "https://webapps.rrc.texas.gov/CMPL/packet;jsessionid=SECRET"
            "?methodToCall=displayBySummaryId&packetSummaryId=273201&rrcActionMan=SECRET"
        ),
    )
    assert "sessionid" not in result["source_url"].casefold()
    assert "rrcactionman" not in result["source_url"].casefold()
    assert "methodToCall=displayBySummaryId" in result["source_url"]
    assert "packetSummaryId=273201" in result["source_url"]


def _permit_record():
    return {
        "source_hash": "c" * 64,
        "permit": {
            "permit_number": "0918069",
            "operator": "PIONEER NATURAL RES. USA, INC.",
            "operator_number": "665748",
            "lease": "GLASSCOCK-DICKENSON 44C",
            "well": "3H",
            "county_code": "317",
        },
    }


def test_w1_retrieval_traverses_sanitized_actual_official_search_and_detail_pages():
    pages = [
        (_FIXTURES / "search-form.html").read_bytes(),
        (_FIXTURES / "search-result.html").read_bytes(),
        (_FIXTURES / "detail.html").read_bytes(),
    ]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=pages.pop(0), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        result = retrieve_w1_detail(_permit_record(), deadline=time.monotonic() + 20, client=client)
    assert len(requests) == 3
    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    assert all(request.url.host == "webapps2.rrc.texas.gov" for request in requests)
    assert result["identity_validated"] is True
    assert result["identity"]["permit_number"] == "0918069"
    assert result["asset_identity"]["value"] == "4231747395"
    assert result["spud_date"] is None
    assert result["rrc_w1_completion_date"] is None
    assert result["native_content_hash"] == "c" * 64
    source_url = result["source_url"]
    assert "sessionid" not in source_url.casefold()
    assert "rrcactionman" not in source_url.casefold()
    assert "methodToCall=searchByUniversalDocNo" in source_url
    assert "universalDocNo=499388208" in source_url
    assert (
        result["content_hash"]
        == hashlib.sha256((_FIXTURES / "detail.html").read_bytes()).hexdigest()
    )


def test_w1_retrieval_does_not_select_when_query_has_no_exact_detail_row():
    pages = [
        (_FIXTURES / "search-form.html").read_bytes(),
        b"<html><body>No results found</body></html>",
    ]

    def handler(request):
        return httpx.Response(200, content=pages.pop(0), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(SourceParseError, match="result grid"):
            retrieve_w1_detail(_permit_record(), deadline=time.monotonic() + 20, client=client)


def test_w1_retrieval_rejects_multiple_exact_rows_from_captured_official_query():
    search_result = (_FIXTURES / "search-result.html").read_bytes()
    soup = BeautifulSoup(search_result, "html.parser")
    table = soup.find("table", class_="DataGrid")
    assert table is not None
    row = next(
        (
            candidate
            for candidate in table.find_all("tr")
            if candidate.find("a", href=lambda href: bool(href and "universalDocNo=" in href))
        ),
        None,
    )
    assert row is not None
    table.append(row.__copy__())
    pages = [(_FIXTURES / "search-form.html").read_bytes(), str(soup).encode()]

    def handler(request):
        return httpx.Response(200, content=pages.pop(0), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(SourceParseError, match="conflicting exact well rows"):
            retrieve_w1_detail(_permit_record(), deadline=time.monotonic() + 20, client=client)
