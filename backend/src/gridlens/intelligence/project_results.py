"""Project-first reads over the immutable saved browse generation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.domain.opportunity_shortlist import POLICY_VERSION
from gridlens.intelligence.saved_browse import current_generation
from gridlens.intelligence.saved_browse import refresh_state as _refresh_state
from gridlens.intelligence.saved_history_privacy import (
    _redact_all_contact_tokens,
    project_saved_history_privacy,
)
from gridlens.intelligence.signal_adjudication import POLICY_VERSION as SIGNAL_POLICY_VERSION
from gridlens.settings import settings


def _contains_identity_pointer(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key in value for key in ("claim_id", "company_identity_id", "person_identity_id")):
            return True
        return any(_contains_identity_pointer(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_identity_pointer(child) for child in value)
    return False


def _representative_need(item: dict[str, Any]) -> dict[str, Any]:
    """Return the uniquely identified representative need, never a sibling fallback."""
    representative_id = item.get("representative_need_id")
    if representative_id is None:
        return {}
    matches = [
        need
        for need in item.get("needs", [])
        if isinstance(need, dict) and str(need.get("id")) == str(representative_id)
    ]
    return matches[0] if len(matches) == 1 else {}


def _current_jev_decisions(session, evidence_ids: list[str]) -> dict[str, str]:
    """Return only pinned Jev decisions for each exact current demand evidence version."""
    if not evidence_ids:
        return {}
    rows = (
        session.execute(
            text(
                """SELECT DISTINCT ON (e.id) e.id, sd.decision, sd.source,
                      sd.model_version, sd.policy_version, sd.dimensions
               FROM evidence e
               JOIN observations o ON o.id = e.observation_id
               JOIN signal_decisions sd
                 ON sd.observation_id = e.observation_id
                AND sd.content_hash = e.content_hash
               WHERE e.id = ANY(CAST(:evidence_ids AS uuid[]))
                 AND e.content_hash = o.content_hash
                 AND sd.policy_version = :policy_version
                 AND sd.source = 'jev'
                 AND sd.model_version = :model_version
                 AND sd.dimensions->>'question_set' = 'demand-v1'
                 AND sd.decision IN ('SHOW', 'HOLD', 'REVIEW')
               ORDER BY e.id, sd.id DESC"""
            ),
            {
                "evidence_ids": evidence_ids,
                "policy_version": SIGNAL_POLICY_VERSION,
                "model_version": settings.jev_model,
            },
        )
        .mappings()
        .all()
    )
    decisions: dict[str, str] = {}
    for row in rows:
        decisions[str(row["id"])] = row["decision"]
    return decisions


def page(
    session,
    *,
    search: str | None = None,
    sector: str = "all",
    limit: int = 50,
    offset: int = 0,
    token: str | None = None,
    sort: str = "priority",
    need_id: UUID | None = None,
    include_signals: bool = False,
    shortlist: bool = False,
    project_ids: list[UUID] | None = None,
    canonical_assets: bool = False,
    selected_generation=None,
    primary_customer_ids_by_project: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return physical projects, consolidating only validated well API identities."""
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    if sort not in {"priority", "priority_asc", "company", "project", "updated"}:
        raise HTTPException(422, "Unsupported project sort")
    generation = selected_generation or current_generation(session)
    term = (search or "").strip().casefold()
    source_rows: list[Any] = []
    shortlist_data = None
    if shortlist or canonical_assets:
        # Freeze the exact effective Jev map before validating pagination.
        # This avoids MAX(id) races (IDs can commit out of order) and ensures
        # this request assesses exactly the decisions represented by its token.
        from gridlens.intelligence.account_shortlist import assess_generation

        shortlist_data = assess_generation(session, generation)
        source_rows = shortlist_data["rows"]
        jev_map_digest = shortlist_data["jev_map_digest"]
    else:
        jev_map_digest = None
    cohort_payload = [
        str(generation.id),
        generation.digest,
        sector,
        sort,
        term,
        str(need_id or ""),
        include_signals,
        shortlist,
        canonical_assets,
        POLICY_VERSION if shortlist or canonical_assets else None,
        jev_map_digest if shortlist or canonical_assets else None,
        date.today().isoformat() if shortlist or canonical_assets else None,
        sorted(str(value) for value in project_ids or []),
    ]
    cohort_digest = hashlib.sha256(
        json.dumps(cohort_payload, separators=(",", ":")).encode()
    ).hexdigest()
    cohort = f"p1_{cohort_digest}"
    if token and token != cohort:
        raise HTTPException(409, "Project cohort changed; restart pagination")
    if offset and not token:
        raise HTTPException(422, "cohort_token is required when offset is greater than zero")

    filters = ["generation_id = :generation"]
    params: dict[str, Any] = {
        "generation": generation.id,
        "term": term,
        "limit": limit,
        "offset": min(offset, generation.row_count),
        "selected_need": need_id,
    }
    if need_id is not None and not shortlist:
        filters.append("need_id = :need_id")
        params["need_id"] = need_id
    if project_ids:
        filters.append("project_id = ANY(CAST(:project_ids AS uuid[]))")
        params["project_ids"] = project_ids
    if term:
        filters.append(
            "(strpos(search_text, :term) > 0 OR "
            "strpos(lower(coalesce(compact->>'browse_title','')), :term) > 0 OR "
            "strpos(lower(coalesce(compact->>'name','')), :term) > 0)"
        )
    if sector == "oil_gas":
        filters.append("compact #>> '{project_metadata,sector}' = 'oil_gas'")
    elif sector == "data_centers":
        filters.append("compact #>> '{project_metadata,sector}' = 'data_centers'")
    discovery = bool(term or sector != "all" or need_id is not None or include_signals or shortlist)
    if not discovery:
        # A useful contact route does not qualify an unsupported permit Signal.
        # Search and explicit sector exploration retain those early discoveries.
        filters.append("tier IN ('Prospect', 'Lead')")
    if shortlist:
        # Source assessment runs over the entire filtered generation below;
        # eligible need ids then constrain this SQL cohort before counting/page.
        pass
    where = " AND ".join(filters)
    eligible_need_ids: list[UUID] = []
    shortlist_by_need: dict[str, dict[str, Any]] = {}
    shortlist_priority_by_need: dict[UUID, int] = {}
    if shortlist:
        assert shortlist_data is not None
        # Build eligibility and duplicate lineage against the full generation,
        # so search/sector/detail filters cannot split one physical project into
        # unstable public groups or omit its other source references.
        shortlist_by_need = shortlist_data["assessments"]
        eligible_need_ids = shortlist_data["eligible_need_ids"]
        shortlist_priority_by_need = shortlist_data["priority_by_need"]
        filters.append("need_id = ANY(CAST(:shortlist_need_ids AS uuid[]))")
        params["shortlist_need_ids"] = eligible_need_ids
        params["eligible_need_ids"] = eligible_need_ids
        if need_id is not None:
            target = next((row for row in source_rows if row["need_id"] == need_id), None)
            if target is None:
                params["shortlist_scope_project_ids"] = []
            else:
                target_project = target["project_id"]
                target_duplicate = shortlist_by_need[str(need_id)].get("duplicate_key")
                scope_projects = {
                    row["project_id"]
                    for row in source_rows
                    if row["project_id"] == target_project
                    or (
                        target_duplicate
                        and shortlist_by_need[str(row["need_id"])].get("duplicate_key")
                        == target_duplicate
                    )
                }
                params["shortlist_scope_project_ids"] = sorted(scope_projects, key=str)
            filters.append("project_id = ANY(CAST(:shortlist_scope_project_ids AS uuid[]))")
        where = " AND ".join(filters)
    # Exact retained-source duplicate groups are only applied in shortlist mode;
    # the full All Projects view keeps every canonical project unchanged.
    duplicate_project_map: dict[UUID, UUID] = {}
    if shortlist or canonical_assets:
        assert shortlist_data is not None
        duplicate_project_map = shortlist_data["duplicate_project_map"]
        params["shortlist_dup_ids"] = list(duplicate_project_map)
    # Only a validated, canonical U.S. well API number may consolidate separate
    # permit Projects. Every other row retains its own canonical project id.
    duplicate_case = (
        "CASE "
        + " ".join(
            f"WHEN project_id = :duplicate_{index} "
            f"THEN 'shortlist:' || CAST(:canonical_{index} AS text)"
            for index, (project_id, canonical) in enumerate(duplicate_project_map.items())
        )
        + " ELSE NULL END"
    )
    for index, (project_id, canonical) in enumerate(duplicate_project_map.items()):
        params[f"duplicate_{index}"] = project_id
        params[f"canonical_{index}"] = str(canonical)
    asset_key = (
        """CASE
        WHEN :shortlist_dedupe_enabled AND project_id = ANY(CAST(:shortlist_dup_ids AS uuid[]))
         THEN """
        + duplicate_case
        + """
        WHEN compact #>> '{project_metadata,asset_identity,kind}' = 'us_well_api'
         AND compact #>> '{project_metadata,asset_identity,identity_validated}' = 'true'
         AND compact #>> '{project_metadata,asset_identity,value}' ~ '^[0-9]{10}([0-9]{2}){0,2}$'
        THEN 'api:' || (compact #>> '{project_metadata,asset_identity,value}')
        ELSE 'project:' || project_id::text END"""
    )
    params["shortlist_dedupe_enabled"] = bool(
        (shortlist or canonical_assets) and duplicate_project_map
    )
    if not (shortlist or canonical_assets) or not duplicate_project_map:
        # Avoid array bind or generated CASE references in the compatibility path.
        asset_key = """CASE
        WHEN compact #>> '{project_metadata,asset_identity,kind}' = 'us_well_api'
         AND compact #>> '{project_metadata,asset_identity,identity_validated}' = 'true'
         AND compact #>> '{project_metadata,asset_identity,value}' ~ '^[0-9]{10}([0-9]{2}){0,2}$'
        THEN 'api:' || (compact #>> '{project_metadata,asset_identity,value}')
        ELSE 'project:' || project_id::text END"""
    asset_key_b = asset_key.replace("compact", "b.compact").replace("project_id", "b.project_id")
    if shortlist and shortlist_priority_by_need:
        priority_case = (
            "CASE "
            + " ".join(
                f"WHEN b.need_id = :shortlist_priority_{index} THEN {score}"
                for index, (need_id, score) in enumerate(shortlist_priority_by_need.items())
            )
            + " ELSE 0 END"
        )
        for index, need_id in enumerate(shortlist_priority_by_need):
            params[f"shortlist_priority_{index}"] = need_id
        priority_projection = f"max({priority_case})::integer AS priority_score"
        representative_priority = f"{priority_case} DESC, "
    elif shortlist:
        priority_projection = "0::integer AS priority_score"
        representative_priority = ""
    else:
        priority_projection = "max(b.rank_score)::integer AS priority_score"
        representative_priority = ""
    order = {
        "priority": "priority_score DESC NULLS LAST, updated_at DESC NULLS LAST, asset_key",
        "priority_asc": "priority_score ASC NULLS LAST, updated_at DESC NULLS LAST, asset_key",
        "company": "company_sort ASC NULLS LAST, asset_key",
        "project": "project_sort ASC NULLS LAST, asset_key",
        "updated": "updated_at DESC NULLS LAST, asset_key",
    }[sort]
    # Sort keys come from exactly the representative need used below. Selecting
    # them across the full cohort keeps pagination global without changing which
    # physical project/need represents an asset or building all its JSON eagerly.
    representative_order = (
        ("(b.need_id = ANY(CAST(:eligible_need_ids AS uuid[]))) DESC, " if shortlist else "")
        + representative_priority
        + "(b.need_id = :selected_need) DESC NULLS LAST, "
        "b.rank_score DESC, b.updated_at DESC, b.need_id"
    )
    company_name = (
        "coalesce(nullif(b.compact #>> '{project_metadata,operator}', ''), "
        "nullif(b.compact #>> '{project_metadata,owner}', ''))"
    )
    project_name = (
        "coalesce(nullif(canonical_project.name, ''), "
        "nullif(b.compact #>> '{project_metadata,title}', ''), "
        "nullif(b.compact #>> '{project_metadata,name}', ''), "
        "nullif(b.compact->>'browse_title', ''), nullif(b.compact->>'name', ''))"
    )
    # Match the UI's displayProjectName: remove only the exact attributed company
    # prefix before case folding, without changing the returned name or identity.
    project_key = (
        f"lower(CASE WHEN left({project_name}, length({company_name}) + 3) "
        f"= {company_name} || ' · ' "
        f"THEN substring({project_name} FROM length({company_name}) + 4) "
        f"ELSE {project_name} END)"
    )
    company_sort = (
        f"(array_agg(lower({company_name}) ORDER BY {representative_order}))[1]"
        if sort == "company"
        else "NULL::text"
    )
    project_sort = (
        f"(array_agg({project_key} ORDER BY {representative_order}))[1]"
        if sort == "project"
        else "NULL::text"
    )
    # Rank and count scalar project groups across the cohort, but build JSON
    # aggregates only after limiting to the requested page.
    rows = (
        session.execute(
            text(
                f"""
            WITH candidate_assets AS (
              SELECT DISTINCT {asset_key} AS asset_key
              FROM browse_rows WHERE {where}
            ), ranked_assets AS (
              SELECT {asset_key_b} AS asset_key,
                     array_agg(DISTINCT b.project_id ORDER BY b.project_id) AS project_ids,
                     (array_agg(canonical_project.name ORDER BY {representative_order}))[1]
                         AS representative_project_name,
                     {priority_projection},
                     max(b.updated_at) AS updated_at,
                     {company_sort} AS company_sort,
                     {project_sort} AS project_sort
              FROM browse_rows b JOIN candidate_assets c ON c.asset_key = {asset_key_b}
              LEFT JOIN projects canonical_project ON canonical_project.id = b.project_id
              WHERE b.generation_id = :generation
              GROUP BY 1
            ), page_assets AS (
              SELECT * FROM ranked_assets
              ORDER BY {order} LIMIT :limit OFFSET :offset
            ), page_privacy_state AS (
              SELECT p.asset_key,
                     EXISTS (
                         SELECT 1 FROM buying_chain_claims claim
                         WHERE claim.project_id = ANY(p.project_ids)
                     ) AS has_history_claims
              FROM page_assets p
            ), page_need_ids AS (
              SELECT DISTINCT b.need_id
              FROM page_assets p
              CROSS JOIN LATERAL unnest(p.project_ids) AS selected(project_id)
              JOIN browse_rows b ON b.generation_id = :generation
                AND b.project_id = selected.project_id
            ), accepted_current_sources AS (
              SELECT DISTINCT ON (no.need_id, e.id)
                     no.need_id, e.id, e.title, e.url, e.event_date,
                     left(e.abstract, 8192) AS abstract, e.published_at,
                     e.observed_at, e.content_hash,
                     e.extraction_location, e.event_date_label,
                     o.content_hash AS semantic_hash,
                     i.evaluator_version,
                     jsonb_build_object(
                         'semantic_hash', i.assessment->'semantic_hash',
                         'evidence_hash', i.assessment->'evidence_hash',
                         'project_identity_key', i.assessment->'project_identity_key',
                         'acquisition_capture_version',
                             i.assessment->'acquisition_capture_version',
                         'admission_status', i.assessment->'admission_status',
                         'target_need_id', i.assessment->'target_need_id',
                         'project_id', i.assessment->'project_id',
                         'research_claims', jsonb_path_query_array(
                             i.assessment->'research_claims',
                             '$[*] ? (@.field == "activity_load_mw")'
                         )
                     ) AS assessment,
                     s.id AS source_id, s.family AS source_family,
                     s.retrieval_method, project.identity_key AS project_identity_key
              FROM need_observations no
              JOIN observations o ON o.id=no.observation_id
              JOIN evidence e ON e.observation_id=o.id
              JOIN interpretations i ON i.observation_id=o.id
              JOIN sources s ON s.id=o.source_id
              JOIN power_needs pn ON pn.id=no.need_id
              JOIN projects project ON project.id=pn.project_id
              WHERE no.need_id IN (SELECT need_id FROM page_need_ids)
                AND i.content_hash=o.content_hash
                AND i.assessment->>'semantic_hash'=o.content_hash
                AND i.assessment->>'evidence_hash'=e.content_hash
                AND i.status='accepted'
                AND coalesce(i.assessment->>'decision','accepted')='accepted'
              ORDER BY no.need_id, e.id, i.id DESC
            ), ranked_current_sources AS (
              SELECT accepted.*,
                     count(*) OVER (PARTITION BY accepted.need_id) AS source_count,
                     row_number() OVER (
                         PARTITION BY accepted.need_id ORDER BY accepted.id
                     ) AS source_rank
              FROM accepted_current_sources accepted
            ), current_sources_by_need AS (
              SELECT need_id,
                     jsonb_agg(
                         CASE WHEN source_count > 40 THEN jsonb_build_object('overflow', true)
                         ELSE jsonb_build_object(
                             'id', id,
                             'title', title,
                             'url', url,
                             'event_date', event_date,
                             'event_date_label', event_date_label,
                             'abstract', abstract,
                             'published_at', published_at,
                             'observed_at', observed_at,
                             'content_hash', content_hash,
                             'semantic_hash', semantic_hash,
                             'assessment', assessment,
                             'evaluator_version', evaluator_version,
                             'source', jsonb_build_object(
                                 'id', source_id,
                                 'family', source_family,
                                 'retrieval_method', retrieval_method
                             ),
                             'project_identity_key', project_identity_key,
                             'extraction_location', extraction_location,
                             'current', true
                         ) END ORDER BY id
                     ) FILTER (
                         WHERE source_rank <= 40 OR (source_rank = 41 AND source_count > 40)
                     ) AS evidence
              FROM ranked_current_sources
              WHERE source_rank <= 41
              GROUP BY need_id
            )
            SELECT p.asset_key, p.project_ids, p.representative_project_name,
                   privacy.has_history_claims,
              (array_agg(
                  b.compact || jsonb_build_object(
                      '_commercial_brief_evidence', coalesce(s.evidence, '[]'::jsonb)
                  ) ORDER BY {representative_order}
              ))[1]
                  AS representative,
              (array_agg(b.summary ORDER BY {representative_order}))[1]
                  AS representative_summary,
              jsonb_agg(
                b.compact || jsonb_build_object(
                    '_commercial_brief_evidence', coalesce(s.evidence, '[]'::jsonb)
                ) ORDER BY b.rank_score DESC, b.updated_at DESC, b.need_id
              ) AS needs,
              count(*)::integer AS need_count, p.priority_score, p.updated_at,
              (SELECT count(*)::bigint FROM ranked_assets) AS total
            FROM page_assets p JOIN browse_rows b
              ON b.generation_id = :generation AND {asset_key_b} = p.asset_key
            JOIN page_privacy_state privacy ON privacy.asset_key = p.asset_key
            LEFT JOIN current_sources_by_need s ON s.need_id = b.need_id
            GROUP BY p.asset_key, p.project_ids, p.representative_project_name,
                     privacy.has_history_claims, p.priority_score, p.updated_at,
                     p.company_sort, p.project_sort
            ORDER BY {order}
            """
            ),
            params,
        )
        .mappings()
        .all()
    )
    if rows:
        total = rows[0]["total"]
    else:
        total = (
            session.scalar(
                text(
                    f"WITH candidate_assets AS (SELECT DISTINCT {asset_key} AS asset_key "
                    f"FROM browse_rows WHERE {where}) SELECT count(*) FROM candidate_assets"
                ),
                params,
            )
            or 0
        )

    items = []
    for row in rows:
        compact = row["representative"] or {}
        meta = compact.get("project_metadata") or {}
        name = (
            row["representative_project_name"]
            or meta.get("title")
            or meta.get("name")
            or compact.get("browse_title")
            or compact.get("name")
        )
        category = meta.get("sector")
        representative_project_id = str(compact.get("project_id") or "")
        if primary_customer_ids_by_project is not None:
            primary_id = primary_customer_ids_by_project.get(representative_project_id)
            project_contact_people = [
                person
                for person in (compact.get("contact_people") or [])
                if primary_id is not None
                and str(person.get("company_identity_id") or "") == primary_id
            ]
        else:
            primary_id = None
            project_contact_people = compact.get("contact_people") or []
        needs = []
        for need in row["needs"] or []:
            need_project_id = str(need.get("project_id") or representative_project_id)
            if primary_customer_ids_by_project is not None:
                need_primary_id = primary_customer_ids_by_project.get(need_project_id)
                need_contact_actions = [
                    action
                    for action in (need.get("contact_actions") or [])
                    if need_primary_id is not None
                    and str(action.get("company_identity_id") or "") == need_primary_id
                ]
                need_contact_people = [
                    person
                    for person in (need.get("contact_people") or [])
                    if need_primary_id is not None
                    and str(person.get("company_identity_id") or "") == need_primary_id
                ]
            else:
                need_contact_actions = need.get("contact_actions") or []
                need_contact_people = need.get("contact_people") or []
            needs.append(
                {
                    key: need.get(key)
                    for key in (
                        "id",
                        "project_id",
                        "name",
                        "browse_title",
                        "asset_type",
                        "tier",
                        "location",
                        "activity",
                        "required_mw",
                        "start_window",
                        "commercial_preview",
                        "evidence_count",
                        "priority_segment",
                        "priority_label",
                        "project_metadata",
                        "contact_actions",
                        "contact_people",
                        "_commercial_brief_evidence",
                    )
                    if need.get(key) is not None
                }
            )
            if primary_customer_ids_by_project is not None:
                needs[-1]["contact_actions"] = need_contact_actions
                needs[-1]["contact_people"] = need_contact_people
        contact = []
        for action in compact.get("contact_actions") or []:
            if primary_customer_ids_by_project is not None and (
                primary_id is None or str(action.get("company_identity_id") or "") != primary_id
            ):
                continue
            kind = action.get("kind")
            if kind not in {"call", "email", "contact"}:
                continue
            contact.append(
                {
                    **action,
                    "label": {
                        "call": "Call",
                        "email": "Email",
                        "contact": "Company contact page",
                    }[kind]
                    + (
                        f" {action.get('name') or action.get('company')}"
                        if kind in {"call", "email"}
                        and (action.get("name") or action.get("company"))
                        else ""
                    ),
                    "route_kind": (
                        "person_method"
                        if action.get("name")
                        and action.get("responsibility") != "General company contact path"
                        else "company_route"
                    ),
                }
            )
        if primary_customer_ids_by_project is not None:
            # A project's header can use a current primary-account contact
            # attached to any need on that physical project.
            known_actions = {
                (
                    str(action.get("company_identity_id") or ""),
                    str(action.get("person_identity_id") or ""),
                    str(action.get("kind") or ""),
                    str(action.get("href") or ""),
                )
                for action in contact
            }
            for need_item in needs:
                for action in need_item.get("contact_actions") or []:
                    key = (
                        str(action.get("company_identity_id") or ""),
                        str(action.get("person_identity_id") or ""),
                        str(action.get("kind") or ""),
                        str(action.get("href") or ""),
                    )
                    kind = action.get("kind")
                    if key in known_actions or kind not in {"call", "email", "contact"}:
                        continue
                    known_actions.add(key)
                    contact.append(
                        {
                            **action,
                            "label": {
                                "call": "Call",
                                "email": "Email",
                                "contact": "Company contact page",
                            }[kind]
                            + (
                                f" {action.get('name') or action.get('company')}"
                                if kind in {"call", "email"}
                                and (action.get("name") or action.get("company"))
                                else ""
                            ),
                            "route_kind": (
                                "person_method"
                                if action.get("name")
                                and action.get("responsibility") != "General company contact path"
                                else "company_route"
                            ),
                        }
                    )
        asset_project_ids = [str(project_id) for project_id in row["project_ids"]]
        if representative_project_id not in asset_project_ids:
            representative_project_id = asset_project_ids[0]
        asset_identity = meta.get("asset_identity")
        public_id = (
            str(uuid5(NAMESPACE_URL, f"gridlens:{row['asset_key']}"))
            if row["asset_key"].startswith("api:")
            else asset_project_ids[0]
        )
        shortlist_result = None
        if shortlist:
            assessment = shortlist_by_need.get(str(compact.get("id")), {})
            grouped_assessments = [
                shortlist_by_need[str(need["id"])]
                for need in row["needs"] or []
                if need.get("id") in shortlist_by_need
                and shortlist_by_need[str(need["id"])].get("eligible")
            ]
            if grouped_assessments:
                assessment = {
                    **assessment,
                    "eligible": True,
                    "reasons": list(
                        dict.fromkeys(
                            reason
                            for grouped in grouped_assessments
                            for reason in grouped.get("reasons") or []
                        )
                    ),
                    "evidence_refs": sorted(
                        {
                            reference
                            for grouped in grouped_assessments
                            for reference in grouped.get("evidence_refs") or []
                        }
                    ),
                }
            shortlist_result = assessment
        items.append(
            {
                "id": public_id,
                "project_id": representative_project_id,
                "project_ids": asset_project_ids,
                "asset_identity": asset_identity,
                "representative_need_id": compact.get("id"),
                "name": name,
                "company": meta.get("operator") or meta.get("owner"),
                "location": meta.get("location") or compact.get("location"),
                "sector": category if category in {"oil_gas", "data_centers"} else None,
                "asset_type": compact.get("asset_type"),
                "priority_score": row["priority_score"],
                "needs": needs,
                "_has_history_claims": row["has_history_claims"],
                "need_count": row["need_count"],
                "event": meta.get("event"),
                "_representative_metadata": meta,
                "contact": contact,
                "contact_people": project_contact_people,
                "power_summary": meta.get("power_summary") or compact.get("power_summary"),
                "power_summary_kind": meta.get("power_summary_kind") or "unknown",
                "power_amount_class": (
                    meta.get("power_amount_class")
                    if meta.get("power_amount_class")
                    in {"documented", "calculated", "estimated", "inferred", "unknown"}
                    else "unknown"
                ),
                "next_action": (compact.get("commercial_preview") or {}).get("next_action"),
                **({"shortlist_assessment": shortlist_result} if shortlist else {}),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        )

    if shortlist and items:
        # Batch assessments through the established saved-history privacy
        # projection. Each synthetic saved card carries only its own project
        # lineage, preventing unrelated page items from cross-redacting.
        scoped = project_saved_history_privacy(
            session,
            {
                "versions": [
                    {
                        "saved_card": {
                            "project_id": item["project_id"],
                            "related_project_ids": item["project_ids"],
                            "shortlist_assessment": item["shortlist_assessment"],
                        }
                    }
                    for item in items
                ]
            },
        )
        for item, version in zip(items, scoped["versions"], strict=True):
            item["shortlist_assessment"] = _redact_all_contact_tokens(
                version["saved_card"]["shortlist_assessment"]
            )

    # Recheck cached actions and named people against current suppressions. A
    # later privacy suppression takes effect without waiting for a new snapshot.
    from gridlens.intelligence.project_contact_actions import filter_project_contact_records

    records = []
    brief_cards = []
    for item in items:
        item["_has_contact_records"] = bool(
            item["contact"]
            or item["contact_people"]
            or any(
                need.get("contact_actions") or need.get("contact_people") for need in item["needs"]
            )
        )
        records.extend(item["contact"])
        records.extend(item["contact_people"])
        for need in item["needs"]:
            records.extend(need.get("contact_actions", []))
            records.extend(need.get("contact_people", []))
    allowed = {id(record) for record in filter_project_contact_records(session, records)}
    for item in items:
        item["contact"] = [record for record in item["contact"] if id(record) in allowed]
        item["contact_people"] = [
            record for record in item["contact_people"] if id(record) in allowed
        ]
        for need in item["needs"]:
            need["contact_actions"] = [
                record for record in need.get("contact_actions", []) if id(record) in allowed
            ]
            need["contact_people"] = [
                record for record in need.get("contact_people", []) if id(record) in allowed
            ]
    # Internal suppression keys never cross the API boundary.
    for item in items:
        for record in item["contact"] + item["contact_people"]:
            record.pop("company_identity_id", None)
            record.pop("person_identity_id", None)
            record.pop("record_type", None)
            record.pop("claim_id", None)
        for need in item["needs"]:
            for record in need.get("contact_actions", []) + need.get("contact_people", []):
                record.pop("company_identity_id", None)
                record.pop("person_identity_id", None)
                record.pop("record_type", None)
                record.pop("claim_id", None)

    # Current, version-matched citations were resolved in the bounded page
    # query and attached only to this page's exact need rows.
    evidence_by_need: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for need in item["needs"]:
            attached = need.pop("_commercial_brief_evidence", [])
            if isinstance(attached, list):
                for source in attached:
                    if isinstance(source, dict) and isinstance(source.get("published_at"), str):
                        try:
                            source["published_at"] = date.fromisoformat(source["published_at"][:10])
                        except ValueError:
                            pass
            evidence_by_need[str(need.get("id"))] = attached if isinstance(attached, list) else []

    # Briefs are derived after suppression and primary-account filtering so a
    # stale or cross-account contact route cannot be promoted into a summary.
    from gridlens.domain.commercial_brief import build_optional_commercial_brief

    for item in items:
        representative = _representative_need(item)
        assessment = shortlist_by_need.get(str(representative.get("id")), {}) if shortlist else {}
        representative_evidence = evidence_by_need.get(str(representative.get("id")), [])
        brief_input = {
            **representative,
            "id": representative.get("id"),
            "name": item.get("name"),
            "event": item.get("event"),
            "project_metadata": item.get("_representative_metadata"),
            "power_summary": item.get("power_summary"),
            "power_amount_class": item.get("power_amount_class"),
            "contact_actions": representative.get("contact_actions") or [],
            "shortlist_assessment": assessment,
            "evidence": representative_evidence,
        }
        if not representative_evidence:
            # Activity is a stored scope label, but without a current source it
            # is not part of this evidence-backed summary.
            for activity_field in ("power_scope", "power_activity", "activity", "activity_key"):
                brief_input.pop(activity_field, None)
        item["commercial_brief"] = build_optional_commercial_brief(brief_input)
        item["commercial_brief"]["best_contact"] = None
        brief_cards.append((item, [(item["commercial_brief"], None)]))
        need_brief_inputs = []
        for need in item["needs"]:
            need_evidence = evidence_by_need.get(str(need.get("id")), [])
            need_input = {
                **need,
                "shortlist_assessment": (
                    shortlist_by_need.get(str(need.get("id")), {}) if shortlist else {}
                ),
                "evidence": need_evidence,
                "contact_actions": need.get("contact_actions") or [],
            }
            if not need_evidence:
                for activity_field in ("power_scope", "power_activity", "activity", "activity_key"):
                    need_input.pop(activity_field, None)
            need_brief_inputs.append((need, need_input))
        for need, need_input in need_brief_inputs:
            need["commercial_brief"] = build_optional_commercial_brief(need_input)
        brief_cards[-1][1].extend(
            (need["commercial_brief"], need) for need, _need_input in need_brief_inputs
        )
        item.pop("_representative_metadata", None)

    privacy_targets: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]] = []
    for item, briefs in brief_cards:
        lineage_is_bounded = len(item["project_ids"]) == 1
        has_contact_data = item["_has_contact_records"]
        has_identity_pointer = any(_contains_identity_pointer(brief) for brief, _need in briefs)
        if (
            item["_has_history_claims"]
            or not lineage_is_bounded
            or has_contact_data
            or has_identity_pointer
        ):
            privacy_targets.extend((item, brief, need) for brief, need in briefs)
        else:
            # No retained identity claims exist for this exact bounded project
            # lineage. Contact routes were already live-filtered above, and
            # token redaction below remains unconditional.
            for brief, need in briefs:
                safe = _redact_all_contact_tokens(brief)
                if need is None:
                    item["commercial_brief"] = safe
                else:
                    need["commercial_brief"] = safe
    privacy_versions: list[dict[str, Any]] = []
    for item, brief, _need in privacy_targets:
        privacy_versions.append(
            {
                "saved_card": {
                    "project_id": item["project_id"],
                    "related_project_ids": item["project_ids"],
                    "commercial_brief": brief,
                }
            }
        )
    if privacy_versions:
        privacy_projected = project_saved_history_privacy(session, {"versions": privacy_versions})[
            "versions"
        ]
        for (item, _brief, need), version in zip(privacy_targets, privacy_projected, strict=True):
            safe = _redact_all_contact_tokens(version["saved_card"]["commercial_brief"])
            if need is None:
                item["commercial_brief"] = safe
            else:
                need["commercial_brief"] = safe
    # The contact action has already passed primary-account and live
    # suppression filtering. Reattach that one permitted route after the
    # history sanitizer, which intentionally redacts all method tokens.
    # (Need-specific briefs likewise use their own filtered action list.)
    for item in items:
        representative = _representative_need(item)
        route_actions = representative.get("contact_actions") or []
        action_brief = build_optional_commercial_brief({"contact_actions": route_actions}).get(
            "best_contact"
        )
        item["commercial_brief"]["best_contact"] = action_brief
        for need in item["needs"]:
            need["commercial_brief"]["best_contact"] = build_optional_commercial_brief(
                {"contact_actions": need.get("contact_actions") or []}
            ).get("best_contact")
        item.pop("_has_history_claims", None)
        item.pop("_has_contact_records", None)

    return {
        "items": items,
        "count_unit": "projects",
        "results_scope": "discovery" if discovery else "qualified",
        "total": total,
        "limit": limit,
        "offset": offset,
        "cohort_token": cohort,
        "generation": str(generation.id),
        "generation_id": str(generation.id),
        "as_of": generation.built_at.isoformat(),
        "valid_until": generation.valid_until.isoformat(),
        "qualification_state": "current",
        "refresh_state": _refresh_state(generation),
    }
