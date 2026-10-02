import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.integrations.typesafe_evidence_judge import SCHEMA_VERSION
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


def test_shadow_missing_identity_key_does_not_turn_exact_match_check_unknown_to_exclusion(
    shadow_db, monkeypatch
):
    project_id = seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    with shadow_db.begin() as session:
        project = session.get(Project, project_id)
        project.external_id = "permit-0"
    with shadow_db() as session:
        judge = FakeJudge()
        result = run_shadow(session, limit=1, judge=judge)
        assert result["attempted"] == 1
        assert judge.calls == 1


def test_concurrent_shadow_workers_reserve_identical_input_once(shadow_db, monkeypatch):
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 20)
    with shadow_db() as session:
        evidence_id = session.scalar(select(Evidence.id))

    def run_once():
        with shadow_db() as session:
            return run_shadow(
                session,
                limit=1,
                judge=FakeJudge(),
                evidence_ids=[str(evidence_id)],
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_once(), range(2)))
    assert sum(result["attempted"] for result in results) == 1
    with shadow_db() as session:
        assert session.scalar(select(func.count()).select_from(EvidenceJudgeRun)) == 1


def test_shadow_skips_reservation_when_daily_lock_is_held(shadow_db, monkeypatch):
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 20)
    locked, release = Event(), Event()

    def hold_reservation():
        with shadow_db() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(647809130122)"))
            locked.set()
            assert release.wait(3)

    holder = ThreadPoolExecutor(max_workers=1)
    hold_future = holder.submit(hold_reservation)
    try:
        assert locked.wait(2)
        judge = FakeJudge()

        def run_once():
            with shadow_db() as session:
                return run_shadow(session, limit=1, judge=judge)

        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(run_once).result(1)
        assert result["attempted"] == 0
        assert judge.calls == 0
        with shadow_db() as session:
            assert session.scalar(select(EvidenceJudgeRun.id)) is None
    finally:
        release.set()
        hold_future.result(3)
        holder.shutdown(wait=True)


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


def test_shadow_rotates_through_more_than_two_hundred_candidates(shadow_db, monkeypatch):
    seed_accepted(shadow_db, count=225)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 250)
    judge = FakeJudge()
    with shadow_db() as session:
        for _ in range(11):
            result = run_shadow(session, limit=20, judge=judge)
            assert result["attempted"] == 20
        runs = session.scalars(select(EvidenceJudgeRun)).all()
        assert len(runs) == 220
        attempted_ids = {run.evidence_id for run in runs}
        all_ids = set(session.scalars(select(Evidence.id)).all())
        assert len(attempted_ids & all_ids) == 220
        assert judge.calls == 220


def test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate(shadow_db, monkeypatch):
    project_id = seed_accepted(shadow_db, count=1205)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 1300)
    with shadow_db.begin() as session:
        evidence_rows = session.scalars(
            select(Evidence).join(Observation).order_by(Evidence.observed_at, Evidence.id)
        ).all()
        unseen = evidence_rows[1100]
        bounded_state = {
            "project_id": str(project_id),
            "state": {
                key: {"status": "UNKNOWN", "value": None}
                for key in (
                    "identity",
                    "site",
                    "lifecycle",
                    "activity",
                    "power_need",
                    "utility_service",
                )
            },
            "organizations_and_roles": [],
            "candidate_matches": [],
        }
        monkeypatch.setattr(
            "gridlens.intelligence.evidence_shadow.project_state",
            lambda *_args: bounded_state,
        )
        base = datetime(2026, 10, 1, tzinfo=UTC)
        runs = []
        for index, evidence in enumerate(evidence_rows):
            if evidence.id == unseen.id:
                continue
            deterministic = {
                "relevant": "YES",
                "same_project": "UNKNOWN",
                "material_change": "NO",
            }
            evidence_context = {
                "id": str(evidence.id),
                "hash": evidence.content_hash,
                "title": evidence.title[:300],
                "abstract": evidence.abstract[:1200] if evidence.abstract else None,
                "url": evidence.url[:500],
                "published_at": evidence.published_at,
                "retrieved_at": evidence.observed_at,
                "extraction_location": evidence.extraction_location[:150],
            }
            request_context = {
                "project": bounded_state,
                "evidence": evidence_context,
                "candidates": [],
                "deterministic": deterministic,
                "schema": SCHEMA_VERSION,
                "model": "jev-latest",
            }
            input_key = hashlib.sha256(
                json.dumps(request_context, sort_keys=True, default=str).encode()
            ).hexdigest()
            runs.append(
                EvidenceJudgeRun(
                    project_id=project_id,
                    evidence_id=evidence.id,
                    candidate_project_id=None,
                    input_key=input_key,
                    schema_version=SCHEMA_VERSION,
                    model="test-model",
                    status="invalid",
                    deterministic=deterministic,
                    result=None,
                    started_at=base + timedelta(seconds=index),
                    finished_at=base + timedelta(seconds=index),
                    latency_ms=1,
                )
            )
        session.add_all(runs)
    with shadow_db() as session:
        judge = FakeJudge()
        result = run_shadow(session, limit=1, judge=judge)
        assert result["attempted"] == 1
        attempted = session.scalar(
            select(EvidenceJudgeRun)
            .where(EvidenceJudgeRun.status == "valid")
            .order_by(EvidenceJudgeRun.started_at.desc())
        )
        attempted_index = next(
            (
                index
                for index, evidence in enumerate(evidence_rows)
                if evidence.id == attempted.evidence_id
            ),
            None,
        )
        assert attempted is not None and attempted.evidence_id == unseen.id, {
            "attempted_index": attempted_index,
            "unseen_index": 1100,
            "cursor_index": 1204,
        }
        assert judge.calls == 1
