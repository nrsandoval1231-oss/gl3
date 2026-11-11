"""Server-filtered need-level commercial workspace over a current saved generation."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.domain.lifecycle import INDUSTRIAL_ASSET_VALUES
from gridlens.intelligence.saved_browse import canonical_json, current_generation


def query_plan(
    session, filters: dict[str, Any], *, alias: str = "", route: str | None = "pursuit_workspace"
):
    """Return the canonical SQL eligibility predicates shared by need/account pages."""
    generation = current_generation(session, route=route)
    identity = hashlib.sha256(
        canonical_json([str(generation.id), generation.digest, filters]).encode()
    ).hexdigest()
    cohort = f"pw1_{identity}"
    prefix = f"{alias}." if alias else ""
    clauses = [f"{prefix}generation_id=:generation"]
    params: dict[str, Any] = {"generation": generation.id}
    dimensions = (
        ("tier", "tier"),
        ("geography", "location"),
        ("industry", "industry"),
        ("activity", "activity"),
    )
    for key, column in dimensions:
        if filters.get(key):
            if filters[key] == "UNKNOWN" and key in {"geography", "industry", "activity"}:
                clauses.append(
                    f"{prefix}{column} IN ('', 'unknown')"
                    if key == "industry"
                    else f"{prefix}{column} = ''"
                )
            else:
                clauses.append(f"{prefix}{column}=:f_{key}")
                params[f"f_{key}"] = filters[key]
    if filters.get("industry_group") == "industrial":
        names = [f"industrial_asset_{index}" for index in range(len(INDUSTRIAL_ASSET_VALUES))]
        clauses.append(f"{prefix}industry IN ({', '.join(':' + name for name in names)})")
        params.update(dict(zip(names, INDUSTRIAL_ASSET_VALUES, strict=True)))
    if filters.get("timing"):
        clauses.append(f"{prefix}has_timing=:has_timing")
        params["has_timing"] = filters["timing"] == "KNOWN"
    if filters.get("mw_status"):
        clauses.append(
            f"{prefix}mw_low IS NOT NULL"
            if filters["mw_status"] == "KNOWN"
            else f"{prefix}mw_low IS NULL"
        )
    if filters.get("mw_min"):
        bound = Decimal(filters["mw_min"])
        if bound and bound.adjusted() > 512:
            clauses.append("false")
        elif bound and bound.adjusted() < -512:
            clauses.append(f"{prefix}mw_high > 0")
        else:
            clauses.append(f"{prefix}mw_high >= CAST(:mw_min AS numeric)")
            params["mw_min"] = filters["mw_min"]
    if filters.get("mw_max"):
        bound = Decimal(filters["mw_max"])
        if bound and bound.adjusted() > 512:
            clauses.append(f"{prefix}mw_low IS NOT NULL")
        elif bound and bound.adjusted() < -512:
            clauses.append(f"{prefix}mw_low = 0")
        else:
            clauses.append(f"{prefix}mw_low <= CAST(:mw_max AS numeric)")
            params["mw_max"] = filters["mw_max"]
    if filters.get("search"):
        clauses.append(f"strpos({prefix}search_text, :search)>0")
        params["search"] = filters["search"].casefold().strip()
    base = " AND ".join(clauses)
    disposition = filters.get("disposition")
    filtered = (
        f"{base} AND {prefix}compact->'commercial_preview'->>'disposition'=:disposition"
        if disposition
        else base
    )
    if disposition:
        params["disposition"] = disposition
    return generation, cohort, base, filtered, params


def page(session, filters: dict[str, Any], *, limit: int, offset: int, token: str | None):
    generation, cohort, base, filtered, params = query_plan(session, filters)
    if token is not None and token != cohort:
        raise HTTPException(409, "Opportunity cohort changed; restart pagination")
    params = {**params, "limit": limit, "offset": offset}
    sort_sql = {
        "priority": "rank_score DESC, updated_at DESC, need_id",
        "project": "lower(display_title), display_title, need_id",
        "mw": "mw_low DESC NULLS LAST, need_id",
        "start": (
            "NULLIF(NULLIF(lower(compact->>'start_window'), 'unknown'), '') ASC NULLS LAST, need_id"
        ),
        "updated": "updated_at DESC, need_id",
    }[filters["sort"]]
    count_sql = f"""
        SELECT count(*) FILTER (WHERE disposition='ACTION NOW') action_now,
          count(*) FILTER (WHERE disposition='RESEARCH') research,
          count(*) FILTER (WHERE disposition='WATCH') watch,
          count(*) FILTER (WHERE disposition='REJECT') reject
        FROM (
          SELECT compact->'commercial_preview'->>'disposition' disposition
          FROM browse_rows WHERE {base}
        ) q
    """
    counts = session.execute(text(count_sql), params).mappings().one()
    total = session.execute(
        text(f"SELECT count(*) FROM browse_rows WHERE {filtered}"), params
    ).scalar_one()
    rows = (
        session.execute(
            text(
                f"SELECT compact FROM browse_rows WHERE {filtered} "
                f"ORDER BY {sort_sql} LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        .scalars()
        .all()
    )
    items = []
    from gridlens.domain.commercial_brief import build_optional_commercial_brief
    from gridlens.intelligence.saved_history_privacy import (
        _redact_all_contact_tokens,
        project_saved_history_privacy,
    )

    need_ids = [compact.get("id") for compact in rows if compact.get("id")]
    evidence_by_need: dict[str, list[dict[str, Any]]] = {str(identity): [] for identity in need_ids}
    if need_ids:
        source_rows = (
            session.execute(
                text(
                    """WITH accepted AS (
                       SELECT DISTINCT ON (no.need_id, e.id)
                          no.need_id, e.id, e.title, e.url, left(e.abstract, 8192) AS abstract,
                          e.event_date,
                          e.event_date_label, e.published_at, e.observed_at, e.content_hash,
                          e.extraction_location, o.content_hash AS semantic_hash,
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
                          s.retrieval_method, p.identity_key AS project_identity_key
                   FROM need_observations no
                   JOIN observations o ON o.id=no.observation_id
                   JOIN evidence e ON e.observation_id=o.id
                   JOIN interpretations i ON i.observation_id=o.id
                   JOIN sources s ON s.id=o.source_id
                   JOIN power_needs pn ON pn.id=no.need_id
                   JOIN projects p ON p.id=pn.project_id
                   WHERE no.need_id=ANY(CAST(:need_ids AS uuid[]))
                     AND i.content_hash=o.content_hash
                     AND i.assessment->>'semantic_hash'=o.content_hash
                     AND i.assessment->>'evidence_hash'=e.content_hash
                     AND i.status='accepted'
                     AND coalesce(i.assessment->>'decision','accepted')='accepted'
                   ORDER BY no.need_id,e.id,i.id DESC
                   ), ranked AS (
                   SELECT accepted.*,
                          count(*) OVER (PARTITION BY accepted.need_id) AS source_count,
                          row_number() OVER (
                              PARTITION BY accepted.need_id ORDER BY accepted.id
                          ) AS source_rank
                   FROM accepted
                   )
                   SELECT * FROM ranked WHERE source_rank <= 41"""
                ),
                {"need_ids": need_ids},
            )
            .mappings()
            .all()
        )
        overflow_needs: set[str] = set()
        for source in source_rows:
            if source["source_count"] > 40:
                need_key = str(source["need_id"])
                if need_key not in overflow_needs:
                    evidence_by_need[need_key].append({"overflow": True})
                    overflow_needs.add(need_key)
                continue
            evidence_by_need[str(source["need_id"])].append(
                {
                    "id": str(source["id"]),
                    "title": source["title"],
                    "url": source["url"],
                    "abstract": source["abstract"],
                    "event_date": source["event_date"],
                    "event_date_label": source["event_date_label"],
                    "published_at": source["published_at"],
                    "observed_at": source["observed_at"],
                    "content_hash": source["content_hash"],
                    "semantic_hash": source["semantic_hash"],
                    "assessment": source["assessment"],
                    "evaluator_version": source["evaluator_version"],
                    "source": {
                        "id": source["source_id"],
                        "family": source["source_family"],
                        "retrieval_method": source["retrieval_method"],
                    },
                    "project_identity_key": source["project_identity_key"],
                    "extraction_location": source["extraction_location"],
                    "current": True,
                }
            )

    for compact in rows:
        preview = compact.pop("commercial_preview", {})
        if (
            not isinstance(preview, dict)
            or preview.get("disposition") not in {"ACTION NOW", "RESEARCH", "WATCH", "REJECT"}
            or not all(
                isinstance(preview.get(key), str)
                for key in ("reason", "next_question", "next_action")
            )
            or preview.get("organization") is not None
            and not isinstance(preview.get("organization"), str)
        ):
            raise HTTPException(
                503,
                "Commercial workspace preview unavailable; saved browse generation needs rebuild",
                headers={"Retry-After": "5", "X-Qualification-State": "pending"},
            )
        item = {
            **compact,
            "commercial_disposition": preview["disposition"],
            "commercial_reason": preview["reason"],
            "commercial_next_question": preview["next_question"],
            "commercial_next_action": preview["next_action"],
            "commercial_organization": preview.get("organization"),
        }
        item["commercial_brief"] = build_optional_commercial_brief(
            {
                **item,
                "commercial_preview": preview,
                # Workspace contact actions are generation-bound. They are
                # privacy-filtered again by project result routes only, so do
                # not elevate a cached route into this compact need brief.
                "contact_actions": [],
                "evidence": evidence_by_need.get(str(item.get("id")), []),
            }
        )
        items.append(item)
    if items:
        projected = project_saved_history_privacy(
            session,
            {
                "versions": [
                    {
                        "saved_card": {
                            "project_id": item.get("project_id"),
                            "commercial_brief": item["commercial_brief"],
                        }
                    }
                    for item in items
                ]
            },
        )["versions"]
        for item, version in zip(items, projected, strict=True):
            item["commercial_brief"] = _redact_all_contact_tokens(
                version["saved_card"]["commercial_brief"]
            )
    next_offset = offset + len(items) if offset + len(items) < total else None
    return {
        "items": items,
        "total": total,
        "counts": dict(counts),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "cohort_token": cohort,
        "count_unit": "power needs",
        "changes_available": False,
    }
