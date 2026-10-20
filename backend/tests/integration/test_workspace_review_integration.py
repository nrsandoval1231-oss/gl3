from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    ChangeEvent,
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


def test_change_projection_counts_sibling_transition_and_review_exact_page(runtime):
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

    receipt = client.post(
        "/api/opportunities/workspace/changes/review",
        json={
            "baseline_identity": payload["baseline_identity"],
            "token": payload["token"],
            "limit": 50,
            "offset": 0,
        },
        headers={"origin": "http://testserver"},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["reviewed_count"] == 50
    assert (
        client.post(
            "/api/opportunities/workspace/changes/review",
            json={
                "baseline_identity": payload["baseline_identity"],
                "token": payload["token"],
                "limit": 50,
                "offset": 0,
            },
            headers={"origin": "http://testserver"},
        ).json()
        == receipt.json()
    )
    with factory() as session:
        assert len(session.scalars(select(WorkspaceChangeAcknowledgment)).all()) == 50

    # A late lower-ID event is reviewed by exact identity, never a max-ID fence.
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
    assert later.json()["total_unreviewed"] == 13


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


def test_review_rejects_changed_page_and_cross_origin(runtime):
    client, factory, project_id, _need_ids, observation_id = runtime
    api = import_module("gridlens.api.app")
    anonymous = TestClient(api.app)
    assert anonymous.get("/api/opportunities/workspace/changes").status_code == 401
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            _change(
                observation_id,
                project_id,
                event_id=50,
                activity="construction",
                before_tier="Signal",
                after_tier="Prospect",
                at=now,
            )
        )
    payload = client.get("/api/opportunities/workspace/changes").json()
    body = {
        "baseline_identity": payload["baseline_identity"],
        "token": "0" * 64,
        "limit": 50,
        "offset": 0,
    }
    assert (
        client.post(
            "/api/opportunities/workspace/changes/review",
            json=body,
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/opportunities/workspace/changes/review",
            json=body,
            headers={"origin": "http://testserver"},
        ).status_code
        == 409
    )


def test_concurrent_first_review_and_overlapping_pages_are_bounded(runtime):
    client, factory, project_id, _need_ids, observation_id = runtime
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add_all(
            _change(
                observation_id,
                project_id,
                event_id=event_id,
                activity="construction",
                before_tier="Signal",
                after_tier="Prospect",
                at=now - timedelta(seconds=event_id),
            )
            for event_id in range(1, 101)
        )

    snapshot = client.get("/api/opportunities/workspace/changes?limit=50&offset=0").json()
    body = {
        "baseline_identity": snapshot["baseline_identity"],
        "token": snapshot["token"],
        "limit": 50,
        "offset": 0,
    }
    first_barrier = Barrier(3)

    def post_review(request_body, barrier):
        worker = TestClient(import_module("gridlens.api.app").app)
        worker.cookies.set(
            "gridlens_session",
            token_for(int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
        )
        barrier.wait(timeout=10)
        return worker.post(
            "/api/opportunities/workspace/changes/review",
            json=request_body,
            headers={"origin": "http://testserver"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = [pool.submit(post_review, body, first_barrier) for _ in range(2)]
        first_barrier.wait(timeout=10)
        first_responses = [future.result(timeout=30) for future in first]
    assert [response.status_code for response in first_responses] == [200, 200]
    assert first_responses[0].json() == first_responses[1].json()
    first_reviewed_keys = set(first_responses[0].json()["event_keys"])
    with factory() as session:
        assert len(session.scalars(select(WorkspaceChangeAcknowledgment)).all()) == 50

    second_page = client.get("/api/opportunities/workspace/changes?limit=50&offset=25").json()
    current_first_page = client.get("/api/opportunities/workspace/changes?limit=50&offset=0").json()
    overlap_body = {
        "baseline_identity": second_page["baseline_identity"],
        "token": second_page["token"],
        "limit": 50,
        "offset": 25,
    }
    first_page_body = {
        "baseline_identity": current_first_page["baseline_identity"],
        "token": current_first_page["token"],
        "limit": 50,
        "offset": 0,
    }
    overlap_barrier = Barrier(3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        overlapping = [
            pool.submit(post_review, request_body, overlap_barrier)
            for request_body in (first_page_body, overlap_body)
        ]
        overlap_barrier.wait(timeout=10)
        overlap_responses = [future.result(timeout=30) for future in overlapping]
    assert sorted(response.status_code for response in overlap_responses) == [200, 409]
    overlap_receipt = next(
        response.json() for response in overlap_responses if response.status_code == 200
    )
    with factory() as session:
        acknowledgments = session.scalars(select(WorkspaceChangeAcknowledgment)).all()
        acknowledged_keys = {item.event_key for item in acknowledgments}
        assert acknowledged_keys == first_reviewed_keys | set(overlap_receipt["event_keys"])
        assert len(acknowledgments) == len(acknowledged_keys)
