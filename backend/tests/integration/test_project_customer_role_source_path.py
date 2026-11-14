"""Source-linked project-customer claims reach saved account generations."""

from sqlalchemy import select
from test_customer_account_scenarios import _owner_claim, _project

from gridlens.intelligence.customer_accounts import (
    _current_customer_claims,
    associated_accounts_for_projects,
)
from gridlens.intelligence.customer_results import groups
from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BrowseUnresolvedCustomer,
    BuyingChainCorrection,
    CompanyIdentity,
    Interpretation,
)

pytest_plugins = ["test_customer_account_scenarios"]


def _data_center(project, observation, evidence, slug):
    project.name = f"Synthetic Data Center facility {slug}"
    project.asset_type = "data_center"
    observation.title = evidence.title = project.name


def test_linked_project_customer_claim_flows_into_saved_primary_customer_group(scenario_db):
    with scenario_db.begin() as session:
        project, _need, observation, evidence, operator = _project(
            session, "project-customer-current", operator_number="930101"
        )
        _data_center(project, observation, evidence, "project-customer-current")
        customer = CompanyIdentity()
        session.add(customer)
        session.flush()
        claim = _owner_claim(
            session,
            project,
            customer,
            "Synthetic Explicit Project Customer",
            "project-customer-current",
            role="project_customer",
        )
        claim_id = claim.id

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse.compact["project_metadata"]["sector"] == "data_centers"
        raw = _current_customer_claims(session, project_ids={project.id}, include_conflicts=True)
        assert any(
            claim.id == claim_id and claim.category == "project_customer"
            for _identity, _project_id, claim in raw
        )
        selected = _current_customer_claims(session, project_ids={project.id})
        assert [(identity, claim.category) for identity, _project_id, claim in selected] == [
            (customer.id, "project_customer")
        ]
        account = associated_accounts_for_projects(session, {project.id})[project.id]
        assert account["company_identity_id"] == customer.id
        assert account["role"] == "project_customer"
        memberships = session.scalars(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        ).all()
        assert [(row.company_identity_id, row.role) for row in memberships] == [
            (customer.id, "project_customer")
        ]
        assert operator.id != customer.id
        page = groups(session, sector="data_centers", selected_generation=generation)
        assert page["total"] == 1
        assert page["items"][0]["name"] == "Synthetic Explicit Project Customer"
        assert page["items"][0]["group_kind"] == "resolved_identity"


def test_retracted_data_center_project_customer_blocks_operator_fallback(scenario_db):
    with scenario_db.begin() as session:
        project, _need, observation, evidence, operator = _project(
            session, "project-customer-retracted", operator_number="930102"
        )
        _data_center(project, observation, evidence, "project-customer-retracted")
        customer = CompanyIdentity()
        session.add(customer)
        session.flush()
        claim = _owner_claim(
            session,
            project,
            customer,
            "Synthetic Retracted Project Customer",
            "project-customer-retracted",
            role="project_customer",
        )
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=claim.id,
                expected_version=claim.fingerprint,
                idempotency_key="retract-project-customer-dc",
                action="retract",
                values={},
                reason="Synthetic explicit project-customer retraction.",
                actor="test",
            )
        )

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        assert associated_accounts_for_projects(session, {project.id})[project.id] is None
        assert not session.scalar(
            select(BrowseCustomerMembership.project_id).where(
                BrowseCustomerMembership.generation_id == generation.id,
                BrowseCustomerMembership.project_id == project.id,
            )
        )
        conflict = session.scalar(
            select(BrowseUnresolvedCustomer).where(
                BrowseUnresolvedCustomer.generation_id == generation.id,
                BrowseUnresolvedCustomer.project_id == project.id,
                BrowseUnresolvedCustomer.role == "conflicting_customer",
            )
        )
        assert conflict is not None
        assert operator.id != customer.id


def test_retracted_project_customer_does_not_block_oil_gas_owner_fallback(scenario_db):
    with scenario_db.begin() as session:
        project, _need, observation, evidence, _operator = _project(
            session,
            "pc-oil",
            include_operator=False,
            operator_number="",
        )
        project.name = "Synthetic gas processing plant construction pc-oil"
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
        owner, customer = CompanyIdentity(), CompanyIdentity()
        session.add_all([owner, customer])
        session.flush()
        _owner_claim(
            session,
            project,
            owner,
            "Synthetic Oil Owner",
            "pc-oil",
            role="owner_developer",
        )
        customer_claim = _owner_claim(
            session,
            project,
            customer,
            "Unsupported Oil Project Customer",
            "pc-oil",
            role="project_customer",
        )
        session.add(
            BuyingChainCorrection(
                project_id=project.id,
                claim_id=customer_claim.id,
                expected_version=customer_claim.fingerprint,
                idempotency_key="retract-pc-oil",
                action="retract",
                values={},
                reason="Synthetic unsupported project-customer retraction.",
                actor="test",
            )
        )

    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        generation = current_generation(session)
        browse = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.project_id == project.id,
            )
        )
        assert browse.compact["project_metadata"]["sector"] == "oil_gas"
        account = associated_accounts_for_projects(session, {project.id})[project.id]
        assert account["company_identity_id"] == owner.id
        assert account["role"] == "owner_developer"
