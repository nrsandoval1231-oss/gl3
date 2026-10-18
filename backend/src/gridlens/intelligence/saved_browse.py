"""Versioned canonical browse generations. No network or model calls.

Builds are repeatable-read snapshots; publication uses a separate transaction and
compares the input revision. Readers never repair a generation or use stale tiers.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, literal, select, text, update

from gridlens.domain.ranking import RANKING_VERSION
from gridlens.intelligence.opportunity_browse import (
    normalized,
    normalized_dimension,
    opportunity_group_id,
    opportunity_group_key,
    project_title,
)
from gridlens.persistence.models import (
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CallFactVersion,
    Evidence,
    NeedObservation,
    Observation,
)


def _policy_fingerprint() -> str:
    # Every local evaluator/input loader participates. Compute once per process;
    # mixed application revisions cannot label each other's generations current.
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


POLICY_VERSION = f"browse-b1-v1/{RANKING_VERSION}/{_policy_fingerprint()}"
BUILD_LOCK = 643119021


def canonical_json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def clock_deadline(session, now: datetime) -> datetime:
    """Cover UTC qualification/buyer clocks, Chicago rank/brief clocks and exact facts."""
    zones = (UTC, ZoneInfo("America/Chicago"))
    boundaries = [
        datetime.combine(now.astimezone(zone).date() + timedelta(days=1), time(), zone).astimezone(
            UTC
        )
        for zone in zones
    ]
    boundaries.append(
        datetime.combine(now.astimezone().date() + timedelta(days=1), time()).astimezone(UTC)
    )
    for column in (CallFactVersion.effective_from, CallFactVersion.effective_until):
        boundary = session.scalar(select(func.min(column)).where(column > now))
        if boundary is not None:
            boundaries.append(boundary)
    return min(boundaries)


def current_generation(session, *, now: datetime | None = None) -> BrowseGeneration:
    now = now or datetime.now(UTC)
    generation = session.scalar(
        select(BrowseGeneration)
        .join(BrowseState, BrowseState.generation_id == BrowseGeneration.id)
        .where(
            BrowseState.id == 1,
            BrowseState.input_revision == BrowseGeneration.input_revision,
            BrowseGeneration.policy_version == POLICY_VERSION,
            BrowseGeneration.valid_until > now,
        )
    )
    if generation is None:
        raise HTTPException(
            503,
            "Qualification pending: saved browse summaries need a retained-data rebuild",
            headers={"Retry-After": "5", "X-Qualification-State": "pending"},
        )
    return generation


def _search_texts(session, summaries: list[dict]) -> dict[str, str]:
    """Exact canonical normalized substring stream, including historical evidence."""
    streams = {
        str(item["id"]): " ".join(
            normalized(value)
            for value in (
                item.get("name"),
                project_title(item),
                item.get("location"),
                item.get("activity"),
                item.get("supported_subject"),
                item.get("supported_action"),
                item.get("assessment_reason"),
            )
            if value
        )
        for item in summaries
    }
    query = (
        select(
            NeedObservation.need_id,
            Evidence.title,
            Evidence.abstract,
            Observation.external_id,
            Observation.source_id,
        )
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(NeedObservation.need_id.in_([UUID(key) for key in streams]))
        .order_by(
            NeedObservation.need_id,
            Evidence.observed_at.desc(),
            Evidence.content_hash.desc(),
            Evidence.id,
        )
    )
    for need_id, *fields in session.execute(query).yield_per(32):
        key = str(need_id)
        for value in fields:
            streams[key] = f"{streams[key]} {normalized(value)}".strip()
    return streams


def rebuild(factory, *, before_publish=None) -> dict:
    """Build without blocking input writers; atomically publish only unchanged inputs.

    A crash rolls back the unpublished generation. The advisory lock excludes other
    builders, not canonical writes. A competing mutation discards the build safely.
    """
    from gridlens.api import app as api

    with factory() as lock_session:
        if not lock_session.scalar(select(func.pg_try_advisory_lock(BUILD_LOCK))):
            return {"status": "busy"}
        try:
            generation_id = uuid4()
            with factory() as session:
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                revision = session.scalar(
                    select(BrowseState.input_revision).where(BrowseState.id == 1)
                )
                if revision is None:
                    raise RuntimeError("saved browse migration is required")
                now = datetime.now(UTC)
                deadline = clock_deadline(session, now)
                generation = BrowseGeneration(
                    id=generation_id,
                    input_revision=revision,
                    policy_version=POLICY_VERSION,
                    built_at=now,
                    valid_until=deadline,
                    row_count=0,
                    digest="",
                    counts={},
                )
                session.add(generation)
                session.flush()
                summaries = api.opportunity_projection(session, summary_only=True)
                digest = hashlib.sha256()
                row_count = 0
                for start in range(0, len(summaries), 50):
                    batch = [
                        {
                            **item,
                            "_browse_first_evidence": {},
                            "_browse_action_candidates": list(
                                item.get("_browse_action_candidates", [])
                            ),
                        }
                        for item in summaries[start : start + 50]
                    ]
                    api._opportunity_evidence_search_matches(session, batch, None)
                    searches = _search_texts(session, batch)
                    details = api.opportunity_projection(
                        session, selected_need_ids={item["id"] for item in batch}
                    )
                    by_id = {str(item["id"]): item for item in details}
                    values = []
                    for summary in batch:
                        detail = by_id.get(str(summary["id"]))
                        if detail is None:
                            # Canonical summary/detail disagreement must never silently omit rows.
                            raise RuntimeError("canonical summary/detail eligibility differs")
                        low_high = api.exact_mw_interval(summary.get("required_mw"))
                        compact = {
                            key: value
                            for key, value in detail.items()
                            if key not in {"evidence", "lifecycle_timeline", "estimate_basis"}
                        }
                        compact.update(
                            evidence=[],
                            lifecycle_timeline=[],
                            browse_title=project_title(summary),
                            evidence_count=len(detail.get("evidence", [])),
                            priority_segment=api._opportunity_priority_segment(summary),
                            priority_label=api._opportunity_priority_label(summary),
                            workflow_status=summary.get("workflow_status", "UNKNOWN"),
                        )
                        # Round-trip converts UUID/date/Decimal values for JSONB serialization.
                        compact = json.loads(canonical_json(compact))
                        saved_summary = json.loads(canonical_json(summary))
                        values.append(
                            dict(
                                generation_id=generation_id,
                                need_id=summary["id"],
                                project_id=summary["project_id"],
                                tier=summary["tier"],
                                location=normalized_dimension(summary.get("location")),
                                industry=normalized_dimension(summary.get("asset_type")),
                                activity=normalized_dimension(summary.get("activity")),
                                has_timing=bool(
                                    summary.get("start_window")
                                    and str(summary["start_window"]).strip()
                                    and normalized_dimension(summary["start_window"]) != "unknown"
                                ),
                                mw_low=low_high[0] if low_high else None,
                                mw_high=low_high[1] if low_high else None,
                                priority_segment=summary.get("_priority_segment", 8),
                                workflow_status=str(
                                    summary.get("workflow_status", "UNKNOWN")
                                ).upper(),
                                signal_decision=summary.get("signal_display_decision") or "REVIEW",
                                project_group=opportunity_group_id(
                                    opportunity_group_key(summary, True)
                                ),
                                single_group=opportunity_group_id(
                                    opportunity_group_key(summary, False)
                                ),
                                rank_score=detail["rank_score"],
                                updated_at=summary["_updated_at"],
                                search_text=searches[str(summary["id"])],
                                summary=saved_summary,
                                compact=compact,
                                display_title=project_title(summary),
                            )
                        )
                        digest.update(
                            canonical_json(
                                [saved_summary, compact, searches[str(summary["id"])]]
                            ).encode()
                        )
                    if values:
                        session.execute(insert(BrowseRow), values)
                    row_count += len(values)
                generation.row_count = row_count
                generation.digest = digest.hexdigest()
                # Fresh backfills must not depend on a later autovacuum pass for
                # usable filter/group plans. This is outside the request path.
                session.execute(text("ANALYZE browse_rows"))
                generation.counts = _publish_group_metadata(session, generation_id)
                session.commit()
            if before_publish is not None:
                before_publish()
            with factory.begin() as publication:
                published = publication.execute(
                    update(BrowseState)
                    .where(
                        BrowseState.id == 1,
                        BrowseState.input_revision == revision,
                        literal(datetime.now(UTC)) < deadline,
                    )
                    .values(generation_id=generation_id)
                ).rowcount
                # Retain current plus two prior snapshots. This removes only derived
                # summary generations, never canonical evidence or accepted history.
                keep = (
                    select(BrowseGeneration.id)
                    .order_by(BrowseGeneration.built_at.desc(), BrowseGeneration.id)
                    .limit(3)
                )
                active = select(BrowseState.generation_id).where(
                    BrowseState.id == 1, BrowseState.generation_id.is_not(None)
                )
                publication.execute(
                    delete(BrowseGeneration).where(
                        BrowseGeneration.id.not_in(keep), BrowseGeneration.id.not_in(active)
                    )
                )
            return {
                "status": "published" if published else "superseded",
                "generation_id": str(generation_id),
                "input_revision": revision,
                "row_count": row_count,
                "digest": generation.digest,
            }
        finally:
            lock_session.execute(select(func.pg_advisory_unlock(BUILD_LOCK)))


def cohort_token(generation: BrowseGeneration, filters: dict, *, ranked=False) -> str:
    normalized_filters = {
        key: normalized(value) for key, value in sorted(filters.items()) if value is not None
    }
    payload = [str(generation.id), generation.digest, normalized_filters]
    base = "b1_" + hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return f"{base}.rank.{generation.digest[:32]}" if ranked else base


def _filtered_cte(filters: dict) -> tuple[str, dict]:
    """Group after dimension filters, then apply group search/decision semantics."""
    predicates = ["generation_id = :generation"]
    params: dict[str, Any] = {
        "term": normalized(filters.get("search")),
        "decision": filters.get("decision") or "ALL",
    }
    for field, column in (
        ("tier", "tier"),
        ("geography", "location"),
        ("industry", "industry"),
        ("activity", "activity"),
        ("priority_segment", "priority_segment"),
        ("status", "workflow_status"),
    ):
        value = filters.get(field)
        if value is None:
            continue
        if value == "UNKNOWN" and field in {"geography", "industry", "activity"}:
            predicates.append(
                f"{column} IN ('', 'unknown')" if field == "industry" else f"{column} = ''"
            )
        else:
            predicates.append(f"{column} = :{field}")
            params[field] = value
    if filters.get("timing"):
        predicates.append("has_timing = :has_timing")
        params["has_timing"] = filters["timing"] == "KNOWN"
    if filters.get("mw_status"):
        predicates.append(
            "mw_low IS NOT NULL" if filters["mw_status"] == "KNOWN" else "mw_low IS NULL"
        )
    for field, expression in (
        ("mw_min", "mw_high >= CAST(:mw_min AS numeric)"),
        ("mw_max", "mw_low <= CAST(:mw_max AS numeric)"),
    ):
        if filters.get(field) is not None:
            bound = Decimal(filters[field])
            # Canonical MW strings are capped at 128 characters, but query
            # decimals may have arbitrarily large exponents. Preserve Decimal
            # comparison semantics without overflowing PostgreSQL numeric.
            if bound and bound.adjusted() > 512:
                predicates.append("false" if field == "mw_min" else "mw_low IS NOT NULL")
            elif bound and bound.adjusted() < -512:
                predicates.append("mw_high > 0" if field == "mw_min" else "mw_low = 0")
            else:
                predicates.append(expression)
                params[field] = filters[field]
    sql = f"""
        WITH dimensions AS (
            SELECT need_id, tier, project_id, project_group, single_group, rank_score,
                updated_at, signal_decision, display_title,
                (:term = '' OR strpos(search_text, :term) > 0) AS matched,
                count(*) OVER (PARTITION BY tier, project_id) AS project_count
            FROM browse_rows WHERE {" AND ".join(predicates)}
        ), grouped AS (
            SELECT *, CASE WHEN project_count > 1 THEN project_group ELSE single_group END AS gid
            FROM dimensions
        ), groups AS (
            SELECT gid, count(*) AS group_count,
                (array_agg(display_title ORDER BY updated_at DESC, need_id))[1] AS title,
                CASE WHEN bool_or(signal_decision = 'SHOW') THEN 'SHOW'
                     WHEN bool_or(signal_decision <> 'HOLD') THEN 'REVIEW'
                     ELSE 'HOLD' END AS decision
            FROM grouped GROUP BY gid HAVING bool_or(matched)
        ), selected_groups AS (
            SELECT * FROM groups WHERE :decision = 'ALL' OR decision = :decision
        ), selected AS (
            SELECT r.*, g.group_count, g.title FROM grouped r JOIN selected_groups g USING (gid)
        )
    """
    return sql, params


def _publish_group_metadata(session, generation_id: UUID) -> dict:
    # Save the unfiltered grouping/counts once, so the ordinary ranked path is
    # an index page read. Dimension/search filters retain their dynamic grouping.
    sql, params = _filtered_cte({})
    params["generation"] = generation_id
    session.execute(
        text(
            sql
            + """
        UPDATE browse_rows b SET compact = b.compact || jsonb_build_object(
            'group_id', s.gid, 'group_title', s.title,
            'group_total_filtered', s.group_count, 'matched_search', true
        ) FROM selected s WHERE b.generation_id=:generation AND b.need_id=s.need_id
    """
        ),
        params,
    )
    counts = {}
    for tier in (None, "Signal", "Prospect", "Lead"):
        tier_sql, tier_params = _filtered_cte({"tier": tier})
        tier_params["generation"] = generation_id
        row = (
            session.execute(
                text(
                    tier_sql
                    + """
            SELECT (SELECT count(*) FROM selected) AS total,
                (SELECT count(*) FROM groups) AS groups,
                (SELECT count(*) FROM groups WHERE decision='SHOW') AS show,
                (SELECT count(*) FROM groups WHERE decision='REVIEW') AS review,
                (SELECT count(*) FROM groups WHERE decision='HOLD') AS hold
        """
                ),
                tier_params,
            )
            .mappings()
            .one()
        )
        counts[tier or "ALL"] = dict(row)
    return counts


def page(
    session,
    filters: dict,
    *,
    limit=50,
    offset=0,
    ranked=False,
    token=None,
    group_id=None,
    need_id=None,
) -> dict:
    generation = current_generation(session)
    current_token = cohort_token(generation, filters, ranked=ranked)
    if token is not None and token.split(".rank.", 1)[0] != current_token.split(".rank.", 1)[0]:
        raise HTTPException(409, "Opportunity cohort changed; restart pagination")
    ordinary = all(
        value is None or key in {"tier", "decision", "search"} for key, value in filters.items()
    )
    ordinary = ordinary and not normalized(filters.get("search"))
    ordinary = ordinary and filters.get("decision") in {None, "ALL"}
    if ordinary and group_id is None and need_id is None:
        counts = generation.counts[filters.get("tier") or "ALL"]
        query = select(BrowseRow.compact).where(BrowseRow.generation_id == generation.id)
        if filters.get("tier"):
            query = query.where(BrowseRow.tier == filters["tier"])
        if ranked:
            query = query.order_by(BrowseRow.rank_score.desc())
        query = (
            query.order_by(BrowseRow.updated_at.desc(), BrowseRow.need_id)
            .limit(limit)
            .offset(offset)
        )
        items = session.scalars(query).all()
        loaded = Counter(row["group_id"] for row in items)
        items = [
            {
                **row,
                "group_loaded_on_page": loaded[row["group_id"]],
                "group_complete_on_page": loaded[row["group_id"]] == row["group_total_filtered"],
            }
            for row in items
        ]
        return {
            "items": items,
            "total_count": counts["total"],
            "group_total_count": counts["groups"],
            "cohort_token": current_token,
            "decision_counts": {
                "SHOW": counts["show"],
                "REVIEW": counts["review"],
                "HOLD": counts["hold"],
            },
            "qualification_state": "current",
        }
    sql, params = _filtered_cte(filters)
    params.update(generation=generation.id, limit=limit, offset=offset)
    counts = (
        session.execute(
            text(
                sql
                + """
        SELECT (SELECT count(*) FROM selected) AS total,
            (SELECT count(*) FROM selected_groups) AS groups,
            (SELECT count(*) FROM groups WHERE decision='SHOW') AS show,
            (SELECT count(*) FROM groups WHERE decision='REVIEW') AS review,
            (SELECT count(*) FROM groups WHERE decision='HOLD') AS hold
    """
            ),
            params,
        )
        .mappings()
        .one()
    )
    where = ""
    if group_id is not None:
        where = "WHERE gid = :group_id"
        params["group_id"] = group_id
    if need_id is not None:
        where = "WHERE need_id = :need_id"
        params["need_id"] = need_id
    order = "rank_score DESC, " if ranked else ""
    rows = (
        session.execute(
            text(
                sql
                + f"""
        SELECT p.*, r.compact FROM (
            SELECT need_id, gid, group_count, title, matched, rank_score, updated_at
            FROM selected {where} ORDER BY {order}updated_at DESC, need_id
            LIMIT :limit OFFSET :offset
        ) p JOIN browse_rows r ON r.generation_id=:generation AND r.need_id=p.need_id
        ORDER BY {("p.rank_score DESC, " if ranked else "")}p.updated_at DESC, p.need_id
    """
            ),
            params,
        )
        .mappings()
        .all()
    )
    loaded = Counter(row["gid"] for row in rows)
    items = [
        {
            **row["compact"],
            "group_id": row["gid"],
            "group_title": row["title"],
            "group_total_filtered": row["group_count"],
            "group_loaded_on_page": loaded[row["gid"]],
            "group_complete_on_page": loaded[row["gid"]] == row["group_count"],
            "matched_search": row["matched"],
        }
        for row in rows
    ]
    return {
        "items": items,
        "total_count": counts["total"],
        "group_total_count": counts["groups"],
        "cohort_token": current_token,
        "decision_counts": {
            "SHOW": counts["show"],
            "REVIEW": counts["review"],
            "HOLD": counts["hold"],
        },
        "qualification_state": "current",
        "generation_id": str(generation.id),
        "built_at": generation.built_at.isoformat(),
        "valid_until": generation.valid_until.isoformat(),
    }


def restore_generation(factory, generation_id: UUID) -> bool:
    """Repoint only to a generation still valid for the exact current inputs/policy."""
    with factory.begin() as session:
        # Serialize against publication and derived-generation retention before
        # testing the target; a retained generation cannot disappear mid-rollback.
        session.scalar(select(BrowseState).where(BrowseState.id == 1).with_for_update())
        generation = session.get(BrowseGeneration, generation_id)
        if generation is None or generation.policy_version != POLICY_VERSION:
            return False
        return bool(
            session.execute(
                update(BrowseState)
                .where(
                    BrowseState.id == 1,
                    BrowseState.input_revision == generation.input_revision,
                    literal(generation.valid_until) > datetime.now(UTC),
                )
                .values(generation_id=generation_id)
            ).rowcount
        )
