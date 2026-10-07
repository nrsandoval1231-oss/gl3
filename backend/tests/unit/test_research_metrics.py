from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from gridlens.intelligence.research_metrics import (
    evaluation_events,
    metrics_report,
    research_overview,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def pursuit():
    return SimpleNamespace(
        id="pursuit-one",
        snapshot={
            "commercial_triage": {
                "versions": [
                    {
                        "version": 1,
                        "disposition": "RESEARCH",
                        "input_hash": "old",
                        "evaluated_at": (NOW - timedelta(hours=2)).isoformat(),
                        "saved_card": {
                            "id": "need-one",
                            "tier": "Signal",
                            "name": "Project",
                            "sources": [{"evidence_id": "old", "url": "https://example.com/a"}],
                        },
                    },
                    {
                        "version": 2,
                        "disposition": "ACTION NOW",
                        "input_hash": "new",
                        "evaluated_at": NOW.isoformat(),
                        "saved_card": {
                            "id": "need-one",
                            "tier": "Signal",
                            "name": "Project",
                            "reason": "Cited buyer path",
                            "next_action": "Review public contact",
                            "sources": [
                                {"evidence_id": "old", "url": "https://example.com/a"},
                                {"evidence_id": "new", "url": "https://example.com/b"},
                            ],
                        },
                    },
                ]
            }
        },
    )


def question(identity, origin="automatic", cost="0"):
    return SimpleNamespace(
        id=identity,
        pursuit_id="pursuit-one",
        attempt_count=1,
        created_at=NOW - timedelta(hours=1),
        completed_at=NOW,
        status="RESOLVED",
        context={"origin": origin, "before": {"tier": "Signal", "disposition": "RESEARCH"}},
        receipt={
            "before": "RESEARCH",
            "after": "ACTION NOW",
            "tier": "Signal",
            "after_input_hash": "new",
            "cost_usd": cost,
            "reserved_cost_usd": "0.01",
            "runtime_seconds": 2,
            "source_checks": [{"url": "https://example.com/b"}],
        },
    )


def test_two_question_receipts_count_one_actual_pursuit_transition():
    report = metrics_report([], [question("one"), question("two")], [pursuit()])
    assert report["commercial_transitions"] == {"RESEARCH → ACTION NOW": 1}
    assert report["evidence_tier_transitions"] == {}
    assert report["blockers_attempted"] == 2
    assert report["automatically_investigated_pursuits"] == 1


def test_manual_validation_and_unknown_origins_are_not_called_automatic():
    rows = [question("one", "manual"), question("two", "validation")]
    rows.append(question("three"))
    rows[-1].context = {}
    report = metrics_report([], rows, [pursuit()])
    assert report["automatically_investigated_pursuits"] == 0
    assert report["attempted_question_origins"] == {"manual": 1, "validation": 1, "unknown": 1}


def test_unknown_actual_billing_is_not_reported_as_reserved_cost_or_zero_average():
    report = metrics_report([], [question("one", cost=None)], [pursuit()])
    assert report["attempts_with_unknown_actual_cost"] == 1
    assert report["average_actual_cost_per_pursuit_usd"] is None
    assert report["reserved_cost_usd"] == "0.01"


def test_missing_historical_tier_does_not_invent_promotion_and_duplicate_version_ignored():
    saved = pursuit()
    versions = saved.snapshot["commercial_triage"]["versions"]
    versions[0]["saved_card"] = None
    versions[1]["saved_card"]["tier"] = "Prospect"
    versions.append(dict(versions[1]))
    report = metrics_report([], [], [saved])
    assert report["commercial_transitions"] == {"RESEARCH → ACTION NOW": 1}
    assert report["evidence_tier_transitions"] == {}
    assert len(evaluation_events([saved])) == 1


def test_morning_items_use_saved_evidence_diff_and_correlate_completed_research_once():
    report = research_overview(
        [], [question("one"), question("two")], [pursuit()], NOW - timedelta(hours=1)
    )
    assert len(report["items"]) == 1
    item = report["items"][0]
    assert item["id"] == "pursuit-one:2"
    assert item["question_ids"] == ["one", "two"]
    assert [source["evidence_id"] for source in item["new_evidence"]] == ["new"]
    assert item["next_action"] == "Review public contact"
    assert report["summary"]["commercial_transitions"] == {"RESEARCH → ACTION NOW": 1}


def test_earlier_manual_evaluation_is_not_attributed_to_later_research():
    row = question("later")
    row.created_at = NOW + timedelta(hours=1)
    row.completed_at = NOW + timedelta(hours=2)
    report = research_overview([], [row], [pursuit()])
    assert report["items"] == []
    assert report["summary"]["commercial_transitions"] == {}


def test_same_disposition_evidence_update_is_visible_without_transition_count():
    saved = pursuit()
    saved.snapshot["commercial_triage"]["versions"][1]["disposition"] = "RESEARCH"
    report = research_overview([], [question("one")], [saved])
    assert len(report["items"]) == 1
    assert report["items"][0]["before"] == report["items"][0]["after"] == "RESEARCH"
    assert report["summary"]["commercial_transitions"] == {}


def test_evaluation_time_filters_transitions_independently_of_question_creation():
    report = metrics_report([], [], [pursuit()], NOW + timedelta(seconds=1))
    assert report["commercial_transitions"] == {}


def test_old_queued_question_completed_today_is_included_without_inventing_attempt_time():
    row = question("old")
    row.created_at = NOW - timedelta(days=7)
    result = metrics_report([], [row], [], NOW - timedelta(hours=1))
    assert result["blockers_attempted"] == 1
    assert "cumulative" in result["question_time_basis"]


def test_recorded_attempt_in_window_counts_running_old_question():
    row = question("running")
    row.created_at = NOW - timedelta(days=7)
    row.completed_at = None
    row.status = "SEARCHING"
    row.receipt["latest_attempt_at"] = NOW.isoformat()
    assert metrics_report([], [row], [], NOW - timedelta(hours=1))["blockers_attempted"] == 1
