from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from gridlens.intelligence.customer_results import group_metadata, group_projects, groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    CompanyIdentity,
    Project,
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
            select(BrowseRow)
            .join(Project, BrowseRow.project_id == Project.id)
            .where(BrowseRow.generation_id == generation.id)
            # Heap/scan order is not deterministic (parallel scans, updated
            # tuple versions, analyze timing): the positional cohort layout
            # below requires numeric project creation order (external_id).
            .order_by(func.length(Project.external_id), Project.external_id)
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


def _seed_tdlr_name_bucket(factory):
    from test_saved_browse import seed

    seed(factory, count=9, histories=1)
    identities = [CompanyIdentity(id=uuid4()) for _ in range(10)]
    with factory.begin() as session:
        session.add_all(identities)
    assert rebuild(factory)["status"] == "published"

    exact_name = "AMAZON DATA SERVICES, INC"
    cases = [
        (exact_name, "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-a"]),
        (exact_name, "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-b"]),
        (exact_name, "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-c"]),
        ("AMAZON DATA SERVICES, INC.", "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-d"]),
        ("Amazon Data Services, INC", "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-e"]),
        (exact_name, "owner_developer", "other-source", ["ev-f"]),
        (exact_name, "owner_developer", "texas-tdlr-tabs-data-centers", []),
        (exact_name, "owner", "texas-tdlr-tabs-data-centers", ["ev-h"]),
        (exact_name, "owner_developer", "texas-tdlr-tabs-data-centers", ["ev-i"]),
    ]
    with factory.begin() as session:
        generation = current_generation(session)
        projects = session.scalars(
            select(Project).order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        assert len(projects) == len(cases)
        for index, (project, case) in enumerate(zip(projects, cases, strict=True)):
            name, role, source, evidence_refs = case
            rows = session.scalars(
                select(BrowseRow).where(
                    BrowseRow.generation_id == generation.id,
                    BrowseRow.project_id == project.id,
                )
            ).all()
            for row in rows:
                row.compact = {
                    **row.compact,
                    "contact_actions": [
                        {
                            "kind": "email",
                            "href": f"mailto:customer-{index}@example.invalid",
                            "company": name,
                            "company_identity_id": str(identities[index].id),
                        }
                    ],
                    "project_metadata": {
                        "sector": "data_centers",
                        "title": f"PECOS facility {index}",
                        "data_center": {"owner_developer": name},
                        "event": {
                            "source": source,
                            "evidence_refs": evidence_refs,
                            "kind": "permit_issued",
                        },
                    },
                }
            attached_ids = [identities[index].id]
            if index == 8:
                attached_ids.append(identities[9].id)
            for identity_id in attached_ids:
                session.add(
                    BrowseCustomerMembership(
                        generation_id=generation.id,
                        company_identity_id=identity_id,
                        project_id=project.id,
                        organization_name=name,
                        role=role,
                    )
                )
    return {identity.id for identity in identities[:3]}, exact_name


def test_groups_aggregate_over_full_cohort_and_scope_children(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        generation = current_generation(session)
        first = groups(session, sector="all", limit=1)
        assert first["generation_id"] == str(generation.id)
        assert first["as_of"] == generation.built_at.isoformat()
        assert first["valid_until"] == generation.valid_until.isoformat()
        assert first["qualification_state"] == "current"
        assert first["refresh_state"] == "current"
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
        assert owner_projects["generation_id"] == str(generation.id)
        assert owner_projects["as_of"] == generation.built_at.isoformat()
        assert owner_projects["refresh_state"] == "current"
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


def test_customer_filter_and_search_keep_all_related_sector_projects(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.scalars(
            select(BrowseRow)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(BrowseRow.project_id)
        ).all()
        operator_rows = [
            row
            for row in rows
            if (
                row.compact.get("project_metadata", {}).get("oil_gas", {}).get("operator_number")
                == "12345"
            )
        ]
        assert len(operator_rows) == 63
        # All 63 are separate projects; the conflicting row stays outside the
        # resolved 62-project operator group asserted below.
        assert len({row.project_id for row in operator_rows}) == 63
        for index, row in enumerate(operator_rows):
            row.compact = {
                **row.compact,
                "location": "Texas" if index == 0 else "Oklahoma",
                "project_metadata": {
                    **row.compact["project_metadata"],
                    "event": {"kind": "permit_issued" if index == 0 else "well_permitted"},
                },
            }

    with saved_db() as session:
        searched = groups(session, search="Synthetic 7", sector="oil_gas", limit=10)
        assert searched["total"] == 1
        selected = searched["items"][0]
        assert selected["project_count"] == 62
        complete = group_projects(
            session,
            selected["id"],
            search="Synthetic 7",
            sector="oil_gas",
            parent_token=searched["cohort_token"],
            limit=50,
        )
        assert complete["total"] == 62

        by_region = groups(session, sector="oil_gas", region="Texas", limit=10)
        assert by_region["total"] == 1
        assert by_region["items"][0]["project_count"] == 62
        regional_children = group_projects(
            session,
            by_region["items"][0]["id"],
            sector="oil_gas",
            region="Texas",
            parent_token=by_region["cohort_token"],
            limit=50,
        )
        assert regional_children["total"] == 62

        by_stage = groups(session, sector="oil_gas", stage="permit_issued", limit=10)
        assert by_stage["total"] == 1
        assert by_stage["items"][0]["project_count"] == 62
        # Facets cover the entire sector, including the separate operator,
        # rather than only the selected customer or stage-filtered page.
        assert by_stage["facets"]["regions"] == ["Albuquerque, NM", "Oklahoma", "Texas"]
        assert by_stage["facets"]["stages"] == ["permit_issued", "well_permitted"]
        with pytest.raises(HTTPException) as mismatched_child:
            group_projects(
                session,
                selected["id"],
                search="Synthetic 7",
                sector="oil_gas",
                region="Texas",
                parent_token=searched["cohort_token"],
            )
        assert mismatched_child.value.status_code == 409


def test_tdlr_same_name_container_preserves_distinct_company_identities(saved_db, monkeypatch):
    identity_ids, exact_name = _seed_tdlr_name_bucket(saved_db)
    # This test measures container identity/contact isolation. Project contact
    # privacy filtering is exercised by the dedicated suppression tests.
    from gridlens.intelligence import project_contact_actions

    monkeypatch.setattr(
        project_contact_actions,
        "filter_project_contact_records",
        lambda _session, records: records,
    )
    with saved_db() as session:
        parent = groups(session, sector="data_centers", limit=20)
        same_name = [
            group for group in parent["items"] if group["group_kind"] == "same_name_unconfirmed"
        ]
        assert len(same_name) == 1
        container = same_name[0]
        assert container["name"] == exact_name
        assert container["role"] == "unresolved"
        assert container["identity_count"] == 3
        assert container["project_count"] == 3

        metadata = group_metadata(
            session,
            container["id"],
            sector="data_centers",
        )
        assert metadata["group_kind"] == "same_name_unconfirmed"
        assert metadata["identity_count"] == 3

        children = group_projects(
            session,
            container["id"],
            sector="data_centers",
            parent_token=parent["cohort_token"],
            limit=10,
        )
        assert children["total"] == 3
        assert {item["customer_identity_id"] for item in children["items"]} == {
            str(value) for value in identity_ids
        }
        assert len({item["customer_identity_id"] for item in children["items"]}) == 3
        assert len({item["project_id"] for item in children["items"]}) == 3
        assert all(len(item["contact"]) == 1 for item in children["items"])
        assert {item["contact"][0]["href"] for item in children["items"]} == {
            f"mailto:customer-{index}@example.invalid" for index in range(3)
        }

        # Exact-case and punctuation variants, wrong namespaces, empty evidence,
        # non-owner roles, and project-level identity conflicts remain outside
        # the presentation bucket.
        outside_bucket = [group for group in parent["items"] if group["id"] != container["id"]]
        assert len(outside_bucket) == 6
        assert all(group["group_kind"] != "same_name_unconfirmed" for group in outside_bucket)


@pytest.mark.parametrize("sort", ["priority_asc", "company", "updated"])
def test_customer_sort_is_global_and_deterministic(saved_db, sort):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        full = groups(session, sector="all", sort=sort, limit=50)
        first = groups(session, sector="all", sort=sort, limit=1)
        second = groups(
            session,
            sector="all",
            sort=sort,
            limit=50,
            offset=1,
            token=first["cohort_token"],
        )
        assert [item["id"] for item in first["items"] + second["items"]] == [
            item["id"] for item in full["items"]
        ]
