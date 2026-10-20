import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.intelligence_jobs import (
    enqueue_intelligence,
    intelligence_history,
)
from gridlens.persistence import database
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    LogicalCall,
    LogicalCallBudget,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
    Pursuit,
    PursuitResearchQuestion,
    SignalDecision,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def sessions():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _enable_bounded_typesafe(monkeypatch):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "evaluation",
        "intelligence_typesafe_enabled": True,
        "intelligence_enabled_contracts": "SOURCE_RELEVANCE_V1",
        "jev_enabled": True,
        "typesafe_api_key": SecretStr("fixture-only"),
        "intelligence_typesafe_model": "pinned-fixture-model",
        "intelligence_typesafe_priced_model_id": "pinned-fixture-model",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": Decimal("1"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
        "intelligence_typesafe_max_output_tokens": 100,
        "intelligence_typesafe_output_limit_verified": True,
        "intelligence_typesafe_billing_mode": "input_only",
        "intelligence_typesafe_billing_model_id": "pinned-fixture-model",
        "intelligence_typesafe_billing_contract_id": "systemone-v1",
        "intelligence_typesafe_billing_policy_id": "typesafe-total-input-ceiling-v1",
        "intelligence_typesafe_billing_reference": "synthetic://fixture/typesafe-input-only-total-input-ceiling-20000",
        "intelligence_typesafe_billing_verified": True,
        "intelligence_typesafe_max_total_billable_input_tokens": 20_000,
        "intelligence_typesafe_total_input_bound_verified": True,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))


def _seed_job(sessions, *, task_type="SOURCE_RELEVANCE_V1", question_id=None, link_pursuit=False):
    source_id = "intelligence-fixture-source"
    need_id = uuid4()
    project_id = uuid4()
    observation_id = uuid4()
    evidence_id = uuid4()
    with sessions.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Fixture Utility",
                endpoint="https://example.invalid",
                family="test",
                geography="fixture",
                industries=["power"],
                retrieval_method="test",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        session.add(
            Project(
                id=project_id,
                identity_key="fixture-project",
                name="Fixture Data Center",
                source_id=source_id,
                external_id="fixture-1",
                identity_facts={"identity": "fixture"},
            )
        )
        session.flush()
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key="fixture-construction",
                rationale="Fixture only; testing bounded advisory processing.",
                required_mw="12 MW",
                start_window="2027",
                duration="temporary",
                supply="Unknown",
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id="fixture-evidence",
                title="Fixture project seeks utility coordination",
                abstract="Temporary load of 12 MW is requested in the utility service application.",
                published_at=date(2026, 10, 1),
                url="https://example.invalid/fixture",
                content_hash="a" * 64,
            )
        )
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash="a" * 64,
                title="Fixture project seeks utility coordination",
                abstract="Temporary load of 12 MW is requested in the utility service application.",
                url="https://example.invalid/fixture",
                published_at=date(2026, 10, 1),
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))
        if link_pursuit:
            session.add(
                Pursuit(
                    identity_key="fixture-pursuit",
                    project_id=project_id,
                    project_ids=[str(project_id)],
                    snapshot={},
                    research_status="not_researched",
                )
            )
        job = enqueue_intelligence(
            session,
            need_id=need_id,
            task_type=task_type,
            question_id=question_id,
            origin="test",
        )
        job_id = job.id
    return need_id, evidence_id, job_id


def test_retained_context_uses_accepted_supplement_hashes_independently(sessions):
    from gridlens.intelligence.intelligence_jobs import _retained_context

    need_id, _evidence_id, _job_id = _seed_job(sessions)
    semantic_hash = "b" * 64
    evidence_hash = "c" * 64
    with sessions.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        session.add(
            Source(
                id="research-public-fixture",
                publisher="Research Supplement",
                endpoint="https://example.invalid/research",
                family="public-research",
                geography="fixture",
                industries=["power"],
                retrieval_method="fixture",
                enabled=False,
                registry_enabled=False,
                health={},
            )
        )
        session.flush()
        observation = Observation(
            source_id="research-public-fixture",
            external_id="accepted-supplement",
            title="Supplement page 4",
            abstract="Later page quote proves the retained distinction.",
            published_at=date(2026, 10, 2),
            url="https://example.invalid/research/accepted",
            content_hash=semantic_hash,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=evidence_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="PDF pages 1-4 (inline page markers)",
        )
        session.add(evidence)
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation.id))
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash=semantic_hash,
                status="accepted",
                assessment={
                    "admission_status": "project_research_supplement",
                    "semantic_hash": semantic_hash,
                    "evidence_hash": evidence_hash,
                    "target_need_id": str(need_id),
                    "project_identity_key": project.identity_key,
                },
            )
        )
        rejected = Observation(
            source_id="research-public-fixture",
            external_id="quarantine-supplement",
            title="Quarantined text",
            abstract="This text must never enter context.",
            published_at=date(2026, 10, 3),
            url="https://example.invalid/research/quarantine",
            content_hash="d" * 64,
        )
        session.add(rejected)
        session.flush()
        session.add(
            Evidence(
                observation_id=rejected.id,
                content_hash="e" * 64,
                title=rejected.title,
                abstract=rejected.abstract,
                url=rejected.url,
                published_at=rejected.published_at,
            )
        )
        session.add(NeedObservation(need_id=need_id, observation_id=rejected.id))
        session.add(
            Interpretation(
                observation_id=rejected.id,
                content_hash=rejected.content_hash,
                status="quarantined",
                assessment={"admission_status": "project_research_supplement"},
            )
        )
    with sessions() as session:
        _need, _project, _source, retained = _retained_context(session, need_id)
    by_hash = {row["content_hash"]: row for row in retained}
    assert evidence_hash in by_hash
    assert semantic_hash != by_hash[evidence_hash]["content_hash"]
    assert "e" * 64 not in by_hash


def test_retained_context_marks_scanned_text_unavailable_without_ocr_provenance(sessions):
    from gridlens.intelligence.intelligence_jobs import _retained_context

    need_id, _evidence_id, _job_id = _seed_job(sessions)
    with sessions.begin() as session:
        for external_id, digest, provenance in (
            ("scan-unavailable", "f" * 64, {"scan_detected": True}),
            (
                "ocr-retained-unreviewed",
                "9" * 64,
                {
                    "scan_detected": True,
                    "ocr": {
                        "original_document_hash": "9" * 64,
                        "method": "tesseract",
                        "version": "5.3.0",
                        "review_status": "unreviewed",
                        "transcript_hash": "8" * 64,
                    },
                },
            ),
        ):
            observation = Observation(
                source_id="intelligence-fixture-source",
                external_id=external_id,
                title="Scanned filing page 2",
                abstract="Page 2: Recognized transcript text from the source image.",
                published_at=date(2026, 10, 2),
                url=f"https://example.invalid/{external_id}",
                content_hash=digest,
            )
            session.add(observation)
            session.flush()
            session.add(
                Evidence(
                    observation_id=observation.id,
                    content_hash=digest,
                    title=observation.title,
                    abstract=observation.abstract,
                    url=observation.url,
                    published_at=observation.published_at,
                    extraction_location="scanned PDF page 2",
                    provenance=provenance,
                )
            )
            session.add(NeedObservation(need_id=need_id, observation_id=observation.id))
    with sessions() as session:
        _need, _project, _source, retained = _retained_context(session, need_id)
    unavailable = next(row for row in retained if row["retained_text_status"] == "unavailable_ocr")
    accepted_ocr = next(
        row for row in retained if row["retained_text_status"] == "retained_ocr_unreviewed"
    )
    assert unavailable["abstract"] == ""
    assert accepted_ocr["abstract"].startswith("Page 2:")
    assert accepted_ocr["ocr_provenance"]["original_document_hash"] == "9" * 64


def test_retained_context_omits_opaque_binary_tail_with_original_offsets(sessions):
    from gridlens.intelligence.intelligence_jobs import _retained_context

    need_id, _evidence_id, _job_id = _seed_job(sessions)
    marker = "\nOpaque source bytes (base64; not interpreted): "
    text = "Page 2: Exact retained sentence supports a cited fact." + marker + "QUJDREVGRw=="
    with sessions.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        observation = Observation(
            source_id=project.source_id,
            external_id="opaque-tail-fixture",
            title="RRC filing page 2",
            abstract=text,
            published_at=date(2026, 10, 2),
            url="https://example.invalid/rrc/opaque-tail",
            content_hash="b" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash="b" * 64,
            title=observation.title,
            abstract=text,
            url=observation.url,
            published_at=observation.published_at,
            extraction_location="PDF page 2",
        )
        session.add(evidence)
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation.id))
        evidence_id = evidence.id
    with sessions() as session:
        _need, _project, _source, retained = _retained_context(session, need_id)
        immutable = session.get(Evidence, evidence_id)
        row = next(item for item in retained if item["content_hash"] == "b" * 64)
    assert immutable.abstract == text
    assert row["abstract"] == text[: text.index(marker)]
    assert row["text_truncated"] is True
    assert row["retained_text_status"] == "partial_retained_excerpt"
    assert row["omitted_text_start"] == len(row["abstract"])
    assert row["omitted_text_end"] == len(text)


def _fake_call(**_kwargs):
    return {
        "model": "pinned-fixture-model",
        "provider_response_id": "fixture-response",
        "answers": {
            "answer": {
                "type": "choice",
                "choice": "RELEVANT",
                "confidence": 1.0,
                "probabilities": {"RELEVANT": 1.0, "IRRELEVANT": 0.0, "UNCERTAIN": 0.0},
            }
        },
    }


def _wire_worker(sessions, monkeypatch):
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs import worker

    # signal_adjudication imports SessionLocal inside its functions, so patch the
    # defining module instead of assigning an unused attribute on that module.
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(intelligence_jobs, "SessionLocal", sessions)
    monkeypatch.setattr(intelligence_jobs, "call_typesafe", _fake_call)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    return worker


def test_leased_worker_runs_retained_need_through_shared_ledger(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, evidence_id, job_id = _seed_job(sessions)

    worker = _wire_worker(sessions, monkeypatch)
    worker_id = "fixture-worker"
    monkeypatch.setattr(worker, "WORKER_ID", worker_id)
    assert worker.run_one({}, job_ids=[job_id]) is True

    with sessions() as session:
        history = intelligence_history(session, need_id)
        call = session.scalar(select(LogicalCall))
    assert len(history) == 1
    assert history[0]["status"] == "completed"
    assert history[0]["result"]["authority"] == "ADVISORY_ONLY"
    assert history[0]["evidence_ids"] == [str(evidence_id)]
    assert history[0]["logical_call_id"] == str(call.id)
    assert history[0]["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "actual_cost_usd": None,
        "estimated_cost_usd": None,
        "cost_basis": None,
    }
    assert call and call.status == "COMPLETED" and call.result_payload
    assert call.max_cost_usd == Decimal("0.020000")


def test_catalog_worker_blocks_without_total_input_bound_before_provider_call(
    sessions, monkeypatch
):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_typesafe_total_input_bound_verified", False)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-proof-missing-worker")
    provider_calls = []

    from gridlens.intelligence import intelligence_jobs

    monkeypatch.setattr(
        intelligence_jobs, "call_typesafe", lambda **_kwargs: provider_calls.append(True)
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        history = intelligence_history(session, need_id)
    assert provider_calls == []
    assert calls == []
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"


def test_catalog_worker_applies_per_call_cap_to_full_input_ceiling(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.01"))
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-full-ceiling-cap-worker")
    provider_calls = []

    from gridlens.intelligence import intelligence_jobs

    monkeypatch.setattr(
        intelligence_jobs, "call_typesafe", lambda **_kwargs: provider_calls.append(True)
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        history = intelligence_history(session, need_id)
    assert provider_calls == []
    assert calls == []
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "FINITE_BUDGET_REQUIRED"


def _deep_provider_response():
    nested = "leaf"
    for _ in range(1_500):
        nested = {"nested": nested}
    return {
        "model": "pinned-fixture-model",
        "provider_response_id": "fixture-recursive-response",
        "usage": {"input_tokens": 10, "output_tokens": 1},
        "nested": nested,
    }


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        (
            {
                "model": "unconfigured-alias",
                "provider_response_id": "fixture-model-mismatch",
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "answers": {"invalid": "semantic payload must not be parsed"},
                "api_key": "synthetic-secret-must-not-persist",
            },
            "MODEL_IDENTITY_MISMATCH",
        ),
        (
            {
                "provider_response_id": "fixture-model-missing",
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "answers": {"invalid": "semantic payload must not be parsed"},
            },
            "MODEL_IDENTITY_MISMATCH",
        ),
        (
            {
                "model": "pinned-fixture-model",
                "provider_response_id": "fixture-input-overage",
                "usage": {"input_tokens": 20_001, "output_tokens": 1},
                "answers": {"invalid": "semantic payload must not be parsed"},
            },
            "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED",
        ),
        (
            {
                "model": "pinned-fixture-model",
                "provider_response_id": "fixture-unrepresentable-input-overage",
                "usage": {"input_tokens": 2**63 - 1, "output_tokens": 1},
                "answers": {"invalid": "semantic payload must not be parsed"},
            },
            "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED",
        ),
        (
            {
                "model": "pinned-fixture-model",
                "provider_response_id": "fixture-oversized-response",
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "large_untrusted_output": "x" * 70_000,
            },
            "RESPONSE_TOO_LARGE",
        ),
        (
            {
                "model": "pinned-fixture-model",
                "provider_response_id": "fixture-oversized-tail-response",
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "items": [""] * 1000 + ["x" * 65_000],
            },
            "RESPONSE_TOO_LARGE",
        ),
        (_deep_provider_response(), "RESPONSE_TOO_LARGE"),
    ],
)
def test_catalog_quarantines_type_safe_identity_and_input_bound_breaches_before_parse(
    sessions, monkeypatch, response, expected_reason
):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-billing-quarantine-worker")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = []

    def fake_response(**_kwargs):
        provider_calls.append(True)
        return response

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", fake_response)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
        budget = session.scalar(
            select(LogicalCallBudget).where(
                LogicalCallBudget.scope == "global:global",
                LogicalCallBudget.period == "daily",
            )
        )
    assert provider_calls == [True]
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == f"BILLING_QUARANTINE:{expected_reason}"
    assert call.actual_cost_usd is None and call.finished_at is None
    quarantine = call.result_payload["billing_quarantine"]
    assert quarantine["response"].get("provider_response_id")
    assert quarantine["reason"] == expected_reason
    assert "synthetic-secret-must-not-persist" not in json.dumps(call.result_payload)
    if expected_reason == "MODEL_IDENTITY_MISMATCH":
        assert quarantine["response"].get("model") in {None, "unconfigured-alias"}
    elif expected_reason == "TOTAL_BILLABLE_INPUT_CEILING_EXCEEDED":
        assert quarantine["usage"]["input_tokens"] > 20_000
        if quarantine["exposure_status"] == "UNBOUNDED":
            assert quarantine["conservative_exposure_usd"] is None
        else:
            assert Decimal(quarantine["conservative_exposure_usd"]) > call.max_cost_usd
    else:
        assert quarantine["reason"] == "RESPONSE_TOO_LARGE"
        assert quarantine["response"]["omitted"] == "MAX_RESULT_BYTES"
    assert budget and budget.active_count == 1
    assert history[0]["status"] == "unknown" and history[0]["uncertain"] is True
    assert history[0]["result"]["billing_quarantine"] == expected_reason


def test_catalog_quarantines_openai_output_bound_breach_before_semantic_parse(
    sessions, monkeypatch
):
    for name, value in {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "intelligence_enabled_contracts": "TEMP_LOAD_MW",
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_openai_reasoning_model": "pinned-openai-fixture",
        "intelligence_openai_reasoning_priced_model_id": "pinned-openai-fixture",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": Decimal("1"),
        "intelligence_openai_reasoning_output_usd_per_million": Decimal("1"),
        "intelligence_openai_reasoning_max_output_tokens": 1,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))
    need_id, _evidence_id, job_id = _seed_job(
        sessions,
        task_type="GROUNDED_DOSSIER",
        question_id="TEMP_LOAD_MW",
        link_pursuit=True,
    )
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-openai-quarantine-worker")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = []

    def fake_response(**_kwargs):
        provider_calls.append(True)
        return {
            "model": "pinned-openai-fixture",
            "provider_response_id": "fixture-output-bound-breach",
            "input_tokens": 10,
            "output_tokens": 2,
            "output": {"invalid": "must not parse"},
        }

    monkeypatch.setattr(intelligence_jobs, "call_openai", fake_response)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert provider_calls == [True]
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == "BILLING_QUARANTINE:ENFORCED_OUTPUT_BOUND_EXCEEDED"
    assert call.actual_cost_usd is None and call.output_tokens == 2
    assert call.result_payload["billing_quarantine"]["response"]["output"] == {
        "invalid": "must not parse"
    }
    assert history[0]["status"] == "unknown" and history[0]["uncertain"] is True


@pytest.mark.parametrize(
    ("off_case", "changed_setting"),
    [
        ("master_off", ("intelligence_enabled", False)),
        ("provider_off", ("intelligence_typesafe_enabled", False)),
        ("zero_global_call_cap", ("intelligence_global_daily_calls", 0)),
    ],
)
def test_synthetic_key_present_off_zero_first_entry_has_no_ledger_or_budget_effect(
    sessions, monkeypatch, off_case, changed_setting
):
    _enable_bounded_typesafe(monkeypatch)
    # A fixture-only key is deliberately present, proving the guards independently
    # of missing credentials. No real provider is called.
    assert settings.typesafe_api_key is not None
    setting_name, value = changed_setting
    monkeypatch.setattr(settings, setting_name, value)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", f"fixture-{off_case}")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = []
    monkeypatch.setattr(
        intelligence_jobs, "call_typesafe", lambda **_kwargs: provider_calls.append(True)
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        budgets = list(session.scalars(select(LogicalCallBudget)))
        history = intelligence_history(session, need_id)
    assert provider_calls == []
    assert calls == [] and budgets == []
    assert history[0]["status"] == "blocked"
    assert history[0]["error"]


def test_legacy_typesafe_model_mismatch_quarantines_and_blocks_reuse(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    from gridlens.integrations import legacy_calls

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    state = {
        "title": "Fixture project",
        "abstract": "Fixture abstract",
        "url": "https://example.invalid",
        "published_at": "2026-10-01",
        "source_id": "fixture-source",
        "source_family": "permit",
        "publisher": "Fixture Publisher",
        "event_date": "",
        "event_date_label": "",
        "project_name": "Fixture project",
        "location": "Austin, TX",
        "asset_type": "facility",
        "lifecycle_state": "planned",
    }
    provider_calls = []

    def mismatched_result():
        provider_calls.append(True)
        return (
            {
                "model": "unconfigured-alias",
                "provider_response_id": "fixture-legacy-model-mismatch",
                "usage": {"input_tokens": 50, "output_tokens": 5},
                "answers": {"raw": "retained"},
            },
            50,
            5,
        )

    args = {
        "task_type": "SIGNAL_ADJUDICATION",
        "task_key": "fixture-legacy-model-mismatch",
        "payload": {"state": state},
        "source_id": None,
        "project_id": None,
        "job_id": None,
        "worker_id": None,
        "fence_token": 7,
    }
    with pytest.raises(legacy_calls.LegacyCallUnknown, match="BILLING_QUARANTINE"):
        legacy_calls.perform_legacy_call(**args, invoke=mismatched_result)
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert provider_calls == [True]
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.actual_cost_usd is None
    assert call.result_payload["billing_quarantine"]["response"]["provider_response_id"] == (
        "fixture-legacy-model-mismatch"
    )
    with pytest.raises(legacy_calls.LegacyCallBlocked, match="PROVIDER_BILLING_QUARANTINED"):
        legacy_calls.perform_legacy_call(**args, invoke=mismatched_result)
    assert provider_calls == [True]


def _legacy_signal_state():
    return {
        "title": "Fixture project",
        "abstract": "Fixture abstract",
        "url": "https://example.invalid",
        "published_at": "2026-10-01",
        "source_id": "fixture-source",
        "source_family": "permit",
        "publisher": "Fixture Publisher",
        "event_date": "",
        "event_date_label": "",
        "project_name": "Fixture project",
        "location": "Austin, TX",
        "asset_type": "facility",
        "lifecycle_state": "planned",
    }


@pytest.mark.parametrize("input_tokens, output_tokens", [("50", 5), (2**63, 5), (50, 2**63)])
def test_legacy_invalid_reported_usage_quarantines_without_ledger_overflow(
    sessions, monkeypatch, input_tokens, output_tokens
):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    from gridlens.integrations import legacy_calls

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    args = {
        "task_type": "SIGNAL_ADJUDICATION",
        "task_key": f"fixture-invalid-usage-{type(input_tokens).__name__}-{output_tokens}",
        "payload": {"state": _legacy_signal_state()},
        "source_id": None,
        "project_id": None,
        "job_id": None,
        "worker_id": None,
        "fence_token": 7,
    }

    def invalid_usage_result():
        return (
            {
                "model": "pinned-fixture-model",
                "provider_response_id": "fixture-legacy-invalid-usage",
                "answers": {"raw": "retained"},
            },
            input_tokens,
            output_tokens,
        )

    with pytest.raises(legacy_calls.LegacyCallUnknown, match="INVALID_REPORTED_USAGE"):
        legacy_calls.perform_legacy_call(**args, invoke=invalid_usage_result)
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.actual_cost_usd is None
    expected_input = input_tokens if type(input_tokens) is int and input_tokens < 2**63 else None
    expected_output = (
        output_tokens if type(output_tokens) is int and output_tokens < 2**63 else None
    )
    assert call.input_tokens == expected_input
    assert call.output_tokens == expected_output


@pytest.mark.parametrize("usage_field", [{}, {"usage": None}])
def test_legacy_valid_null_usage_can_complete(sessions, monkeypatch, usage_field):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    from gridlens.integrations import legacy_calls

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    response = {
        "model": "pinned-fixture-model",
        "answers": {"raw": "retained"},
        **usage_field,
    }
    result = legacy_calls.perform_legacy_call(
        task_type="SIGNAL_ADJUDICATION",
        task_key="fixture-null-usage",
        payload={"state": _legacy_signal_state()},
        source_id=None,
        project_id=None,
        job_id=None,
        worker_id=None,
        fence_token=7,
        invoke=lambda: (response, None, None),
    )
    assert result.input_tokens is None and result.output_tokens is None
    with sessions() as session:
        call = session.get(LogicalCall, result.logical_call_id)
    assert call and call.status == "COMPLETED"


@pytest.mark.parametrize("usage", ["invalid", [], 0, False])
def test_legacy_present_nondict_raw_usage_quarantines(sessions, monkeypatch, usage):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    from gridlens.integrations import legacy_calls

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    with pytest.raises(legacy_calls.LegacyCallUnknown, match="INVALID_REPORTED_USAGE"):
        legacy_calls.perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key=f"fixture-raw-usage-{type(usage).__name__}",
            payload={"state": _legacy_signal_state()},
            source_id=None,
            project_id=None,
            job_id=None,
            worker_id=None,
            fence_token=7,
            invoke=lambda: (
                {"model": "pinned-fixture-model", "usage": usage, "answers": {}},
                None,
                None,
            ),
        )
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == "BILLING_QUARANTINE:INVALID_REPORTED_USAGE"


def test_jev_wrapper_preserves_received_error_for_legacy_quarantine(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    provider_calls = []
    raw = {
        "id": "resp-jev-invalid",
        "model": "pinned-fixture-model",
        "usage": {"input_tokens": 17, "output_tokens": 2},
        "output": [],
    }

    def provider_error(**_kwargs):
        provider_calls.append(True)
        raise signal_adjudication.intelligence_provider.ProviderResponseError(
            "synthetic received semantic error",
            request_id="req-jev-invalid",
            response_received=True,
            raw_response=raw,
            reported_model=raw["model"],
            reported_usage=raw["usage"],
        )

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", provider_error)
    with pytest.raises(legacy_calls.LegacyCallUnknown, match="BILLING_QUARANTINE"):
        legacy_calls.perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key="fixture-jev-wrapper-error",
            payload={"state": _legacy_signal_state()},
            source_id=None,
            project_id=None,
            job_id=None,
            worker_id=None,
            fence_token=7,
            invoke=lambda: signal_adjudication._jev_call(
                _legacy_signal_state(), "fixture-only", model="pinned-fixture-model", max_attempts=1
            ),
        )
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
    assert provider_calls == [True]
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.result_payload["billing_quarantine"]["response"]["provider_request_id"] == (
        "req-jev-invalid"
    )


def test_catalog_worker_rechecks_exact_billing_proof_before_dispatch(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-proof-changed-worker")
    provider_calls = []

    from gridlens.intelligence import intelligence_jobs

    original_reserve = intelligence_jobs.reserve_call

    def reserve_then_change_proof(*args, **kwargs):
        result = original_reserve(*args, **kwargs)
        monkeypatch.setattr(
            settings,
            "intelligence_typesafe_billing_reference",
            "synthetic://fixture/changed-after-reservation",
        )
        return result

    monkeypatch.setattr(intelligence_jobs, "reserve_call", reserve_then_change_proof)
    monkeypatch.setattr(
        intelligence_jobs, "call_typesafe", lambda **_kwargs: provider_calls.append(True)
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        history = intelligence_history(session, need_id)
    assert provider_calls == []
    assert len(calls) == 1
    assert calls[0].status != "SENT_OUTCOME_UNKNOWN"
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "TYPESAFE_BILLING_POLICY_CHANGED"


@pytest.mark.parametrize(
    "failure_case",
    [
        None,
        "semantic_followon",
        "followon_input_overbound",
        "followon_output_overbound",
        "ocr_input_overbound",
        "ocr_output_overbound",
    ],
)
def test_leased_scanned_pdf_job_commits_capture_then_counts_and_keeps_transcript_private(
    sessions, monkeypatch, failure_case
):
    import base64
    import hashlib
    import io

    from pypdf import PdfWriter

    from gridlens.intelligence import scanned_pdf_ocr
    from gridlens.intelligence.scanned_pdf_ocr import enqueue_scanned_pdf_ocr
    from gridlens.jobs import worker

    source_id = "federal-register-eis"
    document_id = "2026-18765"
    source_url = "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf"
    pdf_buffer = io.BytesIO()
    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=612, height=792)
    pdf_writer.write(pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    need_id, project_id, observation_id, evidence_id = uuid4(), uuid4(), uuid4(), uuid4()
    semantic_hash = hashlib.sha256(b"Federal Register semantic record").hexdigest()

    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "intelligence_enabled_contracts": "OCR_EXTRACTION,OCR_GROUNDED_FOLLOWON",
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_ocr_enabled": True,
        "intelligence_ocr_vision_enabled": True,
        "intelligence_ocr_preflight_enabled": True,
        "intelligence_ocr_preflight_cost_bound_verified": True,
        "intelligence_ocr_preflight_cost_reference": "fixture-verified-count-bound",
        "intelligence_ocr_preflight_max_cost_usd": Decimal("0.01"),
        "intelligence_ocr_retention_source_ids": source_id,
        "intelligence_ocr_retention_reference": "fixture-retention-policy",
        "intelligence_ocr_model": "pinned-ocr-fixture-model",
        "intelligence_ocr_priced_model_id": "pinned-ocr-fixture-model",
        "intelligence_ocr_pricing_verified": True,
        "intelligence_ocr_input_usd_per_million": Decimal("1"),
        "intelligence_ocr_output_usd_per_million": Decimal("1"),
        "intelligence_ocr_detail": "low",
        "intelligence_ocr_max_output_tokens": 100,
        "intelligence_ocr_max_call_usd": Decimal("0.1"),
        "intelligence_max_call_usd": Decimal("0.1"),
        "intelligence_max_active_calls": 2,
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("1"))

    with sessions.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Federal Register",
                endpoint="https://www.govinfo.gov/content/pkg/FR",
                family="federal-register-eis",
                geography="United States",
                industries=["power"],
                retrieval_method="GovInfo Federal Register API",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        session.add(
            Project(
                id=project_id,
                identity_key="fr-ocr-fixture",
                name="Federal Register OCR fixture",
                source_id=source_id,
                external_id=document_id,
            )
        )
        session.flush()
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key="fr-ocr-fixture",
                rationale="Fixture-only OCR job.",
                supply="Unknown",
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id=document_id,
                title="Federal Register semantic record",
                abstract="The semantic record is distinct from the companion PDF bytes.",
                url="https://www.federalregister.gov/documents/2026/09/14/2026-18765/example",
                content_hash=semantic_hash,
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash=pdf_hash,
                title="Original Federal Register PDF",
                url=source_url,
                provenance={"preserved": "existing provenance"},
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))
        job = enqueue_scanned_pdf_ocr(session, need_id=need_id, evidence_id=evidence_id)
        job_id = job.id

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(scanned_pdf_ocr, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-ocr-worker")

    def fake_capture(url, expected_hash):
        assert url == source_url
        assert expected_hash == pdf_hash
        return {
            "document_id": document_id,
            "content_hash": pdf_hash,
            "page_count": 1,
            "scanned_pages": [1],
            "data_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "source_url": source_url,
        }

    count_errors = []
    fail_followon_response = []

    def fake_count(**kwargs):
        try:
            with sessions() as session:
                evidence = session.get(Evidence, evidence_id)
                assert (
                    evidence
                    and evidence.provenance["govinfo_ocr_capture_v1"]["content_hash"] == pdf_hash
                )
                preflight = session.scalar(
                    select(LogicalCall)
                    .where(
                        LogicalCall.task_type.in_(
                            {"OCR_INPUT_PREFLIGHT", "OCR_FOLLOWON_INPUT_PREFLIGHT"}
                        ),
                        LogicalCall.status == "SENT_OUTCOME_UNKNOWN",
                    )
                    .limit(1)
                )
                assert preflight is not None
                assert preflight.max_cost_usd <= Decimal("0.01")
                assert preflight.result_payload is None
        except Exception as exc:
            count_errors.append(f"{type(exc).__name__}: {exc}")
            raise
        return 321

    def fake_response(**kwargs):
        request = kwargs["request"]
        assert request["model"] == "pinned-ocr-fixture-model"
        assert request["store"] is False and request["tools"] == []
        if isinstance(request["input"], str):
            assert "ocr-grounded-followon-v1" in request["input"]
            if failure_case == "semantic_followon":
                raw = {
                    "status": "incomplete",
                    "model": "pinned-ocr-fixture-model",
                    "usage": {"input_tokens": 26, "output_tokens": 4},
                    "output": [],
                }
                raise scanned_pdf_ocr.ProviderResponseError(
                    "synthetic incomplete semantic response",
                    request_id="fixture-followon-semantic-error",
                    conclusive=True,
                    status_code=200,
                    response_received=True,
                    raw_response=raw,
                    reported_model=raw["model"],
                    reported_usage=raw["usage"],
                )
            return {
                "model": "pinned-ocr-fixture-model",
                "provider_response_id": "fixture-grounded-response-id",
                "input_tokens": 322 if failure_case == "followon_input_overbound" else 26,
                "output_tokens": 101 if failure_case == "followon_output_overbound" else 4,
                "output": {
                    "candidates": [],
                    "hypotheses": [],
                    "contradictions": [],
                    "unresolved_questions": [],
                    "candidate_orgs": [],
                    "proposed_queries": [],
                    "suggested_pursuit": None,
                },
            }
        return {
            "model": "pinned-ocr-fixture-model",
            "provider_response_id": "fixture-response-id",
            "input_tokens": 322 if failure_case == "ocr_input_overbound" else 18,
            "output_tokens": 101 if failure_case == "ocr_output_overbound" else 7,
            "output": {"pages": [{"page": 1, "text": "Fixture scanned page text."}]},
        }

    monkeypatch.setattr(scanned_pdf_ocr, "capture_govinfo_pdf", fake_capture)
    monkeypatch.setattr(scanned_pdf_ocr, "call_openai_input_token_count", fake_count)
    monkeypatch.setattr(scanned_pdf_ocr, "call_openai_request", fake_response)
    assert worker.run_one({}, job_ids=[job_id]) is True
    assert not count_errors, count_errors

    if failure_case and failure_case.startswith("ocr_"):
        expected_reason = (
            "REPORTED_INPUT_EXCEEDS_PREFLIGHT_COUNT"
            if failure_case == "ocr_input_overbound"
            else "ENFORCED_OUTPUT_BOUND_EXCEEDED"
        )
        with sessions() as session:
            failed_call = session.scalar(
                select(LogicalCall).where(
                    LogicalCall.task_type == "OCR_EXTRACTION",
                    LogicalCall.status == "SENT_OUTCOME_UNKNOWN",
                )
            )
        assert failed_call and failed_call.actual_cost_usd is None
        assert failed_call.blocked_reason == f"BILLING_QUARANTINE:{expected_reason}"
        return

    with sessions.begin() as session:
        followon_job = scanned_pdf_ocr.enqueue_ocr_grounded_followon(
            session,
            need_id=need_id,
            evidence_id=evidence_id,
            question_id="TEMP_LOAD_MW",
        )
        followon_job_id = followon_job.id
    if failure_case == "semantic_followon":
        fail_followon_response.append(True)
    assert worker.run_one({}, job_ids=[followon_job_id]) is True
    assert not count_errors, count_errors

    if failure_case:
        with sessions() as session:
            failed_followon = session.scalar(
                select(LogicalCall).where(
                    LogicalCall.task_type == "OCR_GROUNDED_FOLLOWON",
                    LogicalCall.status == "SENT_OUTCOME_UNKNOWN",
                )
            )
            failed_job = session.get(Job, followon_job_id)
        assert failed_followon and failed_followon.actual_cost_usd is None
        assert failed_followon.blocked_reason.startswith("BILLING_QUARANTINE:")
        reason = failed_followon.result_payload["billing_quarantine"]["reason"]
        if failure_case == "semantic_followon":
            assert failed_followon.result_payload["billing_quarantine"]["response"]["status"] == (
                "incomplete"
            )
        elif failure_case == "followon_input_overbound":
            assert reason == "REPORTED_INPUT_EXCEEDS_PREFLIGHT_COUNT"
        else:
            assert reason == "ENFORCED_OUTPUT_BOUND_EXCEEDED"
        assert failed_job and failed_job.status == "succeeded"
        checkpoint = json.loads(failed_job.checkpoint)
        assert checkpoint["status"] == "unknown"
        assert checkpoint["error"] == "OCR_FOLLOWON_OUTCOME_UNKNOWN"
        assert failed_job.lease_owner is None and failed_job.lease_until is None
        return

    from gridlens.api.intelligence import _history_view

    with sessions() as session:
        logical_call_selects = []

        def count_logical_call_select(_conn, _cursor, statement, _parameters, _context, _many):
            normalized = statement.lstrip().casefold()
            if normalized.startswith("select") and "from logical_calls" in normalized:
                logical_call_selects.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", count_logical_call_select)
        try:
            history = _history_view(session, need_id, 10)
        finally:
            event.remove(engine, "before_cursor_execute", count_logical_call_select)
        assert len(logical_call_selects) == 1
        ocr_history = next(item for item in history if item["task_type"] == "OCR_EXTRACTION")
        followon_history = next(
            item for item in history if item["task_type"] == "OCR_GROUNDED_FOLLOWON"
        )
        assert ocr_history["result_status"] == "OCR_UNVERIFIED"
        assert ocr_history["result"]["pages"] == [{"page": 1, "text": "Fixture scanned page text."}]
        assert "data_base64" not in str(ocr_history)
        assert followon_history["result_status"] == "OCR_UNVERIFIED"
        assert followon_history["result"]["authority"] == "ADVISORY_ONLY"
        assert followon_history["result"]["canonical_promotion"] == "PROHIBITED"
        assert "data_base64" not in str(followon_history)
        evidence = session.get(Evidence, evidence_id)
        job = session.get(Job, job_id)
        calls = session.scalars(
            select(LogicalCall).where(LogicalCall.job_id == job_id).order_by(LogicalCall.created_at)
        ).all()
        assert evidence and job
        capture = evidence.provenance["govinfo_ocr_capture_v1"]
        assert capture["content_hash"] == pdf_hash
        assert base64.b64decode(capture["data_base64"]) == pdf_bytes
        assert evidence.provenance["preserved"] == "existing provenance"
        assert evidence.provenance["ocr"]["original_document_hash"] == pdf_hash
        assert job.status == "succeeded"
        assert job.checkpoint and json.loads(job.checkpoint)["result_status"] == "OCR_UNVERIFIED"
        assert len(calls) == 2
        count_call, response_call = calls
        assert count_call.task_type == "OCR_INPUT_PREFLIGHT"
        assert count_call.status == "COMPLETED"
        assert count_call.result_payload["counted_input_tokens"] == 321
        assert count_call.result_payload["counted_input_tokens_are_billable_usage"] is False
        assert count_call.result_payload["actual_cost_usd"] is None
        assert response_call.task_type == "OCR_EXTRACTION"
        assert response_call.status == "COMPLETED"
        assert response_call.actual_cost_usd is None
        assert response_call.result_payload["status"] == "OCR_UNVERIFIED"
        assert response_call.result_payload["original_document_hash"] == pdf_hash
        assert response_call.result_payload["pages"] == [
            {"page": 1, "text": "Fixture scanned page text."}
        ]
        assert "data_base64" not in response_call.result_payload
        followon_call = session.scalar(
            select(LogicalCall).where(LogicalCall.task_type == "OCR_GROUNDED_FOLLOWON")
        )
        followon_job = session.get(Job, followon_job_id)
        assert followon_job and followon_job.status == "succeeded"
        followon_checkpoint = json.loads(followon_job.checkpoint or "{}")
        assert followon_checkpoint.get("result_status") == "OCR_UNVERIFIED", (
            followon_checkpoint.get("status"),
            followon_checkpoint.get("error"),
            list(followon_checkpoint),
        )
        assert followon_call and followon_call.status == "COMPLETED"
        assert followon_call.result_payload["status"] == "OCR_UNVERIFIED"
        assert followon_call.result_payload["authority"] == "ADVISORY_ONLY"
        assert followon_call.result_payload["canonical_promotion"] == "PROHIBITED"
        assert followon_call.result_payload["independent_source_check"] == "REQUIRED"
        assert followon_call.result_payload["candidates"] == []


def test_typesafe_dispatch_preserves_bounded_need_and_identity_context(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    captured = {}

    def inspect_payload(**kwargs):
        captured.update(kwargs["payload"])
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", inspect_payload)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-context-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    assert captured["state"]["task_type"] == "SOURCE_RELEVANCE_V1"
    assert captured["state"]["schema_version"]
    assert captured["state"]["need"]["project_identity_key"] == "fixture-project"
    assert "state_version_digest" in captured["state"]["need"]
    assert captured["state"]["evidence"][0]["content_hash"] == "a" * 64


def test_match_context_keeps_exact_nearby_candidate_ids_and_negative_decisions(sessions):
    from gridlens.intelligence.intelligence_jobs import _request_payload, _retained_context

    need_id, evidence_id, _job_id = _seed_job(sessions, task_type="MATCH_ADVISORY_V1")
    candidate_ids = [uuid4(), uuid4()]
    with sessions.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        evidence = session.get(Evidence, evidence_id)
        assert need and project and evidence
        for index, candidate_id in enumerate(candidate_ids):
            session.add(
                Project(
                    id=candidate_id,
                    identity_key=f"candidate-{index}",
                    name="Northstar Data Center",
                    location=f"{100 + index} Test Road, Austin, TX",
                    source_id=project.source_id,
                    external_id=f"candidate-{index}",
                    identity_facts={"site_address": f"{100 + index} Test Road"},
                )
            )
        session.flush()
        session.add_all(
            [
                ProjectMatchDecision(
                    observation_id=evidence.observation_id,
                    candidate_project_id=candidate_ids[0],
                    evidence_id=evidence.id,
                    decision="REJECTED",
                    reason="Different parcel despite similar project name.",
                    matched_facts=["project_name"],
                ),
                ProjectMatchDecision(
                    observation_id=evidence.observation_id,
                    candidate_project_id=candidate_ids[1],
                    evidence_id=evidence.id,
                    decision="CANDIDATE",
                    reason="Same metro, distinct street address; exact site unresolved.",
                    matched_facts=["city"],
                ),
            ]
        )
        session.flush()
        need, project, source, retained = _retained_context(session, need_id)
        payload = _request_payload(
            session, "MATCH_ADVISORY_V1", None, need, project, source, retained
        )
    expected = {str(value) for value in candidate_ids}
    assert set(payload["questions"]) == expected
    assert payload["need"]["state_version_digest"]
    facts = {
        item["candidate_id"]: item for item in payload["task_context"]["deterministic_candidates"]
    }
    assert set(facts) == expected
    assert facts[str(candidate_ids[0])]["deterministic_decision"] == "REJECTED"
    assert "Different parcel" in facts[str(candidate_ids[0])]["deterministic_reason"]
    assert facts[str(candidate_ids[1])]["deterministic_decision"] == "CANDIDATE"


def test_match_without_existing_candidate_is_not_applicable_and_never_calls_provider(sessions):
    from gridlens.persistence.models import LogicalCall

    _need_id, _evidence_id, job_id = _seed_job(sessions, task_type="MATCH_ADVISORY_V1")
    with sessions() as session:
        job = session.get(Job, job_id)
        calls = session.query(LogicalCall).count()
        assert job and job.status == "succeeded"
        checkpoint = json.loads(job.checkpoint or "{}")
    assert calls == 0
    assert checkpoint["status"] == "not_applicable"
    assert checkpoint["result"]["disposition"] == "UNRESOLVED_NO_ELIGIBLE_CANDIDATE"


def test_match_candidate_change_stales_context_before_provider_dispatch(sessions, monkeypatch):
    from gridlens.intelligence import intelligence_jobs
    from gridlens.jobs.queue import lease_one

    _enable_bounded_typesafe(monkeypatch)
    _wire_worker(sessions, monkeypatch)
    need_id, evidence_id, _initial_job_id = _seed_job(sessions, task_type="MATCH_ADVISORY_V1")
    candidate_id = uuid4()
    with sessions.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        evidence = session.get(Evidence, evidence_id)
        assert need and project and evidence
        session.add(
            Project(
                id=candidate_id,
                identity_key="stale-candidate",
                name="Northstar Data Center",
                location="200 Test Road, Austin, TX",
                source_id=project.source_id,
                external_id="stale-candidate",
                identity_facts={"site_address": "200 Test Road"},
            )
        )
        session.flush()
        session.add(
            ProjectMatchDecision(
                observation_id=evidence.observation_id,
                candidate_project_id=candidate_id,
                evidence_id=evidence.id,
                decision="CANDIDATE",
                reason="Same metro; verify exact site.",
                matched_facts=["city"],
            )
        )
        session.flush()
        job = enqueue_intelligence(
            session, need_id=need_id, task_type="MATCH_ADVISORY_V1", origin="test"
        )
        job_id = job.id
    monkeypatch.setattr(
        intelligence_jobs,
        "call_typesafe",
        lambda **_: pytest.fail("stale candidate context must not dispatch"),
    )
    with sessions.begin() as session:
        row = session.execute(
            select(
                Job.kind,
                Job.status,
                Job.available_at,
                Job.lease_until,
                Job.target_id,
                Job.attempts,
                Job.fence,
            ).where(Job.id == job_id)
        ).one()
        app_now = datetime.now(UTC)
        database_now = session.scalar(select(func.clock_timestamp()))
        queued = session.get(Job, job_id)
        assert queued is not None
        queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased, fence = lease_one(session, "match-stale-worker", job_ids=[job_id])
        assert leased is not None, (
            "Expected explicitly-due advisory job to be leaseable; "
            f"row={row!r}, app_now={app_now!r}, database_now={database_now!r}, "
            f"lease_available_at={queued.available_at!r}"
        )
        assert leased.id == job_id
    with sessions.begin() as session:
        candidate = session.get(Project, candidate_id)
        assert candidate
        candidate.identity_facts = {"site_address": "201 Test Road"}
    result = intelligence_jobs.process_intelligence_job(job_id, "match-stale-worker", fence)
    assert result["status"] == "stale"


def test_authorized_research_priority_changes_only_fresh_queued_job_order(sessions, monkeypatch):
    from gridlens.intelligence.intelligence_jobs import _apply_bounded_routing_effect

    _enable_bounded_typesafe(monkeypatch)
    for name, value in {
        "intelligence_mode": "bounded_routing",
        "intelligence_enabled_contracts": "RESEARCH_PRIORITY_V1,LLM_ROUTE_V1",
        "intelligence_routing_policy_id": "evaluated-policy-v1",
        "intelligence_routing_policy_evaluated": True,
        "intelligence_bounded_routing_authorized": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    need_id, _evidence_id, original_job_id = _seed_job(sessions, task_type="RESEARCH_PRIORITY_V1")
    with sessions.begin() as session:
        original = session.get(Job, original_job_id)
        assert original
        queued = original
        evaluation = {
            "task_type": "RESEARCH_PRIORITY_V1",
            "job_id": str(uuid4()),
            "logical_call_id": str(uuid4()),
            "request_digest": "d" * 64,
            "routing_approval": {
                "policy_id": "evaluated-policy-v1",
                "evaluated": True,
                "authorized": True,
                "reference_type": "configured_policy_id",
            },
        }
        effect = _apply_bounded_routing_effect(
            session,
            checkpoint=evaluation,
            result={"answer": {"choice": "5"}},
            need_id=need_id,
        )
        queued_id = queued.id
    with sessions() as session:
        queued = session.get(Job, queued_id)
        applied = json.loads(queued.checkpoint or "{}")["routing_priority"]
    assert effect and effect["status"] == "QUEUED_WORK_RANKED"
    assert effect["job_ids"] == [str(queued_id)]
    assert applied == {
        "rank": 1,
        "route": "RESEARCH_PRIORITY",
        "policy_id": "evaluated-policy-v1",
        "evaluated": True,
        "authorized": True,
        "evaluation_job_id": evaluation["job_id"],
        "evaluation_call_id": evaluation["logical_call_id"],
        "request_digest": "d" * 64,
    }


@pytest.mark.parametrize(
    ("route", "expected_task", "expected_rank"),
    [
        ("FAST_EXTRACT", "GROUNDED_EXTRACTION", 1),
        ("DEEP_RESEARCH", "GROUNDED_DOSSIER", 2),
    ],
)
def test_authorized_llm_route_enqueues_bounded_grounding_under_same_caps(
    sessions, monkeypatch, route, expected_task, expected_rank
):
    from gridlens.intelligence.intelligence_jobs import _apply_bounded_routing_effect

    _enable_bounded_typesafe(monkeypatch)
    grounded_values = {
        "intelligence_mode": "bounded_routing",
        "intelligence_enabled_contracts": "LLM_ROUTE_V1,TEMP_LOAD_MW",
        "intelligence_routing_policy_id": "evaluated-policy-v1",
        "intelligence_routing_policy_evaluated": True,
        "intelligence_bounded_routing_authorized": True,
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_openai_fast_model": "fast-fixture-model",
        "intelligence_openai_fast_priced_model_id": "fast-fixture-model",
        "intelligence_openai_fast_pricing_verified": True,
        "intelligence_openai_fast_input_usd_per_million": Decimal("1"),
        "intelligence_openai_fast_output_usd_per_million": Decimal("0"),
        "intelligence_openai_fast_max_output_tokens": 600,
        "intelligence_openai_reasoning_model": "reasoning-fixture-model",
        "intelligence_openai_reasoning_priced_model_id": "reasoning-fixture-model",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": Decimal("1"),
        "intelligence_openai_reasoning_output_usd_per_million": Decimal("0"),
        "intelligence_openai_reasoning_max_output_tokens": 1200,
    }
    for name, value in grounded_values.items():
        monkeypatch.setattr(settings, name, value)
    need_id, _evidence_id, _ = _seed_job(sessions, task_type="SOURCE_RELEVANCE_V1")
    with sessions.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need
        project = session.get(Project, need.project_id)
        assert project
        pursuit = Pursuit(
            identity_key=f"route-pursuit-{uuid4()}",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={},
            research_status="not_researched",
        )
        session.add(pursuit)
        session.flush()
        session.add(
            PursuitResearchQuestion(
                pursuit_id=pursuit.id,
                project_id=project.id,
                need_id=need_id,
                parent_id=None,
                category="load",
                question="What exact temporary load remains unresolved?",
                status="QUEUED",
                attempt_count=0,
                query_fingerprint="a" * 64,
                evidence_fingerprint="b" * 64,
                context={},
                budget={},
                receipt={},
            )
        )
        session.flush()
        route_job = enqueue_intelligence(
            session, need_id=need_id, task_type="LLM_ROUTE_V1", origin="test"
        )
        checkpoint = json.loads(route_job.checkpoint or "{}")
        checkpoint.update(
            job_id=str(route_job.id),
            logical_call_id=str(uuid4()),
            routing_approval={
                "policy_id": "evaluated-policy-v1",
                "evaluated": True,
                "authorized": True,
                "reference_type": "configured_policy_id",
            },
        )
        effect = _apply_bounded_routing_effect(
            session,
            checkpoint=checkpoint,
            result={"answer": {"choice": route}},
            need_id=need_id,
        )
        follow_on_id = effect["job_id"] if effect else None
    assert effect and effect["status"] == "ROUTED_JOB_ENQUEUED"
    assert effect["task_type"] == expected_task
    assert effect["question_id"] == "TEMP_LOAD_MW"
    with sessions() as session:
        follow_on = session.get(Job, follow_on_id)
        follow_on_checkpoint = json.loads(follow_on.checkpoint or "{}")
    assert follow_on.status == "queued"
    assert follow_on_checkpoint["routing_priority"]["rank"] == expected_rank
    assert follow_on_checkpoint["routing_priority"]["policy_id"] == "evaluated-policy-v1"


@pytest.mark.parametrize("mid_call_change", [None, "source_permission", "accepted_fact"])
def test_leased_worker_rechecks_grounded_context_after_provider_response(
    sessions, monkeypatch, mid_call_change
):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "intelligence_enabled_contracts": "TEMP_LOAD_MW",
        "openai_api_key": SecretStr("fixture-only"),
        "intelligence_openai_reasoning_model": "pinned-reasoning-fixture",
        "intelligence_openai_reasoning_priced_model_id": "pinned-reasoning-fixture",
        "intelligence_openai_reasoning_pricing_verified": True,
        "intelligence_openai_reasoning_input_usd_per_million": Decimal("1"),
        "intelligence_openai_reasoning_output_usd_per_million": Decimal("0"),
        "intelligence_openai_reasoning_max_output_tokens": 1200,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.1"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("10"))
    need_id, evidence_id, job_id = _seed_job(
        sessions,
        task_type="GROUNDED_DOSSIER",
        question_id="TEMP_LOAD_MW",
        link_pursuit=True,
    )
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    output = {
        "candidates": [
            {
                "field": "temporary_load_mw",
                "value": "12",
                "unit": "MW",
                "original_value": "12",
                "original_unit": "MW",
                "precision": 0,
                "date_precision": None,
                "evidence_id": str(evidence_id),
                "evidence_hash": "a" * 64,
                "quote": "Temporary load of 12 MW is requested in the utility service application.",
                "section": "abstract",
                "page": None,
                "span_start": len("Fixture project seeks utility coordination\n"),
                "span_end": len("Fixture project seeks utility coordination\n")
                + len("Temporary load of 12 MW is requested in the utility service application."),
                "publisher": "Fixture Utility",
                "published_date": "2026-10-01",
                "speaker": None,
                "speaker_organization": None,
                "speaker_role": None,
                "support": "direct",
                "status": "candidate",
            }
        ],
        "hypotheses": ["Ask the utility to confirm temporary load."],
        "contradictions": [],
        "unresolved_questions": ["What exact MW amount is requested?"],
        "candidate_orgs": [],
        "proposed_queries": ["utility temporary service load MW"],
        "suggested_pursuit": None,
    }

    def fake_openai(**_kwargs):
        if mid_call_change == "source_permission":
            with sessions.begin() as session:
                source = session.get(Source, "intelligence-fixture-source")
                source.enabled = False
        elif mid_call_change == "accepted_fact":
            from datetime import UTC, datetime, timedelta

            from gridlens.persistence.models import CallFactDecision, CallFactVersion

            now = datetime.now(UTC)
            fact_id = uuid4()
            with sessions.begin() as session:
                session.add(
                    CallFactVersion(
                        id=fact_id,
                        need_id=need_id,
                        project_id=session.scalar(
                            select(PowerNeed.project_id).where(PowerNeed.id == need_id)
                        ),
                        pursuit_id=None,
                        predecessor_id=None,
                        client_id=uuid4(),
                        activity_key="fixture-construction",
                        facility_scope="fixture facility",
                        fact_type="buyer",
                        value={"organization": "Fixture Buyer", "role": "project owner"},
                        reporter_name="Fixture Owner",
                        reporter_organization="Fixture Buyer",
                        reporter_role="owner",
                        confirmation_channel="call",
                        source_reference=None,
                        source_date=None,
                        confirmed_at=now,
                        effective_from=now - timedelta(minutes=1),
                        effective_until=None,
                        content_hash="9" * 64,
                        recorded_by="test",
                    )
                )
                session.flush()
                session.add(
                    CallFactDecision(
                        need_id=need_id,
                        fact_version_id=fact_id,
                        version=1,
                        client_id=uuid4(),
                        decision="accepted",
                        expected_version=0,
                        reason="fixture context change",
                        content_hash="8" * 64,
                        actor="fixture owner",
                    )
                )
        return {
            "model": "pinned-reasoning-fixture",
            "provider_response_id": "fixture-grounded-response",
            "latency_ms": 19,
            "input_tokens": 300,
            "output_tokens": 80,
            "output": output,
        }

    monkeypatch.setattr(intelligence_jobs, "call_openai", fake_openai)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-openai-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        history = intelligence_history(session, need_id)
        call = session.scalar(select(LogicalCall))
        question = session.scalar(select(PursuitResearchQuestion))
    original = next(item for item in history if item["job_id"] == str(job_id))
    expected_status = "stale" if mid_call_change else "completed"
    assert original["status"] == expected_status
    assert original["evidence_ids"] == [str(evidence_id)]
    assert original["result"]["schema_version"] == "grounded-candidates-v2"
    assert original["result"]["candidates"][0]["value"] == "12"
    assert original["result"]["unresolved_questions"] == output["unresolved_questions"]
    assert original["result"]["actual_model"] == "pinned-reasoning-fixture"
    assert original["result"]["latency_ms"] == 19
    assert original["usage"]["actual_cost_usd"] is None
    assert original["usage"]["estimated_cost_usd"] == "0.0003"
    assert original["usage"]["cost_basis"] == "derived_from_verified_usage_and_pinned_rates"
    assert call and call.status == "COMPLETED" and call.input_tokens == 300
    assert question and question.category == "load" and question.status == "UNRESOLVED"
    assert question.receipt["intelligence_job"]["logical_call_id"] == str(call.id)
    if mid_call_change:
        assert original["result_status"] == "stale_context"
        assert original["error"] == "INPUT_CHANGED_DURING_PROVIDER_CALL"
        if mid_call_change == "accepted_fact":
            assert original["reassessment_job_id"]
    else:
        assert history[0]["status"] == "completed"


def test_worker_recovers_not_sent_reservation_after_lease_turnover(sessions, monkeypatch):
    from datetime import UTC, datetime, timedelta

    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")

    from gridlens.intelligence import intelligence_jobs

    real_dispatch = intelligence_jobs.mark_dispatched

    def crash_before_dispatch(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(intelligence_jobs, "mark_dispatched", crash_before_dispatch)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])
    monkeypatch.setattr(intelligence_jobs, "mark_dispatched", real_dispatch)
    with sessions.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-b")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        row = session.scalar(select(LogicalCall))
        history = intelligence_history(session, _need_id)
    assert row and row.status == "COMPLETED"
    assert history[0]["status"] == "completed"


def test_zeroed_budget_after_reserve_cancels_before_provider_dispatch(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def provider_call(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", provider_call)
    original_policy = intelligence_jobs._dispatch_policy

    def zero_budget_before_dispatch(*args, **kwargs):
        monkeypatch.setattr(settings, "intelligence_global_daily_calls", 0)
        return original_policy(*args, **kwargs)

    monkeypatch.setattr(intelligence_jobs, "_dispatch_policy", zero_budget_before_dispatch)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert call and call.status == "CANCELLED"
    assert provider_calls == 0
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "GLOBAL_DAILY_CAP_ZERO"


@pytest.mark.parametrize("crash_point", ["after_dispatch", "after_provider_response"])
def test_worker_never_retries_ambiguous_dispatch_after_lease_turnover(
    sessions, monkeypatch, crash_point
):
    from datetime import UTC, datetime, timedelta

    _enable_bounded_typesafe(monkeypatch)
    _need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def provider_crash(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if crash_point == "after_dispatch":
            raise KeyboardInterrupt
        return _fake_call()

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", provider_crash)
    if crash_point == "after_provider_response":

        def crash_before_ledger_commit(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(intelligence_jobs, "complete_call", crash_before_ledger_commit)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])

    with sessions.begin() as session:
        job = session.get(Job, job_id)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-b")
    assert worker.run_one({}, job_ids=[job_id]) is True

    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, _need_id)
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.result_payload is None
    assert provider_calls == 1
    assert history[0]["status"] == "blocked"
    assert history[0]["error"] == "IDENTITY_LEASE_MISMATCH"


def test_same_job_reentry_does_not_repeat_sent_unknown_call(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-worker-a")
    from gridlens.intelligence import intelligence_jobs

    provider_calls = 0

    def ambiguous_call(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(intelligence_jobs, "call_typesafe", ambiguous_call)
    with pytest.raises(KeyboardInterrupt):
        worker.run_one({}, job_ids=[job_id])
    result = intelligence_jobs.process_intelligence_job(job_id, "fixture-worker-a", 1)
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert result["status"] == "blocked"
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert provider_calls == 1
    assert history[0]["status"] == "blocked"


def test_conclusive_provider_schema_failure_is_terminal_not_unknown(sessions, monkeypatch):
    _enable_bounded_typesafe(monkeypatch)
    need_id, _evidence_id, job_id = _seed_job(sessions)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import intelligence_jobs

    monkeypatch.setattr(
        intelligence_jobs,
        "call_typesafe",
        lambda **_kwargs: {
            "model": "pinned-fixture-model",
            "provider_response_id": "fixture-invalid-response",
            "answers": {"answer": {"type": "choice", "choice": "NOT_ALLOWED"}},
        },
    )
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-invalid-worker")
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        history = intelligence_history(session, need_id)
    assert call and call.status == "FAILED"
    assert call.result_payload == {"provider_response_ref": "response:fixture-invalid-response"}
    assert history[0]["status"] == "failed"
    assert history[0]["uncertain"] is False


def _estimated_signal_enabled(monkeypatch, observation_id):
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_enabled_contracts": "SIGNAL_ADJUDICATION",
        "jev_enabled": True,
        "intelligence_typesafe_enabled": True,
        "typesafe_api_key": SecretStr("fixture-only"),
        "intelligence_typesafe_model": "jev-1.13.0",
        "intelligence_typesafe_priced_model_id": "jev-1.13.0",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": Decimal("0.042"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
        "intelligence_typesafe_billing_mode": "input_only",
        "intelligence_typesafe_billing_model_id": "jev-1.13.0",
        "intelligence_typesafe_billing_contract_id": "systemone-v1",
        "intelligence_typesafe_billing_policy_id": "typesafe-signal-estimate-v1",
        "intelligence_typesafe_billing_reference": "https://docs.typesafe.ai/models#jev-1.13.0",
        "intelligence_typesafe_billing_verified": True,
        "intelligence_typesafe_total_input_bound_verified": False,
        "intelligence_typesafe_estimated_reservation_usd": Decimal("0.01"),
        "intelligence_typesafe_estimate_observation_ids": str(observation_id),
        "intelligence_max_active_calls": 1,
        "intelligence_max_call_usd": Decimal("0.01"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 10)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("50"))


def _seed_signal_adjudication_job(sessions):
    source_id = "estimated-jev-public-source"
    observation_id, evidence_id = uuid4(), uuid4()
    evidence_hash = "f" * 64
    with sessions.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Fixture City",
                endpoint="https://example.invalid",
                family="permit",
                geography="Austin",
                industries=["power"],
                retrieval_method="fixture",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id="estimate-test-1",
                title="Austin facility expansion permit",
                abstract="A new facility expansion is proposed.",
                published_at=date(2026, 10, 1),
                url="https://example.invalid/permit/1",
                content_hash=evidence_hash,
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash=evidence_hash,
                title="Austin facility expansion permit",
                abstract="A new facility expansion is proposed.",
                url="https://example.invalid/permit/1",
                published_at=date(2026, 10, 1),
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            kind="signal_adjudication",
            target_id=observation_id,
            checkpoint=json.dumps(
                {
                    "evidence_id": str(evidence_id),
                    "content_hash": evidence_hash,
                    "policy_version": "signal-display-v2",
                }
            ),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    return source_id, observation_id, evidence_id, evidence_hash, job_id


def test_estimated_jev_worker_persists_usage_audit_and_reuses_completed_call(sessions, monkeypatch):
    (
        source_id,
        observation_id,
        evidence_id,
        evidence_hash,
        job_id,
    ) = _seed_signal_adjudication_job(sessions)
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-jev-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    sent = []
    answers = {
        name: {"type": "noul", "noul": value}
        for name, value in {
            "physical_project_event": 0.9,
            "meaningful_new_activity": 0.9,
            "commercial_relevance": 0.7,
            "temporary_power_relevance": 0.6,
            "routine_maintenance": 0.1,
            "transient_event": 0.0,
        }.items()
    }

    def provider(**kwargs):
        sent.append(kwargs)
        return {
            "model": "jev-1.13.0",
            "answers": answers,
            "usage": {"input_tokens": 551, "output_tokens": None},
        }

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", provider)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        decision = session.scalar(
            select(SignalDecision).where(SignalDecision.observation_id == observation_id)
        )
        job = session.get(Job, job_id)
    assert len(sent) == 1
    assert call and call.status == "COMPLETED"
    assert call.max_cost_usd == Decimal("0.010000") and call.actual_cost_usd is None
    assert call.result_payload["usage_estimated_usd"] == str(
        Decimal(551) * Decimal("0.042") / Decimal(1_000_000)
    )
    assert call.result_payload["usage_estimate_policy"]["hard_bound_verified"] is False
    assert decision and decision.source == "jev" and decision.content_hash == evidence_hash
    assert job and json.loads(job.checkpoint)["logical_call_id"] == str(call.id)
    from gridlens.intelligence.intelligence_jobs import _billing_policy_identity

    assert json.loads(job.checkpoint)["logical_call_policy"] == _billing_policy_identity(
        "typesafe", "jev-1.13.0", "SIGNAL_ADJUDICATION"
    )
    assert sent[0]["model"] == "jev-1.13.0"
    assert sent[0]["payload"]["state"]["source_id"] == source_id
    from gridlens.intelligence.signal_adjudication import jev_request_payload

    assert {"model": sent[0]["model"], **sent[0]["payload"]} == jev_request_payload(
        sent[0]["payload"]["state"], model="jev-1.13.0"
    )

    with sessions.begin() as session:
        duplicate = Job(
            source_id=source_id,
            kind="signal_adjudication",
            target_id=observation_id,
            # This tests completed-call reuse, not database/application clock
            # alignment. Make the fixture unambiguously eligible for leasing.
            available_at=datetime.now(UTC) - timedelta(seconds=1),
            checkpoint=json.dumps(
                {
                    "evidence_id": str(evidence_id),
                    "content_hash": evidence_hash,
                    "policy_version": "signal-display-v2",
                }
            ),
        )
        session.add(duplicate)
        session.flush()
        duplicate_id = duplicate.id
    assert worker.run_one({}, job_ids=[duplicate_id]) is True
    assert len(sent) == 1


def test_estimated_jev_final_usage_envelope_overflow_quarantines_and_cannot_replay(
    sessions, monkeypatch
):
    from gridlens.integrations.logical_calls import MAX_RESULT_BYTES

    source_id, observation_id, _evidence_id, evidence_hash, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-envelope-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    answers = {
        name: {"type": "noul", "noul": 0.5}
        for name in (
            "physical_project_event",
            "meaningful_new_activity",
            "commercial_relevance",
            "temporary_power_relevance",
            "routine_maintenance",
            "transient_event",
        )
    }
    response = {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 551, "output_tokens": None},
        "padding": "",
    }
    estimate = str(Decimal(551) * Decimal("0.042") / Decimal(1_000_000))
    estimate_policy = {
        "id": "typesafe-signal-estimate-v1",
        "cost_basis": "ESTIMATE",
        "input_rate_usd_per_million": "0.042",
        "output_rate_usd_per_million": "0",
        "hard_bound_verified": False,
    }

    def encoded_size(value):
        return len(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        )

    response["padding"] = "x" * (MAX_RESULT_BYTES - encoded_size(response) - 64)
    assert encoded_size(response) == MAX_RESULT_BYTES - 64
    assert (
        encoded_size(
            {
                **response,
                "usage_estimated_usd": estimate,
                "usage_estimate_policy": estimate_policy,
            }
        )
        > MAX_RESULT_BYTES
    )

    provider_calls = []

    def provider(**kwargs):
        provider_calls.append(kwargs)
        return response

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", provider)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        decision = session.scalar(
            select(SignalDecision).where(SignalDecision.observation_id == observation_id)
        )
        job = session.get(Job, job_id)
        budgets = list(session.scalars(select(LogicalCallBudget)))
    assert len(provider_calls) == 1
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == "BILLING_QUARANTINE:RESPONSE_TOO_LARGE"
    assert call.result_payload["billing_quarantine"]["reason"] == "RESPONSE_TOO_LARGE"
    assert call.actual_cost_usd is None and call.estimated_cost_usd == Decimal("0.010000")
    assert budgets and all(budget.active_count == 1 for budget in budgets)
    assert decision and decision.source == "jev_error"
    assert job and job.status == "succeeded"
    assert json.loads(job.checkpoint)["logical_call_policy"]["hard_bound_verified"] == "false"

    with pytest.raises(
        legacy_calls.LegacyCallUnknown, match="CHECKPOINT_LOGICAL_CALL_NOT_REPLAYABLE"
    ):
        legacy_calls.perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key=f"{observation_id}:{evidence_hash}:signal-display-v2",
            payload={},
            source_id=source_id,
            project_id=None,
            job_id=job_id,
            worker_id="fixture-estimated-envelope-worker",
            fence_token=1,
            invoke=lambda: pytest.fail("an uncertain response must not be replayed"),
            existing_call_id=call.id,
        )
    assert len(provider_calls) == 1


def test_estimated_jev_unselected_backlog_finishes_without_reservation_or_transport(
    sessions, monkeypatch
):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, uuid4())
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(database, "SessionLocal", sessions)
    calls = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        job = session.get(Job, job_id)
        logical_calls = list(session.scalars(select(LogicalCall)))
        decisions = list(
            session.scalars(
                select(SignalDecision).where(SignalDecision.observation_id == observation_id)
            )
        )
    assert calls == [] and logical_calls == [] and decisions == []
    assert job and job.status == "succeeded" and "OBSERVATION_NOT_SELECTED" in (job.error or "")


@pytest.mark.parametrize("reservation", [Decimal("0.001"), Decimal("0.02")])
def test_estimated_jev_unreviewed_reservation_fails_before_ledger_or_transport(
    sessions, monkeypatch, reservation
):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    monkeypatch.setattr(settings, "intelligence_typesafe_estimated_reservation_usd", reservation)
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(database, "SessionLocal", sessions)
    provider_calls = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        job = session.get(Job, job_id)
        calls = list(session.scalars(select(LogicalCall)))
        budgets = list(session.scalars(select(LogicalCallBudget)))
    assert provider_calls == [] and calls == [] and budgets == []
    assert job and job.status == "succeeded"
    assert "TYPESAFE_ESTIMATE_RESERVATION_INVALID" in (job.error or "")


def test_estimated_jev_reservation_change_before_dispatch_cancels_without_transport(
    sessions, monkeypatch
):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.05"))
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-policy-change-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    original_reserve = legacy_calls.reserve_call

    def reserve_then_change_policy(*args, **kwargs):
        result = original_reserve(*args, **kwargs)
        monkeypatch.setattr(
            settings, "intelligence_typesafe_estimated_reservation_usd", Decimal("0.02")
        )
        return result

    monkeypatch.setattr(legacy_calls, "reserve_call", reserve_then_change_policy)
    provider_calls = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        budgets = list(session.scalars(select(LogicalCallBudget)))
    assert provider_calls == []
    assert call and call.status == "CANCELLED"
    assert budgets and all(budget.active_count == 0 for budget in budgets)


@pytest.mark.parametrize("blocker", ["max_active", "shared_daily_budget"])
def test_estimated_jev_uses_existing_shared_active_and_budget_caps(sessions, monkeypatch, blocker):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    if blocker == "max_active":
        monkeypatch.setattr(settings, "intelligence_max_active_calls", 0)
    else:
        monkeypatch.setattr(settings, "intelligence_global_daily_usd", Decimal("0.005"))
    worker = _wire_worker(sessions, monkeypatch)
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(database, "SessionLocal", sessions)
    provider_calls = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        budgets = list(session.scalars(select(LogicalCallBudget)))
    assert provider_calls == []
    assert all(call.status != "SENT_OUTCOME_UNKNOWN" for call in calls)
    assert all(budget.active_count == 0 for budget in budgets)


@pytest.mark.parametrize("change", ["evidence", "source_disabled"])
def test_estimated_jev_rechecks_evidence_and_source_before_dispatch(sessions, monkeypatch, change):
    source_id, observation_id, evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-current-check-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    original_reserve = legacy_calls.reserve_call

    def reserve_then_change_public_support(*args, **kwargs):
        reservation = original_reserve(*args, **kwargs)
        with sessions.begin() as session:
            if change == "evidence":
                session.get(Evidence, evidence_id).content_hash = "b" * 64
            else:
                session.get(Source, source_id).enabled = False
        return reservation

    monkeypatch.setattr(legacy_calls, "reserve_call", reserve_then_change_public_support)
    provider_calls = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        calls = list(session.scalars(select(LogicalCall)))
        budgets = list(session.scalars(select(LogicalCallBudget)))
        decisions = list(
            session.scalars(
                select(SignalDecision).where(SignalDecision.observation_id == observation_id)
            )
        )
    assert provider_calls == [] and len(calls) == 1
    assert calls[0].status == "CANCELLED"
    assert budgets and all(budget.active_count == 0 for budget in budgets)
    assert decisions == []


@pytest.mark.parametrize(
    ("response_model", "explicit_actual_model", "input_tokens", "expected_reason"),
    [
        ("jev-alias", None, 551, "MODEL_IDENTITY_MISMATCH"),
        ("wrong-alias", "jev-1.13.0", 551, "MODEL_IDENTITY_MISMATCH"),
        ("jev-1.13.0", None, True, "INVALID_REPORTED_USAGE"),
        ("jev-1.13.0", None, 64_001, "ESTIMATED_CONTEXT_ASSUMPTION_EXCEEDED"),
    ],
)
def test_estimated_jev_response_guards_quarantine_through_shared_ledger(
    sessions, monkeypatch, response_model, explicit_actual_model, input_tokens, expected_reason
):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-guard-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    answers = {
        name: {"type": "noul", "noul": 0.5}
        for name in (
            "physical_project_event",
            "meaningful_new_activity",
            "commercial_relevance",
            "temporary_power_relevance",
            "routine_maintenance",
            "transient_event",
        )
    }
    provider_calls = []

    def provider(**kwargs):
        provider_calls.append(kwargs)
        usage = {"input_tokens": input_tokens, "output_tokens": 12}
        response = {"model": response_model, "answers": answers, "usage": usage}
        if explicit_actual_model is not None:
            response["actual_model"] = explicit_actual_model
        return response

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", provider)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        decisions = list(
            session.scalars(
                select(SignalDecision).where(SignalDecision.observation_id == observation_id)
            )
        )
        job = session.get(Job, job_id)
    assert len(provider_calls) == 1
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == f"BILLING_QUARANTINE:{expected_reason}"
    assert call.actual_cost_usd is None and call.estimated_cost_usd == Decimal("0.010000")
    assert decisions and decisions[-1].source == "jev_error"
    assert job and json.loads(job.checkpoint)["logical_call_policy"]["policy_id"] == (
        "typesafe-signal-estimate-v1"
    )


def test_estimated_jev_received_error_uses_snapshot_threshold_and_quarantine(sessions, monkeypatch):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-provider-error-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    raw = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 64_001, "output_tokens": None},
    }

    def provider(**_kwargs):
        raise signal_adjudication.intelligence_provider.ProviderResponseError(
            "synthetic provider semantic response",
            response_received=True,
            raw_response=raw,
            reported_model=raw["model"],
            reported_usage=raw["usage"],
        )

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", provider)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        job = session.get(Job, job_id)
    assert call and call.status == "SENT_OUTCOME_UNKNOWN"
    assert call.blocked_reason == "BILLING_QUARANTINE:ESTIMATED_CONTEXT_ASSUMPTION_EXCEEDED"
    assert call.actual_cost_usd is None
    assert job and json.loads(job.checkpoint)["logical_call_policy"]["policy_id"] == (
        "typesafe-signal-estimate-v1"
    )


def test_estimated_jev_received_conclusive_failure_retains_captured_policy(sessions, monkeypatch):
    _source_id, observation_id, _evidence_id, _digest, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-estimated-rejected-worker")
    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    provider_calls = []
    raw = {"model": "jev-1.13.0", "usage": {"input_tokens": 551, "output_tokens": None}}

    def reject(**_kwargs):
        provider_calls.append(True)
        raise signal_adjudication.intelligence_provider.ProviderResponseError(
            "synthetic conclusive rejection",
            request_id="fixture-rejected-response",
            conclusive=True,
            status_code=400,
            response_received=True,
            raw_response=raw,
            reported_model=raw["model"],
            reported_usage=raw["usage"],
        )

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", reject)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        call = session.scalar(select(LogicalCall))
        job = session.get(Job, job_id)
    assert provider_calls == [True]
    assert call and call.status == "FAILED"
    assert job and job.status == "succeeded"
    assert json.loads(job.checkpoint)["logical_call_policy"]["policy_id"] == (
        "typesafe-signal-estimate-v1"
    )


def test_estimated_jev_uncertain_checkpoint_is_not_replayed_after_policy_change(
    sessions, monkeypatch
):
    source_id, observation_id, _evidence_id, evidence_hash, job_id = _seed_signal_adjudication_job(
        sessions
    )
    _estimated_signal_enabled(monkeypatch, observation_id)
    worker = _wire_worker(sessions, monkeypatch)
    worker_id = "fixture-estimated-uncertain-worker"
    monkeypatch.setattr(worker, "WORKER_ID", worker_id)
    import httpx

    from gridlens.integrations import legacy_calls
    from gridlens.intelligence import signal_adjudication

    monkeypatch.setattr(legacy_calls, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    provider_calls = []

    def disconnect(**_kwargs):
        provider_calls.append(True)
        raise httpx.ConnectError("synthetic disconnected outcome")

    monkeypatch.setattr(signal_adjudication.intelligence_provider, "call_typesafe", disconnect)
    assert worker.run_one({}, job_ids=[job_id]) is True
    with sessions() as session:
        job = session.get(Job, job_id)
        call = session.scalar(select(LogicalCall))
        budget_count = session.scalar(select(func.count()).select_from(LogicalCallBudget))
    assert job and call and call.status == "SENT_OUTCOME_UNKNOWN"
    checkpoint = json.loads(job.checkpoint)
    assert checkpoint["logical_call_id"] == str(call.id)
    snapshot = checkpoint["logical_call_policy"]
    assert snapshot["reservation_usd"] == "0.01"
    monkeypatch.setattr(
        settings, "intelligence_typesafe_estimated_reservation_usd", Decimal("0.02")
    )
    with pytest.raises(
        legacy_calls.LegacyCallUnknown, match="CHECKPOINT_LOGICAL_CALL_NOT_REPLAYABLE"
    ):
        legacy_calls.perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key=f"{observation_id}:{evidence_hash}:signal-display-v2",
            payload={"observation_id": str(observation_id)},
            source_id=source_id,
            project_id=None,
            job_id=job_id,
            worker_id=worker_id,
            fence_token=1,
            invoke=lambda: provider_calls.append(True),
            existing_call_id=call.id,
        )
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LogicalCall)) == 1
        assert session.scalar(select(func.count()).select_from(LogicalCallBudget)) == budget_count
    assert provider_calls == [True]
