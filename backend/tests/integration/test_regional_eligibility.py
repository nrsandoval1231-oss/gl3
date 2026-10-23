"""Persisted regional eligibility matrix on isolated PostgreSQL schemas."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.persistence.database import Base
from gridlens.persistence.models import Project, Source
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


@pytest.fixture
def regional_db():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for persisted regional policy tests")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    schema = "regional_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


CASES = [
    ("Dallas, TX", {}, "ELIGIBLE", "TX"),
    ("Tulsa, OK", {}, "ELIGIBLE", "OK"),
    ("Albuquerque, NM", {}, "ELIGIBLE", "NM"),
    ("Boston, MA", {}, "EXCLUDED", "MA"),
    ("Santa Clara, CA", {}, "EXCLUDED", "CA"),
    ("Atlanta, GA", {}, "EXCLUDED", "GA"),
    ("Austin, TX; Atlanta, GA", {}, "HOLD", None),
    ("Austin, TX 78701; Tulsa, OK 74103", {}, "HOLD", None),
    ("Austin", {}, "HOLD", None),
    (None, {}, "HOLD", None),
    ("Unknown", {}, "HOLD", None),
    (None, {"headquarters": "Dallas, TX"}, "HOLD", None),
    (None, {"source_geography": "Texas"}, "HOLD", None),
    ("Austin, TX", {"site": "Tulsa, OK"}, "HOLD", None),
    ("Austin, TX / Tulsa, OK", {}, "HOLD", None),
    ("Austin, TX; Santa Clara, CA", {}, "HOLD", None),
    ("Made in Texas", {}, "HOLD", None),
    ("EVERYTHING IS OK", {}, "HOLD", None),
    ("Everything Is OK", {}, "HOLD", None),
    ("Austin, TX; Everything Is OK", {}, "HOLD", None),
    ("Atlanta, GA and Austin, TX", {}, "HOLD", None),
    ("Austin, TX and Atlanta, GA", {}, "HOLD", None),
    ("Dallas, TX and Austin, TX", {}, "ELIGIBLE", "TX"),
    ("Austin, TX; Atlanta Georgia", {}, "HOLD", None),
    ("Atlanta Georgia and Austin, TX", {}, "HOLD", None),
    ("Las Cruces NM", {}, "HOLD", None),
    ("TULSA OK", {}, "HOLD", None),
    ("TULSA OK 74103", {}, "ELIGIBLE", "OK"),
    (
        "Abilene, TX",
        {"crossborder_supporting_evidence": "Santa Clara, CA"},
        "ELIGIBLE",
        "TX",
    ),
    ("Austin, TX", {"headquarters": "San Jose, CA"}, "ELIGIBLE", "TX"),
]


@pytest.mark.parametrize("location,facts,status,state", CASES)
def test_region_decision_is_persisted_from_site_fields_only(
    regional_db, location, facts, status, state
):
    with regional_db.begin() as session:
        session.add(
            Source(
                id="synthetic-permits",
                publisher="Synthetic",
                endpoint="https://example.test",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="synthetic",
                health={},
            )
        )
        session.flush()
        project = Project(
            identity_key=f"regional-{uuid4()}",
            name="Synthetic permitted project",
            location=location,
            identity_facts=facts,
            source_id="synthetic-permits",
            external_id=str(uuid4()),
        )
        session.add(project)
        session.flush()
        assert (project.region_status, project.region_state) == (status, state)
        project_id = project.id
    with regional_db() as session:
        stored = session.scalar(select(Project).where(Project.id == project_id))
        assert stored is not None
        assert (stored.region_status, stored.region_state) == (status, state)
        if status == "ELIGIBLE":
            assert stored.region_provenance["policy_version"] == "regional-project-scope-v1"


def test_region_reclassification_on_site_update_does_not_delete_supporting_facts(regional_db):
    with regional_db.begin() as session:
        session.add(
            Source(
                id="synthetic-permits",
                publisher="Synthetic",
                endpoint="https://example.test",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="synthetic",
                health={},
            )
        )
        session.flush()
        project = Project(
            identity_key=f"regional-{uuid4()}",
            name="Synthetic cross-border project",
            location="Dallas, TX",
            identity_facts={"crossborder_supporting_evidence": "Santa Clara, CA"},
            source_id="synthetic-permits",
            external_id=str(uuid4()),
        )
        session.add(project)
        session.flush()
        project_id = project.id
        assert project.region_status == "ELIGIBLE"
    with regional_db.begin() as session:
        project = session.get(Project, project_id)
        project.location = "Austin, TX / Tulsa, OK"
    with regional_db() as session:
        stored = session.get(Project, project_id)
        assert stored.region_status == "HOLD"
        assert stored.identity_facts["crossborder_supporting_evidence"] == "Santa Clara, CA"


def test_direct_project_state_fences_noneligible_projects_and_preserves_history(
    saved_db, monkeypatch
):
    from fastapi import HTTPException
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.persistence.models import Evidence, NeedObservation, Observation, PowerNeed

    seed(saved_db, count=0)
    locations = {
        "ca": "Santa Clara, CA",
        "ga": "Atlanta, GA",
        "hold_unknown": None,
        "hold_conflict": "Austin, TX / Tulsa, OK",
        "tx": "Dallas, TX",
        "ok": "Tulsa, OK",
        "nm": "Albuquerque, NM",
    }
    project_ids = {}
    need_ids = {}
    historical_need_id = None
    historical_hash = "a" * 64
    with saved_db.begin() as session:
        for key, location in locations.items():
            project = Project(
                identity_key=f"state-fence-{key}-{uuid4()}",
                name=f"Retained {key} project",
                location=location,
                source_id="synthetic-permits",
                external_id=f"state-fence-{key}",
            )
            session.add(project)
            session.flush()
            need = PowerNeed(
                project_id=project.id,
                activity_key=f"current-{key}",
                tier="Signal",
                rationale="Retained active need for endpoint boundary verification.",
                supply="Unknown",
                active=True,
            )
            session.add(need)
            session.flush()
            project_ids[key] = project.id
            need_ids[key] = need.id
        historical_need = PowerNeed(
            project_id=project_ids["ca"],
            activity_key="historical-ca",
            tier="Signal",
            rationale="Prior retained need remains historical.",
            supply="Unknown",
            active=False,
        )
        session.add(historical_need)
        session.flush()
        historical_need_id = historical_need.id
        observation = Observation(
            source_id="synthetic-permits",
            external_id="historical-ca-evidence",
            title="Historical California project evidence",
            abstract="Retained source record for historical access.",
            url="https://example.test/historical-ca",
            content_hash=historical_hash,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=historical_hash,
            title=observation.title,
            abstract=observation.abstract,
            url=observation.url,
        )
        session.add(evidence)
        session.flush()
        session.add(NeedObservation(need_id=historical_need.id, observation_id=observation.id))
        expected_status = {
            "ca": "EXCLUDED",
            "ga": "EXCLUDED",
            "hold_unknown": "HOLD",
            "hold_conflict": "HOLD",
            "tx": "ELIGIBLE",
            "ok": "ELIGIBLE",
            "nm": "ELIGIBLE",
        }
        assert {key: session.get(Project, project_ids[key]).region_status for key in locations} == (
            expected_status
        )

    original_reader = api.read_project_state
    hydrated: list[object] = []

    def guarded_reader(session, project_id):
        hydrated.append(project_id)
        return original_reader(session, project_id)

    monkeypatch.setattr(api, "read_project_state", guarded_reader)
    for key in ("ca", "ga", "hold_unknown", "hold_conflict"):
        with pytest.raises(HTTPException) as error:
            api.project_state_endpoint(project_ids[key])
        assert error.value.status_code == 404
    assert hydrated == []

    for key in ("tx", "ok", "nm"):
        result = api.project_state_endpoint(project_ids[key])
        assert result["project_id"] == str(project_ids[key])
        assert result["state"]["power_need"]["status"] == "UNKNOWN"

    history = api.workspace_historical_need(historical_need_id)
    assert history["active"] is False
    assert history["project_id"] == project_ids["ca"]
    assert history["evidence"][0]["content_hash"] == historical_hash
    with saved_db() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.content_hash == historical_hash)
            )
            == 1
        )
        assert session.get(PowerNeed, need_ids["ca"]).active is True
        assert session.get(PowerNeed, historical_need_id).active is False


def test_active_api_projection_includes_only_persisted_eligible_region(saved_db):
    from test_saved_browse import seed

    from gridlens.persistence.models import PowerNeed

    ids = seed(saved_db, count=4, histories=1)
    # Generic seed rows are all positive TX/NM examples. Set these two sites
    # explicitly outside scope so this projection test retains negative coverage.
    with saved_db.begin() as session:
        for need_id in (ids[0], ids[2]):
            need = session.get(PowerNeed, need_id)
            project = session.get(Project, need.project_id)
            project.location = "Santa Clara, CA"
    from gridlens.api import app as api

    visible = api.opportunities(tier="Signal", limit=50, offset=0, cohort=None)
    assert len(visible) == 2
    assert {item["id"] for item in visible} == {ids[1], ids[3]}
