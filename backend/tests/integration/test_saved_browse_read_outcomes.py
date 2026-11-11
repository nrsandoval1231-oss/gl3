"""Every labelled browse read is counted as current, updating or pending with its fence."""

import logging
import re
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from test_saved_browse import seed

from gridlens.intelligence import saved_browse
from gridlens.intelligence.saved_browse import READ_REASONS, current_generation, rebuild
from gridlens.persistence.models import PowerNeed, Source
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _published(factory):
    ids = seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    saved_browse.reset_read_counts()
    return ids


def _scoped_write(factory, need_id):
    with factory.begin() as session:
        session.get(PowerNeed, need_id).rationale = f"Synthetic scoped change {uuid4()}"


def _read(factory, *, allow_stale=True, route="groups"):
    with factory() as session:
        try:
            current_generation(session, allow_stale=allow_stale, route=route)
        except HTTPException as raised:
            assert raised.status_code == 503
    return saved_browse.read_counts()


def test_current_and_updating_reads_are_counted(saved_db, monkeypatch):
    ids = _published(saved_db)
    assert _read(saved_db) == {"groups|current|-": 1}
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, ids[0])
    assert _read(saved_db) == {"groups|current|-": 1, "groups|updating|-": 1}


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("stale_age", "stale_age"),
        ("unknown_start", "stale_age"),
        ("source_write", "full_scope"),
        ("clock", "clock"),
        ("policy", "policy"),
        ("flag_off", "flag_off"),
        ("strict_reader", "strict_reader"),
        ("stale_age_beats_flag_off", "stale_age"),
    ],
)
def test_each_fence_is_reported_as_the_pending_reason(saved_db, monkeypatch, setup, reason):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", setup not in {"flag_off"})
    monkeypatch.setattr(settings, "browse_stale_max_seconds", 60)
    allow_stale = setup != "strict_reader"
    if setup in {"stale_age", "stale_age_beats_flag_off", "unknown_start"}:
        _scoped_write(saved_db, ids[0])
        with saved_db.begin() as session:
            session.execute(
                text("UPDATE browse_state SET stale_since = :s"),
                {
                    "s": None
                    if setup == "unknown_start"
                    else datetime.now(UTC) - timedelta(seconds=300)
                },
            )
        monkeypatch.setattr(settings, "browse_serve_stale", setup != "stale_age_beats_flag_off")
    elif setup == "source_write":
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
    elif setup == "clock":
        with saved_db.begin() as session:
            session.execute(
                text("UPDATE browse_generations SET valid_until = :b"),
                {"b": datetime.now(UTC) - timedelta(seconds=1)},
            )
    elif setup == "policy":
        with saved_db.begin() as session:
            session.execute(text("UPDATE browse_generations SET policy_version = 'old-policy'"))
    else:  # flag_off, strict_reader: servable except for the mode
        _scoped_write(saved_db, ids[0])
    counts = _read(saved_db, allow_stale=allow_stale)
    assert counts == {f"groups|pending|{reason}": 1}
    assert reason in READ_REASONS


def test_a_structural_write_is_reported_as_full_scope(saved_db, monkeypatch):
    from test_saved_browse_serve_stale_joins import _contact_fixture

    from gridlens.persistence.models import CompanyIdentity

    fixture = _contact_fixture(saved_db)
    assert rebuild(saved_db)["status"] == "published"
    assert rebuild(saved_db)["status"] == "published"
    saved_browse.reset_read_counts()
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db.begin() as session:  # a linked identity changes after the snapshot
        session.get(CompanyIdentity, fixture["identity_id"]).rrc_operator_number = "123456"
    assert _read(saved_db) == {"groups|pending|full_scope": 1}


def test_no_generation_is_reported_before_the_first_publication(saved_db, monkeypatch):
    seed(saved_db, count=1, histories=1)
    saved_browse.reset_read_counts()
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    assert _read(saved_db) == {"groups|pending|no_generation": 1}


def test_unrouted_callers_are_not_counted(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, ids[0])
    with saved_db() as session:
        current_generation(session, allow_stale=True)  # builders and maintenance pass no route
        with pytest.raises(HTTPException):
            current_generation(session)
    assert saved_browse.read_counts() == {}


def _statements(factory, action):
    engine = factory.kw["bind"]
    seen = []

    def count(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return seen


def test_reason_costs_no_query_on_the_current_path_and_one_read_when_pending(saved_db, monkeypatch):
    ids = _published(saved_db)

    def one(route):
        def action():
            with saved_db() as session:
                current_generation(session, allow_stale=True, route=route)

        return action

    # Current path: counting adds no statement.
    assert len(_statements(saved_db, one("groups"))) == len(_statements(saved_db, one(None)))
    monkeypatch.setattr(settings, "browse_serve_stale", False)
    _scoped_write(saved_db, ids[0])

    def pending(route):
        def action():
            with saved_db() as session, pytest.raises(HTTPException):
                current_generation(session, allow_stale=True, route=route)

        return action

    # Pending path: exactly one extra read, of browse_state.
    with_reason = _statements(saved_db, pending("groups"))
    without = _statements(saved_db, pending(None))
    assert len(with_reason) == len(without) + 1
    assert "browse_state" in with_reason[-1]


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_log_lines_carry_only_route_outcome_reason_and_generation(saved_db, monkeypatch):
    ids = _published(saved_db)
    capture = _Capture()
    saved_browse.read_log.addHandler(capture)
    try:
        monkeypatch.setattr(settings, "browse_serve_stale", False)
        _read(saved_db)
        assert capture.lines == []  # the log is the flag's view: silent while it is off
        monkeypatch.setattr(settings, "browse_serve_stale", True)
        monkeypatch.setattr(settings, "saved_browse_enabled", True)
        api = import_module("gridlens.api.app")
        monkeypatch.setattr(api, "SessionLocal", saved_db)
        client = TestClient(api.app, base_url="https://testserver")
        client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
        _scoped_write(saved_db, ids[0])
        secret = "PRIVATE-SEARCH-TERM-4471"
        assert client.get("/api/opportunities/groups", params={"search": secret}).status_code == 200
        with saved_db.begin() as session:
            session.add(
                Source(
                    id="synthetic-log-fence",
                    publisher="Synthetic",
                    endpoint="https://example.test/log",
                    family="construction-permits",
                    geography="Test",
                    industries=["construction"],
                    retrieval_method="socrata-permits",
                    health={},
                )
            )
        assert client.get("/api/opportunities/groups", params={"search": secret}).status_code == 503
    finally:
        saved_browse.read_log.removeHandler(capture)
    assert len(capture.lines) == 2
    shape = re.compile(
        r"browse_read route=groups outcome=(updating|pending) reason=[a-z_-]+ "
        r"generation=[0-9a-f-]{36}"
    )
    for line in capture.lines:
        assert shape.fullmatch(line), line
        assert "PRIVATE" not in line and "Synthetic" not in line
    assert "outcome=updating reason=-" in capture.lines[0]
    assert "outcome=pending reason=full_scope" in capture.lines[1]


def test_pending_path_costs_one_extra_read_with_the_flag_on(saved_db, monkeypatch):
    _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    with saved_db.begin() as session:  # a fence that stays closed with the flag on
        session.add(
            Source(
                id="synthetic-full-scope-cost",
                publisher="Synthetic",
                endpoint="https://example.test/cost",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )

    def pending(route):
        def action():
            with saved_db() as session, pytest.raises(HTTPException):
                current_generation(session, allow_stale=True, route=route)

        return action

    with_reason = _statements(saved_db, pending("groups"))
    without = _statements(saved_db, pending(None))
    assert len(with_reason) == len(without) + 1
    assert "browse_state" in with_reason[-1]


def test_each_stale_capable_route_is_counted_once_per_request(saved_db, monkeypatch):
    ids = _published(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    _scoped_write(saved_db, ids[0])
    saved_browse.reset_read_counts()
    parent = client.get("/api/opportunities/groups", params={"limit": 1})
    assert parent.status_code == 200
    group_id = parent.json()["items"][0]["id"]
    token = parent.json()["cohort_token"]
    assert (
        client.get(
            f"/api/opportunities/groups/{group_id}/projects",
            params={"parent_cohort_token": token},
        ).status_code
        == 200
    )
    assert client.get(f"/api/opportunities/groups/{group_id}/open").status_code == 200
    assert (
        client.get("/api/opportunities/projects", params={"include_signals": "true"}).status_code
        == 200
    )
    assert saved_browse.read_counts() == {
        "groups|updating|-": 1,
        "group_projects|updating|-": 1,
        "group_open|updating|-": 1,
        "projects|updating|-": 1,
    }
