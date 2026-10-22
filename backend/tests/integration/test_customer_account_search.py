"""Search account names from saved customer memberships without shrinking totals."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.customer_accounts import account_browse_page, account_queue
from gridlens.intelligence.pursuit_workspace import query_plan
from gridlens.intelligence.saved_browse import POLICY_VERSION
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CompanyIdentity,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def search_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    schema = "account_search_" + uuid4().hex
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


def test_company_search_matches_membership_alias_and_preserves_account_totals(search_db):
    now = datetime.now(UTC)
    generation_id, identity_id = uuid4(), uuid4()
    project_ids, need_ids = [uuid4(), uuid4()], [uuid4(), uuid4(), uuid4()]
    with search_db.begin() as session:
        session.add_all(
            [
                CompanyIdentity(id=identity_id, rrc_operator_number="217012"),
                BrowseGeneration(
                    id=generation_id,
                    input_revision=0,
                    policy_version=POLICY_VERSION,
                    built_at=now,
                    valid_from=now,
                    valid_until=now.replace(year=now.year + 1),
                    row_count=3,
                    digest="account-search-generation",
                    counts={},
                ),
            ]
        )
        session.flush()
        session.add(BrowseState(id=1, input_revision=0, generation_id=generation_id))
        session.add(
            Source(
                id="search-fixture",
                publisher="Synthetic",
                endpoint="https://example.test",
                family="permits",
                geography="Texas",
                industries=["construction"],
                retrieval_method="test",
            )
        )
        session.flush()
        for index, project_id in enumerate(project_ids):
            project = Project(
                identity_key=f"account-search-{project_id}",
                name=f"Search site {index}",
                location="Texas",
                source_id="search-fixture",
                external_id=f"search-{index}",
            )
            session.add(project)
            session.flush()
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation_id,
                    company_identity_id=identity_id,
                    project_id=project.id,
                    organization_name=("Acme Owner Holdings" if index == 0 else "AOH"),
                    role="owner_developer",
                    supporting_evidence_count=2,
                    last_evidence_update=now,
                )
            )
            for need_index in [0, 1] if index == 0 else [2]:
                need_id = need_ids[need_index]
                disposition = "ACTION NOW" if need_index == 0 else "RESEARCH"
                compact = {
                    "id": str(need_id),
                    "project_id": str(project.id),
                    "name": project.name,
                    "location": "Texas",
                    "tier": "Lead",
                    "activity": "construction",
                    "required_mw": None,
                    "start_window": None,
                    "duration": None,
                    "supply": "Unknown",
                    "commercial_preview": {
                        "disposition": disposition,
                        "reason": "Review",
                        "next_question": "Need?",
                        "next_action": "Review",
                    },
                }
                session.add(
                    BrowseRow(
                        generation_id=generation_id,
                        need_id=need_id,
                        project_id=project.id,
                        tier="Lead",
                        location="Texas",
                        industry="Construction",
                        activity="construction",
                        has_timing=False,
                        mw_low=None,
                        mw_high=None,
                        priority_segment=1,
                        workflow_status="UNKNOWN",
                        signal_decision="UNKNOWN",
                        project_group=f"group-{project.id}",
                        single_group=f"single-{project.id}",
                        rank_score=100 - need_index,
                        updated_at=now,
                        search_text="permit evidence only",
                        display_title=project.name,
                        commercial_group=None,
                        commercial_segment=None,
                        commercial_geography=None,
                        commercial_date=None,
                        summary={},
                        compact=compact,
                    )
                )
        session.flush()
        filters = {
            "search": "acme owner",
            "tier": None,
            "disposition": None,
            "geography": None,
            "industry": None,
            "industry_group": None,
            "activity": None,
            "timing": None,
            "mw_status": None,
            "mw_min": None,
            "mw_max": None,
            "sort": "priority",
        }
        browse = account_browse_page(session, filters, limit=25, offset=0, token=None)
        assert browse["total"] == 1
        _, need_cohort, _, _, _ = query_plan(session, filters)
        assert browse["cohort_token"] != need_cohort
        assert browse["items"][0]["project_count"] == 2
        assert browse["items"][0]["need_count"] == 3
        assert browse["items"][0]["matching_project_count"] == 2
        assert browse["items"][0]["matching_need_count"] == 3
        assert browse["counts"]["action_now"] == 1
        assert browse["counts"]["research"] == 2

        alias_queue = account_queue(session, search="aoh", limit=25, offset=0)
        assert alias_queue["total"] == 1
        assert alias_queue["items"][0]["project_count"] == 2
        assert alias_queue["items"][0]["need_count"] == 3

        need_search = account_browse_page(
            session, {**filters, "search": "permit"}, limit=25, offset=0, token=None
        )
        assert need_search["total"] == 1
        assert need_search["items"][0]["matching_need_count"] == 3
        assert browse["cohort_token"] != need_search["cohort_token"]
        with pytest.raises(HTTPException) as error:
            account_browse_page(
                session,
                {**filters, "search": "permit"},
                limit=25,
                offset=0,
                token=browse["cohort_token"],
            )
        assert error.value.status_code == 409
        stable_page = account_browse_page(
            session, filters, limit=25, offset=0, token=browse["cohort_token"]
        )
        assert stable_page["cohort_token"] == browse["cohort_token"]
        assert stable_page["items"][0]["company_identity_id"] == identity_id
