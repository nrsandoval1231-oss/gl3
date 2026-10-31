"""Keep the initiating publication outcome without exposing canonical inputs."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from test_saved_browse import saved_db, seed  # noqa: F401

from gridlens.intelligence import saved_browse
from gridlens.intelligence.worker_browse import install_worker_publication
from gridlens.persistence.models import BrowseGeneration, BrowseRow, BrowseState, PowerNeed
from gridlens.settings import settings


def controlled_clock(monkeypatch, instant):
    clock = {"now": instant}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock["now"]
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    return clock


@pytest.mark.parametrize("prepare_next_window", [False, True])
def test_refresh_outcome_survives_savepoint_and_excludes_private_error(
    saved_db,  # noqa: F811
    monkeypatch,
    prepare_next_window,
):
    # Refresh also clamps validity to the next clock boundary. Freeze before
    # the first build so a real run near midnight cannot enter preparation.
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    controlled_clock(monkeypatch, now)
    ids = seed(saved_db, histories=1)
    assert saved_browse.rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(factory)
    with factory() as writer:
        writer.get(PowerNeed, ids[0]).rationale = "Synthetic updated rationale"
        writer.commit()
        assert writer.info["worker_browse_outcome"]["status"] == "published", writer.info[
            "worker_browse_outcome"
        ]

    original = saved_browse._write_rows

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE-SYNTHETIC-INPUT must not enter diagnostics")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with factory() as writer:
        writer.get(PowerNeed, ids[0]).rationale = "Canonical change survives"
        writer.commit()
        assert writer.info["worker_browse_outcome"] == {
            "status": "pending",
            "reason": "RuntimeError",
            "sqlstate": None,
        }
    with saved_db() as reader:
        assert reader.get(PowerNeed, ids[0]).rationale == "Canonical change survives"
        with pytest.raises(HTTPException) as failure:
            saved_browse.current_generation(reader)
        assert failure.value.status_code == 503
    monkeypatch.setattr(saved_browse, "_write_rows", original)
    with saved_db.begin() as fixture:
        state = fixture.get(BrowseState, 1)
        current = fixture.get(BrowseGeneration, state.generation_id)
        # Deterministically exercise either maintenance completion or creation
        # of the next interval without depending on when pytest crosses midnight.
        current.valid_until = now + timedelta(seconds=60 if prepare_next_window else 3600)
    controlled_clock(monkeypatch, now)
    saved_db.kw["bind"].dispose()
    restarted = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    maintenance = saved_browse.maintain_once(restarted)
    assert maintenance["status"] == ("prepared" if prepare_next_window else "published")
    with restarted() as reader:
        generation = saved_browse.current_generation(reader)
        state = reader.get(BrowseState, 1)
        assert generation.input_revision == state.input_revision
        row = reader.get(BrowseRow, (generation.id, ids[0]))
        assert row is not None
        assert reader.get(PowerNeed, ids[0]).rationale == "Canonical change survives"
        if prepare_next_window:
            assert state.prepared_generation_id is not None
            prepared = reader.get(BrowseGeneration, state.prepared_generation_id)
            assert prepared is not None
            assert prepared.input_revision == state.input_revision
