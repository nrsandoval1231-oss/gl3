from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.commercial_triage import build_card
from gridlens.intelligence.pursuit_questions import schedule_questions
from gridlens.jobs.queue import lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Job,
    PowerNeed,
    Project,
    Pursuit,
    PursuitResearchQuestion,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    worker = import_module("gridlens.intelligence.autonomous_research")
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
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
            location="100 ORION LN",
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
    Base.metadata.drop_all(engine)
    engine.dispose()


def schedule(factory, card, **kwargs):
    with factory.begin() as session:
        return [q.id for q in schedule_questions(session, [card], **kwargs)]


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


@pytest.mark.parametrize("change", ["force", "evidence", "expired"])
def test_fresh_cache_reused_until_force_material_change_or_expiry(runtime, change):
    factory, _, _, card = runtime
    first = schedule(factory, card)
    finish_questions(factory, first)
    assert schedule(factory, card) == []
    kwargs = {}
    if change == "force":
        kwargs["force"] = True
    elif change == "evidence":
        card["input_hash"] = "changed-evidence-and-project-state"
    else:
        kwargs["now"] = datetime.now(UTC) + timedelta(days=2)
    second = schedule(factory, card, **kwargs)
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
    original_ids = schedule(factory, card)
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

    replacements = schedule(factory, card)
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
    original_ids = schedule(factory, card)
    finish_questions(factory, original_ids)
    with factory.begin() as session:
        for question_id in original_ids:
            row = session.get(PursuitResearchQuestion, question_id)
            row.receipt.pop("retry_class", None)
            row.receipt["source_checks"] = []
            row.receipt["route_results"] = [{"kind": "registered", "status": "CHECKED"}]
    assert schedule(factory, card) == []


def test_free_get_and_unconfigured_extraction_recover_same_evidence(runtime, monkeypatch):
    import time
    from decimal import Decimal

    from pydantic import SecretStr

    from gridlens.ingestion.adapters.buying_chain_public import (
        PublicDocument,
        PublicExtractionUnavailable,
    )

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = session.get(PursuitResearchQuestion, question_id).budget

    monkeypatch.setattr(settings, "firecrawl_api_key", None)
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", None)
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)

    def free_get_fails(*_args, **_kwargs):
        raise PublicExtractionUnavailable("JavaScript shell")

    monkeypatch.setattr(worker, "retrieve", free_get_fails)
    monkeypatch.setattr(
        worker,
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

    recovery_ids = schedule(factory, card, now=datetime.now(UTC) + timedelta(hours=2))
    assert len(recovery_ids) == 1
    recovery_id = recovery_ids[0]
    recovery_job, recovery_fence = lease_question(factory, recovery_id)
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
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

    def successful_mocked_extraction(_url, **kwargs):
        kwargs["before_request"]("https://api.firecrawl.dev/v2/scrape")
        return PublicDocument(url, "Project update", "Bounded public project content")

    monkeypatch.setattr(worker, "retrieve", free_get_fails)
    monkeypatch.setattr(worker, "extract_public_document", successful_mocked_extraction)
    monkeypatch.setattr(
        worker,
        "retain_research_document",
        lambda *_args, **_kwargs: {"disposition": "ACCEPTED", "evidence_id": str(uuid4())},
    )
    monkeypatch.setattr(worker, "enrich_buying_chain", lambda *_args, **_kwargs: None)
    worker._research_public_url(recovery_run, url)
    worker._finish(
        recovery_job, "question-test", recovery_fence, recovery_id, "UNRESOLVED", time.monotonic()
    )
    with factory() as session:
        recovered = session.get(PursuitResearchQuestion, recovery_id)
        assert recovered.receipt["retry_class"] == "FRESH_CHECK"
        assert recovered.receipt["source_checks"][-1]["disposition"] == "ACCEPTED"
        assert not recovered.receipt.get("inflight_url")
        assert recovered.receipt.get("inflight_acquisition_url") is None
    assert schedule(factory, card) == []


def test_mixed_completed_and_failed_checks_use_bounded_retry_chain(runtime):
    import time

    factory, worker, _, card = runtime
    initial_ids = schedule(factory, card)
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
        run = worker.QuestionRun(
            job_id, "question-test", fence, retry_id, started, budget
        )
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
                assert completed.retry_after == completed.completed_at + timedelta(
                    hours=delay_hours
                )
                retry_after = completed.retry_after

        if delay_hours is None:
            assert schedule(factory, card, now=exhausted_at + timedelta(days=2)) == []
            break

        assert schedule(factory, card, now=retry_after - timedelta(seconds=1)) == []
        next_ids = schedule(factory, card, now=retry_after + timedelta(seconds=1))
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
    initial_ids = schedule(factory, card)
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
    assert schedule(factory, card) == []


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


def test_status_and_queue_api_require_auth_origin_and_preserve_receipts(runtime):
    factory, _, api, card = runtime
    url = f"/api/commercial/triage/{card['id']}/autonomous-research"
    client = TestClient(api.app, base_url="https://testserver")
    assert client.get(url).status_code == 401
    assert client.post(url, json={}).status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(url).json() == {"items": []}
    assert client.post(url, json={}, headers={"origin": "https://evil.invalid"}).status_code == 403
    response = client.post(url, json={}, headers={"origin": "https://testserver"})
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 2
    assert all(
        q["status"] == "QUEUED" and q["receipt"]["reevaluation_status"] == "NOT_STARTED"
        for q in rows
    )
    readback = client.get(url)
    assert readback.status_code == 200
    assert {q["id"] for q in readback.json()["items"]} == {q["id"] for q in rows}
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
    monkeypatch.setattr(worker, "discover_urls", forbidden)
    monkeypatch.setattr(worker, "acquire_registered_record", forbidden)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "UNRESOLVED"
        assert row.attempt_count == 1
        assert row.receipt["source_checks"] == []
        assert row.receipt["searches"] == row.receipt["model_calls"] == 0
        assert row.receipt["cost_usd"] == "0"
        assert row.receipt["acquisition_limitations"]
        assert row.retry_after <= row.completed_at + timedelta(hours=2)
        assert row.receipt["before"] == row.receipt["after"] == "RESEARCH"
        assert session.get(PowerNeed, card["id"]).tier == "Signal"
        pursuit = session.get(Pursuit, row.pursuit_id)
        assert len(pursuit.snapshot["commercial_triage"]["versions"]) == 1


def test_unconfigured_route_is_retryable_after_provider_recovery(runtime, monkeypatch):
    from decimal import Decimal

    from pydantic import SecretStr

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    for name in ("retrieve", "discover_urls", "acquire_registered_record"):
        monkeypatch.setattr(
            worker,
            name,
            lambda *_args, **_kwargs: pytest.fail("Unconfigured provider must not be called"),
        )
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "UNRESOLVED"
        assert row.retry_after <= row.completed_at + timedelta(hours=2)
        assert not row.receipt.get("ambiguous_effects")
    recovered = schedule(
        factory,
        card,
        now=datetime.now(UTC) + timedelta(hours=2),
    )
    assert recovered
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    with factory.begin() as session:
        row = session.get(PursuitResearchQuestion, recovered[0])
        row.budget = {**row.budget, "max_cost_usd": "1"}
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_search_cost_usd", Decimal("0.001"))
    recovery_id = recovered[0]
    recovery_job, recovery_fence = lease_question(factory, recovery_id)

    def successful_empty_search(_query, **kwargs):
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        return []

    monkeypatch.setattr(worker, "discover_urls", successful_empty_search)
    worker.process_question_job(recovery_job, "question-test", recovery_fence)
    with factory() as session:
        checked = session.get(PursuitResearchQuestion, recovery_id)
        assert checked.status == "UNRESOLVED"
        assert checked.receipt["retry_class"] == "FRESH_CHECK"
        assert any(route["status"] == "CHECKED" for route in checked.receipt["route_results"])
    assert schedule(factory, card) == []


def test_search_timeout_keeps_unknown_effect_across_force(runtime, monkeypatch):
    from decimal import Decimal

    from pydantic import SecretStr

    factory, worker, _, card = runtime
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("1"))
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_search_cost_usd", Decimal("0.001"))

    def timed_out(_query, **kwargs):
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        raise TimeoutError("simulated response timeout after request dispatch")

    monkeypatch.setattr(worker, "discover_urls", timed_out)
    worker.process_question_job(job_id, "question-test", fence)
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.status == "FAILED"
        assert row.receipt["inflight_url"] == "https://api.firecrawl.dev/v2/search"
        assert row.receipt["ambiguous_effects"][-1]["status"] == "UNKNOWN"
    card["input_hash"] = "new-evidence-after-ambiguous-search"
    assert schedule(factory, card, force=True) == []


def test_extraction_timeout_preserves_unknown_paid_effect(runtime, monkeypatch):
    import time
    from decimal import Decimal

    from pydantic import SecretStr

    from gridlens.ingestion.adapters.buying_chain_public import PublicExtractionUnavailable

    factory, worker, _, card = runtime
    question_id = schedule(factory, card)[0]
    job_id, fence = lease_question(factory, question_id)
    with factory() as session:
        budget = {**session.get(PursuitResearchQuestion, question_id).budget, "max_cost_usd": "1"}
    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_scrape_cost_usd", Decimal("0.01"))
    run = worker.QuestionRun(job_id, "question-test", fence, question_id, time.monotonic(), budget)

    def direct_fails(*_args, **_kwargs):
        raise PublicExtractionUnavailable("direct page needs extraction")

    def extract_times_out(url, **kwargs):
        kwargs["before_request"](url)
        raise TimeoutError("simulated extraction timeout after dispatch")

    monkeypatch.setattr(worker, "retrieve", direct_fails)
    monkeypatch.setattr(worker, "extract_public_document", extract_times_out)
    worker._research_public_url(run, "https://publisher.example/document")
    with factory() as session:
        row = session.get(PursuitResearchQuestion, question_id)
        assert row.receipt["inflight_url"] == "https://publisher.example/document"
        assert row.receipt["ambiguous_effects"][-1]["status"] == "UNKNOWN"
        assert row.receipt["firecrawl_extractions"] == 1
    card["input_hash"] = "new-evidence-after-ambiguous-extraction"
    assert schedule(factory, card, force=True) == []


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
    current = schedule(factory, card)
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
        assert schedule(factory, card) == []
        current = schedule(factory, card, now=now + timedelta(hours=delay + 1))
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
    assert schedule(factory, card, now=now + timedelta(days=2)) == []
    forced = schedule(factory, card, force=True, now=now + timedelta(days=2))
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
    question_id = schedule(factory, card)[0]
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
    assert schedule(factory, card) == []


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
    from decimal import Decimal

    from pydantic import SecretStr

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

    def retrieve_public(candidate, **_kwargs):
        assert candidate == url
        events.append("public")
        return PublicDocument(candidate, "Project", "Bounded retained page")

    def search(_query, **kwargs):
        events.append("discovery")
        kwargs["before_request"]("https://api.firecrawl.dev/v2/search")
        return []

    monkeypatch.setattr(settings, "firecrawl_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "firecrawl_search_cost_usd", Decimal("0.001"))
    monkeypatch.setattr(worker, "retrieve", retrieve_public)
    monkeypatch.setattr(worker, "discover_urls", search)
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
    assert "discovery" in events
    assert events[0] == ("public" if public_expected else "discovery")
    assert events.count("public") == int(public_expected)
    with factory() as session:
        receipt = session.get(PursuitResearchQuestion, question_id).receipt
        assert receipt.get("retrieval_attempts", 0) == int(public_expected)
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
        assert schedule(factory, card) == []


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
            {**card, "id": str(need.id), "related_need_ids": [str(need.id)]}
            for need in needs
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
    with factory.begin() as session:
        scheduled = schedule_questions(session, [planned[-1]])
        assert len(scheduled) == 1
    with factory.begin() as session:
        assert schedule_questions(session, planned) == []


@pytest.mark.parametrize("retry_index,delay", [(0, 1), (1, 6), (2, 24), (3, None)])
def test_unexpected_question_worker_failure_uses_bounded_retry_and_keeps_receipt(
    runtime, monkeypatch, retry_index, delay
):
    factory, research, _, card = runtime
    job_worker = import_module("gridlens.jobs.worker")
    monkeypatch.setattr(job_worker, "SessionLocal", factory)
    question_id = schedule(factory, card)[0]
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
            assert question.retry_after == completed_at + timedelta(hours=delay)
    next_attempts = schedule(
        factory,
        card,
        now=completed_at + timedelta(hours=(delay or 48), seconds=1),
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
    assert schedule(
        factory, changed, force=True, now=datetime.now(UTC) + timedelta(days=2)
    ) == []
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        assert question.receipt["retry_class"] == "UNKNOWN_EFFECT"
        assert question.receipt[marker] == value
