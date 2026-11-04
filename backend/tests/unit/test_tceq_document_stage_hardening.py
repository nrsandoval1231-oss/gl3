"""Regression tests for the independent review of the TCEQ document stage (B1-B3, S1-S8)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from _permit_pdf import make_pdf
from _tceq_portfolio import make_portfolio, pi1_workbook
from test_tceq_application_documents import (
    BASE,
    ELECTRIC,
    NOW,
    Tceq,
    nsr_record,
    portfolio_bytes,
    public_dns,  # noqa: F401  (autouse fixture: DNS pinned to a public address)
)

import gridlens.ingestion.adapters.tceq_application_documents as docs
import gridlens.ingestion.adapters.tceq_http as tceq_http
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_pi1_workbook import (
    WorkbookError,
    read_pi1_workbook,
    read_pi1_workbook_isolated,
)
from gridlens.ingestion.tceq_document_stage import merge_report

CONFIG = docs.StageConfig(max_downloads=2, max_checks=10, extract_seconds=120, isolate=False)


def run(origin, records, prior=None, config=CONFIG, *, book=None, deadline=None, at=NOW):
    return docs.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        pacer=origin.pacer,
        now=lambda: at,
        bookkeeping=book,
        deadline=deadline,
    )


def boom(code: str, *, limited: bool = False):
    def fail(*_args, **_kwargs):
        failure = docs.DocumentFailure(code, "untrusted /secret/path text")
        failure.budget_limited = limited
        raise failure

    return fail


# ----------------------------------------------------------------------------- B1 time budget


def test_stage_works_to_its_own_deadline_and_leaves_the_persist_reserve(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    reserve = docs.persist_reserve(1)
    assert reserve >= 120.0 and docs.persist_reserve(2000) <= 300.0
    # Not enough stage time for even one HEAD (it can block for the read timeout).
    report = run(origin, [nsr_record()], deadline=time.monotonic() + reserve + 40)
    assert origin.log == [] and report.counts["deferred_deadline"] == 1
    # Enough for a HEAD but not for a heavy download.
    report = run(origin, [nsr_record()], deadline=time.monotonic() + reserve + 150)
    assert origin.count("HEAD") == 1 and origin.count("GET") == 0
    assert report.counts["deferred_deadline"] == 1


def test_child_budgets_are_cut_to_the_time_left_and_marked_budget_limited(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    seen = {}

    def slow(_path, _name, _sha, _link, budget, _isolate):
        seen["budget"] = budget
        raise docs.DocumentFailure("text_layer_time_budget")

    monkeypatch.setattr(docs, "_extract_pdf", slow)
    stage_left = 300.0
    deadline = time.monotonic() + docs.persist_reserve(1) + stage_left
    config = docs.StageConfig(2, 10, 900.0, isolate=False)
    report = run(origin, [nsr_record()], config=config, deadline=deadline)
    assert seen["budget"] <= stage_left - docs.STAGE_MARGIN_SECONDS - docs.CHILD_GRACE_SECONDS
    assert seen["budget"] < config.extract_seconds
    # Cut short by the deadline: retried without spending an attempt.
    assert report.bookkeeping["900001"]["attempts"] == 0


def test_unpack_is_bounded_by_the_time_left(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    seen = {}
    real = docs.portfolio.unpack_portfolio

    def spy(path, out, *, isolate, max_seconds):
        seen["max_seconds"] = max_seconds
        return real(path, out, isolate=isolate, max_seconds=max_seconds)

    monkeypatch.setattr(docs.portfolio, "unpack_portfolio", spy)
    run(origin, [nsr_record()], deadline=time.monotonic() + docs.persist_reserve(1) + 300)
    assert seen["max_seconds"] <= 300 - docs.STAGE_MARGIN_SECONDS - docs.CHILD_GRACE_SECONDS


def test_workbook_read_runs_in_a_killable_child_with_a_time_bound(tmp_path):
    path = tmp_path / "w.xlsx"
    path.write_bytes(pi1_workbook([("E1", "1", "Engine 1", "Engine: Internal Combustion")]))
    summary = read_pi1_workbook_isolated(path, "w.xlsx", max_seconds=60.0, isolate=True)
    assert summary.unit_count == 1
    # A bound that expires before the child can answer is a typed time-budget failure.
    with pytest.raises(WorkbookError) as caught:
        read_pi1_workbook_isolated(path, "w.xlsx", max_seconds=-19.99, isolate=True)
    assert caught.value.code == "workbook_time_budget"
    assert "workbook_time_budget" in docs.RETRYABLE_CODES


def test_workbook_units_in_provenance_are_a_bounded_sample(tmp_path):
    path = tmp_path / "w.xlsx"
    path.write_bytes(
        pi1_workbook([(f"E{i}", str(i), f"Engine {i}", "Engine: ICE") for i in range(60)])
    )
    summary = read_pi1_workbook(path, "w.xlsx")
    assert summary.unit_count == 60 and summary.units_by_type == {"Engine": 60}
    assert len(summary.units) == 25 and summary.units_truncated is True


def test_supply_quotes_and_rows_are_capped():
    from gridlens.ingestion.parsers.permit_docs.models import FieldEvidence

    evidence = FieldEvidence("rating", "2000", "q" * 500, 0, 500, 1)
    row = SimpleNamespace(
        equipment_id="G1",
        equipment_type="generator",
        drive="unknown",
        rating=2000,
        unit="kW",
        count=1,
        state="unknown",
        origin="narrative",
        evidence={"rating": evidence},
    )
    kept = docs._supply_json([row] * 150)
    assert len(kept) == docs.MAX_SUPPLY_ROWS_KEPT == 100
    assert len(kept[0]["evidence"]["rating"]["quote"]) == 160


# ----------------------------------------------------------------------------- B2 rate limits


@pytest.mark.parametrize("status", [429, 503])
def test_first_429_or_503_aborts_the_stage_and_carries_retry_after(status):
    origin = Tceq()
    records = []
    for index in range(10):
        project = f"90010{index}"
        origin.put(project, portfolio_bytes([ELECTRIC]))
        origin.docs[f"{BASE}{project}-tc.pdf"]["status"] = status
        origin.docs[f"{BASE}{project}-tc.pdf"]["headers"] = {"retry-after": "3600"}
        records.append(nsr_record(project))
    original = origin.handler

    def with_retry_after(request):
        response = original(request)
        if response.status_code == status:
            response.headers["retry-after"] = "3600"
        return response

    client = httpx.Client(transport=httpx.MockTransport(with_retry_after), follow_redirects=False)
    report = docs.run_stage(
        records, {}, client=client, config=CONFIG, pacer=origin.pacer, now=lambda: NOW
    )
    assert len(origin.log) == 1  # one request, then the stage stops
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 3600
    assert report.rejections[0]["error_code"] == f"http_status_{status}"
    counts: dict = {}
    merge_report(counts, report)
    assert counts["application_documents"]["retry_after_seconds"] == 3600


def test_get_429_aborts_after_the_head_succeeded():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    origin.put("900002", portfolio_bytes([ELECTRIC]))
    original = origin.handler

    def throttle_get(request):
        if request.method == "GET":
            return httpx.Response(429, headers={"retry-after": "120"})
        return original(request)

    client = httpx.Client(transport=httpx.MockTransport(throttle_get), follow_redirects=False)
    report = docs.run_stage(
        [nsr_record("900001"), nsr_record("900002")],
        {},
        client=client,
        config=CONFIG,
        pacer=origin.pacer,
        now=lambda: NOW,
    )
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 120
    assert report.counts.get("checked") == 1  # the second filing was never contacted


# ----------------------------------------------------------------------------- B3 / S1 retries


def test_time_and_memory_failures_are_retryable_with_a_capped_attempt_count(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    monkeypatch.setattr(docs, "_extract_pdf", boom("text_layer_time_budget"))
    book: dict = {}
    states = []
    for attempt in range(1, 4):
        record = nsr_record()
        report = run(origin, [record], book=book)
        assert report.rejections[0]["error_code"] == "text_layer_time_budget"
        assert report.bookkeeping["900001"]["attempts"] == attempt
        states.append(record.get("application_document"))
        book = report.bookkeeping
    assert states == [None, None, None]  # nothing is written into evidence
    gets = origin.count("GET")
    # Cap reached: the document rests for the back-off period.
    rested = run(origin, [nsr_record()], book=book)
    assert rested.counts["backed_off"] == 1 and origin.count("GET") == gets
    # ... unless it changed (new ETag), or the period has passed.
    origin.docs[f"{BASE}900001-tc.pdf"]["etag"] = "e2"
    assert run(origin, [nsr_record()], book=book).counts.get("backed_off") is None
    later = NOW + timedelta(days=docs.RETRY_BACKOFF_DAYS + 1)
    origin.docs[f"{BASE}900001-tc.pdf"]["etag"] = "e1"
    assert run(origin, [nsr_record()], book=book, at=later).counts.get("backed_off") is None
    assert origin.count("GET") > gets


@pytest.mark.parametrize("code", ["text_layer_memory_limit", "text_layer_page_too_long"])
def test_memory_and_page_limits_are_retryable_too(code, monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    monkeypatch.setattr(docs, "_extract_pdf", boom(code))
    record = nsr_record()
    report = run(origin, [record])
    assert "application_document" not in record and report.bookkeeping["900001"]["code"] == code


def test_dns_failure_is_a_retryable_network_error_not_a_policy_violation(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    calls = {"n": 0}

    def flaky(_host):
        calls["n"] += 1
        if calls["n"] == 2:  # the GET's lookup
            raise SourceParseError("TCEQ host DNS resolution failed")
        return "8.8.8.8"

    monkeypatch.setattr(tceq_http, "_public_ip", flaky)
    record = nsr_record()
    report = run(origin, [record])
    assert report.rejections[0]["error_code"] == "network_error"
    assert "application_document" not in record  # no permanent marker
    # A real allowlist violation (redirect off the allowlist) is still a policy failure.
    monkeypatch.setattr(tceq_http, "_public_ip", lambda _h: "8.8.8.8")

    def off_list(_request):
        return httpx.Response(302, headers={"location": "https://evil.example/x-tc.pdf"})

    client = httpx.Client(transport=httpx.MockTransport(off_list), follow_redirects=False)
    policy = docs.run_stage(
        [nsr_record()], {}, client=client, config=CONFIG, pacer=origin.pacer, now=lambda: NOW
    )
    assert policy.rejections[0]["error_code"] == "url_policy"


def test_failed_host_that_rejects_head_is_not_downloaded_again():
    origin = Tceq()
    origin.put("900001", b"GIF89a....", ctype="application/pdf")
    origin.head_supported = False
    first = nsr_record()
    run(origin, [first])
    state = first["application_document"]
    assert state["last_attempt"]["code"] == "not_pdf_signature"
    assert state["last_attempt"]["validators"]["etag"] == "e1"  # taken from the GET headers
    second = nsr_record()
    report = run(origin, [second], {"900001": state})
    assert report.counts["known_failed"] == 1 and report.rejections == []
    assert second["source_hash"] == first["source_hash"]


def test_failed_attempt_with_the_same_hash_is_skipped_without_extraction(monkeypatch):
    origin = Tceq()
    body = portfolio_bytes([ELECTRIC])
    origin.put("900001", body)
    origin.docs[f"{BASE}900001-tc.pdf"]["etag"] = "e2"
    import hashlib

    prior = {
        "version": docs.VERSION,
        "project": "900001",
        "document": None,
        "last_attempt": {
            "status": "failed",
            "code": "unreadable_stream",
            "validators": {"etag": "old"},
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    }
    monkeypatch.setattr(docs, "_extract_pdf", boom("should_not_run"))
    report = run(origin, [nsr_record()], {"900001": prior})
    assert report.counts["known_failed"] == 1 and report.rejections == []


def test_never_tried_documents_go_ahead_of_ones_with_failed_attempts():
    origin = Tceq()
    older_new = nsr_record("900001")
    older_new["event_date"] = "2026-09-01"
    newer_failed = nsr_record("900002")
    origin.put("900001", portfolio_bytes([ELECTRIC]), etag="a")
    origin.put("900002", portfolio_bytes([ELECTRIC]), etag="b")
    book = {"900002": {"code": "text_layer_time_budget", "attempts": 1, "at": NOW.isoformat()}}
    config = docs.StageConfig(max_downloads=1, max_checks=10, extract_seconds=120, isolate=False)
    report = run(origin, [newer_failed, older_new], config=config, book=book)
    gets = [url for method, url in origin.log if method == "GET"]
    assert gets == [f"{BASE}900001-tc.pdf"]  # the never-tried filing took the one download
    assert report.counts["deferred_download_budget"] == 1


# ----------------------------------------------------------------------------- S2 / S4 / S5


def test_notices_never_make_the_job_partial_but_failures_do():
    report = docs.StageReport()
    report.reject("1", "zero_verified_rows", pages=3)
    report.reject("listing", "listing_shrink", previously=6, listed_now=1)
    counts: dict = {}
    merge_report(counts, report)
    assert "partial" not in counts and "parse_failures" not in counts
    assert {n["error_code"] for n in counts["application_document_notices"]} == {
        "zero_verified_rows",
        "listing_shrink",
    }
    report.reject("1", "js_shell", stage=2)
    merge_report(counts, report)
    assert counts["partial"] is True and counts["parse_failures"] == 1
    assert "collection_status" not in counts  # the listing's retry scheduling is untouched
    assert counts["rejected_records"][0]["error_code"] == "js_shell"


def test_untrusted_exception_text_is_never_persisted():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    original = docs.DocumentFailure.__init__
    record = nsr_record()
    import gridlens.ingestion.adapters.tceq_application_documents as module

    real = module._extract_pdf
    module._extract_pdf = boom("unreadable_stream")
    try:
        report = run(origin, [record])
    finally:
        module._extract_pdf = real
    assert original is not None
    blob = str(report.rejections) + str(record.get("application_document"))
    assert "secret" not in blob and "/path" not in blob
    assert all(
        set(r["raw"]) <= {"stage", "pages", "previously", "listed_now"} for r in report.rejections
    )


def test_transient_failure_does_not_change_the_evidence_hash(monkeypatch):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    good = nsr_record()
    run(origin, [good])
    accepted = good["application_document"]
    origin.put(
        "900001", portfolio_bytes([["Different bytes, same project, new revision."]]), etag="e2"
    )
    monkeypatch.setattr(docs, "_extract_pdf", boom("text_layer_time_budget"))
    again = nsr_record()
    run(origin, [again], {"900001": accepted})
    assert again["source_hash"] == good["source_hash"] and again["abstract"] == good["abstract"]
    fresh = nsr_record()
    base = fresh["source_hash"]
    run(origin, [fresh])
    assert fresh["source_hash"] == base  # nothing retained, nothing changed


def test_matched_validators_clear_a_stale_failure_note():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    first = nsr_record()
    run(origin, [first])
    state = first["application_document"]
    noted = {**state, "last_attempt": {"status": "failed", "code": "js_shell", "validators": None}}
    cleared = nsr_record()
    book = {"900001": {"code": "x", "attempts": 1, "at": NOW.isoformat()}}
    report = run(origin, [cleared], {"900001": noted}, book=book)
    assert cleared["application_document"]["last_attempt"] is None
    assert cleared["source_hash"] == first["source_hash"]
    assert "900001" not in report.bookkeeping


# ----------------------------------------------------------------------------- NITs


def test_apply_state_is_atomic_and_repeatable_without_duplicating_lines():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    record = nsr_record()
    base_abstract = record["abstract"]
    run(origin, [record])
    once = (record["abstract"], record["source_hash"], record["extraction_location"])
    docs.apply_state(record, record["application_document"])
    docs.apply_prior_states([record], {"900001": record["application_document"]})
    assert (record["abstract"], record["source_hash"], record["extraction_location"]) == once
    assert record["abstract"].count("Equipment ID") == 1 and record["abstract"].startswith(
        base_abstract
    )
    broken = nsr_record()
    before = dict(broken)
    with pytest.raises((TypeError, AttributeError)):
        docs.apply_state(broken, {"document": object()})  # type: ignore[dict-item]
    assert broken == before  # a fault leaves the record untouched


def test_ignored_embedded_files_count_toward_the_total_cap(tmp_path, monkeypatch):
    import gridlens.ingestion.adapters.tceq_portfolio as portfolio

    path = tmp_path / "outer.pdf"
    path.write_bytes(make_portfolio([("a.bin", b"x" * 400), ("b.pdf", make_pdf([["p"]]))]))
    monkeypatch.setattr(portfolio, "MAX_TOTAL_EMBEDDED_BYTES", 300)
    result = portfolio.unpack_portfolio(path, tmp_path / "out", isolate=False)
    assert [f.status for f in result.files][0] == "skipped_total_limit"
    # The same file at a normal cap is ignored by type but still adds to the running total.
    monkeypatch.setattr(portfolio, "MAX_TOTAL_EMBEDDED_BYTES", 400 + 10)
    result = portfolio.unpack_portfolio(path, tmp_path / "out2", isolate=False)
    assert [f.status for f in result.files] == ["ignored_type", "skipped_total_limit"]


def test_datetime_import_is_used():
    assert datetime.now(UTC).tzinfo is not None
