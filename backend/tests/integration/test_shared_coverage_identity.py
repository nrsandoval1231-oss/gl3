"""Shared article coverage must not collapse distinct physical campuses."""

from datetime import date
from uuid import uuid4

from sqlalchemy import select

from gridlens.intelligence.account_shortlist import assess_generation
from gridlens.intelligence.customer_results import group_projects, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    CompanyIdentity,
    Evidence,
    NeedObservation,
    Observation,
    Source,
)

pytest_plugins = ["test_saved_browse"]


def test_one_shared_news_story_keeps_two_distinct_campuses_in_both_account_reads(saved_db):
    from test_saved_browse import seed

    need_ids = seed(saved_db, count=2, histories=1)
    owner_id = uuid4()
    rebuild(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        session.add(CompanyIdentity(id=owner_id))
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        assert {row.need_id for row in rows} == set(need_ids)
        session.add(
            Source(
                id="synthetic-shared-news",
                publisher="Synthetic News",
                endpoint="https://example.test/news",
                family="news",
                geography="Texas",
                industries=["data centers"],
                retrieval_method="synthetic-test",
                health={},
            )
        )
        session.flush()
        headline = "Example and Other to build 50MW data center"
        abstract = "Companies to build at named Desert site."
        for index, row in enumerate(rows):
            observation_id, evidence_id = uuid4(), uuid4()
            content_hash = f"{index + 1:064x}"
            session.add(
                Observation(
                    id=observation_id,
                    source_id="synthetic-shared-news",
                    external_id=f"shared-story-campus-{index}",
                    title=headline,
                    abstract=abstract,
                    url="https://example.test/shared-story",
                    content_hash=content_hash,
                    published_at=date(2026, 10, 27),
                )
            )
            session.add(
                Evidence(
                    id=evidence_id,
                    observation_id=observation_id,
                    content_hash=content_hash,
                    title=headline,
                    abstract=abstract,
                    url="https://example.test/shared-story",
                    published_at=date(2026, 10, 27),
                )
            )
            session.flush()
            session.add(NeedObservation(need_id=row.need_id, observation_id=observation_id))
            row.summary = {
                **(row.summary or {}),
                "evidence": [
                    {
                        "id": str(evidence_id),
                        "source_id": "synthetic-shared-news",
                        "assessment_current": True,
                    }
                ],
            }
            row.compact = {
                **(row.compact or {}),
                "project_metadata": {
                    **((row.compact or {}).get("project_metadata") or {}),
                    "sector": "data_centers",
                    "title": f"{('North', 'South')[index]} Campus",
                    "asset_identity": {
                        "kind": "data_center_campus",
                        "value": f"synthetic-campus-{index}",
                        "identity_validated": True,
                    },
                },
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=owner_id,
                    project_id=row.project_id,
                    organization_name="Synthetic Campus Owner",
                    role="owner_developer",
                )
            )
        session.flush()
        assessment = assess_generation(session, generation)
        assert set(assessment["eligible_need_ids"]) == set(need_ids)
        assert assessment["duplicate_project_map"] == {}

    for shortlist in (False, True):
        with saved_db.begin() as session:
            page = groups(
                session,
                sector="data_centers",
                shortlist=shortlist,
                limit=25,
                selected_generation=generation,
            )
            assert page["total"] == 1
            assert len(page["items"]) == 1
            account = page["items"][0]
            assert account["project_count"] == 2
            if shortlist:
                assert account["relevant_project_count"] == 2
                assert account["eligible_need_count"] == 2
            children = group_projects(
                session,
                account["id"],
                sector="data_centers",
                shortlist=shortlist,
                parent_token=page["cohort_token"],
                limit=25,
                selected_generation=generation,
            )
            assert children["total"] == 2
            assert len(children["items"]) == 2
            child_project_ids = [item["project_ids"][0] for item in children["items"]]
            assert len(set(child_project_ids)) == 2


def test_well_api_component_includes_nonpaired_permit_sibling(saved_db):
    """A paired BP/EP duplicate edge must not split one well API asset."""
    from test_saved_browse import seed

    need_ids = seed(saved_db, count=3, histories=1)
    owner_id = uuid4()
    rebuild(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        session.add(CompanyIdentity(id=owner_id))
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        assert {row.need_id for row in rows} == set(need_ids)
        for index, row in enumerate(rows):
            observation_id, evidence_id = uuid4(), uuid4()
            content_hash = f"{index + 10:064x}"
            permit_row = (
                "2026-100000 BP"
                if index == 0
                else "2026-100000 EP"
                if index == 1
                else "2026-200000 EP"
            )
            body = (
                f"row: {permit_row}\naddress: 1 SITE RD\n"
                "description: Generator replacement and new ATS\nstatus: Active"
            )
            session.add(
                Observation(
                    id=observation_id,
                    source_id="synthetic-permits",
                    external_id=f"well-api-permit-{index}",
                    title="Well site electrical upgrade",
                    abstract=body,
                    url=f"https://example.test/permit/{index}",
                    content_hash=content_hash,
                    published_at=date(2026, 10, 27),
                )
            )
            session.add(
                Evidence(
                    id=evidence_id,
                    observation_id=observation_id,
                    content_hash=content_hash,
                    title="Well site electrical upgrade",
                    abstract=body,
                    url=f"https://example.test/permit/{index}",
                    published_at=date(2026, 10, 27),
                )
            )
            session.flush()
            session.add(NeedObservation(need_id=row.need_id, observation_id=observation_id))
            row.summary = {
                **(row.summary or {}),
                "evidence": [
                    {
                        "id": str(evidence_id),
                        "source_id": "synthetic-permits",
                        "assessment_current": True,
                    }
                ],
            }
            row.compact = {
                **(row.compact or {}),
                "project_metadata": {
                    "sector": "oil_gas",
                    "title": f"Well Site Permit {index}",
                    "oil_gas": {"operator_number": "12345"},
                    "asset_identity": {
                        "kind": "us_well_api",
                        "value": "4216500001",
                        "identity_validated": True,
                    },
                },
            }
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=owner_id,
                    project_id=row.project_id,
                    organization_name="Synthetic Well Operator",
                    role="asset_operator",
                )
            )
        session.flush()
        assessment = assess_generation(session, generation)
        assert set(assessment["eligible_need_ids"]) == set(need_ids)
        assert assessment["duplicate_project_map"]
        assert len(set(assessment["duplicate_project_map"].values())) == 1

    for shortlist in (False, True):
        with saved_db.begin() as session:
            page = groups(
                session,
                sector="oil_gas",
                shortlist=shortlist,
                limit=25,
                selected_generation=generation,
            )
            assert page["total"] == 1
            account = page["items"][0]
            assert account["project_count"] == 1
            if shortlist:
                assert account["relevant_project_count"] == 1
                assert account["eligible_need_count"] == 3
            children = group_projects(
                session,
                account["id"],
                sector="oil_gas",
                shortlist=shortlist,
                parent_token=page["cohort_token"],
                limit=25,
                selected_generation=generation,
            )
            assert children["total"] == 1
            assert len(children["items"]) == 1
            child = children["items"][0]
            assert len(child["project_ids"]) == 3
            assert child["need_count"] == 3
            if shortlist:
                assert len(child["eligible_need_ids"]) == 3
