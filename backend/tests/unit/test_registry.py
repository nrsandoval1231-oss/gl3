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
