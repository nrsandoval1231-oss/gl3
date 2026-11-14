"""Explicit project-customer roles flow through grouped, searched and API views."""

from datetime import UTC, datetime
from importlib import import_module

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from gridlens.intelligence.customer_results import group_metadata, group_open, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    CompanyIdentity,
    Project,
)
from gridlens.security import token_for
from gridlens.settings import settings

pytest_plugins = ["test_saved_browse"]


def _seed_role_corpus(factory):
    from test_saved_browse import seed

    seed(factory, count=5, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        generation = current_generation(session)
        rows = session.execute(
            select(BrowseRow, Project)
            .join(Project, Project.id == BrowseRow.project_id)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        assert len(rows) == 5
        (
            project_customer,
            operator,
            oil_customer,
            blocked_customer,
            blocked_operator,
            multiple_customer_a,
            multiple_customer_b,
            multiple_operator,
            unknown_customer,
            unknown_operator,
        ) = [CompanyIdentity() for _ in range(10)]
        session.add_all(
            [
                project_customer,
                operator,
                oil_customer,
                blocked_customer,
                blocked_operator,
                multiple_customer_a,
                multiple_customer_b,
                multiple_operator,
                unknown_customer,
                unknown_operator,
            ]
        )
        session.flush()

        for index, (row, project) in enumerate(rows):
            metadata = dict(row.compact.get("project_metadata") or {})
            if index == 0:
                metadata.update(
                    sector="data_centers",
                    title="Direct Customer Facility",
                    operator=None,
                )
                memberships = [
                    (project_customer, "Direct Project Customer", "project_customer"),
                    (operator, "Unpreferred Site Operator", "asset_operator"),
                ]
            elif index == 1:
                metadata.update(
                    sector="oil_gas",
                    title="Oil Project Customer Control",
                    operator=None,
                    oil_gas={},
                )
                memberships = [(oil_customer, "Oil Project Customer", "project_customer")]
            elif index == 2:
                metadata.update(
                    sector="data_centers",
                    title="Blocked Customer Facility",
                    operator=None,
                )
                memberships = [
                    (blocked_customer, "Blocked Project Customer", "project_customer"),
                    (blocked_operator, "Blocked Site Operator", "asset_operator"),
                ]
                session.add(
                    BrowseUnresolvedCustomer(
                        generation_id=generation.id,
                        project_id=project.id,
                        organization_name="Separate conflicting review identity",
                        role="conflicting_customer",
                        reason="Synthetic collision control for role suppression.",
                    )
                )
            elif index == 3:
                metadata.update(
                    sector="data_centers",
                    title="Multiple Customer Facility",
                    operator=None,
                )
                memberships = [
                    (multiple_customer_a, "Multiple Project Customer A", "project_customer"),
                    (multiple_customer_b, "Multiple Project Customer B", "project_customer"),
                    (multiple_operator, "Lower Priority Multiple Operator", "asset_operator"),
                ]
            else:
                metadata.update(
                    sector="unknown",
                    title="Unknown Sector Customer Facility",
                    operator=None,
                )
                memberships = [
                    (unknown_customer, "Unknown Project Customer", "project_customer"),
                    (unknown_operator, "Unknown Sector Operator", "asset_operator"),
                ]
            row.compact = {**row.compact, "project_metadata": metadata}
            for identity, organization, role in memberships:
                session.add(
                    BrowseCustomerMembership(
                        generation_id=generation.id,
                        company_identity_id=identity.id,
                        project_id=project.id,
                        organization_name=organization,
                        role=role,
                    )
                )
        return generation.id, rows[0][1].id, project_customer.id


def test_project_customer_role_matches_group_search_open_and_api(saved_db, monkeypatch):
    generation_id, project_id, primary_identity_id = _seed_role_corpus(saved_db)

    with saved_db() as session:
        direct = groups(
            session,
            search="Direct Project Customer",
            sector="data_centers",
            sort="company",
            limit=10,
            selected_generation=current_generation(session),
        )
        assert direct["total"] == 1
        item = direct["items"][0]
        assert item["name"] == "Direct Project Customer"
        assert item["role"] == "customer"
        assert item["group_kind"] == "resolved_identity"

        # The less-preferred operator is neither selected nor searchable as the
        # primary account when an explicit project-customer role is present.
        hidden = groups(
            session,
            search="Unpreferred Site Operator",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert hidden["total"] == 0

        metadata = group_metadata(
            session,
            item["id"],
            search="Direct Project Customer",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert (metadata["id"], metadata["name"], metadata["group_kind"]) == (
            item["id"],
            item["name"],
            "resolved_identity",
        )
        opened = group_open(
            session,
            item["id"],
            search="Direct Project Customer",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert opened["group"]["id"] == item["id"]
        assert opened["group"]["name"] == item["name"]
        assert [row["customer_identity_id"] for row in opened["projects"]["items"]] == [
            str(primary_identity_id)
        ]
        assert opened["projects"]["items"][0]["project_ids"] == [str(project_id)]

        # A project_customer role is not an oil-and-gas operator or owner.
        oil = groups(
            session,
            sector="oil_gas",
            selected_generation=current_generation(session),
        )
        oil_customer = [row for row in oil["items"] if row["name"] == "Oil Project Customer"]
        assert not oil_customer

        # An explicit conflict remains unresolved and blocks both candidate
        # identities from becoming a resolved project-customer group.
        all_dc = groups(
            session,
            sector="data_centers",
            selected_generation=current_generation(session),
            limit=10,
        )
        blocked = [row for row in all_dc["items"] if row["name"] == "Blocked Customer Facility"]
        assert len(blocked) == 1
        assert blocked[0]["group_kind"] == "unresolved"
        assert blocked[0]["role"] == "unresolved"
        blocked_search = groups(
            session,
            search="Blocked Project Customer",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert blocked_search["total"] == 0

        multiple_a = groups(
            session,
            search="Multiple Project Customer A",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        multiple_b = groups(
            session,
            search="Multiple Project Customer B",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert multiple_a["total"] == multiple_b["total"] == 1
        assert multiple_a["items"][0]["id"] == multiple_b["items"][0]["id"]
        assert multiple_a["items"][0]["name"] == "Multiple Customer Facility"
        assert multiple_a["items"][0]["group_kind"] == "unresolved"
        multiple_open = group_open(
            session,
            multiple_a["items"][0]["id"],
            search="Multiple Project Customer A",
            sector="data_centers",
            selected_generation=current_generation(session),
        )
        assert multiple_open["group"]["group_kind"] == "unresolved"
        assert multiple_open["projects"]["items"][0]["customer_identity_id"] is None

        unknown = groups(
            session,
            search="Unknown Project Customer",
            sector="all",
            selected_generation=current_generation(session),
        )
        assert unknown["total"] == 1
        assert unknown["items"][0]["name"] == "Unknown Sector Customer Facility"
        assert unknown["items"][0]["group_kind"] == "unresolved"
        unknown_open = group_open(
            session,
            unknown["items"][0]["id"],
            search="Unknown Project Customer",
            sector="all",
            selected_generation=current_generation(session),
        )
        assert unknown_open["group"]["group_kind"] == "unresolved"
        assert unknown_open["projects"]["items"][0]["customer_identity_id"] is None

    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", saved_db)
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    response = client.get(
        "/api/opportunities/groups",
        params={
            "search": "Direct Project Customer",
            "sector": "data_centers",
            "sort": "company",
            "limit": 10,
        },
    )
    assert response.status_code == 200, response.text
    api_items = response.json()["items"]
    assert [(row["id"], row["name"], row["role"], row["group_kind"]) for row in api_items] == [
        (item["id"], "Direct Project Customer", "customer", "resolved_identity")
    ]
