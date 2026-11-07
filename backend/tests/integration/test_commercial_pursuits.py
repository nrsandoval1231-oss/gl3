from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.api import commercial_pursuits as module
from gridlens.api.app import app
from gridlens.api.commercial_pursuits import _contact as real_contact
from gridlens.domain.commercial_pursuits import OpenTask, attention_reasons, parse_power_day
from gridlens.persistence.commercial_pursuit_models import CommercialPursuit, PursuitActivity
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


def test_mutations_reject_foreign_origins_without_blocking_reads(pursuit_env):
    """Cross-origin requests cannot create or change the owner-managed record."""
    client = TestClient(app)
    need_id = _need(pursuit_env)
    pursuit = client.post(
        "/api/commercial-pursuits",
        headers={"Origin": "http://testserver"},
        json={"need_id": need_id},
    ).json()
    base = f"/api/commercial-pursuits/{pursuit['id']}"
    foreign = {"Origin": "https://attacker.example"}

    assert client.get("/api/commercial-pursuits", headers=foreign).status_code == 200
    assert (
        client.post(
            "/api/commercial-pursuits", headers=foreign, json={"need_id": need_id}
        ).status_code
        == 403
    )
    assert client.patch(base, headers=foreign, json={"stage": "Engaged"}).status_code == 403
    assert (
        client.post(f"{base}/tasks", headers=foreign, json={"description": "blocked"}).status_code
        == 403
    )

    task_response = client.post(f"{base}/tasks", json={"description": "Call contact"})
    assert task_response.status_code == 201
    task_id = task_response.json()["tasks"][0]["id"]
    assert (
        client.patch(
            f"{base}/tasks/{task_id}", headers=foreign, json={"description": "blocked"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/activity",
            headers=foreign,
            json={"kind": "note", "summary": "blocked", "confirmed": True},
        ).status_code
        == 403
    )

    detail = client.get(base).json()
    assert detail["stage"] == "New"
    assert [task["description"] for task in detail["tasks"]] == ["Call contact"]
    assert [item["kind"] for item in detail["activity"]] == ["created"]


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


def test_task_creation_retries_are_idempotent_and_validate_reused_ids(pursuit_env):
    client = TestClient(app)
    first_pursuit = client.post(
        "/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}
    ).json()
    second_pursuit = client.post(
        "/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}
    ).json()
    client_id = str(uuid4())
    payload = {
        "description": "Call about the project",
        "due_date": "2026-12-01",
        "client_id": client_id,
    }
    url = f"/api/commercial-pursuits/{first_pursuit['id']}/tasks"

    first = client.post(url, json=payload)
    replay = client.post(url, json=payload)
    assert first.status_code == 201 and replay.status_code == 200
    assert [task["id"] for task in replay.json()["tasks"]] == [client_id]
    assert [task["description"] for task in replay.json()["tasks"]] == ["Call about the project"]
    assert client.post(url, json={**payload, "description": "Changed on retry"}).status_code == 409
    assert (
        client.post(
            f"/api/commercial-pursuits/{second_pursuit['id']}/tasks", json=payload
        ).status_code
        == 409
    )

    with pursuit_env() as session:
        from gridlens.persistence.commercial_pursuit_models import PursuitTask

        assert session.get(PursuitTask, UUID(client_id)).description == "Call about the project"


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
    assert first.status_code == 201 and again.status_code == 200
    calls = [a for a in again.json()["activity"] if a["kind"] == "call"]
    assert len(calls) == 1
    assert (
        client.post(
            url, json={"kind": "stage_change", "summary": "x", "confirmed": True}
        ).status_code
        == 422
    )
    assert client.get(f"/api/commercial-pursuits/{pursuit['id']}").json()["stage"] == "New"


def test_activity_summary_is_trimmed_and_blank_rejected(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    url = f"/api/commercial-pursuits/{pursuit['id']}/activity"
    blank = {"kind": "call", "summary": "   ", "confirmed": True}
    assert client.post(url, json=blank).status_code == 422
    ok = {"kind": "call", "summary": "  Spoke with buyer  ", "detail": "   ", "confirmed": True}
    response = client.post(url, json=ok)
    assert response.status_code == 201
    calls = [a for a in response.json()["activity"] if a["kind"] == "call"]
    assert calls[0]["summary"] == "Spoke with buyer"
    assert not calls[0]["detail"]


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


def test_contact_database_error_does_not_break_list(pursuit_env, monkeypatch):
    from gridlens.intelligence import buying_chain

    client = TestClient(app)
    first = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    second = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    bad_project = first["project_id"]

    def flaky(session, project_id):
        if str(project_id) == bad_project:
            session.execute(text("SELECT * FROM table_that_does_not_exist"))
        return None

    monkeypatch.setattr(module, "_contact", real_contact)
    monkeypatch.setattr(buying_chain, "buying_chain_view", flaky)
    monkeypatch.setattr(
        "gridlens.domain.opportunity_intelligence.contact_projection", lambda view: []
    )
    response = client.get("/api/commercial-pursuits")
    assert response.status_code == 200
    by_id = {i["id"]: i for i in response.json()["items"]}
    assert by_id[first["id"]]["contact_status"] == "unknown"
    assert by_id[second["id"]]["contact_status"] == "missing"


def test_counts_and_need_filter_cover_more_than_200_pursuits(pursuit_env):
    client = TestClient(app)
    old_need = _need(pursuit_env)
    old = client.post("/api/commercial-pursuits", json={"need_id": old_need}).json()
    with pursuit_env() as session:
        template = session.get(CommercialPursuit, old["id"])
        for _ in range(205):
            need_id = _need(pursuit_env)
            need = session.get(PowerNeed, need_id)
            session.add(CommercialPursuit(need_id=need.id, project_id=need.project_id, stage="New"))
        template.stage = "Lost"
        session.commit()
    listing = client.get("/api/commercial-pursuits", params={"need_id": old_need}).json()
    assert listing["counts"] == {"total": 206, "active": 205, "needs_attention": 0}
    assert [i["id"] for i in listing["items"]] == [old["id"]]
    assert len(client.get("/api/commercial-pursuits", params={"limit": 200}).json()["items"]) == 200


def test_duplicate_client_id_replay_returns_200_with_one_row(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    url = f"/api/commercial-pursuits/{pursuit['id']}/activity"
    payload = {"kind": "note", "summary": "x", "confirmed": True, "client_id": str(uuid4())}
    assert client.post(url, json=payload).status_code == 201
    assert client.post(url, json=payload).status_code == 200
    with pursuit_env() as session:
        count = session.scalar(
            select(func.count())
            .select_from(PursuitActivity)
            .where(PursuitActivity.client_id == payload["client_id"])
        )
    assert count == 1


def test_integrity_error_on_commit_returns_existing_record(pursuit_env, monkeypatch):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    url = f"/api/commercial-pursuits/{pursuit['id']}/activity"
    payload = {"kind": "note", "summary": "x", "confirmed": True, "client_id": str(uuid4())}
    assert client.post(url, json=payload).status_code == 201
    # Simulate the race: the pre-commit existence check misses the winner's row.
    calls = {"n": 0}
    real_scalar = module.Session.scalar

    def blind_first(self, stmt, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # 1 = locked pursuit load, 2 = existence check
            return None
        return real_scalar(self, stmt, *a, **k)

    monkeypatch.setattr(module.Session, "scalar", blind_first)
    response = client.post(url, json=payload)
    assert response.status_code == 200
    assert len([a for a in response.json()["activity"] if a["kind"] == "note"]) == 1


def test_naive_occurred_at_is_rejected(pursuit_env):
    client = TestClient(app)
    pursuit = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    url = f"/api/commercial-pursuits/{pursuit['id']}/activity"
    base = {"kind": "call", "summary": "x", "confirmed": True}
    assert client.post(url, json={**base, "occurred_at": "2026-11-05T10:00:00"}).status_code == 422
    ok = client.post(url, json={**base, "occurred_at": "2026-11-05T10:00:00-06:00"})
    assert ok.status_code == 201


def _project_of(factory, need_id):
    with factory() as session:
        return session.get(PowerNeed, need_id).project_id


def _suppressed_person(factory, project_id):
    """A retained claim for ``project_id`` whose person identity is globally suppressed."""
    from datetime import UTC, datetime

    from gridlens.intelligence.contact_suppressions import (
        global_person_suppression_key,
        record_contact_suppression,
    )
    from gridlens.persistence.models import (
        BuyingChainClaim,
        BuyingChainEvidence,
        BuyingChainIdentityLink,
        PersonIdentity,
    )

    now = datetime.now(UTC)
    with factory() as session:
        person = PersonIdentity()
        session.add(person)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project_id,
            entity_key="entity-1",
            fingerprint="1" * 64,
            policy_version="fixture-v1",
            organization="Acme Energy",
            person_name="Jordan Quill",
            title="Director",
            category="owner",
            organization_relationship="owner",
            person_organization_relationship="employee",
            person_project_relationship="project_contact",
            evidence_strength="high",
            reason="fixture",
            citations=[],
            public_contacts=[
                {"kind": "email", "value": "jordan.quill@acme.test"},
                {"kind": "phone", "value": "512-555-0147"},
            ],
            observed_at=now,
        )
        session.add(claim)
        session.flush()
        evidence = BuyingChainEvidence(
            project_id=project_id,
            url="https://example.test/claim",
            title="t",
            excerpt="e",
            content_hash="2" * 64,
            extraction_location="p1",
            observed_at=now,
            last_seen_at=now,
            project_match_reason="fixture",
        )
        session.add(evidence)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="person",
                person_identity_id=person.id,
                reason="fixture",
                basis="strong_identifier",
                source_evidence_id=evidence.id,
                source_version_hash="e" * 64,
                state="active",
            )
        )
        record_contact_suppression(
            session,
            scope="person",
            subject_key=global_person_suppression_key(person.id),
            action="suppress",
            expected_version=0,
            reason="privacy request",
            actor="integration-test",
            idempotency_key="pursuit-privacy",
        )
        session.commit()


def test_suppressed_contact_text_is_redacted_on_read_but_stored_unchanged(pursuit_env):
    client = TestClient(app)
    need_id = _need(pursuit_env)
    created = client.post("/api/commercial-pursuits", json={"need_id": need_id}).json()
    pid = created["id"]
    summary = "Spoke with Jordan Quill at jordan.quill@acme.test"
    detail = "Call back on 512-555-0147 after lunch"
    task_text = "Email jordan.quill@acme.test then ring 512-555-0147"
    base = f"/api/commercial-pursuits/{pid}"
    activity = {"kind": "call", "summary": summary, "detail": detail, "confirmed": True}
    assert client.post(f"{base}/activity", json=activity).status_code == 201
    task_resp = client.post(f"{base}/tasks", json={"description": task_text})
    assert task_resp.status_code == 201
    task_id = task_resp.json()["tasks"][0]["id"]
    _suppressed_person(pursuit_env, _project_of(pursuit_env, need_id))
    secrets = ["Jordan Quill", "jordan.quill@acme.test", "512-555-0147"]

    def assert_clean(body):
        text_blob = str(body)
        for secret in secrets:
            assert secret not in text_blob, secret

    listing = client.get("/api/commercial-pursuits").json()
    assert listing["items"][0]["next_task"]["description"].count("[redacted]") == 2
    assert_clean(listing)
    detail_body = client.get(base).json()
    assert_clean(detail_body)
    assert any("[redacted]" in a["summary"] for a in detail_body["activity"])
    assert any("[redacted]" in (a["detail"] or "") for a in detail_body["activity"])
    assert_clean(client.patch(base, json={"stage": "Engaged"}).json())
    assert_clean(client.post(f"{base}/tasks", json={"description": "ring 512-555-0147"}).json())
    assert_clean(client.patch(f"{base}/tasks/{task_id}", json={"due_date": "2026-12-01"}).json())
    assert_clean(
        client.post(f"{base}/activity", json={**activity, "summary": "again " + summary}).json()
    )
    # Completing a task logs its description in a system activity row; still redacted.
    assert_clean(client.patch(f"{base}/tasks/{task_id}", json={"completed": True}).json())
    with pursuit_env() as session:
        stored = session.scalars(select(PursuitActivity).where(PursuitActivity.summary == summary))
        row = stored.one()
        assert row.detail == detail
        from gridlens.persistence.commercial_pursuit_models import PursuitTask

        assert session.get(PursuitTask, task_id).description == task_text


def _bulk_pursuits(factory, count, stage="New"):
    with factory() as session:
        source = Source(
            id=f"s-{uuid4().hex[:8]}",
            publisher="p",
            endpoint="https://e.example",
            family="oil-and-gas-permits",
            geography="Texas",
            industries=["oil-and-gas"],
            retrieval_method="m",
        )
        session.add(source)
        session.flush()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        ids = []
        for i in range(count):
            project = Project(
                identity_key=f"p-{uuid4()}",
                name=f"Site {i}",
                location="TX",
                source_id=source.id,
                external_id=f"e-{uuid4().hex[:6]}",
            )
            session.add(project)
            session.flush()
            need = PowerNeed(
                project_id=project.id, activity_key="drilling", tier="Lead", rationale="r"
            )
            session.add(need)
            session.flush()
            # Identical created_at for pairs forces the id tiebreak to matter.
            row = CommercialPursuit(
                need_id=need.id,
                project_id=project.id,
                stage="Lost" if i % 5 == 0 else stage,
                created_at=base + timedelta(minutes=i // 2),
            )
            session.add(row)
            session.flush()
            ids.append((str(row.id), str(need.id), i % 5 == 0))
        session.commit()
        return ids


def test_pagination_pages_without_gaps_or_duplicates(pursuit_env):
    client = TestClient(app)
    created = _bulk_pursuits(pursuit_env, 250)
    pages = []
    for offset in (0, 100, 200):
        body = client.get(
            "/api/commercial-pursuits", params={"limit": 100, "offset": offset}
        ).json()
        pages.append(body)
        assert body["total_matching"] == 250 and body["counts"]["total"] == 250
    assert [len(p["items"]) for p in pages] == [100, 100, 50]
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert [p["next_offset"] for p in pages] == [100, 200, None]
    seen = [i["id"] for p in pages for i in p["items"]]
    assert len(seen) == len(set(seen)) == 250
    assert set(seen) == {c[0] for c in created}
    again = client.get("/api/commercial-pursuits", params={"limit": 100, "offset": 100}).json()
    assert [i["id"] for i in again["items"]] == [i["id"] for i in pages[1]["items"]]
    beyond = client.get("/api/commercial-pursuits", params={"offset": 999}).json()
    assert beyond["items"] == [] and beyond["has_more"] is False
    assert beyond["next_offset"] is None and beyond["total_matching"] == 250
    assert client.get("/api/commercial-pursuits", params={"offset": -1}).status_code == 422


def test_pagination_applies_after_filters(pursuit_env):
    client = TestClient(app)
    created = _bulk_pursuits(pursuit_env, 60)
    active = {c[0] for c in created if not c[2]}
    first = client.get(
        "/api/commercial-pursuits", params={"active_only": True, "limit": 25, "offset": 0}
    ).json()
    second = client.get(
        "/api/commercial-pursuits", params={"active_only": True, "limit": 25, "offset": 25}
    ).json()
    assert first["total_matching"] == second["total_matching"] == len(active) == 48
    assert first["counts"]["total"] == 60
    assert first["has_more"] and first["next_offset"] == 25
    assert not second["has_more"] and second["next_offset"] is None
    seen = [i["id"] for i in first["items"] + second["items"]]
    assert len(seen) == 48 and set(seen) == active
    one = client.get("/api/commercial-pursuits", params={"need_id": created[3][1]}).json()
    assert one["total_matching"] == 1 and not one["has_more"] and one["next_offset"] is None
