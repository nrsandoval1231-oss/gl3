"""Serve-stale reads join the last generation to live tables; prove each join is safe."""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from test_saved_browse import seed

from gridlens.intelligence.contact_suppressions import (
    global_method_suppression_key,
    record_contact_suppression,
)
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.models import (
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    Interpretation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]
EMAIL = "private@example.test"


def _contact_fixture(saved_db):
    """One account whose owner contact email is publicly sourced; returns ids."""
    from gridlens.intelligence.buying_chain import enrich_buying_chain

    ids = seed(saved_db, count=1, histories=1)

    with saved_db.begin() as session:
        project_id = session.scalar(select(PowerNeed.project_id).where(PowerNeed.id == ids[0]))
        project = session.get(Project, project_id)
        assert project is not None
        source_id = "texas-tdlr-tabs-data-centers"
        tabs = "TABS2026026955"
        session.add(
            Source(
                id=source_id,
                publisher="Texas Department of Licensing and Regulation",
                endpoint="https://www.tdlr.texas.gov/TABS/Search/SearchProjects",
                family="construction-permits",
                geography="Texas",
                industries=["data center"],
                retrieval_method="tdlr-tabs",
                health={},
            )
        )
        session.flush()
        project.source_id = "texas-tdlr-tabs-data-centers"
        project.external_id = f"TABS-{tabs}"
        project.name = "Synthetic 0"
        project.location = "Dallas, TX"
        project.identity_key = "site-0"
        excerpt = f"""Project: {project.name}
Location: {project.location}
Registered: 2026-08-04
Developer-reported start: 2026-08-01; completion: 2026-12-01
Estimated cost: $300,000,000
Type of work: New Construction
Scope: New data center building
Owner: Synthetic Customer
Owner contact: Jordan Smith
Owner phone: not stated
Owner contact phone: not stated
Owner email: not stated
Owner contact email: private@example.test
Design firm: Synthetic Design LLC
TABS status: Project Registered"""
        semantic_hash = sha256(excerpt.encode()).hexdigest()
        source_url = f"https://www.tdlr.texas.gov/TABS/Search/Project/{tabs}"
        title = f"{project.name} — TDLR TABS {tabs}"
        observation = Observation(
            source_id=source_id,
            external_id=project.external_id,
            title=title,
            url=source_url,
            abstract=excerpt,
            content_hash=semantic_hash,
        )
        session.add(observation)
        session.flush()
        retained = Evidence(
            observation_id=observation.id,
            title=title,
            abstract=excerpt,
            url=source_url,
            content_hash=semantic_hash,
            observed_at=datetime.now(UTC),
            event_date=datetime(2026, 8, 4).date(),
            event_date_label="Registered with TDLR (Architectural Barriers)",
            extraction_location="TDLR TABS project details page",
        )
        session.add_all(
            [
                retained,
                Interpretation(
                    observation_id=observation.id,
                    content_hash=semantic_hash,
                    evaluator_version="tdlr-tabs-data-center-v1",
                    status="accepted",
                    assessment={
                        "semantic_hash": semantic_hash,
                        "evidence_hash": semantic_hash,
                        "decision": "accepted",
                        "project_identity_key": project.identity_key,
                        "subject": project.name,
                        "location": project.location,
                        "power_activity": "construction",
                        "admission_status": "admitted",
                    },
                ),
            ]
        )
        session.flush()
        native = enrich_buying_chain(session, project.id, retained_only=True)
        native_contact = next(
            candidate
            for candidate in native["candidates"]
            if candidate["person_name"] == "Jordan Smith"
        )
        assert native_contact["public_contacts"] == [
            {
                "kind": "email",
                "value": "private@example.test",
                "source_url": source_url,
                "quote": "Owner contact email: private@example.test",
                "observed_at": retained.observed_at.isoformat(),
            }
        ]
        assert native_contact["company_identity_id"]
        claim_id = native_contact["id"]
        identity_id = native_contact["company_identity_id"]
    return {
        "need_id": ids[0],
        "project_id": project_id,
        "claim_id": claim_id,
        "identity_id": identity_id,
    }


@pytest.fixture
def client_for(saved_db, monkeypatch):
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    return client


def _scoped_write(factory, need_id):
    with factory.begin() as session:
        session.get(PowerNeed, need_id).rationale = "Synthetic scoped change"


def _publish_twice(factory):
    assert rebuild(factory)["status"] == "published"
    assert rebuild(factory)["status"] == "published"


def _pending(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 503, response.text
    assert response.headers["X-Qualification-State"] == "pending"


def _endpoints(client):
    """Return (name, response) for groups, group projects, group open and project page."""
    parent = client.get("/api/opportunities/groups", params={"search": "Synthetic", "limit": 1})
    assert parent.status_code == 200, parent.text
    group_id = parent.json()["items"][0]["id"]
    return {
        "groups": parent,
        "group_projects": client.get(
            f"/api/opportunities/groups/{group_id}/projects",
            params={"search": "Synthetic", "parent_cohort_token": parent.json()["cohort_token"]},
        ),
        "group_open": client.get(
            f"/api/opportunities/groups/{group_id}/open", params={"search": "Synthetic"}
        ),
        "project_page": client.get(
            "/api/opportunities/projects", params={"search": "Synthetic", "include_signals": "true"}
        ),
    }


def test_stale_reads_apply_contact_suppression_added_after_snapshot(
    saved_db, client_for, monkeypatch
):
    fixture = _contact_fixture(saved_db)
    _publish_twice(saved_db)
    baseline = _endpoints(client_for)
    assert all(response.status_code == 200 for response in baseline.values())
    assert EMAIL in baseline["group_open"].text  # the suppression below is not vacuous

    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, fixture["need_id"])
    with saved_db.begin() as session:
        record_contact_suppression(
            session,
            scope="method",
            subject_key=global_method_suppression_key("email", f"mailto:{EMAIL}"),
            action="suppress",
            expected_version=0,
            reason="synthetic privacy regression fixture",
            actor="test",
            idempotency_key="stale-read-suppression",
        )
    stale = _endpoints(client_for)
    for name, response in stale.items():
        assert response.status_code == 200, (name, response.text)
        payload = response.json()
        if name == "group_open":  # the header carries no state; its child page does
            payload = payload["projects"]
        assert payload["refresh_state"] == "updating", name
        assert EMAIL not in response.text, name
        assert str(fixture["claim_id"]) not in response.text, name


def test_need_deleted_after_the_snapshot_closes_the_stale_fence(saved_db, client_for, monkeypatch):
    ids = seed(saved_db, count=3, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, ids[1])  # control: an edit is served as updating
    assert all(r.status_code == 200 for r in _endpoints(client_for).values())
    with saved_db.begin() as session:
        removed = session.get(PowerNeed, ids[0])
        removed_id = str(removed.id)
        session.execute(
            text("DELETE FROM need_observations WHERE need_id = :need_id"), {"need_id": removed.id}
        )
        session.delete(removed)
    # A deleted need must never be shown from the snapshot; readers wait for the rebuild.
    for path in ("/api/opportunities/groups", "/api/opportunities/projects"):
        _pending(client_for, path)
    assert rebuild(saved_db)["status"] == "published"
    rebuilt = _endpoints(client_for)
    assert all(r.status_code == 200 for r in rebuilt.values())
    assert removed_id not in rebuilt["project_page"].text


def test_identity_and_membership_writes_close_the_stale_fence(saved_db, client_for, monkeypatch):
    fixture = _contact_fixture(saved_db)
    with saved_db.begin() as session:
        evidence = session.scalars(select(Evidence)).first()
        session.add(
            CompanyProjectMembership(
                company_identity_id=fixture["identity_id"],
                project_id=fixture["project_id"],
                role="owner",
                organization_name="Synthetic Customer",
                source_id="texas-tdlr-tabs-data-centers",
                source_evidence_id=evidence.id,
                source_version_hash="0" * 64,
                decision_basis="synthetic",
                operator_number="000000",
            )
        )
    _publish_twice(saved_db)
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    # Control: a project-scoped write is served as updating.
    _scoped_write(saved_db, fixture["need_id"])
    assert client_for.get("/api/opportunities/groups").json()["refresh_state"] == "updating"
    assert rebuild(saved_db)["status"] == "published"
    assert client_for.get("/api/opportunities/groups").json()["refresh_state"] == "current"

    with saved_db.begin() as session:  # membership retraction after the snapshot
        membership = session.scalars(select(CompanyProjectMembership)).first()
        assert membership is not None
        membership.state = "retracted"
    _pending(client_for, "/api/opportunities/groups")
    _pending(client_for, "/api/opportunities/projects")
    assert rebuild(saved_db)["status"] == "published"
    assert client_for.get("/api/opportunities/groups").status_code == 200

    with saved_db.begin() as session:  # a linked company identity changes after the snapshot
        session.get(CompanyIdentity, fixture["identity_id"]).rrc_operator_number = "123456"
    _pending(client_for, "/api/opportunities/groups")
    assert rebuild(saved_db)["status"] == "published"
    assert client_for.get("/api/opportunities/groups").status_code == 200

    with saved_db.begin() as session:  # an unrelated orphan identity affects no result
        session.add(CompanyIdentity(rrc_operator_number="654321"))
    assert client_for.get("/api/opportunities/groups").json()["refresh_state"] == "current"


def test_stale_cohort_tokens_are_stable_and_republish_returns_409(
    saved_db, client_for, monkeypatch
):
    ids = seed(saved_db, count=4, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "browse_serve_stale", True)
    _scoped_write(saved_db, ids[0])
    params = {"search": "Synthetic", "limit": 1}
    first = client_for.get("/api/opportunities/groups", params=params)
    assert first.status_code == 200 and first.json()["refresh_state"] == "updating"
    token = first.json()["cohort_token"]
    # More scoped writes while paging must not change the stale cohort.
    _scoped_write(saved_db, ids[1])
    second = client_for.get(
        "/api/opportunities/groups", params={**params, "offset": 1, "cohort_token": token}
    )
    assert second.status_code == 200, second.text
    assert second.json()["cohort_token"] == token
    assert second.json()["generation_id"] == first.json()["generation_id"]
    assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
    # A republish mid-pagination yields 409 rather than mixed pages.
    assert rebuild(saved_db)["status"] == "published"
    third = client_for.get(
        "/api/opportunities/groups", params={**params, "offset": 2, "cohort_token": token}
    )
    assert third.status_code == 409, third.text
