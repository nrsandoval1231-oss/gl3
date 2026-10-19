"""Publication/time interleavings must not admit stale or future qualifications."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from test_saved_browse import saved_db, seed  # noqa: F401

from gridlens.intelligence import saved_browse
from gridlens.persistence.models import BrowseGeneration, BrowseState, PowerNeed

BASE = datetime(2026, 10, 19, 12, tzinfo=UTC)


def controlled_clock(monkeypatch, instant=BASE):
    clock = {"now": instant, "samples": 0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            clock["samples"] += 1
            value = clock["now"]
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    return clock


def sample_clock(monkeypatch, samples):
    remaining = iter(samples)
    observed = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = next(remaining)
            observed.append(value)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    return observed


def test_reader_rechecks_time_after_publication_between_sample_and_query(
    saved_db,  # noqa: F811
    monkeypatch,
):
    """Two real DB sessions reproduce the race without scheduler timing guesses."""
    clock = controlled_clock(monkeypatch)
    ids = seed(saved_db, count=1, histories=1)
    assert saved_browse.rebuild(saved_db)["status"] == "published"
    published = {}
    with saved_db() as reader:
        scalar = reader.scalar
        queries = 0

        def interleaved_scalar(statement, *args, **kwargs):
            nonlocal queries
            queries += 1
            if queries == 1:
                # current_generation has already sampled BASE into its query.
                # Publish and commit before that query acquires its DB snapshot.
                clock["now"] = BASE + timedelta(seconds=1)
                with saved_db.begin() as writer:
                    writer.get(PowerNeed, ids[0]).rationale = "Committed concurrent update"
                    result = saved_browse.refresh_project_changes(writer)
                    assert result and result["status"] == "published"
                    state = writer.get(BrowseState, 1)
                    generation = writer.get(BrowseGeneration, state.generation_id)
                    published.update(id=generation.id, revision=state.input_revision)
                    assert generation.valid_from > BASE
                clock["now"] = BASE + timedelta(seconds=2)
            return scalar(statement, *args, **kwargs)

        monkeypatch.setattr(reader, "scalar", interleaved_scalar)
        generation = saved_browse.current_generation(reader)
        assert queries == 2
        assert generation.id == published["id"]
        assert generation.input_revision == published["revision"]
        assert reader.get(PowerNeed, ids[0]).rationale == "Committed concurrent update"


def test_reader_uses_recovered_actual_clock_without_changing_generation(
    saved_db,  # noqa: F811
    monkeypatch,
):
    controlled_clock(monkeypatch)
    seed(saved_db, count=1, histories=1)
    result = saved_browse.rebuild(saved_db)
    observed = sample_clock(
        monkeypatch, [BASE - timedelta(microseconds=1), BASE + timedelta(microseconds=1)]
    )
    with saved_db() as reader:
        generation = saved_browse.current_generation(reader)
        assert str(generation.id) == result["generation_id"]
        assert generation.valid_from == BASE
        assert len(observed) == 2


def test_explicit_past_time_is_not_replaced_by_wall_clock(
    saved_db,  # noqa: F811
    monkeypatch,
):
    controlled_clock(monkeypatch)
    seed(saved_db, count=1, histories=1)
    saved_browse.rebuild(saved_db)
    observed = sample_clock(monkeypatch, [])
    with saved_db() as reader:
        with pytest.raises(HTTPException) as failure:
            saved_browse.current_generation(reader, now=BASE - timedelta(microseconds=1))
        assert failure.value.status_code == 503
        assert observed == []
        assert saved_browse.current_generation(reader, now=BASE).valid_from == BASE
        assert observed == []


@pytest.mark.parametrize("invalid", ["revision", "policy", "expiry", "sustained_rollback"])
def test_retry_never_bypasses_invalid_generation(
    saved_db,  # noqa: F811
    monkeypatch,
    invalid,
):
    controlled_clock(monkeypatch)
    seed(saved_db, count=1, histories=1)
    saved_browse.rebuild(saved_db)
    with saved_db.begin() as setup:
        state = setup.get(BrowseState, 1)
        generation = setup.get(BrowseGeneration, state.generation_id)
        generation_id = generation.id
        if invalid == "revision":
            state.input_revision += 1
        elif invalid == "policy":
            generation.policy_version = "different-policy"
        elif invalid == "expiry":
            generation.valid_until = BASE
    instant = BASE - timedelta(microseconds=1) if invalid == "sustained_rollback" else BASE
    observed = sample_clock(monkeypatch, [instant, instant])
    with saved_db() as reader:
        with pytest.raises(HTTPException) as failure:
            saved_browse.current_generation(reader)
        assert failure.value.status_code == 503
        assert failure.value.headers["X-Qualification-State"] == "pending"
        assert 1 <= len(observed) <= 2
        assert reader.get(BrowseState, 1).generation_id == generation_id


def test_retry_does_not_expose_prepared_future_generation(
    saved_db,  # noqa: F811
    monkeypatch,
):
    controlled_clock(monkeypatch)
    seed(saved_db, count=1, histories=1)
    saved_browse.rebuild(saved_db)
    with saved_db() as reader:
        boundary = saved_browse.current_generation(reader, now=BASE).valid_until
    assert saved_browse.rebuild(saved_db, _prepare_at=boundary)["status"] == "prepared"
    with saved_db.begin() as setup:
        state = setup.get(BrowseState, 1)
        # With no active pointer, only the genuinely future preparation is available.
        state.generation_id = None
        prepared_id = state.prepared_generation_id
    before = boundary - timedelta(microseconds=1)
    observed = sample_clock(monkeypatch, [before, before])
    with saved_db() as reader:
        with pytest.raises(HTTPException) as failure:
            saved_browse.current_generation(reader)
        assert failure.value.status_code == 503
        assert 1 <= len(observed) <= 2
        assert saved_browse.current_generation(reader, now=boundary).id == prepared_id
