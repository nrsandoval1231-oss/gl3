"""TCEQ application-document stage: unpack, hostile input, fetch policy, change detection.

No test touches the network: HTTP goes through httpx.MockTransport with DNS pinned to a
public address, and the pacer uses a fake clock.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, date, datetime

import httpx
import pytest
from _permit_pdf import make_pdf
from _tceq_portfolio import make_portfolio, pi1_workbook

import gridlens.ingestion.adapters.tceq_application_documents as docs
import gridlens.ingestion.adapters.tceq_portfolio as portfolio
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_http import open_tceq_application
from gridlens.ingestion.adapters.tceq_nsr_pending import _record
from gridlens.ingestion.adapters.tceq_pi1_workbook import WorkbookError, read_pi1_workbook
from gridlens.ingestion.parsers.equipment import extract_equipment_claims

BASE = "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/"
ELECTRIC = [
    "The applicant will install three (3) 2,500-hp electric motor-driven compressors at the plant."
]
GENERATORS = ["The project will install four (4) 2,000-kW natural gas-fired generators."]
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.requests: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Tceq:
    """Mock TCEQ origin: per-URL body and validators, request log."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.log: list[tuple[str, str]] = []
        self.head_supported = True
        self.fake = FakeClock()
        self.pacer = docs.Pacer(clock=self.fake.clock, sleep=self.fake.sleep)

    def put(self, project: str, body: bytes, *, kind="tc", etag="e1", ctype="application/pdf"):
        self.docs[f"{BASE}{project}-{kind}.pdf"] = {
            "body": body,
            "etag": etag,
            "ctype": ctype,
            "status": 200,
            "last_modified": "Mon, 02 Nov 2026 10:00:00 GMT",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.fake.requests.append(self.fake.now)
        url = f"https://{request.headers['host']}{request.url.path}"
        self.log.append((request.method, url))
        entry = self.docs.get(url)
        if entry is None:
            return httpx.Response(404)
        if entry["status"] != 200:
            return httpx.Response(entry["status"])
        headers = {
            "content-type": entry["ctype"],
            "etag": entry["etag"],
            "last-modified": entry["last_modified"],
            "content-length": str(len(entry["body"])),
        }
        if request.method == "HEAD":
            if not self.head_supported:
                return httpx.Response(405)
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, headers=headers, content=entry["body"])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)

    def count(self, method: str) -> int:
        return sum(1 for item in self.log if item[0] == method)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def nsr_record(project="900001", applicant="Prairie Example LLC", facility="PRAIRIE DATA CENTER"):
    row = {
        "project": project,
        "applicant": applicant,
        "facility": facility,
        "permits": [f"18{project[-4:]}"],
        "received": date(2026, 10, 14),
        "application_stage": "Technically Complete",
        "notice_url": f"https://www.tceq.texas.gov/notice#{project}",
        "application_url": f"{BASE}{project}-tc.pdf",
        "notice_href": f"/notice#{project}",
        "application_href": f"/assets/public/permitting/air/reports/applications/{project}-tc.pdf",
    }
    summary = {
        "city": "Abilene",
        "county": "Taylor",
        "purpose": "This permit will authorize onsite power generation for a data center.",
        "text": f"Plain language summary for permit {row['permits'][0]}.",
    }
    return _record(row, summary)


def portfolio_bytes(inner_pages: list[list[str]], workbooks=None) -> bytes:
    files: list[tuple[str, bytes]] = [
        ("0-READ THIS FIRST_ Extracting.pdf", make_pdf([["Read this first"]])),
        ("1-900001-tc.pdf", make_pdf(inner_pages)),
    ]
    files.extend(workbooks or [])
    return make_portfolio(files)


CONFIG = docs.StageConfig(max_downloads=2, max_checks=10, extract_seconds=120, isolate=False)


def run(origin: Tceq, records, prior=None, config=CONFIG):
    return docs.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        pacer=origin.pacer,
        now=lambda: NOW,
    )


# ----------------------------------------------------------------------------- unpack


def test_unpack_lists_manifest_hashes_and_writes_only_generated_names(tmp_path):
    workbook = pi1_workbook([("E1", "1", "Engine 1", "Engine: Internal Combustion Engine")])
    path = tmp_path / "outer.pdf"
    path.write_bytes(portfolio_bytes([ELECTRIC], [("20260101-01_workbook.xlsx", workbook)]))
    result = portfolio.unpack_portfolio(path, tmp_path / "out", isolate=False)
    assert result.failure is None and result.is_portfolio
    by_name = {item.name: item for item in result.files}
    assert set(by_name) == {
        "0-READ THIS FIRST_ Extracting.pdf",
        "1-900001-tc.pdf",
        "20260101-01_workbook.xlsx",
    }
    assert by_name["1-900001-tc.pdf"].kind == "pdf" and by_name["1-900001-tc.pdf"].sha256
    assert by_name["20260101-01_workbook.xlsx"].kind == "xlsx"
    written = sorted(item.name for item in (tmp_path / "out").iterdir())
    assert written == ["emb-000.pdf", "emb-001.pdf", "emb-002.xlsx"]
    assert all("path" not in entry for entry in result.manifest())


def test_unpack_isolated_child_matches_in_process(tmp_path):
    path = tmp_path / "outer.pdf"
    path.write_bytes(portfolio_bytes([ELECTRIC]))
    isolated = portfolio.unpack_portfolio(path, tmp_path / "a", isolate=True, max_seconds=60)
    direct = portfolio.unpack_portfolio(path, tmp_path / "b", isolate=False)
    assert isolated.failure is None
    assert [(f.name, f.sha256) for f in isolated.files] == [
        (f.name, f.sha256) for f in direct.files
    ]


def test_hostile_names_are_sanitised_and_never_become_paths(tmp_path):
    path = tmp_path / "outer.pdf"
    path.write_bytes(
        make_portfolio(
            [
                ("../../evil.pdf", make_pdf([["x"]])),
                ("C:\\Windows\\System32\\drop.xlsx", pi1_workbook([])),
                ("nul\x00byte.pdf", make_pdf([["x"]])),
                ("a" * 400 + ".pdf", make_pdf([["x"]])),
                ("run me.exe", b"MZ\x90\x00 not a program"),
            ]
        )
    )
    out = tmp_path / "out"
    result = portfolio.unpack_portfolio(path, out, isolate=False)
    assert len(result.files) == 5
    for item in result.files:
        assert "/" not in item.name and "\\" not in item.name and ".." not in item.name
        assert "\x00" not in item.name and len(item.name) <= 120
    assert any(item.name_changed for item in result.files)
    exe = next(item for item in result.files if item.name.endswith(".exe"))
    assert exe.status == portfolio.IGNORED and exe.path is None and exe.sha256
    produced = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert all(name == "outer.pdf" or name.startswith("out/emb-") for name in produced)


def test_type_follows_content_not_the_claimed_extension(tmp_path):
    path = tmp_path / "outer.pdf"
    path.write_bytes(
        make_portfolio(
            [("looks-like.pdf", b"<html>not a pdf</html>"), ("x.xlsx", b"%PDF-1.4 fake")]
        )
    )
    result = portfolio.unpack_portfolio(path, tmp_path / "out", isolate=False)
    assert [(f.kind, f.status) for f in result.files] == [("other", "ignored_type")] * 2


def test_embedded_count_size_and_total_caps(tmp_path, monkeypatch):
    path = tmp_path / "outer.pdf"
    small = make_pdf([["p"]])
    path.write_bytes(make_portfolio([(f"f{i:02d}.pdf", small) for i in range(5)]))
    monkeypatch.setattr(portfolio, "MAX_EMBEDDED_FILES", 3)
    result = portfolio.unpack_portfolio(path, tmp_path / "a", isolate=False)
    assert [f.status for f in result.files] == ["extracted"] * 3 + ["skipped_count_limit"] * 2
    monkeypatch.setattr(portfolio, "MAX_EMBEDDED_FILES", 64)
    monkeypatch.setattr(portfolio, "MAX_TOTAL_EMBEDDED_BYTES", len(small) * 2 + 1)
    result = portfolio.unpack_portfolio(path, tmp_path / "b", isolate=False)
    assert [f.status for f in result.files].count("skipped_total_limit") == 3
    monkeypatch.setattr(portfolio, "MAX_TOTAL_EMBEDDED_BYTES", 512 * 1024 * 1024)
    monkeypatch.setattr(portfolio, "MAX_EMBEDDED_FILE_BYTES", len(small) - 1)
    result = portfolio.unpack_portfolio(path, tmp_path / "c", isolate=False)
    assert {f.status for f in result.files} == {"skipped_oversize"}


def test_declared_size_over_the_cap_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio, "MAX_EMBEDDED_FILE_BYTES", 10_000)
    path = tmp_path / "outer.pdf"
    path.write_bytes(make_portfolio([("big.pdf", make_pdf([["p"]]))], declared={"big.pdf": 50_000}))
    result = portfolio.unpack_portfolio(path, tmp_path / "out", isolate=False)
    (item,) = result.files
    assert item.status == "skipped_oversize" and item.sha256 is None
    assert not list((tmp_path / "out").iterdir())


def test_unreadable_outer_file_is_a_typed_failure_and_plain_pdf_is_not_a_portfolio(tmp_path):
    path = tmp_path / "outer.pdf"
    path.write_bytes(b"%PDF-1.4\nnot really a pdf\n")
    result = portfolio.unpack_portfolio(path, tmp_path / "out", isolate=False)
    assert result.failure == "unreadable_stream" and result.files == []
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(make_pdf([["no attachments"]]))
    result = portfolio.unpack_portfolio(plain, tmp_path / "out2", isolate=False)
    assert result.failure is None and result.is_portfolio is False and result.files == []


# ----------------------------------------------------------------------------- workbook


def test_workbook_reports_unit_counts_with_cells_and_never_a_rating(tmp_path):
    path = tmp_path / "w.xlsx"
    path.write_bytes(
        pi1_workbook(
            [
                ("E1", "1", "Diesel Engine (each 685 kW/932 hp)", "Engine: Internal Combustion"),
                ("E2", "2", "Engine 2", "Engine: Internal Combustion Engine"),
                ("T1", "3", "Turbine 1", "Turbine: Simple Cycle, Natural Gas"),
            ],
            description=(
                "The proposed project includes the addition of 620 natural gas-fired generators "
                "to provide prime power to a data center, nominal 896 MW."
            ),
        )
    )
    summary = read_pi1_workbook(path, "w.xlsx")
    assert summary.unit_count == 3 and summary.units_by_type == {"Engine": 2, "Turbine": 1}
    first = summary.units[0]
    assert first["fin"] == "E1" and first["cell"] == "C11" and first["type_cell"] == "O12"
    assert summary.stated_counts[0]["count"] == 620
    assert summary.stated_counts[0]["sheet_cell"] == "General!C5"
    assert summary.stated_mw[0]["value"] == "896"
    assert summary.as_json()["basis"] == "documented"
    assert not {"rating", "hp", "kw", "mw"} & {
        key.lower() for unit in summary.units for key in unit
    }


def test_workbook_rejects_macros_zip_bombs_and_garbage(tmp_path, monkeypatch):
    macro = tmp_path / "m.xlsx"
    with zipfile.ZipFile(macro, "w") as archive:
        archive.writestr("[Content_Types].xml", "<x/>")
        archive.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(WorkbookError) as caught:
        read_pi1_workbook(macro, "m.xlsx")
    assert caught.value.code == "workbook_unsafe"
    garbage = tmp_path / "g.xlsx"
    garbage.write_bytes(b"PK\x03\x04 not a zip")
    with pytest.raises(WorkbookError) as caught:
        read_pi1_workbook(garbage, "g.xlsx")
    assert caught.value.code == "workbook_unreadable"
    good = tmp_path / "ok.xlsx"
    good.write_bytes(pi1_workbook([("E1", "1", "e", "Engine: x")]))
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.tceq_pi1_workbook.MAX_ZIP_UNCOMPRESSED_BYTES", 100
    )
    with pytest.raises(WorkbookError) as caught:
        read_pi1_workbook(good, "ok.xlsx")
    assert caught.value.code == "workbook_unsafe"


# ----------------------------------------------------------------------------- fetch policy


def test_discovery_uses_the_adapters_relevance_notion_and_newest_first():
    keep = nsr_record("900001")
    other = nsr_record("900002", applicant="Bakery LLC", facility="BAKERY EXPANSION")
    older = nsr_record("900003")
    older["event_date"] = "2026-09-01"
    links = docs.discover([older, other, keep, {"presence_only": True, "document_number": "x"}])
    assert [link.project for link in links] == ["900001", "900003"]
    assert links[0].kind == "tc" and links[0].url == f"{BASE}900001-tc.pdf"


@pytest.mark.parametrize(
    ("ctype", "body", "code"),
    [
        ("text/html", b"<html><script>window.location='/x'</script></html>", "js_shell"),
        ("application/pdf", b"<!DOCTYPE html><script>app()</script>", "js_shell"),
        ("application/json", b"{}", "wrong_content_type"),
        ("application/pdf", b"GIF89a....", "not_pdf_signature"),
    ],
)
def test_html_shell_and_wrong_types_are_visible_typed_failures(ctype, body, code):
    origin = Tceq()
    origin.put("900001", body, ctype=ctype)
    origin.head_supported = False  # exercise the streamed body classification as well
    record = nsr_record()
    report = run(origin, [record])
    assert report.rejections[0]["error_code"] == code
    assert report.rejections[0]["stage"] == "tceq_application_document"
    assert record["application_document"]["document"] is None
    assert record["application_document"]["last_attempt"]["code"] == code
    assert "Equipment ID" not in record["abstract"]


def test_oversize_from_header_and_from_a_stream_without_length(monkeypatch):
    origin = Tceq()
    origin.put("900001", make_pdf([["x"]]))
    monkeypatch.setattr(docs, "MAX_OUTER_BYTES", 50)
    assert run(origin, [nsr_record()]).rejections[0]["error_code"] == "oversize"
    assert origin.count("GET") == 0  # refused from the HEAD length

    streamed = Tceq()
    streamed.put("900001", make_pdf([["x"]]))
    streamed.head_supported = False
    original = streamed.handler

    def without_length(request: httpx.Request) -> httpx.Response:
        response = original(request)
        response.headers.pop("content-length", None)
        return response

    client = httpx.Client(transport=httpx.MockTransport(without_length), follow_redirects=False)
    report = docs.run_stage(
        [nsr_record()],
        {},
        client=client,
        config=CONFIG,
        pacer=streamed.pacer,
        now=lambda: NOW,
    )
    assert report.rejections[0]["error_code"] == "oversize"


def test_requests_are_paced_to_one_per_second_and_use_a_declared_agent():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    seen_agents: list[str] = []
    inner = origin.handler

    def spy(request: httpx.Request) -> httpx.Response:
        seen_agents.append(request.headers["user-agent"])
        return inner(request)

    client = httpx.Client(transport=httpx.MockTransport(spy), follow_redirects=False)
    docs.run_stage(
        [nsr_record()], {}, client=client, config=CONFIG, pacer=origin.pacer, now=lambda: NOW
    )
    times = origin.fake.requests
    assert len(times) == 2  # HEAD then GET
    assert times[0] - 1000.0 >= 1.0 and times[1] - times[0] >= 1.0
    assert set(seen_agents) == {docs.USER_AGENT}


def test_url_policy_rejects_other_hosts_and_redirects_off_the_allowlist():
    def evil(_request):
        return httpx.Response(302, headers={"location": "https://evil.example/x-tc.pdf"})

    client = httpx.Client(transport=httpx.MockTransport(evil), follow_redirects=False)
    with pytest.raises(SourceParseError), open_tceq_application(client, f"{BASE}900001-tc.pdf"):
        pass
    for url in (
        "http://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf",
        "https://www.tceq.texas.gov.evil.example/assets/public/permitting/air/reports/"
        "applications/1-tc.pdf",
        BASE + "1-tc.pdf?x=1",
        BASE + "../1-tc.pdf",
        BASE + "abc-tc.pdf",
        "https://records.tceq.texas.gov/assets/public/permitting/air/reports/applications/1-tc.pdf",
    ):
        with pytest.raises(SourceParseError), open_tceq_application(client, url):
            pass
    calls = {"n": 0}

    def hop(_request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(301, headers={"location": f"{BASE}900001-tc.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"})

    client = httpx.Client(transport=httpx.MockTransport(hop), follow_redirects=False)
    with open_tceq_application(client, f"{BASE}900002-tc.pdf") as response:
        assert response.status_code == 200 and calls["n"] == 2


# ----------------------------------------------------------------------------- change detection


def test_unchanged_document_is_skipped_changed_one_is_fetched_idempotent_rerun():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    first = nsr_record()
    report = run(origin, [first])
    assert report.counts["new"] == 1 and report.counts["downloads"] == 1
    state = first["application_document"]
    assert state["document"]["status"] == "extracted"

    # Same validators: HEAD only, no body fetch, byte-identical record.
    again = nsr_record()
    gets = origin.count("GET")
    report2 = run(origin, [again], {"900001": state})
    assert origin.count("GET") == gets and report2.counts["unchanged"] == 1
    assert again["source_hash"] == first["source_hash"] and again["abstract"] == first["abstract"]

    # New ETag, identical bytes: downloaded once, recognised by hash, validators refreshed.
    origin.docs[f"{BASE}900001-tc.pdf"]["etag"] = "e2"
    third = nsr_record()
    report3 = run(origin, [third], {"900001": state})
    assert report3.counts["unchanged_by_hash"] == 1
    assert third["application_document"]["document"]["sha256"] == state["document"]["sha256"]
    assert third["application_document"]["document"]["validators"]["etag"] == "e2"

    # Genuinely new bytes: re-extracted and a different evidence hash.
    origin.put("900001", portfolio_bytes([GENERATORS]), etag="e3")
    fourth = nsr_record()
    report4 = run(origin, [fourth], {"900001": third["application_document"]})
    assert report4.counts["updated"] == 1
    assert fourth["source_hash"] != first["source_hash"]
    assert "Equipment ID" not in fourth["abstract"]  # generator-only: abstain, not demand


def test_head_not_supported_falls_back_to_get_and_hash_comparison():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    origin.head_supported = False
    first = nsr_record()
    run(origin, [first])
    second = nsr_record()
    report = run(origin, [second], {"900001": first["application_document"]})
    assert report.counts["unchanged_by_hash"] == 1
    assert second["source_hash"] == first["source_hash"]


def test_download_and_check_budgets_defer_without_failing():
    origin = Tceq()
    records = []
    for index in range(1, 4):
        project = f"90000{index}"
        origin.put(project, portfolio_bytes([ELECTRIC]), etag=f"e{index}")
        records.append(nsr_record(project))
    config = docs.StageConfig(max_downloads=1, max_checks=2, extract_seconds=120, isolate=False)
    report = run(origin, records, config=config)
    assert report.counts["downloads"] == 1
    assert report.counts["deferred_download_budget"] == 1
    assert report.counts["deferred_check_budget"] == 1
    assert report.rejections == []


# ----------------------------------------------------------------------------- failures keep state


def test_failure_after_an_accepted_state_preserves_it_and_is_not_refetched():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    good = nsr_record()
    run(origin, [good])
    accepted = good["application_document"]

    origin.put("900001", b"<html><script>shell()</script></html>", ctype="text/html", etag="e9")
    bad = nsr_record()
    report = run(origin, [bad], {"900001": accepted})
    assert report.rejections[0]["error_code"] == "js_shell"
    assert bad["application_document"]["document"] == accepted["document"]  # preserved
    assert bad["application_document"]["last_attempt"]["code"] == "js_shell"
    assert bad["abstract"] == good["abstract"]  # the accepted schedule still stands

    gets = origin.count("GET")
    repeat = nsr_record()
    report2 = run(origin, [repeat], {"900001": bad["application_document"]})
    assert origin.count("GET") == gets and report2.rejections == []
    assert report2.counts["known_failed"] == 1 and report2.known_failed == ["900001"]
    assert repeat["source_hash"] == bad["source_hash"]


@pytest.mark.parametrize("status", [429, 503])
def test_retryable_http_failure_is_reported_but_leaves_no_failure_marker(status):
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC]))
    origin.docs[f"{BASE}900001-tc.pdf"]["status"] = status
    record = nsr_record()
    report = run(origin, [record])
    assert report.rejections[0]["error_code"] == f"http_status_{status}"
    assert "application_document" not in record  # nothing retained: retried next run


def test_portfolio_content_failures_are_typed(monkeypatch):
    origin = Tceq()
    origin.put("900001", make_portfolio([("readme.txt", b"hello")]))
    assert run(origin, [nsr_record()]).rejections[0]["error_code"] == "no_composite_pdf"

    scanned = Tceq()
    scanned.put("900001", portfolio_bytes([[""], [""]]))
    assert run(scanned, [nsr_record()]).rejections[0]["error_code"] == "empty_text_layer"

    garbage = Tceq()
    garbage.put("900001", b"%PDF-1.4\ngarbage")
    assert run(garbage, [nsr_record()]).rejections[0]["error_code"] == "unreadable_stream"

    capped = Tceq()
    capped.put("900001", portfolio_bytes([ELECTRIC]))
    monkeypatch.setattr(portfolio, "MAX_EMBEDDED_FILE_BYTES", 500)
    assert run(capped, [nsr_record()]).rejections[0]["error_code"] == "embedded_oversize"


def test_non_empty_document_with_zero_verified_rows_is_a_visible_notice_and_abstains():
    origin = Tceq()
    origin.put(
        "900001",
        portfolio_bytes(
            [["Section 1. Administrative information only, with no equipment tables or ratings."]]
        ),
    )
    record = nsr_record()
    report = run(origin, [record])
    assert report.rejections[0]["error_code"] == "zero_verified_rows"
    document = record["application_document"]["document"]
    assert document["status"] == "no_equipment_schedule"
    assert document["abstain"]["reason"] == "no equipment schedule found"
    assert "Equipment ID" not in record["abstract"] and "Company:" not in record["abstract"]
    assert document["manifest"]  # the manifest is recorded even with nothing found


def test_listing_shrink_is_a_typed_notice():
    origin = Tceq()
    prior = {str(900000 + i): {"document": {"sha256": "x", "validators": {}}} for i in range(1, 7)}
    report = run(origin, [nsr_record("900001")], prior)
    shrink = [r for r in report.rejections if r["error_code"] == "listing_shrink"]
    assert len(shrink) == 1 and shrink[0]["raw"] == {"previously": "6", "listed_now": "1"}


# ----------------------------------------------------------------------------- evidence shape


def test_evidence_shape_for_a_stated_electric_compressor_schedule():
    workbook = pi1_workbook(
        [
            ("G1", "1", "Generator 1", "Engine: Internal Combustion Engine"),
            ("G2", "2", "Generator 2", "Engine: Internal Combustion Engine"),
        ],
        description="Data center with two proposed natural gas generators.",
    )
    origin = Tceq()
    origin.put("900001", portfolio_bytes([ELECTRIC], [("20260101-01_workbook.xlsx", workbook)]))
    record = nsr_record()
    base_abstract = record["abstract"]
    base_hash = record["source_hash"]
    run(origin, [record])
    state = record["application_document"]
    document = state["document"]

    # The abstract carries a schedule the unchanged equipment parser accepts.
    parsed = extract_equipment_claims(record["abstract"])
    assert parsed.company == "Prairie Example LLC" and parsed.facility == "PRAIRIE DATA CENTER"
    assert parsed.issues == [] and len(parsed.claims) == 1
    (claim,) = parsed.claims
    assert (claim.drive, claim.unit, claim.count, claim.state) == ("electric", "hp", 3, "proposed")
    assert record["abstract"].startswith(base_abstract)
    assert record["source_hash"] != base_hash

    # Provenance: per-line spans, hashes, embedded file and verifier.
    extraction = document["extraction"]
    (line,) = extraction["line_provenance"].values()
    assert line["embedded_file"] == "1-900001-tc.pdf" and line["page"] == 1
    assert line["document_hash"] == extraction["file_sha256"]
    assert line["outer_sha256"] == document["sha256"] and line["verifier"] == "exact-span-v1"
    assert {"start", "end", "quote", "fields"} <= set(line)
    assert document["manifest"][0]["sha256"]
    roles = {entry["name"]: entry["role"] for entry in document["manifest"]}
    assert roles["1-900001-tc.pdf"] == "composite_pdf"
    assert roles["20260101-01_workbook.xlsx"] == "workbook_parsed"
    workbook_summary = document["workbooks"][0]
    assert workbook_summary["basis"] == "documented" and workbook_summary["unit_count"] == 2
    assert workbook_summary["units_by_type"] == {"Engine": 2}
    assert state["dates"]["listing_received"] == "2026-10-14"
    assert state["dates"]["published_at"] is None
    assert document["fetched_at"] == NOW.isoformat()

    # The location names the embedded file and page range within the column width.
    assert "1-900001-tc.pdf pp.1-1" in record["extraction_location"]
    assert len(record["extraction_location"]) <= 100
    json.dumps(state)  # JSON-safe
    assert base_abstract in record["abstract"]


def test_generator_only_portfolio_yields_supply_and_no_demand_lines():
    origin = Tceq()
    origin.put("900001", portfolio_bytes([GENERATORS]))
    record = nsr_record()
    base_abstract = record["abstract"]
    run(origin, [record])
    document = record["application_document"]["document"]
    assert record["abstract"] == base_abstract
    assert extract_equipment_claims(record["abstract"]).claims == []
    supply = document["extraction"]["supply"]
    assert supply and supply[0]["equipment_type"] == "generator" and supply[0]["unit"] == "kW"
    assert supply[0]["role"] == "supply_or_other" and supply[0]["evidence"]["rating"]["page"] == 1
    assert document["extraction"]["demand_lines"] == 0
    assert document["status"] == "no_equipment_schedule"
    assert document["abstain"]["supply_rows"] == len(supply)


def test_state_digest_ignores_fetch_time_only():
    state = {"document": {"fetched_at": "a", "sha256": "x"}, "last_attempt": None}
    other = {"document": {"fetched_at": "b", "sha256": "x"}, "last_attempt": None}
    changed = {"document": {"fetched_at": "a", "sha256": "y"}, "last_attempt": None}
    assert docs.state_digest(state) == docs.state_digest(other) != docs.state_digest(changed)


def test_registry_accepts_bounded_stage_and_rejects_loose_bounds(tmp_path):
    from gridlens.ingestion.registry import REGISTRY_PATH, load_registry

    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    source = next(s for s in raw["sources"] if s["id"] == "texas-tceq-nsr-pending")
    assert docs.config_from_source(source) == docs.StageConfig(2, 60, 420.0)
    for bad in (
        {"max_downloads": 0, "max_checks": 60, "extract_seconds": 420},
        {"max_downloads": 2, "max_checks": 500, "extract_seconds": 420},
        {"max_downloads": 2, "max_checks": 60, "extract_seconds": 5000},
        {"max_downloads": 2, "max_checks": 60},
        {"max_downloads": 2, "max_checks": 60, "extract_seconds": 420, "extra": 1},
    ):
        source["query"]["application_documents"] = bad
        path = tmp_path / "registry.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            load_registry(path)
