"""PUCT CCN dockets: listing, filtering, URL policy, document stage, extraction, change detection.

No network: HTTP is an httpx.MockTransport with DNS pinned to a public address. Fixtures are short
excerpts of the public dockets 58015 and 59549 read live on 2026-11-04.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from _early_signal_fixtures import (
    APPLICATION_PAGES,
    CASE_58015,
    CASE_59549,
    CASE_GEN,
    ORDER_PAGES,
    Origin,
    documents_html,
    export_xlsx,
    filings_html,
    pdf,
    search_html,
)

import gridlens.ingestion.adapters.puct_ccn_dockets as pc
import gridlens.ingestion.adapters.puct_ccn_extract as px
from gridlens.ingestion.adapters.early_signal_stage import StageConfig
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry

TODAY = date(2026, 11, 4)
START = date(2026, 9, 5)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONFIG = StageConfig(max_downloads=4, max_checks=20, extract_seconds=120.0, isolate=False)

ROWS_LINE = [
    ("59549", "2", "CITY PUBLIC SERVICE BOARD (CPS ENERGY)", CASE_59549),
    ("58015", "9", "AEP TEXAS INC.", CASE_58015),
    ("60001", "3", "EL PASO ELECTRIC COMPANY", CASE_GEN),
]
ROWS_SUB = [("58015", "9", "AEP TEXAS INC.", CASE_58015)]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def source(**documents):
    definition = next(r for r in load_registry() if r["id"] == pc.SOURCE_ID)
    definition = {**definition, "query": {**definition["query"]}}
    definition["query"]["documents"] = {**definition["query"]["documents"], **documents}
    return definition


def origin_with(rows_line=ROWS_LINE, rows_sub=ROWS_SUB) -> Origin:
    o = Origin()
    for description, rows in (("transmission line", rows_line), ("substation", rows_sub)):
        o.put(pc.search_url(description, START, TODAY), search_html(rows))
        o.put(pc.export_url(description, START, TODAY), export_xlsx(rows))
    o.put(
        pc.filings_url("59549"),
        filings_html(
            "59549",
            [
                (
                    "1",
                    "3/23/2026",
                    "City Public Service Board",
                    "LTRS",
                    "Letter Requesting Docket Number",
                ),
                (
                    "2",
                    "4/6/2026",
                    "CITY PUBLIC SERVICE BOARD",
                    "PL",
                    "APPLICATION OF CITY PUBLIC SERVICE BOARD TO AMEND ITS CCN",
                ),
            ],
        ),
    )
    o.put(
        pc.doc_page_url("59549", "2"),
        documents_html("59549", "2", [("1616581", "ZIP"), ("1616582", "PDF"), ("1616583", "PDF")]),
    )
    o.put("https://interchange.puc.texas.gov/Documents/59549_2_1616582.PDF", pdf(APPLICATION_PAGES))
    o.put(
        pc.filings_url("58015"),
        filings_html(
            "58015",
            [
                (
                    "1",
                    "5/21/2025",
                    "AEP TEXAS INC.",
                    "PL",
                    "APPLICATION OF AEP TEXAS INC. TO AMEND ITS CCN",
                ),
                (
                    "9",
                    "6/20/2025",
                    "COMMISSION STAFF",
                    "ORD",
                    "ORDER OF REFERRAL AND PRELIMINARY ORDER",
                ),
            ],
        ),
    )
    o.put(pc.doc_page_url("58015", "1"), documents_html("58015", "1", [("1500001", "PDF")]))
    o.put(pc.doc_page_url("58015", "9"), documents_html("58015", "9", [("1502790", "PDF")]))
    o.put(
        "https://interchange.puc.texas.gov/Documents/58015_1_1500001.PDF",
        pdf([["The applicant proposes a single routing option."]]),
    )
    o.put("https://interchange.puc.texas.gov/Documents/58015_9_1502790.PDF", pdf(ORDER_PAGES))
    return o


def listing(origin):
    return pc.retrieve(source(), origin.client(), pacer=lambda: None, today=TODAY)


def stage(origin, records, *, prior=None, index=None, peers=None, now=NOW, config=CONFIG):
    return pc.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        index=index,
        peers=peers,
        pacer=lambda: None,
        now=lambda: now,
    )


def states_of(records):
    return {
        r["state_key"]: r["early_signal"]
        for r in records
        if r.get("state_key") and "early_signal" in r
    }


# --------------------------------------------------------------------------- registry / policy


def test_ships_off_and_validates():
    definition = source()
    assert definition["enabled"] is False and definition["query"]["documents"]["enabled"] is False
    assert pc.config_from_source(definition) is None
    assert pc.valid_query(definition["query"])
    assert not pc.valid_query({**definition["query"], "window_days": 400})
    assert not pc.valid_query({**definition["query"], "descriptions": ["large load"]})
    seeds = {**definition["query"]["documents"], "seed_urls": ["https://evil.example/x.pdf"]}
    assert not pc.valid_query({**definition["query"], "documents": seeds})


@pytest.mark.parametrize(
    "url",
    [
        pc.search_url("transmission line", START, TODAY),
        pc.export_url("substation", START, TODAY),
        pc.filings_url("59549"),
        pc.doc_page_url("59549", "2"),
        "https://interchange.puc.texas.gov/Documents/59549_2_1616582.PDF",
    ],
)
def test_url_policy_accepts(url):
    assert pc.url_ok(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://interchange.puc.texas.gov/Search/Filings?ControlNumber=59549",
        "https://interchange.puc.texas.gov.evil.example/Search/Filings?ControlNumber=59549",
        "https://evil.example/Search/Filings?ControlNumber=59549",
        "https://interchange.puc.texas.gov/Search/Filings?ControlNumber=59549&x=1",
        "https://interchange.puc.texas.gov/Search/Filings?ControlNumber=abc",
        "https://interchange.puc.texas.gov/Documents/59549_2_1616582.ZIP",
        "https://interchange.puc.texas.gov/Documents/../etc/passwd",
        "https://interchange.puc.texas.gov/search/dockets/?UtilityType=A&ItemMatch=Equal",
        "https://interchange.puc.texas.gov/search/dockets/?Description=large%20load",
        "https://interchange.puc.texas.gov:444/Search/Filings?ControlNumber=59549",
        "https://u@interchange.puc.texas.gov/Search/Filings?ControlNumber=59549",
    ],
)
def test_url_policy_rejects(url):
    assert not pc.url_ok(url)


# --------------------------------------------------------------------------- listing


def test_listing_filters_to_certificate_styles_naming_a_line_or_substation():
    origin = origin_with()
    records = listing(origin)
    assert {r["state_key"] for r in records} == {"59549", "58015"}  # the generation CCN is out
    assert len(origin.log) == 4  # two searches, two exports; nothing else
    rec = next(r for r in records if r["state_key"] == "59549")
    fields = rec["case_style_fields"]
    assert [c["value"] for c in fields["counties"]] == ["Medina"]
    assert [v["value"] for v in fields["voltage_kv"]] == [138]
    assert rec["document_number"] == "PUCT-CCN-59549" and rec["publication_date"] is None
    assert "unknown until then" in rec["abstract"]


def test_listing_cross_checks_search_against_export():
    origin = origin_with()
    origin.put(pc.export_url("transmission line", START, TODAY), export_xlsx(ROWS_LINE[:1]))
    with pytest.raises(SourceParseError, match="disagree"):
        listing(origin)


def test_listing_429_is_typed_with_retry_after():
    from httpx import Response

    origin = origin_with()
    origin.force = lambda url: Response(429, headers={"retry-after": "300"})
    with pytest.raises(SourceParseError) as caught:
        listing(origin)
    assert caught.value.acquisition_code == "http_status_429"
    assert caught.value.acquisition_retry_after_seconds == 300


def test_listing_bot_challenge_page_is_a_typed_failure_not_bypassed():
    origin = origin_with()
    origin.put(
        pc.search_url("transmission line", START, TODAY),
        b"<html>Just a moment...</html>",
        status=403,
    )
    n = None
    with pytest.raises(SourceParseError):
        listing(origin)
    n = len(origin.log)
    assert n == 1  # one request, then stop; no retry around the refusal


def test_multi_county_and_plural_style():
    fields = px.case_style_fields(
        "APPLICATION OF ONCOR TO AMEND ITS CERTIFICATE OF CONVENIENCE AND NECESSITY FOR THE "
        "LONGSHORE SWITCH-DRILL HOLE SWITCH 765 KV TRANSMISSION LINE PROJECT IN ANDREWS, "
        "CULBERSON, ECTOR AND HOWARD COUNTIES"
    )
    assert [c["value"] for c in fields["counties"]] == ["Andrews", "Culberson", "Ector", "Howard"]
    assert [v["value"] for v in fields["voltage_kv"]] == [765]
    assert px.style_is_relevant(
        "JOINT APPLICATION TO AMEND THEIR CERTIFICATES OF CONVENIENCE AND NECESSITY "
        "FOR A SUBSTATION"
    )
    assert not px.style_is_relevant(CASE_GEN)


# --------------------------------------------------------------------------- extraction


def test_voltage_is_only_the_projects_own_line_and_a_cost_range_keeps_both_ends():
    page = (
        "The Proposed Project is a new double circuit 138 kilovolt (kV) transmission line. It taps "
        "the existing 345 kV line and a 230kV or less rule applies. The total estimated cost for "
        "the Proposed Project ranges between a low of $26.79 million to a high of $31.15 million."
    )
    fields = px.text_fields([page])
    assert [v["value"] for v in fields["voltage_kv"]] == [138]
    cost = fields["cost"]
    assert (cost["low_usd"], cost["high_usd"], cost["range"]) == (26_790_000, 31_150_000, True)
    assert cost["basis"] == "calculated"


def test_customer_request_quote_and_cost_from_the_preliminary_order():
    origin = origin_with()
    records = listing(origin)
    report = stage(origin, records)
    assert report.rejections == []
    state = states_of(records)["58015"]
    fields = state["document"]["extraction"]["fields"]
    request = fields["customer_request_mw"]
    assert request["value"] == 10 and request["basis"] == "documented"
    assert "has submitted a request for approximately 10 megawatts" in request["quote"]
    assert request["page"] == 1
    assert fields["cost"]["low_usd"] == 9_820_000 and fields["cost"]["range"] is False
    assert fields["substations"] == []  # none is stated as new in the excerpt: unknown, not guessed
    documents = {d["role"]: d for d in state["document"]["extraction"]["documents"]}
    assert set(documents) == {"application", "order"} and len(documents["order"]["sha256"]) == 64
    assert state["published_at"] == "2025-05-21"  # first filing date
    record = next(r for r in records if r["state_key"] == "58015")
    assert record["publication_date"] == "2025-05-21"
    assert "Customer-requested load: 10 MW (documented)" in record["abstract"]


def test_cost_range_voltage_and_stated_load_from_the_application():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records)
    fields = states_of(records)["59549"]["document"]["extraction"]["fields"]
    cost = fields["cost"]
    assert (cost["low_usd"], cost["high_usd"], cost["range"]) == (26_790_000, 31_150_000, True)
    assert [s["value"] for s in fields["substations"]] == ["Legend Falls"]
    # Not a customer request: the applicant's statement about a different project, kept apart.
    assert fields["customer_request_mw"]["basis"] == "unknown"
    assert [m["value"] for m in fields["stated_load_mw"]] == [129]
    assert 138 in [v["value"] for v in fields["voltage_kv"]]


def test_customer_request_requires_the_sentence_shape():
    only_load = [
        "The area is expected to add 200 MW of load by 2030 and the utility requested 5 MW."
    ]
    assert px.text_fields(only_load).get("customer_request_mw") is None
    gw = px.text_fields(
        ["A large customer has submitted a request for approximately 1.2 GW of service."]
    )
    assert (
        gw["customer_request_mw"]["value"] == 1200
        and gw["customer_request_mw"]["basis"] == "calculated"
    )


def test_unknown_is_not_zero_for_a_docket_with_no_stated_figures():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records)
    fields = states_of(records)["58015"]["document"]["extraction"]["fields"]
    app_only = px.merge_fields(
        {}, px.text_fields(["The applicant proposes a single routing option."])
    )
    assert app_only["cost"] == {"value": None, "basis": "unknown", "reason": "not_stated"}
    assert app_only["customer_request_mw"]["value"] is None
    assert fields["stated_load_mw"][0]["value"] == 10


# --------------------------------------------------------------------------- stage behaviour


def test_documents_are_read_only_within_the_download_budget():
    origin = origin_with()
    records = listing(origin)
    report = stage(origin, records, config=StageConfig(1, 20, 120.0, (), False))
    assert report.counts.get("deferred_download_budget") == 1
    assert len(states_of(records)) == 1


def test_changed_docket_listing_without_new_documents_makes_no_requests():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records)
    prior = states_of(records)
    again = origin_with()
    records2 = listing(again)
    again.log.clear()
    report = stage(again, records2, prior=prior, index={"urls": {}})
    assert again.log == [] and report.counts.get("checked", 0) == 0
    one = {
        r["document_number"]: (r["source_hash"], r["abstract"])
        for r in records
        if r.get("state_key")
    }
    two = {
        r["document_number"]: (r["source_hash"], r["abstract"])
        for r in records2
        if r.get("state_key")
    }
    assert one == two


def test_new_order_filing_triggers_one_reread_and_keeps_first_seen():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records, config=CONFIG)
    prior = states_of(records)
    # Remove the order from the first read to emulate a docket that only had its application.
    first = prior["58015"]
    first["document"]["extraction"]["documents"] = [
        d for d in first["document"]["extraction"]["documents"] if d["role"] == "application"
    ]
    first["filings_listed"] = "1"
    later = NOW + timedelta(days=10)
    rows = [("58015", "9", "AEP TEXAS INC.", CASE_58015)]
    again = origin_with(rows, rows)
    records2 = listing(again)
    stage(
        again,
        records2,
        prior=prior,
        index={"urls": {"58015": {"status": "document", "at": NOW.isoformat()}}},
        now=later,
    )
    new = states_of(records2)["58015"]
    assert {d["role"] for d in new["document"]["extraction"]["documents"]} == {
        "application",
        "order",
    }
    assert new["first_seen_at"] == first["first_seen_at"]
    assert new["document"]["extraction"]["fields"]["customer_request_mw"]["value"] == 10


def test_429_while_reading_stops_and_sets_not_before():
    from httpx import Response

    origin = origin_with()
    origin.force = (
        lambda url: Response(429, headers={"retry-after": "900"})
        if "/Search/Filings" in url
        else None
    )
    records = listing(origin)
    origin.log.clear()
    report = stage(origin, records)
    assert report.counts["aborted_rate_limited"] == 1
    assert report.index["not_before"] == (NOW + timedelta(seconds=900)).isoformat()
    assert len(origin.log) == 1  # stopped at the first refusal
    n = len(origin.log)
    again = stage(
        origin, listing(origin_with()), index=report.index, now=NOW + timedelta(seconds=60)
    )
    assert again.counts.get("skipped_retry_after") == 1 and len(origin.log) == n


def test_a_failed_pdf_is_a_typed_failure_with_retry_bookkeeping():
    origin = origin_with()
    origin.put(
        "https://interchange.puc.texas.gov/Documents/59549_2_1616582.PDF",
        b"<html>app</html>",
        ctype="text/html",
    )
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_js_shell") == 1
    assert "59549" not in states_of(records)
    base = next(r for r in records if r["state_key"] == "59549")
    assert "early_signal" not in base and "Case style:" in base["abstract"]  # case-style facts kept


def test_one_request_per_second():
    from gridlens.ingestion.adapters.tceq_application_documents import Pacer

    origin = origin_with()
    now = {"t": 1000.0}
    sleeps: list[float] = []
    pacer = Pacer(
        clock=lambda: now["t"],
        sleep=lambda s: (sleeps.append(s), now.__setitem__("t", now["t"] + s)),
    )
    pc.retrieve(source(), origin.client(), pacer=pacer, today=TODAY)
    assert len(sleeps) == 4 and all(abs(s - 1.0) < 1e-6 for s in sleeps)
