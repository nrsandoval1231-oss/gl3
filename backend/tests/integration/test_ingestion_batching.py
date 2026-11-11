"""Batch commits in ``process_records`` (performance Phase 2, Step 3).

With ``commit=True`` and ``INGESTION_BATCH_SIZE`` above one, every durable boundary inside a
record is a SAVEPOINT boundary and only the real COMMIT moves to the end of the batch. These
tests pin the failure semantics (they must match what per-boundary commits left behind), the
equivalence of final database state between batch size 1 and 200, replay safety and the lock
scope seen by concurrent writers.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import gridlens.ingestion.service as service
from gridlens.ingestion.adapters.fort_worth_permits import record as fort_worth_record
from gridlens.ingestion.registry import load_registry
from gridlens.persistence.commercial_pursuit_models import CommercialPursuit
from gridlens.persistence.models import (
    CallFactVersion,
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    LogicalCall,
    NeedObservation,
    NeedWorkflowStatusEvent,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
    SignalDecision,
    Source,
    WorkspaceChangeAcknowledgment,
)
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.settings import settings

SOURCE_ID = "fort-worth-development-permits"


def permit(index: int, *, variant: int = 0, kind: str = "accepted") -> dict:
    """A Fort Worth permit record shaped by the adapter's own ``record()``."""
    filed = (date.today() - timedelta(days=3 + index % 10)).isoformat()
    base = f"Batch Campus {index // 2}"
    return fort_worth_record(
        {
            "permit_no": f"PB{9000 + index}",
            "permit_type": "Building",
            # A renovation is retained as evidence but rejected as a new load.
            "subtype": "Remodel" if kind == "rejected" else "New",
            "project": f"{base} Data Center" + (" Phase 2" if index % 2 else ""),
            "work": "New data center building 120,000 SF"
            + (" with added substation yard" if variant else ""),
            "status": "Issued",
            "status_date": filed,
            "filed": filed,
            "job_value": "$25,000,000",
            "owners": [f"Batch Owner {index} LLC"],
            "addresses": [f"{100 + index} Batch Parkway, Fort Worth, TX 76177"],
            "latitude": 32.9,
            "longitude": -97.3,
        }
    )


@pytest.fixture
def db(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test"), "need a *_test database"
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(item for item in load_registry() if item["id"] == SOURCE_ID)
    # Size-driven batches only; the time bound has its own test.
    monkeypatch.setattr(settings, "ingestion_batch_max_seconds", 30.0)

    def seed() -> object:
        reset_test_database(engine)
        with factory.begin() as session:
            session.add(
                Source(
                    id=SOURCE_ID,
                    publisher=definition["publisher"],
                    endpoint=definition["endpoint"],
                    family=definition["family"],
                    geography=definition["geography"],
                    industries=[],
                    retrieval_method=definition["retrieval_method"],
                    health={},
                )
            )
            session.flush()
            job = Job(
                source_id=SOURCE_ID,
                status="running",
                lease_owner="test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            return job.id

    job_id = seed()
    yield engine, factory, definition, job_id, seed
    engine.dispose()


def ingest(factory, job_id, definition, records, **kwargs):
    with factory() as session:
        return service.process_records(session, job_id, "test", 1, definition, records, **kwargs)


def snapshot(factory) -> dict:
    """Final database state keyed by natural identity (no ids or timestamps)."""
    with factory() as session:
        external = {o.id: o.external_id for o in session.scalars(select(Observation))}
        keys = {p.id: p.identity_key for p in session.scalars(select(Project))}
        needs = {
            n.id: (keys[n.project_id], n.activity_key) for n in session.scalars(select(PowerNeed))
        }
        job = session.scalar(select(Job).where(Job.kind == "ingestion"))
        return {
            "observations": sorted(
                (o.external_id, o.content_hash, o.title, o.published_at)
                for o in session.scalars(select(Observation))
            ),
            "evidence": sorted(
                (external[e.observation_id], e.content_hash, e.extraction_location)
                for e in session.scalars(select(Evidence))
            ),
            "interpretations": sorted(
                (
                    external[i.observation_id],
                    i.status,
                    i.error,
                    i.attempts,
                    i.content_hash,
                    i.evaluator_version,
                )
                for i in session.scalars(select(Interpretation))
            ),
            "projects": sorted(
                (p.identity_key, p.name, p.location, p.region_status)
                for p in session.scalars(select(Project))
            ),
            "needs": sorted(
                (*needs[n.id], n.tier, n.active) for n in session.scalars(select(PowerNeed))
            ),
            "need_observations": sorted(
                (*needs[n.need_id], external[n.observation_id])
                for n in session.scalars(select(NeedObservation))
            ),
            "change_events": sorted(
                (external[c.observation_id], c.kind) for c in session.scalars(select(ChangeEvent))
            ),
            "match_decisions": sorted(
                (
                    external[m.observation_id],
                    keys.get(m.candidate_project_id),
                    m.decision,
                )
                for m in session.scalars(select(ProjectMatchDecision))
            ),
            "signal_decisions": sorted(
                (external[s.observation_id], s.decision, s.source)
                for s in session.scalars(select(SignalDecision))
            ),
            "queued_jobs": sorted(
                (j.kind, j.status, external.get(j.target_id))
                for j in session.scalars(select(Job))
                if j.kind != "ingestion"
            ),
            "ledger": {
                "logical_calls": session.scalar(select(func.count()).select_from(LogicalCall)),
            },
            "checkpoint": job.checkpoint if job else None,
        }


def count_commits(engine):
    commits = []

    def on_commit(_conn):
        commits.append(1)

    event.listen(engine, "commit", on_commit)
    return commits, lambda: event.remove(engine, "commit", on_commit)


def checkpoint(factory, job_id):
    with factory() as session:
        return session.get(Job, job_id).checkpoint


def table_counts(factory) -> dict:
    with factory() as session:
        return {
            name: session.scalar(text(f"SELECT count(*) FROM {name}"))
            for name in (
                "observations",
                "evidence",
                "interpretations",
                "projects",
                "power_needs",
                "need_observations",
                "change_events",
                "project_match_decisions",
                "signal_decisions",
                "jobs",
            )
        }


def payload() -> list[dict]:
    """New accepted permits, a rejected one, near-duplicate project names, mixed order."""
    rows = [permit(i) for i in range(9)]
    rows.insert(4, permit(20, kind="rejected"))
    return rows


# --------------------------------------------------------------------------------------
# equivalence, idempotency, accounting
# --------------------------------------------------------------------------------------


def run_scenario(monkeypatch, factory, job_id, definition, size):
    """Varied payload including a durable per-record failure and a raising record."""
    monkeypatch.setattr(settings, "ingestion_batch_size", size)
    original = service.assess_permit
    failing_row = permit(5)["permit"]["row_id"]

    def flaky(record, *args, **kwargs):
        if record["permit"]["row_id"] == failing_row:
            raise ValueError("synthetic interpretation failure")
        return original(record, *args, **kwargs)

    monkeypatch.setattr(service, "assess_permit", flaky)
    rows = payload()
    first = ingest(factory, job_id, definition, rows)
    # Replay: unchanged records, amended records, then a record that raises mid-way
    # (invalid companions) after its evidence boundary.
    amended = [permit(i, variant=1) if i in (1, 2) else rows_i for i, rows_i in enumerate(rows)]
    bad = copy.deepcopy(permit(30))
    bad["companions"] = "not-a-list"
    outcome = {"first": first}
    outcome["replay"] = ingest(factory, job_id, definition, amended)
    with pytest.raises(ValueError, match="companions must be a list"):
        ingest(factory, job_id, definition, [*amended, bad, permit(31)])
    outcome["after_error"] = snapshot(factory)
    return outcome


def test_final_state_is_identical_for_batch_size_1_and_200(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    results = {}
    commits_seen = {}
    for size in (1, 200):
        job_id = seed()
        commits, stop = count_commits(engine)
        try:
            results[size] = run_scenario(monkeypatch, factory, job_id, definition, size)
        finally:
            stop()
        commits_seen[size] = len(commits)
    assert results[1]["first"] == results[200]["first"]
    assert results[1]["replay"] == results[200]["replay"]
    assert results[1]["after_error"] == results[200]["after_error"]
    # The scenario really exercised the failure paths and the batching.
    state = results[200]["after_error"]
    assert any(i[1] == "failed" for i in state["interpretations"])
    bad_id = permit(30)["document_number"]
    assert bad_id in {o[0] for o in state["observations"]}  # its evidence boundary was durable
    assert bad_id in {e[0] for e in state["evidence"]}
    assert not [i for i in state["interpretations"] if i[0] == bad_id]  # raised before it
    assert permit(31)["document_number"] not in {o[0] for o in state["observations"]}
    assert commits_seen[200] * 3 < commits_seen[1]


def test_replay_of_the_same_payload_adds_no_rows(db, monkeypatch):
    _, factory, definition, job_id, _ = db
    monkeypatch.setattr(settings, "ingestion_batch_size", 200)
    rows = payload()
    first = ingest(factory, job_id, definition, rows)
    before = (table_counts(factory), snapshot(factory))
    second = ingest(factory, job_id, definition, rows)
    assert first["new"] == len(rows) and second["unchanged"] == len(rows)
    assert second["new"] == 0 and second["changed"] == 0
    after = (table_counts(factory), snapshot(factory))
    assert before == after


@pytest.mark.parametrize("keyed", [False, True])
def test_provider_accounting_and_ledgers_do_not_depend_on_batch_size(db, monkeypatch, keyed):
    """Ledger rows (logical calls, queued adjudication jobs) match for sizes 1 and 200.

    With a Jev key configured ingestion only queues adjudication jobs (no provider call at
    ingestion time); without one it records an unavailable decision. Either way the same rows
    must exist.
    """
    from pydantic import SecretStr

    engine, factory, definition, _, seed = db
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic") if keyed else None)
    states = {}
    for size in (1, 200):
        job_id = seed()
        monkeypatch.setattr(settings, "ingestion_batch_size", size)
        ingest(factory, job_id, definition, payload())
        with factory() as session:
            ledger = {
                "logical_calls": session.scalar(select(func.count()).select_from(LogicalCall)),
                "signal_decisions": sorted(
                    (s.decision, s.source) for s in session.scalars(select(SignalDecision))
                ),
                "queued": sorted(
                    j.kind for j in session.scalars(select(Job)) if j.kind != "ingestion"
                ),
            }
        states[size] = ledger
    assert states[1] == states[200]
    assert states[200]["logical_calls"] == 0
    assert states[200]["signal_decisions"] or states[200]["queued"]


# --------------------------------------------------------------------------------------
# failure semantics
# --------------------------------------------------------------------------------------


class Crash(BaseException):
    """Stands in for a process dying: not an ``Exception``, so no cleanup code runs."""


def test_resume_after_a_crash_mid_batch_has_no_duplicate_or_lost_evidence(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    rows = [permit(i) for i in range(8)]
    monkeypatch.setattr(settings, "ingestion_batch_size", 3)

    # Reference: an uninterrupted run at batch size 1.
    monkeypatch.setattr(settings, "ingestion_batch_size", 1)
    ingest(factory, job_id, definition, rows)
    reference = snapshot(factory)

    job_id = seed()
    monkeypatch.setattr(settings, "ingestion_batch_size", 3)
    import gridlens.intelligence.equipment_intelligence as equipment

    original = equipment.materialize_equipment_investigation
    seen = []

    def crash_on_sixth(*args, **kwargs):
        seen.append(1)
        if len(seen) == 6:
            raise Crash("process died")
        return original(*args, **kwargs)

    monkeypatch.setattr(equipment, "materialize_equipment_investigation", crash_on_sixth)
    with pytest.raises(Crash):
        ingest(factory, job_id, definition, rows)
    monkeypatch.setattr(equipment, "materialize_equipment_investigation", original)

    # Only the first complete batch (records 0-2) survived; the open batch died with the session.
    with factory() as session:
        survivors = sorted(session.scalars(select(Observation.external_id)))
    assert survivors == sorted(r["document_number"] for r in rows[:3])
    assert checkpoint(factory, job_id) == rows[2]["document_number"]

    resumed = ingest(factory, job_id, definition, rows)
    assert resumed["unchanged"] == 3 and resumed["new"] == 5
    # Same evidence as an uninterrupted run, and none duplicated.
    resumed_state = snapshot(factory)
    assert resumed_state == reference
    with factory() as session:
        pairs = session.execute(
            select(Evidence.observation_id, Evidence.content_hash, func.count())
            .group_by(Evidence.observation_id, Evidence.content_hash)
            .having(func.count() > 1)
        ).all()
    assert pairs == []


def test_lease_loss_at_any_point_publishes_only_whole_committed_batches(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    rows = [permit(i) for i in range(10)]
    size = 4
    original = service.assert_fence

    # Count assert_fence calls of an undisturbed run to pick loss points across the run.
    calls = []
    monkeypatch.setattr(
        service, "assert_fence", lambda *a, **k: (calls.append(1), original(*a, **k))[1]
    )
    monkeypatch.setattr(settings, "ingestion_batch_size", size)
    ingest(factory, job_id, definition, rows)
    total = len(calls)
    assert total > 30
    monkeypatch.setattr(service, "assert_fence", original)

    survived = set()
    for lose_at in sorted({1, 2, 6, 7, 8, 15, 29, total // 2, total - 2, total - 1, total}):
        job_id = seed()
        count = []

        def losing(session, job, worker, fence, _limit=lose_at, _count=count):
            _count.append(1)
            if len(_count) >= _limit:
                raise RuntimeError("Worker lease fence lost")
            return original(session, job, worker, fence)

        monkeypatch.setattr(service, "assert_fence", losing)
        with pytest.raises(RuntimeError, match="fence lost"):
            ingest(factory, job_id, definition, rows)
        monkeypatch.setattr(service, "assert_fence", original)
        with factory() as session:
            published = session.scalar(select(func.count()).select_from(Observation))
            evidence = session.scalar(select(func.count()).select_from(Evidence))
            interpretations = session.scalar(select(func.count()).select_from(Interpretation))
            checkpointed = session.get(Job, job_id).checkpoint
        # Never a partial batch: only whole committed batches of 4 records survive.
        assert published in (0, 4, 8), (lose_at, published)
        assert evidence == published and interpretations == published
        assert checkpointed == (rows[published - 1]["document_number"] if published else None)
        survived.add(published)
    assert 0 in survived and survived & {4, 8}


def test_retained_evidence_survives_a_later_enrichment_failure(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    import gridlens.intelligence.equipment_intelligence as equipment

    rows = [permit(i) for i in range(5)]
    original = equipment.materialize_equipment_investigation
    states = {}
    for size in (1, 200):
        job_id = seed()
        monkeypatch.setattr(settings, "ingestion_batch_size", size)
        seen = []

        def fail_third(*args, _seen=seen, **kwargs):
            _seen.append(1)
            if len(_seen) == 3:
                raise RuntimeError("enrichment failed")
            return original(*args, **kwargs)

        monkeypatch.setattr(equipment, "materialize_equipment_investigation", fail_third)
        with pytest.raises(RuntimeError, match="enrichment failed"):
            ingest(factory, job_id, definition, rows)
        monkeypatch.setattr(equipment, "materialize_equipment_investigation", original)
        states[size] = snapshot(factory)
    assert states[1] == states[200]
    state = states[200]
    failing = rows[2]["document_number"]
    # The failing record's Observation, Evidence and retryable pending Interpretation are
    # durable; its project, need and links were rolled back with the failing section.
    assert failing in {o[0] for o in state["observations"]}
    assert failing in {e[0] for e in state["evidence"]}
    assert [i[1] for i in state["interpretations"] if i[0] == failing] == ["pending"]
    assert failing not in {n[2] for n in state["need_observations"]}
    # Records before it are complete; the checkpoint names the last finished one.
    assert state["checkpoint"] == rows[1]["document_number"]
    assert len(state["observations"]) == 3


def test_a_durable_per_record_failure_is_published_with_its_batch(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    monkeypatch.setattr(settings, "ingestion_batch_size", 200)
    original = service.assess_permit
    rows = [permit(i) for i in range(4)]
    failing = rows[1]["permit"]["row_id"]

    def flaky(record, *args, **kwargs):
        if record["permit"]["row_id"] == failing:
            raise ValueError("synthetic")
        return original(record, *args, **kwargs)

    monkeypatch.setattr(service, "assess_permit", flaky)
    counts = ingest(factory, job_id, definition, rows)
    assert counts["new"] == 4
    state = snapshot(factory)
    by_id = {i[0]: i for i in state["interpretations"]}
    assert by_id[rows[1]["document_number"]][1:3] == ("failed", "ValueError")
    assert all(by_id[r["document_number"]][1] == "accepted" for r in (rows[0], rows[2], rows[3]))
    # Replaying with the fault gone retries the failed record (retryable pending row).
    monkeypatch.setattr(service, "assess_permit", original)
    ingest(factory, job_id, definition, rows)
    retried = {i[0]: i for i in snapshot(factory)["interpretations"]}
    assert retried[rows[1]["document_number"]][1] == "accepted"


def test_batch_size_one_and_commit_false_keep_per_boundary_behaviour(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    rows = [permit(i) for i in range(4)]
    monkeypatch.setattr(settings, "ingestion_batch_size", 1)
    commits, stop = count_commits(engine)
    try:
        ingest(factory, job_id, definition, rows)
    finally:
        stop()
    assert len(commits) >= 3 * len(rows)  # every boundary is a real commit again

    job_id = seed()
    monkeypatch.setattr(settings, "ingestion_batch_size", 200)
    commits, stop = count_commits(engine)
    try:
        with factory() as session:
            counts = service.process_records(
                session, job_id, "test", 1, definition, rows, commit=False
            )
            assert not commits  # the caller owns the transaction
            assert session.scalar(select(func.count()).select_from(Observation)) == len(rows)
            assert session.get(Job, job_id).checkpoint is None
            session.rollback()
    finally:
        stop()
    assert counts["new"] == len(rows)
    assert table_counts(factory)["observations"] == 0


def test_time_bound_commits_a_batch_and_refreshes_the_lease(db, monkeypatch):
    engine, factory, definition, job_id, seed = db
    rows = [permit(i) for i in range(6)]
    monkeypatch.setattr(settings, "ingestion_batch_size", 1000)
    monkeypatch.setattr(settings, "ingestion_batch_max_seconds", 0.05)
    clock = [1000.0]
    real_monotonic = service.time.monotonic

    def slow_clock():
        clock[0] += 0.04  # every reading advances; batches end by the time bound
        return clock[0]

    monkeypatch.setattr(service.time, "monotonic", slow_clock)
    commits, stop = count_commits(engine)
    try:
        ingest(factory, job_id, definition, rows)
    finally:
        stop()
        monkeypatch.setattr(service.time, "monotonic", real_monotonic)
    assert 2 <= len(commits) <= len(rows) + 1
    assert checkpoint(factory, job_id) == rows[-1]["document_number"]
    with factory() as session:
        assert session.get(Job, job_id).lease_until > datetime.now(UTC) + timedelta(seconds=30)


# --------------------------------------------------------------------------------------
# lock scope
# --------------------------------------------------------------------------------------


def test_open_ingestion_batch_does_not_block_api_style_writes(db, monkeypatch):
    """Rows locked by an open batch (replay of amended permits) must not stall API writes.

    Pass 1 commits projects and needs. Pass 2 amends the same permits, so the batch takes its
    project and need locks on committed rows, then pauses just before COMMIT while separate
    connections perform each kind of API write under a short ``lock_timeout``.
    """
    engine, factory, definition, job_id, seed = db
    monkeypatch.setattr(settings, "ingestion_batch_size", 200)
    rows = [permit(i) for i in range(3)]
    ingest(factory, job_id, definition, rows)
    with factory() as session:
        need = session.scalars(select(PowerNeed).order_by(PowerNeed.id)).first()
        need_id, project_id = need.id, need.project_id

    outcomes: dict[str, str] = {}

    def attempt(name, work):
        with engine.connect() as conn:
            try:
                with conn.begin():
                    conn.execute(text("SET LOCAL lock_timeout = '400ms'"))
                    work(conn)
                outcomes[name] = "ok"
            except OperationalError as exc:
                outcomes[name] = f"BLOCKED: {str(exc.orig).splitlines()[0]}"

    def commercial_pursuit(conn):
        conn.execute(
            CommercialPursuit.__table__.insert().values(
                id=uuid4(), need_id=need_id, project_id=project_id, stage="New"
            )
        )

    def contact_suppression(conn):
        conn.execute(
            ContactSuppression.__table__.insert().values(
                id=uuid4(),
                scope="company",
                subject_key="a" * 64,
                expected_version=0,
                version=1,
                action="suppress",
                reason="batch lock probe",
                actor="test",
                idempotency_key=str(uuid4()),
            )
        )

    def owner_fact(conn):
        conn.execute(
            CallFactVersion.__table__.insert().values(
                id=uuid4(),
                need_id=need_id,
                project_id=project_id,
                client_id=uuid4(),
                activity_key="facility-expansion",
                facility_scope="site",
                fact_type="load_mw",
                value={"mw": 1},
                reporter_name="Owner",
                confirmation_channel="call",
                confirmed_at=datetime.now(UTC),
                effective_from=datetime.now(UTC),
                content_hash="f" * 64,
                recorded_by="owner",
            )
        )

    def workflow_status(conn):
        conn.execute(
            NeedWorkflowStatusEvent.__table__.insert().values(
                id=uuid4(),
                need_id=need_id,
                project_id=project_id,
                version=1,
                client_id=uuid4(),
                status="Working",
                expected_version=0,
                reason="batch lock probe",
                content_hash="e" * 64,
                actor="owner",
            )
        )

    def saved_view(conn):
        conn.execute(
            WorkspaceChangeAcknowledgment.__table__.insert().values(
                event_key="b" * 64, reviewed_at=datetime.now(UTC), review_token="c" * 64
            )
        )

    original_commit = service._IngestionBatch._commit_batch

    def probe_then_commit(self):
        for name, work in (
            ("commercial_pursuit", commercial_pursuit),
            ("contact_suppression", contact_suppression),
            ("owner_fact", owner_fact),
            ("workflow_status", workflow_status),
            ("saved_view", saved_view),
        ):
            attempt(name, work)
        original_commit(self)

    monkeypatch.setattr(service._IngestionBatch, "_commit_batch", probe_then_commit)
    amended = [permit(i, variant=1) for i in range(3)]
    counts = ingest(factory, job_id, definition, amended)
    assert counts["changed"] == 3
    # Writes that do not reference a locked project or need row are never held up.
    assert outcomes["contact_suppression"] == "ok"
    assert outcomes["saved_view"] == "ok"
    # KNOWN LIMITATION (Step 3 lock-scope notes in experience/benchmarks.md):
    # an INSERT that references a project or need row waits for its FOR KEY SHARE while the
    # batch holds FOR UPDATE on that row, so it waits until the batch ends (bounded by
    # INGESTION_BATCH_MAX_SECONDS). The fix is FOR NO KEY UPDATE in process_records, in
    # change_detection.lock_project and in buying_chain.enqueue_retained_buying_chain_research
    # (plus the "for update" text match in the existing test
    # test_linked_negative_correction_locks_project_before_need);
    # when it lands this set becomes empty and the assertion below must be tightened.
    blocked = {name for name, outcome in outcomes.items() if outcome != "ok"}
    assert blocked == {"commercial_pursuit", "owner_fact", "workflow_status"}, outcomes


def test_network_companion_fetch_ends_the_batch_first(db, monkeypatch):
    """A PDF fetch needs a clean session, so the batch commits before it and the rest of that
    record commits for real; the final state still matches batch size 1."""
    engine, factory, _, _, _ = db
    fr = next(item for item in load_registry() if item["id"] == "federal-register-eis")
    states = {}
    fetched = {}
    for size in (1, 200):
        reset_test_database(engine)
        with factory.begin() as session:
            session.add(
                Source(
                    id=fr["id"],
                    publisher=fr["publisher"],
                    endpoint=fr["endpoint"],
                    family=fr["family"],
                    geography="US",
                    industries=[],
                    retrieval_method=fr["retrieval_method"],
                    health={},
                )
            )
            session.flush()
            job = Job(
                source_id=fr["id"],
                status="running",
                lease_owner="test",
                fence=1,
                lease_until=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id

        def citations(record, client=None, _size=size, **kwargs):
            number = record["document_number"]
            fetched.setdefault(_size, []).append(number)
            return [
                {
                    "content_hash": f"pdf-{number}",
                    "title": f"Official PDF {number}",
                    "abstract": "Mine plan of operations text.",
                    "url": f"https://www.govinfo.gov/content/pkg/{number}.pdf",
                    "published_at": "2026-09-14",
                    "extraction_location": "PDF page 1",
                }
            ]

        monkeypatch.setattr(service, "retrieve_companion", citations)
        monkeypatch.setattr(settings, "ingestion_batch_size", size)
        rows = []
        for index in range(5):
            row = {
                "document_number": f"FR-{index}",
                "title": f"Silver Ridge {index} Mine: Synthetic Test Notice",
                "abstract": "The proposed Mine Plan of Operations would develop the mine, "
                "with dewatering and ventilation shafts.",
                "publication_date": "2026-09-14",
                "html_url": f"https://www.federalregister.gov/documents/2026/09/14/FR-{index}",
            }
            if index in (1, 3):
                row["pdf_url"] = f"https://www.govinfo.gov/content/pkg/FR-{index}.pdf"
            rows.append(row)
        counts = ingest(factory, job_id, fr, rows)
        assert counts["pdf_enriched"] == 2
        with factory() as session:
            states[size] = {
                "evidence": sorted(
                    (o.external_id, e.content_hash)
                    for e, o in session.execute(
                        select(Evidence, Observation).join(
                            Observation, Evidence.observation_id == Observation.id
                        )
                    )
                ),
                "interpretations": sorted(
                    (o.external_id, i.status)
                    for i, o in session.execute(
                        select(Interpretation, Observation).join(
                            Observation, Interpretation.observation_id == Observation.id
                        )
                    )
                ),
                "checkpoint": session.get(Job, job_id).checkpoint,
            }
    assert states[1] == states[200]
    assert fetched[200] == ["FR-1", "FR-3"]
    assert ("FR-1", "pdf-FR-1") in states[200]["evidence"]
    assert states[200]["checkpoint"] == "FR-4"
