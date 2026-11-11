"""Batch account labels using the exact customer-results grouping assignment."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text


def account_identity_for_projects(session, project_ids: set[UUID]) -> dict[UUID, dict[str, str]]:
    """Return current resolved account ids/names for requested project ids.

    This deliberately reuses customer_results' assignment CTE, so pursuit account
    identifiers follow the same RRC, membership, conflict, and same-name rules.
    """
    if not project_ids:
        return {}
    from gridlens.intelligence.customer_results import _group_id
    from gridlens.intelligence.saved_browse import current_generation

    generation = current_generation(session, route="account_identity")
    ctes, params = _assignment_context(session, generation)
    rows = session.execute(
        text(
            ctes
            + " SELECT DISTINCT ar.project_id, g.group_key, g.name FROM assigned a "
            + "JOIN all_rows ar ON ar.asset_key = a.asset_key "
            + "JOIN grouped g USING (group_key) "
            + "WHERE ar.project_id = ANY(CAST(:project_ids AS uuid[])) "
            + "AND g.group_kind = 'resolved_identity' "
            + "AND g.identity_count = 1"
        ),
        {**params, "project_ids": [str(project_id) for project_id in project_ids]},
    ).mappings()
    result: dict[UUID, dict[str, str]] = {}
    for row in rows:
        result[UUID(str(row["project_id"]))] = {
            "id": _group_id(row["group_key"]),
            "name": row["name"],
        }
    return result


def account_for_company(session, company_id: UUID) -> dict[str, str] | None:
    """Resolve a legacy CompanyIdentity UUID to one current customer group.

    This includes provisional same-name directory buckets when the company
    identity is an explicit member, but returns no result if it maps to more
    than one group or is absent from the current projection.
    """
    from gridlens.intelligence.customer_results import _group_id
    from gridlens.intelligence.saved_browse import current_generation
    from gridlens.persistence.models import CompanyIdentity

    company = session.get(CompanyIdentity, company_id)
    if company is None:
        return None
    generation = current_generation(session, route="account_identity")
    ctes, params = _assignment_context(session, generation)
    rows = (
        session.execute(
            text(
                ctes
                + " SELECT DISTINCT g.group_key, g.name, g.group_kind FROM assigned a "
                + "JOIN grouped g USING (group_key) "
                + "WHERE a.company_id = :company_id "
                + "OR (CAST(:operator_number AS text) IS NOT NULL "
                + "AND g.group_key = 'rrc:' || CAST(:operator_number AS text))"
            ),
            {
                **params,
                "company_id": str(company_id),
                "operator_number": company.rrc_operator_number,
            },
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    return {
        "id": _group_id(row["group_key"]),
        "name": row["name"],
        "group_kind": row["group_kind"],
    }


def _assignment_context(session, generation):
    from gridlens.intelligence.customer_results import _ctes, _query_parts, assignment_context

    where, params = _query_parts(generation, "", "all")
    context = assignment_context(session, generation, shortlist=False)
    params.update(
        {
            "eligible_need_ids": context["eligible_need_ids"],
            "priority_map": context["priority_map"],
            "shortlist_enabled": context["shortlist_enabled"],
            "pursued_need_ids": context["pursued_need_ids"],
            "need_alias_map": context["need_alias_map"],
            **context["asset_params"],
        }
    )
    return _ctes(where, context["data"]), params


def account_for_project(session, project_id: UUID) -> dict[str, str] | None:
    """Resolve one retained project through the same primary browse assignment."""
    from gridlens.intelligence.customer_results import _group_id
    from gridlens.intelligence.saved_browse import current_generation

    generation = current_generation(session, route="account_identity")
    ctes, params = _assignment_context(session, generation)
    rows = (
        session.execute(
            text(
                ctes + " SELECT DISTINCT g.group_key, g.name, g.group_kind, a.anchor_project_id "
                "FROM assigned a "
                "JOIN all_rows ar ON ar.asset_key=a.asset_key "
                "JOIN grouped g USING (group_key) WHERE ar.project_id=:project_id"
            ),
            {**params, "project_id": project_id},
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    return {
        "id": _group_id(row["group_key"]),
        "name": row["name"],
        "group_kind": row["group_kind"],
        "project_id": row["anchor_project_id"],
    }
