import hashlib
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from gridlens.intelligence.customer_results import (
    group_metadata,
    group_open,
    group_projects,
    groups,
)
from gridlens.intelligence.project_results import page as project_page
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
                        (owner_identity.id, "Canonical Owner", "owner_developer"),
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
                            },
                            {
                                "kind": "email",
                                "href": "mailto:operator@example.invalid",
                                "company_identity_id": str(owner_identity.id),
                                "person_identity_id": str(uuid4()),
                                "claim_id": "operator-claim",
                            },
                        ],
                        "contact_people": [
                            {
                                "name": "Contractor Contact",
                                "email": "contractor@example.invalid",
                                "company_identity_id": str(contractor_identity.id),
                                "person_identity_id": str(uuid4()),
                            },
                            {
                                "name": "Operator Contact",
                                "email": "operator-person@example.invalid",
                                "company_identity_id": str(owner_identity.id),
                                "person_identity_id": str(uuid4()),
                            },
                        ],
                    }
                    if index == 0
                    else {}
                ),
                **(
                    {
                        "contact_actions": [
                            {
                                "kind": "email",
                                "href": "mailto:rrc-only@example.invalid",
                                "company_identity_id": str(owner_identity.id),
                            }
                        ]
                    }
                    if index == 1
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
                            role="asset_operator",
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
        assert selected["matched_project_id"] is not None
        assert selected["matched_need_id"] is not None
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


def test_account_contacts_are_scoped_to_selected_primary_identity(saved_db, monkeypatch):
    _seed_group_cohort(saved_db)
    from gridlens.intelligence import project_contact_actions

    monkeypatch.setattr(
        project_contact_actions,
        "filter_project_contact_records",
        lambda _session, records: records,
    )
    with saved_db() as session:
        generation = current_generation(session)
        contact_row = session.execute(
            select(BrowseRow.project_id)
            .where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.compact.contains(
                    {"contact_actions": [{"href": "mailto:business@example.invalid"}]}
                ),
            )
            .limit(1)
        ).scalar_one()
        account_page = groups(
            session, search="Different Canonical Operator Label", sector="oil_gas"
        )
        assert account_page["total"] == 1
        opened = group_open(
            session,
            account_page["items"][0]["id"],
            search="Different Canonical Operator Label",
            sector="oil_gas",
            limit=100,
        )
        account_project = next(
            item for item in opened["projects"]["items"] if str(contact_row) in item["project_ids"]
        )
        account_actions = [
            action for need in account_project["needs"] for action in need["contact_actions"]
        ]
        account_people = [
            person for need in account_project["needs"] for person in need["contact_people"]
        ]
        assert {action["href"] for action in account_project["contact"]} <= {
            "mailto:operator@example.invalid"
        }
        assert {action["href"] for action in account_actions} == {"mailto:operator@example.invalid"}
        assert {person["email"] for person in account_people} == {"operator-person@example.invalid"}

        generic_project = project_page(
            session,
            sector="oil_gas",
            project_ids=[contact_row],
            limit=10,
            selected_generation=generation,
        )
        generic_item = next(
            item for item in generic_project["items"] if str(contact_row) in item["project_ids"]
        )
        generic_actions = [
            action for need in generic_item["needs"] for action in need["contact_actions"]
        ]
        generic_people = [
            person for need in generic_item["needs"] for person in need["contact_people"]
        ]
        assert {action["href"] for action in generic_actions} == {
            "mailto:business@example.invalid",
            "mailto:operator@example.invalid",
        }
        assert {person["email"] for person in generic_people} == {
            "contractor@example.invalid",
            "operator-person@example.invalid",
        }

        rrc_only_row = session.execute(
            select(BrowseRow.project_id).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.compact.contains(
                    {"contact_actions": [{"href": "mailto:rrc-only@example.invalid"}]}
                ),
            )
        ).scalar_one()
        rrc_group = groups(session, search="12345", sector="oil_gas")
        operator_group = next(item for item in rrc_group["items"] if item["project_count"] == 62)
        rrc_open = group_open(
            session,
            operator_group["id"],
            search="12345",
            sector="oil_gas",
            limit=100,
        )
        rrc_project = next(
            item
            for item in rrc_open["projects"]["items"]
            if str(rrc_only_row) in item["project_ids"]
        )
        assert rrc_project["contact"] == []
        assert all(not need["contact_actions"] for need in rrc_project["needs"])


def test_tdlr_bucket_excludes_entire_identity_with_ineligible_sibling(saved_db):
    identity_ids, exact_name = _seed_tdlr_name_bucket(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        project = session.scalar(select(Project).where(Project.external_id == "3"))
        eligible_project = session.scalar(select(Project).where(Project.external_id == "0"))
        excluded_identity = session.scalar(
            select(BrowseCustomerMembership.company_identity_id).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == eligible_project.id,
            )
        )
        assert excluded_identity in identity_ids
        rows = session.scalars(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        ).all()
        for row in rows:
            metadata = dict(row.compact["project_metadata"])
            metadata["data_center"] = {"owner_developer": "Different exact name"}
            row.compact = {**row.compact, "project_metadata": metadata}
        session.execute(
            BrowseCustomerMembership.__table__.delete().where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        )
        session.add(
            BrowseCustomerMembership(
                generation_id=generation.id,
                company_identity_id=excluded_identity,
                project_id=project.id,
                organization_name="Different exact name",
                role="owner_developer",
            )
        )

    with saved_db() as session:
        parent = groups(session, sector="data_centers", limit=20)
        buckets = [
            item for item in parent["items"] if item["group_kind"] == "same_name_unconfirmed"
        ]
        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket["name"] == exact_name
        assert bucket["identity_count"] == 2
        assert bucket["project_count"] == 2
        # The UUID with one eligible and one differently named project stays
        # under its canonical company key with both projects intact.
        company = group_metadata(
            session,
            "cg_"
            + hashlib.md5(
                ("company:" + str(excluded_identity)).encode(), usedforsecurity=False
            ).hexdigest(),
            sector="data_centers",
        )
        assert company["group_kind"] == "resolved_identity"
        assert company["project_count"] == 2
        searched = groups(session, search="PECOS facility 3", sector="data_centers")
        assert searched["total"] == 1
        assert searched["items"][0]["id"] == company["id"]
        children = group_projects(
            session,
            company["id"],
            search="PECOS facility 3",
            sector="data_centers",
            parent_token=searched["cohort_token"],
        )
        assert children["total"] == 2
        assert len(children["items"]) == 2
        assert {item["customer_identity_id"] for item in children["items"]} == {
            str(excluded_identity)
        }


@pytest.mark.parametrize("missing_field", ["owner_developer", "source"])
def test_tdlr_bucket_rejects_missing_owner_or_source(saved_db, missing_field):
    _seed_tdlr_name_bucket(saved_db)
    with saved_db.begin() as session:
        generation = current_generation(session)
        project = session.scalar(select(Project).where(Project.external_id == "0"))
        rows = session.scalars(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        ).all()
        for row in rows:
            metadata = dict(row.compact["project_metadata"])
            if missing_field == "owner_developer":
                metadata["data_center"] = {"owner_developer": None}
            else:
                metadata["event"] = {
                    key: value for key, value in metadata["event"].items() if key != "source"
                }
            row.compact = {**row.compact, "project_metadata": metadata}

    with saved_db() as session:
        parent = groups(session, sector="data_centers", limit=20)
        buckets = [
            item for item in parent["items"] if item["group_kind"] == "same_name_unconfirmed"
        ]
        assert len(buckets) == 1
        assert buckets[0]["identity_count"] == 2
        assert buckets[0]["project_count"] == 2


def test_operator_number_search_and_group_count_unit(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        parent = groups(session, search="12345", sector="oil_gas", limit=10)
        assert parent["count_unit"] == "groups"
        assert parent["total"] == 2
        group = next(item for item in parent["items"] if item["project_count"] == 62)
        conflict = next(item for item in parent["items"] if item["project_count"] == 1)
        assert group["project_count"] == 62
        assert conflict["role"] == "unresolved"
        metadata = group_metadata(session, group["id"], search="12345", sector="oil_gas")
        assert metadata["project_count"] == 62
        children = group_projects(
            session,
            group["id"],
            search="12345",
            sector="oil_gas",
            parent_token=parent["cohort_token"],
            limit=100,
        )
        assert children["total"] == 62
        assert len(children["items"]) == 62
        assert len({item["project_id"] for item in children["items"]}) == 62


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


def test_customer_shortlist_is_bound_into_account_cohort(saved_db, monkeypatch):
    """Synthetic projection check: an eligible need qualifies its resolved account."""
    _seed_group_cohort(saved_db)
    from gridlens.intelligence import account_shortlist

    with saved_db() as session:
        generation = current_generation(session)
        source_rows = (
            session.execute(
                select(
                    BrowseRow.need_id, BrowseRow.project_id, BrowseRow.summary, BrowseRow.compact
                )
                .where(BrowseRow.generation_id == generation.id)
                .order_by(BrowseRow.need_id)
            )
            .mappings()
            .all()
        )
    contact_source = next(
        row
        for row in source_rows
        if any(
            action.get("href") == "mailto:operator@example.invalid"
            for action in row["compact"].get("contact_actions", [])
        )
        and row["compact"].get("project_metadata", {}).get("sector") == "oil_gas"
        and row["compact"].get("project_metadata", {}).get("oil_gas", {}).get("operator_number")
        == "12345"
    )
    eligible_candidates = [
        row
        for row in source_rows
        if row["compact"].get("project_metadata", {}).get("sector") == "oil_gas"
        and row["compact"].get("project_metadata", {}).get("oil_gas", {}).get("operator_number")
        == "12345"
    ]
    chosen_rows = [contact_source] + [
        row for row in eligible_candidates if row["need_id"] != contact_source["need_id"]
    ][:1]
    assert len(chosen_rows) == 2
    chosen_ids = {str(row["need_id"]) for row in chosen_rows}
    assessments = {
        str(row["need_id"]): {
            "eligible": str(row["need_id"]) in chosen_ids,
            "priority": (
                99
                if str(row["need_id"]) == str(contact_source["need_id"])
                else 91
                if str(row["need_id"]) in chosen_ids
                else 0
            ),
            "duplicate_key": None,
            "reasons": [],
            "evidence_refs": [],
        }
        for row in source_rows
    }
    monkeypatch.setattr(
        account_shortlist,
        "assess_generation",
        lambda _session, _generation: {
            "rows": source_rows,
            "assessments": assessments,
            "eligible_need_ids": [row["need_id"] for row in chosen_rows],
            "priority_by_need": {
                row["need_id"]: 99 if row["need_id"] == contact_source["need_id"] else 91
                for row in chosen_rows
            },
            "duplicate_project_map": {},
            "jev_map_digest": "synthetic-decision-digest",
        },
    )
    with saved_db() as session:
        ordinary = groups(session, sector="oil_gas")
        shortlisted = groups(session, sector="oil_gas", shortlist=True)
        assert ordinary["cohort_token"] != shortlisted["cohort_token"]
        original_assessor = account_shortlist.assess_generation
        monkeypatch.setattr(
            account_shortlist,
            "assess_generation",
            lambda db, generation: {
                **original_assessor(db, generation),
                "jev_map_digest": "changed-synthetic-decision-map",
            },
        )
        changed_decision = groups(session, sector="oil_gas", shortlist=True)
        assert changed_decision["cohort_token"] != shortlisted["cohort_token"]
        assert shortlisted["total"] > 0
        assert shortlisted["items"]
        assert all(item["group_kind"] == "resolved_identity" for item in shortlisted["items"])
        assert all(item["relevant_project_count"] > 0 for item in shortlisted["items"])
        assert all(item["eligible_need_count"] > 0 for item in shortlisted["items"])
        assert all(item["featured_project"] is not None for item in shortlisted["items"])
        assert all(
            item["total_known_project_count"] >= item["relevant_project_count"]
            for item in shortlisted["items"]
        )
        chosen_group = next(
            item for item in shortlisted["items"] if item["eligible_need_count"] == 2
        )
        from gridlens.persistence.commercial_pursuit_models import CommercialPursuit

        session.add(
            CommercialPursuit(
                need_id=chosen_rows[0]["need_id"], project_id=chosen_rows[0]["project_id"]
            )
        )
        session.flush()
        partly_pursued = groups(session, sector="oil_gas", shortlist=True)
        account = next(item for item in partly_pursued["items"] if item["id"] == chosen_group["id"])
        assert account["pursued_eligible_need_count"] == 1
        session.add(
            CommercialPursuit(
                need_id=chosen_rows[1]["need_id"], project_id=chosen_rows[1]["project_id"]
            )
        )
        session.flush()
        fully_pursued = groups(session, sector="oil_gas", shortlist=True)
        account = next(item for item in fully_pursued["items"] if item["id"] == chosen_group["id"])
        assert account["pursued_eligible_need_count"] == 2
        opened = group_open(session, chosen_group["id"], sector="oil_gas", shortlist=True)
        assert opened["group"]["eligible_need_count"] > 0
        assert opened["group"]["featured_project"] is not None
        featured = opened["group"]["featured_project"]
        assert str(contact_source["project_id"]) in featured["project_ids"], repr(
            (contact_source["project_id"], featured)
        )
        primary_identity_id = session.scalar(
            select(BrowseCustomerMembership.company_identity_id).where(
                BrowseCustomerMembership.generation_id == current_generation(session).id,
                BrowseCustomerMembership.project_id == contact_source["project_id"],
            )
        )
        expected_contact_identity_id = next(
            action["company_identity_id"]
            for action in contact_source["compact"]["contact_actions"]
            if action["href"] == "mailto:operator@example.invalid"
        )
        assert str(primary_identity_id) == expected_contact_identity_id
        featured_actions = [
            action for need in featured["needs"] for action in need["contact_actions"]
        ]
        assert {action["href"] for action in featured_actions} == {
            "mailto:operator@example.invalid"
        }, repr((primary_identity_id, expected_contact_identity_id, featured))
