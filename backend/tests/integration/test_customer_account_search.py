"""Search account names from saved customer memberships without shrinking totals."""

import json
from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.contact_suppressions import global_person_suppression_key
from gridlens.intelligence.customer_accounts import (
    _safe_need_summary,
    account_browse_page,
    account_queue,
)
from gridlens.intelligence.pursuit_workspace import query_plan
from gridlens.intelligence.saved_browse import POLICY_VERSION
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
    PersonIdentity,
    Project,
    Source,
)
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.security import token_for
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


def test_company_search_matches_membership_alias_and_preserves_account_totals(
    search_db, monkeypatch
):
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
                    supporting_evidence_count=2 if index == 0 else 4,
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
        assert browse["items"][0]["commercial_brief"]["best_contact"] is None
        assert browse["items"][0]["commercial_brief"]["power_need"]["value"] is None
        assert browse["counts"]["action_now"] == 1
        assert browse["counts"]["research"] == 2

        alias_queue = account_queue(session, search="aoh", limit=25, offset=0)
        assert alias_queue["total"] == 1
        assert alias_queue["items"][0]["project_count"] == 2
        assert alias_queue["items"][0]["need_count"] == 3
        assert alias_queue["items"][0]["aliases"] == ["AOH", "Acme Owner Holdings"]
        assert alias_queue["items"][0]["supporting_evidence_count"] == 4
        assert alias_queue["items"][0]["last_evidence_update"] == now
        assert alias_queue["items"][0]["qualification_tiers"] == ["Lead"]
        assert alias_queue["items"][0]["highest_priority_need"]["id"] == str(need_ids[0])
        assert (
            alias_queue["items"][0]["highest_priority_need"]["commercial_brief"]["best_contact"]
            is None
        )
        all_accounts = account_queue(session, search=None, limit=25, offset=0)
        assert all_accounts["total"] == alias_queue["total"]
        assert (
            all_accounts["items"][0]["company_identity_id"]
            == alias_queue["items"][0]["company_identity_id"]
        )
        assert account_queue(session, search="missing", limit=25, offset=0)["total"] == 0
        assert account_queue(session, search=None, limit=25, offset=1)["items"] == []

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

    hidden_name = "Suppressed Account Contact"
    with search_db.begin() as session:
        project = session.scalar(select(Project).order_by(Project.name))
        row = session.scalar(select(BrowseRow).order_by(BrowseRow.rank_score.desc()))
        person = PersonIdentity()
        session.add(person)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="account-brief-contact",
            fingerprint="a" * 64,
            policy_version="fixture-v1",
            organization="Acme Owner Holdings",
            person_name=hidden_name,
            title="Project director",
            category="owner",
            organization_relationship="owner",
            person_organization_relationship="employee",
            person_project_relationship="project_contact",
            evidence_strength="high",
            reason="Fixture for account summary privacy projection.",
            citations=[],
            public_contacts=[],
            observed_at=now,
        )
        session.add(claim)
        session.flush()
        source = BuyingChainEvidence(
            project_id=project.id,
            url="https://example.test/account-brief-contact",
            title="Account contact source",
            excerpt="Account contact source fixture.",
            content_hash="b" * 64,
            extraction_location="Fixture",
            observed_at=now,
            last_seen_at=now,
            project_match_reason="Test scoped privacy record",
        )
        session.add(source)
        session.flush()
        session.add(
            BuyingChainIdentityLink(
                claim_id=claim.id,
                entity_type="person",
                person_identity_id=person.id,
                company_identity_id=None,
                reason="Fixture person identity",
                basis="strong_identifier",
                source_evidence_id=source.id,
                source_version_hash=source.content_hash,
                state="current",
            )
        )
        session.add(
            ContactSuppression(
                scope="person",
                subject_key=global_person_suppression_key(person.id),
                expected_version=0,
                version=1,
                action="suppress",
                reason="fixture suppression",
                actor="test",
                idempotency_key="account-brief-person-suppression",
            )
        )
        row.compact = {
            **row.compact,
            "commercial_preview": {
                **row.compact["commercial_preview"],
                "next_action": f"Confirm details with {hidden_name}",
            },
        }

    with search_db() as session:
        for projection in (
            account_queue(session, search="aoh", limit=25, offset=0)["items"][0][
                "highest_priority_need"
            ],
            account_browse_page(session, filters, limit=25, offset=0, token=None)["items"][0],
            _safe_need_summary(
                session,
                json.dumps(
                    session.scalar(select(BrowseRow).order_by(BrowseRow.rank_score.desc())).compact
                ),
            ),
        ):
            assert hidden_name not in repr(projection["commercial_brief"])

    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", search_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    endpoint = client.get("/api/customer-accounts", params={"search": "aoh"})
    assert endpoint.status_code == 200, endpoint.text
    account = endpoint.json()["items"][0]
    assert hidden_name not in repr(account["highest_priority_need"]["commercial_brief"])
