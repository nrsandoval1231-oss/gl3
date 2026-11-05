"""Regression tests for the workstream 4a review: PUCT evidence identity, requests, cost, links."""

from __future__ import annotations

import pytest
from _early_signal_fixtures import APPLICATION_PAGES, CASE_58015, ORDER_PAGES
from test_early_signal_puct import (
    CONFIG,
    NOW,
    TODAY,
    listing,
    origin_with,
    stage,
    states_of,
)

import gridlens.ingestion.adapters.early_signal_link as lk
import gridlens.ingestion.adapters.puct_ccn_dockets as pc
import gridlens.ingestion.adapters.puct_ccn_extract as px


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")


def evidence_everywhere(fields):
    for value in fields.values():
        for e in value if isinstance(value, list) else [value]:
            if e.get("basis") != "unknown":
                yield e


# --------------------------------------------------------------------------- blocker 3


def test_filing_values_carry_page_quote_and_their_own_document_identity():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records)
    state = states_of(records)["58015"]
    docs = {d["role"]: d for d in state["document"]["extraction"]["documents"]}
    fields = state["document"]["extraction"]["fields"]
    request = fields["customer_request_mw"]
    assert request["role"] == "order" and request["document_sha256"] == docs["order"]["sha256"]
    assert request["url"] == docs["order"]["url"] and request["page"] == 1 and request["quote"]
    assert request["item"] == docs["order"]["item"]
    for e in evidence_everywhere(fields):
        assert e["quote"] and "basis" in e
        if e.get("location") == "PUCT docket case style":
            assert e["document_sha256"] is None and e["page"] is None
        else:
            assert e["document_sha256"] and e["page"] and e["url"] and e["role"]
        # No value is identified by the combined docket hash.
        assert e.get("document_sha256") != state["document"]["sha256"]


def test_case_style_values_carry_the_record_hash_and_the_filings_url():
    origin = origin_with()
    record = next(r for r in listing(origin) if r["state_key"] == "58015")
    for e in evidence_everywhere(record["case_style_fields"]):
        assert e["location"] == "PUCT docket case style"
        assert e["document_sha256"] is None
        assert e["record_source_hash"] == record["source_hash"]
        assert e["url"] == pc.filings_url("58015")


def test_link_sides_use_per_evidence_identity_never_the_combined_hash():
    origin = origin_with()
    records = listing(origin)
    docket_text = px.case_style_fields(CASE_58015, "a" * 64, pc.filings_url("58015"))
    summary = {
        "control": "58015",
        "url": pc.filings_url("58015"),
        "fields": px.merge_fields(docket_text, {}),
    }
    peer = {
        "project_id": "25RPG099",
        "utility": "AEP",
        "counties": [
            {
                "value": "Webb",
                "basis": "documented",
                "page": 2,
                "quote": "q",
                "document_sha256": "c" * 64,
                "url": "u",
            }
        ],
        "substations": [
            {
                "value": "Mangana Hein",
                "basis": "documented",
                "page": 2,
                "quote": "q",
                "document_sha256": "c" * 64,
                "url": "u",
            }
        ],
    }
    # The case style names no "new" substation here; add the one a filing stated, with its PDF hash.
    summary["fields"]["substations"] = [
        {
            "value": "Mangana Hein",
            "basis": "documented",
            "page": 7,
            "quote": "the new Mangana Hein substation",
            "document_sha256": "d" * 64,
            "role": "application",
            "item": "1",
            "url": "https://interchange.puc.texas.gov/Documents/58015_1_1.PDF",
        }
    ]
    decision = lk.link_docket(summary, [peer])
    assert decision["status"] == "linked"
    key = decision["keys"][0]
    assert key["docket"]["substation"]["document_sha256"] == "d" * 64
    assert key["docket"]["substation"]["page"] == 7
    assert key["docket"]["county"]["document_sha256"] is None
    assert key["docket"]["county"]["record_source_hash"] == "a" * 64
    assert key["docket"]["county"]["url"] == pc.filings_url("58015")
    assert key["project"]["substation"]["document_sha256"] == "c" * 64
    assert records  # listing fixture is well-formed


def test_state_size_is_bytes_not_a_page_count():
    origin = origin_with()
    records = listing(origin)
    stage(origin, records)
    state = states_of(records)["58015"]
    sizes = [d["bytes"] for d in state["document"]["extraction"]["documents"]]
    assert state["document"]["size"] == sum(sizes) and all(s > 100 for s in sizes)


# --------------------------------------------------------------------------- S4, S5


@pytest.mark.parametrize(
    "text",
    [
        "A solar developer submitted a request for 250 MW of generation interconnection "
        "at the new station.",
        "The Company has requested approval of 345 kV and the entity request for 150 MW "
        "of transfer capability.",
        "A customer has submitted a request for 300 MW of wind generation interconnection.",
        "A customer submitted a request for 80 MW of battery storage injection.",
        "The facility requested 40 MW of load.",
    ],
)
def test_a_request_must_be_a_customers_load_request(text):
    assert px.text_fields([text]).get("customer_request_mw") is None


def test_two_different_customer_requests_are_unknown_with_both_quotes():
    fields = px.text_fields(
        [
            "A customer has submitted a request for approximately 10 megawatts of load.",
            "Later a customer has requested 25 MW of load capacity.",
        ]
    )
    request = fields["customer_request_mw"]
    assert request["value"] is None and request["reason"] == "conflicting_statements"
    assert len(request["candidates"]) == 2


def test_two_documents_stating_different_requests_merge_to_unknown():
    a = px.text_fields(["A customer has submitted a request for 10 MW of load."])
    b = px.text_fields(["A customer has submitted a request for 20 MW of load."])
    merged = px.merge_fields(a, b)
    assert merged["customer_request_mw"]["value"] is None
    same = px.merge_fields(
        a, px.text_fields(["A customer has submitted a request for 10 MW of load."])
    )
    assert same["customer_request_mw"]["value"] == 10


def test_a_stated_load_overlapping_the_customer_request_is_not_kept_twice():
    fields = px.text_fields(
        [
            "A commercial customer has submitted a request for approximately 10 MW of "
            "load capacity. "
            "The area is expected to add 200 MW of load by 2030."
        ]
    )
    assert fields["customer_request_mw"]["value"] == 10
    assert [m["value"] for m in fields["stated_load_mw"]] == [200]


def test_the_order_fixture_gives_no_other_stated_load():
    fields = px.text_fields(["\n".join(ORDER_PAGES[0])])
    assert fields["customer_request_mw"]["value"] == 10 and fields.get("stated_load_mw", []) == []
    assert APPLICATION_PAGES and TODAY and NOW and CONFIG


# --------------------------------------------------------------------------- S6


def cost(text):
    return px.text_fields([text]).get("cost")


def test_cost_with_a_letter_unit_is_not_read_as_a_bare_number():
    got = cost("The estimated cost of the project is $31.2M for the preferred route.")
    assert got["low_usd"] == 31_200_000 and got["basis"] == "calculated"
    assert cost("The estimated cost is $2.5B in total.")["low_usd"] == 2_500_000_000
    assert cost("The estimated cost is $750K.")["low_usd"] == 750_000
    assert cost("The estimated cost is $500 for the route.") is None  # no plausible unit
    assert cost("The estimated cost is $31.2MM for the route.") is None


def test_and_is_not_a_range_separator_and_low_must_not_exceed_high():
    got = cost("The estimated cost is $9.82 million and $1.5 million for the substation.")
    assert got["range"] is False and got["low_usd"] == got["high_usd"] == 9_820_000
    assert cost("The estimated cost ranges from $40 million to $30 million.") is None
    assert cost("The estimated cost is $26.79 million to $31.15 million.")["high_usd"] == 31_150_000


def test_cost_keeps_exact_decimals():
    assert cost("The estimated cost is $9.8217 million.")["low_usd"] == 9_821_700
    assert cost("The estimated cost is $1.00000001 billion.")["low_usd"] == 1_000_000_010
