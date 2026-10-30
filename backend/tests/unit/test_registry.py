import json
from pathlib import Path

import pytest

from gridlens.ingestion.registry import load_registry


def test_registry_is_versioned_and_validated():
    assert {source["id"] for source in load_registry()} >= {
        "federal-register-eis",
        "austin-building-permits",
        "seattle-building-permits",
        "chicago-building-permits",
    }


def test_registry_rejects_unbounded_page_query(tmp_path: Path):
    source = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = source.read_text(encoding="utf-8").replace('"max_pages": 10', '"max_pages": 100')
    bad = tmp_path / "registry.json"
    bad.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(bad)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("cadence_hours", 0, "positive number of hours"),
        ("schedule_mode", "unknown", "Unsupported source schedule mode"),
        ("timezone", "Not/A_Zone", "valid IANA zone"),
        ("schedule_anchor_time", "25:90", "local clock time"),
    ],
)
def test_registry_rejects_invalid_schedule_configuration(tmp_path: Path, field, value, message):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["sources"][0][field] = value
    bad = tmp_path / "registry.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_registry(bad)


@pytest.mark.parametrize(
    ("cadence", "schedule_mode"),
    [(36, "local_daily"), (True, "utc_hourly")],
)
def test_registry_rejects_unrepresentable_or_boolean_cadence(
    tmp_path: Path, cadence: int | bool, schedule_mode: str
):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source = next(item for item in payload["sources"] if item["id"] == "federal-register-eis")
    assert source["retrieval_method"] == "json-api"
    source["cadence_hours"] = cadence
    source["schedule_mode"] = schedule_mode
    bad = tmp_path / "registry.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cadence"):
        load_registry(bad)


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    bad = tmp_path / "registry.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    return bad


def _federal_register_source(payload: dict) -> dict:
    return next(item for item in payload["sources"] if item["id"] == "federal-register-eis")


def test_federal_register_registry_declares_single_bounded_supplemental_lane():
    source = next(item for item in load_registry() if item["id"] == "federal-register-eis")
    assert source["query"]["supplemental_queries"] == [
        {
            "term": "environmental assessment",
            "agency": "federal-energy-regulatory-commission",
        }
    ]
    assert source["query"]["window_days"] == 30
    assert source["query"]["max_pages"] == 10
    assert source["query"]["max_run_bytes"] == 20_000_000
    assert "not historical backfill" in source["coverage_limitation"]


@pytest.mark.parametrize(
    "supplemental",
    [
        {"term": "environmental assessment", "agency": "federal-energy-regulatory-commission"},
        [
            {"term": "environmental assessment", "agency": "federal-energy-regulatory-commission"},
            {"term": "extra", "agency": "federal-energy-regulatory-commission"},
        ],
        [
            {
                "term": "environmental assessment",
                "agency": "federal-energy-regulatory-commission",
                "extra": "x",
            }
        ],
        [{"term": "environmental assessment", "agency": "wrong-agency"}],
        [{"term": 42, "agency": "federal-energy-regulatory-commission"}],
    ],
)
def test_registry_rejects_malformed_or_unapproved_supplemental_query(tmp_path: Path, supplemental):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    _federal_register_source(payload)["query"]["supplemental_queries"] = supplemental
    with pytest.raises(ValueError, match="bounded collection window"):
        load_registry(_write_registry(tmp_path, payload))


def test_registry_rejects_supplemental_query_on_another_source(tmp_path: Path):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    federal = _federal_register_source(payload)
    supplemental = federal["query"].pop("supplemental_queries")
    next(item for item in payload["sources"] if item["id"] == "nc-commerce")["query"][
        "supplemental_queries"
    ] = supplemental
    with pytest.raises(ValueError, match="unsupported for this source"):
        load_registry(_write_registry(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "other-federal-register-source"),
        ("retrieval_method", "federal-register-json"),
        ("endpoint", "https://www.federalregister.gov:443/api/v1/documents.json"),
        ("endpoint", "https://user@www.federalregister.gov/api/v1/documents.json"),
        ("endpoint", "https://www.federalregister.gov/api/v1/documents.json#fragment"),
    ],
)
def test_registry_rejects_supplemental_field_outside_exact_registered_binding(
    tmp_path: Path, field, value
):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source = _federal_register_source(payload)
    source[field] = value
    with pytest.raises(ValueError, match="bounded collection window"):
        load_registry(_write_registry(tmp_path, payload))


def test_registry_restricts_even_empty_supplemental_list_to_registered_source(tmp_path: Path):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source = _federal_register_source(payload)
    source["id"] = "other-federal-register-source"
    source["query"]["supplemental_queries"] = []
    with pytest.raises(ValueError, match="bounded collection window"):
        load_registry(_write_registry(tmp_path, payload))


def test_registry_preserves_legacy_federal_register_100mb_run_limit(tmp_path: Path):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source = _federal_register_source(payload)
    source["query"]["max_run_bytes"] = 100_000_000
    assert load_registry(_write_registry(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("term", 12),
        ("document_type", ["NOTICE"]),
        ("window_days", True),
        ("per_page", True),
        ("max_pages", "10"),
        ("max_response_bytes", False),
        ("max_run_bytes", 100_000_001),
    ],
)
def test_registry_rejects_malformed_federal_register_query_types_and_bounds(
    tmp_path: Path, field, value
):
    source_path = Path(__file__).parents[3] / "config" / "sources" / "registry.v1.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    _federal_register_source(payload)["query"][field] = value
    with pytest.raises(ValueError, match="bounded collection window"):
        load_registry(_write_registry(tmp_path, payload))
