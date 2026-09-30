from datetime import UTC, date, datetime
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.signal_adjudication import adjudicate, adjudicate_current_signals
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    SignalDecision,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
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
    with factory.begin() as session:
        session.add(
            Source(
                id="adjudication-test",
                publisher="Synthetic test source",
                endpoint="https://example.test/feed",
                family="news",
                geography="US",
                industries=["energy"],
                retrieval_method="publisher-rss",
                cadence_hours=24,
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _record(session, title="Project notice", abstract="Short ambiguous report.", published=None):
    observation = Observation(
        source_id="adjudication-test",
        external_id="record-1",
        title=title,
        abstract=abstract,
        published_at=published,
        url="https://example.test/record-1",
        content_hash="material-hash",
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash="source-evidence-hash",
        title=title,
        abstract=abstract,
        url=observation.url,
        published_at=published,
    )
    session.add(evidence)
    session.flush()
    return observation, evidence


def _dimensions(**overrides):
    values = {
        "physical_project_event": 0.95,
        "meaningful_new_activity": 0.9,
        "commercial_relevance": 0.9,
        "temporary_power_relevance": 0.9,
        "routine_maintenance": 0.05,
        "transient_event": 0.05,
    }
    values.update(overrides)
    return {
        "model": "jev-1.13.0",
        "answers": {name: {"type": "noul", "noul": value} for name, value in values.items()},
    }


def test_explicit_construction_override_does_not_call_jev(db):
    with db.begin() as session:
        observation, evidence = _record(
            session,
            "Data center construction begins",
            "A named data center project has started physical construction.",
            date(2026, 9, 1),
        )

        def forbidden(*args):
            raise AssertionError("Jev must not run for deterministic override")

        decision = adjudicate(session, observation, evidence, caller=forbidden)
        assert decision.decision == "SHOW"
        assert decision.source == "deterministic"


def test_ambiguous_decision_retries_missing_key_once_and_is_idempotent(db):
    calls = []
    with db.begin() as session:
        observation, evidence = _record(session)
        initial = adjudicate(session, observation, evidence)
        assert initial.decision == "REVIEW"

        def caller(state, key):
            calls.append((state, key))
            return _dimensions()

        resolved = adjudicate(session, observation, evidence, api_key="unit-key", caller=caller)
        assert resolved.decision == "SHOW"
        assert resolved.source == "jev"
        assert resolved.model_version == "jev-1.13.0"
        assert resolved.dimensions["temporary_power_relevance"] == 0.9
        assert (
            adjudicate(session, observation, evidence, api_key="unit-key", caller=caller).id
            == resolved.id
        )
        assert len(calls) == 1


def test_evidence_and_policy_version_create_distinct_retained_decisions(db):
    calls = []
    with db.begin() as session:
        observation, evidence = _record(session)

        def caller(state, key):
            calls.append(key)
            return _dimensions()

        first = adjudicate(session, observation, evidence, api_key="unit-key", caller=caller)
        changed = Evidence(
            observation_id=observation.id,
            content_hash="changed-source-hash",
            title=evidence.title,
            abstract="Changed evidence.",
            url=evidence.url,
        )
        session.add(changed)
        session.flush()
        second = adjudicate(session, observation, changed, api_key="unit-key", caller=caller)
        upgraded = adjudicate(
            session,
            observation,
            changed,
            api_key="unit-key",
            caller=caller,
            policy_version="signal-display-v2",
        )
        assert first.id != second.id != upgraded.id
        assert session.query(SignalDecision).count() == 3
        assert len(calls) == 3


def test_untrusted_jev_model_or_probability_stays_review(db):
    with db.begin() as session:
        observation, evidence = _record(session)
        wrong_model = adjudicate(
            session,
            observation,
            evidence,
            api_key="unit-key",
            caller=lambda _state, _key: {**_dimensions(), "model": "other-model"},
        )
        assert wrong_model.decision == "REVIEW"
        assert wrong_model.source == "jev_error"

        changed = Evidence(
            observation_id=observation.id,
            content_hash="new-source-hash",
            title=evidence.title,
            abstract=evidence.abstract,
            url=evidence.url,
        )
        session.add(changed)
        session.flush()
        invalid = _dimensions()
        invalid["answers"]["physical_project_event"]["noul"] = True
        wrong_probability = adjudicate(
            session,
            observation,
            changed,
            api_key="unit-key",
            caller=lambda _state, _key: invalid,
        )
        assert wrong_probability.decision == "REVIEW"
        assert wrong_probability.source == "jev_error"

        malformed = Evidence(
            observation_id=observation.id,
            content_hash="malformed-shape-hash",
            title=evidence.title,
            abstract=evidence.abstract,
            url=evidence.url,
        )
        session.add(malformed)
        session.flush()
        wrong_shape = adjudicate(
            session,
            observation,
            malformed,
            api_key="unit-key",
            caller=lambda _state, _key: [],
        )
        assert wrong_shape.decision == "REVIEW"
        assert wrong_shape.source == "jev_error"


def test_jev_outage_keeps_ambiguous_evidence_in_review(db):
    with db.begin() as session:
        observation, evidence = _record(session)

        def unavailable(_state, _key):
            raise RuntimeError("provider unavailable")

        decision = adjudicate(
            session, observation, evidence, api_key="unit-key", caller=unavailable
        )
        assert decision.decision == "REVIEW"
        assert decision.source == "jev_error"
        assert decision.dimensions == {"status": "malformed_or_unavailable"}


def test_backfill_uses_source_evidence_hash_not_material_digest(db):
    with db.begin() as session:
        observation, evidence = _record(session)
        session.add(
            Interpretation(
                observation_id=observation.id,
                content_hash="different-material-digest",
                evaluator_version="test",
                assessment={"tier": "Signal", "evidence_hash": evidence.content_hash},
                status="accepted",
            )
        )
        project = Project(
            identity_key="backfill-project",
            name="Backfill project",
            location="Austin, TX",
            source_id=observation.source_id,
            external_id=observation.external_id,
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic supported Signal",
        )
        session.add(need)
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        session.flush()
        counts = adjudicate_current_signals(session, limit=20)
        assert counts["processed"] == 1
        assert counts["review"] == 1


def test_adjudication_api_does_not_accept_caller_policy_version(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    calls = []

    def backfill(_session, *, limit):
        calls.append(limit)
        return {"processed": 0, "show": 0, "review": 0, "hold": 0}

    monkeypatch.setattr(api, "adjudicate_current_signals", backfill)
    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300)
    )
    response = client.post(
        "/api/signals/decisions/adjudicate?limit=1&policy_version=untrusted-repeat"
    )
    assert response.status_code == 200
    assert calls == [1]
    parameters = api.app.openapi()["paths"]["/api/signals/decisions/adjudicate"]["post"][
        "parameters"
    ]
    assert {parameter["name"] for parameter in parameters} == {"limit"}
