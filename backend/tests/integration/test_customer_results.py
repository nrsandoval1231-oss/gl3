from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from gridlens.intelligence.customer_results import group_projects, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    CompanyIdentity,
)

pytest_plugins = ["test_saved_browse"]


def _seed_group_cohort(factory):
    from test_saved_browse import seed

    seed(factory, count=66, histories=1)
    contractor_identity = CompanyIdentity(id=uuid4())
    owner_identity = CompanyIdentity(id=uuid4())
    conflicted_identities = [CompanyIdentity(id=uuid4()), CompanyIdentity(id=uuid4())]
    with factory.begin() as session:
        session.add(contractor_identity)
        session.add(owner_identity)
        session.add_all(conflicted_identities)
    result = rebuild(factory)
    assert result["status"] == "published", result
    with factory.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow).where(BrowseRow.generation_id == generation.id)
        ).all()
        for index, row in enumerate(rows):
            if index in {64, 65}:
                title = "Conflicted Customer Site" if index == 64 else "Contractor Site"
                row.compact = {
                    **row.compact,
                    "project_metadata": {"sector": "data_centers", "title": title},
                }
                identities = (
                    [
                        (identity.id, f"Customer {position}", "owner")
                        for position, identity in enumerate(conflicted_identities)
                    ]
                    if index == 64
                    else [
                        (owner_identity.id, "Canonical Owner", "owner"),
                        (contractor_identity.id, "Construction Contractor", "contractor"),
                    ]
                )
                for identity_id, organization_name, role in identities:
                    session.add(
                        BrowseCustomerMembership(
                            generation_id=generation.id,
                            company_identity_id=identity_id,
                            project_id=row.project_id,
                            organization_name=organization_name,
                            role=role,
                        )
                    )
                continue
            operator_number = "12345" if index < 63 else "54321"
            row.compact = {
                **row.compact,
                "project_metadata": {
                    "sector": "oil_gas",
                    "title": f"Lease {index}",
                    "operator": "Same Display Name",
                    "oil_gas": {"operator_number": operator_number},
                    "asset_identity": {
                        "kind": "us_well_api",
                        "value": f"421650{index:04d}",
                        "identity_validated": True,
                    },
                },
                **(
                    {
                        "contact_actions": [
                            {
                                "kind": "email",
                                "href": "mailto:business@example.invalid",
                                "company_identity_id": str(contractor_identity.id),
                                "person_identity_id": str(uuid4()),
                                "claim_id": "private-claim",
                            }
                        ]
                    }
                    if index == 0
                    else {}
                ),
            }
            if index == 0:
                # This asset has a canonical identity membership, while the
                # other 61 assets with RRC 12345 do not. The official RRC
                # identifier should still place all 62 under one operator.
                session.add(
                    BrowseCustomerMembership(
                        generation_id=generation.id,
                        company_identity_id=owner_identity.id,
                        project_id=row.project_id,
                        organization_name="Different Canonical Operator Label",
                        role="asset_operator",
                    )
                )
            if index == 62:
                for position, identity in enumerate(conflicted_identities):
                    session.add(
                        BrowseCustomerMembership(
                            generation_id=generation.id,
                            company_identity_id=identity.id,
                            project_id=row.project_id,
                            organization_name=f"Conflicted Operator {position}",
                            role="operator",
                        )
                    )
                session.add(
                    BrowseUnresolvedCustomer(
                        generation_id=generation.id,
                        project_id=row.project_id,
                        organization_name="Conflicted Operator",
                        role="conflicting_customer",
                        reason="Multiple current canonical company identities require review.",
                    )
                )
    return generation.id


def test_groups_aggregate_over_full_cohort_and_scope_children(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        first = groups(session, sector="all", limit=1)
        assert first["total"] == 5
        assert first["items"][0]["project_count"] <= 66
        outer_page = groups(session, sector="all", limit=1, offset=1, token=first["cohort_token"])
        assert len(outer_page["items"]) == 1
        datacenter = groups(session, sector="data_centers")
        assert datacenter["total"] == 2
        assert {item["role"] for item in datacenter["items"]} == {"unresolved", "customer"}
        owner_group = next(item for item in datacenter["items"] if item["role"] == "customer")
        assert owner_group["name"] == "Canonical Owner"
        searched_owner = groups(session, search="Canonical Owner", sector="data_centers")
        assert searched_owner["total"] == 1
        owner_projects = group_projects(
            session,
            owner_group["id"],
            search="Canonical Owner",
            sector="data_centers",
            parent_token=searched_owner["cohort_token"],
        )
        assert owner_projects["total"] == 1
        assert len(owner_projects["items"]) == 1
        operators = groups(session, sector="oil_gas", limit=10)
        assert operators["total"] == 3
        assert {item["project_count"] for item in operators["items"]} == {1, 62}
        large_group = next(item for item in operators["items"] if item["project_count"] == 62)
        conflicted = next(item for item in operators["items"] if item["role"] == "unresolved")
        assert conflicted["project_count"] == 1
        assert conflicted["name"] == "Lease 62"
        children = group_projects(
            session,
            large_group["id"],
            sector="oil_gas",
            limit=25,
            parent_token=operators["cohort_token"],
        )
        assert children["total"] == 62
        assert len(children["items"]) == 25
        assert "company_identity_id" not in repr(children["items"])
        next_page = group_projects(
            session,
            large_group["id"],
            sector="oil_gas",
            limit=25,
            offset=25,
            parent_token=operators["cohort_token"],
            token=children["cohort_token"],
        )
        assert len(next_page["items"]) == 25
        assert next_page["cohort_token"] == children["cohort_token"]
        with pytest.raises(HTTPException) as mismatch:
            group_projects(
                session,
                large_group["id"],
                sector="oil_gas",
                limit=25,
                parent_token="stale-parent-cohort",
            )
        assert mismatch.value.status_code == 409


def test_customer_search_and_generation_drift_fence(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        searched = groups(session, search="Synthetic 7", sector="oil_gas")
        assert searched["total"] == 1
        old_token = searched["cohort_token"]
    rebuild(saved_db)
    with saved_db() as session:
        with pytest.raises(HTTPException) as changed:
            groups(session, search="Synthetic 7", sector="oil_gas", token=old_token, offset=1)
        assert changed.value.status_code == 409
