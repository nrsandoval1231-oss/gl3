"""Project-first reads over the immutable saved browse generation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.domain.opportunity_shortlist import POLICY_VERSION, shortlist_assessment
from gridlens.intelligence.saved_browse import current_generation
from gridlens.intelligence.saved_history_privacy import (
    _redact_all_contact_tokens,
    project_saved_history_privacy,
)
from gridlens.intelligence.signal_adjudication import POLICY_VERSION as SIGNAL_POLICY_VERSION
from gridlens.settings import settings


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
               ORDER BY e.id, sd.id DESC"""
            ),
            {
                "evidence_ids": evidence_ids,
                "policy_version": SIGNAL_POLICY_VERSION,
            },
        )
        .mappings()
        .all()
    )
    decisions: dict[str, str] = {}
    for row in rows:
        dimensions = row["dimensions"] or {}
        if (
            row["source"] == "jev"
            and row["model_version"] == settings.jev_model
            and dimensions.get("question_set") == "demand-v1"
            and row["decision"] in {"SHOW", "HOLD", "REVIEW"}
        ):
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
    selected_generation=None,
) -> dict[str, Any]:
    """Return physical projects, consolidating only validated well API identities."""
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    if sort not in {"priority", "priority_asc", "company", "project", "updated"}:
        raise HTTPException(422, "Unsupported project sort")
    generation = selected_generation or current_generation(session)
    term = (search or "").strip().casefold()
    source_rows: list[Any] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    if shortlist:
        # Freeze the exact effective Jev map before validating pagination.
        # This avoids MAX(id) races (IDs can commit out of order) and ensures
        # this request assesses exactly the decisions represented by its token.
        source_rows = (
            session.execute(
                text(
                    "SELECT need_id, project_id, summary, compact "
                    "FROM browse_rows WHERE generation_id = :generation"
                ),
                {"generation": generation.id},
            )
            .mappings()
            .all()
        )
        evidence_ids = sorted(
            {
                str(evidence.get("id"))
                for row in source_rows
                for evidence in (row["summary"] or {}).get("evidence", [])
                if evidence.get("assessment_current") is True and evidence.get("id")
            }
        )
        if evidence_ids:
            evidence_rows = (
                session.execute(
                    text("""SELECT e.id, e.title, e.abstract, e.url, e.published_at, e.event_date,
                              e.event_date_label, o.source_id
                       FROM evidence e JOIN observations o ON o.id = e.observation_id
                       WHERE e.id = ANY(CAST(:evidence_ids AS uuid[]))"""),
                    {"evidence_ids": evidence_ids},
                )
                .mappings()
                .all()
            )
            jev_by_evidence = _current_jev_decisions(session, evidence_ids)
            source_by_id = {
                str(row["id"]): {
                    **dict(row),
                    "id": str(row["id"]),
                    "text": row["abstract"],
                    "jev_decision": jev_by_evidence.get(str(row["id"])),
                }
                for row in evidence_rows
            }
        else:
            jev_by_evidence = {}
        jev_map_digest = hashlib.sha256(
            json.dumps(sorted(jev_by_evidence.items()), separators=(",", ":")).encode()
        ).hexdigest()
    else:
        jev_by_evidence = {}
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
        POLICY_VERSION if shortlist else None,
        jev_map_digest,
        date.today().isoformat() if shortlist else None,
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
        # Build eligibility and duplicate lineage against the full generation,
        # so search/sector/detail filters cannot split one physical project into
        # unstable public groups or omit its other source references.
        for row in source_rows:
            summary = row["summary"] or {}
            refs = []
            for evidence in summary.get("evidence", []):
                source = source_by_id.get(str(evidence.get("id")))
                if (
                    source
                    and evidence.get("assessment_current") is True
                    and evidence.get("source_id") == source.get("source_id")
                ):
                    refs.append({**source, "assessment_current": True})
            assessment = shortlist_assessment({**summary, **(row["compact"] or {})}, refs)
            shortlist_by_need[str(row["need_id"])] = assessment
            if assessment["eligible"]:
                eligible_need_ids.append(row["need_id"])
                shortlist_priority_by_need[row["need_id"]] = int(assessment.get("priority") or 0)
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
    if shortlist:
        duplicate_groups: dict[str, set[UUID]] = {}
        for row in source_rows:
            duplicate_key = shortlist_by_need[str(row["need_id"])].get("duplicate_key")
            if duplicate_key:
                duplicate_groups.setdefault(duplicate_key, set()).add(row["project_id"])
        components: list[set[UUID]] = []
        for project_set in duplicate_groups.values():
            if len(project_set) < 2:
                continue
            overlapping = [component for component in components if component & project_set]
            merged = set(project_set)
            for component in overlapping:
                merged.update(component)
                components.remove(component)
            components.append(merged)
        for component in components:
            canonical = min(component, key=str)
            duplicate_project_map.update({project_id: canonical for project_id in component})
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
    params["shortlist_dedupe_enabled"] = bool(shortlist and duplicate_project_map)
    if not shortlist or not duplicate_project_map:
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
        "coalesce(nullif(b.compact #>> '{project_metadata,title}', ''), "
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
                     {priority_projection},
                     max(b.updated_at) AS updated_at,
                     {company_sort} AS company_sort,
                     {project_sort} AS project_sort
              FROM browse_rows b JOIN candidate_assets c ON c.asset_key = {asset_key_b}
              WHERE b.generation_id = :generation
              GROUP BY 1
            ), page_assets AS (
              SELECT * FROM ranked_assets
              ORDER BY {order} LIMIT :limit OFFSET :offset
            )
            SELECT p.asset_key, p.project_ids,
              (array_agg(b.compact ORDER BY {representative_order}))[1]
                  AS representative,
              (array_agg(b.summary ORDER BY {representative_order}))[1]
                  AS representative_summary,
              jsonb_agg(
                b.compact ORDER BY b.rank_score DESC, b.updated_at DESC, b.need_id
              ) AS needs,
              count(*)::integer AS need_count, p.priority_score, p.updated_at,
              (SELECT count(*)::bigint FROM ranked_assets) AS total
            FROM page_assets p JOIN browse_rows b
              ON b.generation_id = :generation AND {asset_key_b} = p.asset_key
            GROUP BY p.asset_key, p.project_ids, p.priority_score, p.updated_at,
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
        summary = row["representative_summary"] or {}
        meta = compact.get("project_metadata") or {}
        name = (
            meta.get("title")
            or meta.get("name")
            or compact.get("browse_title")
            or compact.get("name")
        )
        category = meta.get("sector")
        needs = []
        for need in row["needs"] or []:
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
                    )
                    if need.get(key) is not None
                }
            )
        contact = []
        for action in compact.get("contact_actions") or []:
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
        asset_project_ids = [str(project_id) for project_id in row["project_ids"]]
        representative_project_id = compact.get("project_id")
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
                "need_count": row["need_count"],
                "event": meta.get("event"),
                "contact": contact,
                "contact_people": compact.get("contact_people") or [],
                "power_summary": meta.get("power_summary") or compact.get("power_summary"),
                "power_summary_kind": meta.get("power_summary_kind") or "unknown",
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
    for item in items:
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

    return {
        "items": items,
        "count_unit": "projects",
        "results_scope": "discovery" if discovery else "qualified",
        "total": total,
        "limit": limit,
        "offset": offset,
        "cohort_token": cohort,
        "generation": str(generation.id),
    }
