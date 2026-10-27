"""PostgreSQL project-first projection and authenticated route contracts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    method_suppression_key,
    person_suppression_key,
)
from gridlens.intelligence.project_results import page
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import BrowseRow
from gridlens.persistence.suppression_models import ContactSuppression
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _seed_project_metadata(factory):
    from test_saved_browse import seed

    seed(factory, count=5, histories=1)
    company_id, person_id = uuid4(), uuid4()
    rebuild(factory)
    with factory.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.need_id)
        ).all()
        assert len(rows) == 5
        # Two needs share a Project, a separate permit Project validates to
        # that same well API, and another API stays distinct under the operator.
        rows[1].project_id = rows[0].project_id
        for index, row in enumerate(rows):
            category = "oil_gas" if index < 4 else "data_centers"
            identity = None
            if index < 3:
                identity = {
                    "kind": "us_well_api",
                    "value": "4216538299",
                    "identity_validated": True,
                }
            elif index == 3:
                identity = {
                    "kind": "us_well_api",
                    "value": "4216538001",
                    "identity_validated": True,
                }
            row.compact = {
                **row.compact,
                "project_metadata": {
                    "sector": category,
                    "title": f"Asset {index}",
                    "operator": "Same Operator",
                    "event": None,
                    "asset_identity": identity,
                },
                "contact_actions": [
                    {
                        "kind": "email",
                        "href": "mailto:private@example.invalid",
                        "company": "Same Operator",
                        "name": "Private Person",
                        "company_identity_id": str(company_id),
                        "person_identity_id": str(person_id),
                        "claim_id": f"claim-{index}",
                    }
                ],
                "contact_people": [
                    {
                        "record_type": "contact_person",
                        "company_identity_id": str(company_id),
                        "person_identity_id": str(person_id),
                        "company": "Same Operator",
                        "name": "Private Person",
                        "role": "operations",
                    }
                ],
                "contacts": [{"email": "suppressed@example.invalid"}],
            }
        return company_id


def test_project_groups_needs_filters_sector_and_fences_pagination(saved_db):
    company_id = _seed_project_metadata(saved_db)
    with saved_db() as session:
        default = page(session, sector="all")
        assert default["total"] == 0 and default["items"] == []
        assert default["results_scope"] == "qualified"
        first = page(session, sector="all", search="Synthetic", limit=1)
        assert first["count_unit"] == "projects"
        assert first["total"] == 3
        full = page(session, sector="all", search="Synthetic", limit=50)
        grouped = next(item for item in full["items"] if item["need_count"] == 3)
        assert grouped["company"] == "Same Operator"
        assert len(grouped["project_ids"]) == 2
        assert grouped["asset_identity"]["value"] == "4216538299"
        assert grouped["id"] not in grouped["project_ids"]
        assert grouped["project_id"] in grouped["project_ids"]
        scoped = page(session, need_id=UUID(grouped["needs"][0]["id"]), limit=1)
        assert scoped["total"] == 1 and scoped["items"][0]["id"] == grouped["id"]
        assert scoped["items"][0]["need_count"] == 3
        assert scoped["results_scope"] == "discovery"
        assert page(session, need_id=uuid4())["items"] == []
        assert "contacts" not in grouped["needs"][0]
        assert "suppressed@example.invalid" not in repr(full["items"])
        second = page(
            session,
            sector="all",
            search="Synthetic",
            limit=1,
            offset=1,
            token=first["cohort_token"],
        )
        assert second["items"][0]["id"] != first["items"][0]["id"]
        oil = page(session, sector="oil_gas")
        dc = page(session, sector="data_centers")
        assert oil["total"] == 2
        assert sorted(item["need_count"] for item in oil["items"]) == [1, 3]
        assert len({item["id"] for item in oil["items"]}) == 2
        assert dc["total"] == 1 and dc["items"][0]["sector"] == "data_centers"
        with pytest.raises(HTTPException) as stale:
            page(session, sector="oil_gas", offset=1, token=first["cohort_token"])
        assert getattr(stale.value, "status_code", None) in {409, 422}
        before_suppression = page(session, sector="oil_gas")
        assert before_suppression["items"][0]["contact"]
        assert before_suppression["items"][0]["contact_people"]
        action = before_suppression["items"][0]["contact"][0]
        assert "company_identity_id" not in action and "claim_id" not in action
    # Method suppression added after snapshot creation removes call/email routes
    # while preserving a separately supported named person without a method.
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="method",
                subject_key=method_suppression_key(
                    company_id, "Private Person", "email", "mailto:private@example.invalid"
                ),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration method suppression",
                actor="test",
                idempotency_key="issue128-project-results-method",
            )
        )
    with saved_db() as session:
        method_suppressed = page(session, sector="oil_gas")
        assert method_suppressed["items"][0]["contact"] == []
        assert method_suppressed["items"][0]["contact_people"]
        assert all(
            not need.get("contact_actions") for need in method_suppressed["items"][0]["needs"]
        )
        assert all(need.get("contact_people") for need in method_suppressed["items"][0]["needs"])
    # Person suppression removes the role record as well; company suppression
    # then covers every company-level route regardless of person or method.
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="person",
                subject_key=person_suppression_key(company_id, "Private Person"),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration person suppression",
                actor="test",
                idempotency_key="issue128-project-results-person",
            )
        )
    with saved_db() as session:
        person_suppressed = page(session, sector="oil_gas")
        assert person_suppressed["items"][0]["contact_people"] == []
    with saved_db.begin() as writer:
        writer.add(
            ContactSuppression(
                scope="company",
                subject_key=company_suppression_key(company_id),
                expected_version=0,
                version=1,
                action="suppress",
                reason="integration company suppression",
                actor="test",
                idempotency_key="issue128-project-results-company",
            )
        )
    with saved_db() as session:
        company_suppressed = page(session, sector="oil_gas")
        assert company_suppressed["items"][0]["contact"] == []
        assert company_suppressed["items"][0]["contact_people"] == []


def test_project_results_route_requires_session(saved_db, monkeypatch):
    _seed_project_metadata(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    import gridlens.api.app as api

    monkeypatch.setattr(api, "SessionLocal", saved_db)
    with TestClient(api.app, base_url="https://testserver") as client:
        response = client.get("/api/opportunities/projects")
        assert response.status_code == 401
        client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
        response = client.get("/api/opportunities/projects?sector=oil_gas")
        assert response.status_code == 200, response.text
        assert response.json()["count_unit"] == "projects"
