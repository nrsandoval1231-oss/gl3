"""Regression coverage for retained historical fact and evidence projections.

Operator fact drafting, decisions, and workflow status are retired public
workflows. These tests seed historical records directly, then exercise only the
supported autonomous evidence and commercial read paths.
"""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from gridlens.domain.call_facts import canonical_hash, validate_fact
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
    ), "Refusing destructive setup without an explicit disposable *_test database"
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
                geography="Austin, TX",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        project = Project(
            identity_key=f"a6-project-{uuid4()}",
            name="Synthetic Test Facility",
            location="Austin, TX",
            identity_facts={"site": "Austin, TX"},
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


def _seed_current_source(
    factory, need_id, project_id, *, demand="20 to 25 MW", digest="a" * 64, tier="Prospect"
):
    abstract = (
        f"description: Austin, TX construction requires {demand}. "
        "Power supply for Austin, TX construction is insufficient.\naddress: Austin, TX"
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = Observation(
            source_id="a6-test-source",
            external_id=f"source-{digest[:8]}",
            title="Synthetic construction permit for Synthetic Test Facility",
            abstract=abstract,
            published_at=datetime.now(UTC).date(),
            url=f"https://example.test/{digest[:8]}",
            content_hash=digest,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=digest,
            title=observation.title,
            abstract=abstract,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        session.flush()
        session.add_all(
            [
                Interpretation(
                    observation_id=observation.id,
                    content_hash=digest,
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "semantic_hash": digest,
                        "evidence_hash": digest,
                        "evidence": {"id": str(evidence.id)},
                        "project_identity_key": project.identity_key,
                        "power_activity": "construction",
                        "tier": tier,
                        "demand_mw": demand,
                        "demand_quote": f"Austin, TX construction requires {demand}.",
                        "supply_quote": "Power supply for Austin, TX construction is insufficient.",
                        "reason": "Current retained exact-site permit support.",
                        "subject": project.name,
                        "location": project.location,
                    },
                ),
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )
        from gridlens.ingestion.service import _apply_current_qualification

        _apply_current_qualification(session, need, project)
    return abstract


def _seed_historical_fact(
    factory,
    need_id,
    project_id,
    pursuit_id,
    fact_type,
    value,
    *,
    decision="accepted",
    predecessor_id=None,
    effective_from=None,
    effective_until=None,
):
    """Insert an immutable historical row as a fixture, bypassing retired writers."""
    now = datetime.now(UTC)
    clean = validate_fact(fact_type, value)
    with factory.begin() as session:
        version = (
            session.scalar(
                select(func.max(CallFactDecision.version)).where(
                    CallFactDecision.need_id == need_id
                )
            )
            or 0
        )
        row = CallFactVersion(
            need_id=need_id,
            project_id=project_id,
            pursuit_id=pursuit_id,
            predecessor_id=predecessor_id,
            client_id=uuid4(),
            activity_key="construction",
            facility_scope="Austin, TX",
            fact_type=fact_type,
            value=clean,
            reporter_name="Synthetic source reporter",
            reporter_organization="Synthetic Owner LLC",
            reporter_role="Project owner",
            confirmation_channel="customer_call",
            source_reference=f"historical-{fact_type}-{uuid4()}",
            source_date=now.date(),
            confirmed_at=now,
            effective_from=effective_from or now - timedelta(days=1),
            effective_until=effective_until or now + timedelta(days=500),
            content_hash=canonical_hash(
                {
                    "need_id": str(need_id),
                    "project_id": str(project_id),
                    "type": fact_type,
                    "value": clean,
                    "source_reference": str(uuid4()),
                }
            ),
            recorded_by="historical fixture",
        )
        session.add(row)
        session.flush()
        receipt = CallFactDecision(
            need_id=need_id,
            fact_version_id=row.id,
            version=version + 1,
            client_id=uuid4(),
            decision=decision,
            expected_version=version,
            reason="Synthetic historical fixture decision",
            content_hash=canonical_hash({"decision": decision, "fact_id": str(row.id)}),
            actor="historical fixture",
        )
        session.add(receipt)
        session.flush()
        return row.id, row.content_hash


def test_retired_manual_fact_and_status_routes_are_unavailable(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    historical_id, _ = _seed_historical_fact(
        factory, need_id, project_id, pursuit_id, "demand", {"mw": "20"}
    )
    headers = {"origin": "http://testserver"}
    fact_body = {
        "client_id": str(uuid4()),
        "project_id": str(project_id),
        "pursuit_id": str(pursuit_id),
        "expected_version": 0,
        "activity_key": "construction",
        "facility_scope": "Austin, TX",
        "fact_type": "demand",
        "value": {"mw": "20"},
    }
    status_body = {
        "client_id": str(uuid4()),
        "project_id": str(project_id),
        "pursuit_id": str(pursuit_id),
        "expected_version": 0,
        "status": "Qualified",
    }
    responses = [
        client.get(f"/api/needs/{need_id}/facts"),
        client.post(f"/api/needs/{need_id}/facts", json=fact_body, headers=headers),
        client.post(
            f"/api/needs/{need_id}/facts/{uuid4()}/decision",
            json={"client_id": str(uuid4()), "expected_version": 0, "decision": "accepted"},
            headers=headers,
        ),
        client.get(f"/api/needs/{need_id}/workflow-status"),
        client.post(f"/api/needs/{need_id}/workflow-status", json=status_body, headers=headers),
    ]
    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CallFactVersion)) == 1
        assert session.scalar(select(func.count()).select_from(CallFactDecision)) == 1
        assert session.scalar(select(func.count()).select_from(NeedWorkflowStatusEvent)) == 0
        assert session.scalar(select(CallFactVersion.id)) == historical_id


def test_historical_facts_keep_source_bounded_gap_and_timing_projection(runtime):
    client, factory, need_id, project_id, pursuit_id = runtime
    _seed_current_source(factory, need_id, project_id)
    first_id, _ = _seed_historical_fact(
        factory, need_id, project_id, pursuit_id, "demand", {"mw": "22"}, decision="rejected"
    )
    demand_id, demand_hash = _seed_historical_fact(
        factory, need_id, project_id, pursuit_id, "demand", {"mw": "22"}
    )
    timing_id, _ = _seed_historical_fact(
        factory,
        need_id,
        project_id,
        pursuit_id,
        "timing",
        {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
    )
    supply_id, _ = _seed_historical_fact(
        factory,
        need_id,
        project_id,
        pursuit_id,
        "suitable_supply",
        {"mw": "5", "quality": "suitable"},
    )
    _seed_historical_fact(
        factory,
        need_id,
        project_id,
        pursuit_id,
        "buyer",
        {"organization": "Synthetic Owner LLC", "role": "project owner"},
    )
    with factory() as session:
        from gridlens.ingestion.service import effective_need_qualification

        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        effective = effective_need_qualification(session, need, project)
        assert effective["tier"] == "Lead"
        assert effective["required_mw"] == "22 MW"
        gap = effective["qualified_remaining_gap"]
        assert (gap["remaining_mw_min"], gap["remaining_mw_max"]) == ("17", "17")
        assert gap["demand_fact_id"] == str(demand_id)
        assert gap["demand_fact_hash"] == demand_hash
        assert effective["start_window"] == "2027-01-01 to 2027-02-01"
        assert effective["duration"] == "31 days"
        assert gap["timing_fact_id"] == str(timing_id)
        current = session.scalars(
            select(CallFactVersion).where(CallFactVersion.need_id == need_id)
        ).all()
        decisions = session.scalars(
            select(CallFactDecision).where(CallFactDecision.need_id == need_id)
        ).all()
        from gridlens.domain.call_facts import current_accepted_facts

        accepted = current_accepted_facts(current, decisions)
        assert first_id not in {row.id for row in accepted}
        assert demand_id in {row.id for row in accepted}
    page = client.get("/api/opportunities?tier=Lead")
    assert page.status_code == 200, page.text
    item = next(row for row in page.json() if row["id"] == str(need_id))
    assert item["required_mw"] == "22 MW"
    assert item["qualified_remaining_gap"]["remaining_mw_min"] == "17"
    detail = client.get(f"/api/opportunities/needs/{need_id}?tier=Lead")
    assert detail.status_code == 200, detail.text
    assert detail.json()["start_window"] == "2027-01-01 to 2027-02-01"
    with factory() as session:
        rows = session.scalars(
            select(CallFactVersion).where(CallFactVersion.need_id == need_id)
        ).all()
        assert {demand_id, timing_id, supply_id}.issubset({row.id for row in rows})


def test_historical_fact_conflict_and_withdrawn_source_preserve_audit_history(runtime):
    _client, factory, need_id, project_id, pursuit_id = runtime
    _seed_current_source(factory, need_id, project_id)
    fact_id, _ = _seed_historical_fact(
        factory, need_id, project_id, pursuit_id, "demand", {"mw": "22"}
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        observation = session.scalar(select(Observation))
        interpretation = session.scalar(select(Interpretation))
        digest = "b" * 64
        observation.content_hash = digest
        observation.abstract = "description: Austin, TX construction requires 30 MW."
        session.add(
            Evidence(
                observation_id=observation.id,
                content_hash=digest,
                title=observation.title,
                abstract=observation.abstract,
                url=observation.url,
                published_at=observation.published_at,
                observed_at=datetime.now(UTC),
            )
        )
        interpretation.content_hash = digest
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": digest,
            "evidence_hash": digest,
            "demand_mw": "30 MW",
            "demand_quote": "source explicitly requires 30 MW",
        }
        from gridlens.ingestion.service import (
            _apply_current_qualification,
            effective_need_qualification,
        )

        _apply_current_qualification(session, need, project)
        assert need.tier == "Signal"
        conflict = effective_need_qualification(session, need, project)
        assert conflict["tier"] == "Signal"
        assert "conflict" in need.rationale.casefold()
        interpretation.status = "withdrawn"
        _apply_current_qualification(session, need, project)
        assert need.tier == "Signal"
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(CallFactVersion)) == 1
        assert session.scalar(select(CallFactVersion.id)) == fact_id
        assert interpretation.assessment["demand_mw"] == "30 MW"


def test_historical_supply_closure_is_current_need_scoped_and_historical(runtime):
    _client, factory, need_id, project_id, pursuit_id = runtime
    _seed_current_source(factory, need_id, project_id)
    _seed_historical_fact(factory, need_id, project_id, pursuit_id, "demand", {"mw": "22"})
    _seed_historical_fact(
        factory,
        need_id,
        project_id,
        pursuit_id,
        "suitable_supply",
        {"mw_min": "25", "mw_max": "30", "quality": "suitable"},
    )
    _seed_historical_fact(
        factory,
        need_id,
        project_id,
        pursuit_id,
        "timing",
        {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31},
    )
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        sibling = PowerNeed(
            project_id=project_id,
            activity_key="operations",
            tier="Signal",
            rationale="Independent synthetic need",
            supply="Unknown",
        )
        session.add(sibling)
        session.flush()
        from gridlens.ingestion.service import (
            _apply_current_qualification,
            effective_need_qualification,
        )

        _apply_current_qualification(session, need, project)
        effective = effective_need_qualification(session, need, project)
        assert effective["closed_by_fact"] is True
        assert effective["required_mw"] is None
        assert effective["qualified_remaining_gap"] is None
        assert effective["closure_basis"]["source_semantic_hash"] == "a" * 64
        assert effective["closure_basis"]["source_evidence_hash"] == "a" * 64
        assert need.active is False
        assert sibling.active is True
        assert session.scalar(select(func.count()).select_from(CallFactVersion)) == 3


def test_saved_commercial_projection_keeps_fact_history_as_of_each_snapshot(runtime):
    _client, factory, need_id, project_id, pursuit_id = runtime
    from gridlens.intelligence.commercial_evaluation import save_evaluations

    def save(moment):
        fact_refs = []
        with factory() as session:
            current = session.scalars(
                select(CallFactVersion).where(CallFactVersion.need_id == need_id)
            ).all()
            decisions = session.scalars(
                select(CallFactDecision).where(CallFactDecision.need_id == need_id)
            ).all()
            from gridlens.domain.call_facts import current_accepted_facts

            fact_refs = [
                {
                    "need_id": str(need_id),
                    "fact_version_id": str(row.id),
                    "content_hash": row.content_hash,
                }
                for row in current_accepted_facts(current, decisions)
            ]
        with factory.begin() as session:
            card = {
                "id": str(need_id),
                "project_id": str(project_id),
                "related_project_ids": [str(project_id)],
                "related_need_ids": [str(need_id)],
                "name": "Synthetic Test Facility",
                "location": "Austin, TX",
                "tier": "Signal",
                "activity": "construction",
                "industry": "unknown",
                "disposition": "RESEARCH",
                "reason": "Historical fixture card",
                "required_mw": None,
                "start_window": None,
                "duration": None,
                "supply": "Unknown",
                "stage": {"stage": "Signal", "date": None, "source_url": None, "evidence_id": None},
                "organization": None,
                "organization_role": None,
                "hypothesis": None,
                "next_question": "What is the temporary power requirement?",
                "next_action": "Review retained evidence",
                "conflict_state": None,
                "input_hash": f"{len(fact_refs)}-facts",
                "operator_fact_refs": fact_refs,
            }
            save_evaluations(session, [card], now=moment)
            pursuit = session.scalar(
                select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
            )
            return pursuit.snapshot["commercial_triage"]["versions"][-1]["saved_card"]

    first_time = datetime.now(UTC)
    before_fact = save(first_time)
    fact_id, _ = _seed_historical_fact(
        factory, need_id, project_id, pursuit_id, "demand", {"mw": "22"}
    )
    after_fact = save(first_time + timedelta(seconds=1))
    assert before_fact.get("operator_fact_refs") in (None, [])
    assert after_fact["operator_fact_refs"][0]["fact_version_id"] == str(fact_id)
    with factory() as session:
        pursuit = session.scalar(
            select(Pursuit).where(Pursuit.identity_key == f"commercial-need:{need_id}")
        )
        snapshots = pursuit.snapshot["commercial_triage"]["versions"]
        assert snapshots[0]["saved_card"] == before_fact
        assert snapshots[1]["saved_card"] == after_fact


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
                    facility_scope="Austin, TX",
                    fact_type="demand",
                    value={"mw": "20", "basis": "Synthetic bounded fixture"},
                    reporter_name="Synthetic source reporter",
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
        assert (
            session.scalar(
                select(func.count())
                .select_from(CallFactVersion)
                .where(CallFactVersion.need_id == need_id)
            )
            == number_of_rows
        )
