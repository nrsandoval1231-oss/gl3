from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.saved_browse import POLICY_VERSION
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    BuyingChainClaim,
    CompanyIdentity,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def search_runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    admin = create_engine(settings.test_database_url)
    schema = "unified_search_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    api = import_module("gridlens.api.app")
    security = import_module("gridlens.security")
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(security, "valid_token", lambda _token: True)
    yield factory, api
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _seed_project(session, *, name="Acme Modular Site"):
    source = Source(
        id="unified-search-fixture",
        publisher="Synthetic source",
        endpoint="https://example.test/search",
        family="permits",
        geography="Texas",
        industries=["construction"],
        retrieval_method="test",
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key="unified-search-" + uuid4().hex,
        name=name,
        location="Austin, TX",
        source_id=source.id,
        external_id=uuid4().hex,
    )
    session.add(project)
    session.flush()
    need = PowerNeed(
        project_id=project.id,
        activity_key="construction",
        tier="Lead",
        rationale="Current source-backed construction activity",
    )
    session.add(need)
    session.flush()
    return project, need


def test_search_returns_project_hits_while_saved_browse_is_pending(search_runtime):
    factory, api = search_runtime
    with factory.begin() as session:
        project, need = _seed_project(session)

    client = TestClient(api.app)
    client.cookies.set("gridlens_session", "test")
    response = client.get("/api/search", params={"q": "Acme"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["projects"][0]["project_id"] == str(project.id)
    assert payload["projects"][0]["need_id"] == str(need.id)
    assert payload["companies"] == [] and payload["companies_status"] == "qualification_pending"
    assert payload["opportunities"] == []
    assert payload["opportunities_status"] == "qualification_pending"


def test_search_normalizes_saved_company_opportunity_and_contact_hits(search_runtime, monkeypatch):
    factory, api = search_runtime
    now = datetime.now(UTC)
    generation_id, company_id = uuid4(), uuid4()
    with factory.begin() as session:
        project, need = _seed_project(session)
        generation = BrowseGeneration(
            id=generation_id,
            input_revision=0,
            policy_version=POLICY_VERSION,
            built_at=now,
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(days=1),
            row_count=1,
            digest="unified-search-generation",
            counts={"ALL": {}},
        )
        session.add_all(
            [
                generation,
                CompanyIdentity(id=company_id),
                BrowseState(id=1, input_revision=0, generation_id=generation_id),
            ]
        )
        session.add(
            BuyingChainClaim(
                project_id=project.id,
                entity_key="contact-entity",
                fingerprint="contact-claim-fingerprint",
                policy_version="contact-search-test",
                organization="Acme Energy Holdings",
                person_name="Riley Example",
                title="Power procurement lead",
                category="owner",
                organization_relationship="DIRECT",
                person_organization_relationship="DIRECT",
                person_project_relationship="DIRECT",
                evidence_strength="HIGH",
                reason="Named in a current public project filing.",
                citations=[],
                public_contacts=[
                    {
                        "kind": "email",
                        "value": "riley@example.test",
                        "source_url": "https://example.test/source",
                    }
                ],
                observed_at=now,
                verified_at=now,
            )
        )

        session.flush()
        compact = {
            "id": str(need.id),
            "project_id": str(project.id),
            "name": project.name,
            "location": project.location,
            "tier": "Lead",
            "activity": "construction",
            "required_mw": "0.3",
            "commercial_preview": {"disposition": "RESEARCH"},
        }
        session.add_all(
            [
                BrowseRow(
                    generation_id=generation_id,
                    need_id=need.id,
                    project_id=project.id,
                    tier="Lead",
                    location="Austin, TX",
                    industry="Construction",
                    activity="construction",
                    has_timing=False,
                    mw_low=None,
                    mw_high=None,
                    priority_segment=1,
                    workflow_status="UNKNOWN",
                    signal_decision="UNKNOWN",
                    project_group="group-unified-search",
                    single_group="single-unified-search",
                    rank_score=100,
                    updated_at=now,
                    search_text="acme modular site current construction evidence",
                    display_title=project.name,
                    commercial_group=None,
                    commercial_segment=None,
                    commercial_geography=None,
                    commercial_date=None,
                    summary={},
                    compact=compact,
                ),
                BrowseCustomerMembership(
                    generation_id=generation_id,
                    company_identity_id=company_id,
                    project_id=project.id,
                    organization_name="Acme Energy Holdings",
                    role="owner_developer",
                    supporting_evidence_count=2,
                    last_evidence_update=now,
                ),
            ]
        )

    buying_chain = import_module("gridlens.intelligence.buying_chain")
    monkeypatch.setattr(
        buying_chain,
        "buying_chain_views",
        lambda _session, ids: {
            str(project.id): {
                "candidates": [
                    {
                        "company_identity_id": company_id,
                        "person_name": "Riley Example",
                        "title": "Power procurement lead",
                        "organization": "Acme Energy Holdings",
                        "public_contacts": [
                            {
                                "kind": "email",
                                "value": "riley@example.test",
                                "source_url": "https://example.test/source",
                            }
                        ],
                        "evidence": [{"url": "https://example.test/source"}],
                        "stale": False,
                    }
                ]
            }
            for project_id in ids
        },
    )
    client = TestClient(api.app)
    client.cookies.set("gridlens_session", "test")
    response = client.get("/api/search", params={"q": "Acme"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["companies_status"] == "current"
    assert payload["companies"][0]["company_identity_id"] == str(company_id)
    assert payload["companies"][0]["name"] == "Acme Energy Holdings"
    assert payload["opportunities_status"] == "current"
    assert payload["opportunities"][0]["need_id"] == str(need.id)
    assert payload["opportunities"][0]["name"] == project.name
    assert payload["contacts"][0]["need_id"] == str(need.id)
    assert payload["contacts"][0]["company_identity_id"] == str(company_id)
    assert payload["contacts"][0]["methods"][0]["value"] == "riley@example.test"
    assert payload["contacts"][0]["sources"][0]["url"] == "https://example.test/source"
