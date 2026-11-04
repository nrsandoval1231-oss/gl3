"""WS6 runtime: clock-time schedules, document-source health findings, run summaries, job keys.

Pure unit tests: no database, no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from gridlens.ingestion.document_health import build_run_summary, summarize_states
from gridlens.ingestion.registry import _validate_run_at
from gridlens.jobs import document_alerts as da
from gridlens.jobs.alerts import summarize
from gridlens.jobs.document_extraction import (
    _cap_fields,
    document_job_key,
    merge_pending,
    validators_digest,
)
from gridlens.jobs.worker import _scheduled_instants

CHICAGO = ZoneInfo("America/Chicago")


def epoch(
    *,
    start: datetime,
    anchor_date: str,
    anchor_time: str = "07:00:00",
    cadence: int = 24,
    configuration: dict | None = None,
):
    return SimpleNamespace(
        id="e1",
        source_id="s",
        cadence_hours=cadence,
        schedule_mode="local_daily",
        effective_from=start,
        effective_until=None,
        anchor={"local_date": anchor_date, "local_time": anchor_time},
        timezone="America/Chicago",
        configuration=configuration or {},
    )


def local(instants):
    return [i.astimezone(CHICAGO).strftime("%Y-%m-%d %H:%M") for i in instants]


def test_without_run_at_the_single_anchor_time_is_unchanged():
    e = epoch(start=datetime(2026, 11, 1, tzinfo=UTC), anchor_date="2026-11-01")
    got = list(_scheduled_instants(e, datetime(2026, 11, 4, 12, tzinfo=UTC)))
    assert local(got) == ["2026-11-01 07:00", "2026-11-02 07:00", "2026-11-03 07:00"]


def test_run_at_gives_nightly_and_midday_slots_in_local_time():
    e = epoch(
        start=datetime(2026, 11, 1, tzinfo=UTC),
        anchor_date="2026-11-01",
        configuration={"run_at": ["12:00", "03:30"]},
    )
    got = list(_scheduled_instants(e, datetime(2026, 11, 3, 12, tzinfo=UTC)))
    assert local(got) == [
        "2026-11-01 03:30",
        "2026-11-01 12:00",
        "2026-11-02 03:30",
        "2026-11-02 12:00",
        "2026-11-03 03:30",
    ]


def test_run_at_follows_daylight_saving_time_both_ways():
    # Spring forward 2027-03-14: 02:30 does not exist, 03:30 CDT is used; 03:30 is always valid.
    spring = epoch(
        start=datetime(2027, 3, 12, tzinfo=UTC),
        anchor_date="2027-03-12",
        configuration={"run_at": ["02:30", "12:00"]},
    )
    got = list(_scheduled_instants(spring, datetime(2027, 3, 16, tzinfo=UTC)))
    by_day = {i.astimezone(CHICAGO).date().isoformat(): [] for i in got}
    for instant in got:
        by_day[instant.astimezone(CHICAGO).date().isoformat()].append(instant)
    assert len(by_day["2027-03-14"]) == 2  # the skipped wall time still yields one slot
    assert sorted(i.astimezone(UTC).hour for i in by_day["2027-03-13"]) == [8, 18]  # CST
    assert sorted(i.astimezone(UTC).hour for i in by_day["2027-03-15"]) == [7, 17]  # CDT
    # Fall back 2026-11-01: 01:30 happens twice; exactly one slot per day, fold=0.
    fall = epoch(
        start=datetime(2026, 10, 30, tzinfo=UTC),
        anchor_date="2026-10-30",
        configuration={"run_at": ["01:30"]},
    )
    got = list(_scheduled_instants(fall, datetime(2026, 11, 4, tzinfo=UTC)))
    assert len(got) == len({i.astimezone(CHICAGO).date() for i in got}) == 5
    assert local(got)[0].endswith("01:30") and local(got)[-1].endswith("01:30")


def test_run_weekday_pins_a_weekly_source():
    # 2026-11-04 is a Wednesday; pin to Sunday (6) with a one-week cadence.
    e = epoch(
        start=datetime(2026, 11, 4, tzinfo=UTC),
        anchor_date="2026-11-04",
        cadence=168,
        configuration={"run_at": ["04:00"], "run_weekday": 6},
    )
    got = list(_scheduled_instants(e, datetime(2026, 12, 1, tzinfo=UTC)))
    assert local(got) == [
        "2026-11-08 04:00",
        "2026-11-15 04:00",
        "2026-11-22 04:00",
        "2026-11-29 04:00",
    ]
    assert all(i.astimezone(CHICAGO).weekday() == 6 for i in got)


def test_slots_respect_the_lower_bound_and_end():
    e = epoch(
        start=datetime(2026, 11, 1, tzinfo=UTC),
        anchor_date="2026-11-01",
        configuration={"run_at": ["03:30", "12:00"]},
    )
    lower = datetime(2026, 11, 2, 17, tzinfo=UTC)  # after the 11:00 CST midday... 12:00 CST
    got = list(_scheduled_instants(e, datetime(2026, 11, 4, tzinfo=UTC), not_before=lower))
    assert all(i >= lower for i in got) and got == sorted(got)


@pytest.mark.parametrize(
    "source",
    [
        {"run_at": ["03:30"]},
        {"run_at": ["03:30", "12:00"]},
        {"run_at": ["04:00"], "run_weekday": 0, "cadence_hours": 168},
    ],
)
def test_registry_accepts_valid_run_at(source):
    cadence = source.get("cadence_hours", 24)
    _validate_run_at(source, "local_daily", cadence)


@pytest.mark.parametrize(
    ("source", "mode", "cadence"),
    [
        ({"run_at": ["03:30"]}, "utc_hourly", 12),
        ({"run_at": []}, "local_daily", 24),
        ({"run_at": ["25:00"]}, "local_daily", 24),
        ({"run_at": ["03:30", "03:30"]}, "local_daily", 24),
        ({"run_at": ["03:30+00:00"]}, "local_daily", 24),
        ({"run_at": "03:30"}, "local_daily", 24),
        ({"run_weekday": 7}, "local_daily", 168),
        ({"run_weekday": 2}, "local_daily", 24),
    ],
)
def test_registry_rejects_invalid_run_at(source, mode, cadence):
    with pytest.raises(ValueError):
        _validate_run_at(source, mode, cadence)


def test_registry_without_the_fields_is_untouched():
    _validate_run_at({}, "utc_hourly", 6)


# ---------------------------------------------------------------- health findings

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def run(**kw):
    base = {"at": (NOW - timedelta(hours=1)).isoformat(), "docs": 0, "in_scope": 10}
    base.update(kw)
    return base


def codes(findings):
    return sorted(f.code for f in findings)


def evaluate(runs, **kw):
    return da.evaluate(
        "texas-tceq-nsr-pending",
        runs,
        cadence_hours=24,
        now=NOW,
        thresholds=da.Thresholds(),
        **kw,
    )


def test_a_healthy_source_has_no_findings():
    runs = [run(docs=2, verified_rows=6, rejected_rows=1) for _ in range(6)]
    assert evaluate(runs, new_observations_recent=3, observations_total=40) == []


def test_wrong_content_type_and_js_shell_are_reported_from_the_latest_run():
    assert codes(evaluate([run(failures={"js_shell": 2})])) == [da.WRONG_CONTENT_TYPE]
    assert codes(evaluate([run(failures={"wrong_content_type": 1})])) == [da.WRONG_CONTENT_TYPE]
    assert evaluate([run(failures={"js_shell": 1}), run()]) == []  # cleared in the latest run


def test_empty_text_layer_counts_failures_and_scanned_documents():
    runs = [run(docs=1, empty_text_docs=1, failures={"empty_text_layer": 1}), run(docs=1)]
    found = evaluate(runs)
    assert codes(found) == [da.EMPTY_TEXT_LAYER]
    assert found[0].values == {"empty": 2, "documents": 3}
    assert evaluate([run(docs=3, empty_text_docs=1)]) == []  # a minority is not an alert


def test_yield_drop_needs_a_baseline_and_a_real_fall():
    baseline = [run(docs=3, verified_rows=12) for _ in range(3)]  # 4 rows per document
    recent_bad = [run(docs=2, verified_rows=2) for _ in range(3)]  # 1 row per document
    assert codes(evaluate(baseline + recent_bad)) == [da.YIELD_DROP]
    recent_ok = [run(docs=2, verified_rows=7) for _ in range(3)]
    assert evaluate(baseline + recent_ok) == []
    assert evaluate(recent_bad) == []  # no baseline: no claim


def test_verifier_rejection_spike():
    runs = [run(docs=2, verified_rows=3, rejected_rows=12)]
    found = evaluate(runs)
    assert da.REJECTION_SPIKE in codes(found)
    assert evaluate([run(docs=2, verified_rows=1, rejected_rows=2)]) == []  # too few rows


def test_listing_shrink_from_the_notice_or_the_counts():
    assert codes(evaluate([run(in_scope=40), run(in_scope=10)])) == [da.LISTING_SHRINK]
    assert codes(evaluate([run(in_scope=40), run(in_scope=39, notices={"listing_shrink": 1})])) == [
        da.LISTING_SHRINK
    ]
    assert evaluate([run(in_scope=40), run(in_scope=30)]) == []


def test_overdue_uses_the_cadence_multiplier():
    old = (NOW - timedelta(hours=24 * 3)).isoformat()
    assert codes(evaluate([run(at=old)])) == [da.OVERDUE]
    fresh = (NOW - timedelta(hours=40)).isoformat()
    assert evaluate([run(at=fresh)]) == []


def test_zero_new_records():
    found = evaluate([run()], new_observations_recent=0, observations_total=12)
    assert codes(found) == [da.ZERO_NEW_RECORDS]
    assert evaluate([run()], new_observations_recent=0, observations_total=0) == []
    assert evaluate([run()], new_observations_recent=None, observations_total=12) == []


def test_findings_are_visible_in_the_daily_message_and_make_it_urgent():
    health = {"sources": [], "worker_liveness": "LIVE", "backlog": 0}
    found = evaluate([run(failures={"js_shell": 1})])
    title, body, urgent = summarize(health, {}, None, found)
    assert urgent and "wrong_content_type" in body and "texas-tceq-nsr-pending" in body
    assert summarize(health, {}, None, [])[2] is False


def test_thresholds_come_from_settings():
    limit = da.Thresholds.from_settings()
    assert 0 < limit.yield_drop_ratio < 1 and limit.zero_new_days >= 1


# ---------------------------------------------------------------- summaries and keys


def state(pages=4, scanned=0, verified=3, rejected=1, proposer=None, ocr=None):
    extraction = {
        "pages": pages,
        "scanned_pages": scanned,
        "verified_rows": verified,
        "rejected_rows": rejected,
    }
    if proposer:
        extraction["proposer"] = {"status": proposer}
    if ocr:
        extraction["ocr"] = {"status": ocr}
    return {"document": {"extraction": extraction}}


def test_summarize_states_aggregates_counts_and_pass_statuses():
    out = summarize_states(
        [state(), state(pages=2, scanned=2, verified=0), state(proposer="ok", ocr="capped_out")]
    )
    assert out["docs"] == 3 and out["empty_text_docs"] == 1
    assert out["verified_rows"] == 6 and out["rejected_rows"] == 3
    assert out["proposer"] == {"ok": 1} and out["ocr"] == {"capped_out": 1}


def test_build_run_summary_splits_failures_and_notices_and_is_json_safe():
    summary = build_run_summary(
        "discovery",
        {"in_scope": 7, "enqueued": 2, "failure_js_shell": 1, "notice_listing_shrink": 1},
        [state()],
        at=NOW,
    )
    assert summary["failures"] == {"js_shell": 1} and summary["notices"] == {"listing_shrink": 1}
    assert summary["enqueued"] == 2 and summary["docs"] == 1
    json.dumps(summary)


def test_job_key_is_stable_per_document_version():
    a = validators_digest({"etag": '"v1"', "content_length": 10}, "2026-11-04")
    b = validators_digest({"etag": '"v2"', "content_length": 10}, "2026-11-04")
    key = document_job_key("s", "900001", "https://x/y.pdf", a)
    assert key == document_job_key("s", "900001", "https://x/y.pdf", a)
    assert key != document_job_key("s", "900001", "https://x/y.pdf", b)
    assert key != document_job_key("s", "900002", "https://x/y.pdf", a)
    # No validators: at most one job per document per day.
    assert validators_digest(None, "2026-11-04") == validators_digest(None, "2026-11-04")
    assert validators_digest(None, "2026-11-04") != validators_digest(None, "2026-11-05")


def test_capped_out_fields_are_lifted_from_the_pass_result():
    assert _cap_fields({}) == {}
    assert _cap_fields({"proposer": {"status": "ok"}}) == {}
    fields = _cap_fields(
        {"ocr": {"status": "capped_out", "cap_scope": "provider", "cap_period": "daily"}}
    )
    assert fields["capped_out"] is True and fields["cap_pass"] == "ocr"
    assert fields["cap_scope"] == "provider" and fields["cap_period"] == "daily"


def test_pending_state_wins_only_when_strictly_newer():
    def doc(sha, at):
        return {"document": {"sha256": sha, "fetched_at": at}}

    old, new = (
        doc("a" * 64, "2026-11-01T00:00:00+00:00"),
        doc("b" * 64, "2026-11-02T00:00:00+00:00"),
    )
    merged, taken = merge_pending({"1": old}, {"1": new, "2": new})
    assert merged["1"] is new and merged["2"] is new and taken == 2
    merged, taken = merge_pending({"1": new}, {"1": old})
    assert merged["1"] is new and taken == 0  # an older job result never replaces evidence
    merged, taken = merge_pending({"1": new}, {"1": dict(new)})
    assert taken == 0  # already folded
