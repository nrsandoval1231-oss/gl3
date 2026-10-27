"""Project-first reads over the immutable saved browse generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.intelligence.saved_browse import current_generation


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
    project_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    """Return physical projects, consolidating only validated well API identities."""
    if sector not in {"all", "oil_gas", "data_centers"}:
        raise HTTPException(422, "sector must be all, oil_gas, or data_centers")
    generation = current_generation(session)
    term = (search or "").strip().casefold()
    cohort_payload = [
        str(generation.id),
        generation.digest,
        sector,
        sort,
        term,
        str(need_id or ""),
        include_signals,
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
    if need_id is not None:
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
    discovery = bool(term or sector != "all" or need_id is not None or include_signals)
    if not discovery:
        # A useful contact route does not qualify an unsupported permit Signal.
        # Search and explicit sector exploration retain those early discoveries.
        filters.append("tier IN ('Prospect', 'Lead')")
    where = " AND ".join(filters)
    # Only a validated, canonical U.S. well API number may consolidate separate
    # permit Projects. Every other row retains its own canonical project id.
    asset_key = """CASE
        WHEN compact #>> '{project_metadata,asset_identity,kind}' = 'us_well_api'
         AND compact #>> '{project_metadata,asset_identity,identity_validated}' = 'true'
         AND compact #>> '{project_metadata,asset_identity,value}' ~ '^[0-9]{10}([0-9]{2}){0,2}$'
        THEN 'api:' || (compact #>> '{project_metadata,asset_identity,value}')
        ELSE 'project:' || project_id::text END"""
    asset_key_b = asset_key.replace("compact", "b.compact").replace("project_id", "b.project_id")
    order = (
        "priority_score DESC, updated_at DESC, asset_key"
        if sort == "priority"
        else "updated_at DESC, asset_key"
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
                     max(b.rank_score)::integer AS priority_score,
                     max(b.updated_at) AS updated_at
              FROM browse_rows b JOIN candidate_assets c ON c.asset_key = {asset_key_b}
              WHERE b.generation_id = :generation
              GROUP BY 1
            ), page_assets AS (
              SELECT * FROM ranked_assets
              ORDER BY {order} LIMIT :limit OFFSET :offset
            )
            SELECT p.asset_key, p.project_ids,
              (array_agg(b.compact ORDER BY (b.need_id = :selected_need) DESC NULLS LAST,
                        b.rank_score DESC, b.updated_at DESC, b.need_id))[1]
                  AS representative,
              jsonb_agg(
                b.compact ORDER BY b.rank_score DESC, b.updated_at DESC, b.need_id
              ) AS needs,
              count(*)::integer AS need_count, p.priority_score, p.updated_at,
              (SELECT count(*)::bigint FROM ranked_assets) AS total
            FROM page_assets p JOIN browse_rows b
              ON b.generation_id = :generation AND {asset_key_b} = p.asset_key
            GROUP BY p.asset_key, p.project_ids, p.priority_score, p.updated_at
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
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
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
