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
    """Run API checks in a disposable PostgreSQL schema with isolated route state."""
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
    """Create one synthetic source, project and power need for route assertions."""
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
    with pursuit_env() as session:
        session.get(PowerNeed, UUID(need_id)).active = False
        session.commit()
    inactive_retry = client.post("/api/commercial-pursuits", json={"need_id": need_id})
    assert inactive_retry.status_code == 200
    assert inactive_retry.json()["id"] == first.json()["id"]
    assert (
        client.post("/api/commercial-pursuits", json={"need_id": str(uuid4())}).status_code == 404
    )


def test_concurrent_alias_and_root_create_serializes_to_one_pursuit(pursuit_env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_need_aliases import _fixture_graph, _record

    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    with pursuit_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
    barrier = Barrier(2)

    def create(need_id):
        client = TestClient(app)
        barrier.wait()
        return client.post("/api/commercial-pursuits", json={"need_id": str(need_id)})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(create, (needs[0], needs[1])))
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert responses[0].json()["need_id"] == str(needs[1])
    with pursuit_env() as session:
        pursuits = session.scalars(select(CommercialPursuit)).all()
        assert len(pursuits) == 1
        assert pursuits[0].need_id == needs[1]


def test_distinct_needs_remain_distinct_pursuits_even_on_same_project(pursuit_env):
    """Account/project association must not collapse separate power needs or their history."""
    client = TestClient(app)
    first_need_id = UUID(_need(pursuit_env))
    with pursuit_env() as session:
        first_need = session.get(PowerNeed, first_need_id)
        second_need = PowerNeed(
            project_id=first_need.project_id,
            activity_key="data-center-expansion",
            tier="Lead",
            rationale="Separate synthetic power package",
            required_mw="25",
        )
        session.add(second_need)
        session.commit()
        second_need_id = second_need.id

    first = client.post("/api/commercial-pursuits", json={"need_id": str(first_need_id)}).json()
    first = client.patch(
        f"/api/commercial-pursuits/{first['id']}", json={"stage": "Engaged"}
    ).json()
    second = client.post("/api/commercial-pursuits", json={"need_id": str(second_need_id)}).json()

    assert first["id"] != second["id"]
    assert first["project_id"] == second["project_id"]
    assert first["stage"] == "Engaged"
    assert second["stage"] == "New"
    assert first["account_id"] is None
    assert first["account_name"] is None


def test_alias_retry_returns_existing_canonical_pursuit(pursuit_env):
    from test_need_aliases import _fixture_graph, _record

    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    with pursuit_env() as session:
        _record(session, needs, evidence_id)
        session.commit()
    client = TestClient(app)
    canonical = client.post("/api/commercial-pursuits", json={"need_id": str(needs[1])})
    assert canonical.status_code == 201
    with pursuit_env() as session:
        session.get(PowerNeed, needs[1]).active = False
        session.commit()

    retry = client.post("/api/commercial-pursuits", json={"need_id": str(needs[0])})
    assert retry.status_code == 200
    assert retry.json()["id"] == canonical.json()["id"]
    assert str(needs[0]) in retry.json()["need_alias_ids"]
    alias_filtered = client.get(
        "/api/commercial-pursuits", params={"need_id": str(needs[0])}
    ).json()
    assert [item["id"] for item in alias_filtered["items"]] == [canonical.json()["id"]]


@pytest.fixture
def restored_alias_chain(pursuit_env):
    """Restore source evidence after another accepted alias creates a real chain."""
    from test_need_aliases import _add_pair_evidence, _fixture_graph, _record

    from gridlens.intelligence.account_identity import account_identity_for_projects
    from gridlens.intelligence.need_aliases import NeedAliasError, need_alias_members
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.models import BrowseState, Observation

    client = TestClient(app)
    needs, observation_id, evidence_id = _fixture_graph(pursuit_env)
    created = client.post("/api/commercial-pursuits", json={"need_id": str(needs[1])})
    assert created.status_code == 201
    pursuit = created.json()
    unrelated = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    private_text = "Call Jordan Quill at jordan.quill@acme.test or 512-555-0147"
    base = f"/api/commercial-pursuits/{pursuit['id']}"
    assert client.post(f"{base}/tasks", json={"description": private_text}).status_code == 201
    assert (
        client.post(
            f"{base}/activity",
            json={
                "kind": "note",
                "summary": private_text,
                "detail": private_text,
                "confirmed": True,
            },
        ).status_code
        == 201
    )
    with pursuit_env() as session:
        assert _record(session, needs, evidence_id).state == "current"
        observation = session.get(Observation, observation_id)
        original_hash = observation.content_hash
        observation.content_hash = "b" * 64
        session.flush()
        # A -> B is temporarily invalid. C -> A is accepted without inserting
        # malformed assertions directly or mocking the resolver.
        next_evidence = _add_pair_evidence(session, needs, 2, 0)
        assert (
            _record(session, needs, next_evidence, alias_index=2, canonical_index=0).state
            == "current"
        )
        session.add(BrowseState(id=1))
        session.commit()
    # Ensure the account-label lookup reaches alias validation, rather than
    # returning early because there is no current saved browse generation.
    assert rebuild(pursuit_env)["status"] == "published"
    with pursuit_env() as session:
        session.get(Observation, observation_id).content_hash = original_hash
        session.commit()
    _suppressed_person(pursuit_env, _project_of(pursuit_env, needs[2]))
    with pursuit_env() as session:
        with pytest.raises(NeedAliasError, match="chain"):
            need_alias_members(session, [needs[1]])
        with pytest.raises(NeedAliasError, match="chain"):
            account_identity_for_projects(session, {UUID(pursuit["project_id"])})
    return needs, pursuit, unrelated, private_text


@pytest.mark.parametrize("route", ["list", "detail", "exact-retry"])
@pytest.mark.parametrize("privacy_overflow", [False, True])
def test_saved_pursuits_survive_restored_alias_chain(
    pursuit_env, restored_alias_chain, monkeypatch, route, privacy_overflow
):
    """Optional identity failure cannot hide saved work or relax historical privacy."""
    from gridlens.persistence.commercial_pursuit_models import PursuitTask

    needs, pursuit, unrelated, private_text = restored_alias_chain
    if privacy_overflow:
        monkeypatch.setattr(module, "_MAX_PRIVACY_NEEDS", 2)
    client = TestClient(app, raise_server_exceptions=False)
    if route == "list":
        response = client.get("/api/commercial-pursuits")
    elif route == "detail":
        response = client.get(f"/api/commercial-pursuits/{pursuit['id']}")
    else:
        response = client.post("/api/commercial-pursuits", json={"need_id": str(needs[1])})
    assert response.status_code == 200, response.text
    body = response.json()
    if route == "list":
        assert body["counts"]["total"] == body["total_matching"] == 2
        by_id = {item["id"]: item for item in body["items"]}
        assert set(by_id) == {pursuit["id"], unrelated["id"]}
        body = by_id[pursuit["id"]]
    assert body["id"] == pursuit["id"] and body["need_id"] == str(needs[1])
    assert body["account_id"] is None and body["account_name"] is None
    assert "[redacted]" in body["next_task"]["description"]
    for secret in ("Jordan Quill", "jordan.quill@acme.test", "512-555-0147"):
        assert secret not in str(body)
    if privacy_overflow:
        assert body["next_task"]["description"] == "[redacted]"
    if route != "list":
        assert body["tasks"][0]["description"] == body["next_task"]["description"]
        note = next(item for item in body["activity"] if item["kind"] == "note")
        assert "[redacted]" in note["summary"] and "[redacted]" in note["detail"]
    with pursuit_env() as session:
        assert session.scalar(select(func.count()).select_from(CommercialPursuit)) == 2
        assert session.scalar(select(PursuitTask.description)) == private_text
        note = session.scalar(select(PursuitActivity).where(PursuitActivity.kind == "note"))
        assert note.summary == note.detail == private_text


def test_unknown_alias_membership_rejects_filters_and_prevents_duplicates(
    pursuit_env, restored_alias_chain
):
    """Unknown alias membership is not an authoritative empty or exact-only result."""
    needs, pursuit, unrelated, _private_text = restored_alias_chain
    client = TestClient(app, raise_server_exceptions=False)
    for need_id in (*needs, UUID(unrelated["need_id"]), uuid4()):
        filtered = client.get("/api/commercial-pursuits", params={"need_id": str(need_id)})
        assert filtered.status_code == 409, filtered.text
        assert filtered.json()["detail"] == "Opportunity identity is ambiguous"
    for need_id in (needs[0], needs[2], needs[3]):
        create = client.post("/api/commercial-pursuits", json={"need_id": str(need_id)})
        assert create.status_code == 409, create.text
    # Exact persisted IDs remain replayable, even for a separate unaffected pursuit.
    for existing in (pursuit, unrelated):
        retry = client.post("/api/commercial-pursuits", json={"need_id": existing["need_id"]})
        assert retry.status_code == 200, retry.text
        assert retry.json()["id"] == existing["id"]
    with pursuit_env() as session:
        assert session.scalar(select(func.count()).select_from(CommercialPursuit)) == 2


def test_conflicted_alias_create_preserves_both_existing_pursuits(pursuit_env):
    from test_need_aliases import _fixture_graph, _record

    from gridlens.intelligence.need_aliases import record_alias
    from gridlens.persistence.models import Evidence, NeedObservation, Observation

    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    with pursuit_env() as session:
        _record(session, needs, evidence_id)
        session.commit()

    with pursuit_env() as session:
        alias_need = session.get(PowerNeed, needs[0])
        canonical_need = session.get(PowerNeed, needs[1])
        alias_pursuit = CommercialPursuit(
            need_id=alias_need.id,
            project_id=alias_need.project_id,
            stage="Contacted",
        )
        canonical_pursuit = CommercialPursuit(
            need_id=canonical_need.id,
            project_id=canonical_need.project_id,
            stage="Engaged",
        )
        session.add_all([alias_pursuit, canonical_pursuit])
        session.commit()
        alias_pursuit_id = alias_pursuit.id
        canonical_pursuit_id = canonical_pursuit.id
    client = TestClient(app)
    with pursuit_env() as session:
        alias_need = session.get(PowerNeed, needs[2])
        canonical_need = session.get(PowerNeed, needs[1])
        alias_project = session.get(Project, alias_need.project_id)
        canonical_project = session.get(Project, canonical_need.project_id)
        alias_binding = {
            "source_ref": f"{alias_project.source_id}:{alias_project.external_id}",
            "activity_key": alias_need.activity_key,
            "package_scope": "package-7",
        }
        canonical_binding = {
            "source_ref": f"{canonical_project.source_id}:{canonical_project.external_id}",
            "activity_key": canonical_need.activity_key,
            "package_scope": "package-7",
        }
        quote = (
            f"Package package-7: {alias_binding['source_ref']} "
            f"({alias_binding['activity_key']}) and {canonical_binding['source_ref']} "
            f"({canonical_binding['activity_key']}) refer to the same power package."
        )
        source = session.get(Source, alias_project.source_id)
        observation = Observation(
            source_id=source.id,
            external_id=f"conflicted-alias-{uuid4().hex[:8]}",
            title=quote,
            abstract="Synthetic strict package alias proof",
            url="https://synthetic.invalid/conflicted-alias",
            content_hash="b" * 64,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            provenance={
                "need_alias_assertion": {
                    "package_scope": "package-7",
                    "need_bindings": [alias_binding, canonical_binding],
                    "same_package_quote": quote,
                }
            },
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=needs[2], observation_id=observation.id),
                NeedObservation(need_id=needs[1], observation_id=observation.id),
            ]
        )
        record_alias(
            session,
            alias_need_id=needs[2],
            canonical_need_id=needs[1],
            evidence_id=evidence.id,
            expected_evidence_hash=evidence.content_hash,
            package_scope="package-7",
            reason="Explicit synthetic package link",
        )
        session.commit()

    conflicted = client.post("/api/commercial-pursuits", json={"need_id": str(needs[2])})
    assert conflicted.status_code == 409
    alias_after = client.get(f"/api/commercial-pursuits/{alias_pursuit_id}").json()
    canonical_after = client.get(f"/api/commercial-pursuits/{canonical_pursuit_id}").json()
    assert alias_after["stage"] == "Contacted"
    assert canonical_after["stage"] == "Engaged"


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
    """Exact task retries return one row; changed or cross-pursuit reuse conflicts."""
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


def test_activity_client_id_reuse_with_different_content_conflicts(pursuit_env):
    """Only an exact retry replays; changed content under the same key is a 409."""
    client = TestClient(app)
    first_pursuit = client.post(
        "/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}
    ).json()
    url = f"/api/commercial-pursuits/{first_pursuit['id']}/activity"
    payload = {
        "kind": "call",
        "summary": "Spoke with buyer",
        "detail": "Asked about timing",
        "occurred_at": "2026-11-01T15:00:00Z",
        "confirmed": True,
        "client_id": str(uuid4()),
    }
    assert client.post(url, json=payload).status_code == 201
    assert client.post(url, json=payload).status_code == 200
    for change in (
        {"kind": "email"},
        {"summary": "Spoke with someone else"},
        {"detail": "Different detail"},
        {"occurred_at": "2026-11-02T15:00:00Z"},
    ):
        conflict = client.post(url, json={**payload, **change})
        assert conflict.status_code == 409, change
        assert conflict.json()["detail"] == "Activity idempotency key was already used"
    detail = client.get(f"/api/commercial-pursuits/{first_pursuit['id']}").json()
    assert len([a for a in detail["activity"] if a["kind"] in {"call", "email"}]) == 1


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


@pytest.mark.parametrize("stored_need_index", [0, 1], ids=["alias-pursuit", "root-pursuit"])
@pytest.mark.parametrize("alias_state", ["current", "retracted", "conflicted", "superseded"])
def test_alias_contact_privacy_covers_persisted_history(
    pursuit_env, stored_need_index, alias_state
):
    """Both entry points retain privacy scope after aliases stop resolving together."""
    from test_need_aliases import _fixture_graph, _record

    from gridlens.intelligence.need_aliases import retract_alias
    from gridlens.persistence.commercial_pursuit_models import PursuitTask

    client = TestClient(app)
    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    created = client.post(
        "/api/commercial-pursuits", json={"need_id": str(needs[stored_need_index])}
    )
    assert created.status_code == 201
    pursuit_id = created.json()["id"]
    with pursuit_env() as session:
        assertion = _record(session, needs, evidence_id)
        assertion_id = assertion.id
        session.commit()
    resolved = client.post(
        "/api/commercial-pursuits", json={"need_id": str(needs[1 - stored_need_index])}
    )
    assert resolved.status_code == 200 and resolved.json()["id"] == pursuit_id
    base = f"/api/commercial-pursuits/{pursuit_id}"
    summary = "Spoke with Jordan Quill at jordan.quill@acme.test"
    detail = "Call back on 512-555-0147 after lunch"
    task_text = "Email Jordan Quill at jordan.quill@acme.test or 512-555-0147"
    for kind in ("note", "call"):
        assert (
            client.post(
                f"{base}/activity",
                json={"kind": kind, "summary": summary, "detail": detail, "confirmed": True},
            ).status_code
            == 201
        )
    task_response = client.post(f"{base}/tasks", json={"description": task_text})
    assert task_response.status_code == 201
    task_id = task_response.json()["tasks"][0]["id"]
    # Task-completion activity quotes saved task text as well.
    assert client.patch(f"{base}/tasks/{task_id}", json={"completed": True}).status_code == 200
    assert client.post(f"{base}/tasks", json={"description": task_text}).status_code == 201
    unrelated = client.post("/api/commercial-pursuits", json={"need_id": str(needs[2])}).json()
    unrelated_base = f"/api/commercial-pursuits/{unrelated['id']}"
    assert (
        client.post(f"{unrelated_base}/tasks", json={"description": task_text}).status_code == 201
    )
    if alias_state != "current":
        with pursuit_env() as session:
            if alias_state == "retracted":
                assert retract_alias(session, needs[0], "Synthetic correction") is not None
            else:
                session.get(module.NeedAliasAssertion, assertion_id).state = alias_state
            session.commit()
    # The suppressed contact belongs only to the OTHER source project, not the
    # pursuit's stored project. Apply suppression after all history was persisted.
    _suppressed_person(pursuit_env, _project_of(pursuit_env, needs[1 - stored_need_index]))
    secrets = ("Jordan Quill", "jordan.quill@acme.test", "512-555-0147")

    def assert_safe(body):
        for secret in secrets:
            assert secret not in str(body), secret

    listing = client.get("/api/commercial-pursuits").json()
    by_id = {item["id"]: item for item in listing["items"]}
    assert_safe(by_id[pursuit_id])
    assert "[redacted]" in by_id[pursuit_id]["next_task"]["description"]
    assert by_id[unrelated["id"]]["next_task"]["description"] == task_text
    body = client.get(base).json()
    assert_safe(body)
    assert all("[redacted]" in task["description"] for task in body["tasks"])
    for kind in ("note", "call", "task_completed"):
        items = [item for item in body["activity"] if item["kind"] == kind]
        assert items and all("[redacted]" in item["summary"] for item in items)
        if kind in {"note", "call"}:
            assert all("[redacted]" in item["detail"] for item in items)
    assert_safe(client.patch(base, json={"stage": "Engaged"}).json())
    assert_safe(client.post(f"{base}/tasks", json={"description": task_text}).json())
    assert_safe(client.patch(f"{base}/tasks/{task_id}", json={"due_date": "2026-12-01"}).json())
    assert_safe(
        client.post(
            f"{base}/activity",
            json={"kind": "note", "summary": summary, "detail": detail, "confirmed": True},
        ).json()
    )
    with pursuit_env() as session:
        row = session.get(CommercialPursuit, pursuit_id)
        assert row.need_id == needs[stored_need_index]
        assert row.project_id == _project_of(pursuit_env, needs[stored_need_index])
        assert session.get(PursuitTask, task_id).description == task_text
        saved = session.scalars(
            select(PursuitActivity).where(
                PursuitActivity.pursuit_id == row.id, PursuitActivity.kind.in_(["note", "call"])
            )
        ).all()
        assert saved and all(item.summary == summary and item.detail == detail for item in saved)


@pytest.mark.parametrize("bound", ["_MAX_PRIVACY_NEEDS", "_MAX_PRIVACY_ALIAS_ASSERTIONS"])
def test_alias_privacy_bounds_withhold_only_affected_pursuit(pursuit_env, monkeypatch, bound):
    from test_need_aliases import _fixture_graph, _record

    from gridlens.intelligence.need_aliases import retract_alias
    from gridlens.persistence.commercial_pursuit_models import PursuitTask

    client = TestClient(app)
    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    with pursuit_env() as session:
        _record(session, needs, evidence_id)
        retract_alias(session, needs[0], "Synthetic correction")
        session.commit()
    linked = client.post("/api/commercial-pursuits", json={"need_id": str(needs[1])}).json()
    other = client.post("/api/commercial-pursuits", json={"need_id": str(needs[2])}).json()
    for pursuit in (linked, other):
        assert (
            client.post(
                f"/api/commercial-pursuits/{pursuit['id']}/tasks",
                json={"description": "Retained owner text"},
            ).status_code
            == 201
        )
    monkeypatch.setattr(module, bound, 1)
    listing = client.get("/api/commercial-pursuits")
    assert listing.status_code == 200
    by_id = {item["id"]: item for item in listing.json()["items"]}
    assert by_id[linked["id"]]["next_task"]["description"] == "[redacted]"
    assert by_id[other["id"]]["next_task"]["description"] == "Retained owner text"
    body = client.get(f"/api/commercial-pursuits/{linked['id']}").json()
    assert body["tasks"][0]["description"] == "[redacted]"
    assert all(item["summary"] == "[redacted]" for item in body["activity"])
    with pursuit_env() as session:
        assert set(session.scalars(select(PursuitTask.description))) == {"Retained owner text"}


def test_reparented_alias_preserves_transitive_historical_privacy_scope(pursuit_env):
    from test_need_aliases import _add_pair_evidence, _fixture_graph, _record

    from gridlens.intelligence.need_aliases import retract_alias
    from gridlens.persistence.commercial_pursuit_models import PursuitTask

    client = TestClient(app)
    needs, _observation_id, evidence_id = _fixture_graph(pursuit_env)
    created = client.post("/api/commercial-pursuits", json={"need_id": str(needs[1])}).json()
    base = f"/api/commercial-pursuits/{created['id']}"
    original = "Ask Jordan Quill at jordan.quill@acme.test about 512-555-0147"
    assert client.post(f"{base}/tasks", json={"description": original}).status_code == 201
    assert (
        client.post(
            f"{base}/activity",
            json={"kind": "note", "summary": original, "detail": original, "confirmed": True},
        ).status_code
        == 201
    )
    with pursuit_env() as session:
        _record(session, needs, evidence_id)
        retract_alias(session, needs[0], "Synthetic old root correction")
        replacement = _add_pair_evidence(session, needs, 0, 2, scope="replacement-package")
        _record(session, needs, replacement, canonical_index=2, scope="replacement-package")
        session.commit()
    _suppressed_person(pursuit_env, _project_of(pursuit_env, needs[2]))
    with pursuit_env() as session:
        row = session.get(CommercialPursuit, created["id"])
        assert module._privacy_project_ids(session, row) == sorted(
            [_project_of(pursuit_env, need_id) for need_id in needs[:3]], key=str
        )
        assert session.scalar(select(PursuitTask.description)) == original
    for response in (client.get(base), client.get("/api/commercial-pursuits")):
        assert response.status_code == 200
        body = response.json()
        assert all(
            secret not in str(body)
            for secret in ("Jordan Quill", "jordan.quill@acme.test", "512-555-0147")
        )
        item = body["items"][0] if "items" in body else body
        assert "[redacted]" in item["next_task"]["description"]


def test_alias_privacy_database_error_rolls_back_lookup_and_withholds_text(
    pursuit_env, monkeypatch
):
    from gridlens.persistence.commercial_pursuit_models import PursuitTask

    client = TestClient(app)
    created = client.post("/api/commercial-pursuits", json={"need_id": _need(pursuit_env)}).json()
    base = f"/api/commercial-pursuits/{created['id']}"
    assert (
        client.post(f"{base}/tasks", json={"description": "Retained owner text"}).status_code == 201
    )
    original_execute = module.Session.execute
    failures = []

    def fail_lookup(self, statement, *args, **kwargs):
        names = [column["name"] for column in getattr(statement, "column_descriptions", [])]
        if names == ["id", "alias_need_id", "canonical_need_id"]:
            failures.append(True)
            # A real PostgreSQL statement error must be isolated by the savepoint.
            return original_execute(self, text("SELECT * FROM nonexistent_privacy_alias_table"))
        return original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(module.Session, "execute", fail_lookup)
    for response in (client.get(base), client.get("/api/commercial-pursuits")):
        assert response.status_code == 200
        body = response.json()
        item = body["items"][0] if "items" in body else body
        assert item["next_task"]["description"] == "[redacted]"
    # A failed lookup must leave the same session usable, not transaction-aborted.
    with pursuit_env() as session:
        row = session.get(CommercialPursuit, created["id"])
        assert module._privacy_project_ids(session, row) is None
        assert session.scalar(select(func.count()).select_from(PursuitTask)) == 1
    assert len(failures) == 3


def test_historical_privacy_traversal_is_bounded_and_scoped():
    """No database required: inspect every frontier query and a transitive cycle."""
    from contextlib import nullcontext
    from types import SimpleNamespace

    root, former, earlier, unrelated = (uuid4() for _ in range(4))
    root_project, former_project, earlier_project = (uuid4() for _ in range(3))
    edges = [(uuid4(), root, former), (uuid4(), former, earlier), (uuid4(), earlier, root)]
    queries = []

    class FakeSession:
        def begin_nested(self):
            return nullcontext()

        def execute(self, statement):
            sql = str(statement)
            values = statement.compile().params
            queries.append((sql, values))
            if "need_alias_assertions" in sql:
                assert "WHERE" in sql and "LIMIT" in sql
                assert "state" not in sql  # Historical assertions in every state stay in scope.
                frontier = set(values["alias_need_id_1"])
                assert frontier == set(values["canonical_need_id_1"])
                assert unrelated not in frontier
                result = [edge for edge in edges if edge[1] in frontier or edge[2] in frontier]
            else:
                assert set(values["id_1"]) == {root, former, earlier}
                result = [
                    (root, root_project),
                    (former, former_project),
                    (earlier, earlier_project),
                ]
            return SimpleNamespace(all=lambda: result)

    row = SimpleNamespace(need_id=root, project_id=root_project)
    assert module._privacy_project_ids(FakeSession(), row) == sorted(
        [root_project, former_project, earlier_project], key=str
    )
    assert len(queries) == 3  # Two frontier batches, one need/project lookup.


@pytest.mark.parametrize("failure", ["needs", "assertions", "missing-project", "query-error"])
def test_historical_privacy_traversal_fails_closed_without_database(monkeypatch, failure):
    from contextlib import nullcontext
    from types import SimpleNamespace

    root, other, project = uuid4(), uuid4(), uuid4()
    if failure == "needs":
        monkeypatch.setattr(module, "_MAX_PRIVACY_NEEDS", 1)
    if failure == "assertions":
        monkeypatch.setattr(module, "_MAX_PRIVACY_ALIAS_ASSERTIONS", 1)

    class FakeSession:
        def begin_nested(self):
            return nullcontext()

        def execute(self, statement):
            if failure == "query-error":
                raise RuntimeError("synthetic unavailable graph")
            if "need_alias_assertions" in str(statement):
                result = [(uuid4(), root, other)]
                if failure == "assertions":
                    result.append((uuid4(), root, other))
            else:
                result = [(root, project)]  # Other need's retained project could not be read.
            return SimpleNamespace(all=lambda: result)

    row = SimpleNamespace(need_id=root, project_id=project)
    assert module._privacy_project_ids(FakeSession(), row) is None
    texts = {"note": "Private owner text", "empty": "", "absent": None}
    assert module._private_pursuit_text(FakeSession(), row, texts) == {
        "note": "[redacted]",
        "empty": "",
        "absent": None,
    }


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
