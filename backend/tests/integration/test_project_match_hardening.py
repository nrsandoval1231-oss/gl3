"""Hardening of the indexed project matcher: stale-key guard, bounded keys, lock race, migration."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion import service
from gridlens.ingestion.service import (
    _retained_candidates,
    _retained_identity_match,
)
from gridlens.intelligence.project_identity import project_match_keys
from gridlens.persistence.models import Project
from gridlens.settings import settings


@pytest.fixture
def engine():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sources (id, publisher, endpoint, family, geography, industries, "
                "retrieval_method, cadence_hours, enabled, health) VALUES ('s1', 's1', "
                "'https://example.invalid/', 'permits', 'US', '[]', 'socrata-permits', 1, "
                "true, '{}')"
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with sessionmaker(engine, expire_on_commit=False)() as db:
        yield db


def _project(key: str, name: str, location: str | None, facts: dict | None = None) -> Project:
    return Project(
        identity_key=key,
        name=name,
        location=location,
        source_id="s1",
        external_id=key,
        identity_facts=facts or {"project_aliases": [name], "site": location},
    )


def _keys(engine, key: str):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT match_keys FROM projects WHERE identity_key = :k"), {"k": key}
        ).scalar_one()


def test_raw_update_of_identity_columns_nulls_stale_keys(engine, session):
    session.add(_project("p1", "Alpha Data Center", "100 Main Street, Austin, TX"))
    session.commit()
    assert _keys(engine, "p1")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE projects SET asset_type = 'data_center' WHERE identity_key = 'p1'")
        )
    assert _keys(engine, "p1")  # unrelated columns keep their keys
    for column, value in (
        ("name", "'Renamed'"),
        ("location", "'200 Oak Road, Houston, TX'"),
        ("identity_facts", '\'{"project_aliases": ["Zed"]}\'::jsonb'),
    ):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE projects SET match_keys = ARRAY['n:stale'] WHERE identity_key = 'p1'")
            )
            connection.execute(
                text(f"UPDATE projects SET {column} = {value} WHERE identity_key = 'p1'")
            )
        assert _keys(engine, "p1") is None, column
    # Even an explicit match_keys in the same raw UPDATE cannot smuggle in stale keys.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE projects SET name = 'Q', match_keys = ARRAY['n:stale'] "
                "WHERE identity_key = 'p1'"
            )
        )
    assert _keys(engine, "p1") is None


def test_orm_update_recomputes_keys_and_later_raw_update_is_still_guarded(engine, session):
    first = _project("p1", "Alpha Data Center", "100 Main Street, Austin, TX")
    second = _project("p2", "Beta Station", "200 Oak Road, Houston, TX")
    session.add_all([first, second])
    session.commit()
    first.name = "Gamma Pad"
    session.commit()
    assert _keys(engine, "p1") == project_match_keys(
        "Gamma Pad", first.location, first.identity_facts
    )

    # One transaction: raw UPDATE (nulls p2), ORM UPDATE of p1 (recomputed), raw UPDATE of p1.
    session.execute(text("UPDATE projects SET name = 'Raw Name' WHERE identity_key = 'p2'"))
    first.identity_facts = {"project_aliases": ["Delta"], "site": first.location}
    session.flush()
    session.execute(text("UPDATE projects SET name = 'Raw Again' WHERE identity_key = 'p1'"))
    session.commit()
    assert _keys(engine, "p2") is None
    assert _keys(engine, "p1") is None  # the ORM flush did not leave the guard open

    session.refresh(first)
    first.identity_facts = {"project_aliases": ["Epsilon"], "site": first.location}
    session.commit()
    assert _keys(engine, "p1") == project_match_keys(
        "Raw Again", first.location, first.identity_facts
    )


def test_orm_update_uses_stored_values_for_unmodified_key_inputs(engine, session):
    """A stale session changing one input must not erase a concurrent change to another."""
    session.add(_project("p1", "Alpha Data Center", "100 Main Street, Austin, TX"))
    session.commit()
    with sessionmaker(engine, expire_on_commit=False)() as other:
        stale = other.execute(select(Project).where(Project.identity_key == "p1")).scalar_one()
        session.execute(
            text(
                "UPDATE projects SET location = '200 Oak Road, Houston, TX' "
                "WHERE identity_key = 'p1'"
            )
        )
        session.commit()
        stale.name = "Gamma Pad"
        other.commit()
    with engine.connect() as connection:
        name, location, facts = connection.execute(
            text("SELECT name, location, identity_facts FROM projects WHERE identity_key='p1'")
        ).one()
    assert (name, location) == ("Gamma Pad", "200 Oak Road, Houston, TX")
    assert _keys(engine, "p1") == project_match_keys(name, location, facts)


def test_stale_raw_updated_project_still_matches_via_null_fallback(engine, session):
    session.add(_project("p1", "Alpha Data Center", "100 Main Street, Austin, TX"))
    session.commit()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE projects SET name = 'Beta Station' WHERE identity_key='p1'")
        )
    observation = SimpleNamespace(title="Beta Station news", abstract=None)
    claim = {"decision": "accepted", "subject": "Beta Station", "location": "Elsewhere, TX"}
    assert [p.identity_key for p in _retained_candidates(session, observation, claim, None)] == [
        "p1"
    ]


def test_very_long_names_aliases_and_locations_insert_update_and_match(engine, session):
    long_name = "alpha " * 900
    long_location = "100 Main Street " + "x" * 5000 + ", Austin, TX"
    other = "alpha " * 899 + "beta"
    target = _project(
        "long",
        long_name,
        long_location,
        {
            "project_aliases": ["z" * 5000],
            "site": long_location,
            "asset_identity": ["a", "b" * 4000],
        },
    )
    decoy = _project("decoy", other, "1 Elm Road, Austin, TX")
    session.add_all([target, decoy])
    session.commit()
    assert all(len(key) <= 200 for key in _keys(engine, "long"))
    target.name = long_name + " two"
    target.identity_facts = {**target.identity_facts, "project_aliases": ["z" * 6000]}
    session.commit()
    assert all(len(key) <= 200 for key in _keys(engine, "long"))

    for name in (target.name, "z" * 6000):
        observation = SimpleNamespace(title="t", abstract=None)
        claim = {"decision": "accepted", "subject": name, "location": long_location}
        found = _retained_candidates(session, observation, claim, None)
        assert [p.identity_key for p in found if p.match_keys is not None] == ["long"], name
    # Sanity: the structured path agrees with the oracle on the long asset identity.
    assert service.incoming_match_keys(asset_identity=["a", "b" * 4000]) == [
        key for key in _keys(engine, "long") if key.startswith("x:")
    ]


def test_retained_ambiguous_branch_rejects_project_committed_after_locks(
    engine, session, monkeypatch
):
    for key in ("p1", "p2"):
        session.add(_project(key, "Alpha Data Center", "100 Main Street, Austin, TX"))
    session.commit()
    observation = SimpleNamespace(
        title="Alpha Data Center plans",
        abstract="Site address: 100 Main Street, Austin, TX.",
        source_id="s1",
    )
    claim = {
        "decision": "accepted",
        "subject": "Alpha Data Center",
        "location": "100 Main Street, Austin, TX",
    }
    candidates = _retained_candidates(session, observation, claim, None, refresh=True)
    locked = {p.id for p in session.scalars(select(Project)).all()}

    decisions, matching = _retained_identity_match(
        session, candidates, observation, claim, None, False, locked
    )
    assert len(matching) == 2 and len(decisions) == 2

    real_scan = service._full_scan_projects

    def scan_after_concurrent_commit(db, *, refresh=False):
        other = create_engine(settings.test_database_url)
        with other.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, identity_key, name, location, source_id, "
                    "external_id, identity_facts) VALUES (:i, 'late', 'Unrelated', 'Nowhere', "
                    "'s1', 'late', '{}')"
                ),
                {"i": uuid4()},
            )
        other.dispose()
        return real_scan(db, refresh=refresh)

    monkeypatch.setattr(service, "_full_scan_projects", scan_after_concurrent_commit)
    with pytest.raises(RuntimeError, match="changed after ordered locks"):
        _retained_identity_match(session, candidates, observation, claim, None, False, locked)


@pytest.fixture
def migration_env(monkeypatch):
    from alembic.config import Config

    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    schema = "match_keys_mig_" + uuid4().hex[:12]
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = target.set(query={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(settings, "database_url", url.render_as_string(hide_password=False))
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    engine = create_engine(url)
    try:
        yield config, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _assert_indexes_valid(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON "
                "c.oid = i.indexrelid WHERE c.relname IN ('ix_projects_match_keys', "
                "'ix_projects_match_keys_unset') AND c.relnamespace = "
                "(SELECT oid FROM pg_namespace WHERE nspname = current_schema())"
            )
        ).all()
        assert sorted(r[0] for r in rows) == [
            "ix_projects_match_keys",
            "ix_projects_match_keys_unset",
        ]
        assert all(r[1] for r in rows)
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname = 'projects_match_keys_guard' "
                    "AND tgrelid = 'projects'::regclass"
                )
            ).scalar_one()
            == 1
        )


# Later migrations are not idempotent from the 0054 stamp used below: exercise 0055 alone.
REVISION_0055 = "0055_project_match_keys"


def test_0055_is_retryable_resumable_and_reversible(migration_env):
    from alembic import command

    config, engine = migration_env
    command.upgrade(config, "0054_browse_stale_since")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sources (id, publisher, endpoint, family, geography, industries, "
                "retrieval_method, cadence_hours, enabled, health) VALUES ('s1', 's1', "
                "'https://example.invalid/', 'permits', 'US', '[]', 'socrata-permits', 1, "
                "true, '{}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, identity_key, name, location, source_id, external_id, "
                "identity_facts) VALUES (:i, 'p1', 'Alpha', 'Austin, TX', 's1', 'p1', "
                '\'{"project_aliases": ["Alpha"]}\')'
            ),
            {"i": uuid4()},
        )
    command.upgrade(config, REVISION_0055)
    _assert_indexes_valid(engine)
    with engine.connect() as connection:
        keys = connection.execute(text("SELECT match_keys FROM projects")).scalar_one()
    assert "n:alpha" in keys

    # Simulate a failed index build after the column, keys and trigger were committed.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = '0054_browse_stale_since'")
        )
        connection.execute(text("DROP INDEX ix_projects_match_keys"))
        connection.execute(text("UPDATE projects SET match_keys = NULL"))
    command.upgrade(config, REVISION_0055)
    _assert_indexes_valid(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT match_keys FROM projects")).scalar_one() == keys

    command.downgrade(config, "0054_browse_stale_since")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name = 'projects' "
                    "AND column_name = 'match_keys' AND table_schema = current_schema()"
                )
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc WHERE proname = 'projects_match_keys_guard' "
                    "AND pronamespace = current_schema()::regnamespace"
                )
            ).scalar_one()
            == 0
        )
    command.upgrade(config, "head")
    _assert_indexes_valid(engine)
    command.check(config)
