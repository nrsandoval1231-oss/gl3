"""Actual captured official pages exercise typed, bounded completion research."""

from pathlib import Path
from time import monotonic

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_completion import retrieve_completion_history

FIXTURES = Path(__file__).parents[1] / "fixtures" / "rrc_completion"
IDENTITY = {
    "api": "16538299",
    "permit_number": "0918877",
    "operator_number": "630555",
    "operator": "OXY USA WTP LP",
    "lease": "WEST SEMINOLE SA UNIT",
    "well_number": "604 R",
    "county_code": "165",
    "county": "GAINES",
}


def test_actual_official_history_preserves_initial_completion_and_later_recompletion():
    requests = []

    def transport(request):
        requests.append(request)
        packet = request.url.params.get("packetSummaryId")
        path = {
            None: "listing.html",
            "138740": "new-well-138740.html",
            "273201": "recompletion-273201.html",
        }[packet]
        return httpx.Response(200, content=(FIXTURES / path).read_bytes())

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = retrieve_completion_history(IDENTITY, deadline=monotonic() + 10, client=client)
    assert len(requests) == 3
    assert result["status"] == "bounded_packets_checked"
    events = [record["events"][0] for record in result["records"]]
    assert [(event["kind"], event["date"]) for event in events] == [
        ("historical_completion", "2015-04-19"),
        ("historical_recompletion", "2016-06-02"),
    ]
    assert all(event["date"] < "2026-01-01" for event in events)
    assert all(
        "rrcActionMan" not in record["source_url"] and "jsessionid" not in record["source_url"]
        for record in result["records"]
    )


def test_actual_empty_result_is_absence_of_source_packets_not_a_completion_assertion():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, content=(FIXTURES / "no-packets.html").read_bytes())
        )
    ) as client:
        result = retrieve_completion_history(
            {**IDENTITY, "api": "31747395"}, deadline=monotonic() + 10, client=client
        )
    assert result["status"] == "no_packets_returned"
    assert result["records"] == []


def test_packet_bound_does_not_fetch_or_admit_an_arbitrary_partial_history():
    listing = (
        (FIXTURES / "listing.html").read_bytes()
        + b'<a href="ewaSearchAction.do?methodToCall=displayBySummaryId'
        b'&packetSummaryId=999999">999999</a>'
    )
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, content=listing)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = retrieve_completion_history(IDENTITY, deadline=monotonic() + 10, client=client)
    assert len(requests) == 1
    assert result["status"] == "packet_limit_reached" and result["records"] == []


@pytest.mark.parametrize("alteration", ["wrong_api", "unapproved"])
def test_conflicting_or_unapproved_packet_does_not_become_supported_history(alteration):
    def transport(request):
        if not request.url.params.get("packetSummaryId"):
            return httpx.Response(200, content=(FIXTURES / "listing.html").read_bytes())
        body = (FIXTURES / "new-well-138740.html").read_bytes()
        if alteration == "wrong_api":
            body = body.replace(b"165-38299", b"165-38300")
        else:
            body = body.replace(b"Approved (07/29/2015)", b"Submitted (07/29/2015)")
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(SourceParseError):
            retrieve_completion_history(IDENTITY, deadline=monotonic() + 10, client=client)
