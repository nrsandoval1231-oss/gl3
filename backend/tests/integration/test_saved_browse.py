"""Disposable PostgreSQL parity and publication safety; no external calls."""

from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

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
            session.execute(text("UPDATE sources SET publisher = 'Changed fixture'"))

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
        # Note row DML is live-only; its TRUNCATE trigger remains conservative.
        assert (
            session.scalar(select(BrowseState.input_revision)) == revision + len(INPUT_TABLES) - 1
        )
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
        assert generation.valid_until == saved_browse.clock_deadline(session, generation.built_at)
        assert generation.valid_until <= boundary
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


def test_incremental_refresh_is_atomic_and_rebuilds_only_dirty_project(saved_db, monkeypatch):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        original = current_generation(reader).id
    calls = []
    canonical = api.opportunity_projection

    def track(session, **kwargs):
        calls.append(kwargs.get("selected_need_ids"))
        return canonical(session, **kwargs)

    monkeypatch.setattr(api, "opportunity_projection", track)
    with saved_db.begin() as writer:
        need = writer.get(PowerNeed, ids[0])
        need.active = False
        writer.flush()
        result = refresh_project_changes(writer)
        assert result["mode"] == "projects"
        assert result["needs"] == 1
        with saved_db() as reader:
            assert current_generation(reader).id == original
            assert len(page(reader, filters())["items"]) == len(ids)
    assert calls and all(value == {ids[0]} for value in calls)
    with saved_db() as reader:
        assert current_generation(reader).id != original
        assert str(ids[0]) not in {str(item["id"]) for item in page(reader, filters())["items"]}
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    baseline = api.opportunities(limit=50, offset=0, cohort=None)
    with saved_db() as reader:
        actual = page(reader, filters())["items"]
    assert [str(item["id"]) for item in actual] == [str(item["id"]) for item in baseline]


def test_incremental_rollback_unknown_write_and_expiry_fail_closed(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        original = current_generation(reader).id
    with saved_db() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
        writer.rollback()
    with saved_db() as reader:
        assert current_generation(reader).id == original
    with saved_db.begin() as writer:
        writer.execute(text("UPDATE sources SET publisher = publisher"))
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)
    rebuild(saved_db)
    with saved_db.begin() as writer:
        generation = current_generation(writer)
        generation.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)
    with saved_db() as reader:
        assert reader.scalar(select(BrowseGeneration.id).limit(1)) is not None


def test_multiple_refreshes_in_one_transaction_keep_latest_revision(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
        writer.get(PowerNeed, ids[1]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
    with saved_db() as reader:
        assert len(page(reader, filters())["items"]) == len(ids) - 2


def test_failed_derived_refresh_retains_canonical_change_as_pending(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    ids = seed(saved_db)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic derived failure")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        api._refresh_saved_operator_change(writer)
    with saved_db() as reader:
        assert reader.get(PowerNeed, ids[0]).active is False
        with pytest.raises(HTTPException):
            current_generation(reader)
    monkeypatch.undo()
    assert rebuild(saved_db)["status"] == "published"


def test_incremental_expiring_during_construction_never_serves_current(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    canonical = saved_browse._write_rows

    def cross_boundary(session, generation_id, summaries):
        result = canonical(session, generation_id, summaries)
        after_deadline = session.get(BrowseGeneration, generation_id).valid_until + timedelta(
            seconds=1
        )

        class AdvancedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return after_deadline

        monkeypatch.setattr(saved_browse, "datetime", AdvancedClock)
        return result

    monkeypatch.setattr(saved_browse, "_write_rows", cross_boundary)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert saved_browse.refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)


def test_full_build_rebases_repeated_scoped_writes_before_publication(saved_db):
    ids = seed(saved_db)

    def repeated_writes():
        for index in range(8):
            with saved_db.begin() as writer:
                writer.get(PowerNeed, ids[index % len(ids)]).active = False

    result = rebuild(saved_db, before_publish=repeated_writes)
    assert result["status"] == "published"
    assert result["row_count"] == 0
    with saved_db() as reader:
        assert (
            current_generation(reader).input_revision == reader.get(BrowseState, 1).input_revision
        )
        assert not page(reader, filters())["items"]


def test_full_build_rebase_keeps_concurrent_already_published_operator_edit(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)

    def atomic_operator_write():
        with saved_db.begin() as writer:
            writer.get(PowerNeed, ids[0]).active = False
            assert refresh_project_changes(writer)["status"] == "published"

    assert rebuild(saved_db, before_publish=atomic_operator_write)["status"] == "published"
    with saved_db() as reader:
        assert str(ids[0]) not in {str(item["id"]) for item in page(reader, filters())["items"]}
        current_generation(reader)


def test_long_repeatable_read_cohort_survives_pruning_without_blocking_writers(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        api._begin_consistent_read(reader)
        original = current_generation(reader).id
        for need_id in ids:
            with saved_db.begin() as writer:
                writer.get(PowerNeed, need_id).active = False
                assert refresh_project_changes(writer)["status"] == "published"
        assert current_generation(reader).id == original
        assert len(page(reader, filters())["items"]) == len(ids)
        with saved_db() as fresh:
            assert not page(fresh, filters())["items"]
            assert fresh.get(BrowseGeneration, original) is None


def test_expiry_without_preparation_has_explicit_pending_window(saved_db):
    seed(saved_db, count=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        deadline = current_generation(session).valid_until
        with pytest.raises(HTTPException) as failure:
            current_generation(session, now=deadline)
        assert failure.value.status_code == 503
        assert failure.value.headers["X-Qualification-State"] == "pending"


def test_prepared_clock_snapshot_is_not_early_and_matches_future_canonical(saved_db, monkeypatch):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence.saved_browse import prepare_next, restore_generation
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        old = current_generation(session)
        boundary = old.valid_until
        old_id = old.id
    assert prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        prepared_id = state.prepared_generation_id
        prepared = session.get(BrowseGeneration, prepared_id)
        assert prepared.valid_from == boundary
        assert prepared.built_at < boundary
        assert current_generation(session, now=boundary - timedelta(microseconds=1)).id == old_id
        assert current_generation(session, now=boundary).id == prepared_id
        with pytest.raises(HTTPException):
            current_generation(session, now=prepared.valid_until)
    assert not restore_generation(saved_db, prepared_id)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    with evaluate_at(boundary):
        expected = api.opportunities(limit=50, offset=0, cohort=None, sort="rank")
    # Simulate only the reader's real clock at B; canonical future evaluation has
    # already completed and is no longer active in this thread.
    from gridlens.intelligence import saved_browse

    class AtBoundary(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", AtBoundary)
    with saved_db() as session:
        actual = page(session, filters(), ranked=True)["items"]
    for left, right in zip(actual, expected, strict=True):
        for field in ("id", "tier", "required_mw", "rank_score", "rank_reasons", "group_id"):
            assert str(left[field]) == str(right[field]), field


def test_preparation_write_race_discard_and_rollback_safety(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next

    ids = seed(saved_db)
    rebuild(saved_db)

    def mutate():
        with saved_db.begin() as writer:
            writer.get(PowerNeed, ids[0]).active = False

    assert (
        prepare_next(saved_db, lead_seconds=90000, before_publish=mutate)["status"] == "superseded"
    )
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session)
    rebuild(saved_db)
    assert prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as writer:
        writer.execute(text("UPDATE sources SET publisher=publisher"))
        writer.rollback()
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is not None
    with saved_db.begin() as writer:
        writer.execute(text("UPDATE sources SET publisher=publisher"))
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session)


def test_boundary_write_promotes_ready_base_before_invalidation(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next, refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    # Simulate wall time reaching the candidate interval in persisted metadata;
    # the PostgreSQL trigger uses real database time, not a Python test clock.
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        old = session.get(BrowseGeneration, state.generation_id)
        ready = session.get(BrowseGeneration, state.prepared_generation_id)
        old.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        ready.valid_from = datetime.now(UTC) - timedelta(seconds=1)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        result = refresh_project_changes(writer)
        assert result["mode"] == "projects"
    with saved_db() as reader:
        assert str(ids[0]) not in {str(row["id"]) for row in page(reader, filters())["items"]}
        assert reader.get(BrowseState, 1).prepared_generation_id is None


def test_preparation_failure_and_policy_mismatch_fail_closed(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        old = current_generation(session).id
        boundary = current_generation(session).valid_until
    original = saved_browse._write_rows

    def fail(*args):
        raise RuntimeError("synthetic preparation failure")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with pytest.raises(RuntimeError):
        saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        assert current_generation(session).id == old
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session, now=boundary)
    monkeypatch.setattr(saved_browse, "_write_rows", original)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    monkeypatch.setattr(saved_browse, "POLICY_VERSION", "different-runtime")
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session, now=boundary)


def test_prepared_pointer_survives_pruning_and_new_pool_restart(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        prepared_id = session.get(BrowseState, 1).prepared_generation_id
        boundary = session.get(BrowseGeneration, prepared_id).valid_from
    for _ in range(4):
        assert rebuild(saved_db)["status"] == "published"
    saved_db.kw["bind"].dispose()
    with saved_db() as restarted:
        assert current_generation(restarted, now=boundary).id == prepared_id
        assert restarted.get(BrowseGeneration, prepared_id) is not None


def test_future_fact_start_and_end_use_same_prepared_instant(saved_db, monkeypatch):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.ingestion.service import load_current_need_operator_inputs
    from gridlens.intelligence import saved_browse
    from gridlens.intelligence.saved_browse import prepare_next
    from gridlens.persistence.models import CallFactDecision, CallFactVersion

    fixed = datetime(2026, 10, 18, 12, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    ids = seed(saved_db, count=1)
    start = fixed + timedelta(minutes=10)
    end = start + timedelta(minutes=10)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        fact = CallFactVersion(
            need_id=need.id,
            project_id=need.project_id,
            client_id=uuid4(),
            activity_key=need.activity_key,
            facility_scope="California",
            fact_type="demand",
            value={"mw": "20"},
            reporter_name="Synthetic",
            confirmation_channel="call",
            confirmed_at=datetime.now(UTC),
            effective_from=start,
            effective_until=end,
            content_hash="e" * 64,
            recorded_by="Synthetic",
        )
        session.add(fact)
        session.flush()
        session.add(
            CallFactDecision(
                need_id=need.id,
                fact_version_id=fact.id,
                version=1,
                client_id=uuid4(),
                decision="accepted",
                expected_version=0,
                reason="Synthetic",
                content_hash="d" * 64,
                actor="Synthetic",
            )
        )
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        with evaluate_at(fixed):
            before, _ = load_current_need_operator_inputs(session, ids)
            assert not before
        with evaluate_at(start):
            after, _ = load_current_need_operator_inputs(session, ids)
            assert len(after[ids[0]]) == 1
        with evaluate_at(end):
            expired, _ = load_current_need_operator_inputs(session, ids)
            assert not expired
        candidate = current_generation(session, now=start)
        assert candidate.valid_from == start
        assert candidate.valid_until == end


def test_prepared_boundary_adds_and_expires_real_qualified_lead(saved_db, monkeypatch):
    """Retained official clauses + accepted exact-need facts change qualification."""
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import CallFactDecision, CallFactVersion

    ids = seed(saved_db, count=1, histories=1)
    boundary = datetime(2027, 1, 1, 0, tzinfo=UTC)
    instant = boundary - timedelta(minutes=10)
    expiry = datetime(2027, 3, 4, 0, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        project = session.get(Project, need.project_id)
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        observation.abstract = evidence.abstract = (
            "description: California construction requires 20 to 25 MW. "
            "Power supply for California construction is insufficient.\naddress: California"
        )
        observation.published_at = evidence.published_at = instant.date()
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
            "project_identity_key": project.identity_key,
            "power_activity": "construction",
            "tier": "Prospect",
            "demand_mw": "20 to 25 MW",
            "demand_quote": "California construction requires 20 to 25 MW.",
            "supply_quote": "Power supply for California construction is insufficient.",
            "reason": "Current retained exact-site permit support.",
            "subject": project.name,
            "location": project.location,
        }
        values = [
            ("timing", {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31}),
            ("suitable_supply", {"mw": "5", "quality": "suitable"}),
            ("buyer", {"organization": "Synthetic Owner", "role": "project owner"}),
        ]
        for index, (kind, value) in enumerate(values):
            fact = CallFactVersion(
                need_id=need.id,
                project_id=project.id,
                client_id=uuid4(),
                activity_key=need.activity_key,
                facility_scope=project.location,
                fact_type=kind,
                value=value,
                reporter_name="Synthetic",
                confirmation_channel="customer_call",
                confirmed_at=instant,
                effective_from=boundary,
                effective_until=expiry,
                content_hash=str(index) * 64,
                recorded_by="Synthetic",
            )
            session.add(fact)
            session.flush()
            session.add(
                CallFactDecision(
                    need_id=need.id,
                    fact_version_id=fact.id,
                    version=index + 1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=index,
                    reason="Synthetic exact-need accepted fact",
                    content_hash=str(index + 3) * 64,
                    actor="Synthetic",
                )
            )
    rebuild(saved_db)
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Prospect"
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    instant = boundary
    with saved_db() as session:
        lead = page(session, filters())["items"][0]
        assert lead["tier"] == "Lead"
        assert lead["required_mw"] == "20 to 25 MW"
    # Move through the later calendar intervals using normal rebuilds, then
    # prepare the exact accepted-fact expiry. Expired facts cannot carry a Lead.
    instant = expiry - timedelta(minutes=10)
    rebuild(saved_db)
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Lead"
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    instant = expiry
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Prospect"


def test_maintenance_promotes_persisted_preparation_without_rebuild(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
        prepared_id = session.get(BrowseState, 1).prepared_generation_id

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", Clock)

    def unexpected_build(*args):
        raise AssertionError("promotion must not reconstruct canonical rows")

    monkeypatch.setattr(saved_browse, "_write_rows", unexpected_build)
    assert saved_browse.maintain_once(saved_db)["status"] == "current"
    with saved_db() as restarted:
        state = restarted.get(BrowseState, 1)
        assert state.generation_id == prepared_id
        assert state.prepared_generation_id is None
        assert current_generation(restarted).id == prepared_id


def test_preparing_subsequent_interval_preserves_now_effective_preparation(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
        prepared_id = session.get(BrowseState, 1).prepared_generation_id

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.generation_id == prepared_id
        assert state.prepared_generation_id != prepared_id
        assert current_generation(session).id == prepared_id


def test_incremental_refresh_never_blesses_future_base_if_clocks_disagree(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next, refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    # Simulate DB-clock-ahead promotion while application time is still before B.
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        state.generation_id = state.prepared_generation_id
        state.prepared_generation_id = None
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)


def test_saved_commercial_page_avoids_population_projection(saved_db, monkeypatch):
    """Saved selection must keep the canonical cards without replaying all summaries."""
    factory = saved_db
    ids = seed(factory, count=6, histories=3)
    with factory.begin() as session:
        for index, need_id in enumerate(ids):
            project = session.get(Project, session.get(PowerNeed, need_id).project_id)
            project.location = f"{index} Synthetic Road, Dallas, TX"
    with factory() as session:
        expected = api._commercial_triage_payload(session, 2, 2)
    assert rebuild(factory)["status"] == "published"
    original = api.opportunity_projection

    def targeted_only(session, *, summary_only=False, **kwargs):
        assert not summary_only, "pursuits replayed population canonical summaries"
        assert kwargs.get("selected_need_ids") is not None
        return original(session, **kwargs)

    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    monkeypatch.setattr(api, "opportunity_projection", targeted_only)
    actual = api.commercial_triage(limit=2, offset=2)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected


def test_commercial_selection_matches_canonical_complete_group_priority(saved_db):
    """Tuple minima, Austin cross-project work, UUID ties and all page offsets."""
    from gridlens.domain.commercial_triage import (
        _priority,
        grouped_need_groups,
        work_group_identity,
    )
    from gridlens.intelligence.saved_browse import commercial_selection
    from gridlens.persistence.models import BrowseRow

    factory = saved_db
    seed(factory, count=8, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        generation = current_generation(session)
        rows = list(
            session.scalars(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        )
        items = []
        for index, row in enumerate(rows):
            item = {
                "id": row.need_id,
                "project_id": row.project_id,
                "name": "Synthetic data center" if index % 2 else "Synthetic oil well",
                "location": "100 Synthetic Road, Dallas, TX"
                if index < 3
                else f"{index} Austin, TX",
                "activity": "construction",
                "asset_type": "data_center" if index % 2 else None,
                "_priority_features": {
                    "latest_date": "2026-10-31" if index == 2 else (
                        "2026-10-10" if index >= 5 else f"2026-10-{index + 1:02}"
                    ),
                    "evidence_construction": True,
                },
                "evidence": [
                    {
                        "source_id": "austin-building-permits",
                        "document_number": "2026-123456 BP" if index % 2 else "2026-123456 EP",
                        "assessment_current": True,
                    }
                ],
            }
            if index == 2:
                item["evidence"].insert(0, {"source_id": "stale", "assessment_current": False})
            priority = _priority(item)
            row.commercial_group = work_group_identity(item)
            row.commercial_segment, row.commercial_geography, row.commercial_date = priority[:3]
            items.append(item)
        # A non-Signal must not enter commercial groups even if it ranks first.
        rows[4].tier = "Lead"
        items = [item for item in items if item["id"] != rows[4].need_id]
    expected = grouped_need_groups(items)
    assert any(len(members) == 3 for _identity, members in expected)
    for limit, offset in ((1, 0), (2, 1), (50, 0), (2, len(expected)), (2, 10_000), (2, 10**100)):
        with factory() as session:
            groups, projects, total = commercial_selection(session, limit, offset)
        assert groups == expected[offset : offset + limit]
        assert total == len(expected)
        assert set(projects) == {UUID(need) for _, group in groups for need in group}


def test_commercial_saved_selection_pending_and_write_callers_remain_canonical(
    saved_db, monkeypatch
):
    factory = saved_db
    ids = seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory.begin() as session:
        session.get(Project, session.get(PowerNeed, ids[0]).project_id).name = "Corrected synthetic"
    with factory() as session, pytest.raises(HTTPException) as caught:
        api._commercial_triage_payload(session, 50, saved_selection=True)
    assert caught.value.status_code == 503
    with factory() as session:
        cards = api._commercial_triage_cards(session, 50)
    assert any(card["name"] == "Corrected synthetic" for card in cards)


def test_saved_commercial_group_budget_keeps_all_members(saved_db, monkeypatch):
    factory = saved_db
    ids = seed(factory, count=52, histories=1)
    from gridlens.domain.commercial_triage import grouped_need_groups

    with factory.begin() as session:
        session.execute(
            text("UPDATE projects SET location = '100 Synthetic Test Road, Dallas, TX'")
        )
        session.get(
            Project, session.get(PowerNeed, ids[-1]).project_id
        ).location = "Other synthetic site"
    with factory() as session:
        groups = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
    large_offset = next(i for i, (_key, group) in enumerate(groups) if len(group) == 51)
    small_offset = 1 - large_offset
    with factory() as session, pytest.raises(HTTPException) as canonical:
        api._commercial_triage_page(session, 1, large_offset)
    assert canonical.value.status_code == 413
    assert canonical.value.detail["group_member_count"] == 51
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory() as session, pytest.raises(HTTPException) as saved:
        api._commercial_triage_page(session, 1, large_offset, saved_selection=True)
    assert saved.value.detail == canonical.value.detail
    with factory() as session:
        canonical_cards = api._commercial_triage_page(session, 1, small_offset)
        saved_cards = api._commercial_triage_page(session, 1, small_offset, saved_selection=True)
    assert saved_cards == canonical_cards


def test_commercial_scalar_selection_refreshes_transactionally(saved_db):
    from gridlens.domain.commercial_triage import grouped_need_groups
    from gridlens.intelligence.saved_browse import commercial_selection, refresh_project_changes

    factory = saved_db
    ids = seed(factory, count=4, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        session.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(session)["status"] == "published"
        expected = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
        actual, _projects, total = commercial_selection(session, 50, 0)
        assert actual == expected
        assert total == len(expected)
    # Restart/read from a new session; no prepared data or Python cache is required.
    with factory() as session:
        actual, _projects, total = commercial_selection(session, 50, 0)
    assert actual == expected
    assert total == len(expected)


def test_commercial_prepared_generation_retains_exact_group_selection(saved_db, monkeypatch):
    from gridlens.domain.commercial_triage import grouped_need_groups
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence import saved_browse as browse

    factory = saved_db
    seed(factory, count=4, histories=2)
    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        boundary = current_generation(session).valid_until
    assert rebuild(factory, _prepare_at=boundary)["status"] == "prepared"

    class AtBoundary(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(browse, "datetime", AtBoundary)
    with factory() as session, evaluate_at(boundary):
        expected = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
        groups, _projects, total = browse.commercial_selection(session, 50, 0)
    assert groups == expected
    assert total == len(expected)


def test_receipt_and_note_save_readback_does_not_invalidate(saved_db, monkeypatch):
    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    factory = saved_db
    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory.begin() as session:
        before = current_generation(session).id
        cards = api._commercial_triage_cards(session, 50)
        save_evaluations(session, cards)
        session.flush()
        assert current_generation(session).id == before
        receipt = session.scalar(select(Pursuit))
        session.add(
            PursuitCallNote(
                pursuit_id=receipt.id,
                client_id=uuid4(),
                note="Synthetic saved note",
                outcome="Contacted",
                next_action="Synthetic follow-up",
            )
        )
        session.flush()
        assert current_generation(session).id == before
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert any(
            note["note"] == "Synthetic saved note"
            for card in payload["items"]
            for note in card["notes"]
        )
    with factory() as session:
        assert current_generation(session).id == before
        assert session.scalar(select(PursuitCallNote.note)) == "Synthetic saved note"


def test_commercial_card_reuses_canonical_detail_buying_chain(saved_db, monkeypatch):
    factory = saved_db
    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory() as session:
        expected = api._commercial_triage_payload(session, 50, saved_selection=True)
    calls = []
    original = api.buying_chain_views

    def counted(session, project_ids, **kwargs):
        calls.append(project_ids)
        return original(session, project_ids, **kwargs)

    monkeypatch.setattr(api, "buying_chain_views", counted)
    with factory() as session:
        actual = api._commercial_triage_payload(session, 50, saved_selection=True)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected
    assert len(calls) == 1


def _saved_receipt_fixture(factory):
    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit

    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        cards = api._commercial_triage_cards(session, 50)
        save_evaluations(session, cards)
        session.flush()
        return session.scalar(select(Pursuit.id)), cards


@pytest.mark.parametrize("mutation", ["unknown_root", "scope", "identity", "research", "malformed"])
def test_unknown_receipt_changes_remain_full_pending(saved_db, mutation):
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior_revision = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        if mutation == "unknown_root":
            row.snapshot = {**row.snapshot, "research_state": {"phase": "changed"}}
        elif mutation == "scope":
            row.project_id = session.scalar(select(Project.id).where(Project.id != row.project_id))
        elif mutation == "identity":
            row.identity_key = "unrecognized-workspace"
        elif mutation == "research":
            row.research_status = "completed"
        else:
            row.snapshot = {"commercial_triage": None}
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.full_revision == state.input_revision == prior_revision + 1


@pytest.mark.parametrize("prepared", [False, True])
def test_concurrent_receipt_note_saves_during_generation_publication(
    saved_db, prepared, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy

    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior = current_generation(session)
        prior_revision, boundary = prior.input_revision, prior.valid_until

    def save(index):
        with saved_db.begin() as writer:
            save_evaluations(writer, deepcopy(cards))
            receipt = writer.get(Pursuit, receipt_id)
            receipt.snapshot = {
                **receipt.snapshot,
                "commercial_triage": {
                    **receipt.snapshot["commercial_triage"],
                    "saved_at": datetime.now(UTC).isoformat(),
                },
            }
            writer.add(
                PursuitCallNote(
                    pursuit_id=receipt_id,
                    client_id=uuid4(),
                    note=f"Concurrent synthetic {index}",
                    outcome="Contacted",
                    next_action="Synthetic follow-up",
                )
            )
            writer.flush()
            assert current_generation(writer).input_revision == prior_revision

    def race():
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save, range(4)))

    result = rebuild(saved_db, _prepare_at=boundary if prepared else None, before_publish=race)
    assert result["status"] == ("prepared" if prepared else "published")
    with saved_db() as reader:
        assert current_generation(reader).input_revision == prior_revision
        assert len(list(reader.scalars(select(PursuitCallNote)))) == 4
        assert len(reader.get(Pursuit, receipt_id).snapshot["commercial_triage"]["versions"]) == 1
        state = reader.get(BrowseState, 1)
        if prepared:
            assert state.prepared_generation_id is not None
            ready_id = state.prepared_generation_id
    if prepared:
        save(4)
        with saved_db() as reader:
            assert reader.get(BrowseState, 1).prepared_generation_id == ready_id
        from gridlens.intelligence import saved_browse as browse

        class AtBoundary(datetime):
            @classmethod
            def now(cls, tz=None):
                return boundary

        monkeypatch.setattr(browse, "datetime", AtBoundary)
        with saved_db() as reader:
            assert current_generation(reader).id == ready_id


def test_receipt_rollback_and_failed_preparation_leave_current_state(saved_db):
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior = current_generation(session)
        before_id, boundary = prior.id, prior.valid_until
    with pytest.raises(RuntimeError), saved_db.begin() as session:
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Rolled back",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
        session.flush()
        raise RuntimeError("Synthetic rollback")

    def save_then_fail():
        with saved_db.begin() as session:
            row = session.get(Pursuit, receipt_id)
            row.snapshot = {
                **row.snapshot,
                "commercial_triage": {
                    **row.snapshot["commercial_triage"],
                    "saved_at": datetime.now(UTC).isoformat(),
                },
            }
        raise RuntimeError("Synthetic publication failure")

    with pytest.raises(RuntimeError):
        rebuild(saved_db, _prepare_at=boundary, before_publish=save_then_fail)
    with saved_db() as session:
        assert current_generation(session).id == before_id
        assert list(session.scalars(select(PursuitCallNote))) == []
        assert session.get(BrowseState, 1).prepared_generation_id is None
        assert session.get(Pursuit, receipt_id).snapshot["commercial_triage"]["saved_at"]


def test_receipt_exemption_never_hides_canonical_change_or_expiry(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse as browse
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        boundary = current_generation(session).valid_until

    def canonical_change():
        with saved_db.begin() as session:
            row = session.get(Pursuit, receipt_id)
            row.snapshot = {**row.snapshot, "commercial_triage": {"saved_at": "Synthetic"}}
            session.execute(text("UPDATE sources SET publisher = 'Canonical correction'"))

    assert (
        rebuild(saved_db, _prepare_at=boundary, before_publish=canonical_change)["status"]
        == "superseded"
    )
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    assert rebuild(saved_db)["status"] == "published"

    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(browse, "datetime", Expired)
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        row.project_ids = []
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_note_bulk_update_delete_and_truncate_contract(saved_db, monkeypatch):
    from gridlens.persistence.models import PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db.begin() as session:
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Synthetic",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
    with saved_db.begin() as session:
        session.execute(text("UPDATE pursuit_call_notes SET note = 'Corrected synthetic'"))
    with saved_db() as session:
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert any(
            note["note"] == "Corrected synthetic"
            for card in payload["items"]
            for note in card["notes"]
        )
    with saved_db.begin() as session:
        session.execute(text("DELETE FROM pursuit_call_notes"))
    with saved_db() as session:
        assert current_generation(session)
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert not any(card["notes"] for card in payload["items"])
    with saved_db.begin() as session:
        session.execute(text("TRUNCATE pursuit_call_notes"))
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


@pytest.mark.parametrize("kind", ["unknown_root", "research_fields", "unknown_identity"])
def test_unrecognized_pursuit_insert_stays_full(saved_db, kind):
    from gridlens.persistence.models import Pursuit

    ids = seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        row = Pursuit(
            identity_key="commercial-need:" + str(need.id), project_id=need.project_id, snapshot={}
        )
        if kind == "unknown_root":
            row.snapshot = {"research_state": {}}
        elif kind == "research_fields":
            row.research_status = "completed"
        else:
            row.identity_key = "unrecognized-insert"
        session.add(row)
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_mixed_receipt_bulk_update_fails_closed_once(saved_db):
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        assert len(list(session.scalars(select(Pursuit)))) == 2
        revision = current_generation(session).input_revision
    with saved_db.begin() as session:
        session.execute(
            text(
                "UPDATE pursuits SET snapshot = CASE WHEN id = :id "
                "THEN snapshot || jsonb_build_object('unknown_root', true) "
                "ELSE jsonb_set(snapshot, '{commercial_triage,saved_at}', "
                "'\"Synthetic receipt update\"'::jsonb) END"
            ),
            {"id": receipt_id},
        )
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    with saved_db() as session:
        assert session.get(BrowseState, 1).input_revision == revision + 1


@pytest.mark.parametrize("unsafe", [False, True])
def test_receipt_rollback_preserves_ready_generation(saved_db, unsafe):
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
    assert rebuild(saved_db, _prepare_at=boundary)["status"] == "prepared"
    with saved_db() as session:
        ready = session.get(BrowseState, 1).prepared_generation_id
        revision = current_generation(session).input_revision
    with pytest.raises(RuntimeError), saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        row.snapshot = (
            {**row.snapshot, "unknown_root": True}
            if unsafe
            else {**row.snapshot, "commercial_triage": {"saved_at": "Synthetic rollback"}}
        )
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Rollback",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
        session.flush()
        raise RuntimeError("Synthetic rollback")
    with saved_db() as session:
        assert current_generation(session).input_revision == revision
        assert session.get(BrowseState, 1).prepared_generation_id == ready
        assert list(session.scalars(select(PursuitCallNote))) == []


def test_receipt_bucket_cannot_promote_current_qualification(saved_db, monkeypatch):
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        # This is stored presentation/history, never accepted evidence or call facts.
        row.snapshot = {**row.snapshot, "commercial_triage": {"saved_card": {"tier": "Lead"}}}
    with saved_db() as session:
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
    assert all(card["tier"] == "Signal" for card in payload["items"])


def test_positive_chain_collector_equals_fresh_canonical_fallback(saved_db, monkeypatch):
    """Synthetic canonical nonempty chain preserves organization and full payload."""
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain

    ids = seed(saved_db, count=1, histories=1)
    now = datetime.now(UTC)
    with saved_db.begin() as s:
        project = s.get(Project, s.get(PowerNeed, ids[0]).project_id)
        project.name = "Orion Data Center"
        project.location = "Austin, TX"
        s.flush()
        view = enrich_buying_chain(
            s,
            project.id,
            fetcher=lambda url: PublicDocument(
                url,
                "Orion Data Center, Austin, TX",
                "Acme is the general contractor for Orion Data Center in Austin, TX.",
                now.date(),
                now,
            ),
            now=now,
        )
        assert any(c["organization"] == "Acme" for c in view["candidates"])
        pid = project.id
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    original = api.opportunity_projection

    def suppress_output(s, **kwargs):
        kwargs.pop("buying_chain_results", None)
        return original(s, **kwargs)

    monkeypatch.setattr(api, "opportunity_projection", suppress_output)
    with saved_db() as s:
        expected = api._commercial_triage_payload(s, 50, saved_selection=True)
        assert any(c["organization"] == "Acme" for c in buying_chain_view(s, pid)["candidates"])
    monkeypatch.setattr(api, "opportunity_projection", original)
    with saved_db() as s:
        actual = api._commercial_triage_payload(s, 50, saved_selection=True)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected
    assert any(c["organization"] == "Acme" for c in actual["items"])
