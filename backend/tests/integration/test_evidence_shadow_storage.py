import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from types import SimpleNamespace
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
    EvidenceJudgeScanCheckpoint,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def shadow_db(monkeypatch):
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 20)
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


def seed_accepted(factory, count=1, identity_suffix=""):
    project_id = uuid4()
    with factory.begin() as session:
        project = Project(
            id=project_id,
            source_id="shadow-test",
            external_id=f"ambiguous-project{identity_suffix}",
            name="Ambiguous Data Center",
            location="Austin, TX",
            identity_key=f"shadow-test-ambiguous-project{identity_suffix}",
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
                external_id=f"permit-{identity_suffix}-{index}",
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


def test_shadow_setup_error_releases_default_scan_lease(shadow_db, monkeypatch):
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    with monkeypatch.context() as setup_error:
        setup_error.setattr(
            "gridlens.intelligence.evidence_shadow._checkpoint",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("fixture setup error")),
        )
        with shadow_db() as session, pytest.raises(RuntimeError, match="fixture setup error"):
            run_shadow(session, limit=1, judge=FakeJudge())
    engine = shadow_db.kw["bind"]
    with engine.connect() as fresh_connection:
        assert fresh_connection.scalar(text("SELECT pg_try_advisory_lock(647809130123)"))
        fresh_connection.execute(text("SELECT pg_advisory_unlock(647809130123)"))
    with shadow_db() as session:
        assert run_shadow(session, limit=1, judge=FakeJudge())["attempted"] == 1


def test_zero_work_default_scan_commits_checkpoint_before_releasing_lease(shadow_db, monkeypatch):
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    first_judge, second_judge = FakeJudge(), FakeJudge()
    with shadow_db() as first_session:
        assert run_shadow(first_session, limit=1, judge=first_judge)["attempted"] == 0
        # Keep this caller Session open.  Before the fix its uncommitted
        # checkpoint INSERT could block a new scanner on the singleton PK.
        with shadow_db() as second_session:
            assert run_shadow(second_session, limit=1, judge=second_judge)["attempted"] == 0
    assert first_judge.calls == second_judge.calls == 0
    with shadow_db() as session:
        assert session.scalar(select(func.count()).select_from(EvidenceJudgeRun)) == 0


def test_shadow_acquisition_error_closes_new_connection(shadow_db, monkeypatch):
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    engine = shadow_db.kw["bind"]
    baseline = engine.pool.checkedout()
    real_connect = engine.connect
    closed = Event()

    class FailingConnection:
        def __init__(self):
            self.inner = real_connect()

        def scalar(self, *_args, **_kwargs):
            raise RuntimeError("fixture acquisition error")

        def close(self):
            self.inner.close()
            closed.set()

    with monkeypatch.context() as acquisition_error:
        acquisition_error.setattr(engine, "connect", FailingConnection)
        with shadow_db() as session, pytest.raises(RuntimeError, match="fixture acquisition error"):
            run_shadow(session, limit=1, judge=FakeJudge())
    assert closed.is_set()
    assert engine.pool.checkedout() == baseline


def test_concurrent_default_shadow_scans_hold_lease_across_attempt_commits(shadow_db, monkeypatch):
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    started, release = Event(), Event()

    class BlockingJudge(FakeJudge):
        def judge(self, state, evidence, candidates):
            started.set()
            assert release.wait(3)
            return super().judge(state, evidence, candidates)

    def run_default(run_judge):
        with shadow_db() as session:
            return run_shadow(session, limit=1, judge=run_judge)

    judge = BlockingJudge()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_default, judge)
        assert started.wait(2)
        second = executor.submit(run_default, FakeJudge())
        assert second.result(2)["attempted"] == 0
        release.set()
        assert first.result(4)["attempted"] == 1


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


def test_explicit_shadow_ids_scan_past_twenty_consumed_inputs(shadow_db, monkeypatch):
    seed_accepted(shadow_db, count=21)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 30)
    with shadow_db() as session:
        evidence_ids = [str(value) for value in session.scalars(select(Evidence.id)).all()]
        judge = FakeJudge()
        assert (
            run_shadow(session, limit=20, judge=judge, evidence_ids=evidence_ids)["attempted"] == 20
        )
        assert (
            run_shadow(session, limit=20, judge=judge, evidence_ids=evidence_ids)["attempted"] == 1
        )
        assert judge.calls == 21


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


def test_shadow_checkpoint_reaches_changed_context_after_deadline_limited_skips(
    shadow_db, monkeypatch
):
    """The old attempt-derived cursor restarts at this consumed prefix forever."""
    project_ids = [seed_accepted(shadow_db, identity_suffix=f"-{index}") for index in range(8)]
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_shadow_daily_limit", 20)
    monkeypatch.setattr(settings, "jev_shadow_timeout_seconds", 1)
    with shadow_db.begin() as session:
        rows = session.execute(
            select(Project, Evidence)
            .join(PowerNeed, PowerNeed.project_id == Project.id)
            .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
            .join(Evidence, Evidence.observation_id == NeedObservation.observation_id)
            .order_by(Evidence.observed_at, Evidence.id, Project.id)
        ).all()
        assert len(rows) == len(project_ids)
        target_project, target_evidence = rows[6]

        def state(project, changed=False):
            return {
                "project_id": str(project.id),
                "state": {
                    "identity": {"status": "KNOWN", "value": "changed" if changed else "old"},
                    "site": None,
                    "lifecycle": None,
                    "activity": None,
                    "power_need": None,
                    "utility_service": None,
                },
                "organizations_and_roles": [],
                "candidate_matches": [],
            }

        for index, (project, evidence) in enumerate(rows):
            deterministic = {"relevant": "YES", "same_project": "UNKNOWN", "material_change": "NO"}
            context = {
                "project": state(project),
                "evidence": {
                    "id": str(evidence.id),
                    "hash": evidence.content_hash,
                    "title": evidence.title[:300],
                    "abstract": evidence.abstract[:1200] if evidence.abstract else None,
                    "url": evidence.url[:500],
                    "published_at": evidence.published_at,
                    "retrieved_at": evidence.observed_at,
                    "extraction_location": evidence.extraction_location[:150],
                },
                "candidates": [],
                "deterministic": deterministic,
                "schema": SCHEMA_VERSION,
                "model": "jev-latest",
            }
            session.add(
                EvidenceJudgeRun(
                    project_id=project.id,
                    evidence_id=evidence.id,
                    candidate_project_id=None,
                    input_key=hashlib.sha256(
                        json.dumps(context, sort_keys=True, default=str).encode()
                    ).hexdigest(),
                    schema_version=SCHEMA_VERSION,
                    model="test-model",
                    status="invalid",
                    deterministic=deterministic,
                    result=None,
                    started_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=index),
                    finished_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=index),
                    latency_ms=1,
                )
            )

    def current_state(_session, project_id):
        project = next(project for project, _evidence in rows if project.id == project_id)
        return state(project, changed=project.id == target_project.id)

    class DeadlineClock:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            self.value += 0.19
            return self.value

    monkeypatch.setattr("gridlens.intelligence.evidence_shadow.project_state", current_state)
    monkeypatch.setattr(
        "gridlens.intelligence.evidence_shadow.recommend_from_context", lambda *_args: False
    )
    monkeypatch.setattr(
        "gridlens.intelligence.evidence_shadow.time", SimpleNamespace(monotonic=DeadlineClock())
    )
    judge = FakeJudge()
    results = []
    for _ in range(8):
        with shadow_db() as session:
            results.append(run_shadow(session, limit=1, judge=judge))
        if judge.calls:
            break
    assert judge.calls == 1
    assert any(result["attempted"] == 0 for result in results[:-1])
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun).where(EvidenceJudgeRun.status == "valid"))
        checkpoint = session.get(EvidenceJudgeScanCheckpoint, "default")
        target_runs = session.scalars(
            select(EvidenceJudgeRun).where(EvidenceJudgeRun.evidence_id == target_evidence.id)
        ).all()
        assert run and run.evidence_id == target_evidence.id
        assert sorted(item.status for item in target_runs) == ["invalid", "valid"]
        assert checkpoint is not None and checkpoint.evidence_id == target_evidence.id
