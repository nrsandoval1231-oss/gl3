"""PostgreSQL regressions for draft-only saved-browse invalidation."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.saved_browse import clock_deadline, rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseDirtyProject,
    BrowseState,
    CallFactDecision,
    CallFactVersion,
    PowerNeed,
)
from gridlens.settings import settings

api = import_module("gridlens.api.app")


@pytest.fixture
def publication_db(monkeypatch):
    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    assert test_url.host in {"127.0.0.1", "::1", "localhost"}
    assert test_url.database and test_url.database.endswith("_test")
    assert "corpus" not in test_url.database.lower()
    assert (test_url.host, test_url.port, test_url.database) != (
        app_url.host,
        app_url.port,
        app_url.database,
    )
    admin = create_engine(settings.test_database_url)
    schema = "fact_draft_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def _seed(factory, count=1):
    from test_saved_browse import seed

    return seed(factory, count=count, histories=1)


def _fact(need, *, start, end=None):
    return CallFactVersion(
        need_id=need.id,
        project_id=need.project_id,
        client_id=uuid4(),
        activity_key=need.activity_key,
        facility_scope="Synthetic",
        fact_type="demand",
        value={"mw": "20"},
        reporter_name="Synthetic operator",
        confirmation_channel="call",
        confirmed_at=datetime.now(UTC),
        effective_from=start,
        effective_until=end,
        content_hash=uuid4().hex.ljust(64, "0")[:64],
        recorded_by="Synthetic actor",
    )


def _decision(need_id, fact_id, *, version, expected_version, status):
    return {
        "id": uuid4(),
        "need_id": need_id,
        "fact_version_id": fact_id,
        "version": version,
        "client_id": uuid4(),
        "decision": status,
        "expected_version": expected_version,
        "reason": "Synthetic publication regression",
        "content_hash": uuid4().hex.ljust(64, "0")[:64],
        "actor": "Synthetic tester",
    }


def _state(factory):
    with factory() as session:
        state = session.get(BrowseState, 1)
        return state.input_revision, state.generation_id




def test_initial_draft_batch_is_suppressed_but_mixed_late_draft_is_fenced(publication_db):
    factory = publication_db
    need_ids = _seed(factory, count=4)
    rebuild(factory)
    baseline, _ = _state(factory)
    with factory.begin() as session:
        needs = [session.get(PowerNeed, need_id) for need_id in need_ids]
        facts = [_fact(need, start=datetime.now(UTC) + timedelta(days=7)) for need in needs]
        session.add_all(facts)
        session.flush()
        session.execute(
            insert(CallFactDecision).values(
                [
                    _decision(
                        needs[index].id,
                        facts[index].id,
                        version=1,
                        expected_version=0,
                        status="draft",
                    )
                    for index in range(3)
                ]
            )
        )
    with factory() as session:
        assert session.scalar(select(BrowseState.input_revision)) == baseline
        assert session.scalar(select(func.count()).select_from(BrowseDirtyProject)) == 0

    with factory.begin() as session:
        needs = [session.get(PowerNeed, need_id) for need_id in need_ids]
        late_fact = facts[0]
        initial_fact = _fact(
            needs[3],
            start=datetime.now(UTC) + timedelta(days=8),
        )
        session.add(initial_fact)
        session.flush()
        session.execute(
            insert(CallFactDecision).values(
                [
                    _decision(
                        needs[3].id,
                        initial_fact.id,
                        version=1,
                        expected_version=0,
                        status="draft",
                    ),
                    _decision(
                        needs[0].id,
                        late_fact.id,
                        version=2,
                        expected_version=1,
                        status="draft",
                    ),
                ]
            )
        )
    with factory() as session:
        assert session.scalar(select(BrowseState.input_revision)) == baseline + 1
        assert (
            session.scalar(
                select(BrowseDirtyProject.project_id).where(
                    BrowseDirtyProject.project_id == needs[0].project_id
                )
            )
            == needs[0].project_id
        )


def test_first_draft_per_fact_is_suppressed_but_draft_after_acceptance_is_fenced(
    publication_db,
):
    factory = publication_db
    need_id = _seed(factory)[0]
    rebuild(factory)
    with factory() as session:
        need = session.get(PowerNeed, need_id)

    accepted_fact = _fact(need, start=datetime.now(UTC) + timedelta(days=3))
    with factory.begin() as session:
        session.add(accepted_fact)
        session.flush()
        session.add_all(
            [
                CallFactDecision(
                    **_decision(
                        need_id,
                        accepted_fact.id,
                        version=1,
                        expected_version=0,
                        status="draft",
                    )
                ),
                CallFactDecision(
                    **_decision(
                        need_id,
                        accepted_fact.id,
                        version=2,
                        expected_version=1,
                        status="accepted",
                    )
                ),
            ]
        )
    accepted_revision, _ = _state(factory)
    assert rebuild(factory)["status"] == "published"
    accepted_revision, accepted_generation = _state(factory)

    second_fact = _fact(need, start=datetime.now(UTC) + timedelta(days=4))
    third_fact = _fact(need, start=datetime.now(UTC) + timedelta(days=5))
    with factory.begin() as session:
        session.add_all([second_fact, third_fact])
        session.flush()
        session.add_all(
            [
                CallFactDecision(
                    **_decision(
                        need_id,
                        second_fact.id,
                        version=3,
                        expected_version=2,
                        status="draft",
                    )
                ),
                CallFactDecision(
                    **_decision(
                        need_id,
                        third_fact.id,
                        version=4,
                        expected_version=3,
                        status="draft",
                    )
                ),
            ]
        )
    with factory() as session:
        assert _state(factory) == (accepted_revision, accepted_generation)
        assert (
            session.scalar(
                select(func.count())
                .select_from(BrowseDirtyProject)
                .where(BrowseDirtyProject.project_id == need.project_id)
            )
            == 0
        )

    with factory.begin() as session:
        session.add(
            CallFactDecision(
                **_decision(
                    need_id,
                    second_fact.id,
                    version=5,
                    expected_version=4,
                    status="accepted",
                )
            )
        )
    published_revision, _ = _state(factory)
    assert published_revision == accepted_revision + 1
    with factory() as session:
        assert (
            session.scalar(
                select(BrowseDirtyProject.project_id).where(
                    BrowseDirtyProject.project_id == need.project_id
                )
            )
            == need.project_id
        )

    with factory.begin() as session:
        session.add(
            CallFactDecision(
                **_decision(
                    need_id,
                    accepted_fact.id,
                    version=6,
                    expected_version=5,
                    status="draft",
                )
            )
        )
    hostile_draft_revision, _ = _state(factory)
    assert hostile_draft_revision == published_revision + 1


def test_clock_deadline_uses_only_latest_accepted_fact_intervals(publication_db):
    factory = publication_db
    need_id = _seed(factory)[0]
    rebuild(factory)
    now = datetime(2027, 1, 1, 0, 0, tzinfo=UTC)
    start = now + timedelta(minutes=5)
    end = now + timedelta(minutes=15)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        first = _fact(need, start=start, end=end)
        session.add(first)
        session.flush()
        session.add_all(
            [
                CallFactDecision(
                    **_decision(
                        need.id,
                        first.id,
                        version=1,
                        expected_version=0,
                        status="draft",
                    )
                )
            ]
        )
    with factory() as session:
        assert clock_deadline(session, now) > end

    with factory.begin() as session:
        session.add(
            CallFactDecision(
                **_decision(
                    need_id,
                    first.id,
                    version=2,
                    expected_version=1,
                    status="accepted",
                )
            )
        )
    with factory() as session:
        assert clock_deadline(session, now) == start

    with factory.begin() as session:
        session.add(
            CallFactDecision(
                **_decision(
                    need_id,
                    first.id,
                    version=3,
                    expected_version=2,
                    status="retracted",
                )
            )
        )
        need = session.get(PowerNeed, need_id)
        second = _fact(need, start=now - timedelta(hours=1), end=end)
        session.add(second)
        session.flush()
        session.add(
            CallFactDecision(
                **_decision(
                    need_id,
                    second.id,
                    version=4,
                    expected_version=3,
                    status="accepted",
                )
            )
        )
    with factory() as session:
        assert clock_deadline(session, start + timedelta(seconds=1)) == end


def test_fact_updates_deletes_and_truncates_still_invalidate(publication_db):
    factory = publication_db
    need_id = _seed(factory)[0]
    rebuild(factory)
    baseline, _ = _state(factory)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        fact = _fact(need, start=datetime.now(UTC))
        session.add(fact)
        session.flush()
        decision = CallFactDecision(
            **_decision(need.id, fact.id, version=1, expected_version=0, status="draft")
        )
        session.add(decision)
    with factory() as session:
        assert session.scalar(select(BrowseState.input_revision)) == baseline

    operations = [
        f"UPDATE call_fact_versions SET source_reference = 'updated' WHERE id = '{fact.id}'",
        f"UPDATE call_fact_decisions SET reason = 'updated' WHERE id = '{decision.id}'",
        f"DELETE FROM call_fact_decisions WHERE id = '{decision.id}'",
        f"DELETE FROM call_fact_versions WHERE id = '{fact.id}'",
    ]
    expected_revision = baseline
    for statement in operations:
        with factory.begin() as session:
            session.execute(text(statement))
        expected_revision += 1
        with factory() as session:
            assert session.scalar(select(BrowseState.input_revision)) == expected_revision

    with factory.begin() as session:
        session.execute(text("TRUNCATE call_fact_decisions"))
    expected_revision += 1
    with factory() as session:
        assert session.scalar(select(BrowseState.input_revision)) == expected_revision
    with factory.begin() as session:
        session.execute(text("TRUNCATE call_fact_decisions, call_fact_versions"))
    expected_revision += 2
    with factory() as session:
        assert session.scalar(select(BrowseState.input_revision)) == expected_revision
