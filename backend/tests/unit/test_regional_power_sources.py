from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.domain.signal_admission import admit_standalone
from gridlens.ingestion.adapters.cabq_building_permits import (
    CSV_URL,
    parse_permits,
)
from gridlens.ingestion.adapters.cabq_building_permits import (
    retrieve as retrieve_cabq,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ok_deq_public_review import (
    LISTING_URL,
    parse_listing,
)
from gridlens.ingestion.adapters.ok_deq_public_review import (
    retrieve as retrieve_deq,
)
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response
from gridlens.ingestion.adapters.spp_interconnection import (
    QUEUE_URL,
    parse_queue,
)
from gridlens.ingestion.adapters.spp_interconnection import (
    retrieve as retrieve_spp,
)
from gridlens.ingestion.registry import load_registry

FIXTURES = Path(__file__).parents[1] / "fixtures"
TODAY = date(2026, 10, 23)


def _source(source_id: str) -> dict:
    return next(row for row in load_registry() if row["id"] == source_id)


def test_power_signal_tags_require_explicit_language():
    assert power_signal_tags("5 turbines, onsite use only for data centers") == ["btm"]
    assert power_signal_tags("bridge power until the substation is ready") == ["bridge"]
    assert power_signal_tags("trailer-mounted temporary power") == ["temporary"]
    assert power_signal_tags("210 gas engines serving a data center") == []
    assert power_signal_tags("Wheatland Bridge substation") == []


def test_oklahoma_deq_keeps_power_and_data_center_rows_and_skips_unrelated():
    rows = parse_listing((FIXTURES / "ok-deq-public-review-excerpt.html").read_bytes())
    by_permit = {row["permit_no"]: row for row in rows}
    assert set(by_permit) == {"OK1000144", "2025-0595-C M-1", "2026-0001-C"}
    center = by_permit["OK1000144"]
    assert center["location"] == "Atoka County, OK"
    assert center["event_date"] == "2026-04-25"
    assert center["html_url"].endswith("id=1072441")
    assert center["tags"] == []
    assert by_permit["2025-0595-C M-1"]["event_date"] is None
    assert by_permit["2026-0001-C"]["tags"] == ["bridge"]


def test_spp_queue_keeps_ok_nm_thermal_and_drops_wind_and_texas():
    updated, rows = parse_queue((FIXTURES / "spp-active-queue-excerpt.csv").read_bytes())
    assert updated == "10/22/2026"
    by_id = {row["number"]: row for row in rows}
    assert set(by_id) == {"GEN-2024-341", "GEN-2026-PR18", "GEN-2026-BTM"}
    assert by_id["GEN-2024-341"]["location"] == "Kingfisher County, OK"
    assert by_id["GEN-2024-341"]["tags"] == []
    assert by_id["GEN-2026-PR18"]["state"] == "NM"
    assert by_id["GEN-2026-BTM"]["tags"] == ["btm"]
    assert by_id["GEN-2026-BTM"]["data_center"] is True


def test_albuquerque_window_keeps_dated_relevant_permits():
    permits = parse_permits(
        (FIXTURES / "cabq-building-permits-excerpt.csv").read_bytes(), today=TODAY
    )
    by_id = {row["number"]: row for row in permits}
    assert set(by_id) == {"BP-2026-10001", "BP-2026-10002", "BP-2026-10003"}
    assert by_id["BP-2026-10001"]["data_center"] is True
    assert by_id["BP-2026-10001"]["location"] == "4100 Edith Blvd, Albuquerque, NM 87107"
    assert by_id["BP-2026-10002"]["tags"] == []
    assert by_id["BP-2026-10003"]["tags"] == ["temporary"]


def _client(body: bytes, content_type: str, requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler))


def test_adapters_fetch_with_polite_user_agent_and_do_not_mutate_client_headers():
    deq_body = (FIXTURES / "ok-deq-public-review-excerpt.html").read_bytes()
    spp_body = (FIXTURES / "spp-active-queue-excerpt.csv").read_bytes()
    cabq_body = (FIXTURES / "cabq-building-permits-excerpt.csv").read_bytes()
    seen: list[httpx.Request] = []
    deq_client = _client(deq_body, "text/html; charset=utf-8", seen)
    deq_client.headers["Host"] = "preserve.example"
    records = retrieve_deq(_source("oklahoma-deq-public-review"), deq_client)
    assert {row["document_number"] for row in records} == {
        "OKDEQ-OK1000144",
        "OKDEQ-2025-0595-C-M-1",
        "OKDEQ-2026-0001-C",
    }
    assert seen[-1].headers["user-agent"].startswith("GridLens public source reader/")
    assert seen[-1].url == LISTING_URL
    assert deq_client.headers["Host"] == "preserve.example"

    spp_seen: list[httpx.Request] = []
    spp_records = retrieve_spp(
        _source("spp-thermal-interconnection"), _client(spp_body, "text/csv", spp_seen)
    )
    assert len(spp_records) == 3
    assert spp_seen[-1].url == QUEUE_URL

    cabq_seen: list[httpx.Request] = []
    cabq_records = retrieve_cabq(
        _source("albuquerque-building-permits"),
        _client(cabq_body, "text/csv", cabq_seen),
        today=TODAY,
    )
    assert len(cabq_records) == 3
    assert cabq_seen[-1].url == CSV_URL


def test_public_fetch_retries_retryable_status_then_fails_closed_on_redirect_and_type():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, headers={"content-type": "text/html"}, content=b"busy")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")

    client = httpx.Client(follow_redirects=False, transport=httpx.MockTransport(handler))
    slept: list[float] = []
    headers, body = read_public_response(
        client,
        "https://example.test/listing",
        max_bytes=100,
        allowed_media_types={"text/html"},
        attempts=2,
        backoff_seconds=0.2,
        sleep=slept.append,
    )
    assert body == b"<html/>"
    assert headers["content-type"] == "text/html"
    assert slept == [0.2]
    assert client.headers.get("Host") is None

    redirecting = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "https://evil.example/"})
        ),
    )
    with pytest.raises(SourceParseError, match="redirects are not followed"):
        read_public_response(
            redirecting,
            "https://example.test/listing",
            max_bytes=100,
            allowed_media_types={"text/html"},
            attempts=1,
        )

    wrong_type = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"{}"
            )
        ),
    )
    with pytest.raises(SourceParseError, match="unexpected media type"):
        read_public_response(
            wrong_type,
            "https://example.test/listing",
            max_bytes=10,
            allowed_media_types={"text/html"},
            attempts=1,
        )

    oversized = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html", "content-length": "50"},
                content=b"12345",
            )
        ),
    )
    with pytest.raises(SourceParseError, match="byte limit"):
        read_public_response(
            oversized,
            "https://example.test/listing",
            max_bytes=4,
            allowed_media_types={"text/html"},
            attempts=1,
        )


def test_data_center_rows_can_be_signals_and_bare_generation_stays_evidence():
    deq = retrieve_deq(
        _source("oklahoma-deq-public-review"),
        _client(
            (FIXTURES / "ok-deq-public-review-excerpt.html").read_bytes(),
            "text/html",
            [],
        ),
    )
    center = next(row for row in deq if row["document_number"] == "OKDEQ-OK1000144")
    turbines = next(row for row in deq if "2025-0595" in row["document_number"])
    accepted = assess_permit(center, as_of=TODAY)
    undated = assess_permit(turbines, as_of=TODAY)
    assert accepted["decision"] == "accepted"
    assert accepted["location"] == "Atoka County, OK"
    assert accepted["power_signals"] == []
    assert undated["decision"] == "rejected"
    assert "event date" in undated["reason"]

    spp = retrieve_spp(
        _source("spp-thermal-interconnection"),
        _client((FIXTURES / "spp-active-queue-excerpt.csv").read_bytes(), "text/csv", []),
    )
    thermal = next(row for row in spp if row["document_number"] == "SPP-GEN-2024-341")
    btm = next(row for row in spp if row["document_number"] == "SPP-GEN-2026-BTM")
    assert assess_permit(thermal, as_of=TODAY)["decision"] == "rejected"
    btm_assessment = assess_permit(btm, as_of=TODAY)
    assert btm_assessment["decision"] == "accepted"
    assert btm_assessment["power_signals"] == ["btm"]
    admitted = admit_standalone(
        source_id="spp-thermal-interconnection",
        family="interconnection-queue",
        retrieval_method="spp-interconnection-queue",
        accepted=True,
        activity=btm_assessment["power_activity"],
        title=btm["title"],
        abstract=btm["abstract"],
        dated=True,
        citation_url=btm["html_url"],
        identified_project=True,
    )
    assert admitted.admitted is True
    held = admit_standalone(
        source_id="spp-thermal-interconnection",
        family="interconnection-queue",
        retrieval_method="spp-interconnection-queue",
        accepted=True,
        activity="facility-expansion",
        title=thermal["title"],
        abstract=thermal["abstract"],
        dated=True,
        citation_url=thermal["html_url"],
        identified_project=True,
    )
    assert held.admitted is False


def test_malformed_spp_stamp_and_deq_columns_fail_closed():
    with pytest.raises(SourceParseError, match="update stamp"):
        parse_queue(b"not a queue\n")
    with pytest.raises(SourceParseError, match="columns changed"):
        parse_listing(b"<table><tr><td>Nope</td></tr></table>")
