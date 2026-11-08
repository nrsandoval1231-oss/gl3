"""Pursuit account labels use the canonical customer-results assignment."""

from uuid import uuid4

from sqlalchemy import func, select
from test_customer_results import _seed_group_cohort

from gridlens.intelligence.account_identity import (
    account_for_company,
    account_for_project,
    account_identity_for_projects,
)
from gridlens.intelligence.customer_results import _group_id, groups
from gridlens.intelligence.saved_browse import current_generation
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    CompanyIdentity,
    Project,
)

pytest_plugins = ["test_saved_browse"]


def test_projection_matches_rrc_group_and_omits_conflicted_group(saved_db):
    _seed_group_cohort(saved_db)
    with saved_db() as session:
        generation = current_generation(session)
        rows = session.execute(
            select(BrowseRow.project_id, Project.external_id)
            .join(Project, Project.id == BrowseRow.project_id)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        # _seed_group_cohort assigns RRC 12345 to positions 0..62 and a
        # conflicting pair of customer identities to position 64.
        rrc_project_id = rows[0].project_id
        no_raw_operator_project_id = rows[1].project_id
        mismatched_operator_project_id = rows[2].project_id
        withdrawn_operator_project_id = rows[3].project_id
        conflict_project_id = rows[64].project_id
        canonical_operator = CompanyIdentity(rrc_operator_number="12345")
        session.add(canonical_operator)
        no_raw = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == no_raw_operator_project_id,
            )
        )
        mismatched = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == mismatched_operator_project_id,
            )
        )
        no_raw_metadata = dict(no_raw.compact["project_metadata"])
        no_raw_oil_gas = dict(no_raw_metadata["oil_gas"])
        no_raw_oil_gas.pop("operator_number")
        no_raw_metadata["oil_gas"] = no_raw_oil_gas
        no_raw.compact = {**no_raw.compact, "project_metadata": no_raw_metadata}
        mismatched_metadata = dict(mismatched.compact["project_metadata"])
        mismatched_oil_gas = dict(mismatched_metadata["oil_gas"])
        mismatched_oil_gas["operator_number"] = "54321"
        mismatched_metadata["oil_gas"] = mismatched_oil_gas
        mismatched.compact = {**mismatched.compact, "project_metadata": mismatched_metadata}
        session.add_all(
            [
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=canonical_operator.id,
                    project_id=no_raw_operator_project_id,
                    organization_name="Canonical RRC Operator",
                    role="asset_operator",
                ),
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=canonical_operator.id,
                    project_id=mismatched_operator_project_id,
                    organization_name="Canonical RRC Operator",
                    role="asset_operator",
                ),
            ]
        )
        session.add(
            BrowseUnresolvedCustomer(
                generation_id=generation.id,
                project_id=withdrawn_operator_project_id,
                organization_name="Withdrawn RRC Operator",
                role="conflicting_customer",
                reason="Synthetic retracted membership remains review-required",
            )
        )
        session.flush()
        actual = account_identity_for_projects(
            session,
            {
                rrc_project_id,
                no_raw_operator_project_id,
                mismatched_operator_project_id,
                withdrawn_operator_project_id,
                conflict_project_id,
            },
        )
        customer_groups = groups(session, selected_generation=generation)["items"]
        rrc_group = next(
            group for group in customer_groups if group["id"] == _group_id("rrc:12345")
        )

        assert actual[rrc_project_id] == {
            "id": rrc_group["id"],
            "name": rrc_group["name"],
        }
        assert account_for_company(session, canonical_operator.id) is None
        assert account_for_company(session, uuid4()) is None
        assert actual[no_raw_operator_project_id]["id"] == _group_id("rrc:12345")
        assert account_for_project(session, no_raw_operator_project_id)["id"] == _group_id(
            "rrc:12345"
        )
        assert actual[no_raw_operator_project_id]["id"] == actual[rrc_project_id]["id"]
        assert mismatched_operator_project_id not in actual
        assert withdrawn_operator_project_id not in actual
        assert conflict_project_id not in actual


def test_supported_operator_aliases_roll_up_three_sites_and_keep_conflicting_operator_separate(
    saved_db,
):
    from test_saved_browse import seed

    from gridlens.intelligence.saved_browse import rebuild

    seed(saved_db, count=16, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        rows = session.execute(
            select(BrowseRow, Project)
            .join(Project, Project.id == BrowseRow.project_id)
            .where(BrowseRow.generation_id == generation.id)
            .order_by(func.length(Project.external_id), Project.external_id)
        ).all()
        alpha = CompanyIdentity(rrc_operator_number="12345")
        beta = CompanyIdentity(rrc_operator_number="54321")
        session.add_all([alpha, beta])
        session.flush()
        alias_names = [
            "Shared Operator",
            "Shared Operator Holdings",
            "Shared Operator LLC",
            "Shared Operating Company",
            "Shared Texas Operations",
        ]
        for index, (row, project) in enumerate(rows):
            is_alpha = index < 12 or index == 15
            operator_number = "12345" if is_alpha else "54321"
            site_index = (index % 3) if is_alpha else (index - 12)
            api_number = f"421650{site_index + (0 if is_alpha else 100):04d}"
            metadata = {
                **row.compact["project_metadata"],
                "sector": "oil_gas",
                "operator": "Shared Operator",
                "oil_gas": {"operator_number": operator_number},
                "asset_identity": {
                    "kind": "us_well_api",
                    "value": api_number,
                    "identity_validated": True,
                },
            }
            row.compact = {**row.compact, "project_metadata": metadata}
            session.add(
                BrowseCustomerMembership(
                    generation_id=generation.id,
                    company_identity_id=alpha.id if is_alpha else beta.id,
                    project_id=project.id,
                    organization_name=(
                        alias_names[index % len(alias_names)] if is_alpha else "Shared Operator"
                    ),
                    role="asset_operator",
                )
            )

        session.flush()
        result = groups(session, selected_generation=generation)
        alpha_group = next(
            (group for group in result["items"] if group["id"] == _group_id("rrc:12345")),
            None,
        )
        assert alpha_group is not None, result["items"]
        beta_group = next(
            group for group in result["items"] if group["id"] == _group_id("rrc:54321")
        )
        assert result["total"] == 2
        assert alpha_group["project_count"] == 3
        assert alpha_group["need_count"] == 13
        assert account_for_company(session, alpha.id) == {
            "id": alpha_group["id"],
            "name": alpha_group["name"],
            "group_kind": "resolved_identity",
        }
        assert account_for_company(session, uuid4()) is None
        assert beta_group["project_count"] == 3
        assert beta_group["need_count"] == 3
        assert alpha_group["id"] != beta_group["id"]
        assert alpha_group["name"] == beta_group["name"] == "Shared Operator"
