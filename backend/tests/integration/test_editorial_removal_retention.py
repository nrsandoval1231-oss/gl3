from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    EditorialAssessment,
    EditorialDecision,
    Evidence,
    Observation,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings

api = import_module("gridlens.api.app")


@pytest.fixture
def historical_records(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL historical-record test")
    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    assert (
        test_url.database
        and test_url.database.endswith("_test")
        and "corpus" not in test_url.database.lower()
    )
    assert (test_url.host, test_url.port, test_url.database) != (
        app_url.host,
        app_url.port,
        app_url.database,
    )
    schema = "editorial_removal_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)

    observation_id, evidence_id = uuid4(), uuid4()
    with factory.begin() as session:
        session.add(
            Source(
                id="editorial-removal-fixture",
                publisher="Synthetic removal test",
                endpoint="https://example.test/records",
                family="construction-permits",
                geography="Fixture City",
                industries=["construction"],
                retrieval_method="fixture",
                health={"status": "Updated"},
            )
        )
        session.flush()
        session.add(
            Observation(
                id=observation_id,
                source_id="editorial-removal-fixture",
                external_id="fixture-1",
                title="Synthetic retained observation",
                url="https://example.test/records/1",
                content_hash="b" * 64,
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash="b" * 64,
                title="Synthetic retained evidence",
                url="https://example.test/records/1",
                provenance={},
            )
        )
        session.flush()
        session.add_all(
            [
                EditorialDecision(
                    sequence=1,
                    observation_id=observation_id,
                    evidence_id=evidence_id,
                    evidence_hash="b" * 64,
                    status="approved",
                    reviewer="fixture-owner",
                    payload={"note": "historical decision"},
                ),
                EditorialAssessment(
                    evidence_id=evidence_id,
                    evidence_hash="b" * 64,
                    payload={"summary": "historical assessment"},
                ),
            ]
        )
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def test_authenticated_removed_routes_leave_synthetic_historical_rows_unchanged(
    historical_records,
):
    client = TestClient(api.app)
    paths = (
        ("GET", "/api/editorial/candidates"),
        ("GET", "/api/editorial/sync"),
        ("GET", "/api/editorial/clearance/00000000-0000-0000-0000-000000000001"),
        ("GET", "/api/editorial/review"),
        ("POST", "/api/editorial/review/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/editorial/assessment/00000000-0000-0000-0000-000000000001"),
    )
    before = _historical_snapshot(historical_records)
    assert client.get("/api/health").status_code == 401
    for method, path in paths:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 404

    token = token_for(int(datetime.now(UTC).timestamp()) + 3600)
    client.cookies.set("gridlens_session", token)
    assert client.get("/api/auth/session").json() == {"authenticated": True}
    assert client.get("/api/health").status_code == 200
    for method, path in paths:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 404
    schema = client.get("/openapi.json").json()
    assert not any(path.startswith("/api/editorial/") for path in schema["paths"])
    assert _historical_snapshot(historical_records) == before


def _historical_snapshot(factory):
    with factory() as session:
        decisions = session.scalars(select(EditorialDecision)).all()
        assessments = session.scalars(select(EditorialAssessment)).all()
    return (
        tuple(
            (row.id, row.sequence, row.observation_id, row.evidence_id, row.evidence_hash,
             row.status, row.reviewer, row.payload, row.created_at)
            for row in decisions
        ),
        tuple(
            (row.id, row.evidence_id, row.evidence_hash, row.payload, row.created_at)
            for row in assessments
        ),
    )
