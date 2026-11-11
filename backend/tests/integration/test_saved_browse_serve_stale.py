"""Owner-approved serving of the last complete generation during scoped ingestion."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_saved_browse import seed

from gridlens.intelligence import saved_browse
from gridlens.intelligence.customer_results import groups
from gridlens.intelligence.saved_browse import current_generation, rebuild, refresh_state
from gridlens.persistence.models import BrowseGeneration, PowerNeed, Source
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _scoped_write(factory, need_id):
    with factory.begin() as session:
        session.get(PowerNeed, need_id).rationale = f"Synthetic scoped change {uuid4()}"


def _published(factory):
    ids = seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    return ids


def _pending(factory, **kwargs):
    with factory() as session, pytest.raises(HTTPException) as raised:
        current_generation(session, **kwargs)
    assert raised.value.status_code == 503
    assert raised.value.headers["X-Qualification-State"] == "pending"


def test_scoped_write_stays_pending_by_default(saved_db):
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    _pending(saved_db, allow_stale=True)


def test_scoped_write_serves_last_generation_as_updating(saved_db, monkeypatch):
    ids = _published(saved_db)
    with saved_db() as session:
        published = current_generation(session)
        assert refresh_state(published) == "current"
    _scoped_write(saved_db, ids[0])
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db() as session:
        served = current_generation(session, allow_stale=True)
        assert served.id == published.id
        assert refresh_state(served) == "updating"
        payload = groups(session)
        assert payload["refresh_state"] == "updating"
        assert payload["qualification_state"] == "current"
        assert payload["generation_id"] == str(published.id)
    # Builders, maintenance and explicit evaluation instants never accept it.
    _pending(saved_db)  # callers that do not opt in stay strict
    _pending(saved_db, now=datetime.now(UTC))
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        fresh = current_generation(session)
        assert fresh.id != published.id
        assert refresh_state(fresh) == "current"


def test_full_scope_write_stays_pending(saved_db, monkeypatch):
    _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db.begin() as session:
        session.add(
            Source(
                id="synthetic-full-scope",
                publisher="Synthetic",
                endpoint="https://example.test/full",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
    _pending(saved_db, allow_stale=True)


def _stale_since(factory):
    with factory() as session:
        return session.scalar(text("SELECT stale_since FROM browse_state"))


def test_snapshot_built_long_ago_is_served_after_the_first_write(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    monkeypatch.setattr(settings, "browse_stale_max_seconds", 60)
    with saved_db.begin() as session:  # a quiet period: the snapshot is ten hours old
        session.execute(
            text("UPDATE browse_generations SET built_at = :built_at"),
            {"built_at": datetime.now(UTC) - timedelta(hours=10)},
        )
    assert _stale_since(saved_db) is None  # nothing newer yet
    _scoped_write(saved_db, ids[0])
    started = _stale_since(saved_db)
    assert started is not None and abs((datetime.now(UTC) - started).total_seconds()) < 30
    with saved_db() as session:
        assert refresh_state(current_generation(session, allow_stale=True)) == "updating"


def test_stale_longer_than_the_bound_with_continuous_writes_is_pending(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    monkeypatch.setattr(settings, "browse_stale_max_seconds", 60)
    _scoped_write(saved_db, ids[0])
    with saved_db.begin() as session:  # the first newer write is now two minutes old
        session.execute(
            text("UPDATE browse_state SET stale_since = :since"),
            {"since": datetime.now(UTC) - timedelta(seconds=120)},
        )
    for _ in range(3):  # continuous writes never extend the window
        _scoped_write(saved_db, ids[1 % len(ids)])
        with saved_db() as session, pytest.raises(HTTPException):
            current_generation(session, allow_stale=True)
    assert (datetime.now(UTC) - _stale_since(saved_db)).total_seconds() > 100


def test_a_second_write_does_not_move_stale_since_forward(saved_db, monkeypatch):
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    first = _stale_since(saved_db)
    assert first is not None
    with saved_db() as session:
        revision = session.scalar(text("SELECT input_revision FROM browse_state"))
    _scoped_write(saved_db, ids[1 % len(ids)])
    with saved_db() as session:  # the write really happened and was newer
        assert session.scalar(text("SELECT input_revision FROM browse_state")) > revision
    assert _stale_since(saved_db) == first


def test_publication_clears_stale_since_and_the_next_write_starts_a_new_window(
    saved_db,
):
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    first = _stale_since(saved_db)
    assert first is not None
    assert rebuild(saved_db)["status"] == "published"
    assert _stale_since(saved_db) is None
    _scoped_write(saved_db, ids[0])
    second = _stale_since(saved_db)
    assert second is not None and second > first


def test_scoped_refresh_publication_clears_stale_since(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    assert _stale_since(saved_db) is not None
    with saved_db.begin() as session:
        assert refresh_project_changes(session, max_projects=None, max_needs=None) is not None
    assert _stale_since(saved_db) is None
    with saved_db() as session:
        assert refresh_state(current_generation(session)) == "current"


def test_unknown_stale_start_is_pending_not_servable(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, ids[0])
    with saved_db.begin() as session:  # e.g. a state that was already behind at upgrade time
        session.execute(text("UPDATE browse_state SET stale_since = NULL"))
    _pending(saved_db, allow_stale=True)
    _scoped_write(saved_db, ids[0])  # a later write cannot invent a start for an unknown one
    assert _stale_since(saved_db) is None
    _pending(saved_db, allow_stale=True)


def _copy_generation(factory):
    """An unpublished copy of the published generation (same revision), like a failed rebase."""
    new_id = uuid4()
    with factory.begin() as session:
        columns = [
            row[0]
            for row in session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = current_schema() AND table_name = 'browse_generations'"
                )
            )
        ]
        listed = ", ".join(f'"{c}"' for c in columns)
        values = ", ".join(":new_id" if c == "id" else f'"{c}"' for c in columns)
        session.execute(
            text(
                f"INSERT INTO browse_generations ({listed}) SELECT {values}"
                " FROM browse_generations WHERE id = (SELECT generation_id FROM browse_state)"
            ),
            {"new_id": new_id},
        )
    return new_id


def test_moving_the_pointer_and_restoring_it_never_resets_the_window(saved_db):
    """A rebase publishes a behind generation and, on failure, restores the old pointer."""
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    started = _stale_since(saved_db)
    assert started is not None
    with saved_db() as session:
        original = session.scalar(text("SELECT generation_id FROM browse_state"))
    rebased = _copy_generation(saved_db)
    for target in (rebased, original):
        with saved_db.begin() as session:
            session.execute(text("UPDATE browse_state SET generation_id = :g"), {"g": target})
        assert _stale_since(saved_db) == started


def test_an_unknown_start_is_not_invented_by_a_pointer_move(saved_db):
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    with saved_db.begin() as session:
        session.execute(text("UPDATE browse_state SET stale_since = NULL"))
    rebased = _copy_generation(saved_db)
    with saved_db.begin() as session:
        session.execute(text("UPDATE browse_state SET generation_id = :g"), {"g": rebased})
    assert _stale_since(saved_db) is None


def test_the_age_bound_closes_on_the_real_clock(saved_db, monkeypatch):
    import time

    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    monkeypatch.setattr(settings, "browse_stale_max_seconds", 1)
    _scoped_write(saved_db, ids[0])
    with saved_db() as session:
        assert refresh_state(current_generation(session, allow_stale=True)) == "updating"
    time.sleep(1.5)  # no hand-set timestamps: the window simply runs out
    _pending(saved_db, allow_stale=True)


def _arm_boundary(factory):
    """Prepare the next interval, then move the clock boundary into the past."""
    from gridlens.intelligence.saved_browse import prepare_next

    assert prepare_next(factory, lead_seconds=90000)["status"] == "prepared"
    boundary = datetime.now(UTC) - timedelta(seconds=1)
    with factory.begin() as session:
        state = session.execute(
            text("SELECT generation_id, prepared_generation_id FROM browse_state")
        ).one()
        session.execute(
            text("UPDATE browse_generations SET valid_until = :b WHERE id = :g"),
            {"b": boundary, "g": state.generation_id},
        )
        session.execute(
            text("UPDATE browse_generations SET valid_from = :b WHERE id = :g"),
            {"b": boundary, "g": state.prepared_generation_id},
        )
    return state.generation_id, state.prepared_generation_id


def test_promotion_at_a_boundary_keeps_a_current_state_unstale(saved_db):
    from gridlens.intelligence.saved_browse import maintain_once

    _published(saved_db)
    old_id, prepared_id = _arm_boundary(saved_db)
    maintain_once(saved_db)  # promotes the prepared interval (no newer write)
    with saved_db() as session:
        state = session.execute(text("SELECT generation_id, stale_since FROM browse_state")).one()
        assert state.generation_id == prepared_id != old_id
        assert state.stale_since is None  # the promoted generation covers the revision


def test_a_write_that_promotes_a_boundary_starts_a_new_window(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    old_id, prepared_id = _arm_boundary(saved_db)
    _scoped_write(saved_db, ids[0])  # the invalidation promotes the interval, then moves ahead
    with saved_db() as session:
        state = session.execute(text("SELECT generation_id, stale_since FROM browse_state")).one()
        assert state.generation_id == prepared_id != old_id
        assert state.stale_since is not None  # the promoted generation fell behind just now
        served = current_generation(session, allow_stale=True)
        assert served.id == prepared_id and refresh_state(served) == "updating"


def test_expired_clock_window_stays_pending(saved_db, monkeypatch):
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db.begin() as session:
        generation = session.scalars(saved_browse.select(BrowseGeneration)).one()
        generation.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    _pending(saved_db, allow_stale=True)
