from copy import deepcopy

import pytest

from gridlens.domain.pursuit_research import ROUTES, fingerprint, plan_questions, targeted_queries
from gridlens.intelligence.autonomous_research import blocker_resolved


def card(**overrides):
    return {
        "disposition": "RESEARCH",
        "facts": [],
        "stage": {"stage": "unknown"},
        "contacts": [],
        "activity": "construction",
        "supply": "Unknown",
        **overrides,
    }


def test_planner_prioritizes_two_commercial_blockers_and_replays_without_mutating_input():
    item = card()
    before = deepcopy(item)
    result = plan_questions(item)
    assert [q["category"] for q in result] == ["power_need", "phase"]
    assert all(q["question"] and q["why"] and q["source_families"] for q in result)
    assert plan_questions(item) == result
    assert item == before


@pytest.mark.parametrize("disposition", ["ACTION NOW", "REJECT"])
def test_closed_or_actionable_pursuits_do_not_spawn_questions(disposition):
    assert plan_questions(card(disposition=disposition)) == []


def test_known_temporary_power_and_reachable_buyer_are_excluded():
    item = card(
        facts=[
            {"text": "Temporary power for this construction activity", "evidence_id": "citation"}
        ],
        stage={"stage": "construction"},
        contacts=[{"kind": "public project phone", "value": "5125550100"}],
    )
    assert [q["category"] for q in plan_questions(item)] == ["timing", "load"]


@pytest.mark.parametrize(
    "stage",
    [
        "permitting evidence; construction not established",
        "construction-related source evidence; work underway not confirmed",
        "commissioning-related source evidence; actual activity not confirmed",
    ],
)
def test_actual_commercial_stage_labels_preserve_unconfirmed_phase(stage):
    result = plan_questions(
        card(
            facts=[{"text": "Temporary service", "evidence_id": "citation"}], stage={"stage": stage}
        )
    )
    assert result[0]["category"] == "phase"
    assert not blocker_resolved("commissioning", {"stage": {"stage": stage, "evidence_id": "x"}})


@pytest.mark.parametrize(
    ("category", "first", "second"),
    [
        ("buyer", "retained-permits", "permit-organizations"),
        ("supply", "utility-filings", "interconnection-documents"),
        ("load", "activity-electrical-permits", "temporary-service-permits"),
        ("commissioning", "electrical-testing-permits", "commissioning-contractors"),
    ],
)
def test_routes_prioritize_specific_authoritative_families(category, first, second):
    assert ROUTES[category][:2] == (first, second)


def test_queries_use_exact_site_and_permit_before_broadening():
    context = {"site_address": "400 S LaSalle", "stable_identifiers": ["100991234"]}
    queries = targeted_queries(context, "buyer")
    assert len(queries) == len(set(queries)) == 3
    assert all('"400 S LaSalle"' in q or '"100991234"' in q for q in queries)
    assert targeted_queries({}, "buyer") == []
    assert fingerprint(context) == fingerprint(dict(reversed(list(context.items()))))
    assert fingerprint(context) != fingerprint({**context, "stable_identifiers": ["other"]})


def test_construction_cannot_resolve_commissioning_and_empty_search_is_not_false_evidence():
    item = {"stage": {"stage": "construction", "evidence_id": "accepted-id"}, "tier": "Signal"}
    assert not blocker_resolved("commissioning", item)
    assert not blocker_resolved("supply", item)
    assert not blocker_resolved("power_need", item)
    assert not blocker_resolved("load", item)


def test_acquisition_lock_does_not_wait_for_another_question():
    from unittest.mock import Mock

    import pytest

    from gridlens.intelligence.autonomous_research import AcquisitionBusy, _lock_acquisition

    session = Mock()
    session.scalar.return_value = False
    with pytest.raises(AcquisitionBusy):
        _lock_acquisition(session, "same-url")
    assert "pg_try_advisory_xact_lock" in str(session.scalar.call_args.args[0])
    session.scalar.return_value = True
    _lock_acquisition(session, "same-url")


@pytest.mark.parametrize("text", ["Temporary power is unknown", "No temporary service is required"])
def test_unknown_or_negated_scope_is_not_a_known_fact(text):
    item = card(facts=[{"text": text, "evidence_id": "citation"}])
    assert plan_questions(item)[0]["category"] == "power_need"
    assert not blocker_resolved("power_need", item)
