import hashlib
import json
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.persistence import models  # noqa: F401
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BriefDailyBudget,
    CallFactDecision,
    CallFactVersion,
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    NeedObservation,
    NeedWorkflowStatusEvent,
    Observation,
    PowerNeed,
    PowerNeedBrief,
    PowerNeedBriefVersion,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    service = import_module("gridlens.intelligence.briefs")
    api = import_module("gridlens.api.app")
    worker = import_module("gridlens.jobs.worker")
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(legacy_calls, "SessionLocal", factory)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-key"))
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "POWER_NEED_BRIEF")
    monkeypatch.setattr(settings, "intelligence_openai_enabled", True)
    monkeypatch.setattr(settings, "intelligence_research_enabled", True)
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_model", settings.openai_brief_model
    )
    monkeypatch.setattr(
        settings,
        "intelligence_openai_reasoning_priced_model_id",
        settings.openai_brief_model,
    )
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_pricing_verified", True)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_max_output_tokens", 700)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_input_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_output_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", 1)
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 5)
    monkeypatch.setattr(settings, "briefs_daily_request_limit", 100)
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_calls", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_calls", 1000)
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", 1000)
    with factory.begin() as session:
        source = Source(
            id="brief-test-permits",
            publisher="Synthetic city",
            endpoint="https://example.test/permits",
            family="construction-permits",
            geography="Test City",
            industries=["construction"],
            retrieval_method="socrata-permits",
            health={},
        )
        session.add(source)
        session.flush()
        project = Project(
            identity_key="brief-test-project",
            name="Synthetic North Campus",
            location="Test City",
            identity_facts={"site": "100 Test Road, Test City, TX"},
            source_id=source.id,
            external_id="record-1",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Test only",
            supply="Unknown",
        )
        observation = Observation(
            source_id=source.id,
            external_id="record-1",
            title=(
                "Public permit describes construction at Synthetic North Campus, "
                "100 Test Road, Test City, TX"
            ),
            abstract=("Construction work at Synthetic North Campus, 100 Test Road, Test City, TX."),
            url="https://example.test/permits/record-1",
            content_hash="a" * 64,
        )
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="a" * 64,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            extraction_location="permit description",
        )
        session.add(evidence)
        session.flush()
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="brief-test",
            status="accepted",
            assessment={
                "semantic_hash": observation.content_hash,
                "evidence_hash": evidence.content_hash,
                "project_identity_key": project.identity_key,
                "power_activity": need.activity_key,
                "decision": "accepted",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all(
            [interpretation, NeedObservation(need_id=need.id, observation_id=observation.id)]
        )
        from gridlens.persistence.models import Pursuit, PursuitCallNote

        pursuit = Pursuit(
            identity_key="brief-test-private-workspace",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={},
            research_status="not_researched",
            research_errors=[],
        )
        session.add(pursuit)
        session.flush()
        session.add(
            PursuitCallNote(
                pursuit_id=pursuit.id,
                client_id=uuid4(),
                note="PRIVATE-BRIEF-TEST: never include this note",
                outcome="unknown",
                next_action="private next action",
            )
        )
        ids = need.id, evidence.id
    yield factory, service, ids
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_explicit_request_is_durable_deduplicated_and_cached(runtime):
    factory, service, (need_id, evidence_id) = runtime
    with factory.begin() as session:
        first = service.request_brief(session, need_id)
        second = service.request_brief(session, need_id)
        import json

        payload, _ = service.brief_input(session, need_id)
        assert "PRIVATE-BRIEF-TEST" not in json.dumps(payload)
        assert first["status"] == second["status"] == "pending"
        assert first["job_id"] == second["job_id"]
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_question_bound_request_reuses_exact_pending_job_and_rejects_changed_question(runtime):
    import json

    factory, service, (need_id, _evidence_id) = runtime
    question = "Who owns the next construction power decision?"
    with factory.begin() as session:
        payload, _ = service.brief_input(session, need_id, question)
        first = service.request_brief(session, need_id, question)
        second = service.request_brief(session, need_id, question)
        job = session.scalar(select(Job))
        assert payload["commercial_question"] == question
        assert first["job_id"] == second["job_id"] == str(job.id)
        assert json.loads(job.checkpoint)["commercial_question"] == question
        with pytest.raises(service.BriefUnavailable, match="another_question_or_evidence_version"):
            service.request_brief(session, need_id, "What is the project's MW requirement?")
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_targeted_question_survives_budget_reservation_and_worker_commit(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    question = "Which listed contractor should we ask about temporary power?"
    with factory.begin() as session:
        requested = service.request_brief(session, need_id, question)
        job = session.get(Job, UUID(requested["job_id"]))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    leased = _lease(factory, UUID(requested["job_id"]))
    assert leased
    job, fence = leased
    monkeypatch.setattr(
        service, "_provider", lambda payload, facts: _valid_model_result(payload, facts)
    )
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        completed = session.get(Job, job.id)
        row = session.get(PowerNeedBrief, need_id)
        assert json.loads(completed.checkpoint)["commercial_question"] == question
        assert completed.status == "succeeded"
        assert row and row.status == "ready"
        assert row.result["commercial_question"] == question


def test_browse_cache_fingerprint_matches_detail_relationship_evidence(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    relationship = {
        "stale": False,
        "organization_relationship": "DIRECT",
        "category": "owner_developer",
        "organization": "North Campus Development LLC",
        "evidence": [
            {
                "id": "chain-evidence-1",
                "quote": "North Campus Development LLC is named as project owner.",
                "published_at": None,
                "url": "https://example.test/owner",
            },
            {
                "id": "chain-evidence-1",
                "quote": "North Campus Development LLC is listed as campus developer.",
                "published_at": None,
                "url": "https://example.test/owner",
            },
        ],
    }
    monkeypatch.setattr(
        service,
        "buying_chain_view",
        lambda _session, _project_id: {"candidates": [relationship]},
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        detail_payload, evidence = service.brief_input(session, need_id)
        fingerprint = service.brief_fingerprint(detail_payload)
        raw_links = session.execute(
            select(Observation, Evidence, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need_id)
        ).all()
        link_items = [(item[0], item[1], item[2]) for item in raw_links]
        source_rows = {source.id: source for source in session.scalars(select(Source)).all()}
        canonical_chain = {"candidates": [relationship]}
        legacy_payload, legacy_evidence = service.brief_payload_from_links(
            session, need, project, link_items, source_rows
        )
        preloaded_payload, preloaded_evidence = service.brief_payload_from_links(
            session,
            need,
            project,
            link_items,
            source_rows,
            preloaded_chain=canonical_chain,
        )
        assert preloaded_payload == legacy_payload
        assert preloaded_evidence == legacy_evidence
        assert (
            len(
                [
                    item
                    for item in preloaded_evidence.values()
                    if item["id"].startswith("buying-chain:")
                ]
            )
            == 2
        )
        assert service.brief_fingerprint(preloaded_payload) == service.brief_fingerprint(
            legacy_payload
        )
        empty_payload, empty_evidence = service.brief_payload_from_links(
            session, need, project, link_items, source_rows, preloaded_chain={"candidates": []}
        )
        assert len(empty_evidence) == 1
        assert not any(item["id"].startswith("buying-chain:") for item in empty_evidence.values())
        assert empty_payload != legacy_payload

        def reject_relationship_query(*_args):
            pytest.fail("supplied preload or disabled relationships must not query the chain")

        monkeypatch.setattr(service, "buying_chain_view", reject_relationship_query)
        disabled_payload, disabled_evidence = service.brief_payload_from_links(
            session,
            need,
            project,
            link_items,
            source_rows,
            include_project_relationship=False,
            preloaded_chain=canonical_chain,
        )
        assert len(disabled_evidence) == 1
        assert not any(
            item["id"].startswith("buying-chain:") for item in disabled_evidence.values()
        )
        assert disabled_payload == empty_payload
        monkeypatch.setattr(
            service,
            "buying_chain_view",
            lambda _session, _project_id: {"candidates": [relationship]},
        )
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint=fingerprint,
            generated_fingerprint=fingerprint,
            policy_version=service.POLICY_VERSION,
            schema_version=service.SCHEMA_VERSION,
            model=settings.openai_brief_model,
            status="ready",
            result={
                "event_summary": [],
                "commercial_hypothesis": {"text": "A cached summary."},
            },
            citations=[],
            generated_at=datetime.now(UTC),
        )
        session.add(row)
        links = link_items
        sources = source_rows
        preview = service.brief_preview(
            session,
            need,
            project,
            links,
            sources,
            row,
        )
        preloaded_preview = service.brief_preview(
            session,
            need,
            project,
            links,
            sources,
            row,
            preloaded_chain=canonical_chain,
        )
        assert preloaded_preview == preview
        assert preview["brief_stale"] is False
        assert preview["brief_status"] == "ready"
        relationship["evidence"][0]["quote"] = (
            "North Campus Development LLC is listed in a separate retained source."
        )
        changed = service.brief_preview(
            session,
            need,
            project,
            [(item[0], item[1], item[2]) for item in raw_links],
            {source.id: source for source in session.scalars(select(Source)).all()},
            row,
        )
        assert changed["brief_stale"] is True
        changed_preloaded = service.brief_preview(
            session,
            need,
            project,
            links,
            sources,
            row,
            preloaded_chain=canonical_chain,
        )
        assert changed_preloaded == changed
        assert "North Campus Development LLC" in detail_payload["need"]["display_title"]
    with factory.begin() as session:
        cached = session.get(PowerNeedBrief, need_id)
        cached.requested_fingerprint = cached.generated_fingerprint
        cached.generated_at = datetime.now(UTC)
        cached.result = {
            "event_summary": [],
            "commercial_hypothesis": {"text": "A cached summary."},
            "unknowns": [],
            "next_step": "Verify the activity.",
        }
        cached.citations = []
        cached.status = "ready"
        cached_fingerprint = cached.requested_fingerprint
        payload, _ = service.brief_input(session, need_id)
        cached_fingerprint = service.brief_fingerprint(payload)
        cached.generated_fingerprint = cached_fingerprint
        cached.requested_fingerprint = cached_fingerprint
        cached.generated_at = datetime.now(UTC)
        cached.status = "ready"
    with factory() as session:
        cached = session.get(PowerNeedBrief, need_id)
        project = session.get(Project, session.get(PowerNeed, need_id).project_id)
        links = session.execute(
            select(Observation, Evidence, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need_id)
        ).all()
        card = service.brief_preview(
            session,
            session.get(PowerNeed, need_id),
            project,
            [(item[0], item[1], item[2]) for item in links],
            {source.id: source for source in session.scalars(select(Source)).all()},
            cached,
        )
        assert card["brief_stale"] is False


def test_uncached_card_preview_does_not_load_relationships(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(
        service,
        "buying_chain_view",
        lambda *_args: pytest.fail("uncached card should not query relationships"),
    )
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        preview = service.brief_preview(session, need, project, [], {}, None)
        assert preview["brief_status"] == "unavailable"


def test_selected_browse_reuses_preloaded_chain_for_persisted_brief(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        payload, _ = service.brief_input(session, need_id)
        fingerprint = service.brief_fingerprint(payload)
        cached = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint=fingerprint,
            generated_fingerprint=fingerprint,
            policy_version=service.POLICY_VERSION,
            schema_version=service.SCHEMA_VERSION,
            model=settings.openai_brief_model,
            status="ready",
            result={
                "event_summary": [],
                "commercial_hypothesis": {"text": "A retained browse summary."},
            },
            citations=[],
            generated_at=datetime.now(UTC),
        )
        session.add(cached)
        session.flush()

        def reject_per_need_chain_query(*_args):
            pytest.fail("selected browse must use its batched canonical chain preload")

        monkeypatch.setattr(service, "buying_chain_view", reject_per_need_chain_query)
        statements = [0]

        def count_statement(*_args):
            statements[0] += 1

        connection = session.connection()
        event.listen(connection, "before_cursor_execute", count_statement)
        try:
            cards, grouped_total = api._commercial_triage_page(session, 50)
            selected = api.opportunity_projection(
                session, tier="Signal", selected_need_ids={need_id}
            )
        finally:
            event.remove(connection, "before_cursor_execute", count_statement)
        assert len(cards) == 1
        assert grouped_total == 1
        assert len(selected) == 1
        assert selected[0]["brief_status"] == "ready"
        assert selected[0]["brief_stale"] is False
        assert selected[0]["brief_summary"] == "A retained browse summary."
        assert statements[0] <= 200


def test_commercial_triage_cards_keeps_list_contract(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory() as session:
        cards = api._commercial_triage_cards(session, 50)
        page_cards, grouped_total = api._commercial_triage_page(session, 50)

    assert isinstance(cards, list)
    assert len(cards) == 1
    assert cards == page_cards
    assert grouped_total == 1


def test_commercial_triage_preflight_query_count_is_bounded_for_50_groups(runtime, monkeypatch):
    factory, _service, _ids = runtime
    api = import_module("gridlens.api.app")
    summaries = [
        {
            "id": UUID(int=40_000 + index),
            "project_id": UUID(int=50_000 + index),
            "tier": "Signal",
            "name": f"Synthetic preflight project {index}",
            "location": f"{1000 + index} Synthetic Test Road",
            "activity": "facility-expansion",
            "evidence": [],
        }
        for index in range(50)
    ]

    def projection(_session, *, summary_only=False, selected_need_ids=None, **_kwargs):
        if summary_only:
            return summaries
        assert selected_need_ids is not None
        return []

    monkeypatch.setattr(api, "opportunity_projection", projection)
    statement_counts = []
    for limit in (1, 50):
        with factory() as session:
            count = [0]

            def count_statement(*_args, query_counter=count):
                query_counter[0] += 1

            connection = session.connection()
            event.listen(connection, "before_cursor_execute", count_statement)
            try:
                cards, grouped_total = api._commercial_triage_page(session, limit)
            finally:
                event.remove(connection, "before_cursor_execute", count_statement)
            assert cards == []
            assert grouped_total == 50
            statement_counts.append(count[0])

    assert statement_counts[1] <= 200
    assert statement_counts[1] <= statement_counts[0] + 2


def test_batched_commercial_preflight_rejects_nested_evidence_before_evaluation_write(
    runtime, monkeypatch
):
    factory, _service, (need_id, evidence_id) = runtime
    api = import_module("gridlens.api.app")
    from gridlens.persistence.models import Pursuit

    with factory.begin() as session:
        evidence = session.get(Evidence, evidence_id)
        observation_id = evidence.observation_id
        project_id = session.get(PowerNeed, need_id).project_id
        session.add_all(
            [
                Evidence(
                    observation_id=observation_id,
                    content_hash=f"{index + 1000:064x}",
                    title="Synthetic retained evidence row",
                    abstract="Evidence retained for the nested-card preflight test.",
                    url=f"https://example.test/evidence/{index}",
                )
                for index in range(api._MAX_COMMERCIAL_CARD_EVIDENCE_ROWS)
            ]
        )

    summary = {
        "id": need_id,
        "project_id": project_id,
        "tier": "Signal",
        "name": "Synthetic nested-evidence project",
        "location": "Test City",
        "activity": "facility-expansion",
        "evidence": [
            {
                "assessment_current": True,
                "source_id": "brief-test-permits",
                "document_number": "nested-evidence-case",
            }
        ],
    }

    def projection(_session, *, summary_only=False, **_kwargs):
        if summary_only:
            return [summary]
        pytest.fail("detail projection must not run after the nested evidence cap is exceeded")

    monkeypatch.setattr(api, "opportunity_projection", projection)
    with factory() as session:
        before = session.scalar(
            select(func.count())
            .select_from(Pursuit)
            .where(Pursuit.identity_key.like("commercial-need:%"))
        )

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.post(
        "/api/commercial/triage/evaluate",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["resource"] == "evidence_rows"
    with factory() as session:
        after = session.scalar(
            select(func.count())
            .select_from(Pursuit)
            .where(Pursuit.identity_key.like("commercial-need:%"))
        )
    assert after == before


def test_opportunity_projection_uses_stable_updated_at_tiebreak(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        first = session.get(PowerNeed, need_id)
        first_project = session.get(Project, first.project_id)
        second = PowerNeed(
            project_id=uuid4(),
            activity_key=first.activity_key,
            tier=first.tier,
            rationale=first.rationale,
            supply=first.supply,
        )
        second_project = Project(
            id=second.project_id,
            identity_key="brief-test-project-stable-order",
            name="Synthetic South Campus",
            location="Test City",
            identity_facts={"site": "Test City, TX"},
            source_id=first_project.source_id,
            external_id="record-2",
        )
        source = session.get(Source, first_project.source_id)
        observation = Observation(
            source_id=source.id,
            external_id="record-2",
            title="Public permit describes construction at Synthetic South Campus",
            abstract="Construction work at Synthetic South Campus in Test City, TX.",
            url="https://example.test/permits/record-2",
            content_hash="b" * 64,
        )
        session.add_all([second_project, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            extraction_location="permit description",
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="brief-test",
            status="accepted",
            assessment={
                "semantic_hash": observation.content_hash,
                "evidence_hash": observation.content_hash,
                "project_identity_key": second_project.identity_key,
                "power_activity": second.activity_key,
                "decision": "accepted",
                "subject": second_project.name,
                "location": second_project.location,
            },
        )
        session.add_all([evidence, interpretation])
        session.add(second)
        session.flush()
        session.add(NeedObservation(need_id=second.id, observation_id=observation.id))
        fixed_updated_at = datetime(2026, 10, 7, tzinfo=UTC)
        session.execute(
            update(PowerNeed)
            .where(PowerNeed.id.in_([first.id, second.id]))
            .values(updated_at=fixed_updated_at)
        )
        session.flush()
        projected = api.opportunity_projection(session, tier="Signal", summary_only=True)
        matching_ids = [
            str(item["id"]) for item in projected if item["id"] in {first.id, second.id}
        ]
        assert matching_ids == sorted([str(first.id), str(second.id)])


def test_bounded_opportunity_page_group_detail_and_stale_cohort(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        first = session.get(PowerNeed, need_id)
        project = session.get(Project, first.project_id)
        source = session.get(Source, project.source_id)
        sibling = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier=first.tier,
            rationale=first.rationale,
            supply=first.supply,
        )
        observation = Observation(
            source_id=source.id,
            external_id="record-search-sibling",
            title="Related campus construction record",
            abstract="A related record without the requested phrase.",
            url="https://example.test/permits/search-sibling",
            content_hash="c" * 64,
        )
        session.add_all([sibling, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            extraction_location="permit description",
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="browse-test",
            status="accepted",
            assessment={
                "semantic_hash": observation.content_hash,
                "evidence_hash": evidence.content_hash,
                "project_identity_key": project.identity_key,
                "power_activity": sibling.activity_key,
                "decision": "accepted",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all([evidence, interpretation])
        session.flush()
        session.add(NeedObservation(need_id=sibling.id, observation_id=observation.id))
        first.updated_at = datetime(2026, 10, 7, 12, tzinfo=UTC)
        sibling.updated_at = datetime(2026, 10, 7, 11, tzinfo=UTC)
        sibling_id = sibling.id

    first_response = Response()
    first_page = api.opportunities(
        tier="Signal",
        search="public permit describes",
        limit=1,
        offset=0,
        cohort=None,
        response=first_response,
    )
    assert len(first_page) == 1
    assert first_response.headers["X-Total-Count"] == "2"
    assert first_response.headers["X-Group-Total-Count"] == "1"
    assert first_page[0]["group_complete_on_page"] is False
    assert first_page[0]["group_loaded_on_page"] == 1
    assert first_page[0]["group_total_filtered"] == 2
    assert first_page[0]["matched_search"] is True
    cohort = first_response.headers["X-Cohort-Token"]

    for missing_cohort in (None, "", "   "):
        with pytest.raises(HTTPException) as missing_token:
            api.opportunities(
                tier="Signal",
                search="public permit describes",
                limit=1,
                offset=1,
                cohort=missing_cohort,
                response=Response(),
            )
        assert missing_token.value.status_code == 422

    second_response = Response()
    second_page = api.opportunities(
        tier="Signal",
        search="public permit describes",
        limit=1,
        offset=1,
        cohort=cohort,
        response=second_response,
    )
    assert [item["id"] for item in second_page] == [sibling_id]
    assert second_response.headers["X-Offset"] == "1"
    assert second_response.headers["X-Cohort-Token"] == cohort

    group_page = api.opportunity_group_page(
        first_page[0]["group_id"],
        cohort_token=cohort,
        tier="Signal",
        search="public permit describes",
        decision=None,
        limit=50,
        offset=0,
    )
    assert group_page["total"] == 2
    assert {item["id"] for item in group_page["items"]} == {need_id, sibling_id}
    assert [item["matched_search"] for item in group_page["items"]].count(True) == 1
    from gridlens.intelligence.opportunity_browse import grouped_signal_decision

    expected_decision = grouped_signal_decision(group_page["items"])
    assert json.loads(first_response.headers["X-Decision-Counts"]) == {
        "SHOW": int(expected_decision == "SHOW"),
        "REVIEW": int(expected_decision == "REVIEW"),
        "HOLD": int(expected_decision == "HOLD"),
    }

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        need.updated_at = datetime(2026, 10, 8, tzinfo=UTC)

    with pytest.raises(HTTPException) as stale:
        api.opportunities(
            tier="Signal",
            search="public permit describes",
            limit=1,
            offset=0,
            decision=None,
            cohort=cohort,
            response=Response(),
        )
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as stale_later_page:
        api.opportunities(
            tier="Signal",
            search="public permit describes",
            limit=1,
            offset=1,
            cohort=cohort,
            response=Response(),
        )
    assert stale_later_page.value.status_code == 409


def test_opportunity_http_and_direct_defaults_are_bounded(runtime):
    _factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")

    response = Response()
    page = api.opportunities(tier="Signal", response=response)

    assert page
    assert response.headers["X-Limit"] == "50"
    assert response.headers["X-Offset"] == "0"

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    http_page = client.get("/api/opportunities", params={"tier": "Signal"})
    assert http_page.status_code == 200
    assert http_page.headers["X-Limit"] == "50"
    assert http_page.headers["X-Offset"] == "0"
    assert client.get("/api/opportunities", params={"limit": 51}).status_code == 422
    token = http_page.headers["X-Cohort-Token"]
    assert token
    assert str(need_id) in {item["id"] for item in http_page.json()}
    for missing_token_params in (
        {"tier": "Signal", "offset": 1},
        {"tier": "Signal", "offset": 1, "cohort_token": ""},
        {"tier": "Signal", "offset": 1, "cohort_token": "   "},
    ):
        assert client.get("/api/opportunities", params=missing_token_params).status_code == 422
    later_page = client.get(
        "/api/opportunities",
        params={"tier": "Signal", "offset": 1, "cohort_token": token},
    )
    assert later_page.status_code == 200
    assert later_page.headers["X-Offset"] == "1"
    assert later_page.headers["X-Cohort-Token"] == token


def test_opportunity_filter_scope_is_shared_by_pages_groups_detail_and_csv(runtime):
    _factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    response = Response()
    page = api.opportunities(
        tier="signal",
        geography="  TEST   CITY ",
        activity="Construction",
        timing="UNKNOWN",
        mw_status="UNKNOWN",
        status="unknown",
        response=response,
    )
    assert [str(item["id"]) for item in page] == [str(need_id)]
    assert page[0]["workflow_status"] == "UNKNOWN"
    assert isinstance(page[0]["priority_segment"], int)
    assert page[0]["priority_label"]
    token = response.headers["X-Cohort-Token"]

    group = api.opportunity_group_page(
        page[0]["group_id"],
        token,
        tier="Signal",
        geography="test city",
        activity="construction",
        timing="unknown",
        mw_status="unknown",
        status="UNKNOWN",
    )
    assert group["total"] == 1
    assert str(group["items"][0]["id"]) == str(need_id)

    detail = api.opportunity_need_detail(
        need_id,
        tier="Signal",
        geography="test city",
        activity="construction",
        timing="UNKNOWN",
        mw_status="UNKNOWN",
        status="UNKNOWN",
        cohort_token=token,
    )
    assert str(detail["id"]) == str(need_id)
    with pytest.raises(HTTPException) as out_of_scope:
        api.opportunity_need_detail(need_id, tier="Signal", geography="Elsewhere")
    assert out_of_scope.value.status_code == 404

    with pytest.raises(HTTPException) as changed:
        api.opportunities(tier="Signal", geography="Elsewhere", cohort=token, response=Response())
    assert changed.value.status_code == 409

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    unsupported = client.get("/api/opportunities", params={"state": "TX"})
    assert unsupported.status_code == 422
    unsupported_status = client.get("/api/opportunities", params={"status": "ACTIVE"})
    assert unsupported_status.status_code == 422
    csv = client.get(
        "/api/opportunities/export.csv",
        params={
            "tier": "Signal",
            "geography": "test city",
            "activity": "construction",
            "timing": "UNKNOWN",
            "mw_status": "UNKNOWN",
            "status": "UNKNOWN",
            "cohort_token": token,
        },
    )
    assert csv.status_code == 200
    assert csv.headers["X-Total-Count"] == "1"
    assert "workflow_status,priority_segment,priority_label" in csv.text.splitlines()[0]
    assert str(need_id) in csv.text


def test_history_routes_preflight_one_oversized_snapshot_before_hydration(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    from gridlens.persistence.models import Pursuit

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        pursuit = Pursuit(
            identity_key="commercial-need:oversized-snapshot-test",
            project_id=need.project_id,
            project_ids=[str(need.project_id)],
            snapshot={"commercial_triage": {"saved_card": {"notes": "x" * 1_000_010}}},
            research_status="not_researched",
            research_errors=[],
        )
        session.add(pursuit)
        session.flush()
        pursuit_id = pursuit.id

    with pytest.raises(HTTPException) as page_error:
        api.commercial_triage_history()
    with pytest.raises(HTTPException) as detail_error:
        api.commercial_triage_history_detail(pursuit_id)

    assert page_error.value.status_code == 413
    assert detail_error.value.status_code == 413
    assert page_error.value.detail["resource"] == "saved_snapshot_bytes"
    assert detail_error.value.detail["resource"] == "saved_snapshot_bytes"


def test_oversized_commercial_group_rejects_before_detail_or_evaluation_write(runtime, monkeypatch):
    factory, _service, _ids = runtime
    api = import_module("gridlens.api.app")
    from gridlens.persistence.models import Pursuit

    summaries = [
        {
            "id": UUID(int=20_000 + index),
            "project_id": UUID(int=30_000 + index),
            "tier": "Signal",
            "name": f"Synthetic project {index}",
            "location": "100 Shared Test Road",
            "activity": "facility-expansion",
            "required_mw": "2",
            "supply": "Unknown",
            "evidence": [
                {
                    "assessment_current": True,
                    "source_id": "synthetic-building-permits",
                    "document_number": "same-official-case",
                }
            ],
        }
        for index in range(51)
    ]
    from gridlens.domain.commercial_triage import grouped_need_groups

    identity, members = grouped_need_groups(summaries)[0]
    expected_group_id = "cg_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    assert len(members) == 51

    def canonical_summary_only(_session, *, summary_only=False, **_kwargs):
        assert summary_only is True
        return summaries

    monkeypatch.setattr(api, "opportunity_projection", canonical_summary_only)
    with factory() as session:
        before = session.scalar(
            select(func.count())
            .select_from(Pursuit)
            .where(Pursuit.identity_key.like("commercial-need:%"))
        )
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    response = client.post(
        "/api/commercial/triage/evaluate",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "commercial_group_too_large"
    assert response.json()["detail"]["group_member_count"] == 51
    assert response.json()["detail"]["group_id"] == expected_group_id
    with factory() as session:
        after = session.scalar(
            select(func.count())
            .select_from(Pursuit)
            .where(Pursuit.identity_key.like("commercial-need:%"))
        )
    assert after == before


def test_opportunity_search_rejects_single_oversized_retained_text(runtime):
    factory, _service, (need_id, evidence_id) = runtime
    api = import_module("gridlens.api.app")

    with factory.begin() as session:
        evidence = session.get(Evidence, evidence_id)
        evidence.abstract = "x" * (api._MAX_OPPORTUNITY_SEARCH_FIELD_BYTES + 1)

    with pytest.raises(HTTPException) as oversized:
        api.opportunities(
            tier="Signal",
            search="never-matches",
            limit=50,
            offset=0,
            cohort=None,
            response=Response(),
        )
    assert oversized.value.status_code == 413


def test_search_byte_budget_counts_unassessed_retained_evidence(runtime, monkeypatch):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "_MAX_OPPORTUNITY_SEARCH_COHORT_BYTES", 40)

    with factory.begin() as session:
        base_need = session.get(PowerNeed, need_id)
        project = session.get(Project, base_need.project_id)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction-unassessed-history",
            tier="Signal",
            rationale="Synthetic unassessed search budget case",
            supply="Unknown",
        )
        source = session.get(Source, project.source_id)
        session.add(need)
        session.flush()
        links = []
        for index in range(2):
            observation = Observation(
                source_id=source.id,
                external_id=f"unassessed-budget-{index}",
                title="unassessed title",
                abstract="retained older abstract text",
                url=f"https://example.test/unassessed/{index}",
                content_hash=f"{index + 10:064x}",
            )
            session.add(observation)
            session.flush()
            evidence = Evidence(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                extraction_location="test",
            )
            session.add(evidence)
            links.append(NeedObservation(need_id=need.id, observation_id=observation.id))
        session.add_all(links)
        session.flush()
        unassessed_need_id = need.id

    with factory() as session, pytest.raises(HTTPException) as oversized:
        api._opportunity_evidence_search_matches(
            session,
            [{"id": unassessed_need_id, "name": "Synthetic project"}],
            "never matches",
        )

    assert oversized.value.status_code == 413


def test_cohort_rejects_retained_text_change_without_need_timestamp_change(runtime):
    factory, _service, (_need_id, evidence_id) = runtime
    api = import_module("gridlens.api.app")
    response = Response()
    api.opportunities(
        tier="Signal", search="", limit=50, offset=0, decision=None, cohort=None, response=response
    )
    token = response.headers["X-Cohort-Token"]
    with factory.begin() as session:
        evidence = session.get(Evidence, evidence_id)
        evidence.title = "A different retained title with stable need timestamp"

    with pytest.raises(HTTPException) as stale:
        api.opportunities(
            tier="Signal",
            search="",
            limit=50,
            offset=0,
            decision=None,
            cohort=token,
            response=Response(),
        )
    assert stale.value.status_code == 409


def test_search_uses_final_derived_title_and_joined_evidence_fields(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        observation = Observation(
            source_id="brief-test-permits",
            external_id="record-company-old",
            title="Older retained supporting permit owner Test City, TX",
            abstract="owner_company_name: Example Holdings",
            url="https://example.test/permits/company-old",
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
            observed_at=datetime(2026, 10, 1, tzinfo=UTC),
            extraction_location="permit description",
        )
        session.add(evidence)
        session.flush()
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                evaluator_version="browse-title-order-test",
                status="accepted",
                assessment={
                    "semantic_hash": observation.content_hash,
                    "evidence_hash": evidence.content_hash,
                    "evidence": {"id": str(evidence.id)},
                    "project_identity_key": project.identity_key,
                    "power_activity": need.activity_key,
                    "decision": "accepted",
                    "subject": project.name,
                    "location": project.location,
                    "owner_company_name": "Example Holdings",
                },
            )
        )
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))

    with factory() as session:
        summary = next(
            item
            for item in api.opportunity_projection(session, tier="Signal", summary_only=True)
            if item["id"] == need_id
        )
        summary["_browse_first_evidence"] = {}
        summary["_browse_action_candidates"] = summary.get("_browse_action_candidates", [])
        company_evidence_match = api._opportunity_evidence_search_matches(
            session, [summary], "owner test city"
        )[str(need_id)]
        assert summary.get("_browse_company_candidates") == {
            "owner_company_name": ["Example Holdings"]
        }
        assert api.opportunity_project_title(summary) == "Example Holdings · owner"
        assert company_evidence_match
        selected_details = api.opportunity_projection(
            session, tier="Signal", selected_need_ids={need_id}
        )
        assert selected_details

    title_boundary = Response()
    title_matches = api.opportunities(
        tier="Signal",
        search="owner test city",
        limit=50,
        offset=0,
        cohort=None,
        response=title_boundary,
    )
    evidence_boundary = api.opportunities(
        tier="Signal",
        search="record-company-old brief-test-permits",
        limit=50,
        offset=0,
        cohort=None,
        response=Response(),
    )

    assert title_boundary.headers["X-Total-Count"] == "1"
    assert any(str(item["id"]) == str(need_id) and item["matched_search"] for item in title_matches)
    assert any(
        str(item["id"]) == str(need_id) and item["matched_search"] for item in evidence_boundary
    )


def test_authenticated_csv_matches_filtered_cohort_and_declares_scope(runtime):
    _factory, _service, _ids = runtime
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    assert client.get("/api/opportunities/export.csv?tier=Signal").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    page = client.get("/api/opportunities", params={"tier": "Signal", "decision": "ALL"})
    assert page.status_code == 200
    exported = client.get(
        "/api/opportunities/export.csv",
        params={
            "tier": "Signal",
            "decision": "ALL",
            "cohort_token": page.headers["X-Cohort-Token"],
        },
    )
    assert exported.status_code == 200
    assert exported.headers["X-Export-Scope"] == "all_filtered_matches"
    assert exported.headers["X-Total-Count"] == page.headers["X-Total-Count"]
    assert "export_scope,cohort_token" in exported.text.splitlines()[0]
    assert len(exported.text.splitlines()) == int(exported.headers["X-Total-Count"]) + 1


@pytest.mark.parametrize("conflicting_demand", [False, True])
def test_summary_batches_preserve_cross_boundary_case_siblings_and_compact_history(
    runtime, conflicting_demand, monkeypatch
):
    factory, _service, _ids = runtime
    api = import_module("gridlens.api.app")
    from gridlens.domain.commercial_triage import _priority, grouped_need_ids

    permit = next(row for row in load_registry() if row["id"] == "austin-building-permits")
    source = Source(
        **{key: value for key, value in permit.items() if key in Source.__table__.columns}
    )
    site = "100 Test Road, Austin, TX"
    qualification_site = "100 Test Road"

    def qualification_text(
        required_mw: str,
        *,
        include_lead: bool = True,
        contradictory_supply: bool = False,
        buyer_role: str = "electrical contractor",
    ) -> str:
        description = f"{qualification_site} construction requires {required_mw} MW. "
        description += f"Power supply for {qualification_site} construction is unavailable. "
        if include_lead:
            description += (
                f"{qualification_site} construction starts between 2026-11-01 and 2026-11-05. "
                f"{qualification_site} construction lasts 30 to 60 days. "
                f"No suitable power supply is available for {qualification_site} construction "
                "throughout this start window and duration. "
                f"The {buyer_role} is responsible for power procurement for "
                f"{qualification_site} construction."
            )
        if contradictory_supply:
            description += (
                f" Total suitable power supply available for {qualification_site} construction "
                "is 1 MW throughout this start window and duration."
            )
        return f"description: {description}\naddress: {qualification_site}"

    created: list[tuple[PowerNeed, Project, Observation]] = []
    for index in range(129):
        if index == 0:
            need_id = UUID(int=1)
            external_id = "2019-123456 BP"
        elif index == 128:
            need_id = UUID(int=1000)
            external_id = "2019-123456 EP"
        else:
            need_id = UUID(int=index + 1)
            external_id = f"2020-{index:06d} BP"
        project_id = uuid4()
        project = Project(
            id=project_id,
            identity_key=f"bounded-summary-project-{index}",
            name=f"Permit project {index}",
            location=site,
            source_id=source.id,
            external_id=external_id,
        )
        need = PowerNeed(
            id=need_id,
            project_id=project_id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic batch-boundary regression",
            supply="Unknown",
        )
        content_hash = f"{index + 1:064x}"
        title = (
            f"Building permit was issued for {project.name} data center campus at {site}"
            if index == 1
            else f"Building permit for {project.name} at {site}"
        )
        observation = Observation(
            source_id=source.id,
            external_id=external_id,
            title=title,
            abstract=(
                qualification_text("1", contradictory_supply=conflicting_demand)
                if index == 1
                else f"Construction work for {project.name} at {site}."
            ),
            url=f"https://example.test/austin/{index}",
            content_hash=content_hash,
            published_at=datetime(2026, 10, 1, tzinfo=UTC).date(),
        )
        created.append((need, project, observation))
    large_need, large_project, _large_observation = created[1]
    extra_observations = [
        Observation(
            source_id=source.id,
            external_id=f"2021-{index:06d} BP",
            title=(
                f"Building permit was issued for {large_project.name} data center campus "
                f"at {site} ({index})"
            ),
            abstract=(
                f"Construction work for {large_project.name} at {site}."
                if conflicting_demand
                else qualification_text(
                    "1",
                    buyer_role=("general contractor" if index % 2 else "project owner"),
                )
            ),
            url=f"https://example.test/austin/large/{index}",
            content_hash=f"{50000 + index:064x}",
            published_at=datetime(2026, 9, 1, tzinfo=UTC).date(),
        )
        for index in range(260)
    ]

    with factory.begin() as session:
        session.add(source)
        session.flush()
        session.add_all([project for _need, project, _observation in created])
        session.flush()
        session.add_all(
            [row for need, _project, observation in created for row in (need, observation)]
            + extra_observations
        )
        session.flush()
        evidence_rows = []
        interpretation_rows = []
        need_observation_rows = []
        lifecycle_event_rows = []
        for index, (need, project, observation) in enumerate(created):
            evidence = Evidence(
                id=uuid4(),
                observation_id=observation.id,
                content_hash=observation.content_hash,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                published_at=observation.published_at,
                extraction_location="permit description",
            )
            evidence_rows.append(evidence)
            if need.id == large_need.id:
                lifecycle_event_rows.append(
                    LifecycleEvent(
                        project_id=project.id,
                        observation_id=observation.id,
                        evidence_id=evidence.id,
                        event_type="building_permit_issued",
                        state="permitting",
                    )
                )
            interpretation_rows.append(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="bounded-summary-test",
                    status="accepted",
                    assessment={
                        "semantic_hash": observation.content_hash,
                        "evidence_hash": evidence.content_hash,
                        "evidence": {"id": str(evidence.id)},
                        "project_identity_key": project.identity_key,
                        "power_activity": need.activity_key,
                        "decision": "accepted",
                        "subject": project.name,
                        "location": project.location,
                    },
                )
            )
            need_observation_rows.append(
                NeedObservation(need_id=need.id, observation_id=observation.id)
            )
            if index == 0:
                evidence_rows.extend(
                    Evidence(
                        observation_id=observation.id,
                        content_hash=f"{10000 + old:064x}",
                        title=f"Historical permit revision {old}",
                        abstract="Old retained revision.",
                        url=f"https://example.test/austin/{index}/history/{old}",
                        published_at=datetime(2025, 1, 1, tzinfo=UTC).date(),
                        extraction_location="historical permit revision",
                    )
                    for old in range(64)
                )
        for observation in extra_observations:
            evidence = Evidence(
                id=uuid4(),
                observation_id=observation.id,
                content_hash=observation.content_hash,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                published_at=observation.published_at,
                extraction_location="permit description",
            )
            evidence_rows.append(evidence)
            lifecycle_event_rows.append(
                LifecycleEvent(
                    project_id=large_project.id,
                    observation_id=observation.id,
                    evidence_id=evidence.id,
                    event_type="building_permit_issued",
                    state="permitting",
                )
            )
            assessment = {
                "semantic_hash": observation.content_hash,
                "evidence_hash": evidence.content_hash,
                "evidence": {"id": str(evidence.id)},
                "project_identity_key": large_project.identity_key,
                "power_activity": large_need.activity_key,
                "decision": "accepted",
                "subject": large_project.name,
                "location": large_project.location,
            }
            if conflicting_demand:
                assessment.update(
                    {
                        "tier": "Prospect",
                        "demand_mw": "2 MW",
                        "demand_quote": "Construction demand is 2 MW.",
                        "supply_quote": "Construction supply is unavailable.",
                        "reason": "Legacy accepted Prospect assessment.",
                    }
                )
            interpretation_rows.append(
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="bounded-summary-test",
                    status="accepted",
                    assessment=assessment,
                )
            )
            need_observation_rows.append(
                NeedObservation(need_id=large_need.id, observation_id=observation.id)
            )
        fact_rows = []
        fact_decisions = []
        status_rows = []
        now = datetime.now(UTC)
        for index, (need, project, _observation) in enumerate(created[:50]):
            fact_id = uuid4()
            fact_hash = hashlib.sha256(f"a6-bulk-fact-{index}".encode()).hexdigest()
            fact_rows.append(
                CallFactVersion(
                    id=fact_id,
                    need_id=need.id,
                    project_id=project.id,
                    client_id=uuid4(),
                    activity_key=need.activity_key,
                    facility_scope=project.location,
                    fact_type="demand",
                    value={"mw": "1"},
                    reporter_name="Synthetic bulk fixture",
                    confirmation_channel="customer_call",
                    confirmed_at=now,
                    effective_from=now - timedelta(days=1),
                    content_hash=fact_hash,
                    recorded_by="Synthetic fixture",
                )
            )
            fact_decisions.append(
                CallFactDecision(
                    need_id=need.id,
                    fact_version_id=fact_id,
                    version=1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=0,
                    reason="Synthetic current fact for bounded batch test",
                    content_hash=fact_hash,
                    actor="Synthetic fixture",
                )
            )
            status_rows.append(
                NeedWorkflowStatusEvent(
                    need_id=need.id,
                    project_id=project.id,
                    version=1,
                    client_id=uuid4(),
                    status="Investigating",
                    expected_version=0,
                    reason="Synthetic current status for bounded batch test",
                    content_hash=hashlib.sha256(f"a6-bulk-status-{index}".encode()).hexdigest(),
                    actor="Synthetic fixture",
                )
            )
        session.add_all(fact_rows)
        session.flush()
        session.add_all(
            evidence_rows
            + interpretation_rows
            + need_observation_rows
            + lifecycle_event_rows
            + fact_decisions
            + status_rows
        )
        session.flush()
        session.expunge_all()

        stats: dict[str, int] = {}
        query_count = [0]

        def count_summary_query(*_args):
            query_count[0] += 1

        connection = session.connection()
        event.listen(connection, "before_cursor_execute", count_summary_query)
        tracemalloc.start()
        try:
            summary = api.opportunity_projection(
                session, summary_only=True, summary_diagnostics=stats
            )
        finally:
            _, peak_python_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            event.remove(connection, "before_cursor_execute", count_summary_query)
        assert query_count[0] <= 200
        assert peak_python_bytes < 56_000_000
        print(
            "A6 synthetic summary batch: "
            f"needs={len(created)} facts={len(fact_rows)} statuses={len(status_rows)} "
            f"queries={query_count[0]} peak_python_bytes={peak_python_bytes}"
        )

        engine = factory.kw["bind"]

        class ExistingSessionContext:
            def __enter__(self):
                return session

            def __exit__(self, *_exc):
                return False

        monkeypatch.setattr(api, "SessionLocal", lambda: ExistingSessionContext())

        def measure_handler(label, handler):
            statements = [0]

            def count_handler_query(*_args):
                statements[0] += 1

            event.listen(engine, "before_cursor_execute", count_handler_query)
            tracemalloc.start()
            started = time.perf_counter()
            try:
                result, group_count = handler()
                encoded = json.dumps(
                    result, default=str, sort_keys=True, separators=(",", ":")
                ).encode()
                _, peak_bytes = tracemalloc.get_traced_memory()
                elapsed = time.perf_counter() - started
            finally:
                tracemalloc.stop()
                event.remove(engine, "before_cursor_execute", count_handler_query)
            records = result.get("items", []) if isinstance(result, dict) else result
            assert len(records) == 50, f"{label} handler returned {len(records)} records"
            assert statements[0] <= 200
            assert peak_bytes < 56_000_000
            print(
                "A6 synthetic page handler: "
                f"kind={label} records={len(records)} groups={group_count} "
                f"queries={statements[0]} elapsed_seconds={elapsed:.4f} "
                f"peak_python_bytes={peak_bytes} serialized_bytes={len(encoded)}"
            )

        def public_handler():
            response = Response()
            rows = api.opportunities(limit=50, response=response)
            return rows, int(response.headers["X-Group-Total-Count"])

        def commercial_handler():
            result = api.commercial_triage(limit=50)
            return result, result["grouped_total"]

        measure_handler("public", public_handler)
        measure_handler("commercial", commercial_handler)
        full = api.opportunity_projection(session)
        summary_ids = [str(row["id"]) for row in summary]
        full_ids = [str(row["id"]) for row in full]
        assert summary_ids == full_ids
        summary_by_id = {str(row["id"]): row for row in summary}
        for need, _project, _observation in created[:50]:
            row = summary_by_id[str(need.id)]
            assert row["workflow_status"] == "Investigating"
            assert len(row["_current_fact_digest"]) == 64
        assert {str(row["id"]): _priority(row) for row in summary} == {
            str(row["id"]): _priority(row) for row in full
        }
        summary_groups = grouped_need_ids(summary)
        assert summary_groups == grouped_need_ids(full)
        cross_batch_group = next(group for group in summary_groups if str(UUID(int=1)) in group)
        assert cross_batch_group == sorted([str(UUID(int=1)), str(UUID(int=1000))])
        assert stats["candidate_rows_scanned"] == 130
        assert stats["max_candidate_batch_size"] == 128
        assert stats["max_compact_need_states_per_batch"] == 128
        assert stats["max_current_link_rows_per_need"] == 261
        assert stats["max_resident_link_orm_rows"] <= 3 * stats["link_fetch_chunk_size"]
        assert stats["lifecycle_rows_streamed"] == 261
        assert stats["supported_lifecycle_rows"] == 261
        assert stats["max_resident_lifecycle_orm_rows"] <= (4 * stats["lifecycle_fetch_chunk_size"])
        assert stats["historical_date_rows_aggregated"] == 130
        assert stats["historical_evidence_orm_rows"] == 0
        large_full = next(row for row in full if row["id"] == large_need.id)
        expected_tier = "Signal" if conflicting_demand else "Lead"
        assert large_full["tier"] == expected_tier
        assert large_full["required_mw"] == (None if conflicting_demand else "1 MW")
        assert large_full["qualification_conflict"] is conflicting_demand
        assert large_full["conflict_state"] == (
            "CONFLICT" if conflicting_demand else "Not assessed"
        )
        tier_summary = api.opportunity_projection(
            session,
            tier=expected_tier,
            summary_only=True,
            selected_need_ids={large_need.id},
        )
        tier_full = api.opportunity_projection(
            session,
            tier=expected_tier,
            selected_need_ids={large_need.id},
        )
        assert [row["id"] for row in tier_summary] == [large_need.id]
        assert [row["id"] for row in tier_full] == [large_need.id]
        summary_large = next(row for row in summary if row["id"] == large_need.id)
        first_full_support = next(
            row for row in large_full["evidence"] if row["assessment_current"]
        )
        assert str(summary_large["evidence"][0]["id"]) == str(first_full_support["id"])
        if not conflicting_demand:
            assert large_full["commercial_size_status"] == "at_or_above_floor"
            assert large_full["next_action"] == (
                "Contact the electrical contractor to verify the open power package."
            )


def test_summary_projection_preserves_preloaded_session_rows(runtime):
    factory, _service, (need_id, evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory() as session:
        evidence = session.get(Evidence, evidence_id)
        assert evidence is not None
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        assert interpretation is not None
        summary = api.opportunity_projection(
            session,
            tier="Signal",
            summary_only=True,
            selected_need_ids={need_id},
        )
        assert [row["id"] for row in summary] == [need_id]
        assert session.get(Evidence, evidence_id) is evidence
        assert session.get(Interpretation, interpretation.id) is interpretation


def test_summary_and_detail_share_batched_houston_title_attribution(runtime, monkeypatch):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    project_id = None
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None
        project = session.get(Project, need.project_id)
        assert project is not None
        project_id = project.id
        session.add(
            Source(
                id="houston-weekly-permits",
                publisher="Synthetic Houston",
                endpoint="https://example.test/houston",
                family="construction-permits",
                geography="Houston",
                industries=["construction"],
                retrieval_method="houston-weekly-permits",
                health={},
            )
        )
        session.flush()
        project.source_id = "houston-weekly-permits"

    requested_batches = []

    def with_owner_occupant(_session, project_ids):
        requested_batches.append(set(project_ids))
        return {
            str(project_id): {
                "permit_summaries": [
                    {
                        "facts": [
                            {
                                "label": "Permit-listed owner / occupant",
                                "value": "Synthetic Houston Operator LLC",
                            }
                        ]
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "buying_chain_views", with_owner_occupant)
    with factory() as session:
        diagnostics = {}
        summary = api.opportunity_projection(
            session,
            summary_only=True,
            selected_need_ids={need_id},
            summary_diagnostics=diagnostics,
        )[0]
        detail = api.opportunity_projection(session, selected_need_ids={need_id})[0]
        assert summary["title_company"] == detail["title_company"]
        assert summary["title_company_role"] == detail["title_company_role"]
        assert summary["title_company"] == "Synthetic Houston Operator LLC"
        assert len(requested_batches) == 2
        assert all(len(batch) <= 32 for batch in requested_batches)
        assert diagnostics["title_company_project_count"] == 1
        assert diagnostics["title_company_batch_count"] == 1
        assert diagnostics["max_title_company_batch_size"] == 1

    monkeypatch.setattr(api, "buying_chain_views", lambda _session, _ids: {})
    with factory() as session:
        summary_without_attribution = api.opportunity_projection(
            session,
            summary_only=True,
            selected_need_ids={need_id},
        )[0]
        assert summary_without_attribution["title_company"] is None
        assert summary_without_attribution["title_company_role"] is None


def test_provider_failure_retains_last_good_brief_without_blind_retry(runtime, monkeypatch):
    factory, service, (need_id, evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-fingerprint",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Last good advisory."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=1,
            output_tokens=1,
        )
        session.add(row)
    with factory.begin() as session:
        requested = _request_due_brief(session, service, need_id)
        job_id = requested["job_id"]
    from gridlens.jobs.queue import lease_one

    with factory.begin() as session:
        job, fence = lease_one(session, "brief-test-worker", job_ids=[UUID(job_id)])
    monkeypatch.setattr(
        service,
        "_provider",
        lambda _payload, _evidence: (_ for _ in ()).throw(TimeoutError("provider timeout")),
    )
    service.process_brief_job(job_id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        job = session.get(Job, job_id)
        assert row and row.result["commercial_hypothesis"]["text"] == "Last good advisory."
        assert row.status == "failed"
        assert job and job.status == "failed"
        assert job.attempts == 1
        assert row.error == "request_failed"


def test_rejected_provider_output_keeps_usage_and_safe_reason(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        requested = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(requested["job_id"]))
    assert leased
    job, fence = leased

    def rejected(_payload, evidence):
        evidence_id, source = next(iter(evidence.items()))
        return (
            {
                "selected_fact_ids": ["invented-fact-id"],
                "hypothesis_fact_id": "invented-fact-id",
            },
            123,
            45,
            settings.openai_brief_model,
        )

    monkeypatch.setattr(service, "_provider", rejected)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "failed"
        assert row.error == "invalid_fact_selection"
        assert (row.input_tokens, row.output_tokens) == (123, 45)


@pytest.mark.parametrize(
    ("raw", "expected_reason"),
    [
        (
            {
                "id": "resp-brief-model-mismatch",
                "model": "unconfigured-alias",
                "usage": {"input_tokens": 123, "output_tokens": 45},
                "output": [],
            },
            "MODEL_IDENTITY_MISMATCH",
        ),
        (
            {
                "id": "resp-brief-output-overbound",
                "model": "gpt-5-mini",
                "usage": {"input_tokens": 123, "output_tokens": 701},
                "output": [],
            },
            "ENFORCED_OUTPUT_BOUND_EXCEEDED",
        ),
    ],
)
def test_brief_received_invalid_output_quarantines_metadata_before_local_rejection(
    runtime, monkeypatch, raw, expected_reason
):
    factory, service, (need_id, _evidence_id) = runtime
    if expected_reason == "ENFORCED_OUTPUT_BOUND_EXCEEDED":
        raw = {**raw, "model": settings.openai_brief_model}
    with factory.begin() as session:
        requested = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(requested["job_id"]))
    assert leased
    job, fence = leased
    from gridlens.integrations import intelligence_provider
    from gridlens.persistence.models import LogicalCall

    def invalid_output(*_args, **_kwargs):
        raise intelligence_provider.ProviderResponseError(
            "synthetic completed invalid brief output",
            request_id="req-brief-invalid-output",
            response_received=True,
            raw_response=raw,
            reported_model=raw["model"],
            reported_usage=raw["usage"],
        )

    monkeypatch.setattr(intelligence_provider, "call_openai_request", invalid_output)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        call = session.scalar(select(LogicalCall))
        row = session.get(PowerNeedBrief, need_id)
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == f"BILLING_QUARANTINE:{expected_reason}"
    assert call.result_payload["billing_quarantine"]["response"]["provider_request_id"] == (
        "req-brief-invalid-output"
    )
    assert row and row.status == "failed"


def _valid_model_result(_payload, facts):
    fact_id = next(iter(facts))
    return (
        {"selected_fact_ids": [fact_id], "hypothesis_fact_id": fact_id},
        120,
        40,
        settings.openai_brief_model,
    )


def _request_due_brief(session, service, need_id):
    """A new immediate-lease fixture is due despite sub-ms DB/Python clock skew."""
    requested = service.request_brief(session, need_id)
    job = session.get(Job, UUID(requested["job_id"]))
    assert job is not None and job.status == "queued" and job.attempts == 0
    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    return requested


def _lease(factory, job_id):
    from gridlens.jobs.queue import lease_one

    with factory.begin() as session:
        return lease_one(session, "brief-test-worker", job_ids=[job_id])


def test_budget_reservation_and_expired_reserved_job_never_call_provider(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(settings, "briefs_daily_request_limit", 1)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
        today = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()
        session.add(BriefDailyBudget(day=today, reserved_requests=1))
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    calls = []
    monkeypatch.setattr(service, "_provider", lambda payload, _facts: calls.append(payload))
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        assert calls == []
        assert session.get(Job, job.id).status == "failed"
        assert session.get(PowerNeedBrief, need_id).error == "daily_budget_exhausted"

    with factory.begin() as session:
        row = session.get(PowerNeedBrief, need_id)
        job = session.get(Job, job.id)
        row.status = "pending"
        row.error = None
        job.status = "queued"
        job.attempts = 0
        job.checkpoint = None
        retry = service.request_brief(session, need_id)
    leased = _lease(factory, UUID(retry["job_id"]))
    assert leased
    job, fence = leased
    with factory.begin() as session:
        running = session.get(Job, job.id)
        running.checkpoint = '{"reserved": true}'
        running.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    leased_again = _lease(factory, job.id)
    assert leased_again
    retry_job, retry_fence = leased_again
    service.process_brief_job(retry_job.id, "brief-test-worker", retry_fence)
    with factory() as session:
        assert calls == []
        assert session.get(Job, retry_job.id).status == "failed"
        assert session.get(PowerNeedBrief, need_id).error == "ambiguous_prior_request"


def test_input_changes_fence_worker_and_last_good_version_history(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-request",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Last good advisory."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=10,
            output_tokens=5,
        )
        session.add(row)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased

    def change_input_during_call(payload, facts):
        with factory.begin() as session:
            session.get(PowerNeed, need_id).start_window = "Q4 unknown source"
        return _valid_model_result(payload, facts)

    monkeypatch.setattr(service, "_provider", change_input_during_call)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row.status == "stale"
        assert row.result["commercial_hypothesis"]["text"] == "Last good advisory."
        assert session.scalar(select(func.count()).select_from(PowerNeedBriefVersion)) == 0


def test_non_permit_application_uses_source_neutral_unknown(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        observation = session.scalar(select(Observation))
        observation.title = "Massachusetts cultivation application for Synthetic North Campus"
        observation.abstract = "Cultivation application at Synthetic North Campus in Test City."
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    monkeypatch.setattr(service, "_provider", _valid_model_result)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "ready"
        assert (
            "Whether the reported activity creates any temporary or backup power need is unknown."
            in row.result["unknowns"]
        )
        assert all("permit creates" not in item for item in row.result["unknowns"])


def test_a_to_b_to_a_refresh_preserves_current_cache_status(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        payload_a, _ = service.brief_input(session, need_id)
        fingerprint_a = service.brief_fingerprint(payload_a)
        session.add(
            PowerNeedBrief(
                need_id=need_id,
                requested_fingerprint=fingerprint_a,
                generated_fingerprint=fingerprint_a,
                policy_version=service.POLICY_VERSION,
                schema_version=service.SCHEMA_VERSION,
                model=settings.openai_brief_model,
                status="ready",
                result={
                    "event_summary": [],
                    "commercial_hypothesis": {
                        "text": "Cached A advisory.",
                        "evidence_id": "cached-evidence",
                    },
                    "unknowns": [],
                    "next_step": "Verify the activity.",
                },
                citations=[],
                generated_at=datetime.now(UTC),
            )
        )
        session.get(PowerNeed, need_id).start_window = "Input B"
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased

    def return_to_a_during_b_call(payload, facts):
        with factory.begin() as session:
            session.get(PowerNeed, need_id).start_window = None
        return _valid_model_result(payload, facts)

    monkeypatch.setattr(service, "_provider", return_to_a_during_b_call)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(f"/api/power-needs/{need_id}/brief")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["stale"] is False
    with factory() as session:
        row = session.get(PowerNeedBrief, need_id)
        assert row and row.status == "ready"
        assert row.generated_fingerprint == fingerprint_a
        assert row.result["commercial_hypothesis"]["text"] == "Cached A advisory."


def test_successful_replacement_archives_old_policy_model_and_schema(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    with factory.begin() as session:
        row = PowerNeedBrief(
            need_id=need_id,
            requested_fingerprint="old-request",
            generated_fingerprint="old-fingerprint",
            policy_version="old-policy",
            schema_version="old-schema",
            model="old-model",
            status="ready",
            result={"commercial_hypothesis": {"text": "Old accepted brief."}},
            citations=[],
            generated_at=datetime.now(UTC),
            input_tokens=10,
            output_tokens=5,
        )
        session.add(row)
    with factory.begin() as session:
        queued = _request_due_brief(session, service, need_id)
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    monkeypatch.setattr(service, "_provider", _valid_model_result)
    service.process_brief_job(job.id, "brief-test-worker", fence)
    with factory() as session:
        version = session.scalar(
            select(PowerNeedBriefVersion).where(PowerNeedBriefVersion.need_id == need_id)
        )
        row = session.get(PowerNeedBrief, need_id)
        assert version and version.result["commercial_hypothesis"]["text"] == "Old accepted brief."
        assert (version.policy_version, version.schema_version, version.model) == (
            "old-policy",
            "old-schema",
            "old-model",
        )
        assert row and row.status == "ready"
        assert row.model == settings.openai_brief_model


@pytest.mark.parametrize("commercial", [False, True])
@pytest.mark.parametrize("provider_fails", [False, True])
def test_authenticated_brief_request_and_worker_keep_saved_maps_current(
    runtime, monkeypatch, commercial, provider_fails
):
    from gridlens.intelligence.saved_browse import current_generation, rebuild
    from gridlens.intelligence.worker_browse import install_worker_publication
    from gridlens.persistence.browse_invalidation import install
    from gridlens.persistence.models import BrowseState

    factory, service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.kw["bind"].begin() as connection:
        install(connection)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(factory.kw["bind"], expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", worker_factory)
    install_worker_publication(worker_factory)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    reads = []

    def verify_current():
        with factory() as reader:
            assert (
                current_generation(reader).input_revision
                == reader.get(BrowseState, 1).input_revision
            )
        response = client.get("/api/opportunities/map-window?tier=Signal&decision=ALL")
        reads.append(response.status_code)
        assert response.status_code == 200, response.text

    def after_commit(session):
        if not session.in_nested_transaction():
            try:
                verify_current()
            except HTTPException as exc:
                raise AssertionError(
                    f"Post-commit browse pending: {session.info.get('worker_browse_outcome')}"
                ) from exc

    provider_calls = []

    def synthetic_provider(payload, evidence):
        verify_current()  # The request remains usable while the provider is in flight.
        provider_calls.append(payload)
        assert "PRIVATE-BRIEF-TEST" not in json.dumps(payload)
        if provider_fails:
            raise TimeoutError("synthetic provider timeout")
        return _valid_model_result(payload, evidence)

    monkeypatch.setattr(service, "_provider", synthetic_provider)
    event.listen(worker_factory, "after_commit", after_commit)
    try:
        route = (
            f"/api/commercial/triage/{need_id}/research"
            if commercial
            else f"/api/power-needs/{need_id}/brief"
        )
        body = {"question": "Which source confirms the construction stage?"} if commercial else {}
        response = client.post(route, json=body, headers={"origin": "https://testserver"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "pending"
        verify_current()
        job_id = UUID(response.json()["job_id"])
        leased = _lease(factory, job_id)
        assert leased
        _job, fence = leased
        service.process_brief_job(job_id, "brief-test-worker", fence)
        verify_current()
    finally:
        event.remove(worker_factory, "after_commit", after_commit)
        client.close()
    assert len(reads) >= 4
    assert len(provider_calls) == 1
    with factory() as session:
        assert session.get(PowerNeedBrief, need_id).status == (
            "failed" if provider_fails else "ready"
        )
        assert session.get(Job, job_id).status == ("failed" if provider_fails else "succeeded")


def test_brief_api_requires_auth_and_same_origin_for_explicit_request(runtime):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    assert client.get(f"/api/power-needs/{need_id}/brief").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    assert client.get(f"/api/power-needs/{need_id}/brief").json()["status"] == "unavailable"
    response = client.post(
        f"/api/power-needs/{need_id}/brief",
        headers={"origin": "https://attacker.invalid"},
        json={},
    )
    assert response.status_code == 403
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_legacy_brief_adapter_owner_unlimited_keeps_usage_and_count_caps(runtime, monkeypatch):
    factory, _service, _need = runtime
    from gridlens.integrations.legacy_calls import perform_legacy_call
    from gridlens.persistence.models import LogicalCall, LogicalCallBudget

    monkeypatch.setattr(settings, "intelligence_financial_budget_mode", "owner_unlimited")
    monkeypatch.setattr(settings, "intelligence_financial_authorization_ref", "fixture-auth-brief")
    monkeypatch.setattr(settings, "intelligence_unlimited_providers", "openai")
    monkeypatch.setattr(settings, "intelligence_unlimited_contracts", "POWER_NEED_BRIEF")
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", 0)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", 0)

    result = perform_legacy_call(
        task_type="POWER_NEED_BRIEF",
        task_key="owner-unlimited-brief",
        payload={"brief": {"need": {}, "unknowns": []}, "facts": {}},
        source_id=None,
        project_id=None,
        job_id=None,
        worker_id=None,
        fence_token=1,
        invoke=lambda: (
            {"actual_model": settings.openai_brief_model, "output": {"selected": []}},
            17,
            9,
        ),
    )
    with factory() as session:
        call = session.get(LogicalCall, result.logical_call_id)
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
    assert not result.cached
    assert call and call.status == "COMPLETED"
    assert call.financial_budget_mode == "owner_unlimited"
    assert call.financial_authorization_ref == "fixture-auth-brief"
    assert call.max_cost_usd is None and call.estimated_cost_usd is None
    assert call.input_tokens == 17 and call.output_tokens == 9
    assert call.result_payload["usage_cost_estimate"]["estimated_cost_usd"] is not None
    assert budget and budget.call_count == 1 and budget.cost_usd == 0


def test_missing_provider_key_and_wrong_project_evidence_fail_closed(runtime, monkeypatch):
    factory, service, (need_id, _evidence_id) = runtime
    monkeypatch.setattr(settings, "openai_api_key", None)
    from gridlens.intelligence.briefs import BriefUnavailable

    with factory.begin() as session:
        with pytest.raises(BriefUnavailable, match="provider_not_configured"):
            service.request_brief(session, need_id)
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            **interpretation.assessment,
            "project_identity_key": "another-project",
        }
        session.flush()
        with pytest.raises(BriefUnavailable, match="no_current_public_evidence"):
            service.brief_input(session, need_id)


def test_rank_sort_orders_the_whole_cohort_before_paging(runtime, monkeypatch):
    factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        first = session.get(PowerNeed, need_id)
        project = session.get(Project, first.project_id)
        source = session.get(Source, project.source_id)
        sibling = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier=first.tier,
            rationale=first.rationale,
            supply=first.supply,
        )
        observation = Observation(
            source_id=source.id,
            external_id="record-rank-sibling",
            title="Related campus construction record",
            abstract="A related record.",
            url="https://example.test/permits/rank-sibling",
            content_hash="d" * 64,
        )
        session.add_all([sibling, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            extraction_location="permit description",
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            evaluator_version="browse-test",
            status="accepted",
            assessment={
                "semantic_hash": observation.content_hash,
                "evidence_hash": evidence.content_hash,
                "project_identity_key": project.identity_key,
                "power_activity": sibling.activity_key,
                "decision": "accepted",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all([evidence, interpretation])
        session.flush()
        session.add(NeedObservation(need_id=sibling.id, observation_id=observation.id))
        # The sibling is older, so the default order puts it second.
        first.updated_at = datetime(2026, 10, 7, 12, tzinfo=UTC)
        sibling.updated_at = datetime(2026, 10, 7, 11, tzinfo=UTC)
        sibling_id = sibling.id

    scores = {str(sibling_id): 90, str(need_id): 10}
    seen_chains = []

    def fake_rank(item, chain, today):
        seen_chains.append(chain)
        score = scores[str(item["id"])]
        return {"rank_score": score, "rank_reasons": [f"score {score}"], "rank_version": "t"}

    monkeypatch.setattr(api, "rank_opportunity", fake_rank)

    updated_response = Response()
    updated = api.opportunities(
        tier="Signal", limit=1, offset=0, cohort=None, response=updated_response
    )
    assert str(updated[0]["id"]) == str(need_id)

    ranked_response = Response()
    ranked = api.opportunities(
        tier="Signal", limit=1, offset=0, cohort=None, response=ranked_response, sort="rank"
    )
    # The older but higher-ranked record leads, and the shown score is the ordering score.
    assert str(ranked[0]["id"]) == str(sibling_id)
    assert ranked[0]["rank_score"] == 90
    assert ranked_response.headers["X-Cohort-Token"] != updated_response.headers["X-Cohort-Token"]

    second = api.opportunities(
        tier="Signal",
        limit=1,
        offset=1,
        cohort=ranked_response.headers["X-Cohort-Token"],
        response=Response(),
        sort="rank",
    )
    assert str(second[0]["id"]) == str(need_id) and second[0]["rank_score"] == 10
    with pytest.raises(HTTPException) as mixed:
        api.opportunities(
            tier="Signal",
            limit=1,
            offset=1,
            cohort=ranked_response.headers["X-Cohort-Token"],
            response=Response(),
        )
    assert mixed.value.status_code == 409
    # Record detail validates cohort membership, so it accepts the rank cohort's token.
    detail = api.opportunity_need_detail(
        need_id=sibling_id, tier="Signal", cohort_token=ranked_response.headers["X-Cohort-Token"]
    )
    assert str(detail["id"]) == str(sibling_id)


def test_rank_sort_scores_match_the_displayed_detail_rank(runtime):
    _factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    updated = api.opportunities(tier="Signal", limit=50, offset=0, cohort=None, response=Response())
    ranked = api.opportunities(
        tier="Signal", limit=50, offset=0, cohort=None, response=Response(), sort="rank"
    )
    by_id = {str(item["id"]): item for item in updated}
    assert ranked and str(need_id) in by_id
    for item in ranked:
        canonical = by_id[str(item["id"])]
        assert (item["rank_score"], item["rank_reasons"]) == (
            canonical["rank_score"],
            canonical["rank_reasons"],
        )


def test_map_window_matches_ranked_pages_and_keeps_detail_reads_bounded(runtime, monkeypatch):
    _factory, _service, (need_id, _evidence_id) = runtime
    api = import_module("gridlens.api.app")
    original_ranks = api._cohort_ranks
    original_preflight = api._preflight_opportunity_details
    rank_calls = 0
    detail_batches = []

    def counted_ranks(session, items, tier):
        nonlocal rank_calls
        rank_calls += 1
        return original_ranks(session, items, tier)

    def counted_preflight(session, rows):
        detail_batches.append(len(rows))
        return original_preflight(session, rows)

    monkeypatch.setattr(api, "_cohort_ranks", counted_ranks)
    monkeypatch.setattr(api, "_preflight_opportunity_details", counted_preflight)
    result = api.opportunity_map_window(tier="Signal", search="", decision="ALL")
    assert result["loaded_count"] == len(result["items"]) == 1
    assert result["total_count"] == 1
    assert result["is_subset"] is False
    assert result["window_limit"] == 200
    assert rank_calls == 1
    assert detail_batches and all(0 < batch <= 50 for batch in detail_batches)

    # The map's globally ranked first window is byte-for-byte aligned on the fields
    # that define identity, score, explanations, and the rank policy with legacy pages.
    page_response = Response()
    pages = api.opportunities(
        tier="Signal",
        search="",
        decision="ALL",
        limit=50,
        offset=0,
        cohort=None,
        response=page_response,
        sort="rank",
    )
    assert result["cohort_token"] == page_response.headers["X-Cohort-Token"]
    by_id = {str(item["id"]): item for item in pages}
    assert [str(item["id"]) for item in result["items"]] == [str(item["id"]) for item in pages]
    for item in result["items"]:
        legacy = by_id[str(item["id"])]
        assert (item["rank_score"], item["rank_reasons"], item["rank_version"]) == (
            legacy["rank_score"],
            legacy["rank_reasons"],
            legacy["rank_version"],
        )
    assert str(need_id) in by_id


def test_ranked_map_window_keeps_global_winners_and_stable_ties_past_boundaries():
    api = import_module("gridlens.api.app")
    rows = [{"id": f"need-{index:03}", "updated_order": index} for index in range(205)]
    ranks = {
        row["id"]: {"rank_score": 10, "rank_reasons": ["baseline"], "rank_version": "v"}
        for row in rows
    }
    # The winner is outside the newest 200. Equal scores cross both the legacy page
    # boundary and the 200-item window boundary; source order remains the tie-breaker.
    ranks["need-200"]["rank_score"] = 100
    ranks["need-199"]["rank_score"] = 99
    ranks["need-049"]["rank_score"] = 98
    ranks["need-050"]["rank_score"] = 98
    ranks["need-198"]["rank_score"] = 11
    ranked = api._rank_opportunity_summaries(rows, ranks)
    window = ranked[:200]
    assert ranked[0]["id"] == "need-200"
    assert [row["id"] for row in ranked[2:4]] == ["need-049", "need-050"]
    assert [row["id"] for row in ranked[48:52]] == ["need-043", "need-044", "need-045", "need-046"]
    assert len(window) == 200
    assert window[-1]["id"] == "need-196"
    assert all(row["id"] != "need-197" for row in window)


def test_map_window_http_auth_query_and_payload_bounds(runtime, monkeypatch):
    _factory, _service, _need = runtime
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    assert client.get("/api/opportunities/map-window").status_code == 401
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get("/api/opportunities/map-window", params={"tier": "Signal"})
    assert response.status_code == 200
    assert response.json()["window_limit"] == 200
    assert response.json()["loaded_count"] == len(response.json()["items"])
    for params in (
        {"unknown": "1"},
        {"tier": "candidate"},
        {"decision": "MAYBE"},
        {"search": "x" * 251},
    ):
        assert client.get("/api/opportunities/map-window", params=params).status_code == 422

    # A complete response exceeding the established aggregate byte budget fails closed.
    monkeypatch.setattr(api, "_MAX_OPPORTUNITY_PAGE_BYTES", 1)
    oversized = client.get("/api/opportunities/map-window", params={"tier": "Signal"})
    assert oversized.status_code == 413


def test_map_window_http_byte_cap_includes_envelope_metadata(runtime, monkeypatch):
    _factory, _service, _need = runtime
    api = import_module("gridlens.api.app")
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    params = {"tier": "Signal"}
    payload = api.opportunity_map_window(tier="Signal", search="", decision="ALL")
    encoded_items = json.dumps(payload["items"], default=str, separators=(",", ":")).encode("utf-8")
    encoded_window = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    items_size = len(encoded_items)
    window_size = len(encoded_window)
    assert window_size > items_size

    # Exact equality is accepted by the same full-envelope helper the route uses.
    monkeypatch.setattr(api, "_MAX_OPPORTUNITY_PAGE_BYTES", window_size)
    assert api._bounded_opportunity_map_window_payload(payload) is payload

    # This cap accepts the old list-only check, but cannot hold the envelope too.
    between_sizes = items_size + (window_size - items_size) // 2
    assert items_size < between_sizes < window_size
    monkeypatch.setattr(api, "_MAX_OPPORTUNITY_PAGE_BYTES", between_sizes)
    assert api._bounded_opportunity_payload(payload["items"]) is payload["items"]
    response = client.get("/api/opportunities/map-window", params=params)
    assert response.status_code == 413


@pytest.mark.parametrize("resource", ["evidence", "lifecycle"])
def test_map_window_rejects_rows_over_existing_per_record_caps(runtime, resource):
    factory, _service, (need_id, evidence_id) = runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        observation_id = session.scalar(
            select(NeedObservation.observation_id).where(NeedObservation.need_id == need_id)
        )
        if resource == "evidence":
            session.add_all(
                [
                    Evidence(
                        observation_id=observation_id,
                        content_hash=f"{index + 1000:064x}",
                        title=f"Synthetic retained version {index}",
                        abstract="Bound test evidence.",
                        url=f"https://example.test/versions/{index}",
                        extraction_location="test",
                    )
                    for index in range(api._MAX_OPPORTUNITY_EVIDENCE_ROWS)
                ]
            )
        else:
            session.add_all(
                [
                    LifecycleEvent(
                        project_id=need.project_id,
                        observation_id=observation_id,
                        evidence_id=evidence_id,
                        event_type=f"bounded-test-{index}",
                        state="construction",
                    )
                    for index in range(api._MAX_OPPORTUNITY_LIFECYCLE_ROWS + 1)
                ]
            )
    with pytest.raises(HTTPException) as oversized:
        api.opportunity_map_window(tier="Signal", search="", decision="ALL")
    assert oversized.value.status_code == 413
    expected = "evidence" if resource == "evidence" else "lifecycle"
    assert expected in oversized.value.detail.lower()
