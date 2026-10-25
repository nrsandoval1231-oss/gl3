from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.call_facts import validate_fact
from gridlens.domain.power_enrichment import PowerEnrichment
from gridlens.intelligence.project_enrichment import project_power_enrichment
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    CallFactDecision,
    CallFactVersion,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def power_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database == "power_test", "Refusing database setup outside power_test"
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _schedule(
    *,
    basis="Attributed construction schedule",
    start="2027-01-01",
    end="2027-02-01",
):
    return validate_fact(
        "power_schedule",
        {
            "basis": basis,
            "source_quote": "The operator described the construction package.",
            "phases": [
                {
                    "phase_id": "construction",
                    "start_date": start,
                    "end_date": end,
                    "mw_min": "8",
                    "mw_max": "12",
                    "basis": basis,
                    "supply_coverage": "unknown",
                    "coverage_reason": "Suitable supply is not established",
                }
            ],
            "supplies": [],
        },
    )


def _project(session, *, location="Austin, TX"):
    source = Source(
        id="project-power-enrichment-test",
        publisher="Project power enrichment test",
        endpoint="https://power-enrichment.example",
        family="test",
        geography="TX",
        industries=[],
        retrieval_method="test",
        health={},
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=f"power-enrichment-{uuid4()}",
        name="Test project",
        location=location,
        source_id=source.id,
        external_id=str(uuid4()),
        identity_facts={},
    )
    session.add(project)
    session.flush()
    return project


def _need(session, project, *, activity="construction", active=True):
    need = PowerNeed(
        project_id=project.id,
        activity_key=activity,
        tier="Signal",
        rationale="Project power activity fixture",
        active=active,
    )
    session.add(need)
    session.flush()
    return need


def _accepted_schedule(
    session,
    project,
    need,
    *,
    value=None,
    facility_scope=None,
    decision="accepted",
    decision_version=1,
    content_hash=None,
):
    now = datetime.now(UTC)
    version_id, client_id = uuid4(), uuid4()
    fact = CallFactVersion(
        id=version_id,
        need_id=need.id,
        project_id=project.id,
        client_id=client_id,
        activity_key=need.activity_key,
        facility_scope=facility_scope or project.location,
        fact_type="power_schedule",
        value=value or _schedule(),
        reporter_name="Site electrical lead",
        reporter_organization="Example operator",
        reporter_role="Electrical lead",
        confirmation_channel="phone",
        source_reference="operator-call-17",
        source_date=date(2026, 10, 19),
        confirmed_at=now,
        effective_from=now - timedelta(days=1),
        effective_until=None,
        content_hash=content_hash or "a" * 64,
        recorded_by="power-enrichment-test",
    )
    decision_row = CallFactDecision(
        need_id=need.id,
        fact_version_id=fact.id,
        version=decision_version,
        client_id=client_id,
        decision=decision,
        expected_version=0,
        reason="Fixture fact decision",
        content_hash=fact.content_hash,
        actor="power-enrichment-test",
    )
    session.add(fact)
    session.flush()
    session.add(decision_row)
    session.flush()
    return fact


def test_projects_only_current_accepted_exact_site_schedules(power_db):
    with power_db.begin() as session:
        project = _project(session)
        need = _need(session, project)
        accepted = _accepted_schedule(session, project, need)
        _accepted_schedule(
            session,
            project,
            need,
            facility_scope="Other campus",
            decision="accepted",
            decision_version=2,
            content_hash="b" * 64,
        )
        _accepted_schedule(
            session,
            project,
            need,
            decision="rejected",
            decision_version=3,
            content_hash="c" * 64,
        )

        result = project_power_enrichment(session, project.id)

        assert isinstance(result, PowerEnrichment)
        assert result.status == "UNRESOLVED"
        assert len(result.scenarios) == 1
        scenario = result.scenarios[0]
        assert scenario.project_id == str(project.id)
        assert scenario.need_id == str(need.id)
        assert scenario.activity_key == "construction"
        assert scenario.facility_scope == project.location
        assert (scenario.demand_mw_min, scenario.demand_mw_max) == ("8", "12")
        assert scenario.supply_mw_min is None and scenario.supply_mw_max is None
        assert scenario.sources[0].fact_version_id == str(accepted.id)
        assert scenario.sources[0].source_date == "2026-10-19"


def test_unsuperseded_current_schedule_facts_remain_a_conflict(power_db):
    with power_db.begin() as session:
        project = _project(session)
        need = _need(session, project)
        first = _accepted_schedule(session, project, need)
        second = _accepted_schedule(
            session,
            project,
            need,
            value=_schedule(start="2027-02-01", end="2027-03-01"),
            decision_version=2,
            content_hash="b" * 64,
        )

        result = project_power_enrichment(session, project.id)

        assert result is not None
        assert result.status == "CONFLICT"
        assert result.scenarios == []
        assert first.id != second.id


@pytest.mark.parametrize("location", ["Atlanta, GA", "Unknown location"])
def test_out_of_region_or_unverified_project_returns_none(power_db, location):
    with power_db.begin() as session:
        project = _project(session, location=location)
        _need(session, project)
        assert project_power_enrichment(session, project.id) is None


def test_missing_project_returns_none_and_no_accepted_schedule_returns_no_evidence(power_db):
    with power_db.begin() as session:
        assert project_power_enrichment(session, uuid4()) is None
        project = _project(session)
        need = _need(session, project)
        _accepted_schedule(session, project, need, decision="rejected")
        result = project_power_enrichment(session, project.id)
        assert result is not None
        assert result.status == "NO_EVIDENCE"
        assert result.scenarios == []


def test_inactive_power_need_is_not_projected(power_db):
    with power_db.begin() as session:
        project = _project(session)
        need = _need(session, project, active=False)
        _accepted_schedule(session, project, need)
        result = project_power_enrichment(session, project.id)
        assert result is not None
        assert result.status == "NO_EVIDENCE"
        assert result.scenarios == []
