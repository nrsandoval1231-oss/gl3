"""Source-backed sector-aware customer primary role selection."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from test_customer_account_scenarios import _historical_retraction, _owner_claim, _project

from gridlens.intelligence.customer_accounts import (
    CUSTOMER_ROLES,
    _current_customer_claims,
    associated_accounts_for_projects,
)
from gridlens.intelligence.customer_primary import select_primary_roles
from gridlens.intelligence.customer_results import groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.commercial_pursuit_models import CommercialPursuit
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    BuyingChainClaim,
    BuyingChainCorrection,
    CompanyIdentity,
    CompanyProjectMembership,
    Interpretation,
)

pytest_plugins = ["test_customer_account_scenarios"]


def _claim(role, organization):
    return SimpleNamespace(category=role, organization=organization)


def test_primary_selector_uses_sector_precedence_and_keeps_conflicts_blocked():
    project = uuid4()
    operator_a, owner_b, contractor_c = uuid4(), uuid4(), uuid4()
    rows = [
        (operator_a, project, _claim("asset_operator", "Operator A")),
        (owner_b, project, _claim("owner_developer", "Owner B")),
        (contractor_c, project, _claim("contractor", "EPC C")),
    ]
    assert CUSTOMER_ROLES == {
        "owner_developer",
        "owner_construction",
        "owner_energy",
        "asset_operator",
    }
    oil_gas = select_primary_roles(rows, {project: "oil_gas"})[project]
    assert (oil_gas.status, oil_gas.company_identity_id, oil_gas.role) == (
        "selected",
        operator_a,
        "asset_operator",
    )
    data_center = select_primary_roles(rows, {project: "data_centers"})[project]
    assert (data_center.status, data_center.company_identity_id, data_center.role) == (
        "selected",
        owner_b,
        "owner_developer",
    )
    unknown = select_primary_roles(rows, {project: "unknown"})[project]
    assert unknown.status == "conflict"
    same_class_conflict = select_primary_roles(
        [
            (operator_a, project, _claim("asset_operator", "Operator A")),
            (owner_b, project, _claim("asset_operator", "Operator B")),
        ],
        {project: "oil_gas"},
    )[project]
    assert same_class_conflict.status == "conflict"
    dc_owner_conflict = select_primary_roles(
        [
            (operator_a, project, _claim("owner_developer", "Owner A")),
            (owner_b, project, _claim("owner_energy", "Owner B")),
            (contractor_c, project, _claim("asset_operator", "Operator C")),
        ],
        {project: "data_centers"},
    )[project]
    assert dc_owner_conflict.status == "conflict"
    same_identity = select_primary_roles(
        [
            (owner_b, project, _claim("owner_developer", "Owner B")),
            (owner_b, project, _claim("asset_operator", "Operator B")),
        ],
        {project: "oil_gas"},
    )[project]
    assert same_identity.status == "selected" and same_identity.company_identity_id == owner_b
    withdrawn = select_primary_roles(rows, {project: "oil_gas"}, {project})[project]
    assert withdrawn.status == "conflict" and withdrawn.company_identity_id is None


def test_associated_account_projection_remains_available_before_first_generation(scenario_db):
    with scenario_db.begin() as session:
        project, _need, _observation, _evidence, operator = _project(
            session, "no-generation-account", operator_number="910100"
        )
    with scenario_db() as session:
        account = associated_accounts_for_projects(session, {project.id})[project.id]
        assert account["company_identity_id"] == operator.id


def test_oil_gas_operator_remains_primary_over_owner_and_contractor(scenario_db):
    with scenario_db.begin() as session:
        project, need, observation, evidence, operator = _project(
            session, "primary-operator", operator_number="910101"
        )
        project.name = "Synthetic gas processing plant construction primary-operator"
        project.asset_type = "gas_processing_plant"
        observation.title = evidence.title = project.name
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "subject": project.name,
            "evidence": {"id": str(evidence.id)},
        }
        owner, contractor = CompanyIdentity(), CompanyIdentity()
        session.add_all([owner, contractor])
        session.flush()
        _owner_claim(session, project, owner, "Synthetic Owner B", "primary-operator")
        _owner_claim(
            session,
            project,
            contractor,
            "Synthetic EPC C",
            "primary-operator",
            role="contractor",
        )
        pursuit = CommercialPursuit(need_id=need.id, project_id=project.id, stage="Engaged")
        session.add(pursuit)
        session.flush()
        pursuit_id = pursuit.id

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse_row.compact["project_metadata"]["sector"] == "oil_gas", (
            browse_row.compact["project_metadata"],
            browse_row.compact["asset_type"],
        )
        raw = _current_customer_claims(session, project_ids={project.id}, include_conflicts=True)
        selected = _current_customer_claims(session, project_ids={project.id})
        account = associated_accounts_for_projects(session, {project.id})[project.id]
        assert {claim.category for _identity, _project_id, claim in raw} >= {
            "asset_operator",
            "owner_developer",
        }
        assert (
            session.scalar(
                select(BuyingChainClaim.id).where(
                    BuyingChainClaim.project_id == project.id,
                    BuyingChainClaim.category == "contractor",
                )
            )
            is not None
        )
        assert len(selected) == 1 and selected[0][0] == operator.id
        assert account["company_identity_id"] == operator.id
        memberships = session.scalars(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        ).all()
        assert [(row.company_identity_id, row.role) for row in memberships] == [
            (operator.id, "asset_operator")
        ]
        assert not session.scalar(
            select(BrowseUnresolvedCustomer.project_id).where(
                BrowseUnresolvedCustomer.generation_id == generation.id,
                BrowseUnresolvedCustomer.project_id == project.id,
                BrowseUnresolvedCustomer.role == "conflicting_customer",
            )
        )
        assert session.get(CommercialPursuit, pursuit_id).stage == "Engaged"
        group_page = groups(session, sector="oil_gas", selected_generation=generation)
        assert group_page["total"] == 1
        assert group_page["items"][0]["project_count"] == 1
        assert group_page["items"][0]["group_kind"] == "resolved_identity"
        assert group_page["items"][0]["name"] == "Synthetic Operator primary-operator"


def test_retracted_oil_gas_operator_cannot_fall_back_to_owner_or_change_pursuit(scenario_db):
    with scenario_db.begin() as session:
        project, need, observation, evidence, _operator = _project(
            session, "withdrawn-primary", operator_number="910102"
        )
        project.name = "Synthetic gas processing plant construction withdrawn-primary"
        project.asset_type = "gas_processing_plant"
        observation.title = evidence.title = project.name
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "subject": project.name,
            "evidence": {"id": str(evidence.id)},
        }
        owner = CompanyIdentity()
        session.add(owner)
        session.flush()
        _owner_claim(session, project, owner, "Synthetic Owner B", "withdrawn-primary")
        membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.state == "current",
            )
        )
        _historical_retraction(
            session,
            membership,
            idempotency_key="primary-role-retraction",
            reason="Synthetic explicit operator withdrawal",
        )
        pursuit = CommercialPursuit(need_id=need.id, project_id=project.id, stage="Proposal")
        session.add(pursuit)
        session.flush()
        pursuit_id = pursuit.id

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse_row.compact["project_metadata"]["sector"] == "oil_gas"
        assert associated_accounts_for_projects(session, {project.id})[project.id] is None
        assert not session.scalar(
            select(BrowseCustomerMembership.project_id).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        )
        unresolved = session.scalar(
            select(BrowseUnresolvedCustomer).where(
                BrowseUnresolvedCustomer.generation_id == generation.id,
                BrowseUnresolvedCustomer.project_id == project.id,
                BrowseUnresolvedCustomer.role == "conflicting_customer",
            )
        )
        assert unresolved is not None
        assert session.get(CommercialPursuit, pursuit_id).stage == "Proposal"


def test_data_center_owner_primary_over_operator_and_tenant_in_real_rebuild(scenario_db):
    with scenario_db.begin() as session:
        project, _need, _observation, _evidence, operator = _project(
            session, "primary-data-center", operator_number="910103"
        )
        project.name = "Synthetic Data Center campus primary-data-center"
        project.asset_type = "data_center"
        owner, tenant = CompanyIdentity(), CompanyIdentity()
        session.add_all([owner, tenant])
        session.flush()
        _owner_claim(session, project, owner, "Synthetic DC Owner A", "primary-data-center")
        _owner_claim(
            session,
            project,
            tenant,
            "Synthetic DC Tenant C",
            "primary-data-center",
            role="tenant",
        )
        operator_membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.state == "current",
            )
        )
        _historical_retraction(
            session,
            operator_membership,
            idempotency_key="dc-secondary-operator-retraction",
            reason="Synthetic explicit operator withdrawal; DC owner remains supported.",
        )

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse_row.compact["project_metadata"]["sector"] == "data_centers"
        raw = _current_customer_claims(session, project_ids={project.id}, include_conflicts=True)
        assert {claim.category for _identity, _pid, claim in raw} >= {
            "owner_developer",
        }
        assert (
            session.scalar(
                select(BuyingChainClaim.id).where(
                    BuyingChainClaim.project_id == project.id,
                    BuyingChainClaim.category == "tenant",
                )
            )
            is not None
        )
        memberships = session.scalars(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        ).all()
        assert [(row.company_identity_id, row.role) for row in memberships] == [
            (owner.id, "owner_developer")
        ]
        assert (
            associated_accounts_for_projects(session, {project.id})[project.id][
                "company_identity_id"
            ]
            == owner.id
        )
        assert operator.id != owner.id
        assert not session.scalar(
            select(BrowseUnresolvedCustomer.project_id).where(
                BrowseUnresolvedCustomer.generation_id == generation.id,
                BrowseUnresolvedCustomer.project_id == project.id,
                BrowseUnresolvedCustomer.role == "conflicting_customer",
            )
        )


def test_retracted_data_center_owner_blocks_operator_fallback_and_preserves_pursuit(
    scenario_db,
):
    with scenario_db.begin() as session:
        project, need, _observation, _evidence, operator = _project(
            session, "withdrawn-dc-owner", operator_number="910104"
        )
        project.name = "Synthetic Data Center campus withdrawn-dc-owner"
        project.asset_type = "data_center"
        owner = CompanyIdentity()
        session.add(owner)
        session.flush()
        _owner_claim(session, project, owner, "Synthetic Withdrawn DC Owner", "withdrawn-dc-owner")
        claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.category == "owner_developer",
            )
        )
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                idempotency_key="withdraw-dc-owner",
                action="retract",
                values={},
                reason="Synthetic explicit owner withdrawal.",
                actor="test",
            )
        )
        pursuit = CommercialPursuit(need_id=need.id, project_id=project.id, stage="Proposal")
        session.add(pursuit)
        session.flush()
        pursuit_id = pursuit.id

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse_row.compact["project_metadata"]["sector"] == "data_centers"
        assert operator.id != owner.id
        assert associated_accounts_for_projects(session, {project.id})[project.id] is None
        assert not session.scalar(
            select(BrowseCustomerMembership.project_id).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        )
        unresolved = session.scalar(
            select(BrowseUnresolvedCustomer).where(
                BrowseUnresolvedCustomer.generation_id == generation.id,
                BrowseUnresolvedCustomer.project_id == project.id,
                BrowseUnresolvedCustomer.role == "conflicting_customer",
            )
        )
        assert unresolved is not None
        assert session.get(CommercialPursuit, pursuit_id).stage == "Proposal"
