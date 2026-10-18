from datetime import date

from gridlens.integrations import intelligence_provider
from gridlens.intelligence.signal_adjudication import (
    MODEL,
    _jev_call,
    deterministic_override,
    map_dimensions,
)


def test_jev_uses_pinned_model_one_call_and_typed_dimensions(monkeypatch):
    captured = {}

    def post(*, api_key, model, payload, **_kwargs):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["payload"] = payload
        return {"model": MODEL, "answers": {}}

    monkeypatch.setattr(intelligence_provider, "call_typesafe", post)
    state = {
        "title": "A retained event",
        "abstract": "An excerpt",
        "url": "https://example.test/event",
        "published_at": "2026-09-29",
        "source_id": "test-source",
        "source_family": "news",
        "publisher": "Test publisher",
        "event_date": "unknown",
        "event_date_label": "unknown",
        "project_name": "Test project",
        "location": "Austin, TX",
        "asset_type": "data center",
        "lifecycle_state": "construction",
    }
    result = _jev_call(state, "test-secret")

    assert result["model"] == MODEL
    assert captured["api_key"] == "test-secret"
    assert captured["model"] == "jev-1.13.0"
    expected = {
        "physical_project_event",
        "meaningful_new_activity",
        "commercial_relevance",
        "temporary_power_relevance",
        "routine_maintenance",
        "transient_event",
    }
    assert set(captured["payload"]["questions"]) == expected
    assert all(q["type"] == "noul" for q in captured["payload"]["questions"].values())
    assert "display" not in captured["payload"]["questions"]
    assert captured["payload"]["state"]["publisher"] == "Test publisher"


def test_gl3_policy_holds_transient_or_routine_items_and_shows_supported_activity():
    base = {
        "physical_project_event": 0.95,
        "meaningful_new_activity": 0.95,
        "commercial_relevance": 0.9,
        "temporary_power_relevance": 0.9,
        "routine_maintenance": 0.05,
        "transient_event": 0.02,
    }
    assert map_dimensions(base) == "SHOW"
    assert map_dimensions({**base, "transient_event": 0.95}) == "HOLD"
    assert (
        map_dimensions({**base, "meaningful_new_activity": 0.1, "routine_maintenance": 0.92})
        == "HOLD"
    )
    assert map_dimensions({**base, "temporary_power_relevance": 0.2}) == "SHOW"
    assert map_dimensions({**base, "commercial_relevance": 0.5}) == "REVIEW"


def test_gl3_policy_uses_source_context_for_generic_buildings_and_power_relevant_projects():
    base = {
        "physical_project_event": 0.95,
        "meaningful_new_activity": 0.95,
        "commercial_relevance": 0.85,
        "temporary_power_relevance": 0.3,
        "routine_maintenance": 0.05,
        "transient_event": 0.02,
    }
    assert map_dimensions(base, title="New construction of office warehouse") == "REVIEW"
    assert map_dimensions(base, title="Addition and remodel to existing hospital") == "REVIEW"
    assert (
        map_dimensions(
            base,
            title="Interior and exterior alterations to existing manufacturing facility",
        )
        == "REVIEW"
    )
    assert (
        map_dimensions(
            {**base, "commercial_relevance": 0.62}, title="Additional emergency generators"
        )
        == "REVIEW"
    )
    assert (
        map_dimensions(
            {**base, "commercial_relevance": 0.62},
            title="Additional emergency generators at a data center",
            abstract=(
                "Construction and operation of additional emergency generators with no change "
                "in the facility-wide fuel consumption limit."
            ),
        )
        == "REVIEW"
    )
    assert (
        map_dimensions(
            base,
            title="Finish out to expand data center into existing shell areas",
        )
        == "SHOW"
    )
    assert (
        map_dimensions(
            {**base, "commercial_relevance": 0.38},
            title="Renewable natural gas facility construction",
        )
        == "SHOW"
    )
    assert (
        map_dimensions(
            {**base, "physical_project_event": 0.76, "commercial_relevance": 0.79},
            title="Manufacturing expansion",
        )
        == "SHOW"
    )


def test_deterministic_hold_grammar_is_event_or_like_for_like_specific():
    assert deterministic_override("temporary stage for one-day event", None, "")
    assert deterministic_override("Zilker Park marathon", None, "")
    assert deterministic_override("permanent stage construction", None, "") is None
    assert deterministic_override("like-for-like generator replacement", None, "")
    assert deterministic_override("new backup generators for a data center", None, "") is None
    assert deterministic_override("project construction begins", date.today(), "https://x") is None
    show = deterministic_override(
        "Data center construction begins today", date.today(), "https://example.test/project"
    )
    assert show is not None and show[0] == "SHOW"
