import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
    Job,
    LogicalCall,
    LogicalCallBudget,
    NeedObservation,
    Observation,
    PowerNeed,
    PowerNeedTitle,
    PowerNeedTitleVersion,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def title_runtime(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for title PostgreSQL tests")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    admin = create_engine(settings.test_database_url)
    schema = "title_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    titles = import_module("gridlens.intelligence.titles")
    worker = import_module("gridlens.jobs.worker")
    legacy_calls = import_module("gridlens.integrations.legacy_calls")
    for module in (api, titles, worker, legacy_calls):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-title-key"))
    monkeypatch.setattr(settings, "power_need_titles_enabled", True)
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "POWER_NEED_TITLE")
    monkeypatch.setattr(settings, "intelligence_openai_enabled", True)
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_model", settings.openai_brief_model
    )
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_priced_model_id", settings.openai_brief_model
    )
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_pricing_verified", True)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_max_output_tokens", 700)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_input_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_output_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", 1)
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 5)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_calls", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_calls", 1000)
        monkeypatch.setattr(settings, f"intelligence_{scope}_daily_usd", 100)
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", 1000)
    with factory.begin() as session:
        source = Source(
            id="title-test-permits",
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
            identity_key="title-test-project",
            name="Synthetic North Campus",
            location="Test City",
            source_id=source.id,
            external_id="record-1",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic integration fixture",
            supply="Unknown",
        )
        observation = Observation(
            source_id=source.id,
            external_id="record-1",
            title="Synthetic North Campus construction permit",
            abstract="Activity: Building substations for the Synthetic North Campus.",
            url="https://example.test/permits/record-1",
            content_hash="a" * 64,
            published_at=date(2026, 10, 15),
        )
        session.add_all([need, observation])
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="permit description",
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="title-test",
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
                ),
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )
        need_id = need.id
    yield factory, api, titles, need_id
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def _client(api):
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    return client


def _enqueue(client, need_id):
    return client.post(
        f"/api/power-needs/{need_id}/title",
        json={},
        headers={"origin": "https://testserver"},
    )


def _lease(factory, job_id):
    from gridlens.jobs.queue import lease_one

    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        return lease_one(session, "title-test-worker", job_ids=[job_id])


def _provider_result(request, *, model=None, input_tokens=100, output_tokens=30):
    source = json.loads(request["input"][1]["content"][0]["text"])
    activity_options = source["activity_options"]
    activity_id = next(
        (
            key
            for key, option in activity_options.items()
            if option["quote"].startswith("Activity:")
        ),
        next(iter(activity_options)),
    )
    role_id = next(iter(source["role_options"]), None)
    return {
        "model": model or request["model"],
        "output": {"role_option_id": role_id, "activity_option_id": activity_id},
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _rewrite_current_evidence(session, abstract, content_hash="b" * 64):
    observation = session.scalar(select(Observation))
    evidence = session.scalar(select(Evidence))
    interpretation = session.scalar(select(Interpretation))
    observation.abstract = abstract
    observation.content_hash = content_hash
    evidence.abstract = abstract
    evidence.content_hash = content_hash
    interpretation.content_hash = content_hash
    interpretation.assessment = {
        **interpretation.assessment,
        "semantic_hash": content_hash,
        "evidence_hash": content_hash,
    }


def _add_current_buying_chain_relationship(factory, need_id):
    from gridlens.domain.buying_chain import POLICY_VERSION
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain_extraction import document_content_hash

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        excerpt = (
            "Activity: Building substations for the Synthetic North Campus.\n"
            "Owner/operator: Synthetic North Campus Holdings LLC."
        )
        observation = session.get(Observation, evidence.observation_id)
        observation.abstract = excerpt
        observation.content_hash = "b" * 64
        evidence.abstract = excerpt
        evidence.content_hash = "b" * 64
        interpretation.content_hash = evidence.content_hash
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
        }
        source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=evidence.id,
            url=evidence.url,
            title=evidence.title,
            excerpt=excerpt,
            content_hash="c" * 64,
            extraction_location="permit description",
            published_at=evidence.published_at,
            observed_at=evidence.observed_at,
            last_seen_at=datetime.now(UTC),
            project_match_reason=(
                "Current retained source supports a direct owner/operator relationship."
            ),
        )
        session.add(source)
        session.flush()
        public_quote = "Public filing: Synthetic North Campus Holdings LLC is the owner/operator."
        public_document = PublicDocument(
            url="https://example.test/public-owner",
            title="Synthetic North Campus public owner filing",
            text=public_quote,
            published_at=date(2026, 10, 15),
            observed_at=datetime.now(UTC),
            extraction_location="Public filing, section 1",
        )
        public_source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=None,
            url=public_document.url,
            title=public_document.title,
            excerpt=public_document.text,
            content_hash=document_content_hash(public_document),
            extraction_location=public_document.extraction_location,
            published_at=public_document.published_at,
            observed_at=public_document.observed_at,
            last_seen_at=public_document.observed_at,
            project_match_reason=(
                "Bounded public filing matches the selected project and organization."
            ),
        )
        session.add(public_source)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="d" * 64,
            fingerprint="e" * 64,
            policy_version=POLICY_VERSION,
            organization="Synthetic North Campus Holdings LLC",
            person_name=None,
            title=None,
            category="asset_operator",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="UNKNOWN",
            evidence_strength="High",
            reason="Source-listed owner/operator for this project.",
            citations=[
                {
                    "evidence_id": str(source.id),
                    "url": source.url,
                    "quote": "Owner/operator: Synthetic North Campus Holdings LLC.",
                    "supports": "project_organization",
                },
                {
                    "evidence_id": str(public_source.id),
                    "url": public_source.url,
                    "quote": public_quote,
                    "supports": "project_organization",
                },
            ],
            public_contacts=[],
            observed_at=datetime.now(UTC),
        )
        session.add(claim)
        session.flush()
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="f" * 64,
                evidence_ids=[str(source.id)],
                claim_ids=[str(claim.id)],
                policy_version=POLICY_VERSION,
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )


def test_authenticated_queue_mock_worker_persists_and_projects_title(title_runtime, monkeypatch):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    _add_current_buying_chain_relationship(factory, need_id)

    calls = []

    def provider(*, api_key, request):
        calls.append(request)
        return _provider_result(request)

    monkeypatch.setattr(intelligence_provider, "call_openai_request", provider)
    client = _client(api)
    first = _enqueue(client, need_id)
    second = _enqueue(client, need_id)
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert client.get(f"/api/power-needs/{need_id}/title").json()["status"] == "pending"
    assert calls == []
    leased = _lease(factory, UUID(first.json()["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    ready = client.get(f"/api/power-needs/{need_id}/title")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    title = ready.json()["result"]["title"]
    assert "Activity: Building substations for the Synthetic North Campus." in title
    assert "Synthetic North Campus Holdings LLC - asset_operator" in title
    assert any(
        citation["quote"].startswith("Owner/operator:") for citation in ready.json()["citations"]
    )
    assert (
        "Public filing: Synthetic North Campus Holdings LLC"
        in calls[0]["input"][1]["content"][0]["text"]
    )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion)) == 1
        job = session.get(Job, job.id)
        assert job.status == "succeeded" and job.lease_owner is None and job.lease_until is None
    cached = _enqueue(client, need_id)
    assert cached.status_code == 200 and cached.json()["status"] == "ready"
    assert cached.json()["job_id"] is None and len(calls) == 1

    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    workspace = client.get("/api/opportunities/workspace?limit=10")
    detail = client.get(f"/api/opportunities/needs/{need_id}")
    assert workspace.status_code == detail.status_code == 200
    assert workspace.json()["items"][0]["browse_title"] == title
    assert detail.json()["browse_title"] == title
    assert detail.json()["title_citations"] == ready.json()["citations"]


def test_default_disabled_and_authenticated_read_boundary(title_runtime, monkeypatch):
    _factory, api, _titles, need_id = title_runtime
    client = _client(api)
    monkeypatch.setattr(settings, "power_need_titles_enabled", False)
    get_response = client.get(f"/api/power-needs/{need_id}/title")
    post_response = _enqueue(client, need_id)
    assert get_response.status_code == post_response.status_code == 200
    assert get_response.json()["status"] == post_response.json()["status"] == "disabled"
    unauthenticated = TestClient(api.app, base_url="https://testserver")
    assert unauthenticated.get(f"/api/power-needs/{need_id}/title").status_code == 401
    assert (
        unauthenticated.post(
            f"/api/power-needs/{need_id}/title", json={}, headers={"origin": "https://testserver"}
        ).status_code
        == 401
    )


def test_metadata_only_evidence_fails_without_provider_reservation(title_runtime, monkeypatch):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    provider_calls = []
    monkeypatch.setattr(
        intelligence_provider,
        "call_openai_request",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    with factory.begin() as session:
        _rewrite_current_evidence(
            session,
            "Permit number: 2026-127192 EP\n"
            "Address: 1212 Example Street, Test City\n"
            "Phone: (512) 555-0100",
        )
    queued = _enqueue(_client(api), need_id)
    assert queued.status_code == 200 and queued.json()["status"] == "pending"
    leased = _lease(factory, UUID(queued.json()["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        title = session.get(PowerNeedTitle, need_id)
        job = session.get(Job, job.id)
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 0
    assert provider_calls == []
    assert title and title.status == "failed" and title.error == "no_supported_title_component"
    assert job and job.status == "failed" and job.error == "no_supported_title_component"
    assert job.lease_owner is None and job.lease_until is None


@pytest.mark.parametrize("changed", ["evidence", "source_disabled"])
def test_stale_or_disabled_input_fails_before_provider_and_clears_lease(
    title_runtime, monkeypatch, changed
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    calls = []
    monkeypatch.setattr(
        intelligence_provider,
        "call_openai_request",
        lambda **kwargs: calls.append(kwargs),
    )
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    if changed == "evidence":
        with factory.begin() as session:
            evidence = session.scalar(select(Evidence))
            _rewrite_current_evidence(session, f"{evidence.abstract} amended")
    else:
        with factory.begin() as session:
            session.scalar(select(Source)).enabled = False
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        title = session.get(PowerNeedTitle, need_id)
        job = session.get(Job, job.id)
        assert title.status in {"stale", "failed"}
        assert job.status == "failed" and job.lease_owner is None and job.lease_until is None
    assert calls == []


def test_input_change_during_provider_call_never_publishes_current_title(
    title_runtime, monkeypatch
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    def provider(*, api_key, request):
        with factory.begin() as session:
            evidence = session.scalar(select(Evidence))
            _rewrite_current_evidence(session, f"{evidence.abstract} changed during call")
        return _provider_result(request)

    monkeypatch.setattr(intelligence_provider, "call_openai_request", provider)
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        title = session.get(PowerNeedTitle, need_id)
        assert title.status == "stale" and title.result is None
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion)) == 0
        assert session.get(Job, job.id).status == "failed"


def test_source_disabled_during_provider_call_is_terminal_without_replay(
    title_runtime, monkeypatch
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    calls = []

    def provider(*, api_key, request):
        calls.append(request)
        with factory.begin() as session:
            session.scalar(select(Source)).enabled = False
        return _provider_result(request)

    monkeypatch.setattr(intelligence_provider, "call_openai_request", provider)
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        title = session.get(PowerNeedTitle, need_id)
        job = session.get(Job, job.id)
        call = session.scalar(select(LogicalCall))
        assert title.status == "failed" and title.error == "current_evidence_unavailable"
        assert job.status == "failed" and job.lease_owner is None and job.lease_until is None
        assert call.status == "COMPLETED" and call.output_tokens == 30
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion)) == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("bad_model", "input_tokens", "output_tokens", "reason"),
    [
        ("wrong-title-model", 100, 30, "MODEL_IDENTITY_MISMATCH"),
        (None, "bad-usage", 30, "INVALID_REPORTED_USAGE"),
        (None, 100, 241, "ENFORCED_OUTPUT_BOUND_EXCEEDED"),
    ],
)
def test_wrong_model_and_malformed_usage_are_quarantined(
    title_runtime, monkeypatch, bad_model, input_tokens, output_tokens, reason
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    def provider(*, api_key, request):
        return _provider_result(
            request,
            model=bad_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    monkeypatch.setattr(intelligence_provider, "call_openai_request", provider)
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        call = session.scalar(select(LogicalCall))
        assert call.status == "SENT_OUTCOME_UNKNOWN"
        assert call.blocked_reason == f"BILLING_QUARANTINE:{reason}"
        quarantine = call.result_payload["billing_quarantine"]
        assert quarantine["reason"] == reason
        assert quarantine["expected_model"] == settings.openai_brief_model
        expected_input = input_tokens if isinstance(input_tokens, int) else None
        expected_output = output_tokens if isinstance(output_tokens, int) else None
        assert quarantine["usage"]["input_tokens"] == expected_input
        assert quarantine["usage"]["output_tokens"] == expected_output
        budget_keys = {
            (item["scope"], item["period"], item["period_key"]) for item in call.budget_scopes
        }
        budgets = session.scalars(select(LogicalCallBudget)).all()
        reserved = [
            row for row in budgets if (row.scope, row.period, row.period_key) in budget_keys
        ]
        assert len(reserved) == len(budget_keys)
        assert all(row.active_count == 1 for row in reserved)
        assert session.get(PowerNeedTitle, need_id).status == "failed"


def test_unknown_dispatch_is_not_retried_and_lost_fence_cannot_publish(title_runtime, monkeypatch):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    calls = []

    def uncertain(**_kwargs):
        calls.append(True)
        raise intelligence_provider.ProviderResponseError(
            "synthetic network uncertainty", response_received=False
        )

    monkeypatch.setattr(intelligence_provider, "call_openai_request", uncertain)
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        call = session.scalar(select(LogicalCall))
        assert call.status == "SENT_OUTCOME_UNKNOWN"
        assert session.get(PowerNeedTitle, need_id).status == "failed"
    retried = _enqueue(client, need_id).json()
    assert retried["job_id"] and retried["job_id"] != queued["job_id"]
    retry_lease = _lease(factory, UUID(retried["job_id"]))
    assert retry_lease
    retry_job, retry_fence = retry_lease
    titles.process_title_job(retry_job.id, "title-test-worker", retry_fence)
    assert calls == [True]

    new_request = _enqueue(client, need_id).json()
    lost_lease = _lease(factory, UUID(new_request["job_id"]))
    assert lost_lease
    lost_job, lost_fence = lost_lease
    with factory.begin() as session:
        current = session.get(Job, lost_job.id)
        current.fence += 1
    with pytest.raises(RuntimeError, match="Worker lease fence lost"):
        titles.process_title_job(lost_job.id, "title-test-worker", lost_fence)
    with factory() as session:
        assert session.get(PowerNeedTitle, need_id).status != "ready"
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion)) == 0


def test_expired_unknown_title_job_reuses_saved_call_after_pricing_change(
    title_runtime, monkeypatch
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    calls = []

    def uncertain(**_kwargs):
        calls.append(True)
        raise intelligence_provider.ProviderResponseError(
            "synthetic network uncertainty", response_received=False
        )

    monkeypatch.setattr(intelligence_provider, "call_openai_request", uncertain)
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        original_call = session.scalar(select(LogicalCall))
        saved_job = session.get(Job, job.id)
        checkpoint = json.loads(saved_job.checkpoint)
        assert original_call and original_call.status == "SENT_OUTCOME_UNKNOWN"
        assert checkpoint["logical_call_id"] == str(original_call.id)
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_input_usd_per_million", Decimal("2")
    )
    with factory.begin() as session:
        current = session.get(Job, job.id)
        current.status = "running"
        current.lease_owner = "crashed-title-worker"
        current.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        current.available_at = datetime.now(UTC) - timedelta(seconds=1)
    retry_lease = _lease(factory, job.id)
    assert retry_lease
    retry_job, retry_fence = retry_lease
    titles.process_title_job(retry_job.id, "title-test-worker", retry_fence)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        assert session.get(Job, job.id).checkpoint == saved_job.checkpoint
        assert session.get(PowerNeedTitle, need_id).status == "failed"
    assert calls == [True]


def test_expired_title_job_reuses_completed_call_without_second_provider_request(
    title_runtime, monkeypatch
):
    factory, api, titles, need_id = title_runtime
    from gridlens.integrations import intelligence_provider

    provider_calls = []

    def provider(**kwargs):
        provider_calls.append(kwargs)
        return _provider_result(kwargs["request"])

    monkeypatch.setattr(intelligence_provider, "call_openai_request", provider)
    validate_title = titles.validate_title
    monkeypatch.setattr(
        titles,
        "validate_title",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    client = _client(api)
    queued = _enqueue(client, need_id).json()
    leased = _lease(factory, UUID(queued["job_id"]))
    assert leased
    job, fence = leased
    with pytest.raises(KeyboardInterrupt):
        titles.process_title_job(job.id, "title-test-worker", fence)
    with factory() as session:
        call = session.scalar(select(LogicalCall))
        current = session.get(Job, job.id)
        checkpoint = json.loads(current.checkpoint)
        assert call and call.status == "COMPLETED"
        assert checkpoint["logical_call_id"] == str(call.id)
    with factory.begin() as session:
        current = session.get(Job, job.id)
        current.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        current.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(titles, "validate_title", validate_title)
    retry_lease = _lease(factory, job.id)
    assert retry_lease
    retry_job, retry_fence = retry_lease
    titles.process_title_job(retry_job.id, "title-test-worker", retry_fence)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        assert session.get(PowerNeedTitle, need_id).status == "ready"
        assert session.scalar(select(func.count()).select_from(PowerNeedTitleVersion)) == 1
    assert len(provider_calls) == 1
