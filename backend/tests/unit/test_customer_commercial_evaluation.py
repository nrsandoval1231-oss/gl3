"""Metric controls for the real-source evaluation, independent of parser heuristics."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "evaluate_customer_commercial.py"


@pytest.fixture
def evaluation():
    spec = importlib.util.spec_from_file_location("customer_commercial_evaluation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capacity_wrong_basis_or_phase_is_not_credit(evaluation):
    gold = {"value_mw": "100", "type": "it_load", "evaluation_scope": "phase:1"}
    right = {"value_mw": "100.0", "basis": "it_load", "scope_id": "p:phase:i"}
    assert evaluation.capacity_matches(gold, right, "p")
    assert not evaluation.capacity_matches(gold, {**right, "basis": "utility_service"}, "p")
    assert not evaluation.capacity_matches(gold, {**right, "scope_id": "p:site"}, "p")
    assert not evaluation.capacity_matches(gold, {**right, "value_mw": "101"}, "p")


def test_repeated_predictions_cannot_inflate_recall(evaluation):
    score = evaluation.score_claims(
        [{"value": 1}], [{"value": 1}, {"value": 1}], lambda g, p: g == p
    )
    assert (score["true_positive"], score["false_positive"], score["false_negative"]) == (1, 1, 0)
    assert score["precision"] == 0.5
    assert score["recall"] == 1


def test_material_qualifiers_cannot_be_scored_as_exact_delivered_capacity(evaluation):
    gold = {"value_mw": "400", "type": "utility_service_capacity", "evaluation_scope": "site"}
    point = {
        "value_mw": "400",
        "basis": "utility_service",
        "scope_id": "p:site",
        "qualifier": "exact",
    }
    assert not evaluation.capacity_matches({**gold, "qualifier": "substation_rating"}, point, "p")
    assert not evaluation.capacity_matches(
        {**gold, "qualifier": "1plus_under_load_study"}, point, "p"
    )
    assert not evaluation.capacity_matches({**gold, "qualifier": "more_than"}, point, "p")
    assert evaluation.capacity_matches(
        {**gold, "qualifier": "more_than"}, {**point, "qualifier": "more_than"}, "p"
    )


def test_one_to_one_matching_finds_valid_reassignment(evaluation):
    score = evaluation.score_claims(
        ["flexible", "only_a"], ["a", "b"], lambda g, p: g == "flexible" or p == "a"
    )
    assert score["true_positive"] == 2
    assert score["false_positive"] == score["false_negative"] == 0


def test_no_predictions_has_undefined_precision_and_zero_supported_recall(evaluation):
    score = evaluation.score_claims([1, 2], [], lambda g, p: g == p)
    assert score["precision"] is None
    assert score["recall"] == 0
    assert score["false_negative"] == 2
    assert evaluation.score_claims([], [], lambda g, p: g == p)["recall"] is None


def test_timeline_precision_kind_scope_and_deadline_are_preserved(evaluation):
    gold = {
        "kind": "expected_first_energization",
        "value": "2027-Q3",
        "precision": "quarter",
        "evaluation_scope": "site",
    }
    right = {
        "event_type": "expected_first_energization",
        "label": "Q3 2027",
        "precision": "quarter",
        "scope_id": "p:site",
    }
    assert evaluation.timeline_matches(gold, right, "p")
    assert evaluation.timeline_matches(gold, {**right, "qualifier": "within"}, "p")
    assert evaluation.timeline_matches(
        {**gold, "qualifier": "at_or_before"}, {**right, "qualifier": "deadline"}, "p"
    )
    assert not evaluation.timeline_matches(gold, {**right, "qualifier": "deadline"}, "p")
    assert not evaluation.timeline_matches(
        {**gold, "qualifier": "at_or_before"}, {**right, "qualifier": "within"}, "p"
    )
    assert evaluation.timeline_matches(gold, {**right, "label": "third quarter of 2027"}, "p")
    assert evaluation.normalized_date("first half of 2025", "half_year") == "2025-h1"
    assert not evaluation.timeline_matches(
        gold, {**right, "event_type": "full_operational_target"}, "p"
    )
    assert not evaluation.timeline_matches(
        gold, {**right, "precision": "day", "label": "2027-07-01"}, "p"
    )
    assert not evaluation.timeline_matches(gold, {**right, "scope_id": "p:phase:1"}, "p")
    assert not evaluation.timeline_matches({**gold, "qualifier": "at_or_before"}, right, "p")


def test_ordinary_operational_target_and_deadline_keep_their_meaning(evaluation):
    gold = {
        "kind": "operational_target",
        "value": "2026-Q4",
        "precision": "quarter",
        "evaluation_scope": "site",
        "qualifier": "at_or_before",
    }
    predicted = {
        "event_type": "operational_target",
        "label": "fourth quarter of 2026",
        "precision": "quarter",
        "scope_id": "p:site",
        "qualifier": "deadline",
    }
    assert evaluation.timeline_matches(gold, predicted, "p")
    assert not evaluation.timeline_matches(
        gold, {**predicted, "event_type": "full_operational_target"}, "p"
    )
    ready = {**gold, "kind": "ready_for_service_target"}
    assert evaluation.timeline_matches(
        ready, {**predicted, "event_type": "ready_for_service_target"}, "p"
    )
    assert not evaluation.timeline_matches(
        ready, {**predicted, "event_type": "expected_first_energization"}, "p"
    )


def test_source_only_predictions_ignore_changed_reference_facts(evaluation, tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "source.json").write_text(
        json.dumps(
            {
                "url": "https://example.org/project",
                "excerpts": ["IT load is 12 MW."],
                "observation_date": "2026-11-12",
                "publication_date_metadata": None,
            }
        )
    )
    record = {
        "id": "fixture-case",
        "project": "Example project",
        "location": "Example City",
        "sources": [["source", "2026-11-11"]],
        "capacity": [{"value_mw": "999999"}],
        "timeline": [{"value": "2099"}],
    }
    original = evaluation.predict_record(record, tmp_path, as_of=date(2026, 11, 12))
    changed = evaluation.predict_record(
        {**record, "capacity": [], "timeline": [], "contacts": [{"name": "Fictional"}]},
        tmp_path,
        as_of=date(2026, 11, 12),
    )
    assert original == changed
    assert original["raw_capacity_claims"][0]["value_mw"] == "12"
    assert original["raw_capacity_claims"][0]["source"]["published_at"] == "2026-11-11"
    assert "999999" not in json.dumps(original)


def test_source_artifact_corruption_is_rejected(evaluation, tmp_path):
    (tmp_path / "source.json").write_text("changed")
    (tmp_path / "source-hashes.json").write_text(
        json.dumps([{"file": "source.json", "sha256": "0" * 64}])
    )
    with pytest.raises(ValueError, match="Retained source artifact changed"):
        evaluation.verify_sources(tmp_path)


def test_provenance_accepts_unknown_publication_but_rejects_missing_trace(evaluation):
    source = {
        "url": "https://example.org",
        "evidence_id": "s",
        "content_hash": "a",
        "observed_at": "2026-11-12",
        "published_at": None,
        "authority": "primary",
    }
    claim = {
        "source": source,
        "extraction_method": "versioned-parser",
        "project_id": "p",
        "status": "reported",
        "quote": "IT load is 12 MW.",
    }
    assert evaluation.provenance_complete(claim)
    for key in ("evidence_id", "content_hash", "observed_at", "published_at"):
        assert not evaluation.provenance_complete(
            {**claim, "source": {k: v for k, v in source.items() if k != key}}
        )
