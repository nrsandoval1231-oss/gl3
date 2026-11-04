"""NMED application documents: URL policy, listing, change detection, limits, 429, extraction.

No test touches the network: HTTP goes through httpx.MockTransport with DNS pinned to a public
address, and pacing uses a fake clock. PDFs are synthetic text pages.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from _nmed_fixtures import (
    ELECTRIC_PROSE,
    GENERATOR_ONLY,
    HOST,
    LISTING,
    FakeClock,
    Origin,
    application_pdf,
    listing_html,
    url,
)

import gridlens.ingestion.adapters.nmed_application_documents as nad
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import Pacer
from gridlens.ingestion.registry import load_registry

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONFIG = nad.StageConfig(max_downloads=3, max_checks=10, extract_seconds=120.0, isolate=False)
DOC = url()
SECOND = url("2025/04", "NSR-Application-3426M1")


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def records_for(*urls):
    return [nad.record_for(item) for item in urls]


def run(origin, records, *, config=CONFIG, prior=None, index=None, now=NOW, **kwargs):
    return nad.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        index=index,
        pacer=kwargs.pop("pacer", lambda: None),
        now=lambda: now,
        **kwargs,
    )


def states_of(records):
    return {r["pdf_url"]: r[nad.STATE_KEY] for r in records if nad.STATE_KEY in r}


# --------------------------------------------------------------------------- URL policy


@pytest.mark.parametrize(
    "good",
    [
        url(),
        url("2024/12", "NSR-Application-3426M1"),
        f"https://{HOST}/public-notices/wp-content/uploads/sites/32/2023/03/A-199L-CRSWF-Air-Quality-Permit-Application.pdf",
    ],
)
def test_upload_urls_that_pass(good):
    assert nad.document_url_ok(good)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        42,
        url().replace("https://", "http://"),
        url().replace(HOST, "www-archive.env.nm.gov"),
        url().replace(HOST, f"{HOST}.attacker.test"),
        url().replace("https://", "https://user:pw@"),
        url().replace(HOST, f"{HOST}:8443"),
        url() + "?download=1",
        url() + "#page=2",
        url().replace("sites/2", "sites/3"),
        url().replace("2025/01", "2025/13"),
        url().replace("2025/01", "1999/01"),
        url().replace(".pdf", ".html"),
        url().replace("/A-1092", "/../A-1092"),
        url().replace("/A-1092", "/%2e%2e/A-1092"),
        f"https://{HOST}/air-quality/wp-content/uploads/sites/2/2025/01/sub/dir/x.pdf",
        f"https://{HOST}/rcb/wp-content/uploads/sites/16/2026/02/Application.pdf",
        "https://169.254.169.254/air-quality/wp-content/uploads/sites/2/2025/01/x.pdf",
    ],
)
def test_upload_urls_that_fail(bad):
    assert nad.document_url_ok(bad) is False


def test_upload_month_comes_only_from_the_path():
    assert nad.upload_month(DOC) == "2025-01"
    assert nad.upload_month("https://example.com/x.pdf") is None


# --------------------------------------------------------------------------- listing parse


def test_listing_links_keep_only_air_quality_application_pdfs_newest_first():
    html = listing_html(
        url("2024/07", "Application-Update-10267"),
        url("2025/04", "NSR-Application-3426M1"),
        "/air-quality/wp-content/uploads/sites/2/2025/01/P278R1_Application.pdf",
        url("2024/08", "Approval-RE05-8661"),
        url("2024/07", "Letter-10267"),
        url("2024/07", "Application-Update-10267"),  # duplicate
        url("2022/08", "Hearing-Notice-Application-Spanish"),
        "https://www-archive.env.nm.gov/air-quality/wp-content/uploads/sites/2/2021/06/AQBP-Roper-Application.pdf",
        f"https://{HOST}/rcb/wp-content/uploads/sites/16/2026/02/Application-x.pdf",
        "javascript:alert(1)",
        "mailto:a@b.test",
        "#top",
        url("2025/02", "Not-A-Match"),
    )
    links = nad.parse_listing_links(html)
    assert [nad.upload_month(item) for item in links] == ["2025-04", "2025-01", "2024-07"]
    assert len(links) == len(set(links)) == 3


def test_listing_parser_tolerates_broken_markup_and_huge_hrefs():
    html = b"<a href='" + b"x" * 5000 + b"'><a href=" + DOC.encode() + b">unterminated <b>"
    assert nad.parse_listing_links(html) == [DOC]


def test_record_is_dated_by_month_only_and_stable():
    record = nad.record_for(DOC)
    assert record["publication_date"] == "2025-01-01"
    assert record["publication_date_precision"] == "month"
    assert record["document_number"] == nad.record_for(DOC)["document_number"]
    assert record["document_number"] != nad.record_for(SECOND)["document_number"]
    assert record["html_url"] == record["pdf_url"] == DOC
    assert len(record["source_hash"]) == 64
    with pytest.raises(SourceParseError):
        nad.record_for("https://example.com/x.pdf")


# --------------------------------------------------------------------------- retrieve


def source(**query):
    base = next(r for r in load_registry() if r["id"] == nad.SOURCE_ID)
    return {**base, "query": {**base["query"], **query}}


def test_registry_entry_ships_off_and_validates():
    entry = next(r for r in load_registry() if r["id"] == nad.SOURCE_ID)
    assert entry["enabled"] is False
    assert entry["query"]["application_documents"]["enabled"] is False
    assert entry["query"]["application_documents"]["seed_urls"] == []
    assert nad.config_from_source(entry) is None
    assert entry["endpoint"] == LISTING


def test_retrieve_makes_one_request_and_no_pdf_fetch():
    origin = Origin()
    origin.listing = (
        200,
        {"content-type": "text/html"},
        listing_html(DOC, url("2024/07", "Letter-1")),
    )
    records = nad.retrieve(source(), origin.client())
    assert [r["pdf_url"] for r in records] == [DOC]
    assert origin.log == [("GET", LISTING)]


def test_seed_urls_are_added_first_and_deduplicated():
    origin = Origin()
    origin.listing = (200, {"content-type": "text/html"}, listing_html(DOC, SECOND))
    seed = url("2020/08", "AQBP-Application-6567M6")
    query = copy.deepcopy(source()["query"])
    query["application_documents"]["seed_urls"] = [seed, DOC]
    records = nad.retrieve(
        source(application_documents=query["application_documents"]), origin.client()
    )
    assert [r["pdf_url"] for r in records] == [seed, DOC, SECOND]


def test_max_records_bounds_the_listing():
    origin = Origin()
    many = [url("2025/01", f"Application-{i}") for i in range(30)]
    origin.listing = (200, {"content-type": "text/html"}, listing_html(*many))
    assert len(nad.retrieve(source(max_records=5), origin.client())) == 5


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ((200, {"content-type": "application/pdf"}, b"%PDF-"), "wrong_content_type"),
        ((302, {"location": "https://x.example/"}, b""), "redirect_not_followed"),
        ((429, {"retry-after": "60"}, b""), "http_status_429"),
        ((503, {}, b""), "http_status_503"),
        ((404, {"content-type": "text/html"}, b""), "http_status_404"),
    ],
)
def test_retrieve_failures_are_typed(reply, why):
    origin = Origin()
    origin.listing = reply
    with pytest.raises(SourceParseError, match=why):
        nad.retrieve(source(), origin.client())


def test_listing_response_is_size_capped():
    origin = Origin()
    origin.listing = (
        200,
        {"content-type": "text/html"},
        b"<html>" + b"x" * nad.MAX_LISTING_BYTES,
    )
    with pytest.raises(SourceParseError, match="oversize"):
        nad.retrieve(source(), origin.client())


def test_retrieve_refuses_a_foreign_source_or_endpoint():
    origin = Origin()
    with pytest.raises(SourceParseError):
        nad.retrieve({**source(), "id": "other"}, origin.client())
    with pytest.raises(SourceParseError):
        nad.retrieve({**source(), "endpoint": "https://example.com/"}, origin.client())
    assert origin.log == []


# --------------------------------------------------------------------------- configuration

GOOD = {
    "enabled": True,
    "max_downloads": 2,
    "max_checks": 40,
    "extract_seconds": 300,
    "seed_urls": [],
}


def test_config_bounds():
    assert nad.valid_config(GOOD)
    bad = [
        {**GOOD, "enabled": 1},
        {**GOOD, "max_downloads": 0},
        {**GOOD, "max_downloads": 6},
        {**GOOD, "max_checks": 61},
        {**GOOD, "extract_seconds": 59},
        {**GOOD, "extract_seconds": 901},
        {**GOOD, "seed_urls": ["https://example.com/x.pdf"]},
        {**GOOD, "seed_urls": [DOC, DOC]},
        {**GOOD, "seed_urls": [url("2025/01", f"Application-{i}") for i in range(51)]},
        {**GOOD, "extra": 1},
        {k: v for k, v in GOOD.items() if k != "seed_urls"},
        None,
    ]
    for item in bad:
        assert not nad.valid_config(item), item
    assert nad.config_from_source({"query": {"application_documents": GOOD}}) is not None


def test_registry_rejects_an_unbounded_query(tmp_path):
    import json

    from gridlens.ingestion.registry import REGISTRY_PATH

    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for entry in raw["sources"]:
        if entry["id"] == nad.SOURCE_ID:
            entry["query"]["application_documents"]["max_checks"] = 500
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(path)


# --------------------------------------------------------------------------- extraction


def test_electric_motors_become_demand_and_the_rest_supply():
    origin = Origin()
    origin.put(DOC, application_pdf())
    recs = records_for(DOC)
    report = run(origin, recs)
    state = recs[0][nad.STATE_KEY]
    extraction = state["document"]["extraction"]
    assert report.counts["new"] == 1 and report.counts["status_extracted"] == 1
    assert extraction["demand_lines"] == 1
    assert "2500" in extraction["schedule_text"] or "2,500" in extraction["schedule_text"]
    assert extraction["schedule_text"].strip() in recs[0]["abstract"]
    assert extraction["supply_total"] >= 2
    drives = {row.get("drive") for row in extraction["supply"]}
    assert "electric" not in drives
    line = next(iter(extraction["line_provenance"].values()))
    assert line["page"] >= 1 and line["outer_sha256"] == state["document"]["sha256"]
    assert state["upload_month"] == "2025-01" and state["document"]["abstain"] is None


def test_rating_without_a_stated_driver_never_becomes_demand():
    origin = Origin()
    origin.put(DOC, application_pdf("The station has three 5,200-hp Ariel compressors."))
    recs = records_for(DOC)
    run(origin, recs)
    extraction = recs[0][nad.STATE_KEY]["document"]["extraction"]
    assert extraction["demand_lines"] == 0 and extraction["schedule_text"] == ""
    assert extraction["supply_total"] == 1
    assert recs[0][nad.STATE_KEY]["document"]["abstain"]["note"].startswith("Abstention")
    base = nad.record_for(DOC)["abstract"]
    sha = recs[0][nad.STATE_KEY]["document"]["sha256"]
    assert recs[0]["abstract"] == f"{base}\nSource document SHA-256: {sha}"
    assert "Equipment ID" not in recs[0]["abstract"]


def test_generator_only_is_supply_and_an_abstention():
    origin = Origin()
    origin.put(DOC, application_pdf(GENERATOR_ONLY))
    recs = records_for(DOC)
    run(origin, recs)
    document = recs[0][nad.STATE_KEY]["document"]
    assert document["extraction"]["demand_lines"] == 0 and document["abstain"] is not None


def test_no_equipment_text_is_a_notice_not_a_failure():
    origin = Origin()
    origin.put(DOC, application_pdf("Nothing about equipment here, only narrative text."))
    recs = records_for(DOC)
    report = run(origin, recs)
    assert report.rejections == []
    assert [n["error_code"] for n in report.notices] == ["zero_verified_rows"]
    assert recs[0][nad.STATE_KEY]["document"]["abstain"]["reason"] == "no equipment schedule found"


def test_the_isolated_child_process_path_works():
    origin = Origin()
    origin.put(DOC, application_pdf())
    recs = records_for(DOC)
    run(origin, recs, config=dataclasses.replace(CONFIG, isolate=True))
    assert recs[0][nad.STATE_KEY]["document"]["extraction"]["demand_lines"] == 1


# --------------------------------------------------------------------------- change detection


def test_unchanged_document_costs_one_head_and_keeps_the_hash():
    origin = Origin()
    origin.put(DOC, application_pdf())
    first = records_for(DOC)
    report = run(origin, first)
    origin.log.clear()
    second = records_for(DOC)
    again = run(
        origin,
        second,
        prior=states_of(first),
        index=report.index,
        now=NOW + timedelta(days=1),
    )
    assert origin.methods() == ["HEAD"]
    assert again.counts["unchanged"] == 1 and "downloads" in again.counts
    assert again.counts["downloads"] == 0
    assert second[0]["source_hash"] == first[0]["source_hash"]
    assert second[0]["abstract"] == first[0]["abstract"]
    assert second[0][nad.STATE_KEY]["first_seen_at"] == first[0][nad.STATE_KEY]["first_seen_at"]


def test_new_etag_with_identical_bytes_is_unchanged_by_hash():
    origin = Origin()
    origin.put(DOC, application_pdf(), etag='"e1"')
    first = records_for(DOC)
    report = run(origin, first)
    origin.put(DOC, application_pdf(), etag='"e2"')
    second = records_for(DOC)
    again = run(
        origin, second, prior=states_of(first), index=report.index, now=NOW + timedelta(days=1)
    )
    assert again.counts["unchanged_by_hash"] == 1
    assert second[0]["source_hash"] == first[0]["source_hash"]
    assert again.index["urls"][DOC]["validators"]["etag"] == '"e2"'


def test_changed_bytes_update_the_state_and_keep_first_seen():
    origin = Origin()
    origin.put(DOC, application_pdf(ELECTRIC_PROSE))
    first = records_for(DOC)
    report = run(origin, first)
    origin.put(DOC, application_pdf(ELECTRIC_PROSE, GENERATOR_ONLY), etag='"e2"')
    second = records_for(DOC)
    again = run(
        origin, second, prior=states_of(first), index=report.index, now=NOW + timedelta(days=2)
    )
    new, old = second[0][nad.STATE_KEY], first[0][nad.STATE_KEY]
    assert again.counts["updated"] == 1
    assert new["document"]["sha256"] != old["document"]["sha256"]
    assert new["document"]["replaced_sha256"] == [old["document"]["sha256"]]
    assert new["first_seen_at"] == old["first_seen_at"]
    assert second[0]["source_hash"] != first[0]["source_hash"]


def test_applying_a_state_twice_is_idempotent():
    origin = Origin()
    origin.put(DOC, application_pdf())
    recs = records_for(DOC)
    run(origin, recs)
    once = copy.deepcopy(recs[0])
    nad.apply_state(recs[0], recs[0][nad.STATE_KEY])
    assert recs[0]["abstract"] == once["abstract"]
    assert recs[0]["source_hash"] == once["source_hash"]


def test_prior_states_are_kept_when_the_stage_is_skipped():
    origin = Origin()
    origin.put(DOC, application_pdf())
    first = records_for(DOC)
    run(origin, first)
    fresh = records_for(DOC)
    assert nad.apply_prior_states(fresh, states_of(first)) == 1
    assert fresh[0]["source_hash"] == first[0]["source_hash"]


# --------------------------------------------------------------------------- limits


def test_download_budget_defers_the_rest_and_the_next_run_finishes():
    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.put(SECOND, application_pdf(ELECTRIC_PROSE))
    config = dataclasses.replace(CONFIG, max_downloads=1)
    recs = records_for(DOC, SECOND)
    report = run(origin, recs, config=config)
    assert report.counts["downloads"] == 1 and report.counts["deferred_download_budget"] == 1
    assert len(states_of(recs)) == 1
    second_run = records_for(DOC, SECOND)
    again = run(
        origin,
        second_run,
        config=config,
        prior=states_of(recs),
        index=report.index,
        now=NOW + timedelta(days=1),
    )
    assert len(states_of(second_run)) == 2 and again.counts["new"] == 1


def test_check_budget_bounds_requests_per_run():
    origin = Origin()
    urls = [url("2025/01", f"Application-{i}") for i in range(6)]
    for item in urls:
        origin.put(item, application_pdf())
    report = run(origin, records_for(*urls), config=dataclasses.replace(CONFIG, max_checks=2))
    assert report.counts["checked"] == 2 and report.counts["deferred_check_budget"] == 1
    assert origin.methods().count("HEAD") == 2


def test_oversize_by_declared_length_is_remembered_not_refetched(monkeypatch):
    monkeypatch.setattr(nad, "MAX_PDF_BYTES", 1000)
    origin = Origin()
    origin.put(DOC, b"%PDF-" + b"0" * 5000)
    rep = run(origin, records_for(DOC))
    assert rep.counts["failure_oversize"] == 1
    assert origin.methods() == ["HEAD"]
    assert rep.index["urls"][DOC]["status"] == "failed"
    origin.log.clear()
    soon = run(origin, records_for(DOC), index=rep.index, now=NOW + timedelta(days=1))
    assert origin.log == [] and soon.counts.get("checked", 0) == 0
    later = run(origin, records_for(DOC), index=rep.index, now=NOW + timedelta(days=8))
    assert later.counts["known_failed"] == 1 and origin.methods() == ["HEAD"]


def test_oversize_stream_without_a_content_length(monkeypatch):
    origin = Origin()
    origin.put(DOC, b"%PDF-" + b"0" * 5000)
    original = origin.handler

    def handler(request):
        response = original(request)
        if request.method == "HEAD":
            return response
        headers = {k: v for k, v in response.headers.items() if k != "content-length"}
        return httpx.Response(200, headers=headers, content=response.content)

    monkeypatch.setattr(nad, "MAX_PDF_BYTES", 1000)
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    report = nad.run_stage(
        records_for(DOC), {}, client=client, config=CONFIG, pacer=lambda: None, now=lambda: NOW
    )
    assert report.counts["failure_oversize"] == 1


def test_requests_are_at_most_one_per_second():
    clock = FakeClock()
    stamps: list[float] = []
    pacer = Pacer(clock=clock.clock, sleep=clock.sleep)

    def mark():
        pacer()
        stamps.append(clock.now)

    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.put(SECOND, application_pdf())
    run(origin, records_for(DOC, SECOND), pacer=mark)
    assert len(stamps) == 4  # two HEADs and two GETs
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:], strict=False))


# --------------------------------------------------------------------------- bad documents


@pytest.mark.parametrize(
    ("body", "ctype", "code"),
    [
        (b"<html><script>x</script></html>", "application/pdf", "js_shell"),
        (b"%PDF-1.4 ok", "text/html", "js_shell"),
        (b"%PDF-1.4 ok", "application/zip", "wrong_content_type"),
        (b"GIF89a....", "application/pdf", "not_pdf_signature"),
    ],
)
def test_bad_documents_are_typed_failures_with_no_untrusted_text(body, ctype, code):
    origin = Origin()
    origin.put(DOC, body, ctype=ctype)
    report = run(origin, records_for(DOC))
    assert report.counts[f"failure_{code}"] == 1
    (rejection,) = report.rejections
    assert rejection["error_code"] == code and rejection["stage"] == "nmed_document"
    assert set(rejection["raw"]) <= {"stage", "pages"}
    assert str(rejection["raw"]).find("script") == -1
    assert DOC not in str(rejection)


def test_a_redirect_is_never_followed():
    origin = Origin()
    origin.put(DOC, b"%PDF-", status=302)
    report = run(origin, records_for(DOC))
    assert report.counts["failure_redirect_not_followed"] == 1
    assert [m for m, _ in origin.log] == ["HEAD"]


def test_404_is_absent_and_rechecked_after_a_week():
    origin = Origin()
    recs = records_for(DOC)
    report = run(origin, recs)
    assert report.counts["absent"] == 1 and report.rejections == []
    origin.log.clear()
    soon = run(origin, records_for(DOC), index=report.index, now=NOW + timedelta(days=1))
    assert origin.log == [] and soon.counts.get("checked", 0) == 0
    later = run(origin, records_for(DOC), index=report.index, now=NOW + timedelta(days=8))
    assert later.counts["checked"] == 1


def test_a_failure_never_replaces_an_accepted_document():
    origin = Origin()
    origin.put(DOC, application_pdf())
    first = records_for(DOC)
    report = run(origin, first)
    origin.put(DOC, b"<html>now a shell</html>", etag='"e2"')
    second = records_for(DOC)
    again = run(
        origin, second, prior=states_of(first), index=report.index, now=NOW + timedelta(days=1)
    )
    assert again.counts["failure_js_shell"] == 1
    assert second[0]["abstract"] == first[0]["abstract"]
    assert again.index["urls"][DOC]["status"] == "document"
    assert again.index["urls"][DOC]["last_failure"]["code"] == "js_shell"


def test_out_of_policy_records_are_never_requested():
    origin = Origin()
    bad = nad.record_for(DOC)
    bad["pdf_url"] = "https://example.com/x.pdf"
    report = run(origin, [bad])
    assert origin.log == [] and report.counts["in_scope"] == 0


# --------------------------------------------------------------------------- 429 / 503


def test_429_on_head_stops_the_stage_and_sets_not_before():
    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.put(SECOND, application_pdf())
    origin.head_status = 429
    report = run(origin, records_for(DOC, SECOND))
    assert report.counts["aborted_rate_limited"] == 1
    assert origin.methods() == ["HEAD"]  # the second document was never requested
    assert report.retry_after_seconds == 120
    assert report.index["not_before"] == (NOW + timedelta(seconds=120)).isoformat()
    assert [r["error_code"] for r in report.rejections] == ["http_status_429"]


def test_503_on_get_stops_with_retry_after_and_no_evidence():
    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.get_status = 503
    recs = records_for(DOC)
    report = run(origin, recs)
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 90
    assert nad.STATE_KEY not in recs[0] or recs[0].get("_document_base") is None


def test_no_request_is_made_until_not_before_passes():
    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.head_status = 429
    first = run(origin, records_for(DOC))
    origin.head_status = None
    origin.log.clear()
    resting = run(origin, records_for(DOC), index=first.index, now=NOW + timedelta(seconds=60))
    assert origin.log == [] and resting.counts["skipped_retry_after"] == 1
    assert resting.index["not_before"] == first.index["not_before"]
    after = run(origin, records_for(DOC), index=first.index, now=NOW + timedelta(seconds=500))
    assert after.counts["new"] == 1 and "not_before" not in after.index


def test_429_without_retry_after_rests_for_an_hour():
    origin = Origin()
    origin.put(DOC, application_pdf())
    original = origin.handler

    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(429)
        return original(request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    report = nad.run_stage(
        records_for(DOC), {}, client=client, config=CONFIG, pacer=lambda: None, now=lambda: NOW
    )
    assert report.index["not_before"] == (NOW + timedelta(seconds=3600)).isoformat()


# --------------------------------------------------------------------------- retry bookkeeping


def test_retryable_failures_count_attempts_and_rest_after_three(monkeypatch):
    origin = Origin()
    origin.put(DOC, application_pdf())
    monkeypatch.setattr(
        nad,
        "read_and_extract",
        lambda *a, **k: (_ for _ in ()).throw(nad.DocumentFailure("text_layer_worker_failed")),
    )
    index = None
    for day in range(3):
        report = run(origin, records_for(DOC), index=index, now=NOW + timedelta(days=day))
        index = report.index
        assert index["urls"][DOC]["retry"]["attempts"] == day + 1
    origin.log.clear()
    rested = run(origin, records_for(DOC), index=index, now=NOW + timedelta(days=4))
    assert rested.counts["backed_off"] == 1 and origin.methods() == ["HEAD"]
    changed_etag = Origin()
    changed_etag.put(DOC, application_pdf(), etag='"new"')
    woke = run(changed_etag, records_for(DOC), index=index, now=NOW + timedelta(days=4))
    assert woke.counts.get("backed_off", 0) == 0
