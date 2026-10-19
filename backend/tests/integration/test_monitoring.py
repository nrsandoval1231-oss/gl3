import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.monitoring import (
    configure_watch,
    plan_monitoring,
    process_monitor_job,
    record_monitor_outcome,
)
from gridlens.intelligence.question_contracts import (
    QUESTION_CONTRACTS,
    question_category,
    question_context,
    question_contract,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.persistence.watch_models import ProjectMonitorWatch, ProjectMonitorWatchSource
from gridlens.settings import settings

# Register the new models until the controller's models.py import hook lands.
assert ProjectMonitorWatch.__table__ in Base.metadata.tables.values()

SOURCE_ID = "austin-building-permits"
SOURCE_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"


@pytest.fixture
def sessions():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url, pool_size=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(factory, suffix: str = "a"):
    with factory.begin() as session:
        if session.get(Source, SOURCE_ID) is None:
            session.add(
                Source(
                    id=SOURCE_ID,
                    publisher="Austin Open Data",
                    endpoint=SOURCE_URL,
                    family="construction-permits",
                    geography="Austin, TX",
                    industries=["data-centers"],
                    retrieval_method="socrata",
                    cadence_hours=24,
                    enabled=True,
                    registry_enabled=True,
                    health={},
                )
            )
            session.flush()
        project = Project(
            identity_key=f"monitor-project-{suffix}",
            name=f"Monitor project {suffix}",
            location="Austin, TX",
            source_id=SOURCE_ID,
            external_id=f"project-{suffix}",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key=f"construction-{suffix}",
            rationale="Bounded synthetic monitoring target",
        )
        session.add(need)
        session.flush()
        return need.id


def _configure(session, need_id, urls=None, questions=None):
    return configure_watch(
        session,
        need_id,
        sources=[{"source_id": SOURCE_ID, "allowed_urls": urls or [SOURCE_URL]}],
        question_ids=questions,
    )


def _lease(factory, job_id, *, fence=1):
    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.status = "running"
        job.lease_owner = "test-worker"
        job.fence = fence
        job.lease_until = datetime.now(UTC) + timedelta(minutes=2)


def _complete(factory, job_id, *, disposition, fence=1, **kwargs):
    with factory.begin() as session:
        record_monitor_outcome(
            session,
            job_id=job_id,
            worker_id="test-worker",
            fence=fence,
            disposition=disposition,
            now=datetime.now(UTC),
            **kwargs,
        )


def _add_evidence(session, need_id, external_id, digest):
    observation = Observation(
        source_id=SOURCE_ID,
        external_id=external_id,
        title="Austin construction schedule",
        abstract="Synthetic retained source evidence for monitoring tests.",
        url="https://data.austintexas.gov/resource/3syk-w9eu.json",
        content_hash=digest,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=digest,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
    )
    session.add(evidence)
    session.add(NeedObservation(need_id=need_id, observation_id=observation.id))
    session.flush()
    return evidence.id


def test_question_ids_map_to_existing_categories_and_keep_identity():
    assert set(QUESTION_CONTRACTS) == {
        "UTILITY_ONLINE_DATE",
        "TEMP_LOAD_MW",
        "CONSTRUCTION_START",
        "COMMISSIONING_WINDOW",
        "NATURAL_GAS_AVAILABILITY",
        "DIRECT_BUYER_AUTHORITY",
    }
    assert question_category("UTILITY_ONLINE_DATE") == "supply"
    assert question_category("NATURAL_GAS_AVAILABILITY") == "supply"
    utility = question_context("UTILITY_ONLINE_DATE", {"need": "same"})
    gas = question_context("NATURAL_GAS_AVAILABILITY", {"need": "same"})
    assert utility["category"] == gas["category"] == "supply"
    assert utility["question_id"] != gas["question_id"]
    assert utility["contract_version"] == gas["contract_version"]
    with pytest.raises(ValueError, match="Unknown commercial question"):
        question_contract("UNREGISTERED")


def test_planner_is_disabled_by_default_and_deduplicates_per_target(sessions):
    need_a = _seed(sessions, "a")
    need_b = _seed(sessions, "b")
    with sessions.begin() as session:
        watch_a = _configure(session, need_a)
        watch_b = _configure(session, need_b)
        assert watch_a.id != watch_b.id
    with sessions.begin() as session:
        assert plan_monitoring(session, limit=20) == []
    with sessions.begin() as session:
        first = plan_monitoring(session, enabled=True, limit=1)
        assert len(first) == 1
        first_job = session.get(Job, first[0])
        first_watch = first_job.target_id
    with sessions.begin() as session:
        second = plan_monitoring(session, enabled=True, limit=20)
        assert len(second) == 1
        second_job = session.get(Job, second[0])
        assert second_job.target_id != first_watch
    with sessions.begin() as session:
        assert plan_monitoring(session, enabled=True, limit=20) == []
        assert len(list(session.scalars(select(Job).where(Job.kind == "project_monitor")))) == 2


def test_revision_forces_reprocess_and_no_change_preserves_good_evidence(sessions):
    need_id = _seed(sessions)
    with sessions.begin() as session:
        watch = _configure(session, need_id)
        watch_id = watch.id
        job_id = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, job_id)
    with sessions.begin() as session:
        evidence_id = _add_evidence(session, need_id, "permit-a", "a" * 64)
    evidence = [{"source_id": SOURCE_ID, "evidence_id": str(evidence_id), "content_hash": "a" * 64}]
    _complete(
        sessions,
        job_id,
        disposition="updated",
        facts=[{"field": "construction_start", "value": "2027-Q1"}],
        evidence_refs=evidence,
        unresolved_questions=["TEMP_LOAD_MW"],
    )
    with sessions.begin() as session:
        watch = session.get(ProjectMonitorWatch, watch_id)
        good_facts = watch.last_good_facts
        good_refs = watch.last_good_evidence_refs
        old_allowed = list(session.scalar(select(ProjectMonitorWatchSource)).allowed_urls)
        cursor_row = session.scalar(select(ProjectMonitorWatchSource))
        cursor_row.cursor = {"stable": "native-cursor"}
        assert cursor_row.applied_version == watch.version
        cursor_row.next_due_at = datetime.now(UTC) + timedelta(days=4)
    with sessions.begin() as session:
        updated = _configure(
            session, need_id, urls=[SOURCE_URL, "https://data.austintexas.gov/resource/other.json"]
        )
        assert updated.version == 2
        assert updated.revision_history[-1]["version"] == 1
        assert updated.revision_history[-1]["last_good_facts"] == good_facts
        assert updated.revision_history[-1]["last_good_evidence_refs"] == good_refs
        assert updated.revision_history[-1]["sources"][0]["allowed_urls"] == old_allowed
        assert updated.revision_history[-1]["sources"][0]["cursor"] == {
            "stable": "native-cursor"
        }
    with sessions.begin() as session:
        job_id2 = plan_monitoring(session, enabled=True)[0]
        assert session.get(Job, job_id2).target_id == watch_id
    _lease(sessions, job_id2)
    _complete(
        sessions,
        job_id2,
        disposition="checked_no_change",
        cursor={"native_id": "same-content"},
    )
    with sessions.begin() as session:
        watch = session.get(ProjectMonitorWatch, watch_id)
        cursor_row = session.scalar(select(ProjectMonitorWatchSource))
        assert watch.last_good_facts == good_facts
        assert watch.last_good_evidence_refs == good_refs
        assert cursor_row.cursor == {"native_id": "same-content"}
        assert cursor_row.applied_version == watch.version


def test_failed_refresh_keeps_last_good_and_stale_fence_cannot_write(sessions):
    need_id = _seed(sessions)
    with sessions.begin() as session:
        watch_id = _configure(session, need_id).id
        first = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, first)
    good_facts = [{"field": "load_mw", "value": "2-4"}]
    with sessions.begin() as session:
        evidence_id = _add_evidence(session, need_id, "permit-b", "b" * 64)
    good_refs = [
        {"source_id": SOURCE_ID, "evidence_id": str(evidence_id), "content_hash": "b" * 64}
    ]
    _complete(sessions, first, disposition="updated", facts=good_facts, evidence_refs=good_refs)
    with sessions.begin() as session:
        cursor_row = session.scalar(select(ProjectMonitorWatchSource))
        cursor_row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
    with sessions.begin() as session:
        second = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, second)
    with pytest.raises(RuntimeError, match="fence lost"):
        _complete(sessions, second, disposition="failed", fence=0, error_class="TimeoutError")
    _complete(sessions, second, disposition="failed", error_class="TimeoutError")
    with sessions.begin() as session:
        watch = session.get(ProjectMonitorWatch, watch_id)
        cursor_row = session.scalar(select(ProjectMonitorWatchSource))
        job = session.get(Job, second)
        assert watch.last_good_facts == good_facts
        assert watch.last_good_evidence_refs == good_refs
        assert watch.status == "failed"
        assert cursor_row.status == "failed"
        assert cursor_row.consecutive_failures == 1
        assert cursor_row.next_due_at > datetime.now(UTC)
        assert job.status == "failed"


def test_repeated_failures_quarantine_until_deliberate_revision(sessions):
    need_id = _seed(sessions, "quarantine")
    with sessions.begin() as session:
        _configure(session, need_id)
    for attempt in range(5):
        with sessions.begin() as session:
            job_id = plan_monitoring(session, enabled=True)[0]
        _lease(sessions, job_id)
        _complete(sessions, job_id, disposition="failed", error_class="TimeoutError")
        if attempt < 4:
            with sessions.begin() as session:
                cursor = session.scalar(select(ProjectMonitorWatchSource))
                cursor.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
    with sessions.begin() as session:
        cursor = session.scalar(select(ProjectMonitorWatchSource))
        assert cursor.status == "quarantined"
        assert cursor.consecutive_failures == 5
        assert plan_monitoring(session, enabled=True) == []
    with sessions.begin() as session:
        configure_watch(
            session,
            need_id,
            sources=[{"source_id": SOURCE_ID, "allowed_urls": [SOURCE_URL]}],
            reprocess_revision="explicit-reprocess-2",
        )
        cursor = session.scalar(select(ProjectMonitorWatchSource))
        assert cursor.status == "idle"
        assert cursor.consecutive_failures == 0
        assert len(plan_monitoring(session, enabled=True)) == 1


def test_disabled_sources_forbidden_urls_and_cancelled_job(sessions):
    need_id = _seed(sessions)
    with sessions.begin() as session:
        with pytest.raises(ValueError, match="forbidden|public|URL|address"):
            _configure(session, need_id, urls=["http://127.0.0.1/private"])
        with pytest.raises(ValueError, match="only once"):
            configure_watch(
                session,
                need_id,
                sources=[
                    {"source_id": SOURCE_ID, "allowed_urls": [SOURCE_URL]},
                    {"source_id": SOURCE_ID, "allowed_urls": [SOURCE_URL]},
                ],
            )
        watch_id = _configure(session, need_id).id
        job_id = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, job_id)
    _complete(sessions, job_id, disposition="cancelled")
    with sessions.begin() as session:
        source = session.get(Source, SOURCE_ID)
        source.enabled = False
    with sessions.begin() as session:
        source_cursor = session.scalar(select(ProjectMonitorWatchSource))
        source_cursor.next_due_at = datetime.now(UTC) - timedelta(days=1)
    with sessions.begin() as session:
        assert plan_monitoring(session, enabled=True) == []
        assert session.get(ProjectMonitorWatch, watch_id).status == "cancelled"


def test_planning_query_and_batch_are_bounded(sessions):
    need_id = _seed(sessions)
    with sessions.begin() as session:
        _configure(session, need_id)
    statements = []
    bind = sessions.kw["bind"]

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    event.listen(bind, "before_cursor_execute", count_selects)
    try:
        with sessions.begin() as session:
            with pytest.raises(ValueError, match="between 1"):
                plan_monitoring(session, enabled=True, limit=101)
        with sessions.begin() as session:
            jobs = plan_monitoring(session, enabled=True, limit=1)
        assert len(jobs) == 1
        assert len(statements) == 6  # lock, active cap, provision cursor/wrap, due targets
        assert all(
            "limit" in statement.lower() or "pg_advisory_xact_lock" in statement
            for statement in statements
        )
    finally:
        event.remove(bind, "before_cursor_execute", count_selects)


def test_planner_respects_global_host_and_source_active_caps(sessions):
    need_ids = [_seed(sessions, f"cap-{index}") for index in range(4)]
    with sessions.begin() as session:
        for need_id in need_ids:
            _configure(session, need_id)
        first = plan_monitoring(
            session,
            enabled=True,
            max_active_jobs=4,
            max_active_per_host=4,
            max_active_per_source=1,
        )
        assert len(first) == 1
    with sessions.begin() as session:
        assert plan_monitoring(
            session,
            enabled=True,
            max_active_jobs=4,
            max_active_per_host=4,
            max_active_per_source=1,
        ) == []
        active = list(
            session.scalars(
                select(Job).where(
                    Job.kind == "project_monitor",
                    Job.status.in_(["queued", "running"]),
                )
            )
        )
        assert len(active) == 1


def test_explicit_policy_revision_requeues_same_sources_and_preserves_prior_snapshot(sessions):
    need_id = _seed(sessions, "policy-revision")
    with sessions.begin() as session:
        watch = _configure(session, need_id)
        old_digest = session.scalar(select(ProjectMonitorWatchSource)).policy_snapshot["digest"]
        watch_id = watch.id
    with sessions.begin() as session:
        updated = configure_watch(
            session,
            need_id,
            sources=[{"source_id": SOURCE_ID, "allowed_urls": [SOURCE_URL]}],
            reprocess_revision="parser-r2",
        )
        assert updated.version == 2
        assert updated.reprocess_revision == "parser-r2"
        assert updated.revision_history[-1]["reprocess_revision"] == "watch-policy-v1"
        assert updated.revision_history[-1]["sources"][0]["policy_snapshot"]["digest"] == old_digest
    with sessions.begin() as session:
        job_id = plan_monitoring(session, enabled=True)[0]
        assert session.get(Job, job_id).target_id == watch_id


def test_planner_provisions_only_from_current_accepted_need_evidence(sessions):
    need_id = _seed(sessions, "auto-watch")
    with sessions.begin() as session:
        evidence_id = _add_evidence(session, need_id, "permit-auto", "c" * 64)
        evidence = session.get(Evidence, evidence_id)
        session.add(
            Interpretation(
                observation_id=evidence.observation_id,
                content_hash=evidence.content_hash,
                assessment={"evidence_hash": evidence.content_hash},
                status="accepted",
            )
        )
    with sessions.begin() as session:
        queued = plan_monitoring(session, enabled=True, limit=5)
        assert len(queued) == 1
        job = session.get(Job, queued[0])
        watch = session.get(ProjectMonitorWatch, job.target_id)
        source = session.scalar(
            select(ProjectMonitorWatchSource).where(
                ProjectMonitorWatchSource.watch_id == watch.id
            )
        )
        assert watch.enabled is True
        assert watch.question_ids == list(QUESTION_CONTRACTS)
        assert watch.last_good_evidence_refs[0]["content_hash"] == "c" * 64
        assert source.source_id == SOURCE_ID
        assert source.record_ids == ["permit-auto"]


def test_fake_retrieval_runs_outside_transaction_with_bounded_watch_context(sessions):
    need_id = _seed(sessions)
    with sessions.begin() as session:
        _configure(session, need_id, questions=["TEMP_LOAD_MW"])
        job_id = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, job_id)
    observed = {}

    def fake_retrieve(request):
        observed["request"] = request
        assert request.allowed_urls == (SOURCE_URL,)
        assert request.question_ids == ("TEMP_LOAD_MW",)
        assert request.max_documents == 5
        assert request.max_document_bytes == 750_000
        assert request.deadline_monotonic > time.monotonic()
        return {"disposition": "checked_no_change", "cursor": {"row": "unchanged"}}

    disposition = process_monitor_job(
        job_id,
        "test-worker",
        1,
        enabled=True,
        retrieve=fake_retrieve,
        session_factory=sessions,
    )
    assert disposition == "checked_no_change"
    assert observed["request"].source_id == SOURCE_ID
    with sessions.begin() as session:
        cursor = session.scalar(select(ProjectMonitorWatchSource))
        assert cursor.cursor == {"row": "unchanged"}


def test_default_runner_uses_registered_acquisition_and_canonical_retention(
    sessions, monkeypatch
):
    from gridlens.intelligence import monitoring, research_evidence

    need_id = _seed(sessions, "default-runner")
    with sessions.begin() as session:
        evidence_id = _add_evidence(session, need_id, "permit-refresh", "d" * 64)
        evidence = session.get(Evidence, evidence_id)
        session.add(
            Interpretation(
                observation_id=evidence.observation_id,
                content_hash=evidence.content_hash,
                assessment={"evidence_hash": evidence.content_hash},
                status="accepted",
            )
        )
        configure_watch(
            session,
            need_id,
            sources=[
                {
                    "source_id": SOURCE_ID,
                    "allowed_urls": [SOURCE_URL],
                    "record_ids": ["permit-refresh"],
                }
            ],
            question_ids=["CONSTRUCTION_START"],
        )
        job_id = plan_monitoring(session, enabled=True)[0]
    _lease(sessions, job_id)
    new_hash = "e" * 64
    calls = {}

    def fake_acquire(source_id, external_id, *, deadline, before_request, max_bytes):
        calls["acquire"] = (source_id, external_id, deadline, max_bytes)
        before_request(SOURCE_URL)
        return (
            {"id": source_id},
            {
                "document_number": external_id,
                "html_url": SOURCE_URL,
                "title": "Updated exact permit",
                "abstract": "Updated source text",
                "publication_date": None,
                "event_date": None,
                "event_date_label": None,
                "source_hash": new_hash,
            },
        )

    def fake_retain(session, project, need, source_definition, record, **kwargs):
        calls["retain"] = (project.id, need.id, record["document_number"], kwargs)
        observation = session.scalar(
            select(Observation).where(
                Observation.source_id == SOURCE_ID,
                Observation.external_id == record["document_number"],
            )
        )
        observation.content_hash = new_hash
        observation.title = record["title"]
        observation.abstract = record["abstract"]
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=new_hash,
            title=record["title"],
            abstract=record["abstract"],
            url=SOURCE_URL,
        )
        session.add(evidence)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.content_hash = new_hash
        interpretation.assessment = {"evidence_hash": new_hash}
        interpretation.status = "accepted"
        session.flush()
        return {"disposition": "ACCEPTED", "evidence_id": str(evidence.id)}

    monkeypatch.setattr(monitoring, "acquire_registered_record", fake_acquire)
    monkeypatch.setattr(research_evidence, "retain_registered_record", fake_retain)
    disposition = process_monitor_job(
        job_id,
        "test-worker",
        1,
        enabled=True,
        session_factory=sessions,
    )
    assert disposition == "updated"
    assert calls["acquire"][0:2] == (SOURCE_ID, "permit-refresh")
    assert calls["acquire"][3] == 750_000
    assert calls["retain"][1:3] == (need_id, "permit-refresh")
    with sessions.begin() as session:
        watch = session.scalar(
            select(ProjectMonitorWatch).where(ProjectMonitorWatch.need_id == need_id)
        )
        assert watch.last_good_evidence_refs[0]["content_hash"] == new_hash
