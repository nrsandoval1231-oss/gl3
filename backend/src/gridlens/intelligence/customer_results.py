"""Bounded read-only operator/customer group pages over saved browse scalars."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from gridlens.intelligence.customer_primary import CUSTOMER_ROLE_ORDER, OWNER_ROLES
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
    shortlist=False,
):
    generation = selected_generation or current_generation(session)
    term = (search or "").strip().casefold()
    from gridlens.domain.opportunity_shortlist import POLICY_VERSION
    from gridlens.intelligence.account_shortlist import assess_generation

    shortlist_digest = (
        assess_generation(session, generation)["jev_map_digest"] if session is not None else None
    )
    need_alias_map = _current_need_alias_map(session, generation) if session is not None else {}
    alias_projects = (
        _current_graph_alias_projects(session, generation, term)
        if session is not None and term
        else []
    )
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
        bool(shortlist),
        POLICY_VERSION,
        date.today().isoformat(),
        shortlist_digest,
        sorted(str(project_id) for project_id in alias_projects),
        hashlib.sha256(
            json.dumps(
                sorted((str(alias), str(root)) for alias, root in need_alias_map.items()),
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
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


def _current_graph_alias_projects(session, generation, term: str) -> list[UUID]:
    """Resolve only graph names still cited by the latest current project view."""
    if not term:
        return []
    transaction = session.get_transaction()
    cache_key = (str(generation.id), term)
    cached = session.info.get("graph_alias_project_cache")
    if transaction is not None and cached and cached[0] is transaction and cached[1] == cache_key:
        return cached[2]
    from gridlens.intelligence.buying_chain import buying_chain_views
    from gridlens.intelligence.company_graph import IDENTITY_NAME_TYPES
    from gridlens.intelligence.contact_suppressions import company_suppression_key
    from gridlens.persistence.suppression_models import ContactSuppression

    customer_roles = list(CUSTOMER_ROLE_ORDER)
    owner_roles = list(OWNER_ROLES)

    candidates = (
        session.execute(
            text("""
            SELECT DISTINCT be.project_id, ii.company_identity_id, be.id AS source_id,
                   be.content_hash
            FROM identity_identifiers ii
            JOIN buying_chain_evidence be ON be.id=ii.source_evidence_id
            JOIN browse_customer_memberships cm
              ON cm.company_identity_id=ii.company_identity_id AND cm.project_id=be.project_id
             AND cm.generation_id=:generation
            JOIN browse_rows role_br ON role_br.generation_id=:generation
              AND role_br.project_id=be.project_id
            JOIN LATERAL (
              SELECT br.evidence_ids FROM buying_chain_runs br
              WHERE br.project_id=be.project_id
              ORDER BY br.created_at DESC, br.id DESC LIMIT 1
            ) current_run ON current_run.evidence_ids @> jsonb_build_array(be.id::text)
            WHERE ii.entity_type='company'
              AND ii.identifier_type = ANY(CAST(:name_types AS text[]))
              AND strpos(lower(ii.normalized_value),:term)>0
              AND ii.source_version_hash=be.content_hash
              AND cm.role = ANY(CAST(:customer_roles AS text[]))
              AND CASE
                WHEN role_br.compact #>> '{project_metadata,sector}'='oil_gas' THEN
                  CASE WHEN EXISTS (
                    SELECT 1 FROM browse_customer_memberships op
                    WHERE op.generation_id=:generation AND op.project_id=be.project_id
                      AND op.role='asset_operator'
                  ) THEN cm.role='asset_operator'
                  ELSE cm.role = ANY(CAST(:owner_roles AS text[])) END
                WHEN role_br.compact #>> '{project_metadata,sector}'='data_centers' THEN
                  CASE WHEN EXISTS (
                    SELECT 1 FROM browse_customer_memberships own
                    WHERE own.generation_id=:generation AND own.project_id=be.project_id
                      AND own.role = ANY(CAST(:owner_roles AS text[]))
                  ) THEN cm.role = ANY(CAST(:owner_roles AS text[]))
                  ELSE cm.role='asset_operator' END
                ELSE true END
              AND NOT EXISTS (
                SELECT 1 FROM browse_unresolved_customers uc
                WHERE uc.generation_id=:generation AND uc.project_id=be.project_id
                  AND uc.role='conflicting_customer'
              )
              AND NOT EXISTS (
                SELECT 1 FROM buying_chain_evidence newer
                WHERE newer.project_id=be.project_id AND newer.url=be.url
                  AND (newer.observed_at > be.observed_at OR
                       (newer.observed_at=be.observed_at AND newer.id > be.id))
              )
            """),
            {
                "generation": generation.id,
                "name_types": sorted(IDENTITY_NAME_TYPES),
                "customer_roles": customer_roles,
                "owner_roles": owner_roles,
                "term": term,
            },
        )
        .mappings()
        .all()
    )
    if not candidates:
        session.info["graph_alias_project_cache"] = (session.get_transaction(), cache_key, [])
        return []
    project_ids = {row["project_id"] for row in candidates}
    views = buying_chain_views(session, project_ids)
    linked_current = set()
    for row in candidates:
        view = views.get(str(row["project_id"]), {})
        if any(
            str(candidate.get("company_identity_id")) == str(row["company_identity_id"])
            and any(
                str(evidence.get("id")) == str(row["source_id"])
                and str(evidence.get("current_source_version_id")) == str(row["source_id"])
                and evidence.get("content_hash") == row["content_hash"]
                and evidence.get("current_support") is True
                for evidence in candidate.get("evidence", [])
            )
            for candidate in view.get("candidates", [])
        ):
            linked_current.add((row["project_id"], row["company_identity_id"]))
    company_ids = {row["company_identity_id"] for row in candidates}
    suppression_keys = {company_suppression_key(company_id) for company_id in company_ids}
    suppression_rows = session.execute(
        select(ContactSuppression.scope, ContactSuppression.subject_key, ContactSuppression.action)
        .where(
            ContactSuppression.scope == "company",
            ContactSuppression.subject_key.in_(suppression_keys),
        )
        .order_by(ContactSuppression.subject_key, ContactSuppression.version.desc())
    ).all()
    suppressed: set[str] = set()
    seen: set[str] = set()
    for scope, key, action in suppression_rows:
        if scope == "company" and key not in seen:
            seen.add(key)
            if action == "suppress":
                suppressed.add(key)
    allowed_ids = {
        row["company_identity_id"]
        for row in candidates
        if company_suppression_key(row["company_identity_id"]) not in suppressed
    }
    result = sorted(
        {project_id for project_id, company_id in linked_current if company_id in allowed_ids},
        key=str,
    )
    session.info["graph_alias_project_cache"] = (session.get_transaction(), cache_key, result)
    return result


def _current_need_alias_map(session, generation) -> dict[UUID, UUID]:
    """Batch-read validated alias roots once in the current read transaction."""
    transaction = session.get_transaction()
    cached = session.info.get("customer_need_alias_map")
    if transaction is not None and cached and cached[0] is transaction:
        return cached[1]
    from gridlens.intelligence.need_aliases import canonical_need_map

    result = canonical_need_map(session)
    session.info["customer_need_alias_map"] = (session.get_transaction(), result)
    return result


def _group_filter(*, term, region, stage, priority, alias="g", session=None, generation=None):
    """Select whole customer groups through any matching member project."""
    clauses = ["TRUE"]
    params: dict[str, Any] = {"term": term}
    params["customer_roles"] = list(CUSTOMER_ROLE_ORDER)
    params["owner_roles"] = list(OWNER_ROLES)
    alias_projects = (
        _current_graph_alias_projects(session, generation, term)
        if session is not None and generation is not None and term
        else []
    )
    params["graph_alias_project_ids"] = alias_projects
    # Qualify from set-based group-key subqueries. Project search and location/
    # stage filters must match the same child; account names remain group-wide.
    member_asset_projects = "SELECT DISTINCT ar.asset_key, ar.project_id FROM all_rows ar"
    if region and stage:
        clauses.append(
            f"{alias}.group_key IN (SELECT DISTINCT fa.group_key "
            "FROM assigned fa JOIN (" + member_asset_projects + ") ar "
            "ON ar.asset_key=fa.asset_key JOIN browse_rows fb "
            "ON fb.generation_id=:generation AND fb.project_id=ar.project_id "
            "WHERE fb.compact->>'location'=:region AND "
            "fb.compact #>> '{project_metadata,event,kind}'=:stage)"
        )
        params.update({"region": region, "stage": stage})
    elif region:
        clauses.append(
            f"{alias}.group_key IN (SELECT DISTINCT fa.group_key "
            "FROM assigned fa JOIN (" + member_asset_projects + ") ar "
            "ON ar.asset_key=fa.asset_key JOIN browse_rows fb "
            "ON fb.generation_id=:generation AND fb.project_id=ar.project_id "
            "WHERE fb.compact->>'location'=:region)"
        )
        params["region"] = region
    if stage and not region:
        clauses.append(
            f"{alias}.group_key IN (SELECT DISTINCT fa.group_key "
            "FROM assigned fa JOIN (" + member_asset_projects + ") ar "
            "ON ar.asset_key=fa.asset_key JOIN browse_rows fb "
            "ON fb.generation_id=:generation AND fb.project_id=ar.project_id "
            "WHERE fb.compact #>> '{project_metadata,event,kind}'=:stage)"
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
        child_scope = ""
        if region:
            child_scope += " AND sb.compact->>'location'=:region"
        if stage:
            child_scope += " AND sb.compact #>> '{project_metadata,event,kind}'=:stage"
        clauses.append(
            f"(strpos(lower(coalesce({alias}.{name_column},'')), :term) > 0 OR "
            f"{alias}.group_key IN (SELECT DISTINCT sa.group_key "
            "FROM assigned sa JOIN (" + member_asset_projects + ") ar "
            "ON ar.asset_key=sa.asset_key JOIN browse_rows sb "
            "ON sb.generation_id=:generation AND sb.project_id=ar.project_id "
            "WHERE (("
            "strpos(sb.search_text,:term)>0 OR "
            "strpos(lower(coalesce(sb.compact->>'browse_title','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact->>'name','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> '{project_metadata,title}','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> '{project_metadata,name}','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> '{project_metadata,operator}','')),:term)>0 OR "
            "strpos(lower(coalesce(sb.compact #>> "
            "'{project_metadata,oil_gas,operator_number}','')),:term)>0 OR "
            "EXISTS (SELECT 1 FROM browse_customer_memberships cm "
            "WHERE cm.generation_id=sb.generation_id AND cm.project_id=sb.project_id "
            "AND cm.role = ANY(CAST(:customer_roles AS text[])) "
            "AND CASE "
            "WHEN sb.compact #>> '{project_metadata,sector}'='oil_gas' THEN "
            "CASE WHEN EXISTS (SELECT 1 FROM browse_customer_memberships op "
            "WHERE op.generation_id=sb.generation_id AND op.project_id=sb.project_id "
            "AND op.role='asset_operator') THEN cm.role='asset_operator' "
            "ELSE cm.role = ANY(CAST(:owner_roles AS text[])) END "
            "WHEN sb.compact #>> '{project_metadata,sector}'='data_centers' THEN "
            "CASE WHEN EXISTS (SELECT 1 FROM browse_customer_memberships own "
            "WHERE own.generation_id=sb.generation_id AND own.project_id=sb.project_id "
            "AND own.role = ANY(CAST(:owner_roles AS text[]))) "
            "THEN cm.role = ANY(CAST(:owner_roles AS text[])) "
            "ELSE cm.role='asset_operator' END ELSE true END "
            "AND NOT EXISTS (SELECT 1 FROM browse_unresolved_customers conflict "
            "WHERE conflict.generation_id=sb.generation_id AND conflict.project_id=sb.project_id "
            "AND conflict.role='conflicting_customer') "
            "AND strpos(lower(cm.organization_name),:term)>0) OR "
            "EXISTS (SELECT 1 FROM browse_unresolved_customers uc "
            "WHERE uc.generation_id=sb.generation_id AND uc.project_id=sb.project_id "
            "AND strpos(lower(uc.organization_name),:term)>0)) " + child_scope + ")) OR "
            f"{alias}.group_key IN (SELECT DISTINCT ga.group_key "
            "FROM assigned ga JOIN (" + member_asset_projects + ") gar "
            "ON gar.asset_key=ga.asset_key "
            "WHERE gar.project_id=ANY(CAST(:graph_alias_project_ids AS uuid[]))))"
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


def assignment_context(session, generation, shortlist: bool = False) -> dict[str, Any]:
    data = None
    from gridlens.intelligence.account_shortlist import assess_generation

    data = assess_generation(session, generation)
    need_alias_map = _current_need_alias_map(session, generation)
    from sqlalchemy import select

    from gridlens.persistence.commercial_pursuit_models import CommercialPursuit

    pursued_ids = (
        set(session.scalars(select(CommercialPursuit.need_id)).all())
        if data["eligible_need_ids"]
        else set()
    )

    def canonical(need_id):
        return need_alias_map.get(need_id, need_id)

    pursued_roots = {canonical(need_id) for need_id in pursued_ids}
    pursued_eligible_ids = [
        root
        for root in {canonical(need_id) for need_id in data["eligible_need_ids"]}
        if root in pursued_roots
    ]
    asset_params = {}
    if data:
        for index, (project_id, canonical) in enumerate(data["duplicate_project_map"].items()):
            asset_params[f"shortlist_duplicate_{index}"] = project_id
            asset_params[f"shortlist_canonical_{index}"] = str(canonical)
    return {
        "data": data,
        "eligible_need_ids": data["eligible_need_ids"] if data else [],
        "priority_map": json.dumps(
            {
                str(need): priority
                for need, priority in (data["priority_by_need"].items() if data else [])
            },
            separators=(",", ":"),
        ),
        "shortlist_enabled": bool(shortlist),
        "pursued_need_ids": pursued_eligible_ids,
        "need_alias_map": json.dumps(
            {str(alias): str(root) for alias, root in need_alias_map.items()},
            separators=(",", ":"),
        ),
        "asset_params": asset_params,
    }


def _ctes(where: str, shortlist_data=None) -> str:
    asset_expr = _ASSET_B
    if shortlist_data and shortlist_data["duplicate_project_map"]:
        duplicate_cases = " ".join(
            f"WHEN b.project_id = :shortlist_duplicate_{index} "
            f"THEN 'shortlist:' || CAST(:shortlist_canonical_{index} AS text)"
            for index in range(len(shortlist_data["duplicate_project_map"]))
        )
        asset_expr = f"CASE {duplicate_cases} ELSE ({_ASSET_B}) END"
    customer_roles = ",".join(f"'{role}'" for role in CUSTOMER_ROLE_ORDER)
    owner_roles = ",".join(f"'{role}'" for role in OWNER_ROLES)
    # Both relations use the same cohort predicate, so the asset self-join
    # cannot add rows beyond those already in matched.
    return (
        """
    WITH matched AS (
      SELECT %%ASSET%% AS asset_key, b.project_id, b.need_id,
             coalesce((CAST(:need_alias_map AS jsonb)->>b.need_id::text)::uuid, b.need_id)
               AS canonical_need_id,
             b.compact,
             b.rank_score, b.updated_at
      FROM browse_rows b WHERE %%WHERE%%
    ), candidate_assets AS (
      SELECT asset_key, min(project_id::text) AS anchor_project_id
      FROM matched GROUP BY asset_key
    ), all_rows AS (SELECT * FROM matched), assets AS (
      SELECT a.asset_key, c.anchor_project_id,
             count(DISTINCT canonical_need_id)::integer AS need_count,
             count(DISTINCT canonical_need_id) FILTER (
               WHERE need_id = ANY(CAST(:eligible_need_ids AS uuid[]))
             )::integer AS eligible_need_count,
             count(DISTINCT canonical_need_id) FILTER (
               WHERE canonical_need_id = ANY(CAST(:pursued_need_ids AS uuid[]))
             )::integer AS pursued_eligible_need_count,
             max(CASE WHEN :shortlist_enabled THEN
               coalesce((CAST(:priority_map AS jsonb)->>need_id::text)::integer, 0)
               ELSE rank_score END)::integer AS priority_score,
             max(updated_at) AS updated_at
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
    ), membership_candidates AS (
      SELECT DISTINCT r.asset_key, r.project_id,
             r.compact #>> '{project_metadata,sector}' AS sector,
             bcm.company_identity_id::text AS company_id,
             ci.rrc_operator_number, bcm.organization_name, bcm.role,
             array_position(ARRAY[%%CUSTOMER_ROLE_ORDER%%]::text[], bcm.role) AS role_priority
      FROM all_rows r JOIN browse_customer_memberships bcm
        ON bcm.generation_id = :generation AND bcm.project_id = r.project_id
      LEFT JOIN company_identities ci ON ci.id = bcm.company_identity_id
      WHERE bcm.role = ANY(ARRAY[%%CUSTOMER_ROLES%%]::text[])
    ), membership_project_roles AS (
      SELECT mc.*
      FROM membership_candidates mc
      WHERE CASE
        WHEN mc.sector = 'oil_gas' THEN
          CASE WHEN EXISTS (
            SELECT 1 FROM membership_candidates preferred
            WHERE preferred.project_id=mc.project_id AND preferred.role='asset_operator'
          ) THEN mc.role='asset_operator'
          ELSE mc.role = ANY(ARRAY[%%OWNER_ROLES%%]::text[]) END
        WHEN mc.sector = 'data_centers' THEN
          CASE WHEN EXISTS (
            SELECT 1 FROM membership_candidates preferred
            WHERE preferred.project_id=mc.project_id
              AND preferred.role = ANY(ARRAY[%%OWNER_ROLES%%]::text[])
          ) THEN mc.role = ANY(ARRAY[%%OWNER_ROLES%%]::text[])
          ELSE mc.role='asset_operator' END
        ELSE true
      END
    ), memberships AS (
      SELECT DISTINCT asset_key, company_id, rrc_operator_number,
             organization_name, role, role_priority
      FROM membership_project_roles
    ), membership_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) > 1
    ), single_membership AS (
      SELECT asset_key, min(company_id) AS company_id,
             min(rrc_operator_number) AS rrc_operator_number,
             (array_agg(organization_name ORDER BY role_priority, lower(organization_name),
                        organization_name))[1] AS organization_name,
             (array_agg(role ORDER BY role_priority, lower(organization_name),
                        organization_name))[1] AS role
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) = 1
    ), recorded_conflicts AS (
      SELECT r.asset_key, min(uc.organization_name) AS organization_name
      FROM all_rows r JOIN browse_unresolved_customers uc
        ON uc.generation_id = :generation AND uc.project_id = r.project_id
      WHERE uc.role = 'conflicting_customer'
      GROUP BY r.asset_key
    ), rrc_membership_conflicts AS (
      SELECT r.asset_key, min(sm.organization_name) AS organization_name
      FROM all_rows r JOIN single_membership sm ON sm.asset_key = r.asset_key
      WHERE lower(sm.role) LIKE '%operator%'
        AND nullif(r.compact #>> '{project_metadata,oil_gas,operator_number}', '')
              ~ '^[0-9]+$'
        AND sm.rrc_operator_number IS NOT NULL
        AND r.compact #>> '{project_metadata,oil_gas,operator_number}'
              <> sm.rrc_operator_number
      GROUP BY r.asset_key
    ), unresolved_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM (
        SELECT asset_key, organization_name FROM membership_conflicts
        UNION ALL
        SELECT asset_key, organization_name FROM recorded_conflicts
        UNION ALL
        SELECT asset_key, organization_name FROM rrc_membership_conflicts
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
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN 'rrc:' || sm.rrc_operator_number
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS group_key,
        CASE WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN 'rrc:' || sm.rrc_operator_number
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS identity_key,
        CASE WHEN uc.asset_key IS NOT NULL
             THEN coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                  'Unresolved project')
             WHEN nb.display_key IS NOT NULL THEN sm.organization_name
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN coalesce(nullif(r.operator_name, ''), sm.organization_name)
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
             WHEN sm.rrc_operator_number IS NOT NULL
               OR nullif(r.operator_number, '') ~ '^[0-9]+$' OR sm.company_id IS NOT NULL
               THEN 'resolved_identity'
             ELSE 'unresolved' END AS group_kind,
        coalesce(nullif(r.sector, ''), 'unknown') AS sector
      FROM assets a JOIN representatives r USING (asset_key)
      LEFT JOIN single_membership sm USING (asset_key)
      LEFT JOIN unresolved_conflicts uc USING (asset_key)
      LEFT JOIN same_name_bucket_assets nb USING (asset_key)
    ), eligible_assets AS (
      SELECT DISTINCT asset_key FROM all_rows
      WHERE need_id = ANY(CAST(:eligible_need_ids AS uuid[]))
    ), grouped_need_counts AS (
      SELECT a.group_key, count(DISTINCT ar.canonical_need_id)::integer AS need_count,
        count(DISTINCT ar.canonical_need_id) FILTER (
          WHERE ar.need_id = ANY(CAST(:eligible_need_ids AS uuid[]))
        )::integer AS eligible_need_count,
        count(DISTINCT ar.canonical_need_id) FILTER (
          WHERE ar.canonical_need_id = ANY(CAST(:pursued_need_ids AS uuid[]))
        )::integer AS pursued_eligible_need_count,
        bool_or(CASE WHEN jsonb_typeof(ar.compact->'contact_actions')='array'
          THEN jsonb_array_length(ar.compact->'contact_actions') > 0 ELSE false END)
          AS has_contact_actions
      FROM assigned a JOIN all_rows ar ON ar.asset_key=a.asset_key
      GROUP BY a.group_key
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
        count(*)::integer AS project_count,
        gnc.need_count, gnc.eligible_need_count, gnc.pursued_eligible_need_count,
        gnc.has_contact_actions,
        count(*) FILTER (
          WHERE asset_key IN (SELECT asset_key FROM eligible_assets)
        )::integer AS relevant_project_count,
        array_agg(DISTINCT sector ORDER BY sector) AS sectors,
        max(updated_at) AS updated_at
      FROM assigned JOIN grouped_need_counts gnc USING (group_key)
      GROUP BY group_key, gnc.need_count, gnc.eligible_need_count,
               gnc.pursued_eligible_need_count, gnc.has_contact_actions
    )
    """.replace("%%ASSET%%", asset_expr)
        .replace("%%WHERE%%", where)
        .replace("%%CUSTOMER_ROLE_ORDER%%", customer_roles)
        .replace("%%CUSTOMER_ROLES%%", customer_roles)
        .replace("%%OWNER_ROLES%%", owner_roles)
    )


def _group_id(key: str) -> str:
    return "cg_" + hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def _primary_contact_identity(row) -> str | None:
    if row.get("asset_group_kind", row.get("group_kind")) not in {
        "resolved_identity",
        "same_name_unconfirmed",
    }:
        return None
    return str(row["company_id"]) if row.get("company_id") is not None else None


def _account_contact_projects(
    session,
    *,
    generation,
    where: str,
    params: dict,
    shortlist_data,
    group_keys: list[str],
    sector: str,
    sort: str,
) -> dict[str, dict]:
    """Choose one live, primary-identity project contact for each resolved group.

    The scan is limited to retained project contact actions whose company UUID
    equals the assigned primary account identity. Suppression is rechecked in
    one batch before deterministic contact ranking; serialization rechecks it
    again at the response boundary.
    """
    if not group_keys:
        return {}
    shortlist_state = shortlist_data
    sql = _ctes(where, shortlist_state)
    candidate_rows = (
        session.execute(
            text(
                sql
                + """
              SELECT a.group_key, a.asset_key, a.company_id, a.group_kind,
                     a.priority_score, b.project_id, b.updated_at, b.compact,
                     ARRAY(SELECT ar2.project_id FROM all_rows ar2
                           WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id
                           ORDER BY ar2.project_id) AS asset_project_ids
              FROM assigned a
              JOIN all_rows ar ON ar.asset_key=a.asset_key
              JOIN browse_rows b ON b.generation_id=:generation
                AND b.project_id=ar.project_id AND b.need_id=ar.need_id
              WHERE a.group_key = ANY(CAST(:contact_group_keys AS text[]))
                AND a.group_kind='resolved_identity' AND a.company_id IS NOT NULL
                AND jsonb_typeof(b.compact->'contact_actions')='array'
                AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(b.compact->'contact_actions') action
                  WHERE action->>'company_identity_id'=a.company_id
                    AND action->>'kind' IN ('email','call')
                )
              ORDER BY a.group_key, a.asset_key, b.rank_score DESC,
                       b.updated_at DESC, b.project_id, b.need_id
            """
            ),
            {**params, "contact_group_keys": group_keys, "generation": generation.id},
        )
        .mappings()
        .all()
    )
    if not candidate_rows:
        return {}

    candidates: dict[int, dict] = {}
    contact_records: list[dict] = []
    for row in candidate_rows:
        primary_id = str(row["company_id"])
        actions = [
            action
            for action in ((row["compact"] or {}).get("contact_actions") or [])
            if str(action.get("company_identity_id") or "") == primary_id
            and action.get("kind") in {"email", "call"}
        ]
        if not actions:
            continue
        candidates[id(row)] = {"row": row, "actions": actions}
        contact_records.extend(actions)
    if not candidates:
        return {}

    from gridlens.intelligence.project_contact_actions import filter_project_contact_records

    allowed_ids = {
        id(record) for record in filter_project_contact_records(session, contact_records)
    }
    by_asset: dict[tuple[str, str], dict] = {}
    for candidate in candidates.values():
        row = candidate["row"]
        actions = [action for action in candidate["actions"] if id(action) in allowed_ids]
        if not actions:
            continue
        for action in actions:
            kind = str(action.get("kind") or "")
            href = str(action.get("href") or "")
            try:
                from gridlens.intelligence.project_contact_actions import _safe_href

                safe_href = _safe_href(href, kind)
            except (TypeError, ValueError):
                safe_href = None
            if not safe_href:
                continue
            responsibility = action.get("responsibility")
            responsibility_rank = {
                "Verified project responsibility": 0,
                "Verified organizational responsibility": 1,
                "Inferred likely role": 2,
                "General company contact path": 3,
            }.get(responsibility, 4)
            quality = (
                responsibility_rank,
                not bool(action.get("name")),
                not bool(action.get("title")),
                0 if kind == "email" else 1,
                -int(row["priority_score"] or 0),
                -(row["updated_at"].timestamp() if row["updated_at"] else 0),
                str(row["project_id"]),
            )
            key = (str(row["group_key"]), str(row["asset_key"]))
            prior = by_asset.get(key)
            if prior is None or quality < prior["quality"]:
                by_asset[key] = {"row": row, "quality": quality}

    best_by_group: dict[str, dict] = {}
    for (group_key, _asset_key), candidate in by_asset.items():
        prior = best_by_group.get(group_key)
        if prior is None or candidate["quality"] < prior["quality"]:
            best_by_group[group_key] = candidate
    if not best_by_group:
        return {}

    chosen = {key: value["row"] for key, value in best_by_group.items()}
    project_ids = list(dict.fromkeys(row["project_id"] for row in chosen.values()))
    primary_ids_by_project: dict[str, str | None] = {
        str(project_id): str(row["company_id"])
        for row in chosen.values()
        for project_id in row["asset_project_ids"]
    }
    page = project_page(
        session,
        sector=sector,
        limit=max(1, len(project_ids)),
        offset=0,
        sort={"priority_asc": "priority_asc", "company": "company", "updated": "updated"}.get(
            sort, "priority"
        ),
        include_signals=True,
        project_ids=project_ids,
        selected_generation=generation,
        primary_customer_ids_by_project=primary_ids_by_project,
    )
    result: dict[str, dict] = {}
    for item in page["items"]:
        candidate_group = next(
            (
                group_key
                for group_key, row in chosen.items()
                if str(row["project_id"]) in item["project_ids"]
            ),
            None,
        )
        if candidate_group and item.get("contact"):
            item["customer_identity_id"] = str(chosen[candidate_group]["company_id"])
            result[candidate_group] = item
    return result


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
    shortlist=False,
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
        shortlist=shortlist,
    )
    _validate_token(token, cohort, offset)
    _disable_jit_for_search(session, term)
    # Search qualifies whole groups below; keep every member in the aggregate
    # so counts and child serialization remain complete when one project hits.
    where, params = _query_parts(generation, "", sector)
    order = {
        "priority": "priority_score DESC NULLS LAST, name, group_key",
        "priority_asc": "priority_score ASC NULLS LAST, name, group_key",
        "company": "lower(name), group_key",
        "updated": "updated_at DESC NULLS LAST, group_key",
    }[sort]
    selected, selected_params = _group_filter(
        term=term,
        region=region,
        stage=stage,
        priority=priority,
        session=session,
        generation=generation,
    )
    selected_totals, totals_params = _group_filter(
        term=term,
        region=region,
        stage=stage,
        priority=priority,
        alias="g2",
        session=session,
        generation=generation,
    )
    params.update(selected_params)
    params.update(totals_params)
    params["generation"] = generation.id
    shortlist_state = assignment_context(session, generation, shortlist)
    params.update(
        {
            key: shortlist_state[key]
            for key in (
                "eligible_need_ids",
                "priority_map",
                "shortlist_enabled",
                "pursued_need_ids",
                "need_alias_map",
            )
        }
    )
    params.update(shortlist_state["asset_params"])
    sql = _ctes(where, shortlist_state["data"])
    rows = (
        session.execute(
            text(
                sql
                + " SELECT g.*, count(*) OVER() AS total, "
                + "count(*) FILTER (WHERE g.group_kind='resolved_identity') "
                + "OVER() AS account_total, "
                + "coalesce(sum(g.project_count) OVER(),0) AS project_total, "
                + "(SELECT count(DISTINCT ar.canonical_need_id) "
                + "FROM assigned na JOIN all_rows ar ON ar.asset_key=na.asset_key "
                + "WHERE na.group_key IN (SELECT g2.group_key FROM grouped g2 WHERE "
                + selected_totals
                + (
                    " AND g2.group_kind='resolved_identity' AND g2.relevant_project_count>0"
                    if shortlist
                    else ""
                )
                + ")) AS need_total FROM grouped g WHERE "
                + selected
                + (
                    " AND g.group_kind='resolved_identity' AND g.relevant_project_count > 0"
                    if shortlist
                    else ""
                )
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
        totals = {
            "accounts": rows[0]["account_total"],
            "projects": rows[0]["project_total"],
            "needs": rows[0]["need_total"],
        }
    else:
        # An empty page may be out of range or an empty cohort. Keep the count
        # query for this uncommon case so totals remain exact.
        aggregate = (
            session.execute(
                text(
                    sql
                    + " SELECT count(*) AS total, "
                    + "count(*) FILTER (WHERE g.group_kind='resolved_identity') AS accounts, "
                    + "coalesce(sum(g.project_count),0) AS projects, "
                    + "(SELECT count(DISTINCT ar.canonical_need_id) "
                    + "FROM assigned na JOIN all_rows ar ON ar.asset_key=na.asset_key "
                    + "WHERE na.group_key IN (SELECT g2.group_key FROM grouped g2 WHERE "
                    + selected_totals
                    + (
                        " AND g2.group_kind='resolved_identity' AND g2.relevant_project_count>0"
                        if shortlist
                        else ""
                    )
                    + ")) AS needs "
                    + "FROM grouped g WHERE "
                    + selected
                    + (
                        " AND g.group_kind='resolved_identity' AND g.relevant_project_count > 0"
                        if shortlist
                        else ""
                    )
                ),
                params,
            )
            .mappings()
            .one()
        )
        total = aggregate["total"]
        totals = {
            "accounts": aggregate["accounts"],
            "projects": aggregate["projects"],
            "needs": aggregate["needs"],
        }
    items = [
        {
            "id": _group_id(row["group_key"]),
            "name": row["name"],
            "role": row["role"],
            "group_kind": row["group_kind"],
            "identity_count": row["identity_count"],
            "project_count": row["project_count"],
            "need_count": row["need_count"],
            "relevant_project_count": row.get("relevant_project_count", 0),
            "total_known_project_count": row["project_count"],
            "eligible_need_count": row["eligible_need_count"],
            "pursued_eligible_need_count": row["pursued_eligible_need_count"],
            "matched_project_id": None,
            "matched_need_id": None,
            "priority_score": row["priority_score"],
            "sectors": row["sectors"],
        }
        for row in rows
    ]
    if shortlist and items:
        page_group_ids = [item["id"] for item in items]
        featured_rows = (
            session.execute(
                text(
                    _ctes(where, shortlist_state["data"])
                    + """
                SELECT DISTINCT ON (a.group_key) a.group_key, ar.project_id AS anchor_project_id,
                       a.asset_key, a.company_id, a.group_kind,
                       ARRAY(SELECT ar2.project_id FROM all_rows ar2
                             WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id
                             ORDER BY ar2.project_id) AS asset_project_ids
                FROM assigned a JOIN all_rows ar USING (asset_key)
                WHERE 'cg_' || md5(a.group_key) = ANY(CAST(:page_group_ids AS text[]))
                  AND ar.need_id = ANY(CAST(:eligible_need_ids AS uuid[]))
                ORDER BY a.group_key,
                         coalesce((CAST(:priority_map AS jsonb)->>ar.need_id::text)::integer, 0)
                           DESC, ar.updated_at DESC NULLS LAST, ar.project_id
                """
                ),
                {**params, "page_group_ids": page_group_ids},
            )
            .mappings()
            .all()
        )
        anchors = [UUID(str(row["anchor_project_id"])) for row in featured_rows]
        featured_primary_ids = {
            str(project_id): _primary_contact_identity(row)
            for row in featured_rows
            for project_id in row["asset_project_ids"]
        }
        featured_results = (
            project_page(
                session,
                search=None,
                sector=sector,
                limit=max(1, len(anchors)),
                offset=0,
                sort=sort,
                shortlist=True,
                include_signals=True,
                project_ids=anchors,
                selected_generation=generation,
                primary_customer_ids_by_project=featured_primary_ids,
            )
            if anchors
            else {"items": []}
        )
        featured_by_anchor = {
            project_id: featured
            for featured in featured_results["items"]
            for project_id in featured["project_ids"]
        }
        group_by_key = {_group_id(row["group_key"]): row for row in rows}
        for item in items:
            key = group_by_key[item["id"]]["group_key"]
            anchor = next(
                (
                    UUID(str(row["anchor_project_id"]))
                    for row in featured_rows
                    if row["group_key"] == key
                ),
                None,
            )
            item["featured_project"] = featured_by_anchor.get(str(anchor)) if anchor else None
    if term and items:
        matched_rows = (
            session.execute(
                text(
                    _ctes(where, shortlist_state["data"])
                    + """
                SELECT DISTINCT ON (a.group_key) a.group_key, b.project_id, b.need_id
                FROM assigned a
                JOIN all_rows ar ON ar.asset_key=a.asset_key
                JOIN browse_rows b ON b.generation_id=:generation
                  AND b.project_id=ar.project_id AND b.need_id=ar.need_id
                WHERE 'cg_' || md5(a.group_key) = ANY(CAST(:page_group_ids AS text[]))
                  AND (strpos(b.search_text,:term)>0
                    OR strpos(lower(coalesce(b.compact->>'browse_title','')),:term)>0
                    OR strpos(lower(coalesce(b.compact->>'name','')),:term)>0
                    OR strpos(lower(coalesce(b.compact #>> '{project_metadata,title}','')),:term)>0
                    OR strpos(lower(coalesce(b.compact #>> '{project_metadata,name}','')),:term)>0
                    OR strpos(lower(coalesce(
                      b.compact #>> '{project_metadata,operator}','')),:term)>0)
                  AND (CAST(:region AS text) IS NULL OR
                       b.compact->>'location'=CAST(:region AS text))
                  AND (CAST(:stage AS text) IS NULL OR
                       b.compact #>> '{project_metadata,event,kind}'=CAST(:stage AS text))
                ORDER BY a.group_key, b.rank_score DESC, b.updated_at DESC, b.need_id
                """
                ),
                {
                    **params,
                    "page_group_ids": [item["id"] for item in items],
                    "term": term,
                    "region": region,
                    "stage": stage,
                },
            )
            .mappings()
            .all()
        )
        by_group = {item["id"]: item for item in items}
        for match in matched_rows:
            item = by_group.get(_group_id(match["group_key"]))
            if item is not None:
                item["matched_project_id"] = str(match["project_id"])
                item["matched_need_id"] = str(match["need_id"])
    account_contact_by_group = (
        _account_contact_projects(
            session,
            generation=generation,
            where=where,
            params=params,
            shortlist_data=shortlist_state["data"],
            group_keys=[row["group_key"] for row in rows],
            sector=sector,
            sort=sort,
        )
        if any(row["has_contact_actions"] for row in rows)
        else {}
    )
    for item, row in zip(items, rows, strict=True):
        item["account_contact_project"] = account_contact_by_group.get(row["group_key"])
    return {
        "items": items,
        "count_unit": "groups",
        "total": total,
        "totals": totals,
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
    shortlist=False,
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
        shortlist=shortlist,
    )
    where, params = _query_parts(generation, "", sector)
    shortlist_state = assignment_context(session, generation, shortlist)
    params.update(
        {
            key: shortlist_state[key]
            for key in (
                "eligible_need_ids",
                "priority_map",
                "shortlist_enabled",
                "pursued_need_ids",
                "need_alias_map",
            )
        }
    )
    params.update(shortlist_state["asset_params"])
    sql = _ctes(where, shortlist_state["data"])
    selected, selected_params = _group_filter(
        term=term,
        region=region,
        stage=stage,
        priority=priority,
        session=session,
        generation=generation,
    )
    row = (
        session.execute(
            text(
                sql
                + """
                SELECT group_key, name, role, group_kind, identity_count, project_count,
                       relevant_project_count, eligible_need_count,
                       pursued_eligible_need_count, need_count,
                       priority_score, sectors
                FROM grouped g WHERE 'cg_' || md5(group_key) = :id AND """
                + selected
                + (
                    " AND group_kind='resolved_identity' AND relevant_project_count>0"
                    if shortlist
                    else ""
                )
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
        "relevant_project_count": row["relevant_project_count"],
        "total_known_project_count": row["project_count"],
        "eligible_need_count": row["eligible_need_count"],
        "pursued_eligible_need_count": row["pursued_eligible_need_count"],
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
    shortlist=False,
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
        shortlist=shortlist,
    )
    if parent_token is None:
        raise HTTPException(422, "parent_cohort_token is required for customer projects")
    if parent_token != cohort:
        raise HTTPException(409, "Customer cohort changed; restart pagination")
    group_token = cohort + ".group." + hashlib.sha256(group_id.encode()).hexdigest()[:16]
    _validate_token(token, group_token, offset)
    _disable_jit_for_search(session, term)
    where, params = _query_parts(generation, "", sector)
    shortlist_state = assignment_context(session, generation, shortlist)
    params.update(
        {
            key: shortlist_state[key]
            for key in (
                "eligible_need_ids",
                "priority_map",
                "shortlist_enabled",
                "pursued_need_ids",
                "need_alias_map",
            )
        }
    )
    params.update(shortlist_state["asset_params"])
    sql = _ctes(where, shortlist_state["data"])
    # Resolve the opaque group id using built-in PostgreSQL md5 and collect only
    # the requested asset page's anchor project IDs for the shared serializer.
    child_order = {
        "priority": "a.priority_score DESC NULLS LAST, a.updated_at DESC NULLS LAST",
        "priority_asc": "a.priority_score ASC NULLS LAST, a.updated_at DESC NULLS LAST",
        "company": "lower(a.group_name), a.asset_key",
        "updated": "a.updated_at DESC NULLS LAST",
    }[sort]
    selected, selected_params = _group_filter(
        term=term,
        region=region,
        stage=stage,
        priority=priority,
        alias="a",
        session=session,
        generation=generation,
    )
    params.update(selected_params)
    params["generation"] = generation.id
    rows = (
        session.execute(
            text(
                sql
                + f"""
          SELECT a.anchor_project_id, a.asset_key, a.company_id, a.group_name, a.group_role,
                 ARRAY(SELECT ar2.project_id FROM all_rows ar2
                       WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id
                       ORDER BY ar2.project_id) AS asset_project_ids,
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
    primary_ids_by_project = {
        str(project_id): _primary_contact_identity(row)
        for row in rows
        for project_id in row["asset_project_ids"]
    }
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
            canonical_assets=True,
            selected_generation=generation,
            primary_customer_ids_by_project=primary_ids_by_project,
        )
        if project_ids
        else {"items": [], "generation": str(generation.id)}
    )
    customer_identity_by_anchor = {str(row["anchor_project_id"]): row["company_id"] for row in rows}
    eligible_ids_by_project: dict[str, list[str]] = {}
    if shortlist_state["data"]:
        eligible_set = {str(need_id) for need_id in shortlist_state["eligible_need_ids"]}
        for source_row in shortlist_state["data"]["rows"]:
            need_id = str(source_row["need_id"])
            if need_id in eligible_set:
                eligible_ids_by_project.setdefault(str(source_row["project_id"]), []).append(
                    need_id
                )
    for item in serialized["items"]:
        item["customer_identity_id"] = next(
            (
                customer_identity_by_anchor[project_id]
                for project_id in item["project_ids"]
                if project_id in customer_identity_by_anchor
            ),
            None,
        )
        item["eligible_need_ids"] = sorted(
            {
                need_id
                for project_id in item["project_ids"]
                for need_id in eligible_ids_by_project.get(project_id, [])
            }
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


def group_open(
    session,
    group_id: str,
    *,
    search=None,
    sector="all",
    limit=25,
    sort="priority",
    region=None,
    stage=None,
    priority=None,
    selected_generation=None,
    shortlist=False,
):
    """Load a group header and its first project page in one cohort pass."""
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
        shortlist=shortlist,
    )
    _disable_jit_for_search(session, term)

    # Build assignments for the complete sector cohort. Search, region, and
    # stage then qualify the group independently through member keysets;
    # they do not trim the group before its full child list is paginated.
    where, params = _query_parts(generation, "", sector)
    shortlist_state = assignment_context(session, generation, shortlist)
    params.update(
        {
            key: shortlist_state[key]
            for key in (
                "eligible_need_ids",
                "priority_map",
                "shortlist_enabled",
                "pursued_need_ids",
                "need_alias_map",
            )
        }
    )
    params.update(shortlist_state["asset_params"])
    selected, selected_params = _group_filter(
        term=term,
        region=region,
        stage=stage,
        priority=priority,
        session=session,
        generation=generation,
    )
    params.update(selected_params)
    params.update({"generation": generation.id, "id": group_id, "limit": limit})
    child_order = {
        "priority": "a.priority_score DESC NULLS LAST, a.updated_at DESC NULLS LAST",
        "priority_asc": "a.priority_score ASC NULLS LAST, a.updated_at DESC NULLS LAST",
        "company": "lower(a.group_name), a.asset_key",
        "updated": "a.updated_at DESC NULLS LAST, a.asset_key",
    }[sort]
    rows = (
        session.execute(
            text(
                _ctes(where, shortlist_state["data"])
                + f"""
          SELECT g.group_key, g.name, g.role, g.group_kind, g.identity_count,
                 g.project_count, g.relevant_project_count, g.eligible_need_count,
                 g.pursued_eligible_need_count,
                 g.need_count, g.has_contact_actions,
                 g.priority_score, g.sectors,
                 a.anchor_project_id, a.asset_key, a.company_id, a.group_name,
                 ARRAY(SELECT ar2.project_id FROM all_rows ar2
                       WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id
                       ORDER BY ar2.project_id) AS asset_project_ids,
                 a.group_role, a.group_kind AS asset_group_kind,
                 a.identity_count AS asset_identity_count,
                 a.priority_score AS asset_priority_score, a.need_count AS asset_need_count,
                 a.sector AS asset_sector, a.updated_at AS asset_updated_at,
                 count(*) OVER() AS child_total
          FROM grouped g JOIN assigned a ON a.group_key = g.group_key
          WHERE 'cg_' || md5(g.group_key) = :id AND {selected}
            {
                    "AND g.group_kind='resolved_identity' AND g.relevant_project_count>0"
                    if shortlist
                    else ""
                }
          ORDER BY {child_order}, a.asset_key
          LIMIT :limit
        """
            ),
            params,
        )
        .mappings()
        .all()
    )
    if not rows:
        raise HTTPException(404, "Customer group not found in this cohort")

    project_ids = [UUID(row["anchor_project_id"]) for row in rows]
    primary_ids_by_project = {
        str(project_id): _primary_contact_identity(row)
        for row in rows
        for project_id in row["asset_project_ids"]
    }
    serialized = project_page(
        session,
        search=None,
        sector=sector,
        limit=max(1, len(project_ids)),
        offset=0,
        sort=sort,
        include_signals=True,
        project_ids=project_ids,
        canonical_assets=True,
        selected_generation=generation,
        primary_customer_ids_by_project=primary_ids_by_project,
    )
    customer_identity_by_anchor = {str(row["anchor_project_id"]): row["company_id"] for row in rows}
    eligible_ids_by_project: dict[str, list[str]] = {}
    if shortlist_state["data"]:
        eligible_set = {str(need_id) for need_id in shortlist_state["eligible_need_ids"]}
        for source_row in shortlist_state["data"]["rows"]:
            need_id = str(source_row["need_id"])
            if need_id in eligible_set:
                eligible_ids_by_project.setdefault(str(source_row["project_id"]), []).append(
                    need_id
                )
    for item in serialized["items"]:
        item["customer_identity_id"] = next(
            (
                customer_identity_by_anchor[project_id]
                for project_id in item["project_ids"]
                if project_id in customer_identity_by_anchor
            ),
            None,
        )
        item["eligible_need_ids"] = sorted(
            {
                need_id
                for project_id in item["project_ids"]
                for need_id in eligible_ids_by_project.get(project_id, [])
            }
        )

    first = rows[0]
    matched_project_id = None
    matched_need_id = None
    if term:
        matched = (
            session.execute(
                text(
                    _ctes(where, shortlist_state["data"])
                    + """
                SELECT b.project_id, b.need_id FROM assigned a
                JOIN all_rows ar ON ar.asset_key=a.asset_key
                JOIN browse_rows b ON b.generation_id=:generation
                  AND b.project_id=ar.project_id AND b.need_id=ar.need_id
                WHERE 'cg_' || md5(a.group_key)=:id
                  AND (CAST(:region AS text) IS NULL OR
                       b.compact->>'location'=CAST(:region AS text))
                  AND (CAST(:stage AS text) IS NULL OR
                       b.compact #>> '{project_metadata,event,kind}'=CAST(:stage AS text))
                  AND (strpos(b.search_text,:term)>0
                    OR strpos(lower(coalesce(b.compact->>'browse_title','')),:term)>0
                    OR strpos(lower(coalesce(b.compact->>'name','')),:term)>0
                    OR strpos(lower(coalesce(b.compact #>> '{project_metadata,title}','')),:term)>0
                    OR strpos(lower(coalesce(b.compact #>> '{project_metadata,name}','')),:term)>0
                    OR strpos(lower(coalesce(
                      b.compact #>> '{project_metadata,operator}','')),:term)>0)
                ORDER BY b.rank_score DESC, b.updated_at DESC, b.need_id LIMIT 1
                """
                ),
                {**params, "term": term, "region": region, "stage": stage},
            )
            .mappings()
            .first()
        )
        if matched:
            matched_project_id = str(matched["project_id"])
            matched_need_id = str(matched["need_id"])
    featured_project = None
    if shortlist and first["relevant_project_count"]:
        featured_anchor = (
            session.execute(
                text(
                    _ctes(where, shortlist_state["data"])
                    + """
              SELECT ar.project_id, a.company_id, a.group_kind,
                     ARRAY(SELECT ar2.project_id FROM all_rows ar2
                           WHERE ar2.asset_key=a.asset_key GROUP BY ar2.project_id
                           ORDER BY ar2.project_id) AS asset_project_ids
              FROM assigned a JOIN all_rows ar ON ar.asset_key=a.asset_key
              WHERE 'cg_' || md5(a.group_key)=:id
                AND ar.need_id = ANY(CAST(:eligible_need_ids AS uuid[]))
              ORDER BY coalesce((CAST(:priority_map AS jsonb)->>ar.need_id::text)::integer, 0)
                       DESC, ar.updated_at DESC NULLS LAST, ar.project_id LIMIT 1
            """
                ),
                {**params, "id": group_id},
            )
            .mappings()
            .first()
        )
        if featured_anchor:
            featured_result = project_page(
                session,
                search=None,
                sector=sector,
                limit=1,
                offset=0,
                sort=sort,
                shortlist=True,
                include_signals=True,
                project_ids=[UUID(str(featured_anchor["project_id"]))],
                selected_generation=generation,
                primary_customer_ids_by_project={
                    str(project_id): _primary_contact_identity(featured_anchor)
                    for project_id in featured_anchor["asset_project_ids"]
                },
            )
            featured_project = next(iter(featured_result["items"]), None)

    group = {
        "id": _group_id(first["group_key"]),
        "name": first["name"],
        "role": first["role"],
        "group_kind": first["group_kind"],
        "identity_count": first["identity_count"],
        "project_count": first["project_count"],
        "need_count": first["need_count"],
        "relevant_project_count": first["relevant_project_count"],
        "total_known_project_count": first["project_count"],
        "eligible_need_count": first["eligible_need_count"],
        "pursued_eligible_need_count": first["pursued_eligible_need_count"],
        "matched_project_id": matched_project_id,
        "matched_need_id": matched_need_id,
        "priority_score": first["priority_score"],
        "sectors": first["sectors"],
    }
    if shortlist:
        group["featured_project"] = featured_project
    contact_projects = (
        _account_contact_projects(
            session,
            generation=generation,
            where=where,
            params=params,
            shortlist_data=shortlist_state["data"],
            group_keys=[first["group_key"]],
            sector=sector,
            sort=sort,
        )
        if first["has_contact_actions"]
        else {}
    )
    group["account_contact_project"] = contact_projects.get(first["group_key"])
    group_token = cohort + ".group." + hashlib.sha256(group_id.encode()).hexdigest()[:16]
    projects = {
        "items": serialized["items"],
        "count_unit": "projects",
        "total": first["child_total"],
        "limit": limit,
        "offset": 0,
        "cohort_token": group_token,
        "generation": str(generation.id),
        **_snapshot_metadata(generation),
    }
    return {
        "group": group,
        "projects": projects,
        "parent_cohort_token": cohort,
        "generation": str(generation.id),
    }
