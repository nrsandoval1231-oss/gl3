from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from gridlens.intelligence import demand_summary


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query):
        return _Result(self.rows)


def test_summary_uses_only_current_projection_and_separates_unknown(monkeypatch):
    monkeypatch.setattr(
        demand_summary, "current_generation", lambda _session: SimpleNamespace(id="g")
    )
    project = SimpleNamespace(
        id="p1",
        identity_key="site1",
        region_status="ELIGIBLE",
        identity_facts={},
        asset_type="compressor",
        name="site one",
        location="midland",
    )
    need_known = SimpleNamespace(id="n1", project_id="p1", active=True)
    project2 = SimpleNamespace(
        id="p2",
        identity_key="site2",
        region_status="ELIGIBLE",
        identity_facts={},
        asset_type="compressor",
        name="site two",
        location="odessa",
    )
    need_unknown = SimpleNamespace(id="n2", project_id="p2", active=True)
    monkeypatch.setattr(
        demand_summary,
        "current_equipment_investigations",
        lambda _session, pairs: {
            "n1": {
                "status": "COMPLETE",
                "demand": {"incremental_kw": "1500"},
                "quantity_classification": {"incremental_kw": "CALCULATED"},
                "evidence": [{"source_id": "s", "retrieved_at": "2026-01-01T00:00:00Z"}],
            },
            "n2": {
                "status": "COMPLETE",
                "demand": {"incremental_kw": None},
                "quantity_classification": {"incremental_kw": "UNKNOWN"},
                "evidence": [],
            },
        },
    )
    result = demand_summary.summarize(
        _Session(
            [
                (need_known, project, {"project_metadata": {"sector": "oil_gas"}}, "project:p1"),
                (need_unknown, project2, {"project_metadata": {"sector": "oil_gas"}}, "project:p2"),
            ]
        )
    )
    assert result["availability"] == "available"
    assert result["totals"] == {
        "identified_records": 2,
        "known_mw_records": 1,
        "unknown_records": 1,
        "conflicted_records": 0,
    }
    assert result["classes"]["calculated"] == {"mw": 1.5, "record_count": 1}
    assert result["classes"]["documented"]["mw"] is None
    assert result["provenance"]["source_count"] == 1
    assert (
        result["provenance"]["latest_evidence_at"] == datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    )


def test_summary_does_not_add_multiple_needs_for_same_project(monkeypatch):
    monkeypatch.setattr(
        demand_summary, "current_generation", lambda _session: SimpleNamespace(id="g")
    )
    project = SimpleNamespace(
        id="p",
        identity_key="site",
        region_status="ELIGIBLE",
        identity_facts={},
        asset_type="compressor",
    )
    needs = [SimpleNamespace(id=f"n{i}", project_id="p", active=True) for i in range(2)]
    monkeypatch.setattr(
        demand_summary,
        "current_equipment_investigations",
        lambda *_: {"n0": {"status": "COMPLETE"}},
    )
    result = demand_summary.summarize(
        _Session([(needs[0], project, {}, "project:p"), (needs[1], project, {}, "project:p")])
    )
    assert result["totals"]["identified_records"] == 1
    assert result["totals"]["conflicted_records"] == 1


def test_over_budget_summary_marks_counts_incomplete_and_skips_projection(monkeypatch):
    monkeypatch.setattr(
        demand_summary, "current_generation", lambda _session: SimpleNamespace(id="g")
    )
    project = SimpleNamespace(id="p", region_status="ELIGIBLE")
    rows = [
        (
            SimpleNamespace(id=f"n{i}", project_id="p", active=True),
            project,
            {},
            f"project:p{i}",
        )
        for i in range(demand_summary.MAX_CANDIDATES + 1)
    ]
    monkeypatch.setattr(
        demand_summary,
        "current_equipment_investigations",
        lambda *_: pytest.fail("projection must not run for an over-budget cohort"),
    )
    result = demand_summary.summarize(_Session(rows))
    assert result["availability"] == "unavailable"
    assert result["counts_complete"] is False
