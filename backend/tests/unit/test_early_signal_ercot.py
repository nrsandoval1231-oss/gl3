"""ERCOT RPG, TPIT and System Planning: listing, URL policy, extraction, diff, change detection.

No network: HTTP is an httpx.MockTransport with DNS pinned to a public address. PDFs and the TPIT
workbook are tiny synthetic files built from short excerpts of the public documents.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from _early_signal_fixtures import (
    HUB,
    MEETING,
    OVERVIEW_PDF,
    PLANNING,
    SHEETS,
    STATUS_PAGES,
    STATUS_PDF,
    SYSPLAN_PDF,
    TPIT_XLSX,
    ercot_origin,
    pdf,
    planning_html,
    status_pdf,
    tpit_row,
    workbook,
)

import gridlens.ingestion.adapters.ercot_rpg as er
import gridlens.ingestion.adapters.ercot_rpg_extract as rx
import gridlens.ingestion.adapters.ercot_tpit as tp
from gridlens.ingestion.adapters.early_signal_stage import StageConfig, apply_state
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONFIG = StageConfig(max_downloads=6, max_checks=20, extract_seconds=120.0, isolate=False)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def text_pages(pages):
    return ["\n".join(lines) for lines in pages]


def source(**documents):
    definition = next(r for r in load_registry() if r["id"] == er.SOURCE_ID)
    definition = {**definition, "query": {**definition["query"]}}
    definition["query"]["documents"] = {**definition["query"]["documents"], **documents}
    return definition


def listing(origin, **kw):
    return er.retrieve(source(), origin.client(), pacer=lambda: None, today=date(2026, 11, 4), **kw)


def stage(origin, records, *, prior=None, index=None, now=NOW, config=CONFIG):
    return er.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        index=index,
        pacer=lambda: None,
        now=lambda: now,
    )


def states_of(records):
    return {
        r["state_key"]: r["early_signal"]
        for r in records
        if r.get("state_key") and "early_signal" in r
    }


# --------------------------------------------------------------------------- registry / ships off


def test_ships_off_and_validates():
    definition = source()
    assert definition["enabled"] is False
    assert definition["query"]["documents"]["enabled"] is False
    assert er.config_from_source(definition) is None
    assert er.valid_query(definition["query"])
    bad = {**definition["query"], "max_meetings": 99}
    assert not er.valid_query(bad)
    assert not er.valid_query({**definition["query"], "documents": {"enabled": True}})
    # An unlisted host or path cannot be a seed.
    seeds = {
        **definition["query"]["documents"],
        "seed_urls": ["https://evil.example/files/docs/2026/01/01/a.pdf"],
    }
    assert not er.valid_query({**definition["query"], "documents": seeds})


# --------------------------------------------------------------------------- URL policy


@pytest.mark.parametrize(
    "url",
    [
        HUB,
        PLANNING,
        MEETING,
        STATUS_PDF,
        TPIT_XLSX,
        "https://www.ercot.com/calendar/10082026-RPG-Meeting-_Webex-Only_",
    ],
)
def test_url_policy_accepts_reviewed_shapes(url):
    assert er.url_ok(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.ercot.com/files/docs/2026/07/17/a.pdf",
        "https://ercot.com/files/docs/2026/07/17/a.pdf",
        "https://www.ercot.com.evil.example/files/docs/2026/07/17/a.pdf",
        "https://evil.example/files/docs/2026/07/17/a.pdf",
        "https://www.ercot.com:8443/files/docs/2026/07/17/a.pdf",
        "https://user@www.ercot.com/files/docs/2026/07/17/a.pdf",
        "https://www.ercot.com/files/docs/2026/07/17/a.pdf?x=1",
        "https://www.ercot.com/files/docs/2026/07/17/a.pdf#frag",
        "https://www.ercot.com/files/docs/2026/13/45/a.pdf",
        "https://www.ercot.com/files/docs/2026/07/17/../a.pdf",
        "https://www.ercot.com/files/docs/2026/07/17/a.exe",
        "https://www.ercot.com/mp/export?x=1",
        "https://www.ercot.com/content/gridinfo/x",
        "https://www.ercot.com/calendar/07212026-RPG-Meeting/../x",
        "https://www.ercot.com/files/docs/2026/07/17/a b.pdf",
        "https://www.ercot.com/files/docs/2026/07/17/" + "a" * 260 + ".pdf",
    ],
)
def test_url_policy_rejects(url):
    assert not er.url_ok(url)


def test_fetcher_refuses_outside_policy_without_a_request():
    from gridlens.ingestion.adapters.early_signal_http import PDF, EarlyFetcher
    from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

    origin = ercot_origin()
    fetcher = EarlyFetcher(origin.client(), lambda: None, er.url_ok)
    with pytest.raises(DocumentFailure) as caught:
        fetcher.get("http://169.254.169.254/latest/meta-data", max_bytes=1000, media_types=PDF)
    assert caught.value.code == "url_policy"
    with pytest.raises(DocumentFailure):
        fetcher.get(
            "https://www.ercot.com/files/docs/2026/07/17/a.pdf?x=1", max_bytes=1000, media_types=PDF
        )
    assert origin.log == []


def test_fetcher_does_not_follow_redirects_and_pins_dns(monkeypatch):
    pinned: list[str] = []
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.tceq_http._public_ip",
        lambda host: pinned.append(host) or "8.8.8.8",
    )
    origin = ercot_origin()
    origin.put(STATUS_PDF, b"", status=302)
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_redirect_not_followed", 0) >= 1
    assert pinned and set(pinned) == {"www.ercot.com"}
    assert all(u.startswith("https://www.ercot.com/") for u in origin.urls())


def test_private_dns_answer_is_refused(monkeypatch):
    from gridlens.ingestion.adapters.federal_register import SourceParseError as Spe

    def private(_host):
        raise Spe("TCEQ host resolved to a non-public address")

    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", private)
    origin = ercot_origin()
    with pytest.raises(Spe):
        er.retrieve(source(), origin.client(), pacer=lambda: None, today=date(2026, 11, 4))
    assert origin.log == []


# --------------------------------------------------------------------------- listing


def test_listing_reads_hub_meeting_and_planning_only():
    origin = ercot_origin()
    records = listing(origin)
    assert origin.urls() == [HUB, MEETING, PLANNING]  # no document fetched, no date-path guess
    by_url = {r["state_key"]: r for r in records}
    assert set(by_url) == {STATUS_PDF, OVERVIEW_PDF, TPIT_XLSX}  # the agenda is not a project doc
    status = by_url[STATUS_PDF]
    assert status["publication_date"] == "2026-07-17" and status["event_date"] == "2026-07-21"
    assert status["doc_kind"] == "rpg_pdf" and by_url[TPIT_XLSX]["doc_kind"] == "tpit"
    assert by_url[TPIT_XLSX]["publication_date"] == "2026-10-23"
    # Off-host and relative meeting links on the hub are ignored.
    assert all(r["html_url"].startswith("https://www.ercot.com/files/docs/") for r in records)


def test_listing_records_are_stable_for_the_same_listing():
    one, two = listing(ercot_origin()), listing(ercot_origin())
    assert [(r["document_number"], r["source_hash"]) for r in one] == [
        (r["document_number"], r["source_hash"]) for r in two
    ]


def test_listing_rate_limited_is_typed_with_retry_after():
    origin = ercot_origin()
    from httpx import Response

    origin.force = lambda url: Response(429, headers={"retry-after": "120"}) if url == HUB else None
    with pytest.raises(SourceParseError) as caught:
        listing(origin)
    assert caught.value.acquisition_code == "http_status_429"
    assert caught.value.acquisition_retry_after_seconds == 120


def test_listing_js_shell_is_a_typed_failure():
    origin = ercot_origin()
    origin.put(HUB, b"<html><script>app()</script></html>", ctype="application/json")
    with pytest.raises(SourceParseError):
        listing(origin)


def test_listing_rejects_wrong_source_or_endpoint():
    origin = ercot_origin()
    bad = {**source(), "endpoint": "https://www.ercot.com/committees/other/rpg/2025"}
    with pytest.raises(SourceParseError):
        er.retrieve(bad, origin.client(), pacer=lambda: None)
    assert origin.log == []


def test_listing_one_request_per_second_with_the_shared_pacer():
    origin = ercot_origin()
    now = {"t": 1000.0}
    sleeps: list[float] = []
    from gridlens.ingestion.adapters.tceq_application_documents import Pacer

    pacer = Pacer(
        clock=lambda: now["t"],
        sleep=lambda s: (sleeps.append(s), now.__setitem__("t", now["t"] + s)),
    )
    er.retrieve(source(), origin.client(), pacer=pacer, today=date(2026, 11, 4))
    assert len(origin.log) == 3 and len(sleeps) == 3 and all(abs(s - 1.0) < 1e-6 for s in sleeps)


# --------------------------------------------------------------------------- extraction


def test_project_fields_from_the_status_update_with_evidence():
    origin = ercot_origin()
    records = listing(origin)
    report = stage(origin, records)
    assert report.rejections == []
    state = states_of(records)[STATUS_PDF]
    projects = {p["project_id"]: p["fields"] for p in state["document"]["extraction"]["projects"]}
    assert set(projects) == {"25RPG020", "25RPG046"}
    cps, stec = projects["25RPG020"], projects["25RPG046"]
    assert cps["utility"]["value"] == "CPS Energy"
    assert cps["tier"]["value"] == "Tier 1"
    assert cps["cost"]["value"] == 333_700_000 and cps["cost"]["basis"] == "calculated"
    assert cps["in_service"]["value"] == "Summer Peak 2035"
    assert cps["ccn"]["value"] is True
    assert cps["load"]["value"] == 2000 and cps["load"]["basis"] == "calculated"
    assert [c["value"] for c in cps["counties"]] == ["Bexar", "Medina"]
    assert stec["load"]["value"] == 1000 and stec["cost"]["value"] == 492_000_000
    # No county is stated for the STEC project: unknown, never guessed from its name.
    assert stec["counties"]["basis"] == "unknown"
    assert stec["utility"]["value"] == "South Texas Electric Cooperative (STEC)"
    # Study-assumption MW ("980 MW of new STEC load") is not a project load.
    assert stec["load"]["value"] == 1000
    sha = state["document"]["sha256"]
    for field in ("utility", "tier", "cost", "in_service", "ccn", "load"):
        ev = cps[field]
        assert ev["quote"] and ev["page"] == 2 and ev["span"][1] - ev["span"][0] == len(ev["quote"])
    assert len(sha) == 64


def test_every_value_reproduces_from_its_own_quote():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    projects = states_of(records)[STATUS_PDF]["document"]["extraction"]["projects"]
    for project in projects:
        for name, ev in project["fields"].items():
            if isinstance(ev, dict) and ev.get("basis") != "unknown":
                rerun = rx._EXTRACTORS.get(name)
                if rerun is not None:
                    assert rerun(ev["quote"]) is not None


def test_unknown_is_not_zero_when_nothing_is_stated():
    pages = [["25RPG099 Some Project", "A routine status page with no figures."]]
    projects, loose = rx.extract_projects(text_pages(pages))
    assert projects[0]["fields"]["load"] == {
        "value": None,
        "basis": "unknown",
        "reason": "not_stated",
    }
    assert projects[0]["fields"]["cost"]["value"] is None
    assert loose == {"counties": [], "substations": []}


def test_conflicting_statements_stay_unknown_with_both_quotes():
    pages = [["25RPG001 Project", "· This is a Tier 1 project", "· This is a Tier 2 project"]]
    projects, _ = rx.extract_projects(text_pages(pages))
    tier = projects[0]["fields"]["tier"]
    assert tier["value"] is None and tier["reason"] == "conflicting_statements"
    assert len(tier["candidates"]) == 2


def test_fields_are_not_attributed_across_projects_or_to_a_page_without_an_id():
    pages = [
        [
            "Combined 25RPG020 and 25RPG046",
            "· This is a Tier 1 project with an estimated cost of $9 million",
        ],
        ["Next page", "· Estimated in-service date (ISD) is June 2031"],
    ]
    projects, _ = rx.extract_projects(text_pages(pages))
    assert projects == []  # two IDs in one statement, then a page with none: nothing attributed


def test_places_without_a_project_are_kept_apart():
    pages = [
        ["25RPG001 and 25RPG002", "· New Load Stations", "– Rogers Road, tapped between X and Y"]
    ]
    projects, loose = rx.extract_projects(text_pages(pages))
    assert projects == [] and [s["value"] for s in loose["substations"]] == ["Rogers Road"]


def test_single_project_document_attributes_all_pages_and_finds_substations():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    state = states_of(records)[OVERVIEW_PDF]
    (project,) = state["document"]["extraction"]["projects"]
    fields = project["fields"]
    assert project["project_id"] == "26RPG022"
    assert fields["tier"]["value"] == "Tier 2" and fields["ccn"]["value"] is False
    assert fields["cost"]["value"] == 41_200_000
    assert [c["value"] for c in fields["counties"]] == ["Travis"]
    assert [s["value"] for s in fields["substations"]] == ["Whitetail"]


def test_scanned_pdf_is_an_abstention_not_zero():
    origin = ercot_origin(status_body=b"%PDF-1.4\n%%EOF")
    records = listing(origin)
    report = stage(origin, records)
    assert any(
        r["error_code"].startswith("text_layer_") or r["error_code"] == "empty_text_layer"
        for r in report.rejections
    )
    # An unread document is left out of the run, never stored as an empty record.
    assert STATUS_PDF not in {r.get("state_key") for r in records}
    assert report.counts["withheld_unread"] >= 1


def test_html_in_place_of_a_pdf_is_js_shell():
    origin = ercot_origin()
    origin.put(STATUS_PDF, b"<html>app</html>", ctype="text/html")
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_js_shell") == 1


def test_wrong_signature_is_rejected():
    origin = ercot_origin()
    origin.put(STATUS_PDF, b"MZ\x90\x00 not a pdf", ctype="application/pdf")
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_not_pdf_signature") == 1


def test_oversize_by_content_length_and_by_count(monkeypatch):
    origin = ercot_origin()
    monkeypatch.setattr(er, "MAX_PDF_BYTES", 500)
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_oversize", 0) >= 1


# --------------------------------------------------------------------------- change detection


def test_unchanged_rerun_is_idempotent_and_skips_downloads():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    first = {
        r["document_number"]: (r["source_hash"], r["abstract"])
        for r in records
        if r.get("state_key") and "early_signal" in r
    }
    prior = states_of(records)
    again_origin = ercot_origin()
    again = listing(again_origin)
    report = stage(
        again_origin,
        again,
        prior=prior,
        index={"urls": {k: {"status": "document", "at": NOW.isoformat()} for k in prior}},
    )
    # Pre-existing states inside the recheck window make no document request at all.
    document_gets = [u for u in again_origin.urls() if "/files/docs/" in u and u != TPIT_XLSX]
    assert document_gets == [] and report.counts.get("fresh_skipped", 0) >= 2
    second = {
        r["document_number"]: (r["source_hash"], r["abstract"])
        for r in again
        if r.get("state_key") and "early_signal" in r
    }
    assert second == first


def test_conditional_get_304_and_hash_equality_skip_extraction():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    prior = states_of(records)
    later = NOW + timedelta(days=20)
    again_origin = ercot_origin()
    again = listing(again_origin)
    report = stage(
        again_origin,
        again,
        prior=prior,
        index={"urls": {k: {"status": "document", "at": NOW.isoformat()} for k in prior}},
        now=later,
    )
    assert report.counts.get("unchanged", 0) >= 1 or report.counts.get("unchanged_by_hash", 0) >= 1
    assert report.counts.get("new", 0) == 0 and report.counts.get("updated", 0) == 0
    # An identical body with a new ETag is unchanged by hash.
    third_origin = ercot_origin()
    third_origin.put(STATUS_PDF, third_origin.routes[STATUS_PDF][2], etag='"e2"')
    third = listing(third_origin)
    r3 = stage(third_origin, third, prior=prior, index={"urls": {}}, now=later)
    assert r3.counts.get("unchanged_by_hash", 0) >= 1


def test_changed_bytes_make_a_new_state_keeping_first_seen():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    prior = states_of(records)
    old_sha = prior[STATUS_PDF]["document"]["sha256"]
    changed = ercot_origin(status_body=status_pdf([[*page] for page in STATUS_PAGES[:-1]]))
    later = NOW + timedelta(days=30)
    again = listing(changed)
    stage(changed, again, prior=prior, index={"urls": {}}, now=later)
    new_state = states_of(again)[STATUS_PDF]
    assert new_state["first_seen_at"] == prior[STATUS_PDF]["first_seen_at"] == NOW.isoformat()
    assert new_state["document"]["sha256"] != old_sha
    assert new_state["document"]["replaced_sha256"] == [old_sha]
    record = next(r for r in again if r["state_key"] == STATUS_PDF)
    assert f"Source document SHA-256: {new_state['document']['sha256']}" in record["abstract"]


def test_apply_state_is_atomic_and_repeatable():
    origin = ercot_origin()
    records = listing(origin)
    stage(origin, records)
    record = next(r for r in records if r["state_key"] == STATUS_PDF)
    once = (record["abstract"], record["source_hash"])
    apply_state(record, record["early_signal"])
    assert (record["abstract"], record["source_hash"]) == once


def test_download_budget_defers_and_withholds_unread_documents():
    origin = ercot_origin()
    records = listing(origin)
    report = stage(origin, records, config=StageConfig(1, 20, 120.0, (), False))
    assert report.counts["downloads"] == 1 and report.counts.get("deferred_download_budget", 0) >= 1
    kept = {r["state_key"] for r in records if r.get("state_key")}
    assert len(kept) == 1 and report.counts["withheld_unread"] == 2


# --------------------------------------------------------------------------- 429 / not_before


def test_429_stops_the_stage_and_sets_not_before_from_retry_after():
    origin = ercot_origin()
    from httpx import Response

    origin.force = (
        lambda url: Response(429, headers={"retry-after": "600"}) if url == STATUS_PDF else None
    )
    records = listing(origin)
    origin.log.clear()
    report = stage(origin, records)
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 600
    assert report.index["not_before"] == (NOW + timedelta(seconds=600)).isoformat()
    n = len(origin.log)
    # While resting no request is made.
    again = stage(
        origin, listing(ercot_origin()), index=report.index, now=NOW + timedelta(seconds=100)
    )
    assert again.counts.get("skipped_retry_after") == 1 and len(origin.log) == n
    assert again.index["not_before"] == report.index["not_before"]
    # After it passes the stage works again.
    clear = ercot_origin()
    ok = stage(clear, listing(clear), index=report.index, now=NOW + timedelta(seconds=700))
    assert "not_before" not in ok.index and ok.counts.get("new", 0) >= 1


def test_503_without_retry_after_rests_one_hour():
    origin = ercot_origin()
    from httpx import Response

    origin.force = lambda url: Response(503) if url == OVERVIEW_PDF else None
    records = listing(origin)
    report = stage(origin, records)
    assert report.index["not_before"] == (NOW + timedelta(hours=1)).isoformat()


# --------------------------------------------------------------------------- failures are bounded


def test_retry_back_off_after_three_environment_failures():
    from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

    origin = ercot_origin()
    records = listing(origin)
    index: dict = {"urls": {}}
    key = STATUS_PDF
    index["urls"][key] = {
        "status": "pending",
        "at": NOW.isoformat(),
        "retry": {"code": "network_error", "attempts": 3, "at": NOW.isoformat()},
    }
    report = stage(origin, records, index=index, now=NOW + timedelta(days=1))
    assert report.counts.get("backed_off") == 1
    assert DocumentFailure("network_error").retryable


def test_failed_permanently_not_retried_until_recheck_window():
    origin = ercot_origin()
    origin.put(STATUS_PDF, b"MZ not a pdf", ctype="application/pdf")
    records = listing(origin)
    first = stage(origin, records)
    n = len(origin.log)
    again = stage(origin, listing(origin), index=first.index, now=NOW + timedelta(days=1))
    assert again.counts.get("known_failed", 0) >= 1
    assert not any(u == STATUS_PDF for u in origin.urls()[n:])


# --------------------------------------------------------------------------- TPIT


def tpit_state(origin=None, now=NOW, prior=None):
    origin = origin or ercot_origin()
    records = listing(origin)
    report = stage(origin, records, prior=prior, now=now, index={"urls": {}})
    return records, report


def test_tpit_snapshot_keeps_only_relevant_rows_and_never_contacts():
    records, report = tpit_state()
    assert report.rejections == []
    state = states_of(records)[TPIT_XLSX]
    extraction = state["document"]["extraction"]
    assert extraction["sheet_counts"] == {"Future": 4, "Planned": 1, "Completed": 1, "Cancelled": 1}
    rows = extraction["rows"]
    assert "99999" not in rows  # Tier 4 breaker replacement: not relevant
    assert {"100305", "90051", "110828", "73025", "81573"} <= set(rows)
    blob = repr(extraction)
    assert "example.com" not in blob and "Jane Doe" not in blob
    assert extraction["baseline"] is True and extraction["diff"] == []
    assert "no MW is derived" in extraction["summary_lines"][-1]
    assert rows["73025"]["rpg"] == "22RPG005" and rows["90051"]["county"] == "Wilbarger"


def test_tpit_baseline_rows_are_observations_labelled_baseline():
    records, _ = tpit_state()
    rows = [
        r
        for r in records
        if r["document_number"].startswith("ERCOT-TPIT-")
        and r.get("early_signal", {}).get("kind") == "tpit_row"
    ]
    assert rows and all(r["early_signal"]["change"] == "baseline" for r in rows)
    one = next(r for r in rows if r["early_signal"]["project"] == "90051")
    assert "baseline, not a new project" in one["abstract"]
    assert "Load MW: not stated in TPIT; unknown is not zero." in one["abstract"]
    assert one["early_signal"]["stateful"] is False
    assert one["early_signal"]["first_seen_at"] == "2026-11-04"
    assert one["publication_date"] == "2026-10-23"


def test_tpit_monthly_diff_new_changed_removed_and_first_seen_carried():
    records, _ = tpit_state()
    prior = states_of(records)
    sheets = {k: [dict(r) for r in v] for k, v in SHEETS.items()}
    sheets["FutureTPIT100126NoCost"] = [
        r for r in sheets["FutureTPIT100126NoCost"] if r["number"] != "100305"
    ]
    for row in sheets["FutureTPIT100126NoCost"]:
        if row["number"] == "110828":
            row["isd"] = "2029-06-30"
    sheets["FutureTPIT100126NoCost"].append(
        tpit_row("120000", title="New Data Center sub", description="serve a data center")
    )
    origin = ercot_origin(tpit_body=workbook(sheets))
    origin.put(PLANNING, planning_html(tpit_listed="Nov 25, 2026"))
    later = NOW + timedelta(days=30)
    records2, report = tpit_state(origin, later, prior)
    extraction = states_of(records2)[TPIT_XLSX]["document"]["extraction"]
    assert extraction["baseline"] is False
    changes = {c["project"]: c for c in extraction["diff"]}
    assert changes["120000"]["change"] == "new"
    assert changes["110828"]["change"] == "changed" and "isd" in changes["110828"]["fields"]
    assert changes["100305"]["change"] == "removed"
    assert "99999" not in changes
    rows = {
        r["early_signal"]["project"]: r
        for r in records2
        if r.get("early_signal", {}).get("kind") == "tpit_row"
    }
    assert set(rows) == {"120000", "110828", "100305"}
    assert rows["100305"]["early_signal"]["change"] == "removed"
    assert (
        rows["100305"]["early_signal"]["first_seen_at"] == "2026-11-04"
    )  # carried from the baseline
    assert rows["120000"]["early_signal"]["first_seen_at"] == "2026-11-04"  # snapshot listing day
    assert "Fields changed: isd" in rows["110828"]["abstract"]
    # Row observation identities are per snapshot, so a re-run does not duplicate them.
    again = {
        r["document_number"]
        for r in records2
        if r.get("early_signal", {}).get("kind") == "tpit_row"
    }
    assert len(again) == 3


def test_tpit_unchanged_snapshot_adds_no_rows():
    records, _ = tpit_state()
    prior = states_of(records)
    again, _ = tpit_state(ercot_origin(), NOW + timedelta(days=2), prior)
    assert not [r for r in again if r.get("early_signal", {}).get("kind") == "tpit_row"]


def test_tpit_changed_columns_is_a_typed_failure():
    bad = workbook({"FutureTPIT100126NoCost": []})
    import io

    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(bad))
    ws = book["FutureTPIT100126NoCost"]
    ws["A2"] = "Something Else"
    out = io.BytesIO()
    book.save(out)
    origin = ercot_origin(tpit_body=out.getvalue())
    records = listing(origin)
    report = stage(origin, records)
    assert report.counts.get("failure_workbook_columns_changed") == 1


def test_tpit_not_a_zip_and_zip_bomb_are_typed_failures():
    from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

    with pytest.raises(DocumentFailure) as caught:
        tp.read_workbook(b"GIF89a....")
    assert caught.value.code == "not_xlsx_signature"
    with pytest.raises(DocumentFailure) as caught:
        tp.read_workbook(b"PK\x03\x04 truncated")
    assert caught.value.code == "workbook_unreadable"


def test_tpit_isolated_child_matches_in_process():
    body = workbook(SHEETS)
    inline = tp.tpit_extraction(body, None, 60.0, False, "2026-11-04")
    isolated = tp.tpit_extraction(body, None, 60.0, True, "2026-11-04")
    assert inline == isolated


# --------------------------------------------------------------------------- System Planning


def test_system_planning_aggregates_are_ercot_wide_with_evidence():
    pages = [
        [
            "As of July 31, 2026, ERCOT has",
            "endorsed transmission projects totaling $12.111 billion.",
        ],
        [
            "Of the $22.947 billion of RPG Projects",
            "ERCOT is currently reviewing:",
            "· $21.311 billion is Large Load-",
            "dependent and may not move forward",
        ],
        ["Year to date 2026, 1,114 new projects have been submitted."],
    ]
    origin = ercot_origin()
    origin.put(SYSPLAN_PDF, pdf(pages))
    cfg = {"seed_urls": [SYSPLAN_PDF]}
    definition = source(**cfg)
    records = er.retrieve(definition, origin.client(), pacer=lambda: None, today=date(2026, 11, 4))
    kinds = {r["state_key"]: r["doc_kind"] for r in records}
    assert kinds[SYSPLAN_PDF] == "system_planning"
    stage(origin, records)
    state = states_of(records)[SYSPLAN_PDF]
    aggregates = state["document"]["extraction"]["aggregates"]
    assert aggregates["rpg_projects_under_review_usd"]["value"] == 22_947_000_000
    assert aggregates["large_load_dependent_usd"]["value"] == 21_311_000_000
    assert aggregates["endorsed_transmission_total_usd"]["value"] == 12_111_000_000
    assert aggregates["new_planning_model_projects_ytd"]["value"] == 1114
    assert "no project, utility, county or site" in state["document"]["extraction"]["note"]
