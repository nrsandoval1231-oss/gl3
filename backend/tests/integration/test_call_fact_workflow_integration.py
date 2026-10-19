from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    Evidence,
    Interpretation,
    NeedObservation,
    NeedWorkflowStatusEvent,
    Observation,
    PowerNeed,
    Project,
    Pursuit,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings


@pytest.fixture
def runtime(monkeypatch):
    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    assert test_url.database and (
        test_url.database == "test" or test_url.database.endswith("_test")
    ), (
        "Refusing destructive setup without an explicit disposable *_test database"
    )
    assert "corpus" not in test_url.database.lower(), (
        "Refusing destructive setup against a retained corpus database"
    )
    assert (test_url.host, test_url.port, test_url.database) != (
        app_url.host,
        app_url.port,
        app_url.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("""CREATE OR REPLACE FUNCTION reject_immutable_history_mutation()
            RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'append-only history cannot be updated or deleted';
            END; $$ LANGUAGE plpgsql""")
        )
        for table in ("call_fact_versions", "call_fact_decisions", "need_workflow_status_events"):
            connection.execute(
                text(
                    f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()"
                )
            )
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", factory)
    with factory.begin() as session:
        session.add(
            Source(
                id="a6-test-source",
                publisher="Synthetic City",
                endpoint="https://example.test",
                family="construction-permits",
                geography="Test City",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        project = Project(
            identity_key=f"a6-project-{uuid4()}",
            name="Synthetic Test Facility",
            location="Test City",
            source_id="a6-test-source",
            external_id="synthetic-1",
        )
        session.add(project)
        session.flush()
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Signal",
            rationale="Synthetic current support unavailable",
            supply="Unknown",
        )
        session.add(need)
        session.flush()
        pursuit = Pursuit(
            identity_key=f"a6-pursuit-{uuid4()}",
            project_id=project.id,
            project_ids=[str(project.id)],
            snapshot={},
            research_status="not_researched",
        )
        session.add(pursuit)
        session.flush()
        need_id, project_id, pursuit_id = need.id, project.id, pursuit.id
    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session",
        token_for(int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
    )
    yield client, factory, need_id, project_id, pursuit_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def _body(project_id, pursuit_id, *, client_id=None, expected_version=0, predecessor_id=None):
    now = datetime.now(UTC)
    return {
        "client_id": str(client_id or uuid4()),
        "project_id": str(project_id),
        "pursuit_id": str(pursuit_id),
        "expected_version": expected_version,
        "predecessor_id": str(predecessor_id) if predecessor_id else None,
        "activity_key": "construction",
        "facility_scope": "Test City",
        "fact_type": "demand",
        "value": {"mw": "20", "basis": "Synthetic operator-confirmed fixture"},
        "reporter_name": "Synthetic Account Manager",
        "reporter_organization": "Synthetic Owner LLC",
        "reporter_role": "Project owner",
        "confirmation_channel": "customer_call",
        "source_reference": "synthetic-test-call-1",
        "source_date": now.date().isoformat(),
        "confirmed_at": now.isoformat(),
        "effective_from": now.isoformat(),
        "effective_until": (now + timedelta(days=90)).isoformat(),
    }


def test_fact_read_exposes_typed_unavailable_timing_target_without_current_source(runtime):
    client, _factory, need_id, _project_id, _pursuit_id = runtime
    response = client.get(f"/api/needs/{need_id}/facts")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["current_fact_version"] == 0
    target = payload["current_reported_timing_correction_target"]
    assert target["available"] is False
    assert target["unavailable_reason"] == "no_current_admitted_lead"
    assert target["source_semantic_hash"] is None
    assert target["source_evidence_hash"] is None
    assert target["retained_evidence_id"] is None


def test_fact_draft_accept_correction_are_append_only_and_nonpromoting_without_source(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    headers = {"origin": "http://testserver"}
    draft_body = _body(project_id, pursuit_id)
    first = client.post(f"/api/needs/{need_id}/facts", json=draft_body, headers=headers)
    assert first.status_code == 200, first.text
    fact_id = first.json()["id"]
    assert first.json()["decision"] == "draft"
    assert (
        client.post(f"/api/needs/{need_id}/facts", json=draft_body, headers=headers).json()["id"]
        == fact_id
    )

    accepted = client.post(
        f"/api/needs/{need_id}/facts/{fact_id}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 1,
            "decision": "accepted",
            "reason": "Synthetic explicit acceptance",
        },
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tier"] == "Signal"
    assert accepted.json()["active"] is True

    correction_body = _body(project_id, pursuit_id, expected_version=2, predecessor_id=fact_id)
    correction_body["value"] = {"mw": "21", "basis": "Synthetic correction"}
    successor = client.post(f"/api/needs/{need_id}/facts", json=correction_body, headers=headers)
    assert successor.status_code == 200, successor.text
    corrected = client.post(
        f"/api/needs/{need_id}/facts/{successor.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 3,
            "decision": "corrected",
            "reason": "Corrected synthetic MW",
        },
        headers=headers,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["tier"] == "Signal"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CallFactVersion)) == 2
        assert session.scalar(select(func.count()).select_from(CallFactDecision)) == 5
        assert session.scalar(select(PowerNeed).where(PowerNeed.id == need_id)).tier == "Signal"
        prior_state = session.scalars(
            select(CallFactDecision)
            .where(CallFactDecision.fact_version_id == fact_id)
            .order_by(CallFactDecision.version.desc())
        ).all()
        assert [row.decision for row in prior_state] == ["superseded", "accepted", "draft"]
        from gridlens.ingestion.service import load_current_need_operator_inputs

        facts_by_need, statuses_by_need = load_current_need_operator_inputs(session, [need_id])
        assert [row.id for row in facts_by_need[need_id]] == [UUID(successor.json()["id"])]
        assert need_id not in statuses_by_need
        with pytest.raises(Exception, match="append-only history"):
            session.execute(
                CallFactDecision.__table__.update()
                .where(CallFactDecision.fact_version_id == fact_id)
                .values(reason="must not update")
            )
            session.flush()


@pytest.mark.parametrize("target_exists", [True, False])
def test_fact_decision_replay_cannot_acknowledge_a_different_fact(runtime, target_exists):
    client, factory, need_id, project_id, pursuit_id = runtime
    headers = {"origin": "http://testserver"}
    first = client.post(
        f"/api/needs/{need_id}/facts", json=_body(project_id, pursuit_id), headers=headers
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/needs/{need_id}/facts",
        json=_body(project_id, pursuit_id, expected_version=1),
        headers=headers,
    )
    assert second.status_code == 200, second.text
    first_id, second_id = first.json()["id"], second.json()["id"]
    decision = {
        "client_id": str(uuid4()),
        "expected_version": 2,
        "decision": "accepted",
        "reason": "Synthetic explicit acceptance of the first fact only",
    }
    accepted = client.post(
        f"/api/needs/{need_id}/facts/{first_id}/decision", json=decision, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    target_id = second_id if target_exists else str(uuid4())
    wrong_target = client.post(
        f"/api/needs/{need_id}/facts/{target_id}/decision", json=decision, headers=headers
    )
    assert wrong_target.status_code == 409, wrong_target.text
    assert "different fact version" in wrong_target.json()["detail"]
    replay = client.post(
        f"/api/needs/{need_id}/facts/{first_id}/decision", json=decision, headers=headers
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == accepted.json()["id"]
    assert replay.json()["version"] == accepted.json()["version"]
    history = client.get(f"/api/needs/{need_id}/facts").json()
    assert history["current_fact_version"] == 3
    assert {row["id"]: row["decision"] for row in history["items"]} == {
        first_id: "accepted", second_id: "draft"
    }
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CallFactDecision)) == 3


def test_status_unknown_seven_states_idempotency_and_tier_independence(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    headers = {"origin": "http://testserver"}
    initial = client.get(f"/api/needs/{need_id}/workflow-status")
    assert initial.status_code == 200
    assert initial.json()["status"] == "UNKNOWN"
    statuses = ["New", "Investigating", "Contacted", "Qualified", "Won", "Lost", "Closed"]
    first_id = uuid4()
    for expected_version, status in enumerate(statuses):
        client_id = first_id if expected_version == 0 else uuid4()
        response = client.post(
            f"/api/needs/{need_id}/workflow-status",
            json={
                "client_id": str(client_id),
                "project_id": str(project_id),
                "pursuit_id": str(pursuit_id),
                "expected_version": expected_version,
                "status": status,
                "reason": f"Synthetic operator reason for {status}",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == expected_version + 1
    replay = client.post(
        f"/api/needs/{need_id}/workflow-status",
        json={
            "client_id": str(first_id),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": 0,
            "status": "New",
            "reason": "Synthetic operator reason for New",
        },
        headers=headers,
    )
    assert replay.status_code == 200
    stale = client.post(
        f"/api/needs/{need_id}/workflow-status",
        json={
            "client_id": str(uuid4()),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": 6,
            "status": "Closed",
            "reason": "stale request",
        },
        headers=headers,
    )
    assert stale.status_code == 409
    changed_replay = client.post(
        f"/api/needs/{need_id}/workflow-status",
        json={
            "client_id": str(first_id),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": 0,
            "status": "Won",
            "reason": "different content",
        },
        headers=headers,
    )
    assert changed_replay.status_code == 409
    current = client.get(f"/api/needs/{need_id}/workflow-status")
    assert current.json()["status"] == "Closed"
    assert len(current.json()["events"]) == 7
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need.tier == "Signal" and need.active is True
        assert session.scalar(select(func.count()).select_from(NeedWorkflowStatusEvent)) == 7
        from gridlens.ingestion.service import load_current_need_operator_inputs

        _facts, status_by_need = load_current_need_operator_inputs(session, [need_id])
        assert status_by_need[need_id].status == "Closed"


def test_fact_and_status_routes_reject_wrong_exact_scope(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    body = _body(project_id, pursuit_id)
    body["project_id"] = str(uuid4())
    response = client.post(
        f"/api/needs/{need_id}/facts", json=body, headers={"origin": "http://testserver"}
    )
    assert response.status_code == 404
    for field, value in (("activity_key", "drilling"), ("facility_scope", "Another City")):
        invalid = _body(project_id, pursuit_id)
        invalid[field] = value
        mismatch = client.post(
            f"/api/needs/{need_id}/facts",
            json=invalid,
            headers={"origin": "http://testserver"},
        )
        assert mismatch.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CallFactVersion)) == 0


def test_concurrent_workflow_updates_serialize_by_exact_need(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    barrier = Barrier(2)

    def submit(status: str):
        barrier.wait()
        return client.post(
            f"/api/needs/{need_id}/workflow-status",
            json={
                "client_id": str(uuid4()),
                "project_id": str(project_id),
                "pursuit_id": str(pursuit_id),
                "expected_version": 0,
                "status": status,
                "reason": f"Synthetic concurrent {status} decision",
            },
            headers={"origin": "http://testserver"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ("Investigating", "Contacted")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(NeedWorkflowStatusEvent)) == 1


def test_current_public_support_bounds_fact_qualification_and_reassessment(runtime, monkeypatch):
    # Exercise the live projection path independently of the optional saved-browse
    # deployment mode used by the current shell environment.
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    client, factory, need_id, project_id, pursuit_id = runtime
    with factory.begin() as session:
        sibling = PowerNeed(
            project_id=project_id,
            activity_key="operations",
            tier="Signal",
            rationale="Synthetic sibling need remains independent",
            supply="Unknown",
        )
        session.add(sibling)
        session.flush()
        sibling_need_id = sibling.id
    content_hash = "a" * 64
    source_abstract = (
        "description: Test City construction requires 20 to 25 MW. "
        "Power supply for Test City construction is insufficient.\n"
        "address: Test City"
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = Observation(
            source_id="a6-test-source",
            external_id="synthetic-permit-1",
            title="Synthetic construction permit for Synthetic Test Facility",
            abstract=source_abstract,
            published_at=datetime.now(UTC).date(),
            url="https://example.test/synthetic-permit-1",
            content_hash=content_hash,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=content_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime.now(UTC),
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=content_hash,
            status="accepted",
            assessment={
                "decision": "accepted",
                "semantic_hash": content_hash,
                "evidence_hash": content_hash,
                "project_identity_key": project.identity_key,
                "power_activity": "construction",
                "tier": "Prospect",
                "demand_mw": "20 to 25 MW",
                "demand_quote": "Test City construction requires 20 to 25 MW.",
                "supply_quote": "Power supply for Test City construction is insufficient.",
                "reason": "Current retained exact-site permit support.",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all(
            [
                evidence,
                interpretation,
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )

    headers = {"origin": "http://testserver"}
    event_version = 0
    range_draft_body = _body(project_id, pursuit_id, expected_version=event_version)
    range_draft_body["value"] = {"mw": "20 to 25 MW"}
    range_draft = client.post(
        f"/api/needs/{need_id}/facts", json=range_draft_body, headers=headers
    )
    assert range_draft.status_code == 200, range_draft.text
    assert range_draft.json()["value"] == {"mw_min": "20", "mw_max": "25"}
    equivalent_range_body = deepcopy(range_draft_body)
    equivalent_range_body["value"] = {"mw_min": "20", "mw_max": "25"}
    same_range_draft = client.post(
        f"/api/needs/{need_id}/facts", json=equivalent_range_body, headers=headers
    )
    assert same_range_draft.status_code == 200, same_range_draft.text
    assert same_range_draft.json()["id"] == range_draft.json()["id"]
    assert same_range_draft.json()["content_hash"] == range_draft.json()["content_hash"]
    event_version += 1
    initial_browse = client.get("/api/opportunities?tier=Prospect")
    assert initial_browse.status_code == 200, initial_browse.text
    assert any(str(item["id"]) == str(need_id) for item in initial_browse.json())
    initial_cohort = initial_browse.headers["x-cohort-token"]
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None
        original_updated_at = need.updated_at

    def accept(fact_type: str, value: dict):
        nonlocal event_version
        body = _body(project_id, pursuit_id, expected_version=event_version)
        body["fact_type"] = fact_type
        body["value"] = value
        body["effective_from"] = "2026-01-01T00:00:00+00:00"
        body["effective_until"] = "2027-03-04T00:00:00+00:00"
        draft = client.post(f"/api/needs/{need_id}/facts", json=body, headers=headers)
        assert draft.status_code == 200, draft.text
        event_version += 1
        decision = client.post(
            f"/api/needs/{need_id}/facts/{draft.json()['id']}/decision",
            json={
                "client_id": str(uuid4()),
                "expected_version": event_version,
                "decision": "accepted",
                "reason": f"Synthetic accepted {fact_type} report",
            },
            headers=headers,
        )
        assert decision.status_code == 200, decision.text
        event_version += 1
        return decision

    # The current official source already supports Prospect. These facts add
    # only the missing Lead gates; no duplicate demand or shortage assertion is needed.
    assert accept(
        "timing", {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31}
    ).json()["tier"] == "Prospect"
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None
        # Hold the legacy row timestamp constant to prove the token binds current
        # accepted facts directly, rather than relying on incidental row updates.
        need.updated_at = original_updated_at
    changed_fact_browse = client.get("/api/opportunities?tier=Prospect")
    assert changed_fact_browse.status_code == 200, changed_fact_browse.text
    assert changed_fact_browse.headers["x-cohort-token"] != initial_cohort
    stale_fact_page = client.get(
        f"/api/opportunities?tier=Prospect&cohort_token={initial_cohort}"
    )
    assert stale_fact_page.status_code == 409
    initial_supply = accept("suitable_supply", {"mw": "5", "quality": "suitable"}).json()
    lead_result = accept(
        "buyer", {"organization": "Synthetic Owner LLC", "role": "project owner"}
    ).json()
    assert lead_result["tier"] == "Lead"
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["tier"] == "Lead"
        assert effective["qualified_remaining_gap"]["remaining_mw_min"] == "15"
        assert effective["qualified_remaining_gap"]["remaining_mw_max"] == "20"
        assert effective["required_mw"] == "20 to 25 MW"
        gap = effective["qualified_remaining_gap"]
        assert effective["start_window"] == "2027-01-01 to 2027-02-01"
        assert effective["duration"] == "31 days"
        assert gap["start_window"] == effective["start_window"]
        assert gap["duration"] == effective["duration"]
        assert gap["selected_activity_interval_start"] == "2027-01-01T00:00:00+00:00"
        assert gap["selected_activity_interval_end_exclusive"] == "2027-03-04T00:00:00+00:00"

    closure_body = _body(project_id, pursuit_id, expected_version=event_version)
    closure_body["fact_type"] = "closure"
    closure_body["value"] = {"state": "adequate_supply"}
    closure = client.post(
        f"/api/needs/{need_id}/facts", json=closure_body, headers=headers
    )
    assert closure.status_code == 200, closure.text
    closure_decision = client.post(
        f"/api/needs/{need_id}/facts/{closure.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version + 1,
            "decision": "accepted",
            "reason": "Synthetic adequate supply closure",
        },
        headers=headers,
    )
    assert closure_decision.status_code == 200, closure_decision.text
    assert closure_decision.json()["active"] is False
    retracted = client.post(
        f"/api/needs/{need_id}/facts/{closure.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version + 2,
            "decision": "retracted",
            "reason": "Synthetic closure correction",
        },
        headers=headers,
    )
    assert retracted.status_code == 200, retracted.text
    assert retracted.json()["tier"] == "Lead"
    assert retracted.json()["active"] is True
    event_version += 3

    # Add a source-consistent demand version so a subsequent source correction
    # can exercise the established conflict/demotion/reassessment path.
    # A point confirmation inside the current public interval narrows the
    # calculation without replacing the retained Reported source claim.
    point_demand = accept("demand", {"mw": "22"}).json()
    assert point_demand["tier"] == "Lead"
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None
        assert effective["qualified_remaining_gap"]["remaining_mw"] == "17"
        # This assertion exposes whether the fact-assisted calculation is
        # actually projected to the persisted/read-back required_mw field.
        assert effective["required_mw"] == "22 MW"
        assert need.required_mw == "22 MW"
        gap = effective["qualified_remaining_gap"]
        assert gap["required_mw_basis"] == "User-confirmed intersection"
        assert gap["source_demand_mw"] == "20 to 25 MW"
        assert gap["user_confirmed_demand_mw"] == "22 MW"
        assert gap["demand_fact_id"] == point_demand["fact_version_id"]
        assert gap["demand_fact_hash"] == point_demand["content_hash"]

    range_body = _body(
        project_id,
        pursuit_id,
        expected_version=event_version,
        predecessor_id=UUID(point_demand["fact_version_id"]),
    )
    range_body["fact_type"] = "demand"
    range_body["value"] = {"mw_min": "21", "mw_max": "24"}
    range_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    range_body["effective_until"] = "2027-03-04T00:00:00+00:00"
    range_draft = client.post(f"/api/needs/{need_id}/facts", json=range_body, headers=headers)
    assert range_draft.status_code == 200, range_draft.text
    assert range_draft.json()["value"] == {"mw_min": "21", "mw_max": "24"}
    event_version += 1
    range_decision = client.post(
        f"/api/needs/{need_id}/facts/{range_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version,
            "decision": "corrected",
            "reason": "Synthetic corrected demand interval",
        },
        headers=headers,
    )
    assert range_decision.status_code == 200, range_decision.text
    assert range_decision.json()["tier"] == "Lead"
    event_version += 2
    corrected_demand = range_decision.json()
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None
        assert effective["required_mw"] == "21 to 24 MW"
        gap = effective["qualified_remaining_gap"]
        assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == ("16", "19")
        assert gap["demand_fact_id"] == corrected_demand["fact_version_id"]
        assert gap["demand_fact_hash"] == corrected_demand["content_hash"]

    page = client.get("/api/opportunities?tier=Lead&limit=50")
    assert page.status_code == 200, page.text
    page_card = next(item for item in page.json() if str(item["id"]) == str(need_id))
    assert page_card["required_mw"] == "21 to 24 MW"
    assert page_card["commercial_size_status"] == "at_or_above_floor"
    assert page_card["qualified_remaining_gap"] == gap
    assert page_card["qualification_version"] == effective["qualification_version"]
    cohort = page.headers["x-cohort-token"]
    detail = client.get(
        f"/api/opportunities/needs/{need_id}?tier=Lead&cohort_token={cohort}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["required_mw"] == "21 to 24 MW"
    assert detail.json()["qualified_remaining_gap"] == gap
    assert detail.json()["qualification_version"] == effective["qualification_version"]
    group_id = page_card["group_id"]
    group_page = client.get(
        f"/api/opportunity-groups/{group_id}?tier=Lead&cohort_token={cohort}"
    )
    assert group_page.status_code == 200, group_page.text
    grouped_card = next(
        item for item in group_page.json()["items"] if str(item["id"]) == str(need_id)
    )
    assert grouped_card["required_mw"] == "21 to 24 MW"
    csv = client.get(
        f"/api/opportunities/export.csv?tier=Lead&limit=50&cohort_token={cohort}"
    )
    assert csv.status_code == 200, csv.text
    assert "21 to 24 MW" in csv.text

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        evidence = session.scalar(select(Evidence))
        assert (
            need is not None
            and project is not None
            and observation is not None
            and interpretation is not None
        )
        assert evidence is not None and evidence.content_hash == content_hash

        # Append a contradictory current source version; the accepted operator
        # fact remains historical and forces an explicit conflict demotion.
        conflicting_hash = "b" * 64
        observation.content_hash = conflicting_hash
        observation.abstract = (
            "description: Test City construction requires 30 MW. "
            "Power supply for Test City construction is insufficient.\n"
            "address: Test City"
        )
        session.add(
            Evidence(
                observation_id=observation.id,
                content_hash=conflicting_hash,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                published_at=observation.published_at,
                observed_at=datetime.now(UTC),
            )
        )
        interpretation.content_hash = conflicting_hash
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": conflicting_hash,
            "evidence_hash": conflicting_hash,
            "tier": "Prospect",
            "demand_mw": "30 MW",
            "demand_quote": "source explicitly requires 30 MW",
            "supply_quote": "source explicitly reports insufficient supply",
        }
        from gridlens.ingestion.service import _apply_current_qualification

        _apply_current_qualification(session, need, project)
        assert need.tier == "Signal"
        assert (
            need.rationale
            == "Accepted operator demand conflicts with current public source support."
        )

        # Withdrawal removes current support without deleting either evidence
        # version or accepted fact history.
        interpretation.status = "withdrawn"
        _apply_current_qualification(session, need, project)
        assert need.tier == "Signal" and need.required_mw is None

        # A later compatible source version restores the existing fact-aware
        # Lead through the same canonical replay path.
        restored_hash = content_hash
        observation.content_hash = restored_hash
        observation.abstract = source_abstract
        interpretation.content_hash = restored_hash
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": restored_hash,
            "evidence_hash": restored_hash,
            "tier": "Signal",
            "demand_mw": "20 to 25 MW",
            "demand_quote": "Test City construction requires 20 to 25 MW.",
            "supply_quote": "Power supply for Test City construction is insufficient.",
            "reason": "Compatible current source support restored.",
        }
        interpretation.status = "accepted"
        _apply_current_qualification(session, need, project)
        assert need.tier == "Lead"
        assert need.required_mw == "21 to 24 MW"
        assert interpretation.assessment["demand_mw"] == "20 to 25 MW"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert set(session.scalars(select(Evidence.content_hash))) == {
            content_hash,
            conflicting_hash,
        }

    # Replace the old 5 MW report with an exact current adequate range. The
    # correction is append-only and must remove this Need from every active
    # browse projection without rewriting its Reported source assessment.
    preclosure_page = client.get("/api/opportunities?tier=Lead&limit=50")
    assert preclosure_page.status_code == 200, preclosure_page.text
    preclosure_card = next(
        item for item in preclosure_page.json() if str(item["id"]) == str(need_id)
    )
    preclosure_token = preclosure_page.headers["x-cohort-token"]
    preclosure_group_id = preclosure_card["group_id"]
    adequate_body = _body(
        project_id,
        pursuit_id,
        expected_version=event_version,
        predecessor_id=UUID(initial_supply["fact_version_id"]),
    )
    adequate_body["fact_type"] = "suitable_supply"
    adequate_body["value"] = {
        "mw_min": "25",
        "mw_max": "30",
        "quality": "suitable",
    }
    adequate_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    adequate_body["effective_until"] = "2027-03-04T00:00:00+00:00"
    adequate_draft = client.post(
        f"/api/needs/{need_id}/facts", json=adequate_body, headers=headers
    )
    assert adequate_draft.status_code == 200, adequate_draft.text
    event_version += 1
    adequate_decision = client.post(
        f"/api/needs/{need_id}/facts/{adequate_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version,
            "decision": "corrected",
            "reason": "Synthetic full-window suitable supply correction",
        },
        headers=headers,
    )
    assert adequate_decision.status_code == 200, adequate_decision.text
    assert adequate_decision.json()["active"] is False
    assert adequate_decision.json()["tier"] == "Signal"
    event_version += 2
    adequate_fact = adequate_decision.json()

    inactive_leads = client.get("/api/opportunities?tier=Lead&limit=50")
    assert inactive_leads.status_code == 200, inactive_leads.text
    assert inactive_leads.headers["x-total-count"] == "0"
    assert all(str(item["id"]) != str(need_id) for item in inactive_leads.json())
    inactive_prospects = client.get("/api/opportunities?tier=Prospect&limit=50")
    assert inactive_prospects.status_code == 200, inactive_prospects.text
    assert all(str(item["id"]) != str(need_id) for item in inactive_prospects.json())
    stale_preclosure = client.get(
        f"/api/opportunities?tier=Lead&cohort_token={preclosure_token}"
    )
    assert stale_preclosure.status_code == 409
    inactive_csv = client.get("/api/opportunities/export.csv?tier=Lead&limit=50")
    assert inactive_csv.status_code == 200, inactive_csv.text
    assert str(need_id) not in inactive_csv.text
    inactive_detail = client.get(f"/api/opportunities/needs/{need_id}?tier=Lead")
    assert inactive_detail.status_code == 404
    inactive_group = client.get(
        f"/api/opportunity-groups/{preclosure_group_id}?tier=Lead"
        f"&cohort_token={inactive_leads.headers['x-cohort-token']}"
    )
    assert inactive_group.status_code == 404
    fact_history = client.get(f"/api/needs/{need_id}/facts?limit=100")
    assert fact_history.status_code == 200, fact_history.text
    assert any(
        item["id"] == adequate_fact["fact_version_id"]
        and item["content_hash"] == adequate_fact["content_hash"]
        for item in fact_history.json()["items"]
    )
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        assert need is not None and project is not None
        assert observation is not None and interpretation is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["closed_by_fact"] is True
        assert effective["required_mw"] is None
        assert effective["qualified_remaining_gap"] is None
        basis = effective["closure_basis"]
        assert basis["suitable_supply_fact_id"] == adequate_fact["fact_version_id"]
        assert basis["suitable_supply_fact_hash"] == adequate_fact["content_hash"]
        assert basis["source_semantic_hash"] == content_hash
        assert basis["source_evidence_hash"] == content_hash
        assert need.active is False and need.required_mw is None
        sibling = session.get(PowerNeed, sibling_need_id)
        assert sibling is not None and sibling.active is True
        assert "source semantic hash" in need.rationale.casefold()
        assert interpretation.assessment["demand_mw"] == "20 to 25 MW"
        assert (
            interpretation.assessment["supply_quote"]
            == "Power supply for Test City construction is insufficient."
        )

    # Replaying a new compatible public source version cannot reopen a Need
    # while the accepted exact-need adequate supply remains current.
    replay_hash = "d" * 64
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        assert need is not None and project is not None
        assert observation is not None and interpretation is not None
        observation.content_hash = replay_hash
        observation.abstract = source_abstract
        session.add(
            Evidence(
                observation_id=observation.id,
                content_hash=replay_hash,
                title=observation.title,
                abstract=source_abstract,
                url=observation.url,
                published_at=observation.published_at,
                observed_at=datetime.now(UTC),
            )
        )
        interpretation.content_hash = replay_hash
        interpretation.status = "accepted"
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": replay_hash,
            "evidence_hash": replay_hash,
        }
        from gridlens.ingestion.service import _apply_current_qualification

        need.active = True  # ingestion reopens on a new source version before replay
        _apply_current_qualification(session, need, project)
        assert need.active is False and need.tier == "Signal"
        assert replay_hash in need.rationale

    # A supported partial range reopens only an active, recomputed gap; retracting
    # it returns to the public Prospect instead of reusing a stale closed state.
    partial_body = _body(
        project_id,
        pursuit_id,
        expected_version=event_version,
        predecessor_id=UUID(adequate_fact["fact_version_id"]),
    )
    partial_body["fact_type"] = "suitable_supply"
    partial_body["value"] = {"mw_min": "10", "mw_max": "15", "quality": "suitable"}
    partial_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    partial_body["effective_until"] = "2027-03-04T00:00:00+00:00"
    partial_draft = client.post(
        f"/api/needs/{need_id}/facts", json=partial_body, headers=headers
    )
    assert partial_draft.status_code == 200, partial_draft.text
    event_version += 1
    partial_decision = client.post(
        f"/api/needs/{need_id}/facts/{partial_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version,
            "decision": "corrected",
            "reason": "Synthetic suitable supply range leaves an open gap",
        },
        headers=headers,
    )
    assert partial_decision.status_code == 200, partial_decision.text
    assert partial_decision.json()["active"] is True
    assert partial_decision.json()["tier"] == "Lead"
    event_version += 2
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["tier"] == "Lead"
        assert (
            effective["qualified_remaining_gap"]["remaining_mw_min"],
            effective["qualified_remaining_gap"]["remaining_mw_max"],
        ) == ("6", "14")
        assert (
            effective["qualified_remaining_gap"]["suitable_supply_fact_id"]
            == partial_decision.json()["fact_version_id"]
        )
    retracted_partial = client.post(
        f"/api/needs/{need_id}/facts/{partial_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": event_version,
            "decision": "retracted",
            "reason": "Synthetic supply range retracted",
        },
        headers=headers,
    )
    assert retracted_partial.status_code == 200, retracted_partial.text
    assert retracted_partial.json()["active"] is True
    assert retracted_partial.json()["tier"] == "Prospect"
    event_version += 1
    restored_supply = accept("suitable_supply", {"mw": "5", "quality": "suitable"}).json()
    assert restored_supply["active"] is True and restored_supply["tier"] == "Lead"
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["tier"] == "Lead"
        assert (
            effective["qualified_remaining_gap"]["remaining_mw_min"],
            effective["qualified_remaining_gap"]["remaining_mw_max"],
        ) == ("16", "19")

    unknown_page = client.get("/api/opportunities?tier=Lead&status=UNKNOWN")
    assert unknown_page.status_code == 200, unknown_page.text
    assert any(str(item["id"]) == str(need_id) for item in unknown_page.json())
    unknown_token = unknown_page.headers["x-cohort-token"]
    group_id = next(
        item["group_id"] for item in unknown_page.json() if str(item["id"]) == str(need_id)
    )
    status_version = 0
    previous_token = unknown_token
    for status in ("New", "Investigating", "Contacted", "Qualified", "Won", "Lost", "Closed"):
        status_response = client.post(
            f"/api/needs/{need_id}/workflow-status",
            json={
                "client_id": str(uuid4()),
                "project_id": str(project_id),
                "pursuit_id": str(pursuit_id),
                "expected_version": status_version,
                "status": status,
                "reason": f"Synthetic status-filter test: {status}",
            },
            headers=headers,
        )
        assert status_response.status_code == 200, status_response.text
        status_version += 1
        status_filter = status.upper()
        filtered = client.get(f"/api/opportunities?tier=Lead&status={status_filter}")
        assert filtered.status_code == 200, filtered.text
        filtered_item = next(
            item for item in filtered.json() if str(item["id"]) == str(need_id)
        )
        assert filtered_item["workflow_status"] == status
        assert int(filtered.headers["x-total-count"]) >= 1
        current_token = filtered.headers["x-cohort-token"]
        current_group = filtered_item["group_id"]
        grouped = client.get(
            f"/api/opportunity-groups/{current_group}?tier=Lead&status={status_filter}"
            f"&cohort_token={current_token}"
        )
        assert grouped.status_code == 200, grouped.text
        assert any(str(item["id"]) == str(need_id) for item in grouped.json()["items"])
        detail = client.get(
            f"/api/opportunities/needs/{need_id}?tier=Lead&status={status_filter}"
            f"&cohort_token={current_token}"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["workflow_status"] == status
        csv = client.get(f"/api/opportunities/export.csv?tier=Lead&status={status_filter}")
        assert csv.status_code == 200, csv.text
        assert str(need_id) in csv.text
        unknown_filtered = client.get("/api/opportunities?tier=Lead&status=UNKNOWN")
        assert unknown_filtered.status_code == 200, unknown_filtered.text
        assert all(str(item["id"]) != str(need_id) for item in unknown_filtered.json())
        if status == "New":
            stale_page = client.get(
                f"/api/opportunities?tier=Lead&status=UNKNOWN&cohort_token={previous_token}"
            )
            assert stale_page.status_code == 409
            stale_group = client.get(
                f"/api/opportunity-groups/{group_id}?tier=Lead&status=UNKNOWN"
                f"&cohort_token={previous_token}"
            )
            assert stale_group.status_code == 409
        previous_token = current_token


def test_timing_correction_is_source_version_bound_and_replayed_after_source_change(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    from gridlens.domain.power_qualification import qualify_official_power

    source_description = (
        "Test City construction requires 20 to 25 MW. "
        "Power supply for Test City construction is insufficient. "
        "Test City construction starts between 2027-01-01 and 2027-02-01. "
        "Test City construction lasts 31 to 62 days. "
        "No suitable power supply is available for Test City construction throughout this "
        "start window and duration. The electrical contractor is responsible for power "
        "procurement for Test City construction."
    )
    source_text = f"description: {source_description}\naddress: Test City"
    source_hash = "e" * 64
    changed_source_hash = "f" * 64
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        claim = qualify_official_power(
            text=source_description,
            site="Test City",
            activity_key="construction",
            location="Test City",
        )
        assert claim["tier"] == "Lead"
        claim.update(
            {
                "decision": "accepted",
                "semantic_hash": source_hash,
                "evidence_hash": source_hash,
                "project_identity_key": project.identity_key,
                "power_activity": "construction",
                "subject": project.name,
                "location": project.location,
            }
        )
        observation = Observation(
            source_id="a6-test-source",
            external_id="synthetic-timing-correction-1",
            title="Synthetic construction permit correction test",
            abstract=source_text,
            published_at=datetime.now(UTC).date(),
            url="https://example.test/synthetic-timing-correction-1",
            content_hash=source_hash,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=source_hash,
            title=observation.title,
            abstract=source_text,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        session.flush()
        claim["evidence"] = {"id": str(evidence.id), "url": evidence.url}
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=source_hash,
            status="accepted",
            assessment=claim,
        )
        session.add_all(
            [
                interpretation,
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )
        need.active = True
        need.tier = "Lead"
        need.required_mw = claim.get("required_mw") or claim["demand_mw"]
        need.start_window = claim["start_window"]
        need.duration = claim["duration"]
        need.rationale = claim["reason"]

    from gridlens.intelligence.commercial_evaluation import evaluate_target, save_evaluations

    original_saved_at = datetime.now(UTC)
    with factory.begin() as session:
        original_card = evaluate_target(session, need_id)
        assert original_card is not None and original_card["tier"] == "Lead"
        assert original_card["start_window"] == "2027-01-01 to 2027-02-01"
        assert original_card["duration"] == "31 to 62 days"
        save_evaluations(session, [original_card], now=original_saved_at)

    headers = {"origin": "http://testserver"}
    source_readback = client.get(f"/api/needs/{need_id}/facts")
    assert source_readback.status_code == 200, source_readback.text
    assert source_readback.json()["current_fact_version"] == 0
    target = source_readback.json()["current_reported_timing_correction_target"]
    assert target["available"] is True
    assert target["unavailable_reason"] is None
    assert target["need_id"] == str(need_id)
    assert target["project_id"] == str(project_id)
    assert target["activity_key"] == "construction"
    assert target["facility_identity"]
    assert target["source_semantic_hash"] == source_hash
    assert target["source_evidence_hash"] == source_hash
    assert target["retained_evidence_id"]
    assert target["earliest_possible_start"] == "2027-01-01"
    assert target["latest_possible_start"] == "2027-02-01"
    assert target["minimum_duration_days"] == 31
    assert target["maximum_duration_days"] == 62
    compatible_body = _body(project_id, pursuit_id, expected_version=0)
    compatible_body["fact_type"] = "timing"
    compatible_body["value"] = {
        "start_date": "2027-01-10",
        "end_date": "2027-01-20",
        "duration_days": 40,
        "basis": "Owner confirmed the compatible narrower activity window.",
    }
    compatible_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    compatible_body["effective_until"] = "2027-03-01T00:00:00+00:00"
    compatible_draft = client.post(
        f"/api/needs/{need_id}/facts", json=compatible_body, headers=headers
    )
    assert compatible_draft.status_code == 200, compatible_draft.text
    compatible_decision = client.post(
        f"/api/needs/{need_id}/facts/{compatible_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 1,
            "decision": "accepted",
            "reason": "Accepted compatible interval narrowing",
        },
        headers=headers,
    )
    assert compatible_decision.status_code == 200, compatible_decision.text
    assert compatible_decision.json()["tier"] == "Lead"
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["tier"] == "Lead"
        assert effective["start_window"] == "2027-01-10 to 2027-01-20"
        assert effective["duration"] == "40 days"
        assert need.start_window == effective["start_window"]
        assert need.duration == effective["duration"]
        gap = effective["qualified_remaining_gap"]
        assert gap["start_window"] == effective["start_window"]
        assert gap["duration"] == effective["duration"]
        assert gap["selected_activity_interval_start"] == "2027-01-10T00:00:00+00:00"
        assert gap["selected_activity_interval_end_exclusive"] == "2027-03-01T00:00:00+00:00"
        assert gap["source_reported_start_window"] == "2027-01-01 to 2027-02-01"
        assert gap["source_reported_duration"] == "31 to 62 days"
        assert gap["remaining_mw_min"] == "20"
        assert gap["remaining_mw_max"] == "25"

    compatible_page = client.get("/api/opportunities?tier=Lead&timing=KNOWN")
    assert compatible_page.status_code == 200, compatible_page.text
    compatible_card = next(
        item for item in compatible_page.json() if str(item["id"]) == str(need_id)
    )
    assert compatible_card["start_window"] == "2027-01-10 to 2027-01-20"
    assert compatible_card["duration"] == "40 days"
    compatible_group = client.get(
        f"/api/opportunity-groups/{compatible_card['group_id']}?tier=Lead&timing=KNOWN"
        f"&cohort_token={compatible_page.headers['x-cohort-token']}"
    )
    assert compatible_group.status_code == 200, compatible_group.text
    assert any(str(item["id"]) == str(need_id) for item in compatible_group.json()["items"])
    compatible_detail = client.get(
        f"/api/opportunities/needs/{need_id}?tier=Lead&timing=KNOWN"
    )
    assert compatible_detail.status_code == 200, compatible_detail.text
    assert compatible_detail.json()["start_window"] == "2027-01-10 to 2027-01-20"
    compatible_csv = client.get("/api/opportunities/export.csv?tier=Lead&timing=KNOWN")
    assert compatible_csv.status_code == 200, compatible_csv.text
    assert str(need_id) in compatible_csv.text
    assert "start_window" not in compatible_csv.text.splitlines()[0]

    compatible_saved_at = original_saved_at + timedelta(seconds=1)
    with factory.begin() as session:
        compatible_card = evaluate_target(session, need_id)
        assert compatible_card is not None and compatible_card["tier"] == "Lead"
        assert compatible_card["start_window"] == "2027-01-10 to 2027-01-20"
        assert compatible_card["duration"] == "40 days"
        assert compatible_card["operator_fact_refs"][0]["fact_version_id"] == (
            compatible_draft.json()["id"]
        )
        save_evaluations(session, [compatible_card], now=compatible_saved_at)

    retract_compatible = client.post(
        f"/api/needs/{need_id}/facts/{compatible_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 2,
            "decision": "retracted",
            "reason": "Restore the source timing before the separate correction case",
        },
        headers=headers,
    )
    assert retract_compatible.status_code == 200, retract_compatible.text
    assert retract_compatible.json()["tier"] == "Lead"

    correction_value = {
        "start_date": "2026-11-01",
        "end_date": "2026-11-01",
        "duration_days": 31,
        "corrects_source_semantic_hash": source_hash,
        "corrects_source_evidence_hash": source_hash,
        "basis": "Owner confirmed the current reported timing was outdated.",
    }
    correction_body = _body(project_id, pursuit_id, expected_version=3)
    correction_body["fact_type"] = "timing"
    correction_body["value"] = correction_value
    correction_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    correction_body["effective_until"] = "2026-12-03T00:00:00+00:00"
    correction_draft = client.post(
        f"/api/needs/{need_id}/facts", json=correction_body, headers=headers
    )
    assert correction_draft.status_code == 200, correction_draft.text
    assert correction_draft.json()["value"] == {
        **correction_value,
        "start_date": "2026-11-01",
        "end_date": "2026-11-01",
    }
    correction_decision = client.post(
        f"/api/needs/{need_id}/facts/{correction_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 4,
            "decision": "accepted",
            "reason": "Accepted attributed timing correction",
        },
        headers=headers,
    )
    assert correction_decision.status_code == 200, correction_decision.text
    assert correction_decision.json()["active"] is True
    assert correction_decision.json()["tier"] == "Prospect"
    corrected_saved_at = original_saved_at + timedelta(seconds=2)
    with factory.begin() as session:
        corrected_card = evaluate_target(session, need_id)
        assert corrected_card is not None and corrected_card["tier"] == "Prospect"
        assert corrected_card["start_window"] == "2026-11-01 to 2026-11-01"
        assert corrected_card["duration"] == "31 days"
        assert corrected_card["operator_fact_refs"][0]["fact_version_id"] == (
            correction_draft.json()["id"]
        )
        assert corrected_card["operator_fact_refs"][0]["content_hash"] == (
            correction_draft.json()["content_hash"]
        )
        save_evaluations(session, [corrected_card], now=corrected_saved_at)
    with factory() as session:
        pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
        )
        assert pursuit is not None
        saved_versions = pursuit.snapshot["commercial_triage"]["versions"]
        original_saved = next(
            version["saved_card"]
            for version in saved_versions
            if version["evaluated_at"] == original_saved_at.isoformat()
        )
        compatible_saved = next(
            version["saved_card"]
            for version in saved_versions
            if version["evaluated_at"] == compatible_saved_at.isoformat()
        )
        corrected_saved = next(
            version["saved_card"]
            for version in saved_versions
            if version["evaluated_at"] == corrected_saved_at.isoformat()
        )
        assert original_saved["start_window"] == "2027-01-01 to 2027-02-01"
        assert original_saved["duration"] == "31 to 62 days"
        assert "operator_fact_refs" not in original_saved
        assert compatible_saved["start_window"] == "2027-01-10 to 2027-01-20"
        assert compatible_saved["duration"] == "40 days"
        assert compatible_saved["operator_fact_refs"][0]["fact_version_id"] == (
            compatible_draft.json()["id"]
        )
        assert corrected_saved["start_window"] == "2026-11-01 to 2026-11-01"
        assert corrected_saved["duration"] == "31 days"
        assert corrected_saved["operator_fact_refs"][0]["fact_version_id"] == (
            correction_draft.json()["id"]
        )
    correction_history = client.get(f"/api/needs/{need_id}/facts?limit=20")
    assert correction_history.status_code == 200, correction_history.text
    history_correction = next(
        row
        for row in correction_history.json()["items"]
        if row["id"] == correction_draft.json()["id"]
    )
    assert history_correction["value"] == correction_draft.json()["value"]

    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        current = effective_need_qualification(session, need, project)
        assert current is not None and current["tier"] == "Prospect"
        assert current["start_window"] == "2026-11-01 to 2026-11-01"
        assert current["duration"] == "31 days"
        assert current["qualified_remaining_gap"] is None
        assert current["timing_provenance"]["fact_id"] == correction_draft.json()["id"]
        assert current["timing_provenance"]["fact_hash"] == correction_draft.json()["content_hash"]
        assert need.tier == "Prospect"
        assert need.start_window == "2026-11-01 to 2026-11-01"
        assert need.duration == "31 days"

    known_timing_page = client.get("/api/opportunities?tier=Prospect&timing=KNOWN")
    assert known_timing_page.status_code == 200, known_timing_page.text
    known_timing_card = next(
        item for item in known_timing_page.json() if str(item["id"]) == str(need_id)
    )
    assert known_timing_card["start_window"] == "2026-11-01 to 2026-11-01"
    assert known_timing_card["duration"] == "31 days"
    known_group = client.get(
        f"/api/opportunity-groups/{known_timing_card['group_id']}?tier=Prospect&timing=KNOWN"
        f"&cohort_token={known_timing_page.headers['x-cohort-token']}"
    )
    assert known_group.status_code == 200, known_group.text
    assert any(str(item["id"]) == str(need_id) for item in known_group.json()["items"])
    unknown_timing_page = client.get("/api/opportunities?tier=Prospect&timing=UNKNOWN")
    assert unknown_timing_page.status_code == 200, unknown_timing_page.text
    assert all(str(item["id"]) != str(need_id) for item in unknown_timing_page.json())
    known_detail = client.get(
        f"/api/opportunities/needs/{need_id}?tier=Prospect&timing=KNOWN"
    )
    assert known_detail.status_code == 200, known_detail.text
    assert known_detail.json()["start_window"] == "2026-11-01 to 2026-11-01"
    known_csv = client.get("/api/opportunities/export.csv?tier=Prospect&timing=KNOWN")
    assert known_csv.status_code == 200, known_csv.text
    assert str(need_id) in known_csv.text
    assert "start_window" not in known_csv.text.splitlines()[0]

    supply_body = _body(project_id, pursuit_id, expected_version=5)
    supply_body["fact_type"] = "suitable_supply"
    supply_body["value"] = {
        "mw_min": "10",
        "mw_max": "15",
        "quality": "suitable",
        "basis": "Synthetic full-window partial supply confirmation",
    }
    supply_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    supply_body["effective_until"] = "2026-12-03T00:00:00+00:00"
    supply_draft = client.post(
        f"/api/needs/{need_id}/facts", json=supply_body, headers=headers
    )
    assert supply_draft.status_code == 200, supply_draft.text
    supply_decision = client.post(
        f"/api/needs/{need_id}/facts/{supply_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 6,
            "decision": "accepted",
            "reason": "Accepted suitable supply for corrected window",
        },
        headers=headers,
    )
    assert supply_decision.status_code == 200, supply_decision.text
    assert supply_decision.json()["active"] is True
    assert supply_decision.json()["tier"] == "Lead"
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective_after_supply = effective_need_qualification(session, need, project)
        assert effective_after_supply is not None
        assert effective_after_supply["closed_by_fact"] is False, effective_after_supply
        assert effective_after_supply["tier"] == "Lead"
        assert effective_after_supply["start_window"] == "2026-11-01 to 2026-11-01"
        assert effective_after_supply["duration"] == "31 days"
        assert effective_after_supply["qualified_remaining_gap"]["remaining_mw_min"] == "5"
        assert effective_after_supply["qualified_remaining_gap"]["remaining_mw_max"] == "15"

    retract_partial_supply = client.post(
        f"/api/needs/{need_id}/facts/{supply_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 7,
            "decision": "retracted",
            "reason": "Replace the partial fixture with a separate adequate-supply case",
        },
        headers=headers,
    )
    assert retract_partial_supply.status_code == 200, retract_partial_supply.text
    adequate_supply_body = _body(project_id, pursuit_id, expected_version=8)
    adequate_supply_body["fact_type"] = "suitable_supply"
    adequate_supply_body["value"] = {
        "mw_min": "25",
        "mw_max": "30",
        "quality": "suitable",
        "basis": "Synthetic full-window suitable capacity confirmation",
    }
    adequate_supply_body["effective_from"] = "2026-01-01T00:00:00+00:00"
    adequate_supply_body["effective_until"] = "2026-12-03T00:00:00+00:00"
    adequate_supply_draft = client.post(
        f"/api/needs/{need_id}/facts", json=adequate_supply_body, headers=headers
    )
    assert adequate_supply_draft.status_code == 200, adequate_supply_draft.text
    adequate_supply_decision = client.post(
        f"/api/needs/{need_id}/facts/{adequate_supply_draft.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 9,
            "decision": "accepted",
            "reason": "Accepted sufficient supply for corrected window",
        },
        headers=headers,
    )
    assert adequate_supply_decision.status_code == 200, adequate_supply_decision.text
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective_after_adequate_supply = effective_need_qualification(session, need, project)
        assert effective_after_adequate_supply is not None
        assert effective_after_adequate_supply["closed_by_fact"] is True, (
            effective_after_adequate_supply
        )
        assert effective_after_adequate_supply["closure_basis"]["source_reported_start_window"] == (
            "2027-01-01 to 2027-02-01"
        )
    assert adequate_supply_decision.json()["active"] is False, adequate_supply_decision.json()
    before_source_replay = client.get("/api/opportunities?tier=Prospect")
    assert before_source_replay.status_code == 200, before_source_replay.text
    old_cohort = before_source_replay.headers["x-cohort-token"]
    with factory.begin() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        effective = effective_need_qualification(session, need, project)
        assert effective is not None and effective["closed_by_fact"] is True
        basis = effective["closure_basis"]
        assert basis["timing_fact_id"] == correction_draft.json()["id"]
        assert basis["timing_fact_hash"] == correction_draft.json()["content_hash"]
        assert basis["timing_resolution"] == "explicit_source_correction"
        assert basis["timing_source_semantic_hash"] == source_hash
        assert basis["timing_source_evidence_hash"] == source_hash
        assert basis["source_reported_start_window"] == "2027-01-01 to 2027-02-01"
        assert need.active is False
        assert need.start_window is None and need.duration is None
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        assert observation is not None and interpretation is not None
        observation.content_hash = changed_source_hash
        observation.abstract = source_text
        session.add(
            Evidence(
                observation_id=observation.id,
                content_hash=changed_source_hash,
                title=observation.title,
                abstract=source_text,
                url=observation.url,
                published_at=observation.published_at,
                observed_at=datetime.now(UTC),
            )
        )
        interpretation.content_hash = changed_source_hash
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": changed_source_hash,
            "evidence_hash": changed_source_hash,
        }
        need.active = True
        from gridlens.ingestion.service import _apply_current_qualification

        _apply_current_qualification(session, need, project)
        current = effective_need_qualification(session, need, project)
        assert current is not None and current["qualification_conflict"] is True
        assert current["tier"] == "Prospect"
        assert not current.get("closed_by_fact")
        assert need.active is True
        assert need.start_window is None and need.duration is None
        assert changed_source_hash in need.rationale
        assert interpretation.assessment["start_window"] == "2027-01-01 to 2027-02-01"
    current_browse = client.get("/api/opportunities?tier=Prospect")
    assert current_browse.status_code == 200, current_browse.text
    assert any(str(item["id"]) == str(need_id) for item in current_browse.json())
    stale_browse = client.get(
        f"/api/opportunities?tier=Prospect&cohort_token={old_cohort}"
    )
    assert stale_browse.status_code == 409
    current_csv = client.get("/api/opportunities/export.csv?tier=Prospect")
    assert current_csv.status_code == 200, current_csv.text
    assert str(need_id) in current_csv.text


def test_saved_commercial_card_binds_accepted_fact_versions_as_of(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    original_hash = "c" * 64
    with factory.begin() as session:
        project = session.get(Project, project_id)
        need = session.get(PowerNeed, need_id)
        assert project is not None and need is not None
        observation = Observation(
            source_id="a6-test-source",
            external_id="triage-asof-1",
            title="Synthetic current construction permit",
            abstract="Current public permit supports construction activity at Test City.",
            published_at=datetime.now(UTC).date(),
            url="https://example.test/triage-asof-1",
            content_hash=original_hash,
        )
        session.add(observation)
        session.flush()
        public_evidence = Evidence(
            observation_id=observation.id,
            content_hash=original_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime.now(UTC),
        )
        session.add(public_evidence)
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=observation.id,
                    content_hash=original_hash,
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": original_hash,
                        "evidence_hash": original_hash,
                        "evidence": {"id": str(public_evidence.id)},
                        "project_identity_key": project.identity_key,
                        "power_activity": "construction",
                        "tier": "Signal",
                        "reason": "Synthetic current public support.",
                        "subject": project.name,
                        "location": project.location,
                    },
                ),
                NeedObservation(need_id=need_id, observation_id=observation.id),
            ]
        )

    api = import_module("gridlens.api.app")
    from gridlens.intelligence.commercial_evaluation import save_evaluations

    def evaluate_and_save(moment: datetime):
        with factory.begin() as session:
            cards, _total = api._commercial_triage_page(session, 50)
            card = next(card for card in cards if card["id"] == str(need_id))
            save_evaluations(session, [card], now=moment)
            return card

    moment = datetime.now(UTC)
    no_fact_card = evaluate_and_save(moment)
    with factory() as session:
        pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
        )
        assert pursuit is not None
        initial_saved = pursuit.snapshot["commercial_triage"]["versions"][0]["saved_card"]
        assert "operator_fact_refs" not in initial_saved
    initial_hash = no_fact_card["input_hash"]

    headers = {"origin": "http://testserver"}
    qualified_status = client.post(
        f"/api/needs/{need_id}/workflow-status",
        json={
            "client_id": str(uuid4()),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": 0,
            "status": "Qualified",
            "reason": "Synthetic status remains separate from evidence inputs",
        },
        headers=headers,
    )
    assert qualified_status.status_code == 200, qualified_status.text
    status_only_card = evaluate_and_save(moment + timedelta(milliseconds=500))
    assert status_only_card["input_hash"] == initial_hash
    assert "operator_fact_refs" not in status_only_card

    first_body = _body(project_id, pursuit_id)
    first_body["value"] = {"mw": "20", "basis": "Synthetic fact A"}
    first = client.post(f"/api/needs/{need_id}/facts", json=first_body, headers=headers)
    assert first.status_code == 200, first.text
    first_fact_id = first.json()["id"]
    draft_only_card = evaluate_and_save(moment + timedelta(milliseconds=750))
    assert draft_only_card["input_hash"] == initial_hash
    assert "operator_fact_refs" not in draft_only_card
    accepted = client.post(
        f"/api/needs/{need_id}/facts/{first_fact_id}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 1,
            "decision": "accepted",
            "reason": "Synthetic confirmed A",
        },
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    card_a = evaluate_and_save(moment + timedelta(seconds=1))
    refs_a = card_a["operator_fact_refs"]
    assert refs_a == [
        {
            "need_id": str(need_id),
            "fact_version_id": first_fact_id,
            "content_hash": first.json()["content_hash"],
            "authority": "User-confirmed",
        }
    ]
    assert card_a["input_hash"] != initial_hash
    assert card_a["facts"][0]["hash"] == original_hash
    assert "value" not in refs_a[0]
    with factory() as session:
        pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
        )
        assert pursuit is not None
        saved_card_a = deepcopy(pursuit.snapshot["commercial_triage"]["versions"][-1]["saved_card"])

    correction_body = _body(
        project_id, pursuit_id, expected_version=2, predecessor_id=first_fact_id
    )
    correction_body["value"] = {"mw": "21", "basis": "Synthetic fact B"}
    correction = client.post(
        f"/api/needs/{need_id}/facts", json=correction_body, headers=headers
    )
    assert correction.status_code == 200, correction.text
    corrected = client.post(
        f"/api/needs/{need_id}/facts/{correction.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 3,
            "decision": "corrected",
            "reason": "Synthetic correction B",
        },
        headers=headers,
    )
    assert corrected.status_code == 200, corrected.text
    card_b = evaluate_and_save(moment + timedelta(seconds=2))
    refs_b = card_b["operator_fact_refs"]
    assert [reference["fact_version_id"] for reference in refs_b] == [correction.json()["id"]]
    assert card_b["input_hash"] not in {initial_hash, card_a["input_hash"]}

    return_body = _body(
        project_id,
        pursuit_id,
        expected_version=5,
        predecessor_id=correction.json()["id"],
    )
    return_body["value"] = {"mw": "20", "basis": "Synthetic fact A"}
    returned = client.post(f"/api/needs/{need_id}/facts", json=return_body, headers=headers)
    assert returned.status_code == 200, returned.text
    accepted_return = client.post(
        f"/api/needs/{need_id}/facts/{returned.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 6,
            "decision": "corrected",
            "reason": "Synthetic original value restored",
        },
        headers=headers,
    )
    assert accepted_return.status_code == 200, accepted_return.text
    card_returned = evaluate_and_save(moment + timedelta(seconds=3))
    refs_returned = card_returned["operator_fact_refs"]
    assert returned.json()["value"] == first.json()["value"]
    assert refs_returned[0]["content_hash"] != refs_a[0]["content_hash"]
    assert refs_returned[0]["fact_version_id"] == returned.json()["id"]
    assert card_returned["input_hash"] not in {
        initial_hash,
        card_a["input_hash"],
        card_b["input_hash"],
    }

    rejected_body = _body(project_id, pursuit_id, expected_version=8)
    rejected_body["fact_type"] = "buyer"
    rejected_body["value"] = {
        "organization": "Synthetic rejected buyer",
        "role": "project owner",
    }
    rejected = client.post(
        f"/api/needs/{need_id}/facts", json=rejected_body, headers=headers
    )
    assert rejected.status_code == 200, rejected.text
    rejection = client.post(
        f"/api/needs/{need_id}/facts/{rejected.json()['id']}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 9,
            "decision": "rejected",
            "reason": "Synthetic rejected report",
        },
        headers=headers,
    )
    assert rejection.status_code == 200, rejection.text
    rejected_card = evaluate_and_save(moment + timedelta(milliseconds=3500))
    assert rejected_card["input_hash"] == card_returned["input_hash"]
    assert rejected_card["operator_fact_refs"] == refs_returned

    conflicting_hash = "d" * 64
    with factory.begin() as session:
        observation = session.scalar(
            select(Observation).where(Observation.external_id == "triage-asof-1")
        )
        interpretation = session.scalar(select(Interpretation))
        assert observation is not None and interpretation is not None
        conflicting_evidence = Evidence(
            observation_id=observation.id,
            content_hash=conflicting_hash,
            title="Synthetic current construction permit revision",
            abstract="The revised public report describes a conflicting 30 MW demand.",
            url="https://example.test/triage-asof-1-revision",
            published_at=datetime.now(UTC).date(),
            observed_at=datetime.now(UTC),
        )
        session.add(conflicting_evidence)
        session.flush()
        observation.content_hash = conflicting_hash
        interpretation.content_hash = conflicting_hash
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": conflicting_hash,
            "evidence_hash": conflicting_hash,
            "evidence": {"id": str(conflicting_evidence.id)},
            "tier": "Prospect",
            "demand_mw": "30 MW",
            "demand_quote": "The revised report states 30 MW.",
        }
    conflict_card = evaluate_and_save(moment + timedelta(seconds=4))
    assert conflict_card["facts"][0]["hash"] == conflicting_hash
    assert conflict_card["operator_fact_refs"] == refs_returned
    assert conflict_card["input_hash"] != card_returned["input_hash"]

    with factory() as session:
        pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
        )
        assert pursuit is not None
        versions = pursuit.snapshot["commercial_triage"]["versions"]
        assert len(versions) == 5
        assert [version["operator_fact_provenance"] for version in versions] == [
            "recorded"
        ] * 5
        saved_refs = [
            version["saved_card"].get("operator_fact_refs", [None])[0]
            for version in versions
        ]
        assert saved_refs == [None, refs_a[0], refs_b[0], refs_returned[0], refs_returned[0]]
        assert versions[1]["saved_card"]["facts"][0]["hash"] == original_hash
        assert versions[1]["saved_card"]["input_hash"] == card_a["input_hash"]
        assert versions[1]["saved_card"] == saved_card_a

    history = client.get("/api/commercial/triage/history")
    assert history.status_code == 200, history.text
    history_item = next(item for item in history.json()["items"] if item["need_id"] == str(need_id))
    assert [version["operator_fact_provenance"] for version in history_item["versions"]] == [
        "recorded"
    ] * 5
    assert history_item["versions"][0]["saved_card"]["operator_fact_refs"] is None
    assert history_item["versions"][-1]["saved_card"]["operator_fact_refs"] == refs_returned


@pytest.mark.parametrize("oversize", ["count", "bytes"])
def test_current_fact_preflight_fails_closed_before_fact_orm_hydration(runtime, oversize):
    client, factory, need_id, project_id, _pursuit_id = runtime
    now = datetime.now(UTC)
    number_of_rows = 51 if oversize == "count" else 2
    with factory.begin() as session:
        for index in range(number_of_rows):
            fact_id = uuid4()
            session.add(
                CallFactVersion(
                    id=fact_id,
                    need_id=need_id,
                    project_id=project_id,
                    pursuit_id=None,
                    predecessor_id=None,
                    client_id=uuid4(),
                    activity_key="construction",
                    facility_scope="Test City",
                    fact_type="demand",
                    value={"mw": "20", "basis": "Synthetic bounded fixture"},
                    reporter_name="Synthetic operator",
                    reporter_organization=None,
                    reporter_role=None,
                    confirmation_channel="customer_call",
                    source_reference=("x" * (512 * 1024 + 1))
                    if oversize == "bytes" and index == 0
                    else None,
                    source_date=now.date(),
                    confirmed_at=now,
                    effective_from=now - timedelta(minutes=1),
                    effective_until=None,
                    content_hash=f"{index + 1:064x}",
                    recorded_by="Synthetic test actor",
                )
            )
            session.flush()
            session.add(
                CallFactDecision(
                    need_id=need_id,
                    fact_version_id=fact_id,
                    version=index + 1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=index,
                    reason="Synthetic accepted fixture",
                    content_hash=f"{index + 100:064x}",
                    actor="Synthetic test actor",
                    created_at=now,
                )
            )

    hydrated_fact_entities = []

    def observe_orm_select(execute_state):
        if execute_state.is_select and any(
            description.get("type") is CallFactVersion
            for description in execute_state.statement.column_descriptions
        ):
            hydrated_fact_entities.append(True)

    event.listen(Session, "do_orm_execute", observe_orm_select)
    try:
        response = client.get("/api/opportunities?tier=Signal")
    finally:
        event.remove(Session, "do_orm_execute", observe_orm_select)
    assert response.status_code == 413, response.text
    assert "no evidence was truncated" in response.json()["detail"]
    assert hydrated_fact_entities == []
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(CallFactVersion)
            .where(CallFactVersion.need_id == need_id)
        ) == number_of_rows


def test_saved_browse_parity_through_real_fact_accept_correct_reject_and_source_changes(
    runtime, monkeypatch
):
    """Compare saved reads throughout the complete source-backed operator workflow."""
    from urllib.parse import parse_qs, urlsplit

    from fastapi import HTTPException

    from gridlens.intelligence.saved_browse import current_generation, maintain_once, page
    from gridlens.persistence.browse_invalidation import install

    client, factory, *_scope = runtime
    with factory.kw["bind"].begin() as connection:
        install(connection)
    original_get = client.get
    api = import_module("gridlens.api.app")
    comparisons = []
    monkeypatch.setattr(settings, "saved_browse_enabled", True)

    def compare_get(url, **kwargs):
        with monkeypatch.context() as canonical_read:
            canonical_read.setattr(settings, "saved_browse_enabled", False)
            response = original_get(url, **kwargs)
        parsed = urlsplit(str(url))
        if parsed.path != "/api/opportunities" or response.status_code != 200:
            return response
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        names = (
            "tier",
            "search",
            "decision",
            "geography",
            "industry",
            "activity",
            "timing",
            "mw_status",
            "mw_min",
            "mw_max",
            "priority_segment",
            "status",
        )
        filters = api._normalized_browse_filters(**{name: query.get(name) for name in names})
        with factory() as session:
            try:
                current_generation(session)
            except HTTPException:
                maintain_once(factory)
                with factory() as fresh_session:
                    current_generation(fresh_session)
        with factory() as session:
            saved = page(
                session,
                filters,
                limit=int(query.get("limit", 50)),
                offset=int(query.get("offset", 0)),
                ranked=query.get("sort") == "rank",
            )
        expected = response.json()
        assert [item["id"] for item in saved["items"]] == [item["id"] for item in expected]
        for actual, canonical in zip(saved["items"], expected, strict=True):
            for key in (
                "tier",
                "required_mw",
                "start_window",
                "duration",
                "supply",
                "rank_score",
                "rank_reasons",
                "signal_display_decision",
                "conflict_state",
                "priority_segment",
                "workflow_status",
                "group_id",
                "group_total_filtered",
            ):
                assert actual.get(key) == canonical.get(key), key
        comparisons.append(len(expected))
        return response

    monkeypatch.setattr(client, "get", compare_get)
    test_current_public_support_bounds_fact_qualification_and_reassessment(runtime, monkeypatch)
    assert len(comparisons) >= 5
