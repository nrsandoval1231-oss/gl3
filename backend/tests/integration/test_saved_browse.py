"""Disposable PostgreSQL parity and publication safety; no external calls."""

from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.saved_browse import current_generation, page, rebuild
from gridlens.persistence.browse_invalidation import INPUT_TABLES, install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseState,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

api = import_module("gridlens.api.app")


@pytest.fixture
def saved_db(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL generation tests")
    database = make_url(settings.test_database_url).database
    assert database and database.endswith("_test") and "corpus" not in database.lower(), (
        "An explicit disposable *_test database is required"
    )
    schema = "b1_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
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


def seed(factory, count=4, histories=3):
    ids = []
    with factory.begin() as session:
        session.add(
            Source(
                id="synthetic-permits",
                publisher="Synthetic",
                endpoint="https://example.test",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        for index in range(count):
            pid, nid = uuid4(), uuid4()
            ids.append(nid)
            session.add(
                Project(
                    id=pid,
                    identity_key=f"site-{index}",
                    name=f"Synthetic {index}",
                    location="Dallas, TX" if index % 2 else "California",
                    source_id="synthetic-permits",
                    external_id=str(index),
                )
            )
            session.flush()
            session.add(
                PowerNeed(
                    id=nid,
                    project_id=pid,
                    activity_key="construction",
                    tier="Signal",
                    rationale="Synthetic only",
                    supply="Unknown",
                    active=True,
                )
            )
            session.flush()
            for history in range(histories):
                oid, eid = uuid4(), uuid4()
                fingerprint = f"{index * histories + history:064x}"
                session.add(
                    Observation(
                        id=oid,
                        source_id="synthetic-permits",
                        external_id=f"{index}-{history}",
                        title=f"Synthetic {index}",
                        abstract="Synthetic construction permit.",
                        url=f"https://example.test/{oid}",
                        content_hash=fingerprint,
                        published_at=date(2026, 10, 15),
                    )
                )
                session.flush()
                session.add(
                    Evidence(
                        id=eid,
                        observation_id=oid,
                        content_hash=fingerprint,
                        title=f"Synthetic {index}",
                        abstract=f"Ｆｕｌｌ history {history} cross field",
                        url=f"https://example.test/{oid}",
                        published_at=date(2026, 10, 15),
                        observed_at=datetime.now(UTC) - timedelta(days=history),
                        extraction_location="Synthetic",
                    )
                )
                session.add(
                    Interpretation(
                        observation_id=oid,
                        content_hash=fingerprint,
                        evaluator_version="fixture",
                        status="accepted",
                        assessment={
                            "semantic_hash": fingerprint,
                            "evidence_hash": fingerprint,
                            "project_identity_key": f"site-{index}",
                            "power_activity": "construction",
                            "decision": "accepted",
                            "subject": f"Synthetic {index}",
                            "location": "Dallas, TX",
                        },
                    )
                )
                session.add(NeedObservation(need_id=nid, observation_id=oid))
    return ids


def filters(**changes):
    return api._normalized_browse_filters(
        **{
            **dict.fromkeys(
                (
                    "tier",
                    "search",
                    "decision",
                    "geography",
                    "industry",
                    "activity",
                    "timing",
                    "mw_status",
                    "mw_min",
                    "mw_max",
                    "priority_segment",
                    "status",
                )
            ),
            **changes,
        }
    )


def test_build_saved_page_matches_canonical_and_does_no_evidence_reads(saved_db, monkeypatch):
    seed(saved_db)
    baseline_response = Response()
    expected = api.opportunities(
        response=baseline_response, sort="rank", limit=50, offset=0, cohort=None
    )
    assert len(expected) == 4
    result = rebuild(saved_db)
    assert result["status"] == "published"
    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(saved_db.kw["bind"], "before_cursor_execute", capture)
    try:
        monkeypatch.setattr(settings, "saved_browse_enabled", True)
        response = Response()
        actual = api.opportunities(response=response, sort="rank", limit=50, offset=0, cohort=None)
    finally:
        event.remove(saved_db.kw["bind"], "before_cursor_execute", capture)
    assert [str(row["id"]) for row in actual] == [str(row["id"]) for row in expected]
    for actual_row, expected_row in zip(actual, expected, strict=True):
        for field in (
            "tier",
            "required_mw",
            "rank_score",
            "rank_reasons",
            "rank_version",
            "group_id",
            "group_title",
            "group_total_filtered",
            "priority_segment",
        ):
            assert actual_row[field] == expected_row[field], field
    assert response.headers["x-total-count"] == baseline_response.headers["x-total-count"]
    assert not any(
        "FROM evidence" in statement or "JOIN evidence" in statement for statement in statements
    )
    assert len(statements) <= 5


@pytest.mark.parametrize(
    "query", ["full history 2", "cross field", "synthetic 1", "%", "missing", ""]
)
def test_exact_historical_search(saved_db, query):
    seed(saved_db)
    expected = api.opportunities(search=query, limit=50, offset=0, cohort=None)
    rebuild(saved_db)
    with saved_db() as session:
        actual = page(session, filters(search=query))["items"]
    assert [str(row["id"]) for row in actual] == [str(row["id"]) for row in expected]


def test_committed_mutation_blocks_stale_generation_but_rollback_does_not(saved_db):
    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        before = current_generation(session).id
        session.execute(text("UPDATE projects SET name = name"))
        session.rollback()
    with saved_db() as session:
        assert current_generation(session).id == before
    with saved_db.begin() as session:
        session.execute(text("UPDATE projects SET name = name"))
    with saved_db() as session, pytest.raises(HTTPException) as exc:
        current_generation(session)
    assert exc.value.status_code == 503
    assert "pending" in exc.value.detail


def test_concurrent_input_change_prevents_publication_and_restart_recovers(saved_db):
    seed(saved_db)

    def mutate():
        with saved_db.begin() as session:
            session.execute(text("UPDATE power_needs SET rationale = 'Changed fixture'"))

    assert rebuild(saved_db, before_publish=mutate)["status"] == "superseded"
    with saved_db() as session:
        assert session.get(BrowseState, 1).generation_id is None
    assert rebuild(saved_db)["status"] == "published"


def test_all_declared_input_tables_have_transactional_statement_triggers(saved_db):
    with saved_db() as session:
        tables = session.scalars(
            text("""
            SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=current_schema() AND t.tgname='invalidate_browse'
        """)
        ).all()
        assert set(tables) == set(INPUT_TABLES)
        # Exercise every table without creating/deleting canonical evidence.
        revision = session.scalar(select(BrowseState.input_revision))
        for table in INPUT_TABLES:
            session.execute(text(f"DELETE FROM {table} WHERE false"))
        assert session.scalar(select(BrowseState.input_revision)) == revision + len(INPUT_TABLES)
        session.rollback()


def test_long_history_can_publish_compact_browse_but_detail_stays_bounded(saved_db, monkeypatch):
    ids = seed(saved_db, count=1, histories=501)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db() as session:
        saved = page(session, filters())["items"]
    assert len(saved) == 1
    assert saved[0]["evidence_count"] == 501
    assert saved[0]["evidence"] == []
    with pytest.raises(HTTPException) as exc:
        api.opportunity_need_detail(ids[0])
    assert exc.value.status_code == 413


@pytest.mark.parametrize(
    "selection",
    [
        {"tier": "Signal"},
        {"tier": "Lead"},
        {"geography": "California"},
        {"geography": "UNKNOWN"},
        {"industry": "UNKNOWN"},
        {"industry": "construction"},
        {"activity": "construction"},
        {"activity": "UNKNOWN"},
        {"timing": "UNKNOWN"},
        {"timing": "KNOWN"},
        {"mw_status": "UNKNOWN"},
        {"mw_min": "0.3"},
        {"mw_min": "1e1000000"},
        {"mw_max": "1e1000000"},
        {"mw_min": "1e-1000000"},
        {"mw_max": "1e-1000000"},
        {"priority_segment": "8"},
        {"status": "UNKNOWN"},
        {"tier": "Signal", "decision": "REVIEW", "search": "full history"},
    ],
)
def test_saved_filter_and_rank_parity(saved_db, selection):
    seed(saved_db)
    expected_response = Response()
    expected = api.opportunities(
        **selection, response=expected_response, sort="rank", limit=50, offset=0, cohort=None
    )
    rebuild(saved_db)
    with saved_db() as session:
        actual = page(session, filters(**selection), ranked=True)
    assert [str(row["id"]) for row in actual["items"]] == [str(row["id"]) for row in expected]
    assert actual["total_count"] == int(expected_response.headers["x-total-count"])
    assert actual["group_total_count"] == int(expected_response.headers["x-group-total-count"])


def test_group_membership_is_recomputed_after_activity_filter(saved_db):
    ids = seed(saved_db, count=1)
    with saved_db.begin() as session:
        original = session.get(PowerNeed, ids[0])
        sibling = PowerNeed(
            project_id=original.project_id,
            activity_key="operations",
            tier="Signal",
            rationale="Fixture",
            supply="Unknown",
        )
        session.add(sibling)
    rebuild(saved_db)
    for selection in (
        {},
        {"activity": "construction"},
        {"activity": "operations"},
        {"search": "full history 2"},
    ):
        expected = api.opportunities(**selection, limit=50, offset=0, cohort=None)
        with saved_db() as session:
            actual = page(session, filters(**selection))["items"]
        assert [
            (str(row["id"]), row["group_id"], row["group_total_filtered"]) for row in actual
        ] == [(str(row["id"]), row["group_id"], row["group_total_filtered"]) for row in expected]


def test_exact_fact_boundary_and_policy_expiry_fail_closed(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration, CallFactVersion

    ids = seed(saved_db, count=1)
    boundary = datetime.now(UTC) + timedelta(minutes=5)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        session.add(
            CallFactVersion(
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
                effective_from=boundary,
                content_hash="a" * 64,
                recorded_by="Synthetic actor",
            )
        )
    rebuild(saved_db)
    with saved_db() as session:
        generation = current_generation(session)
        assert generation.valid_until == boundary
        with pytest.raises(HTTPException):
            current_generation(session, now=boundary)
        assert (
            session.scalar(select(BrowseGeneration)).policy_version == saved_browse.POLICY_VERSION
        )
    monkeypatch.setattr(saved_browse, "POLICY_VERSION", "changed-policy")
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_failed_build_preserves_current_generation_and_rolls_back_rows(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db, count=1)
    first = rebuild(saved_db)

    def fail(*args):
        raise RuntimeError("Synthetic build interruption")

    monkeypatch.setattr(saved_browse, "_search_texts", fail)
    with pytest.raises(RuntimeError, match="Synthetic build interruption"):
        rebuild(saved_db)
    with saved_db() as session:
        assert str(current_generation(session).id) == first["generation_id"]
        assert len(session.scalars(select(BrowseGeneration)).all()) == 1


def test_competing_builder_is_excluded_without_input_or_pointer_changes(saved_db):
    from sqlalchemy import func

    from gridlens.intelligence.saved_browse import BUILD_LOCK

    with saved_db() as owner:
        assert owner.scalar(select(func.pg_try_advisory_lock(BUILD_LOCK)))
        try:
            assert rebuild(saved_db) == {"status": "busy"}
        finally:
            owner.execute(select(func.pg_advisory_unlock(BUILD_LOCK)))


def test_retention_and_safe_generation_rollback(saved_db):
    from uuid import UUID

    from gridlens.intelligence.saved_browse import restore_generation
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db, count=1)
    generations = [rebuild(saved_db)["generation_id"] for _ in range(4)]
    with saved_db() as session:
        assert len(session.scalars(select(BrowseGeneration)).all()) == 3
    assert not restore_generation(saved_db, UUID(generations[0]))
    assert restore_generation(saved_db, UUID(generations[1]))
    with saved_db.begin() as session:
        session.execute(text("UPDATE power_needs SET rationale='Changed fixture'"))
    assert not restore_generation(saved_db, UUID(generations[2]))


def test_clock_boundary_crossed_during_build_cannot_publish(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db, count=1)
    monkeypatch.setattr(
        saved_browse, "clock_deadline", lambda session, now: now + timedelta(microseconds=1)
    )
    assert rebuild(saved_db)["status"] == "superseded"
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_map_group_detail_and_export_accept_saved_tokens(saved_db, monkeypatch):
    seed(saved_db, count=3)
    canonical = api.opportunity_map_window(tier="Signal")
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    saved = api.opportunity_map_window(tier="Signal")
    assert [str(row["id"]) for row in saved["items"]] == [
        str(row["id"]) for row in canonical["items"]
    ]
    assert "summaries" not in saved
    assert saved["items"][0]["evidence"] == []
    item = saved["items"][0]
    group = api.opportunity_group_page(
        item["group_id"], saved["cohort_token"], tier="Signal", limit=50, offset=0
    )
    assert group["items"][0]["id"] == item["id"]
    empty_page = api.opportunity_group_page(
        item["group_id"], saved["cohort_token"], tier="Signal", limit=50, offset=999
    )
    assert empty_page["items"] == []
    assert empty_page["total"] == group["total"]
    from uuid import UUID

    detail = api.opportunity_need_detail(
        UUID(str(item["id"])), tier="Signal", cohort_token=saved["cohort_token"]
    )
    assert len(detail["evidence"]) == 3
    exported = api.export_opportunities_csv(
        tier="Signal", cohort_token=saved["cohort_token"], limit=500
    )
    assert exported.headers["x-total-count"] == "3"
    with saved_db.begin() as session:
        session.execute(text("UPDATE projects SET name='Changed fixture'"))
    with pytest.raises(HTTPException) as exc:
        api.opportunity_map_window(tier="Signal")
    assert exc.value.status_code == 503


def test_unscoped_detail_keeps_canonical_priority_metadata(saved_db, monkeypatch):
    ids = seed(saved_db, count=1)
    expected = api.opportunity_need_detail(ids[0])
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    actual = api.opportunity_need_detail(ids[0])
    for key in ("priority_segment", "priority_label", "workflow_status", "tier", "rank_score"):
        assert actual[key] == expected[key]


@pytest.mark.parametrize(
    "selection",
    [
        {"mw_min": "1e1000000"},
        {"mw_max": "1e1000000"},
        {"mw_min": "1e-1000000"},
        {"mw_max": "1e-1000000"},
    ],
)
def test_extreme_bounds_match_decimal_comparisons_for_known_and_zero_ranges(saved_db, selection):
    from decimal import Decimal

    from gridlens.persistence.models import BrowseRow

    seed(saved_db, count=3)
    rebuild(saved_db)
    canonical = []
    # Test the SQL filter against canonical interval arithmetic independently of
    # qualification. Zero lower bounds can occur in visible uncertain ranges.
    with saved_db.begin() as session:
        rows = session.scalars(select(BrowseRow).order_by(BrowseRow.need_id)).all()
        for row, interval in zip(rows, ("0 to 2 MW", "1 to 3 MW", None), strict=True):
            parsed = api.exact_mw_interval(interval)
            row.mw_low = parsed[0] if parsed else None
            row.mw_high = parsed[1] if parsed else None
            canonical.append({"id": str(row.need_id), "required_mw": interval})
        assert rows[0].mw_low == Decimal("0")
    selected_filters = filters(**selection)
    expected = api._filter_opportunity_summaries(canonical, selected_filters)
    with saved_db() as session:
        actual = page(session, selected_filters)["items"]
    assert {row["id"] for row in actual} == {row["id"] for row in expected}


@pytest.mark.parametrize("selection", [{}, {"search": "full history"}])
def test_offset_beyond_database_integer_range_is_a_valid_empty_page(saved_db, selection):
    seed(saved_db, count=1)
    rebuild(saved_db)
    with saved_db() as session:
        result = page(session, filters(**selection), offset=10**100)
    assert result["items"] == []
    assert result["total_count"] == 1
