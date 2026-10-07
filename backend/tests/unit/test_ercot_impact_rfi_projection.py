from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from gridlens.domain.ercot_impact_rfi import VERSION
from gridlens.intelligence.ercot_impact_rfi import public_rfi_state
from gridlens.persistence.models import Evidence, Interpretation, Observation, Project, Source


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@pytest.mark.parametrize("invalid", [None, "stale", "wrong_site", "quote", "aggregate", "id"])
def test_real_orm_projection_requires_exact_public_project_support(invalid):
    engine = create_engine("sqlite://")
    for model in (Source, Observation, Evidence, Project, Interpretation):
        model.__table__.create(engine)
    with Session(engine) as session:
        source = Source(
            id="rfi",
            publisher="ERCOT",
            endpoint="https://www.ercot.com/",
            family="ercot-impact-rfi",
            geography="Texas",
            industries=[],
            retrieval_method="ercot-impact-rfi-project",
        )
        oid, eid = uuid4(), uuid4()
        project = Project(
            id=uuid4(), identity_key="site", name="Example", source_id="rfi", external_id="site"
        )
        observation = Observation(
            id=oid,
            source_id="rfi",
            external_id="1",
            title="Example",
            url=source.endpoint,
            content_hash="a" * 64,
        )
        evidence = Evidence(
            id=eid,
            observation_id=oid,
            title="Example",
            abstract="Region C",
            url=source.endpoint,
            content_hash="a" * 64,
            published_at=date(2026, 10, 7),
        )
        record = {
            "publication_state": "public_project_disclosure",
            "project_identity_key": "site",
            "evidence_id": str(eid),
            "evidence_hash": "a" * 64,
            "claims": {"regional_water_planning_group": {"value": "Region C", "quote": "Region C"}},
        }
        if invalid == "wrong_site":
            record["project_identity_key"] = "other"
        if invalid == "quote":
            record["claims"]["regional_water_planning_group"]["quote"] = "not present"
        if invalid == "aggregate":
            record["publication_state"] = "public_aggregate"
        if invalid == "id":
            record["evidence_id"] = str(uuid4())
        interpretation = Interpretation(
            observation_id=oid,
            content_hash="a" * 64,
            evaluator_version=VERSION,
            status="accepted",
            assessment={"evidence_hash": "a" * 64, "ercot_impact_rfi": record},
        )
        if invalid == "stale":
            observation.content_hash = "b" * 64
        session.add_all([source, observation, evidence, project, interpretation])
        session.commit()
        state = public_rfi_state(session, project)
        assert len(state["disclosures"]) == (1 if invalid is None else 0)
        if invalid is None:
            assert state["disclosures"][0]["respondent_category"] == "UNKNOWN"
            assert (
                state["disclosures"][0]["claims"]["regional_water_planning_group"]["value"]
                == "Region C"
            )
