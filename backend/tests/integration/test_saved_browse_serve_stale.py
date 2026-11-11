"""Owner-approved serving of the last complete generation during scoped ingestion."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_saved_browse import saved_db, seed  # noqa: F401

from gridlens.intelligence import saved_browse
from gridlens.intelligence.customer_results import groups
from gridlens.intelligence.saved_browse import current_generation, rebuild, refresh_state
from gridlens.persistence.models import BrowseGeneration, PowerNeed, Source
from gridlens.settings import settings


def _scoped_write(factory, need_id):
    with factory.begin() as session:
        session.get(PowerNeed, need_id).rationale = "Synthetic scoped change"


def _published(factory):
    ids = seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    return ids


def _pending(factory, **kwargs):
    with factory() as session, pytest.raises(HTTPException) as raised:
        current_generation(session, **kwargs)
    assert raised.value.status_code == 503
    assert raised.value.headers["X-Qualification-State"] == "pending"


def test_scoped_write_stays_pending_by_default(saved_db):  # noqa: F811
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    _pending(saved_db, allow_stale=True)


def test_scoped_write_serves_last_generation_as_updating(saved_db, monkeypatch):  # noqa: F811
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


def test_full_scope_write_stays_pending(saved_db, monkeypatch):  # noqa: F811
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


def test_stalled_republication_stops_serving(saved_db, monkeypatch):  # noqa: F811
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    monkeypatch.setattr(settings, "browse_stale_max_seconds", 60)
    with saved_db.begin() as session:
        session.execute(
            text("UPDATE browse_generations SET built_at = :built_at"),
            {"built_at": datetime.now(UTC) - timedelta(seconds=120)},
        )
    _pending(saved_db, allow_stale=True)


def test_expired_clock_window_stays_pending(saved_db, monkeypatch):  # noqa: F811
    ids = _published(saved_db)
    _scoped_write(saved_db, ids[0])
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db.begin() as session:
        generation = session.scalars(saved_browse.select(BrowseGeneration)).one()
        generation.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    _pending(saved_db, allow_stale=True)
