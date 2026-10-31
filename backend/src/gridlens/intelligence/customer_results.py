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


def _cohort(
    session,
    *,
    search: str | None,
    sector: str,
    sort: str,
    region: str | None = None,
    stage: str | None = None,
    priority: str | None = None,
    selected_generation=None,
):
    generation = selected_generation or current_generation(session)
    term = (search or "").strip().casefold()
    payload: list[Any] = [
        "customer-rollup-v2-tdlr-owner-namebucket",
        str(generation.id),
        generation.digest,
        sector,
        sort,
        term,
        region or "",
        stage or "",
        priority or "",
        "",
        True,
        [],
    ]
    token = "p1_" + hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return generation, term, token


def _snapshot_metadata(generation) -> dict[str, str]:
    """Expose the exact published snapshot time on every successful page."""
    as_of = generation.built_at.isoformat()
    return {
        "generation_id": str(generation.id),
        "as_of": as_of,
        "valid_until": generation.valid_until.isoformat(),
        "qualification_state": "current",
        "refresh_state": "current",
    }


def _disable_jit_for_search(session, term: str) -> None:
    # PostgreSQL's JIT threshold can trigger substantial one-off compilation
    # for the substring-search cohort query. Keep this request-local; do not
    # alter the database-wide setting used by other workloads.
    if term:
        session.execute(text("SET LOCAL jit = off"))


def _query_parts(generation, term, sector):
    clauses = ["b.generation_id = :generation"]
    params: dict[str, Any] = {"generation": generation.id, "term": term}
    if sector == "oil_gas":
        clauses.append("b.compact #>> '{project_metadata,sector}' = 'oil_gas'")
    elif sector == "data_centers":
        clauses.append("b.compact #>> '{project_metadata,sector}' = 'data_centers'")
    return " AND ".join(clauses), params


def _group_filter(*, term, region, stage, priority, alias="g"):
    """Select whole customer groups through any matching member project."""
    clauses = ["TRUE"]
    params: dict[str, Any] = {"term": term}
    if region:
        clauses.append(
            "EXISTS (SELECT 1 FROM assigned fa JOIN browse_rows fb "
            "ON fb.generation_id=:generation AND fb.project_id IN "
            "(SELECT ar.project_id FROM all_rows ar WHERE ar.asset_key=fa.asset_key) "
            f"WHERE fa.group_key={alias}.group_key AND fb.compact->>'location'=:region)"
        )
        params["region"] = region
    if stage:
        clauses.append(
            "EXISTS (SELECT 1 FROM assigned fa JOIN browse_rows fb "
            "ON fb.generation_id=:generation AND fb.project_id IN "
            "(SELECT ar.project_id FROM all_rows ar WHERE ar.asset_key=fa.asset_key) "
            f"WHERE fa.group_key={alias}.group_key "
            "AND fb.compact #>> '{project_metadata,event,kind}'=:stage)"
        )
        params["stage"] = stage
    if priority == "ranked":
        clauses.append(
            f"{alias}.priority_score IS NOT NULL"
            if alias == "g"
            else f"EXISTS (SELECT 1 FROM assigned pf WHERE pf.group_key={alias}.group_key "
            "AND pf.priority_score IS NOT NULL)"
        )
    elif priority == "unranked":
        clauses.append(
            f"{alias}.priority_score IS NULL"
            if alias == "g"
            else f"NOT EXISTS (SELECT 1 FROM assigned pf WHERE pf.group_key={alias}.group_key "
            "AND pf.priority_score IS NOT NULL)"
        )
    if term:
        name_column = "group_name" if alias == "a" else "name"
        clauses.append(
            f"(strpos(lower(coalesce({alias}.{name_column},'')), :term) > 0 OR EXISTS ("
            "SELECT 1 FROM assigned sa JOIN browse_rows sb "
            "ON sb.generation_id=:generation AND sb.project_id IN "
            "(SELECT ar.project_id FROM all_rows ar WHERE ar.asset_key=sa.asset_key) "
            f"WHERE sa.group_key={alias}.group_key AND ("
            "strpos(sb.search_text,:term)>0 OR "
            "strpos(lower(coalesce(sb.compact->>'browse_title','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact->>'name','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> '{project_metadata,operator}','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> "
            "'{project_metadata,oil_gas,operator_number}','')),:term)>0 OR "
            "EXISTS (SELECT 1 FROM browse_customer_memberships cm "
            "WHERE cm.generation_id=sb.generation_id AND cm.project_id=sb.project_id "
            "AND lower(cm.role) NOT IN ('contractor','general_contractor','epc','subcontractor') "
            "AND strpos(lower(cm.organization_name),:term)>0) OR "
            "EXISTS (SELECT 1 FROM browse_unresolved_customers uc "
            "WHERE uc.generation_id=sb.generation_id AND uc.project_id=sb.project_id "
            "AND strpos(lower(uc.organization_name),:term)>0))))"
        )
    return " AND ".join(clauses), params


def _facets(session, generation, sector):
    where, params = _query_parts(generation, "", sector)
    row = (
        session.execute(
            text(
                "SELECT coalesce(array_agg(DISTINCT nullif(b.compact->>'location','') "
                "ORDER BY nullif(b.compact->>'location','')) FILTER "
                "(WHERE nullif(b.compact->>'location','') IS NOT NULL), ARRAY[]::text[]) regions, "
                "coalesce(array_agg(DISTINCT nullif(b.compact #>> "
                "'{project_metadata,event,kind}','') ORDER BY nullif(b.compact #>> "
                "'{project_metadata,event,kind}','')) FILTER (WHERE nullif(b.compact #>> "
                "'{project_metadata,event,kind}','') IS NOT NULL), ARRAY[]::text[]) stages "
                "FROM browse_rows b WHERE " + where
            ),
            params,
        )
        .mappings()
        .one()
    )
    return {"regions": row["regions"], "stages": row["stages"]}


def _ctes(where: str) -> str:
    # In the unfiltered All cohort, matched already contains every row in the
    # generation. Reusing it avoids rescanning browse_rows and recomputing the
    # validated asset identity for the same rows. Filtered cohorts still expand
    # each matched asset to all of its generation rows below.
    all_rows = (
        "all_rows AS (SELECT * FROM matched),"
        if where == "b.generation_id = :generation"
        else """
    all_rows AS (
      SELECT %%ASSET%% AS asset_key, b.project_id, b.need_id, b.compact,
             b.rank_score, b.updated_at
      FROM browse_rows b JOIN candidate_assets c ON c.asset_key = %%ASSET%%
      WHERE %%WHERE%%
    ),"""
    )
    return (
        """
    WITH matched AS (
      SELECT %%ASSET%% AS asset_key, b.project_id, b.need_id, b.compact,
             b.rank_score, b.updated_at
      FROM browse_rows b WHERE %%WHERE%%
    ), candidate_assets AS (
      SELECT asset_key, min(project_id::text) AS anchor_project_id
      FROM matched GROUP BY asset_key
    ), %%ALL_ROWS%% assets AS (
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
    ), same_name_asset_eligible AS (
      SELECT DISTINCT r.asset_key, sm.company_id, sm.organization_name, sm.role
      FROM all_rows r
      JOIN single_membership sm ON sm.asset_key = r.asset_key
      LEFT JOIN unresolved_conflicts uc ON uc.asset_key = r.asset_key
      WHERE uc.asset_key IS NULL
        AND NOT EXISTS (
          SELECT 1 FROM all_rows nr
          WHERE nr.asset_key = r.asset_key
            AND nullif(nr.compact #>> '{project_metadata,oil_gas,operator_number}', '')
                ~ '^[0-9]+$'
        )
        AND sm.role = 'owner_developer'
        AND nullif(sm.organization_name, '') IS NOT NULL
        AND r.compact #>> '{project_metadata,sector}' = 'data_centers'
        AND convert_to(
          r.compact #>> '{project_metadata,data_center,owner_developer}', 'UTF8'
        ) = convert_to(sm.organization_name, 'UTF8')
        AND r.compact #>> '{project_metadata,event,source}' = 'texas-tdlr-tabs-data-centers'
        AND CASE
          WHEN jsonb_typeof(r.compact #> '{project_metadata,event,evidence_refs}') = 'array'
          THEN jsonb_array_length(r.compact #> '{project_metadata,event,evidence_refs}') > 0
          ELSE false
        END
        -- An asset may enter a presentation bucket only when every project
        -- represented by that canonical asset meets the same strict rule.
        AND NOT EXISTS (
          SELECT 1 FROM all_rows nr
          WHERE nr.asset_key = r.asset_key AND (
            nr.compact #>> '{project_metadata,sector}' = 'data_centers'
            AND convert_to(
              nr.compact #>> '{project_metadata,data_center,owner_developer}', 'UTF8'
            ) = convert_to(sm.organization_name, 'UTF8')
            AND nr.compact #>> '{project_metadata,event,source}' = 'texas-tdlr-tabs-data-centers'
            AND CASE
              WHEN jsonb_typeof(nr.compact #> '{project_metadata,event,evidence_refs}') = 'array'
              THEN jsonb_array_length(nr.compact #> '{project_metadata,event,evidence_refs}') > 0
              ELSE false
            END
          ) IS NOT TRUE
        )
    ), same_name_eligible AS (
      -- Require every asset attached to this company UUID to be eligible.
      -- This prevents a good TDLR project from pulling unsupported siblings
      -- into the same-name display collection.
      SELECT candidate.* FROM same_name_asset_eligible candidate
      WHERE NOT EXISTS (
        SELECT 1 FROM assets ca
        JOIN single_membership csm ON csm.asset_key = ca.asset_key
        WHERE csm.company_id = candidate.company_id
          AND NOT EXISTS (
            SELECT 1 FROM same_name_asset_eligible eligible
            WHERE eligible.asset_key = ca.asset_key
              AND eligible.company_id = csm.company_id
              AND eligible.role = candidate.role
              AND convert_to(eligible.organization_name, 'UTF8') =
                  convert_to(candidate.organization_name, 'UTF8')
          )
      )
    ), same_name_bucket_defs AS (
      SELECT convert_to(organization_name, 'UTF8') AS organization_name_bytes, role,
             min(organization_name) AS organization_name,
             count(DISTINCT company_id)::integer AS identity_count
      FROM same_name_eligible
      GROUP BY convert_to(organization_name, 'UTF8'), role
      HAVING count(DISTINCT company_id) > 1
    ), same_name_bucket_assets AS (
      SELECT DISTINCT e.asset_key,
             'namebucket:' || e.role || ':' || encode(e.organization_name_bytes, 'hex')
               AS display_key,
             d.identity_count
      FROM (
        SELECT e.*, convert_to(e.organization_name, 'UTF8') AS organization_name_bytes
        FROM same_name_eligible e
      ) e
      JOIN same_name_bucket_defs d
        USING (organization_name_bytes, role)
    ), assigned AS (
      SELECT a.*, sm.company_id, sm.organization_name, sm.role AS membership_role,
             uc.organization_name AS unresolved_name,
             nb.display_key AS display_container_key, nb.identity_count,
        CASE WHEN nb.display_key IS NOT NULL THEN nb.display_key
             WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS group_key,
        CASE WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS identity_key,
        CASE WHEN uc.asset_key IS NOT NULL
             THEN coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                  'Unresolved project')
             WHEN nb.display_key IS NOT NULL THEN sm.organization_name
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN coalesce(nullif(r.operator_name, ''), 'RRC operator ' || r.operator_number)
             WHEN sm.company_id IS NOT NULL THEN sm.organization_name
             ELSE coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                    'Unresolved project') END AS group_name,
        CASE WHEN nb.display_key IS NOT NULL THEN 'unresolved'
             WHEN uc.asset_key IS NOT NULL THEN 'unresolved'
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$' THEN 'operator'
             WHEN sm.company_id IS NOT NULL AND lower(sm.role) LIKE '%operator%'
             THEN 'operator' WHEN sm.company_id IS NOT NULL THEN 'customer'
             ELSE 'unresolved' END AS group_role,
        CASE WHEN nb.display_key IS NOT NULL THEN 'same_name_unconfirmed'
             WHEN uc.asset_key IS NOT NULL THEN 'unresolved'
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$' OR sm.company_id IS NOT NULL
               THEN 'resolved_identity'
             ELSE 'unresolved' END AS group_kind,
        coalesce(nullif(r.sector, ''), 'unknown') AS sector
      FROM assets a JOIN representatives r USING (asset_key)
      LEFT JOIN single_membership sm USING (asset_key)
      LEFT JOIN unresolved_conflicts uc USING (asset_key)
      LEFT JOIN same_name_bucket_assets nb USING (asset_key)
    ), grouped AS (
      SELECT group_key, (array_agg(group_name ORDER BY group_name))[1] AS name,
        (array_agg(group_role ORDER BY group_role))[1] AS role,
        CASE WHEN bool_or(group_kind = 'same_name_unconfirmed')
             THEN 'same_name_unconfirmed'
             WHEN bool_or(group_kind = 'resolved_identity') THEN 'resolved_identity'
             ELSE 'unresolved' END AS group_kind,
        CASE WHEN bool_or(group_kind = 'same_name_unconfirmed')
             THEN max(identity_count)
             WHEN bool_or(group_kind = 'resolved_identity') THEN 1
             ELSE NULL END AS identity_count,
        max(priority_score)::integer AS priority_score,
        count(*)::integer AS project_count, sum(need_count)::integer AS need_count,
        array_agg(DISTINCT sector ORDER BY sector) AS sectors,
        max(updated_at) AS updated_at
      FROM assigned GROUP BY group_key
    )
    """.replace("%%ALL_ROWS%%", all_rows)
        .replace("%%ASSET%%", _ASSET_B)
        .replace("%%WHERE%%", where)
    )


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
    region=None,
    stage=None,
    priority=None,
    selected_generation=None,
):
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    if sort not in {"priority", "priority_asc", "company", "updated"}:
        raise HTTPException(422, "Unsupported customer sort")
    if priority not in {None, "ranked", "unranked"}:
        raise HTTPException(422, "priority must be ranked or unranked")
    generation, term, cohort = _cohort(
        session,
        search=search,
        sector=sector,
        sort=sort,
        region=region,
        stage=stage,
        priority=priority,
        selected_generation=selected_generation,
    )
    _validate_token(token, cohort, offset)
    _disable_jit_for_search(session, term)
    where, params = _query_parts(generation, term, sector)
    order = {
        "priority": "priority_score DESC NULLS LAST, name, group_key",
        "priority_asc": "priority_score ASC NULLS LAST, name, group_key",
        "company": "lower(name), group_key",
        "updated": "updated_at DESC NULLS LAST, group_key",
    }[sort]
    selected, selected_params = _group_filter(
        term=term, region=region, stage=stage, priority=priority
    )
    params.update(selected_params)
    params["generation"] = generation.id
    sql = _ctes(where)
    rows = (
        session.execute(
            text(
                sql
                + " SELECT g.*, count(*) OVER() AS total FROM grouped g WHERE "
                + selected
                + " "
                + f"ORDER BY {order} LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": min(offset, generation.row_count)},
        )
        .mappings()
        .all()
    )
    # Count the cohort in the same grouped pass as the requested page. The
    # window is evaluated before LIMIT/OFFSET, so every page retains the same
    # total without rebuilding the full aggregation a second time.
    if rows:
        total = rows[0]["total"]
    else:
        # An empty page may be out of range or an empty cohort. Keep the count
        # query for this uncommon case so totals remain exact.
        total = session.execute(
            text(sql + " SELECT count(*) FROM grouped g WHERE " + selected), params
        ).scalar_one()
    items = [
        {
            "id": _group_id(row["group_key"]),
            "name": row["name"],
            "role": row["role"],
            "group_kind": row["group_kind"],
            "identity_count": row["identity_count"],
            "project_count": row["project_count"],
            "need_count": row["need_count"],
            "priority_score": row["priority_score"],
            "sectors": row["sectors"],
        }
        for row in rows
    ]
    return {
        "items": items,
        "count_unit": "groups",
        "total": total,
        "limit": limit,
        "offset": offset,
        "cohort_token": cohort,
        "generation": str(generation.id),
        "facets": _facets(session, generation, sector),
        **_snapshot_metadata(generation),
    }


def group_metadata(
    session,
    group_id: str,
    *,
    search=None,
    sector="all",
    sort="priority",
    region=None,
    stage=None,
    priority=None,
    selected_generation=None,
):
    """Resolve one group against the entire filtered cohort without paging headers."""
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    generation, term, _ = _cohort(
        session,
        search=search,
        sector=sector,
        sort=sort,
        region=region,
        stage=stage,
        priority=priority,
        selected_generation=selected_generation,
    )
    where, params = _query_parts(generation, term, sector)
    sql = _ctes(where)
    selected, selected_params = _group_filter(
        term=term, region=region, stage=stage, priority=priority
    )
    row = (
        session.execute(
            text(
                sql
                + """
                SELECT group_key, name, role, group_kind, identity_count, project_count,
                       need_count, priority_score, sectors
                FROM grouped g WHERE 'cg_' || md5(group_key) = :id AND """
                + selected
            ),
            {**params, "id": group_id, "generation": generation.id, **selected_params},
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
        "group_kind": row["group_kind"],
        "identity_count": row["identity_count"],
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
    region=None,
    stage=None,
    priority=None,
    selected_generation=None,
):
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    if sort not in {"priority", "priority_asc", "company", "updated"}:
        raise HTTPException(422, "Unsupported customer sort")
    if priority not in {None, "ranked", "unranked"}:
        raise HTTPException(422, "priority must be ranked or unranked")
    generation, term, cohort = _cohort(
        session,
        search=search,
        sector=sector,
        sort=sort,
        region=region,
        stage=stage,
        priority=priority,
        selected_generation=selected_generation,
    )
    if parent_token is None:
        raise HTTPException(422, "parent_cohort_token is required for customer projects")
    if parent_token != cohort:
        raise HTTPException(409, "Customer cohort changed; restart pagination")
    group_token = cohort + ".group." + hashlib.sha256(group_id.encode()).hexdigest()[:16]
    _validate_token(token, group_token, offset)
    _disable_jit_for_search(session, term)
    where, params = _query_parts(generation, term, sector)
    sql = _ctes(where)
    # Resolve the opaque group id using built-in PostgreSQL md5 and collect only
    # the requested asset page's anchor project IDs for the shared serializer.
    child_order = {
        "priority": "a.priority_score DESC NULLS LAST, a.updated_at DESC NULLS LAST",
        "priority_asc": "a.priority_score ASC NULLS LAST, a.updated_at DESC NULLS LAST",
        "company": "lower(a.group_name), a.asset_key",
        "updated": "a.updated_at DESC NULLS LAST",
    }[sort]
    selected, selected_params = _group_filter(
        term=term, region=region, stage=stage, priority=priority, alias="a"
    )
    params.update(selected_params)
    params["generation"] = generation.id
    rows = (
        session.execute(
            text(
                sql
                + f"""
          SELECT a.anchor_project_id, a.asset_key, a.company_id, a.group_name, a.group_role,
                 a.group_kind, a.identity_count,
                 a.priority_score, a.need_count, a.sector, a.updated_at,
                 count(*) OVER() AS total
          FROM assigned a
          WHERE 'cg_' || md5(a.group_key) = :id AND {selected}
          ORDER BY {child_order}, a.asset_key
          LIMIT :limit OFFSET :offset
        """
            ),
            {**params, "id": group_id, "limit": limit, "offset": min(offset, generation.row_count)},
        )
        .mappings()
        .all()
    )
    if rows:
        count = rows[0]["total"]
    else:
        # Preserve exact empty-cohort and out-of-range behavior without paying
        # for a second full assignment aggregation on ordinary pages.
        count = session.execute(
            text(
                sql
                + "SELECT count(*) FROM assigned a "
                + "WHERE 'cg_' || md5(a.group_key) = :id AND "
                + selected
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
    customer_identity_by_anchor = {str(row["anchor_project_id"]): row["company_id"] for row in rows}
    for item in serialized["items"]:
        item["customer_identity_id"] = next(
            (
                customer_identity_by_anchor[project_id]
                for project_id in item["project_ids"]
                if project_id in customer_identity_by_anchor
            ),
            None,
        )
    return {
        "items": serialized["items"],
        "count_unit": "projects",
        "total": count,
        "limit": limit,
        "offset": offset,
        "cohort_token": group_token,
        "generation": str(generation.id),
        **_snapshot_metadata(generation),
        "group": {
            "id": group_id,
            "name": rows[0]["group_name"] if rows else "",
            "role": rows[0]["group_role"] if rows else "unresolved",
            "group_kind": rows[0]["group_kind"] if rows else "unresolved",
            "identity_count": rows[0]["identity_count"] if rows else None,
        },
    }
