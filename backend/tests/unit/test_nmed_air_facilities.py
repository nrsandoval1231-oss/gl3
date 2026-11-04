"""NMED air-facility layers: fixed query shape, paging, caps, 429, identity-only records.

No network: HTTP goes through httpx.MockTransport with DNS pinned to a public address and a
fake clock for pacing.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

import gridlens.ingestion.adapters.nmed_air_facilities as nf
import gridlens.ingestion.adapters.nmed_http as nh
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import Pacer


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def feature(object_id, name="Roswell Compressor Station", **over):
    attrs = {
        "OBJECTID": object_id,
        "AI_NAME": name,
        "PHYSICAL_ADDRESS_LINE_1": "23 mi N of Roswell",
        "MUNICIPALITY": "Roswell",
        "COUNTY": "Chaves",
        "STATE": "NM",
        "ZIP": "88201    ",
        "AI_STATUS": "Active",
        "AI_TYPE": "O&G-Compressor Station",
        "FACILITY_CLASS": "Major-Title V ",
        "LAT": 33.711917,
        "LON": -104.5495,
    }
    attrs.update(over)
    return {"attributes": attrs}


class Arc:
    """Mock mercator.env.nm.gov: rows per layer, a request log, optional forced replies."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        self.log: list[tuple[str, dict]] = []
        self.forced: dict[int, httpx.Response] = {}
        self.omit_exceeded = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == nf.HOST
        assert request.headers["user-agent"] == "GridLens public source reader/1.0"
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        layer = int(request.url.path.split("/")[-2])
        assert request.url.path == f"{nf.SERVICE_PATH}/{layer}/query"
        self.log.append((request.url.path, query))
        if layer in self.forced:
            return self.forced[layer]
        rows = self.rows.get(layer, [])
        offset, count = int(query["resultOffset"]), int(query["resultRecordCount"])
        page = rows[offset : offset + count]
        body = {"features": page}
        if offset + count < len(rows) and not self.omit_exceeded:
            body["exceededTransferLimit"] = True
        return httpx.Response(200, headers={"content-type": "application/json"}, json=body)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)


def cfg(**over):
    base = {"layers": (0,), "page_size": 50, "max_records": 500, "max_requests": 10}
    return nf.FacilityConfig(**{**base, **over})


def run(arc, config=None, **kwargs):
    return nf.fetch_facilities(arc.client(), config or cfg(), pacer=lambda: None, **kwargs)


# --------------------------------------------------------------------------- shape and policy


def test_query_shape_is_fixed_and_never_asks_for_geometry_or_all_fields():
    arc = Arc({0: [feature(1)]})
    run(arc)
    (path, query) = arc.log[0]
    assert path.endswith("/MapServer/0/query")
    assert set(query) == {
        "where",
        "outFields",
        "orderByFields",
        "resultOffset",
        "resultRecordCount",
        "returnGeometry",
        "f",
    }
    assert query["returnGeometry"] == "false" and query["f"] == "json"
    assert query["outFields"].split(",") == list(nf.FIELDS) and "*" not in query["outFields"]
    assert query["where"] == "AI_TYPE LIKE 'O&G%'"


def test_oil_gas_filter_can_be_turned_off():
    arc = Arc({0: [feature(1)]})
    run(arc, cfg(oil_gas_only=False))
    assert arc.log[0][1]["where"] == "1=1"


@pytest.mark.parametrize("layer", [-1, 7, 99])
def test_unknown_layers_are_refused(layer):
    with pytest.raises(ValueError):
        nf.layer_query_url(layer, 0, 10, oil_gas_only=True)


@pytest.mark.parametrize("count", [0, 1001])
def test_page_size_bounds(count):
    with pytest.raises(ValueError):
        nf.layer_query_url(0, 0, count, oil_gas_only=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://mercator.env.nm.gov/server/rest/services",
        "https://mercator.env.nm.gov.attacker.test/server/rest/services",
        "https://user:pw@mercator.env.nm.gov/server/rest/services",
        "https://mercator.env.nm.gov:8443/server/rest/services",
        "https://mercator.env.nm.gov/server/rest/services#x",
        "https://169.254.169.254/latest",
    ],
)
def test_host_policy_rejects_other_origins(url):
    with pytest.raises(SourceParseError):
        nh.check_host(url, nh.ARCGIS_HOST)


def test_non_public_dns_is_refused(monkeypatch):
    def private(_host):
        raise SourceParseError("TCEQ host resolved to a non-public address")

    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", private)
    result = run(Arc({0: [feature(1)]}))
    assert result.records == [] and result.failures == ["url_policy"]


# --------------------------------------------------------------------------- records


def test_records_are_identity_only_with_no_permit_number():
    result = run(Arc({0: [feature(7)]}))
    (record,) = result.records
    assert record["ai_number"] is None and record["permit_number"] is None
    assert record["permit_class"] == "Major-Title V"
    assert record["facility_class"] == "Major-Title V"  # trailing space stripped
    assert record["zip"] == "88201"
    assert (record["latitude"], record["longitude"]) == (33.711917, -104.5495)
    assert record["identity_key"] == "nmed-aq:0:7"
    assert len(record["record_hash"]) == 64
    assert "no AI or permit number" in record["identity_basis"]


def test_hash_is_stable_and_changes_with_content():
    one = run(Arc({0: [feature(7)]})).records[0]["record_hash"]
    again = run(Arc({0: [feature(7)]})).records[0]["record_hash"]
    changed = run(Arc({0: [feature(7, AI_STATUS="Inactive")]})).records[0]["record_hash"]
    assert one == again != changed


def test_out_of_range_or_partial_coordinates_are_unknown_not_moved():
    rows = [
        feature(1, LAT=0.0, LON=0.0),
        feature(2, LAT=33.7, LON=None),
        feature(3, LAT="33.7", LON="-104.5"),
        feature(4, LAT=True, LON=-104.5),
    ]
    records = run(Arc({0: rows})).records
    assert [(r["latitude"], r["longitude"]) for r in records] == [(None, None)] * 4


def test_unusable_and_duplicate_features_are_skipped_and_counted():
    rows = [feature(1), feature(1), feature("x"), feature(2, name=None), {"nope": 1}, feature(3)]
    result = run(Arc({0: rows}))
    assert [r["object_id"] for r in result.records] == [1, 3]
    assert result.layers[0]["skipped"] == 4


def test_text_is_cleaned_and_capped():
    name = "Plant\x00\x07 Name\n  Two " + "x" * 300
    (record,) = run(Arc({0: [feature(1, name=name)]})).records
    assert "\x00" not in record["name"] and "\n" not in record["name"]
    assert len(record["name"]) <= 100


# --------------------------------------------------------------------------- paging and caps


def test_pages_until_a_short_page():
    arc = Arc({0: [feature(i) for i in range(1, 121)]})
    result = run(arc, cfg(page_size=50))
    assert len(result.records) == 120 and result.requests == 3
    assert [q["resultOffset"] for _, q in arc.log] == ["0", "50", "100"]
    assert result.layers[0]["truncated"] is False


def test_full_page_without_exceeded_flag_still_checks_the_next_page():
    arc = Arc({0: [feature(i) for i in range(1, 101)]})
    arc.omit_exceeded = True
    result = run(arc, cfg(page_size=50))
    assert len(result.records) == 100 and result.requests == 3


def test_record_cap_marks_the_layer_truncated():
    arc = Arc({0: [feature(i) for i in range(1, 201)]})
    result = run(arc, cfg(page_size=50, max_records=100))
    assert len(result.records) == 100
    assert result.layers[0]["truncated"] is True


def test_request_cap_is_shared_across_layers():
    arc = Arc({0: [feature(i) for i in range(1, 101)], 1: [feature(i) for i in range(1, 101)]})
    result = run(arc, cfg(layers=(0, 1), page_size=50, max_requests=2))
    assert result.requests == 2 and len(arc.log) == 2
    assert result.layers[1]["truncated"] is True and result.layers[1]["rows"] == 0


def test_layers_are_read_in_order_and_labelled():
    arc = Arc({0: [feature(1)], 2: [feature(1, name="Other Plant")]})
    result = run(arc, cfg(layers=(0, 2)))
    assert [(r["layer_id"], r["permit_class"]) for r in result.records] == [
        (0, "Major-Title V"),
        (2, "Synthetic Minor"),
    ]


# --------------------------------------------------------------------------- failures


def test_429_stops_everything_and_reports_retry_after():
    arc = Arc({0: [feature(1)], 1: [feature(2)]})
    arc.forced[0] = httpx.Response(429, headers={"retry-after": "120"})
    result = run(arc, cfg(layers=(0, 1)))
    assert result.rate_limited is True and result.retry_after_seconds == 120
    assert result.failures == ["http_status_429"]
    assert len(arc.log) == 1  # layer 1 was never requested


def test_503_is_a_rate_limit_too():
    arc = Arc({0: [feature(1)]})
    arc.forced[0] = httpx.Response(503)
    result = run(arc)
    assert result.rate_limited is True and result.retry_after_seconds is None


def test_arcgis_error_payload_keeps_only_a_code():
    arc = Arc()
    arc.forced[0] = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"error": {"code": 400, "message": "secret detail <script>"}},
    )
    result = run(arc)
    assert result.failures == ["arcgis_error"] and result.records == []
    assert "secret" not in json.dumps(result.failures)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"),
            "wrong_content_type",
        ),
        (
            httpx.Response(200, headers={"content-type": "application/json"}, content=b"{"),
            "schema_invalid",
        ),
        (
            httpx.Response(200, headers={"content-type": "application/json"}, json=[1]),
            "schema_invalid",
        ),
        (
            httpx.Response(200, headers={"content-type": "application/json"}, json={"features": 1}),
            "schema_invalid",
        ),
        (
            httpx.Response(302, headers={"location": "https://evil.example/"}),
            "redirect_not_followed",
        ),
        (httpx.Response(500), "http_status_500"),
        (httpx.Response(404), "http_status_404"),
    ],
)
def test_bad_replies_are_typed_failures(response, code):
    arc = Arc()
    arc.forced[0] = response
    result = run(arc)
    assert result.failures == [code] and result.records == []
    assert result.layers[0]["truncated"] is True and result.rate_limited is False


def test_oversize_by_declared_length(monkeypatch):
    monkeypatch.setattr(nf, "MAX_RESPONSE_BYTES", 100)
    arc = Arc()
    arc.forced[0] = httpx.Response(
        200, headers={"content-type": "application/json"}, content=b"{" + b" " * 500 + b"}"
    )
    assert run(arc).failures == ["oversize"]


def test_a_failed_layer_does_not_stop_the_next_one():
    arc = Arc({1: [feature(5)]})
    arc.forced[0] = httpx.Response(500)
    result = run(arc, cfg(layers=(0, 1)))
    assert [r["object_id"] for r in result.records] == [5]
    assert result.failures == ["http_status_500"]


def test_deadline_stops_before_any_request():
    arc = Arc({0: [feature(1)]})
    result = run(arc, deadline=0.0)
    assert arc.log == [] and result.failures == ["deadline"] and result.requests == 0


# --------------------------------------------------------------------------- pacing


def test_requests_are_at_most_one_per_second():
    clock = {"now": 1000.0}
    stamps: list[float] = []

    def sleep(seconds):
        clock["now"] += seconds

    pacer = Pacer(clock=lambda: clock["now"], sleep=sleep)

    def mark():
        pacer()
        stamps.append(clock["now"])

    arc = Arc({0: [feature(i) for i in range(1, 121)]})
    nf.fetch_facilities(arc.client(), cfg(page_size=50), pacer=mark)
    assert len(stamps) == 3
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:], strict=False))
    assert stamps[0] - 1000.0 >= 1.0


# --------------------------------------------------------------------------- configuration


GOOD = {
    "layers": [0, 1, 2],
    "page_size": 500,
    "max_records": 3000,
    "max_requests": 12,
    "oil_gas_only": True,
}


def test_config_validation():
    assert nf.valid_config(GOOD)
    assert nf.config_from_dict(GOOD).layers == (0, 1, 2)
    bad = [
        {**GOOD, "layers": []},
        {**GOOD, "layers": [0, 0]},
        {**GOOD, "layers": [9]},
        {**GOOD, "layers": [True]},
        {**GOOD, "page_size": 49},
        {**GOOD, "page_size": 1001},
        {**GOOD, "max_records": 0},
        {**GOOD, "max_records": 10_001},
        {**GOOD, "max_requests": 31},
        {**GOOD, "oil_gas_only": "yes"},
        {**GOOD, "extra": 1},
        {k: v for k, v in GOOD.items() if k != "page_size"},
        None,
        [],
    ]
    for item in bad:
        assert not nf.valid_config(item), item
    with pytest.raises(ValueError):
        nf.config_from_dict(bad[0])
