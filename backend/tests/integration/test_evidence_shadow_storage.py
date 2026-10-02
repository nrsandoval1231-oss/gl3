from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.evidence_judge import Judgment
from gridlens.intelligence.evidence_shadow import run_shadow
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    EvidenceJudgeRun,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def shadow_db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database.endswith("_test") and target != application
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="shadow-test",
                publisher="Synthetic fixture",
                endpoint="https://example.test/shadow",
                family="permits",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_accepted(factory, count=1):
    project_id = uuid4()
    with factory.begin() as session:
        project = Project(
            id=project_id,
            source_id="shadow-test",
            external_id="ambiguous-project",
            name="Ambiguous Data Center",
            location="Austin, TX",
            identity_key="shadow-test-ambiguous-project",
            identity_facts={},
        )
        need = PowerNeed(
            project_id=project_id,
            activity_key="construction",
            tier="Signal",
            rationale="test row",
            admission_basis={},
            supply="Unknown",
            active=True,
        )
        session.add(project)
        session.flush()
        session.add(need)
        session.flush()
        for index in range(count):
            observation = Observation(
                source_id="shadow-test",
                external_id=f"permit-{index}",
                title=f"Permit {index}",
                abstract="Phased construction activity; no power size stated.",
                published_at=date(2026, 10, 1),
                url=f"https://example.test/{index}",
                content_hash=f"hash-{index}",
            )
            session.add(observation)
            session.flush()
            evidence = Evidence(
                observation_id=observation.id,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                content_hash=observation.content_hash,
                published_at=observation.published_at,
                observed_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
            session.add_all(
                [
                    evidence,
                    Interpretation(
                        observation_id=observation.id,
                        content_hash=observation.content_hash,
                        status="accepted",
                        assessment={
                            "decision": "accepted",
                            "evidence_hash": observation.content_hash,
                        },
                    ),
                    NeedObservation(need_id=need.id, observation_id=observation.id),
                ]
            )
    return project_id


class FakeJudge:
    timeout = 4

    def __init__(self, outcome="valid"):
        self.outcome = outcome
        self.calls = 0

    def judge(self, state, evidence, candidates):
        self.calls += 1
        if self.outcome == "timeout":
            import httpx

            raise httpx.TimeoutException("fixture timeout")
        if self.outcome == "invalid":
            from gridlens.intelligence.evidence_judge import InvalidJudgment

            raise InvalidJudgment("fixture invalid")
        return (
            Judgment(
                relevant="YES",
                same_project="UNKNOWN",
                event_type="construction",
                material_change="UNKNOWN",
                power_relevance="MEDIUM",
                temporary_power_hint="UNKNOWN",
                needs_deep_enrichment="YES",
            ),
            {"model": "test-model", "latency_ms": 5, "input_tokens": 10, "output_tokens": 2},
        )


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("valid", "valid"), ("timeout", "timeout"), ("invalid", "invalid")],
)
def test_shadow_attempt_persists_and_replay_never_repeats_or_changes_authority(
    shadow_db, monkeypatch, outcome, expected_status
):
    project_id = seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    judge = FakeJudge(outcome)
    with shadow_db() as session:
        before = (
            session.scalar(select(Project).where(Project.id == project_id)).identity_key,
            session.scalar(select(PowerNeed).where(PowerNeed.project_id == project_id)).tier,
            session.scalar(
                select(Evidence).join(Observation).where(Observation.source_id == "shadow-test")
            ).content_hash,
        )
        first = run_shadow(session, limit=1, judge=judge)
        assert first["attempted"] == 1
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == expected_status
        assert run.latency_ms is not None
        if expected_status == "valid":
            assert "research_recommended" in run.result["advisory"]
        after = (
            session.scalar(select(Project).where(Project.id == project_id)).identity_key,
            session.scalar(select(PowerNeed).where(PowerNeed.project_id == project_id)).tier,
            session.scalar(
                select(Evidence).join(Observation).where(Observation.source_id == "shadow-test")
            ).content_hash,
        )
        assert before == after
        second = run_shadow(session, limit=1, judge=judge)
        assert second["attempted"] == 0
        assert judge.calls == 1


def test_shadow_missing_key_disabled_and_daily_limit_are_fail_closed(shadow_db, monkeypatch):
    project_id = seed_accepted(shadow_db, count=2)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    with shadow_db() as session:
        assert run_shadow(session, limit=1)["reason"] == "missing_key"
        assert session.scalar(select(EvidenceJudgeRun)) is None
        monkeypatch.setattr(settings, "jev_enabled", False)
        assert run_shadow(session, limit=1)["status"] == "disabled"
        monkeypatch.setattr(settings, "jev_enabled", True)
        monkeypatch.setattr(settings, "jev_shadow_daily_limit", 1)
        judge = FakeJudge()
        result = run_shadow(session, limit=2, judge=judge)
        assert result["attempted"] == 1
        assert session.scalar(select(EvidenceJudgeRun.id)) is not None
        assert judge.calls == 1
        assert (
            session.scalar(select(PowerNeed).where(PowerNeed.project_id == project_id)).tier
            == "Signal"
        )
