"""Workstream 5 sector and regulation sources: mock origins and small real-derived fixtures."""

import copy
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters import (
    afdc_stations,
    ercot_monthly,
    faa_oeaaa,
    msha_mines,
    nevi_awards,
    regulatory_events,
    sec_edgar_site_mw,
    sector_common,
    tceq_aggregate,
)
from gridlens.ingestion.adapters.diagnostics import acquisition_diagnostics
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import Pacer
from gridlens.ingestion.registry import load_registry

REAL_RESOLVE = sector_common.resolve_public
FIX = Path(__file__).parents[1] / "fixtures" / "ws5"
ROOT = Path(__file__).resolve().parents[3]
TODAY = date(2026, 10, 27)
WS5_IDS = [
    "faa-oeaaa-obstruction",
    "msha-mines",
    "texas-tceq-aggregate-production",
    "afdc-ev-stations",
    "texas-txdot-nevi-awards",
    "sec-edgar-site-mw",
    "texas-ercot-monthly-overview",
    "regulatory-event-feed",
]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Mock origins have fake hosts; the resolver guard has its own test."""
    monkeypatch.setattr(sector_common, "resolve_public", lambda _host: "8.8.8.8")


def source(source_id: str) -> dict:
    return copy.deepcopy(next(row for row in load_registry() if row["id"] == source_id))


def make_client(handler, requests: list | None = None) -> httpx.Client:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return handler(request)

    return httpx.Client(follow_redirects=False, transport=httpx.MockTransport(wrapped))


def fast_pacer() -> Pacer:
    return Pacer(clock=lambda: 0.0, sleep=lambda _s: None)


def pdf_bytes(text: str) -> bytes:
    flattened = " ".join(text.split())
    escaped = flattened.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 9 Tf 36 760 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(body)


# ---------------------------------------------------------------- registry and policy


def test_every_ws5_source_ships_off_and_validates():
    rows = {row["id"]: row for row in load_registry()}
    for source_id in WS5_IDS:
        assert rows[source_id]["enabled"] is False, source_id
        assert rows[source_id]["credential_reference"] is None


def test_registry_rejects_unbounded_or_wrong_ws5_queries():
    rows = load_registry()
    for source_id, mutate in {
        "msha-mines": lambda s: s["query"].update(max_uncompressed_bytes=10**9),
        "faa-oeaaa-obstruction": lambda s: s["query"].update(radius_m=10**6),
        "texas-tceq-aggregate-production": lambda s: s["query"].update(max_pages=99),
        "texas-ercot-monthly-overview": lambda s: s.update(cadence_hours=24),
        "sec-edgar-site-mw": lambda s: s["query"].update(ciks=["123"]),
        "afdc-ev-stations": lambda s: s["query"].update(states=["CA"]),
    }.items():
        broken = copy.deepcopy(next(r for r in rows if r["id"] == source_id))
        mutate(broken)
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"version": 1, "sources": [broken]}), encoding="utf-8")
            with pytest.raises(ValueError):
                load_registry(path)


def test_no_retired_nrel_host_remains_in_code_or_config():
    offenders = []
    for base in (ROOT / "backend" / "src", ROOT / "config"):
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".toml"}:
                if re.search(
                    r"https?://[\w.-]*nrel\.gov", path.read_text(encoding="utf-8", errors="ignore")
                ):
                    offenders.append(str(path))
    assert offenders == []
    assert afdc_stations.HOST == "developer.nlr.gov"
    assert "nrel" not in afdc_stations.ENDPOINT


def test_evidence_only_assessment_even_when_a_name_says_data_center():
    record = faa_oeaaa.build_record(
        {
            "asn": "2026-ASW-1-OE",
            "dateEntered": "2026-10-01",
            "dateCompleted": "2026-10-02",
            "sponsor": "Acme Data Center LLC",
            "structureType": "CRANE",
            "aglStructureHeight": "120",
            "nearestCity": "Plano",
            "nearestState": "TX",
            "latitude": "33.0",
            "longitude": "-96.7",
            "latLongAccuracy": "4D",
            "statusCode": "DET-DNE",
        },
        [{"campus_id": "C1", "name": "Campus one", "m": 400}],
    )
    result = assess_permit(record, as_of=TODAY)
    assert result["decision"] == "rejected"
    assert "stays evidence" in result["reason"]
    assert record["permit"]["data_center"] is False
    assert record["permit"]["power_signals"] == []


# ---------------------------------------------------------------- pacing and 429


def test_pacer_keeps_one_request_per_second():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    pacer = Pacer(clock=lambda: now[0], sleep=sleep)
    pacer.wait()
    now[0] += 0.25
    pacer.wait()
    pacer.wait()
    assert slept == [0.75, 1.0]
    assert pacer.requests == 3


def test_429_stops_the_run_and_the_worker_reads_retry_after():
    requests: list = []
    client = make_client(
        lambda r: httpx.Response(429, headers={"retry-after": "3600"}, content=b""), requests
    )
    cfg = source("texas-tceq-aggregate-production")
    with pytest.raises(httpx.HTTPStatusError) as caught:
        tceq_aggregate.retrieve(cfg, client, pacer=fast_pacer())
    assert len(requests) == 1
    info = acquisition_diagnostics(caught.value)
    assert info["error_code"] == "http_status_429"
    assert "retry_after_at" in info and (
        "retry_after_seconds" in info or info.get("retry_after_exceeds_bound")
    )


def test_redirect_is_never_followed_and_foreign_host_is_refused():
    requests: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    cfg = source("texas-tceq-aggregate-production")
    with pytest.raises(SourceParseError):
        tceq_aggregate.retrieve(cfg, make_client(handler, requests), pacer=fast_pacer())
    assert len(requests) == 1
    from gridlens.ingestion.adapters.sector_common import fetch

    with pytest.raises(SourceParseError):
        fetch(
            make_client(handler, requests),
            "https://evil.example/data",
            hosts={"data.texas.gov"},
            max_bytes=10,
            media_types={"application/json"},
            pacer=fast_pacer(),
        )
    assert len(requests) == 1  # the foreign host was refused before any request


def test_wrong_endpoint_or_id_is_refused_before_any_request():
    requests: list = []
    client = make_client(lambda r: httpx.Response(200, content=b"[]"), requests)
    cfg = source("texas-tceq-aggregate-production")
    cfg["endpoint"] = "https://data.texas.gov/resource/other.json"
    with pytest.raises(SourceParseError):
        tceq_aggregate.retrieve(cfg, client)
    assert requests == []


# ---------------------------------------------------------------- FAA


def faa_config(campuses: list, **query) -> dict:
    cfg = source("faa-oeaaa-obstruction")
    cfg["query"].update(window_days=1, campuses=campuses, **query)
    return cfg


def test_faa_spatial_join_is_deterministic_and_exact():
    cases = faa_oeaaa.parse_cases((FIX / "faa-cases.xml").read_bytes())
    assert len(cases) == 8 and all(c["asn"] for c in cases)
    target = next(c for c in cases if c["asn"] == "2026-ASW-3602-NRA")
    lat, lon = float(target["latitude"]), float(target["longitude"])
    campuses = [
        {"id": "B-far", "name": "Far", "latitude": lat + 0.03, "longitude": lon},
        {"id": "A-near", "name": "Near", "latitude": lat + 0.009, "longitude": lon},
        {"id": "A-tie", "name": "Tie", "latitude": lat + 0.009, "longitude": lon},
    ]
    found = faa_oeaaa.match_campuses(target, campuses, 2000)
    assert [m["campus_id"] for m in found] == ["A-near", "A-tie"]
    assert 990 <= found[0]["m"] <= 1010
    assert faa_oeaaa.match_campuses(target, campuses, 500) == []
    # The edge is inclusive: a radius equal to the rounded distance still matches.
    exact = faa_oeaaa.haversine_m(lat, lon, lat + 0.009, lon)
    assert faa_oeaaa.match_campuses(target, campuses[1:2], int(exact) + 1)
    assert faa_oeaaa.match_campuses(target, campuses[1:2], int(exact) - 1) == []
    assert faa_oeaaa.haversine_m(0, 0, 0, 1) == pytest.approx(111_194.9, abs=1)


def test_faa_candidate_observation_not_a_claim():
    body = (FIX / "faa-cases.xml").read_bytes()
    requests: list = []
    client = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "application/xml"}, content=body),
        requests,
    )
    lat, lon = 33.66569722, -101.81958889
    cfg = faa_config([{"id": "LBB-1", "name": "Campus", "latitude": lat + 0.009, "longitude": lon}])
    records = faa_oeaaa.retrieve(cfg, client, today=TODAY, pacer=fast_pacer())
    assert [r["document_number"] for r in records] == ["FAA-2026-ASW-3602-NRA"]
    record = records[0]
    assert str(requests[0].url) == (
        "https://oeaaa.faa.gov/oeaaa/services/caseList/date/OE?start=2026-10-27&end=2026-10-28"
    )
    assert record["publication_date"] == "2026-10-27" and record["event_date"] == "2026-08-19"
    assert "Candidate observation: proximity only" in record["abstract"]
    assert "states no electrical demand" in record["abstract"]
    assert record["permit"]["candidate_campuses"][0]["campus_id"] == "LBB-1"
    assert assess_permit(record, as_of=TODAY)["decision"] == "rejected"
    # Replay changes nothing: the hash is stable and tied to the join result.
    again = faa_oeaaa.retrieve(cfg, client, today=TODAY, pacer=fast_pacer())
    assert again[0]["source_hash"] == record["source_hash"]
    moved = faa_config(
        [{"id": "LBB-2", "name": "Campus", "latitude": lat + 0.009, "longitude": lon}]
    )
    assert (
        faa_oeaaa.retrieve(moved, client, today=TODAY, pacer=fast_pacer())[0]["source_hash"]
        != record["source_hash"]
    )


def test_faa_without_campuses_makes_no_request():
    requests: list = []
    client = make_client(lambda r: httpx.Response(500), requests)
    assert faa_oeaaa.retrieve(faa_config([]), client, today=TODAY) == []
    assert requests == []


def test_faa_window_pages_by_day_and_stops_at_the_cap():
    requests: list = []
    body = (FIX / "faa-cases.xml").read_bytes()
    client = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "application/xml"}, content=body),
        requests,
    )
    cfg = faa_config([{"id": "X", "name": "x", "latitude": 1.0, "longitude": 1.0}])
    cfg["query"]["window_days"] = 3
    faa_oeaaa.retrieve(cfg, client, today=TODAY, pacer=fast_pacer())
    assert [str(r.url).split("start=")[1] for r in requests] == [
        "2026-10-27&end=2026-10-28",
        "2026-10-26&end=2026-10-27",
        "2026-10-25&end=2026-10-26",
    ]
    one = re.search(rb"<OECase>.*?</OECase>", body, re.S).group(0)
    big = b"<caseList>" + one * faa_oeaaa.ROW_CAP + b"</caseList>"
    capped = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "text/xml"}, content=big)
    )
    cfg["query"]["window_days"] = 1
    with pytest.raises(SourceParseError, match="8,000-row cap"):
        faa_oeaaa.retrieve(cfg, capped, today=TODAY, pacer=fast_pacer())


def test_faa_refuses_dtd_oversize_and_bad_shapes():
    for bad in (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><caseList/>',
        b"<other/>",
        b"<caseList><OECase>",
    ):
        with pytest.raises(SourceParseError):
            faa_oeaaa.parse_cases(bad)
    big = b"<caseList>" + b"x" * 2_000_000 + b"</caseList>"
    cfg = faa_config(
        [{"id": "X", "name": "x", "latitude": 1.0, "longitude": 1.0}], max_response_bytes=1_000_000
    )
    client = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "application/xml"}, content=big)
    )
    with pytest.raises(SourceParseError, match="byte limit"):
        faa_oeaaa.retrieve(cfg, client, today=TODAY, pacer=fast_pacer())
    wrong_type = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")
    )
    with pytest.raises(SourceParseError, match="media type"):
        faa_oeaaa.retrieve(cfg, wrong_type, today=TODAY, pacer=fast_pacer())


def test_faa_campus_list_validation():
    ok = {"id": "A", "name": "n", "latitude": 30.0, "longitude": -97.0}
    assert faa_oeaaa.valid_campuses([ok])
    assert not faa_oeaaa.valid_campuses([ok, ok])  # duplicate id
    assert not faa_oeaaa.valid_campuses([{**ok, "latitude": 91}])
    assert not faa_oeaaa.valid_campuses([{**ok, "id": "bad id!"}])
    assert not faa_oeaaa.valid_campuses([{**ok, "extra": 1}])


# ---------------------------------------------------------------- MSHA


def msha_zip(text: bytes, name: str = "Mines.txt") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def test_msha_scope_fields_and_unknowns():
    data = (FIX / "msha-mines.txt").read_bytes()
    rows = msha_mines.parse_mines(
        data,
        states=["TX", "OK", "NM"],
        statuses=["Active", "New Mine", "Intermittent", "Temporarily Idled", "NonProducing"],
        max_records=100,
    )
    assert {r["STATE"] for r in rows} <= {"TX", "OK", "NM"}
    assert all(r["CURRENT_MINE_STATUS"] != "Abandoned" for r in rows)
    assert len(rows) == 6  # eight fixture rows minus the abandoned TX one and the Alabama one
    record = msha_mines.build_record(rows[0], "Fri, 30 Oct 2026 12:31:40 GMT")
    assert record["document_number"].startswith("MSHA-")
    assert "states no equipment or electrical demand" in record["abstract"]
    assert record["permit"]["snapshot_last_modified"].startswith("Fri, 30 Oct")
    assert assess_permit(record, as_of=TODAY)["decision"] == "rejected"


def test_msha_diff_is_by_record_hash_not_by_file_date_or_order():
    data = (FIX / "msha-mines.txt").read_bytes()
    kwargs = {
        "states": ["TX", "OK", "NM"],
        "statuses": ["Active", "New Mine", "Intermittent", "Temporarily Idled", "NonProducing"],
        "max_records": 100,
    }
    rows = msha_mines.parse_mines(data, **kwargs)
    first = [msha_mines.build_record(r, "Fri, 23 Oct 2026") for r in rows]
    second = [msha_mines.build_record(r, "Fri, 30 Oct 2026") for r in reversed(rows)]
    assert {r["document_number"]: r["source_hash"] for r in first} == {
        r["document_number"]: r["source_hash"] for r in second
    }
    changed = copy.deepcopy(rows)
    changed[0]["CURRENT_MINE_STATUS"] = "Temporarily Idled"
    assert msha_mines.build_record(changed[0], None)["source_hash"] != first[0]["source_hash"]


def test_msha_retrieve_downloads_once_and_reads_the_member():
    data = (FIX / "msha-mines.txt").read_bytes()
    archive = msha_zip(data)
    requests: list = []
    client = make_client(
        lambda r: httpx.Response(
            200,
            headers={
                "content-type": "application/x-zip-compressed",
                "last-modified": "Fri, 30 Oct 2026 12:31:40 GMT",
            },
            content=archive,
        ),
        requests,
    )
    records = msha_mines.retrieve(source("msha-mines"), client, pacer=fast_pacer())
    assert len(requests) == 1 and len(records) == 6
    assert [r["document_number"] for r in records] == sorted(r["document_number"] for r in records)
    assert source("msha-mines")["cadence_hours"] == 168


def test_msha_zip_guards():
    data = b"MINE_ID|X\n" + b"0" * 10
    with pytest.raises(SourceParseError, match="exactly Mines.txt"):
        msha_mines.read_member(msha_zip(data, "evil.txt"), max_uncompressed=1_000_000)
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as zf:
        zf.writestr("Mines.txt", data)
        zf.writestr("extra.txt", data)
    with pytest.raises(SourceParseError, match="exactly Mines.txt"):
        msha_mines.read_member(two.getvalue(), max_uncompressed=1_000_000)
    with pytest.raises(SourceParseError, match="exactly Mines.txt"):
        msha_mines.read_member(msha_zip(data, "../Mines.txt"), max_uncompressed=1_000_000)
    bomb = msha_zip(b"0" * 5_000_000)
    with pytest.raises(SourceParseError, match="compression-ratio"):
        msha_mines.read_member(bomb, max_uncompressed=10_000_000)
    with pytest.raises(SourceParseError, match="size bound"):
        msha_mines.read_member(msha_zip(os_random(2_000_000)), max_uncompressed=1_000_000)
    with pytest.raises(SourceParseError, match="not a zip"):
        msha_mines.read_member(b"PK-not-really", max_uncompressed=1_000_000)


def os_random(size: int) -> bytes:
    import random

    rng = random.Random(7)
    return bytes(rng.getrandbits(8) for _ in range(size))


def test_msha_download_is_capped_by_content_length_and_bound():
    big = msha_zip(os_random(50_000))
    cfg = source("msha-mines")
    cfg["query"]["max_zip_bytes"] = 1_000_000
    client = make_client(
        lambda r: httpx.Response(
            200,
            headers={"content-type": "application/zip", "content-length": "99999999"},
            content=big,
        )
    )
    with pytest.raises(SourceParseError, match="byte limit"):
        msha_mines.retrieve(cfg, client, pacer=fast_pacer())


def test_msha_bounds_and_identity_errors():
    data = (FIX / "msha-mines.txt").read_bytes()
    kw = {
        "states": ["TX", "OK", "NM"],
        "statuses": ["Active", "New Mine", "Intermittent", "Temporarily Idled", "NonProducing"],
    }
    with pytest.raises(SourceParseError, match="exceeds its bound"):
        msha_mines.parse_mines(data, max_records=2, **kw)
    lines = data.decode("latin-1").splitlines()
    dup = "\r\n".join([lines[0], lines[1], lines[1]]).encode("latin-1")
    with pytest.raises(SourceParseError, match="duplicate"):
        msha_mines.parse_mines(dup, max_records=10, **kw)
    with pytest.raises(SourceParseError, match="reviewed columns"):
        msha_mines.parse_mines(b"A|B\r\n1|2\r\n", max_records=10, **kw)


# ---------------------------------------------------------------- TCEQ aggregate


def socrata_handler(rows: list[dict], count: int | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        payload = (
            [{"count": str(len(rows) if count is None else count)}] if "count" in url else rows
        )
        return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)

    return handler


def test_tceq_aggregate_counts_pages_and_dates():
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    requests: list = []
    records = tceq_aggregate.retrieve(
        source("texas-tceq-aggregate-production"),
        make_client(socrata_handler(rows), requests),
        pacer=fast_pacer(),
    )
    assert len(records) == 5 and len(requests) == 2
    first = records[0]
    assert first["document_number"] == "TCEQ-APO-AP0000007"
    assert first["event_date"] == "2026-09-01"  # last application status date
    assert first["permit"]["state"] == "TX" and first["permit"]["location"] == "Liberty County, TX"
    assert "Registration only" in first["abstract"]
    assert assess_permit(first, as_of=TODAY)["decision"] == "rejected"


def test_tceq_aggregate_diff_changed_and_new_registrations():
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    base = {
        r["document_number"]: r["source_hash"]
        for r in [tceq_aggregate.build_record(tceq_aggregate.normalize(row)) for row in rows]
    }
    changed = copy.deepcopy(rows)
    changed[0]["last_applicaiton_status"] = "DENIED"
    changed.append({**rows[0], "registration": "AP0009999"})
    after = {
        r["document_number"]: r["source_hash"]
        for r in [tceq_aggregate.build_record(tceq_aggregate.normalize(row)) for row in changed]
    }
    new = set(after) - set(base)
    altered = {k for k in base if after[k] != base[k]}
    assert new == {"TCEQ-APO-AP0009999"} and altered == {"TCEQ-APO-AP0000007"}


def test_tceq_aggregate_count_mismatch_duplicates_and_bound():
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    cfg = source("texas-tceq-aggregate-production")
    with pytest.raises(SourceParseError, match="do not match"):
        tceq_aggregate.retrieve(
            cfg, make_client(socrata_handler(rows, count=7)), pacer=fast_pacer()
        )
    with pytest.raises(SourceParseError, match="duplicate"):
        tceq_aggregate.retrieve(
            cfg, make_client(socrata_handler(rows + [rows[0]])), pacer=fast_pacer()
        )
    cfg["query"]["max_records"] = 3
    with pytest.raises(SourceParseError, match="exceeds its bound"):
        tceq_aggregate.retrieve(cfg, make_client(socrata_handler(rows)), pacer=fast_pacer())
    with pytest.raises(SourceParseError, match="registration"):
        tceq_aggregate.normalize({"site_name": "x"})


# ---------------------------------------------------------------- AFDC


def afdc_page(total: int, stations: list[dict]) -> dict:
    return {"total_results": total, "fuel_stations": stations}


STATION = {
    "id": 101,
    "station_name": "Test Plaza",
    "status_code": "P",
    "city": "Austin",
    "state": "TX",
    "ev_dc_fast_num": 8,
    "ev_level2_evse_num": None,
    "ev_network": "Example",
    "access_code": "public",
    "open_date": "2027-01-15",
    "updated_at": "2026-11-03T12:00:00Z",
    "latitude": 30.27,
    "longitude": -97.74,
    "ev_connector_types": ["J1772COMBO", "TESLA"],
}


def test_afdc_without_a_key_fails_closed_before_any_request(monkeypatch):
    monkeypatch.delenv("AFDC_API_KEY", raising=False)
    from gridlens import settings as settings_module

    monkeypatch.setattr(settings_module, "_settings", settings_module.Settings(_env_file=None))
    requests: list = []
    client = make_client(lambda r: httpx.Response(200), requests)
    with pytest.raises(SourceParseError, match="AFDC_API_KEY"):
        afdc_stations.retrieve(source("afdc-ev-stations"), client)
    assert requests == []


def test_afdc_key_goes_in_a_header_never_the_url_and_unknown_is_not_zero():
    requests: list = []
    client = make_client(
        lambda r: httpx.Response(
            200, headers={"content-type": "application/json"}, json=afdc_page(1, [STATION])
        ),
        requests,
    )
    records = afdc_stations.retrieve(
        source("afdc-ev-stations"), client, api_key="test-key-not-real", pacer=fast_pacer()
    )
    request = requests[0]
    assert request.url.host == "developer.nlr.gov"
    assert "test-key-not-real" not in str(request.url)
    assert request.headers["x-api-key"] == "test-key-not-real"
    assert "limit=200" in str(request.url) and "offset=0" in str(request.url)
    record = records[0]
    assert record["permit"]["dc_fast_ports"] == 8 and record["permit"]["level2_ports"] is None
    assert "Level 2 ports: not stated" in record["abstract"]
    assert record["event_date"] == "2027-01-15" and record["publication_date"] == "2026-11-03"
    assert "test-key-not-real" not in json.dumps(record)


def test_afdc_pages_and_refuses_unexpected_shapes():
    pages = {
        0: afdc_page(201, [{**STATION, "id": i} for i in range(1, 201)]),
        200: afdc_page(201, [{**STATION, "id": 201}]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        return httpx.Response(200, headers={"content-type": "application/json"}, json=pages[offset])

    records = afdc_stations.retrieve(
        source("afdc-ev-stations"), make_client(handler), api_key="k", pacer=fast_pacer()
    )
    assert len(records) == 201
    odd = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "application/json"}, json={"x": 1})
    )
    with pytest.raises(SourceParseError, match="total_results"):
        afdc_stations.retrieve(source("afdc-ev-stations"), odd, api_key="k", pacer=fast_pacer())
    forbidden = make_client(
        lambda r: httpx.Response(
            403,
            headers={"content-type": "application/json"},
            json={"error": {"code": "API_KEY_MISSING"}},
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        afdc_stations.retrieve(
            source("afdc-ev-stations"), forbidden, api_key="k", pacer=fast_pacer()
        )


# ---------------------------------------------------------------- NEVI


def nevi_handler(features: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("returnCountOnly"):
            payload = {"count": len(features)}
        else:
            payload = {"features": features}
        return httpx.Response(
            200, headers={"content-type": "application/json; charset=utf-8"}, json=payload
        )

    return handler


def test_nevi_identity_nameplate_and_unknowns():
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    records = nevi_awards.retrieve(
        source("texas-txdot-nevi-awards"), make_client(nevi_handler(features)), pacer=fast_pacer()
    )
    assert len(records) == 5
    by_csj = {r["permit"]["facility"]: r for r in records}
    love = by_csj["NEVI 5000-00-399"]
    assert love["permit"]["calculated_nameplate_kw"] == 1200.0
    assert love["permit"]["nameplate_basis"].startswith("calculated")
    assert "a rating, not site demand" in love["abstract"]
    assert love["publication_date"] == "2026-09-02"
    # NEVI_ID is blank on this live row: the site key still identifies it.
    tesla = next(r for r in records if "5000-00-522" in r["document_number"])
    assert "NEVI ID not stated" in tesla["abstract"]
    empty = next(r for r in records if r["permit"]["applicant"] is None)
    assert "no applications received" in empty["abstract"]
    assert assess_permit(love, as_of=TODAY)["decision"] == "rejected"
    unknown = copy.deepcopy(features[0])
    unknown["attributes"]["MAX_PER_PORT_KW"] = None
    assert (
        nevi_awards.build_record(nevi_awards.normalize(unknown["attributes"]))["permit"][
            "calculated_nameplate_kw"
        ]
        is None
    )


def test_nevi_count_mismatch_duplicates_and_identity_failures():
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    cfg = source("texas-txdot-nevi-awards")

    def lying(request: httpx.Request) -> httpx.Response:
        payload = (
            {"count": 9} if request.url.params.get("returnCountOnly") else {"features": features}
        )
        return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)

    with pytest.raises(SourceParseError, match="do not match"):
        nevi_awards.retrieve(cfg, make_client(lying), pacer=fast_pacer())
    with pytest.raises(SourceParseError, match="duplicate"):
        nevi_awards.retrieve(
            cfg, make_client(nevi_handler(features + features[:1])), pacer=fast_pacer()
        )
    with pytest.raises(SourceParseError, match="identity"):
        nevi_awards.normalize({"CSJ": None, "LATITUDE": 30.0, "LONGITUDE": -97.0})
    with pytest.raises(SourceParseError, match="error payload"):
        nevi_awards.parse_features(b'{"error": {"code": 400}}')
    # Paging asks for fixed, ordered pages.
    requests: list = []
    nevi_awards.retrieve(cfg, make_client(nevi_handler(features), requests), pacer=fast_pacer())
    page = requests[1].url.params
    assert page["orderByFields"] == "OBJECTID" and page["resultRecordCount"] == "500"
    assert page["returnGeometry"] == "false"


# ---------------------------------------------------------------- SEC


def sec_client(requests: list, status: int = 200):
    submissions = (FIX / "sec-submissions.json").read_bytes()
    document = (FIX / "sec-10k-excerpt.htm").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(
                status, headers={"content-type": "application/json"}, content=b"{}"
            )
        if request.url.host == "data.sec.gov":
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=submissions
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=document)

    return make_client(handler, requests)


def sec_config() -> dict:
    cfg = source("sec-edgar-site-mw")
    cfg["query"].update(ciks=["0001167419"], max_filings_per_cik=1, forms=["10-K"])
    return cfg


def test_sec_refuses_to_run_without_a_contact():
    requests: list = []
    for contact in (None, "", "   "):
        with pytest.raises(SourceParseError, match="SEC_EDGAR_CONTACT"):
            sec_edgar_site_mw.retrieve(
                sec_config(),
                sec_client(requests),
                contact=contact if contact is not None else "",
                pacer=fast_pacer(),
            )
    assert requests == []


def test_sec_declares_the_contact_and_quotes_only_named_site_statements():
    requests: list = []
    records = sec_edgar_site_mw.retrieve(
        sec_config(), sec_client(requests), contact="data-contact@example.test", pacer=fast_pacer()
    )
    assert [r.url.host for r in requests] == ["data.sec.gov", "www.sec.gov"]
    for request in requests:
        agent = request.headers["user-agent"]
        assert (
            agent.startswith("GridLens public source reader/1.0")
            and "data-contact@example.test" in agent
        )
    assert str(requests[1].url) == (
        "https://www.sec.gov/Archives/edgar/data/1167419/000110465926022322/riot-20251231x10k.htm"
    )
    sites = sorted({r["permit"]["facility"] for r in records})
    assert sites == ["Corsicana Facility", "Kentucky Facility", "Rockdale Facility"]
    assert len(records) == 4  # the "1,200 MW across sites" sentence and hidden header are not read
    assert all(
        re.fullmatch(r"SEC-0001167419-[0-9-]+-[0-9a-f]{12}", r["document_number"]) for r in records
    )
    quotes = [r["permit"]["quote"] for r in records]
    assert (
        "The Kentucky Facility currently has approximately 137 MW of developed capacity." in quotes
    )
    assert not any("Phantom" in q or "1,200 MW" in q for q in quotes)
    gw = next(r for r in records if "1 GW" in r["permit"]["quote"])
    assert gw["permit"]["stated_figures"][0]["unit"] == "GW"
    for record in records:
        start, end = record["permit"]["quote_span"]
        assert record["permit"]["accession_number"] == "0001104659-26-022322"
        assert record["extraction_location"].endswith(f"characters {start}-{end}")
        assert record["publication_date"] == "2026-03-02"
        assert assess_permit(record, as_of=TODAY)["decision"] == "rejected"


def test_sec_quote_span_matches_normalised_text_exactly():
    text = sec_edgar_site_mw.filing_text((FIX / "sec-10k-excerpt.htm").read_bytes())
    statements = sec_edgar_site_mw.extract_statements(text, limit=50)
    assert statements
    for item in statements:
        assert text[item["start"] : item["end"]] == item["quote"]


def test_sec_no_named_site_means_no_statement():
    text = "Our fleet totals 1,200 MW across sites. The grid interconnection is 700 MW."
    assert sec_edgar_site_mw.extract_statements(text, limit=10) == []
    assert sec_edgar_site_mw.extract_statements("The Alpha Campus is planned.", limit=10) == []


def test_sec_403_propagates_and_bad_inputs_are_refused():
    requests: list = []
    with pytest.raises(httpx.HTTPStatusError):
        sec_edgar_site_mw.retrieve(
            sec_config(),
            sec_client(requests, status=403),
            contact="c@example.test",
            pacer=fast_pacer(),
        )
    assert len(requests) == 1
    bad = {"filings": {"recent": {"form": ["10-K"]}}}
    with pytest.raises(SourceParseError):
        sec_edgar_site_mw._recent_filings(bad, ["10-K"], 1)
    rows = sec_edgar_site_mw._recent_filings(
        {
            "filings": {
                "recent": {
                    "accessionNumber": ["0001104659-26-022322", "bad"],
                    "filingDate": ["2026-03-02", "2026-03-02"],
                    "reportDate": ["", ""],
                    "form": ["10-K", "10-K"],
                    "primaryDocument": ["../x.htm", "ok.htm"],
                }
            }
        },
        ["10-K"],
        5,
    )
    assert rows == []  # a path-traversal document name and a malformed accession are dropped


# ---------------------------------------------------------------- ERCOT monthly

BOARD = """
<a href="https://www.ercot.com/files/docs/2026/09/16/ERCOT-Monthly-Operational-Overview-August-2026.pdf">Aug</a>
<a href="https://www.ercot.com/files/docs/2026/10/16/ERCOT-Monthly-Operational-Overview-September.pdf">Sep</a>
<a href="https://www.ercot.com/files/docs/2026/10/16/Other-Report.pdf">Other</a>
<a href="https://evil.example/files/docs/2026/11/16/ERCOT-Monthly-Operational-Overview-October.pdf">x</a>
"""
SEPT = (
    "CONFIDENTIALPUBLIC ERCOT Monthly Operational Overview (September 2026) ERCOT Public "
    "October 16, 2026 PUBLIC 9 Loads Approved to Energize - Observations - Of the 9,456 MW "
    "that have received Approval to Energize, ERCOT has observed a non-simultaneous monthly peak "
    "consumption of 4,132 MW in September 2026, which is a slight decrease since August 2026."
)


def test_ercot_links_and_parse():
    links = ercot_monthly.report_links(BOARD.encode())
    assert [item["posted"] for item in links] == ["2026-10-16", "2026-09-16"]
    parsed = ercot_monthly.parse_overview(pdf_bytes(SEPT))
    assert parsed["report_month"] == "2026-09"
    assert parsed["approved_to_energize_mw"] == 9456
    assert parsed["observed_nonsimultaneous_peak_mw"] == 4132
    record = ercot_monthly.build_record(parsed, links[0]["url"], "2026-10-16")
    assert record["permit"]["calculated_observed_over_approved"] == 0.437
    assert "not a site or customer" in record["abstract"]
    assert record["permit"]["location"] is None
    assert assess_permit(record, as_of=TODAY)["decision"] == "rejected"


def test_ercot_missing_sentence_is_unknown_not_zero_and_month_must_match():
    no_fact = SEPT.split("-")[0]
    parsed = ercot_monthly.parse_overview(pdf_bytes(no_fact))
    assert (
        parsed["approved_to_energize_mw"] is None
        and parsed["observed_nonsimultaneous_peak_mw"] is None
    )
    record = ercot_monthly.build_record(
        parsed, "https://www.ercot.com/files/docs/x.pdf", "2026-10-16"
    )
    assert (
        "not stated" in record["abstract"]
        and record["permit"]["calculated_observed_over_approved"] is None
    )
    stale = SEPT.replace("in September 2026", "in August 2026")
    assert ercot_monthly.parse_overview(pdf_bytes(stale))["approved_to_energize_mw"] is None
    with pytest.raises(SourceParseError, match="report month"):
        ercot_monthly.parse_overview(pdf_bytes("no title here"))
    with pytest.raises(SourceParseError, match="could not be read"):
        ercot_monthly.parse_overview(b"not a pdf")


def test_ercot_retrieve_fetches_the_page_then_the_newest_pdfs_only():
    requests: list = []
    pdf = pdf_bytes(SEPT)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("index.html"):
            return httpx.Response(
                200, headers={"content-type": "text/html;charset=UTF-8"}, content=BOARD.encode()
            )
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)

    cfg = source("texas-ercot-monthly-overview")
    cfg["query"]["max_reports"] = 1
    records = ercot_monthly.retrieve(cfg, make_client(handler, requests), pacer=fast_pacer())
    assert len(requests) == 2 and len(records) == 1
    assert requests[1].url.path.endswith("September.pdf")
    empty = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")
    )
    with pytest.raises(SourceParseError, match="links no monthly"):
        ercot_monthly.retrieve(source("texas-ercot-monthly-overview"), empty, pacer=fast_pacer())


# ---------------------------------------------------------------- regulatory events


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_every_event_quote_is_in_its_official_source_text():
    texts = json.loads((FIX / "regulatory-source-text.json").read_text(encoding="utf-8"))
    events = regulatory_events.load_events()
    assert len(events) == 4
    for event in events:
        assert event["source_url"] in texts, event["id"]
        text = texts[event["source_url"]]
        if event["source_url"].endswith("tceq-response-gov-abbott-dc-directive.pdf"):
            # Only this PDF's text layer has stray spaces inside words, so compare compactly.
            assert _compact(event["quote"]) in _compact(text), event["id"]
        else:
            assert " ".join(event["quote"].split()) in " ".join(text.split()), event["id"]


def test_event_records_are_dated_sourced_and_evidence_only():
    cfg = source("regulatory-event-feed")
    records = regulatory_events.retrieve(cfg)
    assert [r["document_number"] for r in records] == [
        "tx-gov-20260803-puct-ercot-audit",
        "tx-gov-20260914-twdb-water-survey",
        "tx-gov-20260921-tceq-pause",
        "tx-tceq-20261019-pause-response",
    ]
    pause = records[2]
    assert pause["publication_date"] == pause["event_date"] == "2026-09-21"
    assert pause["html_url"].startswith("https://gov.texas.gov/")
    assert "pause the issuance of all permits related to data center projects" in pause["abstract"]
    # The directive orders a pause but says nothing of any single filing: no label.
    assert pause["permit"]["status"] is None
    assert records[3]["permit"]["status"] == "pending — pause may apply (TCEQ screening)"
    assert records[1]["permit"]["status"] is None  # conditional: no label is inferred
    assert assess_permit(pause, as_of=TODAY)["decision"] == "rejected"


FILING = {
    "state": "TX",
    "agency": "TCEQ",
    "instrument": "permits",
    "data_center_explicit": True,
    "pending": True,
}


def test_event_to_scope_to_status_model():
    events = regulatory_events.load_events()
    # The Governor's directive alone (09-21) labels nothing; TCEQ's own reply (10-19) does.
    for day in (date(2026, 9, 20), date(2026, 9, 21), date(2026, 10, 18)):
        assert regulatory_events.status_for(FILING, events, day) is None
    hit = regulatory_events.status_for(FILING, events, date(2026, 10, 19))
    assert hit and hit["label"] == "pending — pause may apply (TCEQ screening)"
    assert hit["event_id"] == "tx-tceq-20261019-pause-response"
    later = regulatory_events.status_for(FILING, events, date(2026, 11, 4))
    assert later and later["event_id"] == "tx-tceq-20261019-pause-response"
    # No inference: not explicitly a data center, not pending, other agency or state: unknown.
    for patch in (
        {"data_center_explicit": False},
        {"pending": False},
        {"agency": "RRC"},
        {"state": "OK"},
        {"instrument": "interconnection"},
    ):
        assert regulatory_events.status_for({**FILING, **patch}, events, date(2026, 11, 4)) is None
    audit = regulatory_events.status_for(
        {**FILING, "agency": "PUCT+ERCOT", "instrument": "project_advancement"},
        events,
        date(2026, 11, 4),
    )
    assert audit and audit["label"] == "pending — audit required"


def test_only_a_later_lift_event_clears_a_pause():
    events = regulatory_events.load_events()
    lift = {**events[3], "id": "zz-lift", "date": "2027-01-10", "effect": "lift_pause"}
    assert (
        regulatory_events.status_for(FILING, [*events, lift], date(2027, 1, 9))["label"]
        == "pending — pause may apply (TCEQ screening)"
    )
    assert regulatory_events.status_for(FILING, [*events, lift], date(2027, 1, 10)) is None


def test_event_file_validation(tmp_path):
    good = json.loads(regulatory_events.EVENTS_PATH.read_text(encoding="utf-8"))
    event = good["events"][2]

    def load_with(mutated) -> None:
        path = tmp_path / "events.json"
        path.write_text(json.dumps({"version": 1, "events": [mutated]}), encoding="utf-8")
        regulatory_events.load_events(path)

    load_with(event)
    for mutated in (
        {**event, "source_url": "https://evil.example/x"},
        {**event, "source_url": "http://gov.texas.gov/x"},
        {**event, "effect": "invented"},
        {**event, "date": "soon"},
        {**event, "quote": ""},
        {**event, "scope": {"state": "TX"}},
        {**event, "extra": 1},
        {**event, "verified_on": "2026-09-20"},  # verified before the event happened
        {**event, "source_url": "https://gov.texas.gov:99999/x"},  # invalid port
    ):
        with pytest.raises(SourceParseError):
            load_with(mutated)
    path = tmp_path / "dup.json"
    path.write_text(json.dumps({"version": 1, "events": [event, event]}), encoding="utf-8")
    with pytest.raises(SourceParseError, match="unique"):
        regulatory_events.load_events(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(SourceParseError, match="unreadable"):
        regulatory_events.load_events(path)


# ---------------------------------------------------------------- review fixes


def test_ercot_keeps_only_the_newest_pdf_for_a_report_month():
    board = (
        '<a href="https://www.ercot.com/files/docs/2026/10/16/ERCOT-Monthly-Operational-Overview-September.pdf">a</a>'
        '<a href="https://www.ercot.com/files/docs/2026/10/20/ERCOT-Monthly-Operational-Overview-September-Revised.pdf">b</a>'
    )
    old_pdf, new_pdf = pdf_bytes(SEPT), pdf_bytes(SEPT.replace("4,132", "4,200"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("index.html"):
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=board.encode()
            )
        body = new_pdf if "Revised" in request.url.path else old_pdf
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    records = ercot_monthly.retrieve(
        source("texas-ercot-monthly-overview"), make_client(handler), pacer=fast_pacer()
    )
    assert len(records) == 1
    assert records[0]["permit"]["stated_aggregates"]["observed_nonsimultaneous_peak_mw"] == 4200
    assert records[0]["publication_date"] == "2026-10-20"


def test_ercot_picks_the_sentence_for_the_title_month_and_wraps_pdf_errors():
    other = (
        "Of the 8,000 MW that have received Approval to Energize, ERCOT has observed a "
        "non-simultaneous monthly peak consumption of 3,000 MW in August 2026. "
    )
    parsed = ercot_monthly.parse_overview(
        pdf_bytes(SEPT.replace("PUBLIC 9 Loads", other + "PUBLIC 9 Loads"))
    )
    assert parsed["approved_to_energize_mw"] == 9456
    for broken in (b"%PDF-1.4 garbage", b""):
        with pytest.raises(SourceParseError):
            ercot_monthly.parse_overview(broken)


def sec_statements(text: str) -> list[dict]:
    return sec_edgar_site_mw.extract_statements(text, limit=20)


def test_sec_probe_energy_units_are_not_power():
    assert sec_statements("The Kentucky Facility used 400 megawatt-hours of power last year.") == []
    assert sec_statements("The Kentucky Facility used 400 MWh and 2 GWh in 2025.") == []
    assert sec_statements("The Kentucky Facility used 400 megawatt hours.") == []
    assert len(sec_statements("The Kentucky Facility has 400 MW of capacity.")) == 1


def test_sec_probe_financing_facilities_are_not_sites():
    assert sec_statements("We drew 200 MW worth under the Revolving Credit Facility.") == []
    assert sec_statements("The Term Loan Facility funds the 300 MW build.") == []
    assert sec_statements("The Credit Facility supports 50 MW of expansion.") == []

    sentence = "The Rockdale Facility hosts mining; the Corsicana Facility has 1 GW of capacity."


def test_sec_probe_two_sites_in_one_sentence_are_dropped():
    sentence = "The Rockdale Facility hosts mining; separately the Corsicana Facility has 1 GW of capacity."
    assert sec_statements(sentence) == []
    assert len(sec_statements("The Rockdale Facility (the Rockdale Facility) has 700 MW.")) == 1


def test_sec_probe_tables_and_unfinished_text_yield_nothing():
    table = "<table><tr><td>The Kentucky Facility has 137 MW of capacity.</td></tr></table>"
    assert sec_edgar_site_mw.filing_text(table.encode()) == ""
    assert sec_statements("The Kentucky Facility has 137 MW of capacity") == []
    assert len(sec_statements('We said "the Kentucky Facility has 137 MW."')) == 1


def test_sec_contact_is_secret_ascii_and_never_echoed():
    from pydantic import SecretStr

    requests: list = []
    records = sec_edgar_site_mw.retrieve(
        sec_config(),
        sec_client(requests),
        contact=SecretStr("owner@example.test"),
        pacer=fast_pacer(),
    )
    assert records and "owner@example.test" in requests[0].headers["user-agent"]
    assert "owner@example.test" not in repr(SecretStr("owner@example.test"))
    for bad in ("caf\u00e9@example.test", "line\nbreak@example.test"):
        with pytest.raises(SourceParseError) as caught:
            sec_edgar_site_mw.retrieve(
                sec_config(), sec_client([]), contact=bad, pacer=fast_pacer()
            )
        assert bad not in str(caught.value)


def test_sec_skips_accessions_already_ingested_and_row_id_follows_the_quote():
    requests: list = []
    cfg = sec_config()
    cfg["known_accessions"] = ["0001104659-26-022322"]
    assert (
        sec_edgar_site_mw.retrieve(
            cfg, sec_client(requests), contact="c@example.test", pacer=fast_pacer()
        )
        == []
    )
    assert [r.url.host for r in requests] == ["data.sec.gov"]  # the filing itself was not fetched
    cfg["known_accessions"] = ["not-an-accession"]
    with pytest.raises(SourceParseError):
        sec_edgar_site_mw.retrieve(
            cfg, sec_client([]), contact="c@example.test", pacer=fast_pacer()
        )
    first = sec_edgar_site_mw.retrieve(
        sec_config(), sec_client([]), contact="c@example.test", pacer=fast_pacer()
    )
    again = sec_edgar_site_mw.retrieve(
        sec_config(), sec_client([]), contact="c@example.test", pacer=fast_pacer()
    )
    assert [r["document_number"] for r in first] == [r["document_number"] for r in again]


def test_afdc_hash_ignores_updated_at_and_last_confirmed_only():
    base = afdc_stations.build_record(afdc_stations.normalize(STATION))
    touched = afdc_stations.build_record(
        afdc_stations.normalize(
            {**STATION, "updated_at": "2026-12-01T00:00:00Z", "date_last_confirmed": "2026-12-01"}
        )
    )
    assert touched["source_hash"] == base["source_hash"]
    assert touched["publication_date"] == "2026-12-01" and base["publication_date"] == "2026-11-03"
    moved = afdc_stations.build_record(afdc_stations.normalize({**STATION, "ev_dc_fast_num": 12}))
    assert moved["source_hash"] != base["source_hash"]


def test_fetch_refuses_a_host_that_resolves_to_a_private_address(monkeypatch):
    import socket

    monkeypatch.setattr(sector_common, "resolve_public", REAL_RESOLVE)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))],
    )
    requests: list = []
    client = make_client(lambda r: httpx.Response(200, content=b"[]"), requests)
    with pytest.raises(SourceParseError, match="non-public"):
        sector_common.fetch(
            client,
            "https://data.texas.gov/resource/9ixa-7k3m.json",
            hosts={"data.texas.gov"},
            max_bytes=10,
            media_types={"application/json"},
            pacer=fast_pacer(),
        )
    assert requests == []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(SourceParseError, match="non-public"):  # one bad address is enough
        sector_common.fetch(
            client,
            "https://data.texas.gov/x",
            hosts={"data.texas.gov"},
            max_bytes=10,
            media_types={"application/json"},
            pacer=fast_pacer(),
        )
    assert requests == []


def test_a_503_is_one_request_and_surfaces_for_the_worker():
    requests: list = []
    client = make_client(lambda r: httpx.Response(503, headers={"retry-after": "120"}), requests)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        tceq_aggregate.retrieve(
            source("texas-tceq-aggregate-production"), client, pacer=fast_pacer()
        )
    assert len(requests) == 1
    assert acquisition_diagnostics(caught.value)["error_code"] == "http_status_503"
    assert acquisition_diagnostics(caught.value)["retry_after_seconds"] == 120


def test_published_at_is_stated_only_where_the_source_states_it():
    rows = json.loads((FIX / "tceq-aggregate.json").read_text(encoding="utf-8"))
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    mine = msha_mines.parse_mines(
        (FIX / "msha-mines.txt").read_bytes(),
        states=["TX"],
        statuses=["Active"],
        max_records=10,
    )[0]
    faa = faa_oeaaa.build_record(
        faa_oeaaa.parse_cases((FIX / "faa-cases.xml").read_bytes())[0],
        [{"campus_id": "C", "name": "n", "m": 5}],
    )
    sec_text = sec_edgar_site_mw.filing_text((FIX / "sec-10k-excerpt.htm").read_bytes())
    sec = sec_edgar_site_mw.build_record(
        sec_edgar_site_mw.extract_statements(sec_text, limit=1)[0],
        company="Riot",
        cik="0001167419",
        filing={
            "accessionNumber": "0001104659-26-022322",
            "filingDate": "2026-03-02",
            "reportDate": "2025-12-31",
            "form": "10-K",
        },
        url="https://www.sec.gov/x.htm",
    )
    ercot = ercot_monthly.build_record(
        ercot_monthly.parse_overview(pdf_bytes(SEPT)), "https://www.ercot.com/x.pdf", "2026-10-16"
    )
    stated = {
        "faa": faa["publication_date"],
        "nevi": nevi_awards.build_record(nevi_awards.normalize(features[0]["attributes"]))[
            "publication_date"
        ],
        "sec": sec["publication_date"],
        "ercot": ercot["publication_date"],
        "events": regulatory_events.build_record(regulatory_events.load_events()[0])[
            "publication_date"
        ],
        "afdc": afdc_stations.build_record(afdc_stations.normalize(STATION))["publication_date"],
    }
    assert all(stated.values()), stated
    # MSHA and the TCEQ registry publish no publication date: published_at stays NULL.
    assert msha_mines.build_record(mine, None)["publication_date"] is None
    assert (
        tceq_aggregate.build_record(tceq_aggregate.normalize(rows[0]))["publication_date"] is None
    )


def test_faa_cap_counts_raw_nodes_and_dtd_is_refused_anywhere():
    one = re.search(rb"<OECase>.*?</OECase>", (FIX / "faa-cases.xml").read_bytes(), re.S).group(0)
    bad_asn = one.replace(re.search(rb"<asn>(.*?)</asn>", one).group(0), b"<asn>junk</asn>")
    body = b"<caseList>" + bad_asn * faa_oeaaa.ROW_CAP + b"</caseList>"
    cases, nodes = faa_oeaaa.parse_case_list(body)
    assert cases == [] and nodes == faa_oeaaa.ROW_CAP  # unparsed rows still count toward the cap
    cfg = faa_config([{"id": "X", "name": "x", "latitude": 1.0, "longitude": 1.0}])
    client = make_client(
        lambda r: httpx.Response(200, headers={"content-type": "text/xml"}, content=body)
    )
    with pytest.raises(SourceParseError, match="8,000-row cap"):
        faa_oeaaa.retrieve(cfg, client, today=TODAY, pacer=fast_pacer())
    late = b"<caseList>" + b" " * 70000 + b"<!DOCTYPE x></caseList>"
    with pytest.raises(SourceParseError, match="DTD"):
        faa_oeaaa.parse_case_list(late)


def test_msha_fails_above_a_small_number_of_malformed_rows():
    lines = (FIX / "msha-mines.txt").read_bytes().decode("latin-1").splitlines()
    kw = {"states": ["TX"], "statuses": ["Active"], "max_records": 50}
    few = "\r\n".join([*lines, *["short|row"] * 3]).encode("latin-1")
    msha_mines.parse_mines(few, **kw)  # three skipped rows are tolerated
    many = "\r\n".join([*lines, *["short|row"] * (msha_mines.MAX_MALFORMED_ROWS + 1)]).encode(
        "latin-1"
    )
    with pytest.raises(SourceParseError, match="malformed"):
        msha_mines.parse_mines(many, **kw)


def test_nevi_prints_a_stated_zero_grant_as_zero():
    features = json.loads((FIX / "nevi-features.json").read_text(encoding="utf-8"))["features"]
    attrs = {**features[0]["attributes"], "CONSTRUCTION_GRANT": 0}
    record = nevi_awards.build_record(nevi_awards.normalize(attrs))
    assert "Construction grant (USD): 0" in record["abstract"]
    attrs["CONSTRUCTION_GRANT"] = None
    assert (
        "Construction grant (USD): not stated"
        in nevi_awards.build_record(nevi_awards.normalize(attrs))["abstract"]
    )


def test_candidate_record_asserts_its_own_source_type():
    record = sector_common.candidate_record(
        source_id="msha-mines",
        row_id="X-1",
        title="t",
        abstract_lines=["a"],
        url="https://example.test/",
        extraction_location="loc",
        semantic={},
        permit={"source_type": "texas-jeti-agreements", "data_center": True},
    )
    assert record["permit"]["source_type"] == "msha-mines"
    assert record["permit"]["data_center"] is False


def test_pacer_stops_at_the_job_deadline():
    pacer = Pacer(deadline=0.0)  # long past on the monotonic clock
    with pytest.raises(TimeoutError):
        pacer.wait()
