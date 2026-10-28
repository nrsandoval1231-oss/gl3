"""Bounded read-only operator/customer group pages over saved browse scalars."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.intelligence.project_results import page as project_page
from gridlens.intelligence.saved_browse import current_generation

_ASSET = """CASE
 WHEN compact #>> '{project_metadata,asset_identity,kind}' = 'us_well_api'
  AND compact #>> '{project_metadata,asset_identity,identity_validated}' = 'true'
  AND compact #>> '{project_metadata,asset_identity,value}' ~ '^[0-9]{10}([0-9]{2}){0,2}$'
 THEN 'api:' || (compact #>> '{project_metadata,asset_identity,value}')
 ELSE 'project:' || project_id::text END"""
_ASSET_B = _ASSET.replace("compact", "b.compact").replace("project_id", "b.project_id")


def _cohort(session, *, search: str | None, sector: str, sort: str, selected_generation=None):
    generation = selected_generation or current_generation(session)
    term = (search or "").strip().casefold()
    payload: list[Any] = [str(generation.id), generation.digest, sector, sort, term, "", True, []]
    token = "p1_" + hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return generation, term, token


def _query_parts(generation, term, sector):
    clauses = ["b.generation_id = :generation"]
    params: dict[str, Any] = {"generation": generation.id, "term": term}
    if term:
        clauses.append(
            "(strpos(b.search_text, :term) > 0 OR "
            "strpos(lower(coalesce(b.compact->>'browse_title','')), :term) > 0 OR "
            "strpos(lower(coalesce(b.compact->>'name','')), :term) > 0 OR "
            "strpos(lower(coalesce(b.compact #>> '{project_metadata,operator}','')), :term) > 0 OR "
            "strpos(lower(coalesce(b.compact #>> "
            "'{project_metadata,oil_gas,operator_number}','')), :term) > 0 OR "
            "EXISTS (SELECT 1 FROM browse_customer_memberships cm "
            "WHERE cm.generation_id=b.generation_id AND cm.project_id=b.project_id "
            "AND lower(cm.role) NOT IN ('contractor','general_contractor','epc','subcontractor') "
            "AND strpos(lower(cm.organization_name), :term) > 0) OR "
            "EXISTS (SELECT 1 FROM browse_unresolved_customers uc "
            "WHERE uc.generation_id=b.generation_id AND uc.project_id=b.project_id "
            "AND strpos(lower(uc.organization_name), :term) > 0))"
        )
    if sector == "oil_gas":
        clauses.append("b.compact #>> '{project_metadata,sector}' = 'oil_gas'")
    elif sector == "data_centers":
        clauses.append("b.compact #>> '{project_metadata,sector}' = 'data_centers'")
    return " AND ".join(clauses), params


def _ctes(where: str) -> str:
    return """
    WITH matched AS (
      SELECT %%ASSET%% AS asset_key, b.project_id, b.need_id, b.compact,
             b.rank_score, b.updated_at
      FROM browse_rows b WHERE %%WHERE%%
    ), candidate_assets AS (
      SELECT asset_key, min(project_id::text) AS anchor_project_id
      FROM matched GROUP BY asset_key
    ), all_rows AS (
      SELECT %%ASSET%% AS asset_key, b.project_id, b.need_id, b.compact,
             b.rank_score, b.updated_at
      FROM browse_rows b JOIN candidate_assets c ON c.asset_key = %%ASSET%%
      WHERE b.generation_id = :generation
    ), assets AS (
      SELECT a.asset_key, c.anchor_project_id,
             count(DISTINCT need_id)::integer AS need_count,
             max(rank_score)::integer AS priority_score, max(updated_at) AS updated_at
      FROM all_rows a JOIN candidate_assets c USING (asset_key)
      GROUP BY a.asset_key, c.anchor_project_id
    ), representatives AS (
      SELECT DISTINCT ON (asset_key) asset_key,
        compact #>> '{project_metadata,oil_gas,operator_number}' AS operator_number,
        compact #>> '{project_metadata,operator}' AS operator_name,
        compact #>> '{project_metadata,title}' AS project_title,
        compact->>'browse_title' AS browse_title,
        compact #>> '{project_metadata,sector}' AS sector
      FROM all_rows ORDER BY asset_key, rank_score DESC, updated_at DESC, need_id
    ), memberships AS (
      SELECT DISTINCT r.asset_key, bcm.company_identity_id::text AS company_id,
             bcm.organization_name, bcm.role
      FROM all_rows r JOIN browse_customer_memberships bcm
        ON bcm.generation_id = :generation AND bcm.project_id = r.project_id
      WHERE lower(bcm.role) NOT IN
        ('contractor', 'general_contractor', 'epc', 'subcontractor')
    ), membership_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) > 1
    ), single_membership AS (
      SELECT asset_key, min(company_id) AS company_id,
             min(organization_name) AS organization_name, min(role) AS role
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) = 1
    ), recorded_conflicts AS (
      SELECT r.asset_key, min(uc.organization_name) AS organization_name
      FROM all_rows r JOIN browse_unresolved_customers uc
        ON uc.generation_id = :generation AND uc.project_id = r.project_id
      WHERE uc.role = 'conflicting_customer'
      GROUP BY r.asset_key
    ), unresolved_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM (
        SELECT asset_key, organization_name FROM membership_conflicts
        UNION ALL
        SELECT asset_key, organization_name FROM recorded_conflicts
      ) conflicts GROUP BY asset_key
    ), assigned AS (
      SELECT a.*, sm.company_id, sm.organization_name, sm.role AS membership_role,
             uc.organization_name AS unresolved_name,
        CASE WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS group_key,
        CASE WHEN uc.asset_key IS NOT NULL
             THEN coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                  'Unresolved project')
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN coalesce(nullif(r.operator_name, ''), 'RRC operator ' || r.operator_number)
             WHEN sm.company_id IS NOT NULL THEN sm.organization_name
             ELSE coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                    'Unresolved project') END AS group_name,
        CASE WHEN uc.asset_key IS NOT NULL THEN 'unresolved'
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$' THEN 'operator'
             WHEN sm.company_id IS NOT NULL AND lower(sm.role) LIKE '%operator%'
             THEN 'operator' WHEN sm.company_id IS NOT NULL THEN 'customer'
             ELSE 'unresolved' END AS group_role,
        coalesce(nullif(r.sector, ''), 'unknown') AS sector
      FROM assets a JOIN representatives r USING (asset_key)
      LEFT JOIN single_membership sm USING (asset_key)
      LEFT JOIN unresolved_conflicts uc USING (asset_key)
    ), grouped AS (
      SELECT group_key, (array_agg(group_name ORDER BY group_name))[1] AS name,
        (array_agg(group_role ORDER BY group_role))[1] AS role,
        max(priority_score)::integer AS priority_score,
        count(*)::integer AS project_count, sum(need_count)::integer AS need_count,
        array_agg(DISTINCT sector ORDER BY sector) AS sectors,
        max(updated_at) AS updated_at
      FROM assigned GROUP BY group_key
    )
    """.replace("%%ASSET%%", _ASSET_B).replace("%%WHERE%%", where)


def _group_id(key: str) -> str:
    return "cg_" + hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def _validate_token(token: str | None, expected: str, offset: int) -> None:
    if token is not None and token != expected:
        raise HTTPException(409, "Customer cohort changed; restart pagination")
    if offset and not token:
        raise HTTPException(422, "cohort_token is required when offset is greater than zero")


def groups(
    session,
    *,
    search=None,
    sector="all",
    limit=25,
    offset=0,
    token=None,
    sort="priority",
    selected_generation=None,
):
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    generation, term, cohort = _cohort(
        session, search=search, sector=sector, sort=sort, selected_generation=selected_generation
    )
    _validate_token(token, cohort, offset)
    where, params = _query_parts(generation, term, sector)
    order = (
        "priority_score DESC, name, group_key"
        if sort == "priority"
        else "updated_at DESC, group_key"
    )
    sql = _ctes(where)
    total = session.execute(text(sql + " SELECT count(*) FROM grouped"), params).scalar_one()
    if total == 0 and term:  # TEMPORARY flake forensics; remove before merge.
        import sys

        try:
            dbg = session.execute(
                text(
                    "SELECT (SELECT count(*) FROM browse_rows),"
                    " (SELECT count(*) FROM browse_rows WHERE generation_id = :gen),"
                    " (SELECT count(*) FROM browse_rows"
                    "  WHERE strpos(search_text, :term) > 0),"
                    " (SELECT count(*) FROM browse_state)"
                ),
                {"gen": generation.id, "term": term},
            ).one()
            print(
                f"GROUPS-DEBUG gen={generation.id} row_count={generation.row_count}"
                f" all_rows={dbg[0]} gen_rows={dbg[1]} term_rows={dbg[2]}"
                f" state_rows={dbg[3]}",
                file=sys.stderr,
            )
        except Exception as error:  # noqa: BLE001
            print(f"GROUPS-DEBUG ERROR {error}", file=sys.stderr)
    rows = (
        session.execute(
            text(sql + f" SELECT * FROM grouped ORDER BY {order} LIMIT :limit OFFSET :offset"),
            {**params, "limit": limit, "offset": min(offset, generation.row_count)},
        )
        .mappings()
        .all()
    )
    items = [
        {
            "id": _group_id(row["group_key"]),
            "name": row["name"],
            "role": row["role"],
            "project_count": row["project_count"],
            "need_count": row["need_count"],
            "priority_score": row["priority_score"],
            "sectors": row["sectors"],
        }
        for row in rows
    ]
    return {
        "items": items,
        "count_unit": "operators and customers",
        "total": total,
        "limit": limit,
        "offset": offset,
        "cohort_token": cohort,
        "generation": str(generation.id),
    }


def group_metadata(
    session, group_id: str, *, search=None, sector="all", sort="priority", selected_generation=None
):
    """Resolve one group against the entire filtered cohort without paging headers."""
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    generation, term, _ = _cohort(
        session, search=search, sector=sector, sort=sort, selected_generation=selected_generation
    )
    where, params = _query_parts(generation, term, sector)
    sql = _ctes(where)
    row = (
        session.execute(
            text(
                sql
                + """
                SELECT group_key, name, role, project_count, need_count, priority_score, sectors
                FROM grouped WHERE 'cg_' || md5(group_key) = :id
                """
            ),
            {**params, "id": group_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Customer group not found in this cohort")
    return {
        "id": _group_id(row["group_key"]),
        "name": row["name"],
        "role": row["role"],
        "project_count": row["project_count"],
        "need_count": row["need_count"],
        "priority_score": row["priority_score"],
        "sectors": row["sectors"],
    }


def group_projects(
    session,
    group_id: str,
    *,
    search=None,
    sector="all",
    limit=25,
    offset=0,
    token=None,
    parent_token=None,
    sort="priority",
    selected_generation=None,
):
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    generation, term, cohort = _cohort(
        session, search=search, sector=sector, sort=sort, selected_generation=selected_generation
    )
    if parent_token is None:
        raise HTTPException(422, "parent_cohort_token is required for customer projects")
    if parent_token != cohort:
        raise HTTPException(409, "Customer cohort changed; restart pagination")
    group_token = cohort + ".group." + hashlib.sha256(group_id.encode()).hexdigest()[:16]
    _validate_token(token, group_token, offset)
    where, params = _query_parts(generation, term, sector)
    sql = _ctes(where)
    # Resolve the opaque group id using built-in PostgreSQL md5 and collect only
    # the requested asset page's anchor project IDs for the shared serializer.
    child_order = "a.priority_score DESC" if sort == "priority" else "a.updated_at DESC"
    rows = (
        session.execute(
            text(
                sql
                + f"""
          SELECT a.anchor_project_id, a.asset_key, a.group_name, a.group_role,
                 a.priority_score, a.need_count, a.sector, a.updated_at
          FROM assigned a
          WHERE 'cg_' || md5(a.group_key) = :id
          ORDER BY {child_order}, a.asset_key
          LIMIT :limit OFFSET :offset
        """
            ),
            {**params, "id": group_id, "limit": limit, "offset": min(offset, generation.row_count)},
        )
        .mappings()
        .all()
    )
    count = session.execute(
        text(
            sql
            + """
          SELECT count(*) FROM assigned a
          WHERE 'cg_' || md5(a.group_key) = :id
        """
        ),
        {**params, "id": group_id},
    ).scalar_one()
    if count == 0:
        raise HTTPException(404, "Customer group not found in this cohort")
    project_ids = [UUID(row["anchor_project_id"]) for row in rows]
    serialized = (
        project_page(
            session,
            search=None,
            sector=sector,
            limit=max(1, len(project_ids)),
            offset=0,
            sort=sort,
            include_signals=True,
            project_ids=project_ids,
            selected_generation=generation,
        )
        if project_ids
        else {"items": [], "generation": str(generation.id)}
    )
    return {
        "items": serialized["items"],
        "count_unit": "projects",
        "total": count,
        "limit": limit,
        "offset": offset,
        "cohort_token": group_token,
        "generation": str(generation.id),
        "group": {
            "id": group_id,
            "name": rows[0]["group_name"] if rows else "",
            "role": rows[0]["group_role"] if rows else "unresolved",
        },
    }
