"""Physical project labels are independent of selected need/source titles."""

import hashlib

from sqlalchemy import select

from gridlens.intelligence.project_results import page
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseRow,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)

pytest_plugins = ["test_saved_browse"]


def test_exact_physical_project_name_survives_representative_need_change(saved_db):
    from test_saved_browse import seed

    need_ids = seed(saved_db, count=3, histories=1)
    with saved_db.begin() as session:
        needs = [session.get(PowerNeed, need_id) for need_id in need_ids]
        physical_id, other_id = needs[0].project_id, needs[2].project_id
        project = session.get(Project, physical_id)
        project.name = "Canonical Campus A"
        session.get(Project, other_id).name = "Canonical Campus B"
        needs[1].project_id = physical_id
        needs[1].activity_key = "commissioning"
        observation = session.scalar(
            select(Observation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id == needs[1].id)
        )
        evidence = session.scalar(select(Evidence).where(Evidence.observation_id == observation.id))
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        observation.title = evidence.title = "Canonical Campus A commissioning"
        observation.abstract = evidence.abstract = "Synthetic commissioning permit at Campus A."
        evidence.extraction_location = "Synthetic"
        version = hashlib.sha256(
            f"{observation.title}\n{observation.abstract}".encode()
        ).hexdigest()
        observation.content_hash = evidence.content_hash = interpretation.content_hash = version
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": version,
            "evidence_hash": version,
            "project_identity_key": project.identity_key,
            "power_activity": "commissioning",
            "subject": project.name,
            "location": project.location,
        }
    rebuild(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        assert {row.need_id for row in rows} == set(need_ids)
        for row in rows:
            index = need_ids.index(row.need_id)
            row.compact = {
                **row.compact,
                "name": f"Need-specific commissioning {index}",
                "project_metadata": {
                    "title": f"Project: raw permit {index} Location: full source paragraph",
                    "sector": "data_centers",
                },
            }
            row.rank_score = 999 if row.need_id == need_ids[0] else 1
        first_need, second_need = str(need_ids[0]), str(need_ids[1])

    with saved_db() as session:
        first = page(session, include_signals=True, sort="project")
    with saved_db.begin() as session:
        rows = session.scalars(
            select(BrowseRow).where(BrowseRow.need_id.in_([first_need, second_need]))
        ).all()
        for row in rows:
            row.rank_score = 999 if str(row.need_id) == second_need else 1
    with saved_db() as session:
        second = page(session, include_signals=True, sort="project")
        for result in (first, second):
            assert [item["name"] for item in result["items"]] == [
                "Canonical Campus A",
                "Canonical Campus B",
            ]
            campus = result["items"][0]
            assert campus["project_id"] == str(physical_id)
            assert campus["project_ids"] == [str(physical_id)]
            assert {need["id"] for need in campus["needs"]} == {first_need, second_need}
        assert first["items"][0]["representative_need_id"] == first_need
        assert second["items"][0]["representative_need_id"] == second_need
        assert first["items"][0]["id"] == second["items"][0]["id"]
