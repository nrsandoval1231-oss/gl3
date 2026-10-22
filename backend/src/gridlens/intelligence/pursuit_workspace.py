"""Server-filtered need-level commercial workspace over a current saved generation."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from gridlens.domain.lifecycle import INDUSTRIAL_ASSET_VALUES
from gridlens.intelligence.saved_browse import canonical_json, current_generation


def query_plan(session, filters: dict[str, Any], *, alias: str = ""):
    """Return the canonical SQL eligibility predicates shared by need/account pages."""
    generation = current_generation(session)
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
        items.append(
            {
                **compact,
                "commercial_disposition": preview["disposition"],
                "commercial_reason": preview["reason"],
                "commercial_next_question": preview["next_question"],
                "commercial_next_action": preview["next_action"],
                "commercial_organization": preview.get("organization"),
            }
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
