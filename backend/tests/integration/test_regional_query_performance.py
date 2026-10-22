"""The compact browse preflight validates both evidence cohorts in one query."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api import app
from gridlens.persistence.database import Base
from gridlens.persistence.models import Source
from gridlens.settings import settings


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.rows)


def test_streamed_evidence_preflight_aggregates_both_scopes_in_one_query():
    session = _Session([("need", 12, 30), ("lifecycle", 18, 42)])

    app._preflight_streamed_evidence_text(session, [uuid4()], [uuid4()])

    assert len(session.statements) == 1
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "GROUP BY" in sql
    assert "UNION ALL" in sql


@pytest.mark.parametrize(
    "rows",
    [
        [("need", app._MAX_OPPORTUNITY_SEARCH_FIELD_BYTES + 1, 0)],
        [("lifecycle", 1, app._MAX_OPPORTUNITY_SEARCH_COHORT_BYTES + 1)],
    ],
)
def test_streamed_evidence_preflight_preserves_each_scope_bound(rows):
    session = _Session(rows)

    with pytest.raises(HTTPException) as error:
        app._preflight_streamed_evidence_text(session, [uuid4()], [uuid4()])

    assert error.value.status_code == 413
    assert len(session.statements) == 1


def test_disabled_source_is_not_reported_as_failed_or_in_aggregate_freshness(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    schema = "regional_health_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory.begin() as session:
            session.add(
                Source(
                    id="regional-disabled-source",
                    publisher="Fixture",
                    endpoint="https://example.invalid/disabled",
                    family="synthetic",
                    geography="US",
                    industries=[],
                    retrieval_method="test",
                    cadence_hours=24,
                    enabled=False,
                    registry_enabled=False,
                    health={"status": "Failed", "error": "historical failure"},
                )
            )
        monkeypatch.setattr(app, "SessionLocal", factory)
        monkeypatch.setattr(
            app,
            "load_registry",
            lambda: [{"id": "regional-disabled-source", "enabled": False}],
        )

        result = app.health()

        source = result["sources"][0]
        assert source["status"] == "Disabled"
        assert source["freshness"] == "DISABLED"
        assert source["error"] is None
        assert result["collection_freshness"] == "UNKNOWN"
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
