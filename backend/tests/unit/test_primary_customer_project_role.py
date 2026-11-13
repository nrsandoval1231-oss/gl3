from types import SimpleNamespace
from uuid import uuid4

from gridlens.domain.buying_chain import CATEGORY_PRIORITY, Category
from gridlens.intelligence.customer_primary import CUSTOMER_ROLE_ORDER, select_primary_roles


def _row(company_id, role, name):
    return company_id, PROJECT, SimpleNamespace(category=role, organization=name)


PROJECT = uuid4()


def test_project_customer_is_additive_and_preserves_existing_category_order():
    assert Category.PROJECT_CUSTOMER.value == "project_customer"
    assert CATEGORY_PRIORITY["project_customer"] == len(Category) - 1
    assert CUSTOMER_ROLE_ORDER == {
        "owner_developer": 0,
        "owner_energy": 1,
        "owner_construction": 2,
        "asset_operator": 3,
        "project_customer": 4,
    }


def test_data_center_prefers_owner_then_explicit_project_customer_then_operator():
    owner, customer, operator = uuid4(), uuid4(), uuid4()
    rows = [
        _row(owner, "owner_developer", "Owner"),
        _row(customer, "project_customer", "Project Customer"),
        _row(operator, "asset_operator", "Operator"),
    ]
    selected = select_primary_roles(rows, {PROJECT: "data_centers"})[PROJECT]
    assert (selected.status, selected.company_identity_id, selected.role) == (
        "selected",
        owner,
        "owner_developer",
    )

    rows.remove(_row(owner, "owner_developer", "Owner"))
    selected = select_primary_roles(rows, {PROJECT: "data_centers"})[PROJECT]
    assert (selected.status, selected.company_identity_id, selected.role) == (
        "selected",
        customer,
        "project_customer",
    )

    rows.remove(_row(customer, "project_customer", "Project Customer"))
    selected = select_primary_roles(rows, {PROJECT: "data_centers"})[PROJECT]
    assert (selected.status, selected.company_identity_id, selected.role) == (
        "selected",
        operator,
        "asset_operator",
    )


def test_project_customer_does_not_change_oil_gas_or_unknown_conflict_policy():
    customer, operator, owner = uuid4(), uuid4(), uuid4()
    rows = [
        _row(customer, "project_customer", "Project Customer"),
        _row(owner, "owner_developer", "Owner"),
        _row(operator, "asset_operator", "Operator"),
    ]
    oil_gas = select_primary_roles(rows, {PROJECT: "oil_gas"})[PROJECT]
    assert (oil_gas.status, oil_gas.company_identity_id, oil_gas.role) == (
        "selected",
        operator,
        "asset_operator",
    )
    owner_fallback = select_primary_roles(rows[:2], {PROJECT: "oil_gas"})[PROJECT]
    assert (owner_fallback.status, owner_fallback.company_identity_id) == ("selected", owner)
    # A project-customer assertion alone cannot substitute for the established
    # oil-and-gas operator/owner relationship.
    assert select_primary_roles([rows[0]], {PROJECT: "oil_gas"})[PROJECT].status == "none"

    # Unknown sector retains the conservative rule: recognized roles from
    # different company identities remain a conflict rather than being ranked.
    assert select_primary_roles(rows, {PROJECT: "unknown"})[PROJECT].status == "conflict"
    assert (
        select_primary_roles(
            [
                _row(customer, "project_customer", "Project Customer"),
                _row(customer, "asset_operator", "Operator"),
            ],
            {PROJECT: "unknown"},
        )[PROJECT].company_identity_id
        == customer
    )


def test_blocked_data_center_relationship_prevents_project_customer_and_operator_fallback():
    customer, operator = uuid4(), uuid4()
    selection = select_primary_roles(
        [
            _row(customer, "project_customer", "Project Customer"),
            _row(operator, "asset_operator", "Operator"),
        ],
        {PROJECT: "data_centers"},
        blocked_owner_project_ids={PROJECT},
    )[PROJECT]
    assert selection.status == "conflict"
    assert selection.company_identity_id is None
