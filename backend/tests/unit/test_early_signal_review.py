"""Regression tests for the workstream 4a review (probes turned into tests).

Each test names the review finding it holds. No network: MockTransport with DNS pinned to a
public address, synthetic PDFs and workbooks.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta

import pytest
from _early_signal_fixtures import (
    HUB,
    MEETING,
    SHEETS,
    STATUS_PDF,
    TPIT_XLSX,
    ercot_origin,
    hub_html,
    listed_file,
    tpit_row,
    workbook,
)
from httpx import Response

import gridlens.ingestion.adapters.early_signal_link as lk
import gridlens.ingestion.adapters.early_signal_stage as st
import gridlens.ingestion.adapters.ercot_rpg as er
import gridlens.ingestion.adapters.ercot_rpg_extract as rx
import gridlens.ingestion.adapters.ercot_tpit as tp
import gridlens.ingestion.adapters.puct_ccn_extract as px
from gridlens.ingestion.adapters.early_signal_stage import StageConfig
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure
from gridlens.ingestion.registry import load_registry

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONFIG = StageConfig(max_downloads=6, max_checks=20, extract_seconds=120.0, isolate=False)
TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")


def listing(origin, today=TODAY):
    definition = next(r for r in load_registry() if r["id"] == er.SOURCE_ID)
    return er.retrieve(definition, origin.client(), pacer=lambda: None, today=today)


def stage(origin, records, *, prior=None, index=None, now=NOW):
    return er.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=CONFIG,
        index=index,
        pacer=lambda: None,
        now=lambda: now,
    )


def pages_of(*pages):
    return list(pages)


# --------------------------------------------------------------------------- blocker 1


def test_a_reference_to_another_project_does_not_take_over_following_bullets():
    pages = pages_of(
        "CPS Energy submitted the Large Load Project (25RPG020) for RPG review\n"
        "· This project supersedes 24RPG010\n"
        "· This is a Tier 1 project with an estimated cost of approximately $333.7 million\n"
        "· with the addition of approximately 2 GW Load"
    )
    projects, loose = rx.extract_projects(pages)
    for project in projects:
        assert project["fields"]["cost"]["value"] is None
        assert project["fields"]["tier"]["value"] is None
    assert not [
        p for p in projects if p["project_id"] == "24RPG010" and p["fields"]["tier"]["value"]
    ]


def test_a_project_defining_statement_still_switches_the_project():
    pages = pages_of(
        "CPS Energy submitted the Large Load Project (25RPG020) for RPG review\n"
        "· This is a Tier 1 project with an estimated cost of $10 million\n"
        "· STEC submitted the Medina Project (25RPG046) for RPG review\n"
        "· This is a Tier 2 project with an estimated cost of $20 million"
    )
    projects, _ = rx.extract_projects(pages)
    by_id = {p["project_id"]: p["fields"] for p in projects}
    assert by_id["25RPG020"]["tier"]["value"] == "Tier 1"
    assert by_id["25RPG046"]["tier"]["value"] == "Tier 2"
    assert by_id["25RPG046"]["cost"]["value"] == 20_000_000


# --------------------------------------------------------------------------- blocker 2


def test_deferred_first_read_is_recovered_by_a_304_capable_origin(monkeypatch):
    origin = ercot_origin()
    records = listing(origin)
    real = st.shared.MIN_EXTRACT_SECONDS
    monkeypatch.setattr(st.shared, "MIN_EXTRACT_SECONDS", 10**9)
    first = stage(origin, records)
    monkeypatch.setattr(st.shared, "MIN_EXTRACT_SECONDS", real)
    assert first.counts.get("deferred_deadline", 0) >= 1
    assert any(e.get("status") == "pending" for e in first.index["urls"].values())
    again = ercot_origin()  # serves ETags and answers 304 to a conditional request
    records2 = listing(again)
    report = stage(again, records2, index=first.index, now=NOW + timedelta(days=1))
    assert "failure_unexpected_not_modified" not in report.counts
    assert any(r.get("state_key") == STATUS_PDF and "early_signal" in r for r in records2)


def test_a_304_with_no_stored_state_is_retried_once_unconditionally():
    origin = ercot_origin()
    calls = {"n": 0}

    def force(url):
        if url == STATUS_PDF:
            calls["n"] += 1
            if calls["n"] == 1:
                return Response(304, headers={"etag": '"x"'})
        return None

    origin.force = force
    records = listing(origin)
    report = stage(origin, records)
    assert calls["n"] == 2
    assert "failure_unexpected_not_modified" not in report.counts
    assert any(r.get("state_key") == STATUS_PDF and "early_signal" in r for r in records)


def test_conditional_headers_are_not_sent_without_a_state():
    origin = ercot_origin()
    seen: list[dict] = []
    real = origin.handler

    def spy(request):
        seen.append(dict(request.headers))
        return real(request)

    import httpx

    client = httpx.Client(transport=httpx.MockTransport(spy), follow_redirects=False)
    records = er.retrieve(
        next(r for r in load_registry() if r["id"] == er.SOURCE_ID),
        client,
        pacer=lambda: None,
        today=TODAY,
    )
    index = {"urls": {STATUS_PDF: {"status": "pending", "validators": {"etag": '"zzz"'}}}}
    seen.clear()
    er.run_stage(
        records, {}, client=client, config=CONFIG, index=index, pacer=lambda: None, now=lambda: NOW
    )
    assert seen and not any("if-none-match" in h or "if-modified-since" in h for h in seen)


# --------------------------------------------------------------------------- S7, S8


def test_study_assumption_load_is_not_a_project_load_in_a_single_project_document():
    pages = pages_of(
        "Oncor submitted the Foo Load Project (26RPG030) for RPG review\n"
        "· This is a Tier 1 project with an estimated cost of $100 million",
        "Study Assumptions\n· The study assumed the addition of approximately 3,000 MW of "
        "new load in the Permian Basin",
    )
    projects, _ = rx.extract_projects(pages)
    assert projects[0]["fields"]["load"]["basis"] == "unknown"


def test_load_needs_the_project_id_on_the_same_page_not_just_a_sole_id():
    pages = pages_of(
        "Oncor submitted the Foo Load Project (26RPG030) for RPG review",
        "· This project is needed with the addition of approximately 500 MW load",
    )
    projects, _ = rx.extract_projects(pages)
    assert projects[0]["fields"]["load"]["basis"] == "unknown"


def test_decimal_mw_and_gw_keep_their_exact_value():
    def load(text):
        projects, _ = rx.extract_projects(
            [
                "Oncor submitted the X Project (26RPG031) for review\n"
                f"· with the addition of approximately {text} load"
            ]
        )
        return projects[0]["fields"]["load"]

    assert load("12.5 MW")["value"] == "12.5" and load("12.5 MW")["basis"] == "documented"
    assert load("1.25 GW")["value"] == 1250 and load("1.25 GW")["basis"] == "calculated"
    assert load("0.0125 GW")["value"] == "12.5"
    assert load("2 GW")["value"] == 2000
    assert (
        px.text_fields(
            ["A new customer has submitted a request for approximately 12.5 MW of service."]
        )["customer_request_mw"]["value"]
        == "12.5"
    )


# --------------------------------------------------------------------------- S9 to S12 (TPIT)


def test_a_missing_lifecycle_sheet_is_a_typed_failure_not_a_wave_of_removals():
    full = tp.tpit_extraction(workbook(SHEETS), None, 60, False, "2026-10-01")
    assert full["families"] == ["Cancelled", "Completed", "Future", "Planned"]
    partial = {k: v for k, v in SHEETS.items() if not k.startswith("Planned")}
    with pytest.raises(DocumentFailure) as caught:
        tp.tpit_extraction(workbook(partial), full, 60, False, "2026-11-01")
    assert caught.value.code == "workbook_columns_changed"


def test_first_seen_survives_a_row_leaving_and_returning():
    a = tp.tpit_extraction(workbook(SHEETS), None, 60, False, "2026-09-01")
    gone = dict(SHEETS)
    gone["FutureTPIT100126NoCost"] = SHEETS["FutureTPIT100126NoCost"][1:]
    b = tp.tpit_extraction(workbook(gone), a, 60, False, "2026-10-01")
    c = tp.tpit_extraction(workbook(SHEETS), b, 60, False, "2026-11-01")
    assert b["removed_rows"]["100305"]["fs"] == "2026-09-01"
    assert c["rows"]["100305"]["fs"] == "2026-09-01"
    assert c["first_seen"]["100305"] == "2026-09-01"


def test_tpit_state_key_is_stable_when_the_monthly_url_is_renamed():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records, index={"urls": {}})
    prior = {
        r["state_key"]: r["early_signal"]
        for r in records
        if r.get("early_signal", {}).get("stateful")
    }
    assert "tpit" in prior and prior["tpit"]["url"] == TPIT_XLSX
    renamed = "https://www.ercot.com/files/docs/2026/11/25/ERCOT-November-TPIT-No-Cost-110126.xlsx"
    second = ercot_origin()
    second.put(
        "https://www.ercot.com/gridinfo/planning",
        (
            "<html><body>"
            + listed_file(
                renamed, "Transmission Project and Information Tracking", "Nov 25, 2026", "xlsx"
            )
            + "</body></html>"
        ).encode(),
    )
    sheets = {k: [dict(r) for r in v] for k, v in SHEETS.items()}
    sheets["FutureTPIT100126NoCost"].append(tpit_row("120000", description="serve a data center"))
    second.put(renamed, workbook(sheets))
    records2 = listing(second)
    tp_record = next(r for r in records2 if r["doc_kind"] == "tpit")
    assert tp_record["state_key"] == "tpit" and tp_record["doc_url"] == renamed
    assert tp_record["document_number"] == "ERCOT-TPIT-SNAPSHOT"
    stage(second, records2, prior=prior, index={"urls": {}}, now=NOW + timedelta(days=30))
    state = tp_record["early_signal"]
    assert state["url"] == renamed
    assert state["document"]["extraction"]["baseline"] is False
    assert state["first_seen_at"] == prior["tpit"]["first_seen_at"]


def test_row_records_are_emitted_every_run_from_the_snapshot_in_hand():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    kinds = [r for r in records if r.get("early_signal", {}).get("kind") == "tpit_row"]
    assert kinds
    prior = {
        r["state_key"]: r["early_signal"]
        for r in records
        if r.get("early_signal", {}).get("stateful")
    }
    again = listing(ercot_origin())
    stage(
        ercot_origin(),
        again,
        prior=prior,
        index={"urls": {"tpit": {"status": "document", "at": NOW.isoformat()}}},
    )
    two = [r for r in again if r.get("early_signal", {}).get("kind") == "tpit_row"]
    assert {r["document_number"] for r in kinds} == {r["document_number"] for r in two}


def test_persist_time_is_sized_for_the_tpit_rows_that_will_be_added(monkeypatch):
    seen: list[int] = []
    real = st.make_run

    def spy(**kw):
        seen.append(kw["record_count"])
        return real(**kw)

    monkeypatch.setattr(st, "make_run", spy)
    origin = ercot_origin()
    records = listing(origin)
    n = len(records)
    stage(origin, records)
    assert seen and seen[0] >= n + er.MAX_TPIT_ROWS_RESERVE


def test_tpit_free_text_loses_emails_and_phone_numbers():
    sheets = {k: [dict(r) for r in v] for k, v in SHEETS.items()}
    sheets["FutureTPIT100126NoCost"][0]["description"] = (
        "Expand station for a large load. Contact Jane Doe jane.doe@oncor.com or 512-555-1212."
    )
    extraction = tp.tpit_extraction(workbook(sheets), None, 60, False, "2026-10-01")
    blob = repr(extraction)
    assert "@" not in blob and "512-555-1212" not in blob
    assert "[email removed]" in blob and "[phone removed]" in blob


# --------------------------------------------------------------------------- S13, S14, nits


def test_a_bare_compass_name_is_not_a_link_key():
    assert lk.norm_substation("North") is None
    assert lk.norm_substation("West Substation") is None
    assert lk.norm_substation("North Plant") == "north plant"


def test_a_cited_id_counts_only_in_the_projects_own_sentence():
    unlike = px.text_fields(["Unlike 24RPG010, this project was reviewed separately."])
    other = px.text_fields(["The facility serves the area near 24RPG010 as well."])
    own = px.text_fields(["The Proposed Project was submitted for RPG review as 25RPG020."])
    assert unlike.get("rpg_ids", []) == [] and other.get("rpg_ids", []) == []
    assert [e["value"] for e in own["rpg_ids"]] == ["25RPG020"]


def test_substations_come_only_from_project_description_sentences():
    other = px.text_fields(["A third party also owns a new Foo Creek substation nearby."])
    mine = px.text_fields(
        [
            "The Proposed Project consists of constructing one new substation "
            "(the Legend Falls Substation)."
        ]
    )
    assert other.get("substations", []) == []
    assert [e["value"] for e in mine["substations"]] == ["Legend Falls"]


def test_future_meetings_are_not_listed_or_fetched():
    origin = ercot_origin()
    future = "https://www.ercot.com/calendar/12152026-RPG-Meeting"
    origin.put(HUB, hub_html(MEETING, future))
    records = listing(origin)
    assert records and future not in origin.urls()


def test_listing_shrink_is_a_notice_not_a_failure():
    origin = ercot_origin()
    records = listing(origin)
    report = stage(origin, records, index={"urls": {}, "listed_count": 10})
    assert [n["error_code"] for n in report.notices] == ["listing_shrink"]
    assert report.rejections == []
    assert report.index["listed_count"] == len(listing(origin))
    quiet = stage(ercot_origin(), listing(ercot_origin()), index={"urls": {}, "listed_count": 3})
    assert not quiet.notices


def test_retrieve_honours_the_deadline():
    origin = ercot_origin()
    definition = next(r for r in load_registry() if r["id"] == er.SOURCE_ID)
    with pytest.raises(TimeoutError):
        er.retrieve(
            definition,
            origin.client(),
            deadline=time.monotonic() - 1,
            pacer=lambda: None,
            today=TODAY,
        )
    assert origin.log == []


def test_list_item_dash_must_follow_whitespace_and_stop_at_the_sentence():
    names = rx._substations_from("New Load Stations – Alpha, – Beta; In-Service Date – June 2027")
    assert names == ["Alpha", "Beta"]
    assert rx._substations_from("New Load Stations - Alpha. Next sentence - Gamma, tapped") == [
        "Alpha"
    ]


def test_substation_reverification_is_real():
    assert rx._reverified_substation("Alpha", "New Load Stations – Alpha, tapped between")
    assert not rx._reverified_substation("Alpha", "the word Alpha appears in prose only")
    assert rx._substations_from("adds a new Whitetail 138-kV substation") == ["Whitetail"]


def test_case_style_slash_voltage_and_proposed_substation():
    f = px.case_style_fields(
        "APPLICATION OF X TO AMEND ITS CERTIFICATE OF CONVENIENCE AND NECESSITY FOR THE PROPOSED "
        "FOO 345/138-KV SUBSTATION IN BAR COUNTY"
    )
    assert [e["value"] for e in f["voltage_kv"]] == [345, 138]
    assert [e["value"] for e in f["substations"]] == ["Foo"]
    assert [e["value"] for e in f["counties"]] == ["Bar"]
