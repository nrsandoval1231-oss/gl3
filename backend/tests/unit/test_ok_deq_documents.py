"""Oklahoma DEQ permit-document stage: header lineage, fetch policy, change detection, limits.

No test touches the network: HTTP goes through httpx.MockTransport with DNS pinned to a public
address, and pacing uses a fake clock. PDFs are synthetic text pages.
"""

from __future__ import annotations

import dataclasses
import socket
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from _okdeq_fixtures import (
    BASE,
    GENERATORS,
    WEST_EDMOND_PROSE,
    Origin,
    listing_record,
    memo_pdf,
)

import gridlens.ingestion.adapters.ok_deq_documents as okd
import gridlens.ingestion.adapters.tceq_http as tceq_http
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ok_deq_memo import normalize_permit, parse_memo_header
from gridlens.ingestion.parsers.equipment import extract_equipment_claims
from gridlens.ingestion.registry import load_registry

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
REAL_PUBLIC_IP = tceq_http._public_ip
CONFIG = okd.StageConfig(max_downloads=3, max_checks=10, extract_seconds=120.0, isolate=False)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def run(origin, records, *, config=CONFIG, prior=None, index=None, now=NOW, **kwargs):
    return okd.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        index=index,
        pacer=kwargs.pop("pacer", lambda: None),
        now=lambda: now,
        **kwargs,
    )


def seeded(*keys, **kwargs):
    return dataclasses.replace(CONFIG, seed_keys=tuple(keys), **kwargs)


def west_edmond_origin(key=8406, **kwargs):
    origin = Origin()
    origin.put(key, memo_pdf(**kwargs))
    return origin


# --------------------------------------------------------------------------- header facts


def test_permit_numbers_normalize_to_the_listing_form():
    assert normalize_permit("2017-0987-C (M-2)") == "2017-0987-C M-2"
    assert normalize_permit("2017-0987-C  M2") == "2017-0987-C M-2"
    assert normalize_permit("2020-0510-TVR") == "2020-0510-TVR"
    assert normalize_permit("2022-0361-tvr4") == "2022-0361-TVR4"


@pytest.mark.parametrize(
    ("subject", "norm"),
    [
        ("2017-0987-C (M-2)", "2017-0987-C M-2"),
        ("2020-0510-TVR", "2020-0510-TVR"),
        ("2022-0361-TVR4", "2022-0361-TVR4"),
        ("2002-279-O (M-2)", "2002-279-O M-2"),
        ("2017-0446-TV (M-3)", "2017-0446-TV M-3"),
        ("2019-0668-AD", "2019-0668-AD"),
        ("2017-0987-C M-2", "2017-0987-C M-2"),
        ("2017-0987-C  M2", "2017-0987-C M-2"),
    ],
)
def test_header_reads_the_permit_number_with_a_verbatim_span(subject, norm):
    text = (
        "DRAFT\nMEMORANDUM June 3, 2021\nTO: Someone\n"
        f"SUBJECT:  Evaluation of Permit Application No. {subject}\n"
        "Acme Gas, LLC (SIC 1311/NAICS 211130).\n"
        "Facility:  Acme Compressor Station\nFacility ID:  1627 (SIC 1311)\nSection 1, 16N\n"
    )
    header = parse_memo_header(text)
    assert header.permit_norm == norm
    assert text[header.permit.start : header.permit.end] == header.permit.quote == subject
    assert header.memo_date.value == "2021-06-03"
    assert header.company.value == "Acme Gas, LLC"
    assert header.facility.value == "Acme Compressor Station"
    assert header.facility_id.value == "1627"


@pytest.mark.parametrize("subject", ["2017-0987-C (M-2a)", "2017-0987-C M-2a", "2017-0987-C (M-"])
def test_an_unparsed_amendment_suffix_is_unknown_not_the_base_permit(subject):
    text = (
        f"MEMORANDUM June 3, 2021\nSUBJECT:  Evaluation of Permit Application No. {subject}\nAcme\n"
    )
    header = parse_memo_header(text)
    assert header.permit is None and header.permit_norm is None


def test_header_without_a_readable_permit_number_is_unknown_not_guessed():
    text = "MEMORANDUM June 3, 2021\nSUBJECT: Evaluation of a permit\nAcme\n"
    header = parse_memo_header(text)
    assert header.permit is None and header.permit_norm is None and header.company is None
    # A number that only appears in prose, outside the SUBJECT line, is not used.
    prose = "MEMORANDUM June 3, 2021\nSUBJECT: Evaluation\nThis follows Permit No. 2001-100-C.\n"
    assert parse_memo_header(prose).permit is None


# --------------------------------------------------------------------------- West Edmond


def test_west_edmond_memo_yields_exactly_one_electric_compressor_claim_and_supply():
    origin = west_edmond_origin()
    record = listing_record()
    base_hash, base_abstract = record["source_hash"], record["abstract"]
    report = run(origin, [record], config=seeded(8406))
    assert report.rejections == [] and report.counts["new"] == 1
    state = record["okdeq_document"]
    assert state["permit_norm"] == "2017-0987-C M-2" and state["current_key"] == 8406
    document = state["document"]
    assert document["status"] == "extracted"
    assert document["memo"]["permit_number"]["quote"] == "2017-0987-C (M-2)"
    extraction = document["extraction"]
    claims = extract_equipment_claims(extraction["schedule_text"]).claims
    assert len(claims) == 1
    assert (claims[0].drive, claims[0].equipment_type, claims[0].count) == (
        "electric",
        "compressor",
        3,
    )
    claim = claims[0]
    assert (claim.rating, claim.unit, claim.rating_basis) == (
        Decimal("2500"),
        "hp",
        "mechanical_output",
    )
    assert not any(c.rating == Decimal("5200") for c in claims)
    # The driven compressors are supply with an unknown drive, never a demand claim.
    supply = {item["equipment_id"]: item for item in extraction["supply"]}
    assert {"C-0701", "C-0801", "C-0901"} <= set(supply)
    assert all(supply[i]["drive"] == "unknown" for i in ("C-0701", "C-0801", "C-0901"))
    assert extraction["demand_lines"] == 1
    # Per-line provenance carries page, offsets, verifier, document hash and the memo's file.
    (line,) = extraction["line_provenance"].values()
    assert line["verifier"] == "exact-span-v1" and line["page"] == 2
    assert line["document_hash"] == document["sha256"] and line["embedded_file"].endswith(
        "8406.pdf"
    )
    assert {"start", "end", "quote"} <= set(line)
    # Evidence fold: schedule text in the abstract, new hash, null published date.
    assert record["abstract"].startswith(base_abstract) and "Equipment ID" in record["abstract"]
    assert record["source_hash"] != base_hash
    assert record.get("publication_date") is None
    assert state["dates"]["memo_date"] == "2023-03-09" and state["dates"]["published_at"] is None
    assert "pp.2-2" in record["extraction_location"] and len(record["extraction_location"]) <= 100


def test_generator_memo_is_an_explicit_abstention_with_supply_only():
    origin = west_edmond_origin(body=[[GENERATORS]])
    record = listing_record()
    base_abstract = record["abstract"]
    run(origin, [record], config=seeded(8406))
    document = record["okdeq_document"]["document"]
    assert document["status"] == "no_equipment_schedule"
    assert document["abstain"]["reason"] == "no equipment schedule found"
    assert document["extraction"]["supply"][0]["equipment_type"] == "generator"
    assert record["abstract"] == base_abstract  # unknown is not zero, and nothing is added


def test_a_memo_with_no_equipment_text_is_a_notice_not_a_failure():
    origin = west_edmond_origin(body=[["Nothing about equipment appears on this page at all."]])
    report = run(origin, [listing_record()], config=seeded(8406))
    assert report.rejections == []
    assert [n["error_code"] for n in report.notices] == ["zero_verified_rows"]


# --------------------------------------------------------------------------- lineage


def test_same_permit_across_two_keys_links_versions_and_keeps_first_seen():
    origin = Origin()
    origin.put(8406, memo_pdf())
    record = listing_record()
    first = run(origin, [record], config=seeded(8406), now=NOW)
    state = record["okdeq_document"]
    assert [v["key"] for v in state["versions"]] == [8406]
    first_seen = state["versions"][0]["first_seen_at"]
    assert first_seen == NOW.isoformat()

    # A newer key carrying the same permit number is a new version and becomes current.
    revised = memo_pdf(body=[[WEST_EDMOND_PROSE.replace("three (3) 2,500-hp", "two (2) 2,500-hp")]])
    origin.put(8450, revised)
    later = NOW + timedelta(days=1)
    record2 = listing_record()
    second = run(
        origin,
        [record2],
        config=seeded(8406, 8450),
        prior={state["permit_norm"]: state},
        index=first.index,
        now=later,
    )
    new_state = record2["okdeq_document"]
    assert new_state["current_key"] == 8450 and new_state["document"]["key"] == 8450
    assert [v["key"] for v in new_state["versions"]] == [8406, 8450]
    assert new_state["versions"][0]["first_seen_at"] == first_seen  # never overwritten
    assert new_state["versions"][1]["first_seen_at"] == later.isoformat()
    assert second.counts.get("unchanged") == 1  # 8406 was not re-read

    # An older key found afterwards is added as a version without replacing the current one.
    origin.put(8300, memo_pdf(body=[["The facility has no new equipment in this older draft."]]))
    record3 = listing_record()
    run(
        origin,
        [record3],
        config=seeded(8406, 8450, 8300),
        prior={new_state["permit_norm"]: new_state},
        index=second.index,
        now=later,
    )
    final = record3["okdeq_document"]
    assert [v["key"] for v in final["versions"]] == [8300, 8406, 8450]
    assert final["current_key"] == 8450 and final["document"]["key"] == 8450


def test_a_document_for_a_permit_not_in_the_listing_is_indexed_but_joined_to_nothing():
    origin = west_edmond_origin(permit="2019-0001-O")
    record = listing_record()
    report = run(origin, [record], config=seeded(8406))
    assert report.counts["unjoined"] == 1 and "okdeq_document" not in record
    entry = report.index["keys"]["8406"]
    assert entry["permit"] == "2019-0001-O" and entry["status"] == "document"
    # When the permit later appears in the listing, the key is extracted (no states yet).
    later = listing_record(permit_no="2019-0001-O")
    run(origin, [later], config=seeded(8406), index=report.index)
    assert later["okdeq_document"]["permit_norm"] == "2019-0001-O"


def test_unverifiable_permit_number_is_recorded_unknown_and_not_joined():
    origin = west_edmond_origin(permit=None)
    record = listing_record()
    report = run(origin, [record], config=seeded(8406))
    assert "okdeq_document" not in record
    assert [n["error_code"] for n in report.notices] == ["unverified_permit_number"]
    assert report.rejections == [] and report.index["keys"]["8406"]["permit"] is None


# --------------------------------------------------------------------------- fetch policy


def test_html_shells_and_wrong_types_are_typed_failures_and_remembered():
    origin = Origin()
    origin.put(8001, b"<html><script>shell()</script></html>", ctype="text/html")
    origin.put(8002, b"%PDF-1.4 not really", ctype="text/plain")
    report = run(origin, [listing_record()], config=seeded(8001, 8002))
    assert sorted(r["error_code"] for r in report.rejections) == ["js_shell", "wrong_content_type"]
    assert origin.count("GET") == 0
    assert report.index["keys"]["8001"]["status"] == "failed"
    # A failed seed rests for a week; then the unchanged failure is recognised, not re-reported.
    rested = run(origin, [listing_record()], config=seeded(8001, 8002), index=report.index)
    assert rested.rejections == [] and origin.count("HEAD") == 2
    later = NOW + timedelta(days=8)
    again = run(
        origin, [listing_record()], config=seeded(8001, 8002), index=report.index, now=later
    )
    assert again.rejections == [] and again.counts["known_failed"] == 2
    # A 200 whose body is markup despite a PDF content type is also caught while streaming.
    origin.put(8003, b"<!DOCTYPE html><html>login</html>")
    third = run(origin, [listing_record()], config=seeded(8003))
    assert [r["error_code"] for r in third.rejections] == ["js_shell"]


def test_a_missing_key_is_absent_not_a_failure_and_is_not_rechecked_for_a_week():
    origin = Origin()
    report = run(origin, [listing_record()], config=seeded(8200))
    assert report.rejections == [] and report.counts["absent"] == 1
    assert report.index["keys"]["8200"]["status"] == "absent"
    run(origin, [listing_record()], config=seeded(8200), index=report.index, now=NOW)
    assert origin.count("HEAD") == 1
    run(
        origin,
        [listing_record()],
        config=seeded(8200),
        index=report.index,
        now=NOW + timedelta(days=8),
    )
    assert origin.count("HEAD") == 2


def test_oversize_by_header_and_by_stream(monkeypatch):
    origin = west_edmond_origin()
    monkeypatch.setattr(okd, "MAX_PDF_BYTES", 500)
    report = run(origin, [listing_record()], config=seeded(8406))
    assert [r["error_code"] for r in report.rejections] == ["oversize"]
    assert origin.count("GET") == 0
    # No Content-Length: the running count catches it.
    big = Origin()
    big.put(9, b"%PDF-1.4\n" + b"x" * 2000)
    big.docs[9]["body"] = big.docs[9]["body"]

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": "application/pdf"}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, headers=headers, content=big.docs[9]["body"])

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    stream_report = okd.run_stage(
        [listing_record()], {}, client=client, config=seeded(9), pacer=lambda: None, now=lambda: NOW
    )
    assert [r["error_code"] for r in stream_report.rejections] == ["oversize"]


def test_key_urls_are_policy_checked_before_any_request():
    origin = Origin()
    client = origin.client()
    for bad in (
        "http://applications.deq.ok.gov/permitspublic/storedpermits/1.pdf",
        "https://evil.example/permitspublic/storedpermits/1.pdf",
        "https://applications.deq.ok.gov/permitspublic/storedpermits/1.pdf?x=1",
        "https://applications.deq.ok.gov/permitspublic/storedpermits/../x.pdf",
        "https://applications.deq.ok.gov/permitspublic/storedpermits/abc.pdf",
        "https://applications.deq.ok.gov/permitspublic/storedpermits/1234567.pdf",
        "https://applications.deq.ok.gov:8443/permitspublic/storedpermits/1.pdf",
    ):
        with pytest.raises(SourceParseError):
            with okd.open_document(client, bad):
                pass
    assert origin.log == []
    with okd.open_document(client, BASE + "8406.pdf", method="HEAD") as response:
        assert response.status_code == 404
    assert origin.log[0][1] == BASE + "8406.pdf"


def test_redirect_is_a_visible_typed_failure_and_never_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://login.example/shell"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    report = okd.run_stage(
        [listing_record()], {}, client=client, config=seeded(7), pacer=lambda: None, now=lambda: NOW
    )
    assert [r["error_code"] for r in report.rejections] == ["redirect_not_followed"]


def test_requests_are_paced_to_one_per_second():
    origin = Origin()
    origin.put(8406, memo_pdf())
    origin.put(8407, memo_pdf(permit="2019-0001-O"))
    pacer = okd.Pacer(clock=origin.fake.clock, sleep=origin.fake.sleep)
    client = origin.client()
    okd.run_stage(
        [listing_record()],
        {},
        client=client,
        config=seeded(8406, 8407),
        pacer=pacer,
        now=lambda: NOW,
    )
    gaps = [b - a for a, b in zip(origin.times, origin.times[1:], strict=False) if b != a]
    assert len(origin.times) >= 4 and all(gap >= 1.0 - 1e-9 for gap in gaps)
    assert len({round(t, 6) for t in origin.times}) == len(origin.times)  # never two at once


# --------------------------------------------------------------------------- change detection


def test_unchanged_documents_are_skipped_and_the_rerun_is_idempotent():
    origin = west_edmond_origin()
    first_record = listing_record()
    first = run(origin, [first_record], config=seeded(8406))
    assert origin.count("GET") == 1
    state = first_record["okdeq_document"]
    replay_record = listing_record()
    replay = run(
        origin,
        [replay_record],
        config=seeded(8406),
        prior={state["permit_norm"]: state},
        index=first.index,
        now=NOW + timedelta(hours=24),
    )
    assert origin.count("GET") == 1 and replay.counts["unchanged"] == 1
    assert replay_record["source_hash"] == first_record["source_hash"]
    assert replay_record["abstract"] == first_record["abstract"]
    assert replay.index["keys"]["8406"]["sha256"] == first.index["keys"]["8406"]["sha256"]


def test_changed_validators_with_the_same_bytes_are_unchanged_by_hash():
    origin = west_edmond_origin()
    first_record = listing_record()
    first = run(origin, [first_record], config=seeded(8406))
    state = first_record["okdeq_document"]
    origin.put(8406, memo_pdf(), etag='"e2"')
    record = listing_record()
    replay = run(
        origin,
        [record],
        config=seeded(8406),
        prior={state["permit_norm"]: state},
        index=first.index,
    )
    assert replay.counts["unchanged_by_hash"] == 1 and "new" not in replay.counts
    assert record["source_hash"] == first_record["source_hash"]
    assert replay.index["keys"]["8406"]["validators"]["etag"] == '"e2"'


def test_changed_bytes_replace_the_document_and_keep_the_version_first_seen():
    origin = west_edmond_origin()
    first_record = listing_record()
    first = run(origin, [first_record], config=seeded(8406))
    state = first_record["okdeq_document"]
    origin.put(
        8406, memo_pdf(body=[[WEST_EDMOND_PROSE.replace("three (3)", "two (2)")]]), etag='"e2"'
    )
    record = listing_record()
    run(
        origin,
        [record],
        config=seeded(8406),
        prior={state["permit_norm"]: state},
        index=first.index,
        now=NOW + timedelta(days=2),
    )
    new_state = record["okdeq_document"]
    assert new_state["document"]["sha256"] != state["document"]["sha256"]
    (version,) = new_state["versions"]
    assert version["first_seen_at"] == NOW.isoformat()
    assert version["replaced_sha256"] == [state["document"]["sha256"]]
    assert record["source_hash"] != first_record["source_hash"]


# --------------------------------------------------------------------------- stage limits


def test_the_first_429_or_503_stops_the_stage_and_reports_retry_after():
    origin = Origin()
    origin.put(1, memo_pdf())
    origin.put(2, memo_pdf())
    origin.put(3, memo_pdf())
    origin.head_status = 429
    report = run(origin, [listing_record()], config=seeded(1, 2, 3))
    assert origin.count("HEAD") == 1 and origin.count("GET") == 0
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 120
    assert [r["error_code"] for r in report.rejections] == ["http_status_429"]
    origin2 = Origin()
    origin2.put(1, memo_pdf(), status=503)
    origin2.put(2, memo_pdf())
    report2 = run(origin2, [listing_record()], config=seeded(1, 2))
    assert origin2.count("HEAD") == 1 and report2.counts["aborted_rate_limited"] == 1


def test_download_and_check_budgets_defer_work_visibly():
    origin = Origin()
    for key in (1, 2, 3):
        origin.put(key, memo_pdf(permit=f"2019-000{key}-O"))
    report = run(origin, [listing_record()], config=seeded(1, 2, 3, max_downloads=1, max_checks=2))
    assert origin.count("GET") == 1
    assert report.counts["deferred_check_budget"] == 1
    assert report.counts["deferred_download_budget"] == 1
    assert report.index["keys"]["2"]["status"] == "pending"  # seen, not read: still unfinished


def test_a_stage_deadline_without_time_for_a_request_defers_everything():
    origin = west_edmond_origin()
    record = listing_record()
    report = run(origin, [record], config=seeded(8406), deadline=time.monotonic() + 5.0)
    assert origin.log == [] and report.counts["deferred_deadline"] == 1
    assert "okdeq_document" not in record  # nothing retained, nothing invented


def test_environment_failures_are_retryable_with_capped_attempts(monkeypatch):
    origin = west_edmond_origin()
    calls = {"n": 0}

    def failing(*_a, **_k):
        calls["n"] += 1
        raise okd.DocumentFailure("text_layer_time_budget")

    monkeypatch.setattr(okd, "read_document", failing)
    index = None
    for attempt in range(1, 5):
        origin.fake.now += 1
        report = run(origin, [listing_record()], config=seeded(8406), index=index, now=NOW)
        index = report.index
        if attempt <= 3:
            assert calls["n"] == attempt
            assert index["keys"]["8406"]["retry"]["attempts"] == attempt
    # After 3 counted attempts the key rests; no fourth read happens.
    assert calls["n"] == 3 and report.counts["backed_off"] == 1
    # The rest ends after 7 days.
    run(origin, [listing_record()], config=seeded(8406), index=index, now=NOW + timedelta(days=8))
    assert calls["n"] == 4


def test_untrusted_exception_text_is_never_persisted(monkeypatch):
    origin = west_edmond_origin()

    def failing(*_a, **_k):
        raise okd.DocumentFailure("unreadable_stream", "SECRET-DETAIL from the response body")

    monkeypatch.setattr(okd, "read_document", failing)
    report = run(origin, [listing_record()], config=seeded(8406))
    persisted = repr((report.rejections, report.notices, report.index, report.counts))
    assert "SECRET-DETAIL" not in persisted


# --------------------------------------------------------------------------- probe


def probe_config(frontier=8400, max_probes=5, misses=2, **kwargs):
    return okd.StageConfig(
        max_downloads=3,
        max_checks=10,
        extract_seconds=120.0,
        isolate=False,
        probe_enabled=True,
        probe_frontier=frontier,
        max_probes=max_probes,
        max_misses=misses,
        **kwargs,
    )


def test_probe_is_capped_stops_after_consecutive_misses_and_advances_the_frontier():
    origin = Origin()
    origin.put(8402, memo_pdf(permit="2019-0001-O"))
    report = run(origin, [listing_record()], config=probe_config())
    probed = [url.rsplit("/", 1)[-1] for method, url in origin.log if method == "HEAD"]
    # 8401 miss, 8402 found (misses reset), 8403 and 8404 miss -> stop (2 consecutive).
    assert probed == ["8401.pdf", "8402.pdf", "8403.pdf", "8404.pdf"]
    assert report.index["frontier"] == 8402
    # The next run starts from the recorded frontier, not from the configured one.
    origin.log.clear()
    run(
        origin,
        [listing_record()],
        config=probe_config(frontier=8400),
        index=report.index,
        now=NOW + timedelta(days=8),
    )
    assert origin.log[0][1].endswith("8403.pdf")


def test_probe_never_exceeds_max_probes_even_when_every_key_exists():
    origin = Origin()
    for key in range(1, 40):
        origin.put(8400 + key, memo_pdf(permit=f"2019-{key:04d}-O"))
    report = run(origin, [listing_record()], config=probe_config(max_probes=3, misses=5))
    assert report.counts["probed"] == 3
    assert origin.count("HEAD") == 3


def test_probe_off_never_enumerates_and_needs_a_frontier_when_on():
    origin = Origin()
    origin.put(8401, memo_pdf())
    run(origin, [listing_record()], config=okd.StageConfig(isolate=False))
    assert origin.log == []  # no seeds, no probe, no index: no request at all
    base = load_query()["application_documents"]
    assert okd.valid_config(base)
    on = {**base, "probe": {**base["probe"], "enabled": True, "frontier": 0}}
    assert not okd.valid_config(on)  # an enabled probe must name where it starts


# --------------------------------------------------------------------------- config


def load_query():
    source = next(row for row in load_registry() if row["id"] == "oklahoma-deq-public-review")
    return source["query"]


def test_shipped_registry_entry_is_off_and_validated():
    source = next(row for row in load_registry() if row["id"] == "oklahoma-deq-public-review")
    raw = source["query"]["application_documents"]
    assert raw["enabled"] is False and raw["probe"]["enabled"] is False
    assert raw["data_center_page"]["enabled"] is False and raw["seed_keys"] == []
    assert okd.config_from_source(source) is None
    enabled = {
        **source,
        "query": {**source["query"], "application_documents": {**raw, "enabled": True}},
    }
    config = okd.config_from_source(enabled)
    assert config is not None and config.max_probes == 0 and config.seed_keys == ()


@pytest.mark.parametrize(
    "change",
    [
        {"max_downloads": 6},
        {"max_downloads": 0},
        {"max_checks": 61},
        {"extract_seconds": 59},
        {"extract_seconds": 901},
        {"enabled": "yes"},
        {"seed_keys": list(range(1, 52))},
        {"seed_keys": [1, 1]},
        {"seed_keys": [0]},
        {"seed_keys": [1_000_000]},
        {"seed_keys": ["8406"]},
        {"probe": {"enabled": False, "frontier": 0, "max_probes": 21, "max_misses": 3}},
        {"probe": {"enabled": False, "frontier": 0, "max_probes": 5, "max_misses": 6}},
        {"probe": {"enabled": False, "frontier": 0, "max_probes": 5}},
        {"data_center_page": {"enabled": True, "extra": 1}},
        {"unknown": 1},
    ],
)
def test_registry_rejects_unbounded_or_malformed_stage_config(change, tmp_path):
    import json

    from gridlens.ingestion.registry import REGISTRY_PATH

    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    source = next(row for row in raw["sources"] if row["id"] == "oklahoma-deq-public-review")
    source["query"]["application_documents"] = {
        **source["query"]["application_documents"],
        **change,
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(path)


def test_in_process_failures_surface_as_typed_text_layer_failures():
    origin = Origin()
    origin.put(5, b"%PDF-1.4\nthis is not a real pdf at all")
    report = run(origin, [listing_record()], config=seeded(5))
    assert len(report.rejections) == 1
    assert report.rejections[0]["error_code"].startswith("text_layer_")
    raw = report.rejections[0]["raw"]
    assert set(raw) <= {"stage"}  # only codes and small numbers


# --------------------------------------------------------------------------- isolated child


def test_the_real_isolated_child_path_reads_a_memo():
    origin = west_edmond_origin()
    record = listing_record()
    config = dataclasses.replace(CONFIG, seed_keys=(8406,), isolate=True)
    report = run(origin, [record], config=config)
    assert report.rejections == [] and record["okdeq_document"]["current_key"] == 8406


# --------------------------------------------------------------------------- data-center page

DOCS = "/content/dam/ok/en/deq/documents/executive-offices/"
_HEAD = """<html><body>
<table id="adt-manual"><thead><tr><th>Agency</th><th>Jurisdiction</th></tr></thead>
<tbody><tr><td>DEQ</td><td>Air</td></tr></tbody></table>
<table id="adt-manual"><thead><tr><th>DIV</th><th>COUNTY</th><th>COMPANY</th><th>FACILITY</th>
<th>PERMIT TYPE</th><th>STATUS</th><th>LINK</th></tr></thead><tbody>
"""


def _dc_row(company: str, facility: str, href: str) -> str:
    return (
        f"<tr><td><p>AQD</p></td><td><p>X</p></td><td><p>{company}</p></td>"
        f"<td><p>{facility}</p></td><td><p>MINOR</p></td><td><p>ISSUED</p></td>"
        f'<td><a href="{href}">LINK</a></td></tr>\n'
    )


DC_PAGE = (
    _HEAD
    + _dc_row("MIDDLE<br /> MILE<br /> LLC", "ROLAND OK", DOCS + "2021-0235-C%20M-2.pdf")
    + _dc_row("SOLARITY", "SOLARITY POWER", DOCS + "Stillwater%20Data%20Center%20Permit.pdf")
    + _dc_row("EVIL", "F", "https://evil.example/content/dam/ok/en/deq/documents/a/2021-0235-C.pdf")
    + _dc_row("ACME", "ACME COMPRESSOR STATION", DOCS + "2017-0987-C%20M-2.pdf")
    + "</tbody></table></body></html>"
)
PAGE_URL = "https://oklahoma.gov/deq/deq-information-on-data-centers.html"


def test_data_center_page_rows_carry_provenance_and_unsafe_links_are_dropped():
    from gridlens.ingestion.adapters import ok_deq_data_center_page as page

    rows = page.parse_page(DC_PAGE.encode())
    assert [r["company"] for r in rows] == ["MIDDLE MILE LLC", "SOLARITY", "EVIL", "ACME"]
    assert rows[0]["permit_norm"] == "2021-0235-C M-2" and rows[0]["permit_basis"] == (
        "from link file name"
    )
    assert rows[0]["document_url"].startswith("https://oklahoma.gov/content/dam/")
    assert rows[1]["permit_norm"] is None and rows[1]["document_url"] is not None
    assert rows[2]["document_url"] is None and rows[2]["permit_norm"] is None
    with pytest.raises(SourceParseError):
        page.parse_page(b"<html><table><tr><th>A</th></tr></table></html>")


def test_data_center_page_is_joined_by_permit_number_as_discovery_and_supply_context():
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (200, {"content-type": "text/html; charset=utf-8"}, DC_PAGE.encode())
    record = listing_record()
    other = listing_record(permit_no="2021-0235-C M-2", facility="ROLAND OK")
    base = other["source_hash"]
    config = seeded(8406, data_center_page=True)
    report = run(origin, [record, other], config=config)
    assert report.rejections == [] and report.counts["data_center_rows"] == 4
    # The West Edmond-style row joins the page row for 2017-0987-C M-2 AND its memo.
    assert record["okdeq_document"]["data_center_page"]["rows"][0]["facility"] == (
        "ACME COMPRESSOR STATION"
    )
    block = other["okdeq_document"]["data_center_page"]
    assert (
        block["role"] == "discovery_and_supply_context"
        and "document" not in other["okdeq_document"]
    )
    assert "Equipment ID" not in other["abstract"]  # the page never contributes demand
    assert other["source_hash"] != base
    # A failed page fetch keeps the retained block instead of flapping the evidence hash.
    origin.other.clear()
    retained = other["okdeq_document"]
    again = listing_record(permit_no="2021-0235-C M-2", facility="ROLAND OK")
    failed = run(
        origin, [again], config=config, prior={"2021-0235-C M-2": retained}, index=report.index
    )
    assert [r["error_code"] for r in failed.rejections] == ["http_status_404"]
    assert again["source_hash"] == other["source_hash"]


def test_data_center_page_is_one_request_and_off_by_default():
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (200, {"content-type": "text/html"}, DC_PAGE.encode())
    run(origin, [listing_record()], config=seeded(8406))
    assert not any("oklahoma.gov" in url for _, url in origin.log)
    run(origin, [listing_record()], config=seeded(8406, data_center_page=True))
    assert sum("oklahoma.gov" in url for _, url in origin.log) == 1


def test_a_rate_limited_page_stops_the_whole_stage():
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (429, {"retry-after": "90"}, b"")
    report = run(origin, [listing_record()], config=seeded(8406, data_center_page=True))
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 90
    assert origin.count("HEAD") == 0


def test_probe_without_head_support_does_not_run_the_frontier_past_unconfirmed_keys():
    origin = Origin()
    origin.head_status = 405  # the server rejects HEAD, so only a GET can confirm a key
    origin.put(8406, memo_pdf())
    config = probe_config(frontier=8405, max_probes=10, misses=3)
    config = dataclasses.replace(config, max_downloads=1)
    report = run(origin, [listing_record()], config=config)
    assert report.index["frontier"] == 8406  # confirmed by a completed read, not beyond
    assert set(report.index["keys"]) == {"8406"}  # no pending entry for an unconfirmed key
    assert origin.count("GET") == 1


# --------------------------------------------------------------------------- review fixes


def test_page_fetch_pins_dns_and_a_private_resolving_host_is_refused(monkeypatch):
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (200, {"content-type": "text/html"}, DC_PAGE.encode())
    monkeypatch.setattr(tceq_http, "_public_ip", REAL_PUBLIC_IP)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    report = run(origin, [listing_record()], config=seeded(8406, data_center_page=True))
    assert [r["error_code"] for r in report.rejections][0] == "url_policy"
    assert not any("oklahoma.gov" in url for _, url in origin.log)  # no request was made
    # A public answer is pinned: the connection goes to the IP with the real Host header.
    seen = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.4.4", 443))])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["host"]))
        return httpx.Response(200, headers={"content-type": "text/html"}, content=DC_PAGE.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    okd.fetch_data_center_page(client, lambda: None)
    assert seen == [("8.8.4.4", "oklahoma.gov")]


def test_overlong_page_cells_reject_the_row():
    from gridlens.ingestion.adapters import ok_deq_data_center_page as page

    long_row = _dc_row("X" * 201, "F", DOCS + "2021-0235-C.pdf")
    body = _HEAD + long_row + _dc_row("OK", "F", DOCS + "2021-0236-C.pdf") + "</tbody></table>"
    rows, rejected = page.parse_page_checked(body.encode())
    assert rejected == 1 and [r["company"] for r in rows] == ["OK"]
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (200, {"content-type": "text/html"}, body.encode())
    report = run(origin, [listing_record()], config=seeded(8406, data_center_page=True))
    assert report.counts["data_center_rows_rejected"] == 1


def test_a_disabled_page_drops_the_stale_block_and_rate_limit_identity_names_the_page():
    origin = west_edmond_origin()
    origin.other[PAGE_URL] = (200, {"content-type": "text/html"}, DC_PAGE.encode())
    first_record = listing_record()
    first = run(origin, [first_record], config=seeded(8406, data_center_page=True))
    state = first_record["okdeq_document"]
    assert "data_center_page" in state
    off = listing_record()
    run(origin, [off], config=seeded(8406), prior={state["permit_norm"]: state}, index=first.index)
    assert "data_center_page" not in off["okdeq_document"]
    limited = Origin()
    limited.other[PAGE_URL] = (429, {}, b"")
    report = run(limited, [listing_record()], config=seeded(8406, data_center_page=True))
    assert report.rejections[0]["identity"] == "data-center-page"


def test_retry_after_is_honoured_by_the_next_run():
    origin = Origin()
    origin.put(1, memo_pdf())
    origin.head_status = 429  # carries Retry-After: 120
    first = run(origin, [listing_record()], config=seeded(1))
    assert first.index["not_before"] == (NOW + timedelta(seconds=120)).isoformat()
    origin.log.clear()
    origin.head_status = None
    soon = run(
        origin,
        [listing_record()],
        config=seeded(1),
        index=first.index,
        now=NOW + timedelta(seconds=60),
    )
    assert origin.log == [] and soon.counts["skipped_retry_after"] == 1
    assert soon.index["not_before"] == first.index["not_before"]
    later = run(
        origin,
        [listing_record()],
        config=seeded(1),
        index=soon.index,
        now=NOW + timedelta(seconds=121),
    )
    assert origin.count("HEAD") == 1 and "not_before" not in later.index
    # No usable Retry-After: a default rest still applies.
    bare = Origin()
    bare.docs[1] = {
        "body": b"",
        "etag": "x",
        "ctype": "application/pdf",
        "status": 503,
        "last_modified": "x",
    }
    bare.docs[1]["status"] = 503
    report = run(bare, [listing_record()], config=seeded(1))
    assert "not_before" in report.index


def test_unverified_permit_seeds_are_revalidated_weekly():
    origin = west_edmond_origin(permit=None)
    first = run(origin, [listing_record()], config=seeded(8406))
    assert first.index["keys"]["8406"]["permit"] is None
    run(
        origin,
        [listing_record()],
        config=seeded(8406),
        index=first.index,
        now=NOW + timedelta(days=1),
    )
    assert origin.count("HEAD") == 1
    run(
        origin,
        [listing_record()],
        config=seeded(8406),
        index=first.index,
        now=NOW + timedelta(days=8),
    )
    assert origin.count("HEAD") == 2


def test_a_permit_quote_that_does_not_match_its_normalised_value_is_a_typed_failure(monkeypatch):
    origin = west_edmond_origin()
    real = okd.parse_memo_header

    def skewed(text, page_of):
        header = real(text, page_of)
        return dataclasses.replace(header, permit_norm="2017-0987-C M-9")

    monkeypatch.setattr(okd, "parse_memo_header", skewed)
    report = run(origin, [listing_record()], config=seeded(8406))
    assert [r["error_code"] for r in report.rejections] == ["header_quote_mismatch"]


def test_two_listing_rows_with_one_permit_number_are_ambiguous_and_skipped():
    origin = west_edmond_origin()
    one, two = listing_record(), listing_record()
    report = run(origin, [one, two], config=seeded(8406))
    assert [n["error_code"] for n in report.notices] == ["ambiguous_permit_number"]
    assert "okdeq_document" not in one and "okdeq_document" not in two
    assert report.counts["unjoined"] == 1


def test_identity_fields_follow_the_current_listing_row_without_changing_the_hash():
    origin = west_edmond_origin()
    first_record = listing_record(event_date="2026-10-04")
    first = run(origin, [first_record], config=seeded(8406))
    state = first_record["okdeq_document"]
    assert state["document"]["identity_check"]["facility_matches"] is True
    assert state["dates"]["listing_event_date"] == "2026-10-04"
    renamed = listing_record(facility="Totally Different Plant", event_date="2026-10-20")
    run(
        origin,
        [renamed],
        config=seeded(8406),
        prior={state["permit_norm"]: state},
        index=first.index,
    )
    check = renamed["okdeq_document"]["document"]["identity_check"]
    assert check["listing_facility"] == "Totally Different Plant" and not check["facility_matches"]
    assert renamed["okdeq_document"]["dates"]["listing_event_date"] == "2026-10-20"
    # The content digest ignores those listing-derived fields (replaying the snapshot is stable).
    again = listing_record(event_date="2026-10-04")
    run(
        origin,
        [again],
        config=seeded(8406),
        prior={state["permit_norm"]: renamed["okdeq_document"]},
        index=first.index,
    )
    assert again["source_hash"] == first_record["source_hash"]
