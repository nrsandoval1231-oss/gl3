from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.workspace_changes import review_token
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    ChangeEvent,
    Evidence,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
    WorkspaceChangeAcknowledgment,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    assert test_url.database and test_url.database.endswith("_test")
    assert "corpus" not in test_url.database.casefold()
    assert (test_url.host, test_url.port, test_url.database) != (
        app_url.host,
        app_url.port,
        app_url.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", factory)
    with factory.begin() as session:
        source = Source(
            id="workspace-test-source",
            publisher="Synthetic source",
            endpoint="https://example.test",
            family="construction-permits",
            geography="Synthetic City",
            industries=["construction"],
            retrieval_method="synthetic-test",
            health={"status": "failed", "error": "synthetic fixture"},
        )
        session.add(source)
        session.flush()
        project = Project(
            identity_key=f"workspace-test-{uuid4()}",
            name="Synthetic workspace project",
            location="Synthetic City",
            source_id=source.id,
            external_id=str(uuid4()),
        )
        session.add(project)
        session.flush()
        needs = [
            PowerNeed(
                project_id=project.id,
                activity_key=activity,
                tier="Signal",
                rationale="Synthetic fixture",
                supply="Unknown",
                active=activity == "commissioning",
            )
            for activity in ("construction", "commissioning")
        ]
        session.add_all(needs)
        observation = Observation(
            source_id=source.id,
            external_id=str(uuid4()),
            title="Synthetic retained observation",
            url="https://example.test/synthetic",
            content_hash="a" * 64,
        )
        session.add(observation)
        session.flush()
        project_id = project.id
        need_ids = [need.id for need in needs]
        observation_id = observation.id
        session.add_all(
            NeedObservation(need_id=need.id, observation_id=observation.id) for need in needs
        )
    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session",
        token_for(int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
    )
    yield client, factory, project_id, need_ids, observation_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def _change(observation_id, project_id, *, event_id, activity, before_tier, after_tier, at):
    before = {"value": [{"activity": activity, "tier": before_tier, "required_mw": "10"}]}
    after = {"value": [{"activity": activity, "tier": after_tier, "required_mw": "10"}]}
    return ChangeEvent(
        id=event_id,
        observation_id=observation_id,
        project_id=project_id,
        field_name="power_need",
        kind="power_need_changed",
        prior_state=before,
        new_state=after,
        material=True,
        content_hash=f"{event_id:064x}",
        created_at=at,
    )


def test_change_projection_counts_sibling_transition_and_projects_unreviewed_page(runtime):
    client, factory, project_id, need_ids, observation_id = runtime
    now = datetime.now(UTC)
    with factory.begin() as session:
        # Two sibling transitions in one retained event stay one review item and
        # are classified as changed when their supported transitions differ.
        session.add(
            ChangeEvent(
                id=99,
                observation_id=observation_id,
                project_id=project_id,
                field_name="source_listing",
                kind="source_listing_changed",
                prior_state={"listed": True},
                new_state={"listed": False},
                material=True,
                content_hash="9" * 64,
                created_at=now + timedelta(seconds=1),
            )
        )
        session.add(
            ChangeEvent(
                id=100,
                observation_id=observation_id,
                project_id=project_id,
                field_name="power_need",
                kind="power_need_changed",
                prior_state={
                    "value": [
                        {"activity": "construction", "tier": "Prospect", "required_mw": "10"},
                        {"activity": "commissioning", "tier": "Signal", "required_mw": "5"},
                    ]
                },
                new_state={
                    "value": [
                        {"activity": "construction", "tier": "Lead", "required_mw": "10"},
                        {"activity": "commissioning", "tier": "Signal", "required_mw": "7"},
                    ]
                },
                material=True,
                content_hash="b" * 64,
                created_at=now,
            )
        )
        for index in range(101, 161):
            session.add(
                _change(
                    observation_id,
                    project_id,
                    event_id=index,
                    activity="construction",
                    before_tier="Signal",
                    after_tier="Prospect",
                    at=now - timedelta(seconds=index),
                )
            )

    first = client.get("/api/opportunities/workspace/changes?limit=50")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["first_use"] is True
    assert payload["total_unreviewed"] == 62
    assert payload["counts"]["promoted"] == 60
    assert payload["counts"]["changed"] == 1
    assert payload["counts"]["review_exception"] == 1
    absence = next(item for item in payload["items"] if item["event_key"] == "change:99")
    assert absence["category"] == "review_exception"
    assert absence["category"] != "closed"
    mixed = next(item for item in payload["items"] if item["event_key"] == "change:100")
    assert mixed["category"] == "changed"
    assert {item["id"] for item in mixed["needs"]} == {str(value) for value in need_ids}
    assert payload["source_health_exceptions"][0]["status"] == "failed"

    # A late lower-ID event remains visible in the chronological audit projection.
    with factory.begin() as session:
        session.add(
            _change(
                observation_id,
                project_id,
                event_id=1,
                activity="commissioning",
                before_tier="Signal",
                after_tier="Prospect",
                at=now + timedelta(seconds=1),
            )
        )
    later = client.get("/api/opportunities/workspace/changes?limit=50")
    assert later.status_code == 200, later.text
    assert "change:1" in {item["event_key"] for item in later.json()["items"]}
    assert later.json()["total_unreviewed"] == 63


def test_call_fact_journal_shows_assertion_changes_and_historical_need(runtime):
    client, factory, project_id, need_ids, _observation_id = runtime
    need_id = need_ids[0]
    fact_id, corrected_id = uuid4(), uuid4()
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        now = datetime.now(UTC)
        prior = CallFactVersion(
            id=fact_id,
            need_id=need_id,
            project_id=project_id,
            client_id=uuid4(),
            activity_key="construction",
            facility_scope="Synthetic City",
            fact_type="demand",
            value={"mw": "10"},
            reporter_name="Synthetic contact",
            confirmation_channel="customer_call",
            confirmed_at=now - timedelta(days=1),
            effective_from=now - timedelta(days=1),
            content_hash="c" * 64,
            recorded_by="synthetic-test",
            predecessor_id=None,
            source_reference=None,
        )
        corrected = CallFactVersion(
            id=corrected_id,
            need_id=need_id,
            project_id=project_id,
            client_id=uuid4(),
            activity_key="construction",
            facility_scope="Synthetic City",
            fact_type="demand",
            value={"mw": "12"},
            reporter_name="Synthetic contact",
            confirmation_channel="customer_call",
            confirmed_at=now,
            effective_from=now,
            content_hash="d" * 64,
            recorded_by="synthetic-test",
            predecessor_id=fact_id,
            source_reference=None,
        )
        session.add_all([prior, corrected])
        session.flush()
        session.add_all(
            [
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=fact_id,
                    version=1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=0,
                    reason="Synthetic accepted assertion",
                    content_hash="e" * 64,
                    actor="synthetic operator",
                    created_at=now - timedelta(days=1),
                ),
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=fact_id,
                    version=2,
                    client_id=uuid4(),
                    decision="superseded",
                    expected_version=1,
                    reason="Internal companion",
                    content_hash="f" * 64,
                    actor="synthetic system",
                    created_at=now - timedelta(hours=1),
                ),
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=corrected_id,
                    version=3,
                    client_id=uuid4(),
                    decision="corrected",
                    expected_version=2,
                    reason="Synthetic correction",
                    content_hash="1" * 64,
                    actor="synthetic operator",
                    created_at=now,
                ),
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=corrected_id,
                    version=4,
                    client_id=uuid4(),
                    decision="retracted",
                    expected_version=3,
                    reason="Synthetic retraction",
                    content_hash="2" * 64,
                    actor="synthetic operator",
                    created_at=now + timedelta(seconds=1),
                ),
            ]
        )
        need.active = False

    response = client.get("/api/opportunities/workspace/changes?limit=50")
    assert response.status_code == 200, response.text
    facts = [item for item in response.json()["items"] if item["event_key"].startswith("fact:")]
    assert {item["decision"] for item in facts} == {"accepted", "corrected", "retracted"}
    corrected = next(item for item in facts if item["decision"] == "corrected")
    assert corrected["actor"] == "synthetic operator"
    assert corrected["confirmed_at"]
    assert corrected["before_state"]["value"] == {"mw": "10"}
    assert corrected["after_state"]["value"] == {"mw": "12"}
    assert corrected["before_state"]["effective_from"] == (now - timedelta(days=1)).isoformat()
    assert corrected["after_state"]["effective_from"] == now.isoformat()
    assert corrected["before_state"]["effective_until"] is None
    assert corrected["after_state"]["effective_until"] is None
    assert corrected["before_version"] == 1
    assert corrected["after_version"] == 3
    assert corrected["needs"][0]["id"] == str(need_id)
    retracted = next(item for item in facts if item["decision"] == "retracted")
    assert retracted["before_state"]["value"] == {"mw": "12"}
    assert retracted["after_state"] is None
    assert retracted["before_version"] == 3
    assert retracted["after_version"] == 4

    history = client.get(f"/api/opportunities/needs/{need_id}/history")
    assert history.status_code == 200, history.text
    assert history.json()["active"] is False
    current_history = client.get(f"/api/opportunities/needs/{need_ids[1]}/history")
    assert current_history.status_code == 409
    missing = client.get("/api/opportunities/needs/00000000-0000-0000-0000-000000000001/history")
    assert missing.status_code == 404


@pytest.mark.parametrize("changed_field", ["effective_from", "effective_until", None])
def test_date_only_fact_correction_is_material_only_when_effective_window_changes(
    runtime, changed_field
):
    client, factory, project_id, need_ids, _observation_id = runtime
    need_id = need_ids[0]
    fact_id, corrected_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    old_start, old_until = now - timedelta(days=2), now + timedelta(days=2)
    new_start = old_start + timedelta(hours=1) if changed_field == "effective_from" else old_start
    new_until = old_until - timedelta(hours=1) if changed_field == "effective_until" else old_until
    with factory.begin() as session:
        session.add_all(
            [
                CallFactVersion(
                    id=fact_id,
                    need_id=need_id,
                    project_id=project_id,
                    client_id=uuid4(),
                    activity_key="construction",
                    facility_scope="Synthetic City",
                    fact_type="timing",
                    value={"start_date": "2027-01-01"},
                    reporter_name="Synthetic contact",
                    confirmation_channel="customer_call",
                    confirmed_at=now - timedelta(days=1),
                    effective_from=old_start,
                    effective_until=old_until,
                    content_hash="a" * 64,
                    recorded_by="synthetic-test",
                    predecessor_id=None,
                    source_reference=None,
                ),
                CallFactVersion(
                    id=corrected_id,
                    need_id=need_id,
                    project_id=project_id,
                    client_id=uuid4(),
                    activity_key="construction",
                    facility_scope="Synthetic City",
                    fact_type="timing",
                    value={"start_date": "2027-01-01"},
                    reporter_name="Synthetic contact",
                    confirmation_channel="customer_call",
                    confirmed_at=now,
                    effective_from=new_start,
                    effective_until=new_until,
                    content_hash="b" * 64,
                    recorded_by="synthetic-test",
                    predecessor_id=fact_id,
                    source_reference=None,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=fact_id,
                    version=1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=0,
                    reason="Synthetic accepted assertion",
                    content_hash="c" * 64,
                    actor="synthetic operator",
                    created_at=now - timedelta(days=1),
                ),
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=corrected_id,
                    version=2,
                    client_id=uuid4(),
                    decision="corrected",
                    expected_version=1,
                    reason="Synthetic timing correction",
                    content_hash="d" * 64,
                    actor="synthetic operator",
                    created_at=now,
                ),
            ]
        )

    response = client.get("/api/opportunities/workspace/changes?limit=50")
    assert response.status_code == 200, response.text
    corrected_items = [
        item
        for item in response.json()["items"]
        if item.get("decision") == "corrected" and item["fact_version_id"] == str(corrected_id)
    ]
    if changed_field:
        assert len(corrected_items) == 1
        correction = corrected_items[0]
        assert correction["event_key"].startswith("fact:")
        assert correction["before_state"]["effective_from"] == old_start.isoformat()
        assert correction["after_state"]["effective_from"] == new_start.isoformat()
        assert correction["before_state"]["effective_until"] == old_until.isoformat()
        assert correction["after_state"]["effective_until"] == new_until.isoformat()
    else:
        assert corrected_items == []






def test_workspace_change_get_has_constant_query_count_with_acknowledged_history(runtime):
    client, factory, project_id, need_ids, observation_id = runtime
    now = datetime.now(UTC)
    with factory.begin() as session:
        source = Evidence(
            observation_id=observation_id,
            content_hash="e" * 64,
            title="Synthetic retained evidence",
            url="https://example.test/workspace-evidence",
        )
        session.add(source)
        session.flush()
        sibling_transition = ChangeEvent(
            id=1,
            observation_id=observation_id,
            project_id=project_id,
            evidence_id=source.id,
            field_name="power_need",
            kind="power_need_changed",
            prior_state={
                "value": [
                    {"activity": "construction", "tier": "Signal", "required_mw": "10"},
                    {"activity": "commissioning", "tier": "Signal", "required_mw": "10"},
                ]
            },
            new_state={
                "value": [
                    {"activity": "construction", "tier": "Prospect", "required_mw": "10"},
                    {"activity": "commissioning", "tier": "Prospect", "required_mw": "10"},
                ]
            },
            material=True,
            content_hash="1" * 64,
            created_at=now,
        )
        history = [
            ChangeEvent(
                id=event_id,
                observation_id=observation_id,
                project_id=project_id,
                field_name="project_name",
                kind="project_changed",
                prior_state={"value": f"before {event_id}"},
                new_state={"value": f"after {event_id}"},
                material=True,
                content_hash=f"{event_id:064x}",
                created_at=now - timedelta(seconds=event_id),
            )
            for event_id in range(2, 3060)
        ]
        session.add_all([sibling_transition, *history])
        session.add_all(
            WorkspaceChangeAcknowledgment(
                event_key=f"change:{event_id}",
                reviewed_at=now,
                review_token="a" * 64,
            )
            for event_id in range(51, 3060)
        )

    engine = factory.kw["bind"]
    statements = []

    def count_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = client.get("/api/opportunities/workspace/changes?limit=50&offset=0")
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_unreviewed"] == 50
    assert payload["counts"]["promoted"] == 1
    assert payload["counts"]["changed"] == 49
    assert len(payload["items"]) == 50
    expected_keys = [f"change:{event_id}" for event_id in range(1, 51)]
    assert [item["event_key"] for item in payload["items"]] == expected_keys
    assert payload["token"] == review_token(UUID(payload["baseline_identity"]), expected_keys)
    assert payload["next_offset"] is None
    assert payload["items"][0]["before_state"]["value"][0]["tier"] == "Signal"
    assert payload["items"][0]["after_state"]["value"][0]["tier"] == "Prospect"
    assert {item["id"] for item in payload["items"][0]["needs"]} == {
        str(need_id) for need_id in need_ids
    }
    assert payload["items"][0]["sources"][0]["content_hash"] == "e" * 64
    assert len(statements) < 30, f"expected bounded query count, observed {len(statements)}"
