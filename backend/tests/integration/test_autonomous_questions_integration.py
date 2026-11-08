from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from db_reset import reset_test_database
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.commercial_triage import build_card
from gridlens.intelligence.pursuit_questions import schedule_questions
from gridlens.jobs.queue import lease_one
from gridlens.jobs.retry import jittered_delay_seconds
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    Interpretation,
    Job,
    LogicalCall,
    LogicalCallBudget,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    PursuitResearchQuestion,
    SignalDecision,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


def approve_test_host(monkeypatch, hostname, *, modes=("direct",)):
    import json

    instant = datetime.now(UTC)
    monkeypatch.setattr(
        settings,
        "public_research_site_permissions",
        json.dumps(
            [
                {
                    "hostname": hostname,
                    "terms_review_ref": "synthetic-test-approval",
                    "reviewed_at": (instant - timedelta(days=1)).isoformat(),
                    "expires_at": (instant + timedelta(days=1)).isoformat(),
                    "modes": list(modes),
                }
            ]
        ),
    )


@pytest.fixture
def runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    worker = import_module("gridlens.intelligence.autonomous_research")
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    question_scheduler = import_module("gridlens.intelligence.pursuit_questions")
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(
        api, "_unpatched_commercial_triage_cards", api._commercial_triage_cards, raising=False
    )
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(legacy_calls, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(
        question_scheduler,
        "evaluate_targets",
        lambda session, need_ids, **_kwargs: {
            str(need_id): worker.evaluate_target(session, need_id) for need_id in need_ids
        },
    )
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 100)
    with factory.begin() as session:
        session.add(
            Source(
                id="austin-building-permits",
                publisher="Synthetic tests",
                endpoint="https://example.invalid/",
                family="construction-permits",
                geography="Austin",
                industries=[],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        project = Project(
            source_id="austin-building-permits",
            external_id="2026-100001 EP",
            name="Synthetic Orion",
            location="100 ORION LN, Austin, TX",
            identity_facts={"site": "100 ORION LN, Austin, TX"},
            identity_key="orion",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic test need",
            supply="Unknown",
        )
        session.add(need)
        session.flush()
        item = {
            "id": need.id,
            "project_id": project.id,
            "name": project.name,
            "location": "Austin, TX",
            "tier": "Signal",
            "activity": "electrical-construction",
            "asset_type": "data_center",
            "lifecycle_state": "permitting",
            "lifecycle_timeline": [],
            "required_mw": None,
            "start_window": None,
            "duration": None,
            "supply": "Unknown",
            "conflict_state": "Not assessed",
            "missing_facts": ["buyer or responsible operator"],
            "supported_action": "Data center electrical construction includes transformers",
            "signal_display_decision": "REVIEW",
            "evidence": [
                {
                    "id": uuid4(),
                    "title": "Synthetic current permit",
                    "abstract": "Data center electrical construction includes transformers",
                    "url": "https://example.invalid/permit",
                    "content_hash": "a" * 64,
                    "event_date": "2026-10-01",
                    "source_id": project.source_id,
                    "document_number": project.external_id,
                }
            ],
        }
    card = build_card(item, {"candidates": [], "permit_summaries": []}, date(2026, 10, 3))
    assert card["disposition"] == "RESEARCH"
    monkeypatch.setattr(api, "_commercial_triage_cards", lambda *_args: [card])
    monkeypatch.setattr(worker, "evaluate_target", lambda _session, _need: card)
    monkeypatch.setattr(settings, "firecrawl_api_key", None)
    yield factory, worker, api, card
    engine.dispose()


def enable_fake_firecrawl(monkeypatch, factory, question_id):
    """Enable finite ledger dispatch while acquisition adapters remain test fakes."""
    from decimal import Decimal

    from pydantic import SecretStr

    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(
        settings,
        "intelligence_enabled_contracts",
        "FIRECRAWL_SEARCH_V2,FIRECRAWL_SCRAPE_V2",
    )
    monkeypatch.setattr(settings, "intelligence_research_enabled", True)
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 2)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.1"))
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    monkeypatch.setattr(settings, "autonomous_research_max_searches", 2)
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_calls", 10)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_calls", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", Decimal("1"))
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", Decimal("10"))
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("synthetic-test-only"))
    monkeypatch.setattr(settings, "firecrawl_search_cost_usd", Decimal("0.001"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        question.budget = {
            **question.budget,
            "max_cost_usd": "1",
            "searches": 2,
            "documents": 2,
            "urls": 4,
        }


def schedule(factory, card, **kwargs):
    with factory.begin() as session:
        return [q.id for q in schedule_questions(session, [card], **kwargs)]


def schedule_legacy_two_category_plan(factory, card, **kwargs):
    """Pin cache/retry tests to the historical two-category planner contract."""
    scheduler = import_module("gridlens.intelligence.pursuit_questions")
    original_plan = scheduler.plan_questions

    def plan_two(card, **plan_kwargs):
        return original_plan(card, **{**plan_kwargs, "limit": 2})

    scheduler.plan_questions = plan_two
    try:
        return schedule(factory, card, **kwargs)
    finally:
        scheduler.plan_questions = original_plan


def finish_questions(factory, ids):
    with factory.begin() as session:
        for question_id in ids:
            row = session.get(PursuitResearchQuestion, question_id)
            row.status = "UNRESOLVED"
            row.completed_at = datetime.now(UTC)
            row.retry_after = datetime.now(UTC) + timedelta(hours=24)
            row.receipt = {
                **row.receipt,
                "route_results": [{"kind": "registered", "status": "CHECKED"}],
            }


def test_two_distinct_target_jobs_active_cap_and_evaluation_replay(runtime):
    factory, _, _, card = runtime
    ids = schedule(factory, card)
    assert len(ids) == 2
    assert schedule(factory, card, force=True) == []
    with factory() as session:
        jobs = session.scalars(select(Job).where(Job.kind == "pursuit_question")).all()
        assert {j.target_id for j in jobs} == set(ids)
        assert len({j.id for j in jobs}) == 2
        pursuit = session.scalar(select(Pursuit))
        assert len(pursuit.snapshot["commercial_triage"]["versions"]) == 1
        assert session.get(PowerNeed, card["id"]).tier == "Signal"


def test_daily_question_cap_holds_then_reopens_next_day(runtime, monkeypatch):
    factory, _, _, card = runtime
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    # Keep the scheduler's supplied clock and persisted creation timestamps on
    # one stable UTC day, independent of the wall-clock hour running this test.
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    first = schedule(factory, card, now=now)
    assert len(first) == 1
    with factory.begin() as session:
        for question_id in first:
            row = session.get(PursuitResearchQuestion, question_id)
            row.created_at = now
            row.status = "UNRESOLVED"
            row.completed_at = now
            row.retry_after = now + timedelta(days=1)
            row.receipt = {
                **row.receipt,
                "route_results": [{"kind": "registered", "status": "CHECKED"}],
            }
    assert schedule(factory, card, now=now + timedelta(hours=2)) == []
    next_day = schedule(factory, card, now=now + timedelta(days=1))
    assert len(next_day) == 1


def test_daily_cap_uses_one_utc_clock_for_inserted_question(runtime, monkeypatch):
    factory, _, _, card = runtime
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    now = datetime(2026, 10, 8, 0, 30, tzinfo=UTC)
    with factory.begin() as session:
        session.execute(text("SET LOCAL TIME ZONE 'America/Chicago'"))
        rows = schedule_questions(session, [card], now=now)
        assert len(rows) == 1
        assert rows[0].created_at == now


@pytest.mark.parametrize("change", ["force", "evidence", "expired"])
def test_fresh_cache_reused_until_force_material_change_or_expiry(runtime, change):
    factory, _, _, card = runtime
    first = schedule_legacy_two_category_plan(factory, card)
    finish_questions(factory, first)
    assert schedule_legacy_two_category_plan(factory, card) == []
    kwargs = {}
    if change == "force":
        kwargs["force"] = True
    elif change == "evidence":
        card["input_hash"] = "changed-evidence-and-project-state"
    else:
        kwargs["now"] = datetime.now(UTC) + timedelta(days=2)
    second = schedule_legacy_two_category_plan(factory, card, **kwargs)
    assert len(second) == 2
    assert set(second).isdisjoint(first)
    with factory() as session:
        originals = [session.get(PursuitResearchQuestion, i) for i in first]
        assert all(q.status == "UNRESOLVED" for q in originals)
        assert all(
            q.context["before"]["input_hash"] != "changed-evidence-and-project-state"
            for q in originals
        )


@pytest.mark.parametrize(
    "retained_checks",
    [[], [{"acquisition": "retained", "disposition": "UNRESOLVED"}]],
)
def test_legacy_retained_only_check_does_not_suppress_same_input_retry(runtime, retained_checks):
    factory, _, _, card = runtime
    original_ids = schedule_legacy_two_category_plan(factory, card)
    finish_questions(factory, original_ids)
    stale_id = original_ids[0]
    with factory.begin() as session:
        stale = session.get(PursuitResearchQuestion, stale_id)
        stale.retry_after = datetime.now(UTC) + timedelta(days=2)
        stale.receipt = {
            **stale.receipt,
            "retry_class": None,
            "source_checks": retained_checks,
            "route_results": [{"kind": "retained", "status": "CHECKED"}],
        }
        stale.receipt.pop("retry_class")

    replacements = schedule_legacy_two_category_plan(factory, card)
    assert len(replacements) == 1
    with factory() as session:
        stale = session.get(PursuitResearchQuestion, stale_id)
        replacement = session.get(PursuitResearchQuestion, replacements[0])
        assert replacement.category == stale.category
        assert replacement.query_fingerprint == stale.query_fingerprint
        assert replacement.evidence_fingerprint == stale.evidence_fingerprint
        assert stale.receipt["source_checks"] == retained_checks
        assert stale.receipt["route_results"] == [{"kind": "retained", "status": "CHECKED"}]


def test_legacy_external_negative_check_still_honors_freshness(runtime):
    factory, _, _, card = runtime
    original_ids = schedule_legacy_two_category_plan(factory, card)
    finish_questions(factory, original_ids)
    with factory.begin() as session:
        for question_id in original_ids:
            row = session.get(PursuitResearchQuestion, question_id)
            row.receipt.pop("retry_class", None)
            row.receipt["source_checks"] = []
            row.receipt["route_results"] = [{"kind": "registered", "status": "CHECKED"}]
    assert schedule_legacy_two_category_plan(factory, card) == []


def test_direct_get_failure_never_falls_back_to_unverified_provider_scrape(runtime, monkeypatch):
    import time
    from decimal import Decimal

    from gridlens.ingestion.adapters.buying_chain_public import PublicExtractionUnavailable

    factory, worker, _, card = runtime
    question_id = schedule_legacy_two_category_plan(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = session.get(PursuitResearchQuestion, question_id).budget

    approve_test_host(monkeypatch, "public.example")
    monkeypatch.setattr(settings, "firecrawl_api_key", None)
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", None)
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)

    def free_get_fails(url, **kwargs):
        kwargs["before_request"]("https://public.example/robots.txt")
        kwargs["before_request"](url)
        raise PublicExtractionUnavailable("JavaScript shell")

    monkeypatch.setattr(worker, "retrieve", free_get_fails)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "extract_public_document",
        lambda *_args, **_kwargs: pytest.fail("Unavailable extraction must not dispatch"),
    )
    url = "https://public.example/project"
    worker._research_public_url(run, url)
    worker._finish(job_id, "question-test", fence, question_id, "FAILED", time.monotonic())
    with factory() as session:
        failed = session.get(PursuitResearchQuestion, question_id)
        assert failed.receipt["source_checks"][-1]["effect_status"] == "NOT_SENT"
        assert failed.receipt["retry_class"] == "BOUNDED_TRANSIENT"
        assert not failed.receipt.get("inflight_url")
        assert not failed.receipt.get("ambiguous_effects")
        assert failed.receipt.get("inflight_acquisition_url") is None

    recovery_ids = schedule_legacy_two_category_plan(
        factory, card, now=datetime.now(UTC) + timedelta(hours=2)
    )
    assert len(recovery_ids) == 1
    recovery_id = recovery_ids[0]
    recovery_job, recovery_fence = lease_question(factory, recovery_id)
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, recovery_id)
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, recovery_id)
        row.budget = {**row.budget, "max_cost_usd": "1"}
        recovery_budget = row.budget
    recovery_run = worker.QuestionRun(
        recovery_job,
        "question-test",
        recovery_fence,
        recovery_id,
        time.monotonic(),
        recovery_budget,
    )

    monkeypatch.setattr(worker, "retrieve", free_get_fails)
    monkeypatch.setattr(
        acquisition,
        "extract_public_document",
        lambda *_args, **_kwargs: pytest.fail("Unverified provider scrape must not be invoked"),
    )
    worker._research_public_url(recovery_run, url)
    worker._finish(
        recovery_job, "question-test", recovery_fence, recovery_id, "UNRESOLVED", time.monotonic()
    )
    with factory() as session:
        recovered = session.get(PursuitResearchQuestion, recovery_id)
        assert recovered.receipt["retry_class"] == "BOUNDED_TRANSIENT"
        assert recovered.receipt["source_checks"][-1]["disposition"] == "FAILED"
        assert recovered.receipt["source_checks"][-1]["effect_status"] == "NOT_SENT"
        assert not recovered.receipt.get("inflight_url")
        assert recovered.receipt.get("inflight_acquisition_url") is None
        assert (
            session.scalar(
                select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SCRAPE_V2")
            )
            is None
        )


def test_unapproved_public_host_is_denied_before_direct_transport(runtime, monkeypatch):
    import time

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = session.get(PursuitResearchQuestion, question_id).budget
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)
    monkeypatch.setattr(
        worker,
        "retrieve",
        lambda *_args, **_kwargs: pytest.fail("Unapproved host must not reach direct transport"),
    )

    worker._research_public_url(run, "https://unreviewed.example/page")
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        check = row.receipt["source_checks"][-1]
        assert check["effect_status"] == "NOT_SENT"
        assert check["failure_code"] == "access_restricted"
        assert row.receipt.get("retrieval_attempts", 0) == 0


def test_mixed_completed_and_failed_checks_use_bounded_retry_chain(runtime):
    import time

    factory, worker, _, card = runtime
    initial_ids = schedule_legacy_two_category_plan(factory, card)
    assert len(initial_ids) == 2
    first_id, sibling_id = initial_ids
    with factory.begin() as session:
        sibling = session.get(PursuitResearchQuestion, sibling_id)
        sibling.status = "FAILED"
        sibling.completed_at = datetime.now(UTC)
        sibling.retry_after = sibling.completed_at + timedelta(days=1)
        sibling.receipt = {**sibling.receipt, "retry_class": "RETRIES_EXHAUSTED"}

    retry_id = first_id
    expected_delays = (1, 6, 24, None)
    statuses = ("PARTIALLY_RESOLVED", "UNRESOLVED", "PARTIALLY_RESOLVED", "UNRESOLVED")
    accepted_evidence_ids = []
    for retry_index, (delay_hours, terminal_status) in enumerate(
        zip(expected_delays, statuses, strict=True)
    ):
        job_id, fence = lease_question(factory, retry_id)
        with factory() as session:
            row = session.get(PursuitResearchQuestion, retry_id)
            budget = row.budget
        started = time.monotonic()
        run = worker.QuestionRun(job_id, "question-test", fence, retry_id, started, budget)
        accepted_evidence_id = str(uuid4())
        accepted_evidence_ids.append(accepted_evidence_id)
        run.record(
            {
                "url": f"https://public.example/supported-{retry_index}",
                "acquisition": "public",
                "disposition": "ACCEPTED",
                "evidence_id": accepted_evidence_id,
            }
        )
        run.record(
            {
                "url": f"https://public.example/failed-{retry_index}",
                "acquisition": "public",
                "disposition": "FAILED",
                "effect_status": "NOT_SENT",
                "error": "source temporarily unavailable",
            }
        )
        with factory.begin() as session:
            row = session.get(PursuitResearchQuestion, retry_id)
            row.receipt = {
                **row.receipt,
                "route_results": [{"kind": "registered", "status": "CHECKED"}],
            }
        worker._finish(
            job_id,
            "question-test",
            fence,
            retry_id,
            terminal_status,
            started,
        )
        with factory() as session:
            completed = session.get(PursuitResearchQuestion, retry_id)
            assert completed.receipt["resulting_evidence_ids"] == [accepted_evidence_id]
            assert completed.receipt["source_checks"][-2]["acquisition"] == "public"
            assert completed.receipt["source_checks"][-2]["disposition"] == "ACCEPTED"
            assert completed.receipt["source_checks"][-1]["disposition"] == "FAILED"
            assert completed.status == terminal_status
            if delay_hours is None:
                assert completed.receipt["retry_class"] == "RETRIES_EXHAUSTED"
                exhausted_at = completed.retry_after + timedelta(seconds=1)
            else:
                assert completed.receipt["retry_class"] == "BOUNDED_TRANSIENT"
                delay_seconds = jittered_delay_seconds(
                    str(retry_id), retry_index + 1, delay_hours * 3600, ceiling_seconds=24 * 3600
                )
                assert delay_seconds == jittered_delay_seconds(
                    str(retry_id), retry_index + 1, delay_hours * 3600, ceiling_seconds=24 * 3600
                )
                assert 1 <= delay_seconds <= min(delay_hours * 3600 * 1.2, 24 * 3600)
                assert completed.retry_after == completed.completed_at + timedelta(
                    seconds=delay_seconds
                )
                retry_after = completed.retry_after

        if delay_hours is None:
            assert (
                schedule_legacy_two_category_plan(
                    factory, card, now=exhausted_at + timedelta(days=2)
                )
                == []
            )
            break

        assert (
            schedule_legacy_two_category_plan(factory, card, now=retry_after - timedelta(seconds=1))
            == []
        )
        next_ids = schedule_legacy_two_category_plan(
            factory, card, now=retry_after + timedelta(seconds=1)
        )
        assert len(next_ids) == 1
        retry_id = next_ids[0]
        with factory() as session:
            replacement = session.get(PursuitResearchQuestion, retry_id)
            assert replacement.context["retry_index"] == retry_index + 1

    with factory() as session:
        first = session.get(PursuitResearchQuestion, first_id)
        assert first.receipt["resulting_evidence_ids"] == [accepted_evidence_ids[0]]
        assert first.receipt["source_checks"][-2]["url"] == "https://public.example/supported-0"
        assert first.receipt["source_checks"][-1]["effect_status"] == "NOT_SENT"


def test_resolved_question_is_not_reopened_for_unused_failed_route(runtime):
    import time

    factory, worker, _, card = runtime
    initial_ids = schedule_legacy_two_category_plan(factory, card)
    question_id, sibling_id = initial_ids
    with factory.begin() as session:
        sibling = session.get(PursuitResearchQuestion, sibling_id)
        sibling.status = "FAILED"
        sibling.completed_at = datetime.now(UTC)
        sibling.retry_after = sibling.completed_at + timedelta(days=1)
        sibling.receipt = {**sibling.receipt, "retry_class": "RETRIES_EXHAUSTED"}
        row = session.get(PursuitResearchQuestion, question_id)
        budget = row.budget
    job_id, fence = lease_question(factory, question_id)
    started = time.monotonic()
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, started, budget)
    run.record(
        {
            "url": "https://public.example/completed",
            "acquisition": "public",
            "disposition": "UNRESOLVED",
        }
    )
    run.record(
        {
            "url": "https://public.example/unused-route",
            "acquisition": "public",
            "disposition": "FAILED",
            "effect_status": "NOT_SENT",
        }
    )
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        row.receipt = {
            **row.receipt,
            "route_results": [{"kind": "registered", "status": "CHECKED"}],
        }
    worker._finish(job_id, "question-test", fence, question_id, "RESOLVED", started)
    with factory() as session:
        completed = session.get(PursuitResearchQuestion, question_id)
        assert completed.receipt["retry_class"] == "FRESH_CHECK"
        assert completed.receipt["source_checks"][-1]["disposition"] == "FAILED"
    assert schedule_legacy_two_category_plan(factory, card) == []


def test_mixed_paid_unknown_remains_blocking_across_force_and_changed_input(runtime):
    import time

    factory, worker, _, card = runtime
    question_id, sibling_id = schedule(factory, card)
    with factory.begin() as session:
        sibling = session.get(PursuitResearchQuestion, sibling_id)
        sibling.status = "FAILED"
        sibling.completed_at = datetime.now(UTC)
        sibling.retry_after = sibling.completed_at + timedelta(days=1)
        sibling.receipt = {**sibling.receipt, "retry_class": "RETRIES_EXHAUSTED"}
        row = session.get(PursuitResearchQuestion, question_id)
        budget = row.budget
    job_id, fence = lease_question(factory, question_id)
    started = time.monotonic()
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, started, budget)
    run.record(
        {
            "url": "https://public.example/completed-before-unknown",
            "acquisition": "public",
            "disposition": "ACCEPTED",
            "evidence_id": str(uuid4()),
        }
    )
    run.reserve("https://api.firecrawl.dev/v2/search", query="bounded test search")
    run.record(
        {
            "url": "https://api.firecrawl.dev/v2/search",
            "acquisition": "firecrawl_discovery",
            "disposition": "FAILED",
            "effect_status": "UNKNOWN",
            "error": "simulated ambiguous post-dispatch outcome",
        }
    )
    worker._finish(job_id, "question-test", fence, question_id, "PARTIALLY_RESOLVED", started)
    with factory() as session:
        completed = session.get(PursuitResearchQuestion, question_id)
        assert completed.receipt["retry_class"] == "UNKNOWN_EFFECT"
        assert completed.receipt["source_checks"][-2]["disposition"] == "ACCEPTED"
        assert completed.receipt["source_checks"][-1]["disposition"] == "FAILED"
        assert completed.receipt["inflight_url"] == "https://api.firecrawl.dev/v2/search"
        assert completed.receipt["ambiguous_effects"][-1]["status"] == "UNKNOWN"

    assert schedule(factory, card, force=True) == []
    card["input_hash"] = "changed-evidence-after-mixed-paid-unknown"
    card["missing_facts"] = ["buyer", "supply adequacy", "start date"]
    assert schedule(factory, card, force=True) == []


def test_single_followup_and_no_recursive_branch(runtime):
    factory, _, _, card = runtime
    first = schedule(factory, card)
    finish_questions(factory, first)
    followup = schedule(factory, card, parent_id=first[0], force=True)
    assert len(followup) == 1
    assert schedule(factory, card, parent_id=first[0], force=True) == []
    finish_questions(factory, followup)
    assert schedule(factory, card, parent_id=followup[0], force=True) == []


def test_ambiguous_inflight_retrieval_is_visible_failure_without_repeat(runtime, monkeypatch):
    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        row.receipt = {**row.receipt, "inflight_url": "https://example.invalid/uncertain"}
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "question-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id

    def forbidden(*_a, **_kw):
        pytest.fail("Ambiguous retrieval must not be repeated")

    monkeypatch.setattr(worker, "current_cards", forbidden, raising=False)
    monkeypatch.setattr(worker, "current_card", forbidden, raising=False)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "FAILED"
        assert row.receipt["error"] == "ambiguous_prior_retrieval"
        assert row.completed_at and row.retry_after
        assert session.get(Job, job_id).status == "failed"
        assert session.get(PowerNeed, card["id"]).tier == "Signal"


def test_autonomous_research_status_is_read_only_and_preserves_receipts(runtime):
    factory, _, api, card = runtime
    queued_ids = schedule(factory, card)
    assert len(queued_ids) == 2
    url = f"/api/commercial/triage/{card['id']}/autonomous-research"
    client = TestClient(api.app, base_url="https://testserver")
    assert client.get(url).status_code == 401
    # Research scheduling is automatic; the old request/queue writer is retired.
    assert client.post(url, json={}).status_code == 405
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(url)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 2
    assert all(
        q["status"] == "QUEUED" and q["receipt"]["reevaluation_status"] == "NOT_STARTED"
        for q in rows
    )
    assert client.post(url, json={}, headers={"origin": "https://evil.invalid"}).status_code == 405
    assert client.post(url, json={}, headers={"origin": "https://testserver"}).status_code == 405
    readback = client.get(url)
    assert readback.status_code == 200
    assert {q["id"] for q in readback.json()["items"]} == {q["id"] for q in rows}
    assert {UUID(q["id"]) for q in rows} == set(queued_ids)
    assert client.get(f"/api/commercial/triage/{uuid4()}/autonomous-research").status_code == 404


def test_retained_only_buying_chain_never_calls_public_or_houston_detail(runtime, monkeypatch):
    from gridlens.persistence.models import Evidence, Interpretation, Observation

    factory, _, _, card = runtime
    chain = import_module("gridlens.intelligence.buying_chain")

    def forbidden(*_a, **_kw):
        pytest.fail("Retained-only enrichment attempted external acquisition")

    monkeypatch.setattr(chain, "retrieve", forbidden)
    monkeypatch.setattr(chain, "retrieve_detail", forbidden)
    with factory.begin() as session:
        source_id = "houston-weekly-permits"
        session.add(
            Source(
                id=source_id,
                publisher="Synthetic Houston",
                endpoint="https://example.invalid/",
                family="construction-permits",
                geography="Houston",
                industries=[],
                retrieval_method=source_id,
                health={},
            )
        )
        session.flush()
        project = session.get(Project, card["project_id"])
        project.source_id = source_id
        project.external_id = "26051624:Building Pmt:2026-09-02"
        project.location = "8930 GULF FWY A, Houston, TX"
        abstract = (
            "row: 26051624\nevent: Sold (weekly report; issued permit event)\n"
            "date: 2026-09-02\nreport_start: 2026-08-31\nreport_end: 2026-09-07\n"
            "status: Unknown\ntype: Building Pmt\naddress: 8930 GULF FWY A\n"
            "description: 2,765 SQ. FT. CONVERT TO LABORATORY"
        )
        observation = Observation(
            source_id=source_id,
            external_id=project.external_id,
            title="Exact retained permit",
            url="https://example.invalid/retained",
            abstract=abstract,
            content_hash="retained-houston",
        )
        session.add(observation)
        session.flush()
        session.add(
            Evidence(
                observation_id=observation.id,
                title=observation.title,
                url=observation.url,
                abstract=abstract,
                content_hash=observation.content_hash,
                observed_at=datetime.now(UTC),
            )
        )
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                status="accepted",
                assessment={
                    "evidence_hash": observation.content_hash,
                    "decision": "accepted",
                    "project_identity_key": project.identity_key,
                    "admission_status": "supplemental",
                },
            )
        )
        session.flush()
        result = chain.enrich_buying_chain(
            session, project.id, retained_only=True, fetcher=forbidden
        )
        assert result["permit_summaries"]
        assert result["candidates"] == []


def test_unresolved_completion_preserves_tier_and_does_not_duplicate_evaluation(
    runtime, monkeypatch
):
    import time

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "question-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id
    monkeypatch.setattr(worker, "current_cards", lambda: [card], raising=False)
    monkeypatch.setattr(worker, "current_card", lambda _need: card, raising=False)
    worker._finish(job_id, "question-test", fence, question_id, "UNRESOLVED", time.monotonic())
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "UNRESOLVED"
        assert row.receipt["resulting_evidence_ids"] == []
        assert row.receipt["reevaluation_status"] == "COMPLETED"
        assert row.receipt["before"] == row.receipt["after"] == "RESEARCH"
        assert row.receipt["tier"] == "Signal"
        assert row.receipt["reason"] == card["reason"]
        assert row.receipt["remaining_blockers"] == card["blockers"]
        assert row.retry_after > row.completed_at
        assert session.get(PowerNeed, card["id"]).tier == "Signal"
        pursuit = session.get(Pursuit, row.pursuit_id)
        assert len(pursuit.snapshot["commercial_triage"]["versions"]) == 1
        assert session.get(Job, job_id).status == "succeeded"


def lease_question(factory, question_id):
    with factory.begin() as session:
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "question-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        return job.id, fence


def test_worker_empty_bounded_search_is_explicit_unresolved_without_network(runtime, monkeypatch):
    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)

    def forbidden(*_args, **_kwargs):
        pytest.fail("No exact record or configured discovery provider permits a network call")

    monkeypatch.setattr(worker, "retrieve", forbidden)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(acquisition, "discover_urls", forbidden)
    monkeypatch.setattr(worker, "acquire_registered_record", forbidden)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "UNRESOLVED"
        assert row.attempt_count == 1
        assert row.receipt["source_checks"] == []
        assert row.receipt["searches"] == row.receipt["model_calls"] == 0
        assert row.receipt["cost_usd"] is None
        assert row.receipt["acquisition_limitations"]
        assert row.retry_after <= row.completed_at + timedelta(hours=2)
        assert row.receipt["before"] == row.receipt["after"] == "RESEARCH"
        assert session.get(PowerNeed, card["id"]).tier == "Signal"
        pursuit = session.get(Pursuit, row.pursuit_id)
        assert len(pursuit.snapshot["commercial_triage"]["versions"]) == 1


def test_unconfigured_route_is_retryable_after_provider_recovery(runtime, monkeypatch):
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_id = schedule_legacy_two_category_plan(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    monkeypatch.setattr(
        worker,
        "retrieve",
        lambda *_args, **_kwargs: pytest.fail("Unconfigured provider must not be called"),
    )
    monkeypatch.setattr(
        worker,
        "acquire_registered_record",
        lambda *_args, **_kwargs: pytest.fail("Unconfigured provider must not be called"),
    )
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda *_args, **_kwargs: pytest.fail("Unconfigured provider must not be called"),
    )
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "UNRESOLVED"
        assert row.retry_after <= row.completed_at + timedelta(hours=2)
        assert not row.receipt.get("ambiguous_effects")
    recovered = schedule_legacy_two_category_plan(
        factory,
        card,
        now=datetime.now(UTC) + timedelta(hours=2),
    )
    assert recovered
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, recovered[0])
        row.budget = {**row.budget, "max_cost_usd": "1"}
    recovery_id = recovered[0]
    enable_fake_firecrawl(monkeypatch, factory, recovery_id)
    recovery_job, recovery_fence = lease_question(factory, recovery_id)

    def successful_empty_search(_query, **kwargs):
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        return []

    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(acquisition, "discover_urls", successful_empty_search)
    worker.process_question_job(recovery_job, "question-test", recovery_fence)
    with factory() as session:
        checked = session.get(PursuitResearchQuestion, recovery_id)
        assert checked.status == "UNRESOLVED"
        assert checked.receipt["retry_class"] == "FRESH_CHECK"
        assert any(route["status"] == "CHECKED" for route in checked.receipt["route_results"])
    assert schedule_legacy_two_category_plan(factory, card) == []


def test_search_timeout_keeps_unknown_effect_across_force(runtime, monkeypatch):
    from decimal import Decimal

    factory, worker, _, card = runtime
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    enable_fake_firecrawl(monkeypatch, factory, question_id)

    def timed_out(_query, **kwargs):
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        raise TimeoutError("simulated response timeout after request dispatch")

    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(acquisition, "discover_urls", timed_out)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "FAILED"
        assert row.receipt["inflight_url"] == "https://api.firecrawl.dev/v2/search"
        assert row.receipt["ambiguous_effects"][-1]["status"] == "UNKNOWN"
    card["input_hash"] = "new-evidence-after-ambiguous-search"
    assert schedule(factory, card, force=True) == []


def test_unverified_extraction_mode_blocks_before_paid_dispatch(runtime, monkeypatch):
    import time

    from gridlens.ingestion.adapters.buying_chain_public import PublicExtractionUnavailable

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = {**session.get(PursuitResearchQuestion, question_id).budget, "max_cost_usd": "1"}
    enable_fake_firecrawl(monkeypatch, factory, question_id)
    approve_test_host(monkeypatch, "publisher.example")
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)

    def direct_fails(url, **kwargs):
        kwargs["before_request"]("https://publisher.example/robots.txt")
        kwargs["before_request"](url)
        raise PublicExtractionUnavailable("direct page needs extraction")

    def forbidden_extraction(*_args, **_kwargs):
        pytest.fail("Unverified Firecrawl scrape must be blocked before dispatch")

    monkeypatch.setattr(worker, "retrieve", direct_fails)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(acquisition, "extract_public_document", forbidden_extraction)
    worker._research_public_url(run, "https://publisher.example/document")
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.receipt.get("inflight_url") is None
        assert row.receipt["source_checks"][-1]["effect_status"] == "NOT_SENT"
        assert row.receipt["source_checks"][-1]["failure_code"] == "extraction_not_configured"
        assert not row.receipt.get("ambiguous_effects")
        assert row.receipt.get("firecrawl_extractions", 0) == 0
        assert (
            session.scalar(
                select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SCRAPE_V2")
            )
            is None
        )


def test_ambiguous_effect_blocks_new_question_category(runtime):
    factory, _, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        row.status = "FAILED"
        row.receipt = {**row.receipt, "ambiguous_effects": [{"status": "UNKNOWN"}]}
        for other in session.scalars(
            select(PursuitResearchQuestion).where(PursuitResearchQuestion.id != question_id)
        ):
            other.status = "FAILED"
    card["input_hash"] = "changed-evidence-and-category-context"
    card["missing_facts"] = ["load", "start date", "buying responsibility"]
    assert schedule(factory, card, force=True) == []


def test_failed_route_is_not_a_fresh_checked_negative(runtime):
    from gridlens.intelligence.pursuit_questions import _fresh_checked_result

    factory, _, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        row.status = "UNRESOLVED"
        row.retry_after = datetime.now(UTC) + timedelta(hours=24)
        row.receipt = {
            **row.receipt,
            "route_results": [{"kind": "registered", "status": "CHECKED"}],
            "source_checks": [{"disposition": "FAILED"}],
        }
        assert not _fresh_checked_result(row)
        row.receipt = {
            **row.receipt,
            "retry_class": None,
            "source_checks": [
                {"acquisition": "public", "disposition": "ACCEPTED"},
                {"acquisition": "public", "disposition": "FAILED"},
            ],
        }
        assert not _fresh_checked_result(row)
        row.receipt = {
            **row.receipt,
            "retry_class": "RETRIES_EXHAUSTED",
            "source_checks": [{"acquisition": "public", "disposition": "UNRESOLVED"}],
            "queries_searched": ["already completed search"],
        }
        assert not _fresh_checked_result(row)


def test_transient_retry_uses_bounded_backoff_and_exhausts_across_rows(runtime):
    factory, _, _, card = runtime
    current = schedule_legacy_two_category_plan(factory, card)
    for retry_index, delay in enumerate((1, 6, 24)):
        now = datetime.now(UTC)
        with factory.begin() as session:
            for question_id in current:
                row = session.get(PursuitResearchQuestion, question_id)
                row.status = "FAILED"
                row.completed_at = now
                row.retry_after = now + timedelta(hours=delay)
                row.context = {**row.context, "retry_index": retry_index}
                row.receipt = {**row.receipt, "retry_class": "BOUNDED_TRANSIENT"}
        assert schedule_legacy_two_category_plan(factory, card) == []
        current = schedule_legacy_two_category_plan(
            factory, card, now=now + timedelta(hours=delay + 1)
        )
        assert current, f"retry index {retry_index} did not schedule after {delay}h"
        with factory() as session:
            assert all(
                session.get(PursuitResearchQuestion, question_id).context["retry_index"]
                == retry_index + 1
                for question_id in current
            )
    now = datetime.now(UTC) + timedelta(days=2)
    with factory.begin() as session:
        for question_id in current:
            row = session.get(PursuitResearchQuestion, question_id)
            row.status = "FAILED"
            row.completed_at = now
            row.retry_after = now + timedelta(hours=24)
            row.context = {**row.context, "retry_index": 3}
            row.receipt = {**row.receipt, "retry_class": "RETRIES_EXHAUSTED"}
    assert schedule_legacy_two_category_plan(factory, card, now=now + timedelta(days=2)) == []
    forced = schedule_legacy_two_category_plan(
        factory, card, force=True, now=now + timedelta(days=2)
    )
    assert forced
    with factory() as session:
        assert all(
            session.get(PursuitResearchQuestion, question_id).context["retry_index"] == 3
            for question_id in forced
        )


def test_worker_changed_input_fails_before_acquisition_and_preserves_original_context(
    runtime, monkeypatch
):
    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    original_hash = card["input_hash"]
    card["input_hash"] = "new-evidence-arrived-after-queue"
    job_id, fence = lease_question(factory, question_id)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Changed-input question must stop before acquiring or enriching")

    monkeypatch.setattr(worker, "enrich_buying_chain", forbidden)
    monkeypatch.setattr(worker, "acquire_registered_record", forbidden)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "FAILED"
        assert row.receipt["error"] == "input_changed_before_research"
        assert row.context["before"]["input_hash"] == original_hash
        assert row.receipt["after_input_hash"] == card["input_hash"]
        assert session.get(PowerNeed, card["id"]).tier == "Signal"


def test_retrieval_reservation_survives_worker_restart_and_enforces_document_budget(runtime):
    import time

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = {**session.get(PursuitResearchQuestion, question_id).budget, "documents": 1}
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)
    run.reserve("https://example.invalid/exact-record")
    with factory() as session:
        receipt = session.get(PursuitResearchQuestion, question_id).receipt
        assert receipt["retrieval_attempts"] == 1
        assert receipt["inflight_acquisition_url"] == "https://example.invalid/exact-record"
        assert not receipt.get("inflight_url")
    restarted = worker.QuestionRun(
        job_id, "question-test", fence, question_id, time.monotonic(), budget
    )
    with pytest.raises(worker.BudgetExceeded):
        restarted.reserve("https://example.invalid/second-record")
    # A process interruption during a free GET is idempotent and must not be
    # promoted to an ambiguous paid effect. Its reservation still survives and
    # enforces the persisted document budget after a worker restart.


def test_identical_paid_search_is_reused_across_question_jobs(runtime, monkeypatch):
    import time
    from decimal import Decimal

    factory, worker, _, card = runtime
    with factory.begin() as session:
        first_need = session.get(PowerNeed, card["id"])
        first_project = session.get(Project, first_need.project_id)
        other_project = Project(
            source_id=first_project.source_id,
            external_id="2026-100002 EP",
            name=first_project.name,
            location=first_project.location,
            identity_facts={"site": "200 ORION LN, Austin, TX"},
            identity_key="orion-second-project",
        )
        session.add(other_project)
        session.flush()
        other_need = PowerNeed(
            project_id=other_project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic second-project test need",
            supply="Unknown",
        )
        session.add(other_need)
        session.flush()
        other_card = {
            **card,
            "id": str(other_need.id),
            "project_id": str(other_project.id),
            "related_project_ids": [str(other_project.id)],
            "evidence": [],
            "input_hash": "second-project-synthetic-input",
        }
        monkeypatch.setattr(
            worker,
            "evaluate_target",
            lambda _session, need_id: (other_card if str(need_id) == str(other_need.id) else card),
        )
        scheduled = schedule_questions(session, [card, other_card])
        question_by_project = {}
        for row in scheduled:
            question_by_project.setdefault(str(row.project_id), row.id)
        assert str(other_project.id) in question_by_project, [
            (str(row.project_id), str(row.need_id), row.category) for row in scheduled
        ]
        question_ids = [
            question_by_project[str(first_project.id)],
            question_by_project[str(other_project.id)],
        ]
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")

    def search(query, **_kwargs):
        calls.append(query)
        return ["https://example.com/shared-project"]

    monkeypatch.setattr(acquisition, "discover_urls", search)
    results = []
    for question_id in question_ids:
        job_id, fence = lease_question(factory, question_id)
        with factory() as session:
            row = session.get(PursuitResearchQuestion, question_id)
            budget = row.budget
        run = worker.QuestionRun(
            job_id, "question-test", fence, question_id, time.monotonic(), budget
        )
        results.append(run.search('"Synthetic Orion" project contact'))

    assert calls == ['"Synthetic Orion" project contact']
    assert results == [["https://example.com/shared-project"]] * 2
    with factory() as session:
        calls_in_ledger = session.scalars(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        ).all()
        second = session.get(PursuitResearchQuestion, question_ids[1])
        assert len(calls_in_ledger) == 1
        assert second.receipt["shared_provider_reuses"][0]["logical_call_id"] == str(
            calls_in_ledger[0].id
        )


def test_cached_search_cannot_bypass_disabled_provider_policy(runtime, monkeypatch):
    import time
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_ids = schedule(factory, card)
    assert len(question_ids) == 2
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda query, **_kwargs: calls.append(query) or ["https://example.com/disabled-cache"],
    )
    query = '"Synthetic Orion" project contact'
    first_job, first_fence = lease_question(factory, question_ids[0])
    with factory() as session:
        first_budget = session.get(PursuitResearchQuestion, question_ids[0]).budget
    first_run = worker.QuestionRun(
        first_job, "question-test", first_fence, question_ids[0], time.monotonic(), first_budget
    )
    assert first_run.search(query) == ["https://example.com/disabled-cache"]

    monkeypatch.setattr(settings, "intelligence_enabled", False)
    second_job, second_fence = lease_question(factory, question_ids[1])
    with factory() as session:
        second_budget = session.get(PursuitResearchQuestion, question_ids[1]).budget
    second_run = worker.QuestionRun(
        second_job, "question-test", second_fence, question_ids[1], time.monotonic(), second_budget
    )
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    with pytest.raises(legacy_calls.LegacyCallBlocked):
        second_run.search(query)
    assert calls == [query]


@pytest.mark.parametrize("company_planner_first", [False, True])
def test_buyer_question_defers_to_current_canonical_company_contact_job(
    runtime, monkeypatch, company_planner_first
):
    from gridlens.domain.pursuit_research import targeted_queries, targeted_query_plan
    from gridlens.intelligence.research_routing import routing_context, selected_sources

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        need = session.get(PowerNeed, question.need_id)
        project = session.get(Project, question.project_id)
        source_id = project.source_id
        project.region_status = "ELIGIBLE"
        observation = Observation(
            source_id=source_id,
            external_id="buyer-company-membership",
            title="Synthetic company project",
            abstract="Synthetic source backed project membership",
            url="https://example.invalid/company-project",
            content_hash="b" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
        )
        company = CompanyIdentity(rrc_operator_number="123456")
        session.add_all([evidence, company])
        session.flush()
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                evaluator_version="buyer-company-fixture-v1",
                assessment={
                    "decision": "accepted",
                    "project_identity_key": project.identity_key,
                    "evidence_hash": observation.content_hash,
                    "admission_status": "supplemental",
                },
                status="accepted",
            )
        )
        session.add(
            CompanyProjectMembership(
                company_identity_id=company.id,
                project_id=project.id,
                role="owner_developer",
                organization_name=project.name,
                source_id=source_id,
                source_evidence_id=evidence.id,
                source_version_hash=observation.content_hash,
                decision_basis="typed_source_v1",
                operator_number="123456",
                state="current",
            )
        )
        now = datetime.now(UTC)
        claim_evidence = BuyingChainEvidence(
            project_id=project.id,
            url="https://example.invalid/company-claim",
            title="Synthetic company claim",
            excerpt="Synthetic current company relationship.",
            content_hash="c" * 64,
            extraction_location="Test fixture",
            observed_at=now,
            last_seen_at=now,
            project_match_reason="Synthetic current source-backed relationship.",
        )
        session.add(claim_evidence)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="buyer-company-claim",
            fingerprint="d" * 64,
            policy_version="buyer-company-fixture-v1",
            organization=project.name,
            person_name=None,
            title="Owner",
            category="owner_developer",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="DIRECT",
            evidence_strength="high",
            reason="Synthetic exact current canonical-company claim.",
            citations=[
                {
                    "evidence_id": str(claim_evidence.id),
                    "url": claim_evidence.url,
                    "quote": claim_evidence.excerpt,
                    "supports": "project_organization",
                }
            ],
            public_contacts=[],
            observed_at=now,
        )
        session.add(claim)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="company",
                company_identity_id=company.id,
                reason="Synthetic explicit canonical identity binding.",
                basis="attributed_review",
                reviewed_by="synthetic-test-reviewer",
                source_evidence_id=claim_evidence.id,
                source_version_hash=claim_evidence.content_hash,
                state="current",
            )
        )
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="e" * 64,
                evidence_ids=[str(claim_evidence.id)],
                claim_ids=[str(claim.id)],
                policy_version="buyer-company-fixture-v1",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )
        planner = import_module("gridlens.intelligence.pursuit_questions")
        question.category = "buyer"
        sources = selected_sources(session, need.id)
        routing = routing_context("buyer", sources)
        context = {
            **question.context,
            **routing,
            "category": "buyer",
            "queries": targeted_queries(question.context, "buyer"),
            "query_routes": targeted_query_plan(question.context, "buyer"),
            "freshness_hours": 168,
        }
        question.context = context
        if company_planner_first:
            contact_planner = import_module("gridlens.intelligence.company_contact_discovery")
            contact_planner.plan_company_contact_jobs(session, limit=10)
        coverage = planner.buyer_contact_company_coverage(session, project.id)
        assert coverage is not None
        company_jobs = session.scalars(
            select(Job).where(
                Job.kind == "company_contact_discovery",
                Job.target_id == company.id,
            )
        ).all()
        assert len(company_jobs) == 1
        assert company_jobs[0].status == "queued"
        assert planner.buyer_contact_company_coverage(session, project.id) == coverage
        assert (
            len(
                session.scalars(
                    select(Job).where(
                        Job.kind == "company_contact_discovery",
                        Job.target_id == company.id,
                    )
                ).all()
            )
            == 1
        )

    job_id, fence = lease_question(factory, question_id)
    monkeypatch.setattr(
        worker,
        "retrieve",
        lambda *_args, **_kwargs: pytest.fail(
            "Covered buyer research must not fetch project pages"
        ),
    )
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda *_args, **_kwargs: pytest.fail("Company pass owns the shared buyer lookup"),
    )
    worker.process_question_job(job_id, "question-test", fence)

    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        calls = session.scalars(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        ).all()
        assert question.status == "UNRESOLVED"
        assert (
            question.receipt["company_contact_research"]["company_identity_ids"]
            == coverage["company_identity_ids"]
        )
        recorded_coverage = question.receipt["company_contact_research"]
        assert datetime.fromisoformat(question.receipt["retry_after"]) == datetime.fromisoformat(
            recorded_coverage["retry_after"]
        )
        retry_at = datetime.fromisoformat(recorded_coverage["retry_after"])
        assert datetime.now(UTC) < retry_at <= datetime.now(UTC) + timedelta(hours=1, minutes=2)
        assert any(
            route["kind"] == "company_contact" and route["status"] == "DEFERRED"
            for route in question.receipt["route_results"]
        )
        assert calls == []


@pytest.mark.parametrize("company_planner_first", [False, True])
def test_buyer_company_handoff_uses_current_claim_link_without_membership(
    runtime, company_planner_first
):
    """Current source-backed TDLR company claims share the canonical contact job."""
    tdlr = import_module("test_buying_chain")
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.company_contact_discovery import plan_company_contact_jobs
    from gridlens.intelligence.pursuit_questions import buyer_contact_company_coverage

    factory, _, _, _ = runtime
    number, name, location, owner, excerpt = tdlr.TDLR_CASES[1]
    with factory.begin() as session:
        project, _evidence, _owner = tdlr._seed_tdlr_retained_project(
            session, (number, name, location, owner, excerpt)
        )
        project.region_status = "ELIGIBLE"
        result = enrich_buying_chain(session, project.id, retained_only=True, now=tdlr.NOW)
        company = next(
            item
            for item in result["candidates"]
            if item["organization"] == owner and not item["person_name"]
        )
        company_id = UUID(str(company["company_identity_id"]))
        assert (
            session.scalar(
                select(CompanyProjectMembership.id).where(
                    CompanyProjectMembership.project_id == project.id,
                    CompanyProjectMembership.company_identity_id == company_id,
                    CompanyProjectMembership.state == "current",
                )
            )
            is None
        )

        # Remove only the normal retained-projection job to exercise handoff
        # scheduling from both possible planner orders.
        existing = session.scalars(
            select(Job).where(
                Job.kind == "company_contact_discovery",
                Job.target_id == company_id,
            )
        ).all()
        for job in existing:
            session.delete(job)
        session.flush()

        if company_planner_first:
            plan_company_contact_jobs(session, limit=10, now=tdlr.NOW)
        coverage = buyer_contact_company_coverage(session, project.id, now=tdlr.NOW)
        assert coverage is not None
        assert coverage["company_identity_ids"] == [str(company_id)]
        jobs = session.scalars(
            select(Job).where(
                Job.kind == "company_contact_discovery",
                Job.target_id == company_id,
            )
        ).all()
        assert len(jobs) == 1
        assert jobs[0].status == "queued"
        assert buyer_contact_company_coverage(session, project.id, now=tdlr.NOW) == coverage
        assert (
            len(
                session.scalars(
                    select(Job).where(
                        Job.kind == "company_contact_discovery",
                        Job.target_id == company_id,
                    )
                ).all()
            )
            == 1
        )


def test_concurrent_identical_search_defers_second_job_then_reuses_one_call(runtime, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_ids = schedule(factory, card)
    assert len(question_ids) == 2
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    entered = threading.Event()
    release = threading.Event()
    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")

    def search(query, **_kwargs):
        calls.append(query)
        entered.set()
        assert release.wait(timeout=5)
        return ["https://example.com/concurrent-project"]

    monkeypatch.setattr(acquisition, "discover_urls", search)
    runs = []
    for question_id in question_ids:
        job_id, fence = lease_question(factory, question_id)
        with factory() as session:
            budget = session.get(PursuitResearchQuestion, question_id).budget
        runs.append(
            worker.QuestionRun(
                job_id, "question-test", fence, question_id, time.monotonic(), budget
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runs[0].search, '"Synthetic Orion" project contact')
        assert entered.wait(timeout=5)
        second = pool.submit(runs[1].search, '"Synthetic Orion" project contact')
        with pytest.raises(worker.AcquisitionBusy):
            second.result(timeout=5)
        release.set()
        assert first.result(timeout=5) == ["https://example.com/concurrent-project"]

    assert runs[1].search('"Synthetic Orion" project contact') == [
        "https://example.com/concurrent-project"
    ]
    assert calls == ['"Synthetic Orion" project contact']
    with factory() as session:
        ledger = session.scalars(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        ).all()
        second_question = session.get(PursuitResearchQuestion, question_ids[1])
        assert len(ledger) == 1
        assert second_question.receipt["shared_provider_reuses"][0]["logical_call_id"] == str(
            ledger[0].id
        )


def test_same_job_restart_recovers_one_unstarted_shared_reservation(runtime, monkeypatch):
    import time
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_id)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    calls = []
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda query, **_kwargs: calls.append(query) or ["https://example.com/restart-project"],
    )

    class SimulatedProcessExit(BaseException):
        pass

    real_reserve = legacy_calls.reserve_call
    interrupt = True

    def reserve_then_exit(*args, **kwargs):
        nonlocal interrupt
        reservation = real_reserve(*args, **kwargs)
        if interrupt:
            interrupt = False
            raise SimulatedProcessExit()
        return reservation

    monkeypatch.setattr(legacy_calls, "reserve_call", reserve_then_exit)
    query = '"Synthetic Orion" project contact'
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = session.get(PursuitResearchQuestion, question_id).budget
    first_run = worker.QuestionRun(
        job_id, "question-test", fence, question_id, time.monotonic(), budget
    )
    with pytest.raises(SimulatedProcessExit):
        first_run.search(query)

    with factory() as session:
        call_before = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        )
        assert call_before is not None and call_before.status == "NOT_SENT"
        call_id = call_before.id
        budget_before = session.scalars(select(LogicalCallBudget)).all()
        assert len(budget_before) == 12
        before_counts = [
            (row.scope, row.call_count, row.cost_usd, row.active_count) for row in budget_before
        ]

    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    new_job_id, new_fence = lease_question(factory, question_id)
    assert new_job_id == job_id and new_fence > fence
    resumed = worker.QuestionRun(
        new_job_id, "question-test", new_fence, question_id, time.monotonic(), budget
    )
    assert resumed.search(query) == ["https://example.com/restart-project"]
    assert calls == [query]
    with factory() as session:
        calls_after = session.scalars(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        ).all()
        budget_after = session.scalars(select(LogicalCallBudget)).all()
        question = session.get(PursuitResearchQuestion, question_id)
        assert len(calls_after) == 1
        assert calls_after[0].id == call_id and calls_after[0].status == "COMPLETED"
        assert len(budget_after) == len(before_counts)
        after_counts = [
            (row.scope, row.call_count, row.cost_usd, row.active_count) for row in budget_after
        ]
        assert sorted(after_counts) == sorted(
            (scope, count, cost, 0) for scope, count, cost, _ in before_counts
        )
        assert question.receipt["searches"] == 1


def test_process_restart_after_question_reservation_before_dispatch_is_idempotent(
    runtime, monkeypatch
):
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_id)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    calls = []
    query = '"Synthetic Orion" project contact'
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        question.context = {
            **question.context,
            "queries": [query],
            "query_routes": [{"query": query, "family": "public-web"}],
        }
    monkeypatch.setattr(
        acquisition, "discover_urls", lambda searched, **_kwargs: calls.append(searched) or []
    )
    monkeypatch.setattr(worker, "acquire_registered_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        worker,
        "retrieve",
        lambda *_args, **_kwargs: pytest.fail("Empty deterministic search must not retrieve"),
    )
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    real_mark_dispatched = legacy_calls.mark_dispatched

    class SimulatedProcessExit(BaseException):
        pass

    def exit_after_question_reservation(*_args, **_kwargs):
        raise SimulatedProcessExit()

    monkeypatch.setattr(legacy_calls, "mark_dispatched", exit_after_question_reservation)
    job_id, fence = lease_question(factory, question_id)
    with pytest.raises(SimulatedProcessExit):
        worker.process_question_job(job_id, "question-test", fence)

    with factory() as session:
        call_before = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        )
        question = session.get(PursuitResearchQuestion, question_id)
        assert call_before is not None and call_before.status == "NOT_SENT"
        call_id = call_before.id
        assert question.receipt["searches"] == 1
        assert question.receipt["queries_attempted"] == [query]
        assert question.receipt["inflight_logical_call_id"] == str(call_id)
        assert question.receipt["inflight_query"] == query
        reserved_cost = question.receipt["reserved_cost_usd"]
        before_budgets = session.scalars(select(LogicalCallBudget)).all()
        before_counts = [
            (row.scope, row.call_count, row.cost_usd, row.active_count) for row in before_budgets
        ]
        assert before_budgets

    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    new_job_id, new_fence = lease_question(factory, question_id)
    assert new_job_id == job_id and new_fence > fence
    monkeypatch.setattr(legacy_calls, "mark_dispatched", real_mark_dispatched)
    worker.process_question_job(new_job_id, "question-test", new_fence)

    assert calls == [query]
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        calls_after = session.scalars(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        ).all()
        after_budgets = session.scalars(select(LogicalCallBudget)).all()
        assert len(calls_after) == 1
        call_after = calls_after[0]
        assert call_after.id == call_id and call_after.status == "COMPLETED"
        assert len(after_budgets) == len(before_counts)
        after_counts = [
            (row.scope, row.call_count, row.cost_usd, row.active_count) for row in after_budgets
        ]
        assert sorted(after_counts) == sorted(
            (scope, count, cost, 0) for scope, count, cost, _ in before_counts
        )
        assert question.receipt["searches"] == 1
        assert question.receipt["reserved_cost_usd"] == reserved_cost
        assert question.receipt["queries_attempted"] == [query]
        assert question.receipt["inflight_logical_call_id"] is None
        assert question.receipt["inflight_query"] is None


def test_shared_search_cache_expiry_uses_a_new_durable_generation(runtime, monkeypatch):
    import time
    from decimal import Decimal

    factory, worker, _, card = runtime
    question_ids = schedule(factory, card)
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda query, **_kwargs: calls.append(query) or ["https://example.com/shared-project"],
    )
    runs = []
    for question_id in question_ids:
        job_id, fence = lease_question(factory, question_id)
        with factory() as session:
            budget = session.get(PursuitResearchQuestion, question_id).budget
        runs.append(
            worker.QuestionRun(
                job_id, "question-test", fence, question_id, time.monotonic(), budget
            )
        )

    query = '"Synthetic Orion" project contact'
    assert runs[0].search(query) == ["https://example.com/shared-project"]
    with factory.begin() as session:
        original = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        )
        original_id = original.id
        original.finished_at = datetime.now(UTC) - timedelta(days=2)

    assert runs[1].search(query) == ["https://example.com/shared-project"]
    assert runs[0].search(query) == ["https://example.com/shared-project"]
    assert calls == [query, query]
    with factory() as session:
        generations = session.scalars(
            select(LogicalCall)
            .where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
            .order_by(LogicalCall.created_at, LogicalCall.id)
        ).all()
        assert len(generations) == 2
        assert generations[0].id == original_id
        assert generations[1].task_key.startswith("ps1:")
        assert generations[1].task_key != generations[0].task_key
        assert len(generations[1].task_key) <= 200


def test_shared_unknown_search_blocks_new_payload_generation(runtime, monkeypatch):
    import time
    from decimal import Decimal

    from gridlens.integrations.legacy_calls import LegacyCallBlocked

    factory, worker, _, card = runtime
    question_ids = schedule(factory, card)
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda query, **_kwargs: calls.append(query) or ["https://example.com/shared-project"],
    )
    runs = []
    for question_id in question_ids:
        job_id, fence = lease_question(factory, question_id)
        with factory() as session:
            budget = session.get(PursuitResearchQuestion, question_id).budget
        runs.append(
            worker.QuestionRun(
                job_id, "question-test", fence, question_id, time.monotonic(), budget
            )
        )
    query = '"Synthetic Orion" project contact'
    assert runs[0].search(query) == ["https://example.com/shared-project"]
    with factory.begin() as session:
        prior = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        )
        prior.status = "SENT_OUTCOME_UNKNOWN"
        prior.finished_at = datetime.now(UTC) - timedelta(days=3)

    with pytest.raises(LegacyCallBlocked, match="OUTCOME_UNKNOWN"):
        runs[1]._shared_firecrawl_call(
            task_type="FIRECRAWL_SEARCH_V2",
            operation="search",
            semantic_input=query,
            payload={"query": query, "limit": 5, "sources": ["web"]},
            project_id=uuid4(),
            query=query,
            invoke=lambda: (calls.append(query) or {"urls": []}, None, None),
        )
    assert calls == [query]
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_ids[1])
        assert question.receipt["inflight_logical_call_id"] == str(prior.id)
        assert question.receipt["shared_effect_fingerprint"]


def test_malformed_completed_shared_result_fails_closed_without_new_search(runtime, monkeypatch):
    import time
    from decimal import Decimal

    from gridlens.ingestion.adapters.federal_register import SourceParseError
    from gridlens.integrations.legacy_calls import _digest

    factory, worker, _, card = runtime
    question_ids = schedule(factory, card)
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    enable_fake_firecrawl(monkeypatch, factory, question_ids[0])
    with factory.begin() as session:
        second = session.get(PursuitResearchQuestion, question_ids[1])
        second.budget = {**second.budget, "max_cost_usd": "1", "searches": 2}

    calls = []
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(
        acquisition,
        "discover_urls",
        lambda query, **_kwargs: calls.append(query) or ["https://example.com/shared-project"],
    )
    runs = []
    for question_id in question_ids:
        job_id, fence = lease_question(factory, question_id)
        with factory() as session:
            budget = session.get(PursuitResearchQuestion, question_id).budget
        runs.append(
            worker.QuestionRun(
                job_id, "question-test", fence, question_id, time.monotonic(), budget
            )
        )
    query = '"Synthetic Orion" project contact'
    assert runs[0].search(query) == ["https://example.com/shared-project"]
    with factory.begin() as session:
        prior = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "FIRECRAWL_SEARCH_V2")
        )
        prior.result_payload = {"urls": ["https://127.0.0.1/private"]}
        prior.result_digest = _digest(prior.result_payload)

    with pytest.raises(SourceParseError, match="Cached Firecrawl result failed validation"):
        runs[1].search(query)
    assert calls == [query]


@pytest.mark.parametrize("invalidation", ["changed_content", "rejected", "force"])
def test_cross_question_document_cache_requires_current_immutable_evidence(runtime, invalidation):
    import time

    from gridlens.persistence.models import Evidence, Interpretation, NeedObservation, Observation

    factory, worker, _, card = runtime
    first, second = schedule(factory, card)
    with factory.begin() as session:
        observation = Observation(
            source_id="austin-building-permits",
            external_id="cache-test",
            title="Exact accepted record",
            abstract="Scoped temporary service",
            url="https://example.invalid/cache",
            content_hash="v1",
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            content_hash="v1",
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        session.flush()
        evidence_id, observation_id = evidence.id, observation.id
        need = session.get(PowerNeed, card["id"])
        project = session.get(Project, need.project_id)
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash="v1",
                status="accepted",
                assessment={
                    "evidence_hash": "v1",
                    "project_identity_key": project.identity_key,
                    "activity_key": need.activity_key,
                    "admission_status": "supplemental",
                },
            )
        )
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        row = session.get(PursuitResearchQuestion, first)
        row.receipt = {
            **row.receipt,
            "source_checks": [
                {
                    "acquisition_key": "exact-record-key",
                    "disposition": "ACCEPTED",
                    "evidence_id": str(evidence_id),
                    "source_version": "v1",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "url": observation.url,
                }
            ],
        }
    job_id, fence = lease_question(factory, second)
    with factory() as session:
        budget = session.get(PursuitResearchQuestion, second).budget
    run = worker.QuestionRun(job_id, "question-test", fence, second, time.monotonic(), budget)
    cached = run.cached("exact-record-key")
    assert cached and cached["evidence_id"] == str(evidence_id)
    assert run.cached("unrelated-record-key") is None
    run.record({**cached, "cache_reused": True})
    with factory() as session:
        receipt = session.get(PursuitResearchQuestion, second).receipt
        assert receipt["duplicate_work_avoided"] == 1
        assert receipt.get("retrieval_attempts", 0) == 0
    with factory.begin() as session:
        if invalidation == "changed_content":
            session.get(Observation, observation_id).content_hash = "v2-new-current-record"
        elif invalidation == "rejected":
            session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation_id)
            ).status = "rejected"
        else:
            question = session.get(PursuitResearchQuestion, second)
            question.context = {**question.context, "force": True}
    assert run.cached("exact-record-key") is None
    with factory() as session:
        assert session.get(Evidence, evidence_id).content_hash == "v1"


def test_retained_only_pass_preserves_previously_supported_external_buying_contact(runtime):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.persistence.models import BuyingChainClaim

    factory, _, _, card = runtime
    chain = import_module("gridlens.intelligence.buying_chain")
    now = datetime.now(UTC)
    url = "https://news.example/orion"
    with factory.begin() as session:
        project = session.get(Project, card["project_id"])
        project.name = "Orion Data Center"
        project.location = "Austin, TX"
        document = PublicDocument(
            url,
            "Orion Data Center, Austin, TX",
            "Acme is the general contractor for Orion Data Center in Austin, TX.\n"
            "Alice Smith is Project Director at Acme, on Orion Data Center.\n"
            "Email: alice@acme.example",
            now.date(),
            now,
        )
        before = chain.enrich_buying_chain(
            session,
            project.id,
            source_urls=[url],
            fetcher=lambda _url: document,
            now=now,
        )
        person = next(c for c in before["candidates"] if c["person_name"])
        assert person["person_project_relationship"] == "DIRECT"
        # Existing supported contact state may have been admitted by a different
        # exact-source parser; the generic role parser intentionally avoids emails.
        stored = session.get(BuyingChainClaim, person["id"])
        citation = stored.citations[0]
        stored.citations = [
            *stored.citations,
            {
                "evidence_id": citation["evidence_id"],
                "url": url,
                "quote": "Email: alice@acme.example",
                "supports": "public_contact",
            },
        ]
        stored.public_contacts = [
            {
                "kind": "email",
                "value": "alice@acme.example",
                "source_url": url,
                "quote": "Email: alice@acme.example",
                "observed_at": now.isoformat(),
            }
        ]
        session.flush()
        person = next(
            c
            for c in chain.buying_chain_view(session, project.id, now=now)["candidates"]
            if c["person_name"]
        )
        assert person["public_contacts"]

        def forbidden(*_a, **_kw):
            pytest.fail("Retained-only pass must not refetch prior external contact source")

        after = chain.enrich_buying_chain(
            session,
            project.id,
            retained_only=True,
            fetcher=forbidden,
            now=now + timedelta(minutes=1),
        )
        preserved = next(c for c in after["candidates"] if c["person_name"])
        assert preserved["person_project_relationship"] == "DIRECT"
        assert preserved["public_contacts"] == person["public_contacts"]
        assert preserved["organization_relationship"] == person["organization_relationship"]
        assert not preserved.get("purchasing_authority")
        assert session.get(PowerNeed, card["id"]).tier == "Signal"


@pytest.mark.parametrize("status", ["QUEUED", "SEARCHING", "REVIEWING_EVIDENCE"])
@pytest.mark.parametrize("ambiguous", [False, True])
def test_exhausted_job_terminalizes_active_question_without_losing_receipt(
    runtime, status, ambiguous
):
    from gridlens.jobs.queue import assert_fence

    factory, _, _, card = runtime
    question_id = schedule_legacy_two_category_plan(factory, card)[0]
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        question.status = status
        question.receipt = {**question.receipt, "source_checks": [{"reason": "retained partial"}]}
        if ambiguous:
            question.receipt["inflight_url"] = "https://example.invalid/interrupted"
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.status, job.attempts, job.lease_owner, job.fence = "running", 5, "dead-worker", 5
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job_id = job.id
    with factory.begin() as session:
        assert lease_one(session, "replacement", job_ids=[job_id]) is None
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        assert question.status == "FAILED"
        assert question.receipt["error"] == "lease_expired_after_maximum_attempts"
        assert question.receipt["result_disposition"] == "FAILED"
        assert question.receipt["reevaluation_status"] == "NOT_COMPLETED"
        assert question.receipt["source_checks"] == [{"reason": "retained partial"}]
        assert question.receipt.get("inflight_url") == (
            "https://example.invalid/interrupted" if ambiguous else None
        )
        assert question.receipt["retry_class"] == (
            "UNKNOWN_EFFECT" if ambiguous else "RETRIES_EXHAUSTED"
        )
        assert question.retry_after > question.completed_at
        job = session.get(Job, job_id)
        assert job.status == "failed" and job.lease_owner is None and job.lease_until is None
        with pytest.raises(RuntimeError, match="fence lost"):
            assert_fence(session, job_id, "dead-worker", 5)
        assert session.get(PowerNeed, card["id"]).tier == "Signal"
    assert schedule_legacy_two_category_plan(factory, card) == []


def test_expiry_cleanup_is_atomic_and_preserves_already_terminal_question(runtime):
    factory, _, _, card = runtime
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        row.status = "RESOLVED"
        row.receipt = {"result_disposition": "RESOLVED", "marker": "completed receipt"}
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.status, job.attempts, job.lease_owner = "running", 5, "dead-worker"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job_id = job.id
    with factory() as session:
        assert lease_one(session, "replacement", job_ids=[job_id]) is None
        session.rollback()
    with factory() as session:
        assert session.get(Job, job_id).status == "running"
        assert session.get(PursuitResearchQuestion, question_id).status == "RESOLVED"
    with factory.begin() as session:
        assert lease_one(session, "replacement", job_ids=[job_id]) is None
    with factory() as session:
        assert session.get(Job, job_id).status == "failed"
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "RESOLVED"
        assert row.receipt == {"result_disposition": "RESOLVED", "marker": "completed receipt"}


@pytest.mark.parametrize(
    ("family", "method", "public_expected"),
    [
        ("news", "publisher-rss", True),
        ("construction-permits", "socrata-permits", False),
        ("drilling-permits", "rrc-drilling-permits", False),
    ],
)
def test_retained_public_urls_precede_discovery_without_recasting_official_sources(
    runtime, monkeypatch, family, method, public_expected
):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.persistence.models import NeedObservation, Observation

    factory, worker, _, card = runtime
    url = "https://publisher.example/project"
    with factory.begin() as session:
        session.add(
            Source(
                id="retained-known",
                publisher="Retained test publisher",
                endpoint=url,
                family=family,
                geography="Austin",
                industries=[],
                retrieval_method=method,
                health={},
            )
        )
        session.flush()
        observation = Observation(
            source_id="retained-known",
            external_id="known-1",
            title="Project",
            abstract="Existing retained page",
            url=url,
            content_hash="known",
        )
        session.add(observation)
        session.flush()
        session.add(NeedObservation(need_id=card["id"], observation_id=observation.id))
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    events = []
    if public_expected:
        approve_test_host(monkeypatch, "publisher.example")

    def retrieve_public(candidate, **kwargs):
        assert candidate == url
        kwargs["before_request"]("https://publisher.example/robots.txt")
        kwargs["before_request"](candidate)
        events.append("public")
        return PublicDocument(candidate, "Project", "Bounded retained page")

    def search(_query, **kwargs):
        events.append("discovery")
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        return []

    enable_fake_firecrawl(monkeypatch, factory, question_id)
    if public_expected:
        with factory.begin() as session:
            question = session.get(PursuitResearchQuestion, question_id)
            question.budget = {**question.budget, "documents": 4}
    monkeypatch.setattr(worker, "retrieve", retrieve_public)
    acquisition = import_module("gridlens.ingestion.adapters.pursuit_acquisition")
    monkeypatch.setattr(acquisition, "discover_urls", search)
    monkeypatch.setattr(
        worker,
        "retain_research_document",
        lambda *_: {
            "url": url,
            "disposition": "UNRESOLVED",
            "evidence_id": None,
            "reason": "No new supported activity claim",
        },
    )
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        research_receipt = session.get(PursuitResearchQuestion, question_id).receipt
    assert "discovery" in events, f"events={events!r}; receipt={research_receipt!r}"
    assert events[0] == ("public" if public_expected else "discovery")
    assert events.count("public") == int(public_expected)
    with factory() as session:
        receipt = session.get(PursuitResearchQuestion, question_id).receipt
        assert receipt.get("retrieval_attempts", 0) == 2 * int(public_expected)
        if public_expected:
            assert receipt["source_checks"][0]["url"] == url
        else:
            assert any("retained-known" in item for item in receipt["acquisition_limitations"])


@pytest.mark.parametrize("reason", ["fresh", "retry", "changed"])
def test_scheduler_reaches_saved_targets_outside_current_shortlist(runtime, monkeypatch, reason):
    factory, worker, api, card = runtime
    ids = schedule(factory, card)
    now = datetime.now(UTC)
    with factory.begin() as session:
        for question_id in ids:
            row = session.get(PursuitResearchQuestion, question_id)
            row.status, row.completed_at = "UNRESOLVED", now
            row.retry_after = now + timedelta(hours=24)
            row.receipt = {
                **row.receipt,
                "route_results": [{"kind": "registered", "status": "CHECKED"}],
            }
            if reason == "retry":
                row.retry_after = now - timedelta(seconds=1)
        if reason == "changed":
            session.get(PowerNeed, card["id"]).updated_at = now + timedelta(seconds=1)
    monkeypatch.setattr(api, "_commercial_triage_cards", lambda *_: [])
    monkeypatch.setattr(
        worker, "evaluate_targets", lambda *_args, **_kwargs: {str(card["id"]): card}
    )
    assert worker.planning_cards() == [card]
    # Read-only planning may recheck all saved semantic inputs; scheduling reuses
    # unchanged fresh answers and creates no new external work.
    if reason == "fresh":
        from gridlens.intelligence.pursuit_questions import _fresh_checked_result

        with factory() as session:
            assert all(
                _fresh_checked_result(session.get(PursuitResearchQuestion, question_id))
                for question_id in ids
            )
        next_ids = schedule(factory, card)
        with factory() as session:
            fresh_categories = {
                session.get(PursuitResearchQuestion, question_id).category for question_id in ids
            }
            next_categories = {
                session.get(PursuitResearchQuestion, question_id).category
                for question_id in next_ids
            }
            # Fresh checked categories are reused; they must not prevent the
            # planner from investigating other still-missing facts.
            assert fresh_categories.isdisjoint(next_categories)


def test_paid_search_cannot_spend_after_document_budget_exhaustion(runtime):
    import time

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        budget = row.budget
        row.receipt = {**row.receipt, "retrieval_attempts": budget["documents"]}
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)
    with pytest.raises(worker.BudgetExceeded):
        run.reserve("https://api.firecrawl.dev/v2/search", query="exact site query")
    with factory() as session:
        receipt = session.get(PursuitResearchQuestion, question_id).receipt
        assert receipt.get("searches", 0) == 0
        assert not receipt.get("queries_attempted")


def test_planning_discovers_supported_need_beyond_shortlist_without_splitting_group(
    runtime, monkeypatch
):
    factory, worker, api, card = runtime
    with factory.begin() as session:
        needs = [
            PowerNeed(
                project_id=card["project_id"],
                activity_key=f"shortlist-{index}",
                tier="Signal",
                rationale="Synthetic shortlist need",
                supply="Unknown",
            )
            for index in range(50)
        ]
        grouped = PowerNeed(
            project_id=card["project_id"],
            activity_key="grouped-need",
            tier="Signal",
            rationale="Already represented by a grouped card",
            supply="Unknown",
        )
        session.add_all([*needs, grouped])
        session.flush()
        shortlist = [
            {**card, "id": str(need.id), "related_need_ids": [str(need.id)]} for need in needs
        ]
        shortlist[0]["related_need_ids"].append(str(grouped.id))
    monkeypatch.setattr(api, "_commercial_triage_cards", lambda *_: shortlist)
    monkeypatch.setattr(worker, "evaluate_targets", lambda _s, ids, **_kw: {card["id"]: card})
    questions = import_module("gridlens.intelligence.pursuit_questions")
    monkeypatch.setattr(
        questions,
        "evaluate_targets",
        lambda _s, _ids, **_kw: {str(card["id"]): card},
    )
    planned = worker.planning_cards()
    assert len(planned) == 51
    assert planned[-1]["id"] == card["id"]
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    first_day = datetime(2026, 10, 8, 0, 30, tzinfo=UTC)
    with factory.begin() as session:
        session.execute(text("SET LOCAL TIME ZONE 'America/Chicago'"))
        scheduled = schedule_questions(session, [planned[-1]], now=first_day)
        assert len(scheduled) == 1
    with factory.begin() as session:
        session.execute(text("SET LOCAL TIME ZONE 'America/Chicago'"))
        assert schedule_questions(session, planned, now=first_day) == []
    with factory() as session:
        assert len(list(session.scalars(select(PursuitResearchQuestion)))) == 1


def test_real_projection_groups_outside_shortlist_before_research_planning(runtime, monkeypatch):
    import hashlib

    factory, worker, api, _ = runtime
    questions = import_module("gridlens.intelligence.pursuit_questions")
    evaluator = import_module("gridlens.intelligence.commercial_evaluation")
    monkeypatch.setattr(api, "_commercial_triage_cards", api._unpatched_commercial_triage_cards)
    monkeypatch.setattr(questions, "evaluate_targets", evaluator.evaluate_targets)

    def add_supported_need(
        session,
        *,
        sequence,
        need_number,
        document_number,
        location,
        hold=False,
        active=True,
    ):
        project_id = UUID(int=sequence)
        need_id = UUID(int=need_number)
        name = f"Commercial project {sequence:03d}"
        action = "Data center electrical construction includes transformers."
        title = f"{name} {location} electrical building permit"
        abstract = f"{name} at {location}: {action}"
        url = f"https://abc.austintexas.gov/permit/{document_number}"
        semantic_hash = hashlib.sha256(f"semantic:{sequence}".encode()).hexdigest()
        evidence_hash = hashlib.sha256(f"evidence:{sequence}".encode()).hexdigest()
        project = Project(
            id=project_id,
            identity_key=f"austin-building-permits:{document_number}",
            source_id="austin-building-permits",
            external_id=document_number,
            name=name,
            location=location,
            asset_type="data_center",
        )
        need = PowerNeed(
            id=need_id,
            project_id=project_id,
            activity_key="electrical-construction",
            tier="Signal",
            rationale="Supported official permit work; temporary-power need is unverified.",
            supply="Unknown",
            active=active,
        )
        observation = Observation(
            source_id="austin-building-permits",
            external_id=document_number,
            title=title,
            abstract=abstract,
            published_at=date(2026, 10, 1),
            url=url,
            content_hash=semantic_hash,
        )
        session.add(project)
        session.flush()
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=evidence_hash,
            title=title,
            abstract=abstract,
            url=url,
            published_at=observation.published_at,
            extraction_location="synthetic exact official permit record",
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=observation.id,
                    content_hash=semantic_hash,
                    evaluator_version="grouping-test",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": semantic_hash,
                        "evidence_hash": evidence_hash,
                        "evidence": {"id": str(evidence.id), "url": url},
                        "project_identity_key": project.identity_key,
                        "power_activity": need.activity_key,
                        "activity_key": need.activity_key,
                        "subject": name,
                        "location": location,
                        "action": action,
                    },
                ),
                NeedObservation(need_id=need_id, observation_id=observation.id),
            ]
        )
        if hold:
            session.add(
                SignalDecision(
                    observation_id=observation.id,
                    content_hash=evidence_hash,
                    policy_version=api.POLICY_VERSION,
                    decision="HOLD",
                    source="deterministic",
                    reason="Synthetic conflicting sibling state for grouping control.",
                    dimensions={},
                )
            )
        return project, need

    with factory.begin() as session:
        distractor_ids = []
        for index in range(1, 51):
            document_number = f"2026-{800000 + index:06d} EP"
            _, need = add_supported_need(
                session,
                sequence=index,
                need_number=10_000 + index,
                document_number=document_number,
                location=f"{1000 + index} DISTRACTOR LN, Austin, TX",
            )
            distractor_ids.append(str(need.id))

        site = "811 CLAYTON LN, Austin, TX"
        shared_case = "2026-900001"
        _, bp_need = add_supported_need(
            session,
            sequence=1001,
            need_number=1_000_001,
            document_number=f"{shared_case} BP",
            location=site,
        )
        _, ep_need = add_supported_need(
            session,
            sequence=1002,
            need_number=1_000_002,
            document_number=f"{shared_case} EP",
            location=site,
            hold=True,
        )
        _, nearby_need = add_supported_need(
            session,
            sequence=1003,
            need_number=1_000_003,
            document_number="2026-900002 EP",
            location="813 CLAYTON LN, Austin, TX",
        )
        saved_project, saved_need = add_supported_need(
            session,
            sequence=1004,
            need_number=1_000_004,
            document_number="2026-900003 BP",
            location="815 CLAYTON LN, Austin, TX",
            active=False,
        )
        session.add(
            Pursuit(
                identity_key=f"commercial-need:{saved_need.id}",
                project_id=saved_project.id,
                project_ids=[str(saved_project.id)],
                snapshot={},
            )
        )
        pair_ids = {str(bp_need.id), str(ep_need.id)}
        nearby_id, saved_id = str(nearby_need.id), str(saved_need.id)

    with factory() as session:
        before = api._commercial_triage_cards(session, 50)
        assert len(before) == 50
        assert {need_id for card in before for need_id in card["related_need_ids"]} == set(
            distractor_ids
        )

    planned = worker.planning_cards()
    pair_cards = [card for card in planned if pair_ids.intersection(card["related_need_ids"])]
    assert len(pair_cards) == 1, [(card["id"], card["related_need_ids"]) for card in pair_cards]
    pair_card = pair_cards[0]
    assert set(pair_card["related_need_ids"]) == pair_ids
    assert pair_card["reason"].startswith(
        "Related need records for this exact work scope have different states:"
    )
    assert {state["held"] for state in pair_card["related_need_states"]} == {False, True}
    nearby_cards = [card for card in planned if nearby_id in card["related_need_ids"]]
    assert len(nearby_cards) == 1 and set(nearby_cards[0]["related_need_ids"]) == {nearby_id}
    saved_cards = [card for card in planned if saved_id in card["related_need_ids"]]
    assert len(saved_cards) == 1 and saved_cards[0]["id"] == saved_id
    with factory() as session:
        assert session.get(PowerNeed, UUID(saved_id)).active is False

    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    first_day = datetime(2026, 10, 7, 16, tzinfo=UTC)
    with factory.begin() as session:
        created_pair = schedule_questions(session, [pair_card], grouped=True, now=first_day)
        assert len(created_pair) == 1
        created_pair[0].created_at = first_day
        pair_pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{pair_card['id']}")
        )
        assert pair_pursuit is not None
        pair_questions = list(
            session.scalars(
                select(PursuitResearchQuestion).where(
                    PursuitResearchQuestion.pursuit_id == pair_pursuit.id
                )
            )
        )
        assert len(pair_questions) == 1
        assert pair_questions[0].need_id == UUID(pair_card["id"])
        assert set(pair_questions[0].context["before"]["related_need_ids"]) == pair_ids
        pair_states = pair_questions[0].context["before"]["related_need_states"]
        assert {state["held"] for state in pair_states} == {False, True}
        assert len(pair_card["related_need_ids"]) == 2
        assert (
            schedule_questions(session, [pair_card, nearby_cards[0]], grouped=True, now=first_day)
            == []
        )

    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 1)
    second_day = first_day + timedelta(days=1)
    with factory.begin() as session:
        created_nearby = schedule_questions(session, nearby_cards, grouped=True, now=second_day)
        assert len(created_nearby) == 1
        created_nearby[0].created_at = second_day
        nearby_pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{nearby_id}")
        )
        assert nearby_pursuit is not None and nearby_pursuit.id != pair_pursuit.id
        assert schedule_questions(session, nearby_cards, grouped=True, now=second_day) == []


@pytest.mark.parametrize("retry_index,delay", [(0, 1), (1, 6), (2, 24), (3, None)])
def test_unexpected_question_worker_failure_uses_bounded_retry_and_keeps_receipt(
    runtime, monkeypatch, retry_index, delay
):
    factory, research, _, card = runtime
    job_worker = import_module("gridlens.jobs.worker")
    monkeypatch.setattr(job_worker, "SessionLocal", factory)
    question_id = schedule_legacy_two_category_plan(factory, card)[0]
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        question.context = {**question.context, "retry_index": retry_index}
        question.receipt = {**question.receipt, "partial_receipt": {"retained": True}}
        job_id = session.scalar(select(Job.id).where(Job.target_id == question_id))

    def fail_before_or_after_dispatch(*_args):
        raise RuntimeError("synthetic worker failure")

    monkeypatch.setattr(research, "process_question_job", fail_before_or_after_dispatch)
    assert job_worker.run_one({}, job_ids=[job_id])
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        job = session.get(Job, job_id)
        assert question.status == "FAILED"
        assert question.receipt["partial_receipt"] == {"retained": True}
        assert question.receipt["result_disposition"] == "FAILED"
        assert question.receipt["retry_class"] == (
            "BOUNDED_TRANSIENT" if delay else "RETRIES_EXHAUSTED"
        )
        assert job.status == "failed"
        completed_at = question.completed_at
        if delay:
            delay_seconds = jittered_delay_seconds(
                str(question_id), retry_index + 1, delay * 3600, ceiling_seconds=24 * 3600
            )
            assert delay_seconds == jittered_delay_seconds(
                str(question_id), retry_index + 1, delay * 3600, ceiling_seconds=24 * 3600
            )
            assert 1 <= delay_seconds <= min(delay * 3600 * 1.2, 24 * 3600)
            assert question.retry_after == completed_at + timedelta(seconds=delay_seconds)
            retry_after = question.retry_after
        else:
            retry_after = None
    next_attempts = schedule_legacy_two_category_plan(
        factory,
        card,
        now=(retry_after or completed_at + timedelta(hours=48)) + timedelta(seconds=1),
    )
    assert bool(next_attempts) is (delay is not None)
    if next_attempts:
        with factory() as session:
            retried = session.get(PursuitResearchQuestion, next_attempts[0])
            assert retried.context["retry_index"] == retry_index + 1


@pytest.mark.parametrize("marker", ["inflight_url", "ambiguous_effects"])
def test_unexpected_failure_with_paid_effect_blocks_changed_forced_refresh(
    runtime, monkeypatch, marker
):
    factory, research, _, card = runtime
    job_worker = import_module("gridlens.jobs.worker")
    monkeypatch.setattr(job_worker, "SessionLocal", factory)
    question_id = schedule(factory, card)[0]
    with factory.begin() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        value = "https://example.invalid/paid-reservation"
        question.receipt = {**question.receipt, marker: value}
        job_id = session.scalar(select(Job.id).where(Job.target_id == question_id))
    monkeypatch.setattr(
        research,
        "process_question_job",
        lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interrupted call")),
    )
    assert job_worker.run_one({}, job_ids=[job_id])
    changed = {**card, "input_hash": "changed-after-ambiguous-effect"}
    assert schedule(factory, changed, force=True, now=datetime.now(UTC) + timedelta(days=2)) == []
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        assert question.receipt["retry_class"] == "UNKNOWN_EFFECT"
        assert question.receipt[marker] == value
