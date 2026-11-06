from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api import commercial_pursuits as module
from gridlens.api.app import app
from gridlens.domain.commercial_pursuits import OpenTask, attention_reasons, parse_power_day
from gridlens.persistence.database import Base
from gridlens.persistence.models import PowerNeed, Project, Source
from gridlens.security import require_session
from gridlens.settings import settings


@pytest.fixture
def pursuit_env(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL pursuit tests")
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    schema = "pursuit_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(module, "_contact", lambda session, project_id: (None, "unknown"))
    app.dependency_overrides[require_session] = lambda: None
    yield factory
    app.dependency_overrides.pop(require_session, None)
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _need(factory, start_window=None):
    with factory() as session:
        source = Source(
            id=f"s-{uuid4().hex[:8]}",
            publisher="Texas Railroad Commission",
            endpoint="https://rrc.example",
            family="oil-and-gas-permits",
            geography="Texas",
            industries=["oil-and-gas"],
            retrieval_method="rrc-flare-exceptions",
        )
        session.add(source)
        session.flush()
        project = Project(
            identity_key=f"p-{uuid4()}",
            name="Synthetic Site",
            location="Midland, TX",
            source_id=source.id,
            external_id=f"e-{uuid4().hex[:6]}",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="drilling",
            tier="Lead",
            rationale="r",
            required_mw=None,
            start_window=start_window,
        )
        session.add(need)
        session.commit()
        return str(need.id)


def test_routes_require_authentication():
    client = TestClient(app)
    assert client.get("/api/commercial-pursuits").status_code == 401
    assert client.post("/api/commercial-pursuits", json={}).status_code == 401


def test_create_is_idempotent_per_opportunity(pursuit_env):
    client = TestClient(app)
    need_id = _need(pursuit_env)
    first = client.post("/api/commercial-pursuits", json={"need_id": need_id})
    second = client.post("/api/commercial-pursuits", json={"need_id": need_id})
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["stage"] == "New"
    listing = client.get("/api/commercial-pursuits", params={"need_id": need_id}).json()
    assert listing["counts"]["total"] == 1 and len(listing["items"]) == 1
    assert [a["kind"] for a in first.json()["activity"]] == ["created"]
    assert (
        client.post("/api/commercial-pursuits", json={"need_id": str(uuid4())}).status_code == 404
    )


def test_stage_changes_persist_and_log_without_advancing_automatically(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    updated = client.patch(f"/api/commercial-pursuits/{pursuit['id']}", json={"stage": "Engaged"})
    assert updated.json()["stage"] == "Engaged"
    assert updated.json()["activity"][0]["kind"] == "stage_change"
    assert (
        client.patch(
            f"/api/commercial-pursuits/{pursuit['id']}", json={"stage": "Bogus"}
        ).status_code
        == 422
    )
    lost = client.patch(f"/api/commercial-pursuits/{pursuit['id']}", json={"stage": "Lost"}).json()
    assert lost["stage"] == "Lost" and lost["attention"] == []
    assert (
        client.get("/api/commercial-pursuits", params={"active_only": True}).json()["items"] == []
    )


def test_tasks_create_edit_reschedule_complete(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    base = f"/api/commercial-pursuits/{pursuit['id']}"
    yesterday = (date.today() - timedelta(days=3)).isoformat()
    made = client.post(
        f"{base}/tasks", json={"description": "Call buyer", "due_date": yesterday}
    ).json()
    task = made["tasks"][0]
    assert made["attention"] == ["overdue_follow_up"]
    later = (date.today() + timedelta(days=30)).isoformat()
    moved = client.patch(
        f"{base}/tasks/{task['id']}", json={"due_date": later, "description": "Call buyer again"}
    ).json()
    assert moved["tasks"][0]["due_date"] == later and moved["attention"] == []
    done = client.patch(f"{base}/tasks/{task['id']}", json={"completed": True}).json()
    assert done["tasks"][0]["completed_at"] and done["next_task"] is None
    assert done["activity"][0]["kind"] == "task_completed"
    assert client.post(f"{base}/tasks", json={"description": "   "}).status_code == 422


def test_activity_requires_confirmation_and_is_idempotent(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    url = f"/api/commercial-pursuits/{pursuit['id']}/activity"
    payload = {"kind": "call", "summary": "Spoke with buyer", "confirmed": False}
    assert client.post(url, json=payload).status_code == 422
    client_id = str(uuid4())
    payload.update(confirmed=True, client_id=client_id)
    first = client.post(url, json=payload)
    again = client.post(url, json=payload)
    assert first.status_code == 201 and again.status_code == 201
    calls = [a for a in again.json()["activity"] if a["kind"] == "call"]
    assert len(calls) == 1
    assert (
        client.post(
            url, json={"kind": "stage_change", "summary": "x", "confirmed": True}
        ).status_code
        == 422
    )
    assert client.get(f"/api/commercial-pursuits/{pursuit['id']}").json()["stage"] == "New"


def test_needs_attention_rules_and_counts(pursuit_env, monkeypatch):
    client = TestClient(app)
    quiet = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    soon = (date.today() + timedelta(days=10)).isoformat()
    near = client.post(
        "/api/commercial-pursuits", json={"need_id": _need(pursuit_env, soon)}
    ).json()
    assert quiet["attention"] == [] and near["attention"] == ["power_timing_near"]
    monkeypatch.setattr(module, "_contact", lambda session, project_id: (None, "missing"))
    listing = client.get("/api/commercial-pursuits").json()
    assert listing["counts"] == {"total": 2, "active": 2, "needs_attention": 2}
    flagged = client.get("/api/commercial-pursuits", params={"needs_attention": True}).json()
    assert {i["id"] for i in flagged["items"]} == {quiet["id"], near["id"]}
    assert all("missing_contact" in i["attention"] for i in flagged["items"])


def test_attention_rule_unit_behaviour():
    today = date(2026, 11, 6)
    open_due = lambda d: [OpenTask("t", d)]  # noqa: E731
    assert attention_reasons(
        stage="New",
        open_tasks=open_due(date(2026, 11, 5)),
        has_usable_contact=True,
        start_window=None,
        today=today,
    ) == ["overdue_follow_up"]
    assert attention_reasons(
        stage="New",
        open_tasks=open_due(date(2026, 11, 8)),
        has_usable_contact=True,
        start_window=None,
        today=today,
    ) == ["follow_up_due_soon"]
    assert (
        attention_reasons(
            stage="New",
            open_tasks=open_due(date(2026, 11, 9)),
            has_usable_contact=True,
            start_window=None,
            today=today,
        )
        == []
    )
    assert (
        attention_reasons(
            stage="Won",
            open_tasks=open_due(date(2026, 1, 1)),
            has_usable_contact=False,
            start_window=None,
            today=today,
        )
        == []
    )
    assert (
        attention_reasons(
            stage="New", open_tasks=[], has_usable_contact=None, start_window=None, today=today
        )
        == []
    )
    assert parse_power_day("Q4 2026") is None and parse_power_day("2026-11") is None
    assert parse_power_day("2026-13-40") is None and parse_power_day("2026-12-01") == date(
        2026, 12, 1
    )
