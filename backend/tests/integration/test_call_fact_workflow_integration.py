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


def test_current_public_support_bounds_fact_qualification_and_reassessment(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
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
    accept("suitable_supply", {"mw": "5", "quality": "suitable"})
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
    cohort = page.headers["x-cohort-token"]
    detail = client.get(
        f"/api/opportunities/needs/{need_id}?tier=Lead&cohort_token={cohort}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["required_mw"] == "21 to 24 MW"
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

    unknown_page = client.get("/api/opportunities?tier=Lead&status=UNKNOWN")
    assert unknown_page.status_code == 200, unknown_page.text
    assert any(str(item["id"]) == str(need_id) for item in unknown_page.json())
    unknown_token = unknown_page.headers["x-cohort-token"]
    group_id = next(
        item["group_id"] for item in unknown_page.json() if str(item["id"]) == str(need_id)
    )
    status_response = client.post(
        f"/api/needs/{need_id}/workflow-status",
        json={
            "client_id": str(uuid4()),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": 0,
            "status": "Investigating",
            "reason": "Synthetic status-filter test",
        },
        headers=headers,
    )
    assert status_response.status_code == 200, status_response.text
    filtered = client.get("/api/opportunities?tier=Lead&status=UNKNOWN")
    assert filtered.status_code == 200, filtered.text
    assert all(str(item["id"]) != str(need_id) for item in filtered.json())
    assert filtered.headers["x-total-count"] == "0"
    stale_page = client.get(
        f"/api/opportunities?tier=Lead&status=UNKNOWN&cohort_token={unknown_token}"
    )
    assert stale_page.status_code == 409
    stale_group = client.get(
        f"/api/opportunity-groups/{group_id}?tier=Lead&status=UNKNOWN&cohort_token={unknown_token}"
    )
    assert stale_group.status_code == 409
    filtered_detail = client.get(f"/api/opportunities/needs/{need_id}?tier=Lead&status=UNKNOWN")
    assert filtered_detail.status_code == 404
    csv = client.get("/api/opportunities/export.csv?tier=Lead&status=UNKNOWN")
    assert csv.status_code == 200
    assert str(need_id) not in csv.text


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
