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
from time import monotonic
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, literal, or_, select, text, union, update

from gridlens.domain.commercial_triage import _priority, work_group_identity
from gridlens.domain.evaluation_clock import evaluate_at, evaluation_now
from gridlens.domain.ranking import RANKING_VERSION
from gridlens.intelligence.opportunity_browse import (
    normalized,
    normalized_dimension,
    opportunity_group_id,
    opportunity_group_key,
    project_title,
)
from gridlens.persistence.models import (
    BrowseDirtyProject,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CallFactVersion,
    Evidence,
    NeedObservation,
    Observation,
    PowerNeed,
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
    requested_now = now
    # A writer may publish between our clock sample and the SELECT snapshot.
    # Retry once with the actual clock, preserving explicit evaluation instants
    # and every freshness predicate in the same session/transaction.
    for _ in range(1 if requested_now is not None else 2):
        now = requested_now if requested_now is not None else datetime.now(UTC)
        generation = session.scalar(
            select(BrowseGeneration)
            .join(
                BrowseState,
                or_(
                    BrowseState.generation_id == BrowseGeneration.id,
                    BrowseState.prepared_generation_id == BrowseGeneration.id,
                ),
            )
            .where(
                BrowseState.id == 1,
                BrowseState.input_revision == BrowseGeneration.input_revision,
                BrowseGeneration.policy_version == POLICY_VERSION,
                BrowseGeneration.valid_from <= now,
                BrowseGeneration.valid_until > now,
            )
            .order_by(
                BrowseGeneration.valid_from.desc(),
                BrowseGeneration.built_at.desc(),
                BrowseGeneration.id,
            )
            .limit(1)
        )
        if generation is not None:
            return generation
    raise HTTPException(
        503,
        "Qualification pending: saved browse summaries need a retained-data rebuild",
        headers={"Retry-After": "5", "X-Qualification-State": "pending"},
    )


def _search_texts(session, summaries: list[dict]) -> dict[str, str]:
    """Exact canonical normalized substring stream, including historical evidence."""
    streams = {
        str(item["id"]): " ".join(
            normalized(value)
            for value in (
                item.get("name"),
                item.get("browse_title"),
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


def _write_rows(session, generation_id, summaries, *, check_budget=None):
    from gridlens.api import app as api

    digest = hashlib.sha256()
    row_count = 0
    for start in range(0, len(summaries), 50):
        if check_budget is not None:
            check_budget()
        batch = [
            {
                **item,
                "_browse_first_evidence": {},
                "_browse_action_candidates": list(item.get("_browse_action_candidates", [])),
            }
            for item in summaries[start : start + 50]
        ]
        api._opportunity_evidence_search_matches(session, batch, None)
        details = api.opportunity_projection(
            session, selected_need_ids={item["id"] for item in batch}
        )
        if check_budget is not None:
            check_budget()
        by_id = {str(item["id"]): item for item in details}
        for summary in batch:
            detail = by_id.get(str(summary["id"]))
            if detail and detail.get("browse_title"):
                summary["browse_title"] = detail["browse_title"]
        searches = _search_texts(session, batch)
        # Persist the compact commercial decision beside each canonical need row.
        # This is built during generation publication so requests never scan the
        # corpus or recompute business rules.
        from gridlens.domain.commercial_triage import build_card
        from gridlens.intelligence.buying_chain import buying_chain_views

        chains = buying_chain_views(
            session, {UUID(str(item["project_id"])) for item in details}
        )
        previews = {
            str(item["id"]): build_card(
                item,
                chains.get(str(item["project_id"])),
                api.chicago_today(),
            )
            for item in details
        }
        values = []
        for summary in batch:
            detail = by_id.get(str(summary["id"]))
            if detail is None:
                # Canonical summary/detail disagreement must never silently omit rows.
                raise RuntimeError("canonical summary/detail eligibility differs")
            commercial_priority = _priority(summary)
            low_high = api.exact_mw_interval(summary.get("required_mw"))
            compact = {
                key: value
                for key, value in detail.items()
                if key not in {"evidence", "lifecycle_timeline", "estimate_basis"}
            }
            compact.update(
                evidence=[],
                lifecycle_timeline=[],
                browse_title=summary.get("browse_title") or project_title(summary),
                evidence_count=len(detail.get("evidence", [])),
                priority_segment=api._opportunity_priority_segment(summary),
                priority_label=api._opportunity_priority_label(summary),
                workflow_status=summary.get("workflow_status", "UNKNOWN"),
            )
            preview = previews[str(summary["id"])]
            compact["commercial_preview"] = {
                "disposition": preview.get("disposition", "WATCH"),
                "reason": preview.get("reason", "Commercial assessment unavailable."),
                "next_question": preview.get("next_question", ""),
                "next_action": preview.get("next_action", ""),
                "organization": preview.get("organization"),
            }
            # Round-trip converts UUID/date/Decimal values for JSONB serialization.
            compact = json.loads(canonical_json(compact))
            saved_summary = json.loads(canonical_json(summary))
            saved_summary["browse_title"] = compact["browse_title"]
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
                    workflow_status=str(summary.get("workflow_status", "UNKNOWN")).upper(),
                    signal_decision=summary.get("signal_display_decision") or "REVIEW",
                    project_group=opportunity_group_id(opportunity_group_key(summary, True)),
                    single_group=opportunity_group_id(opportunity_group_key(summary, False)),
                    rank_score=detail["rank_score"],
                    updated_at=summary["_updated_at"],
                    search_text=searches[str(summary["id"])],
                    commercial_group=work_group_identity(summary),
                    commercial_segment=commercial_priority[0],
                    commercial_geography=commercial_priority[1],
                    commercial_date=commercial_priority[2],
                    summary=saved_summary,
                    compact=compact,
                    display_title=compact["browse_title"],
                )
            )
            digest.update(
                canonical_json([saved_summary, compact, searches[str(summary["id"])]]).encode()
            )
        if values:
            session.execute(insert(BrowseRow), values)
        row_count += len(values)
        if check_budget is not None:
            check_budget()
    return row_count, digest.hexdigest()


def refresh_project_changes(
    session, *, max_projects=100, max_needs=100, execution_deadline=None
) -> dict | None:
    """Publish scoped operator/ingestion changes in their canonical write transaction.

    The singleton lock serializes writers/publication; pre-commit readers keep the
    previous complete generation, post-commit readers see the new one. Unknown
    writes, policy changes and clock expiry stay pending for the full builder.
    Cloning is SQL-only population work; canonical reconstruction is project-bound.
    """
    from gridlens.api import app as api

    def check_budget():
        if execution_deadline is not None and monotonic() >= execution_deadline:
            raise TimeoutError("Saved browse publication deadline exhausted")

    check_budget()
    session.flush()
    state = session.scalar(
        select(BrowseState)
        .where(BrowseState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state is None or state.generation_id is None:
        return None
    # Any caller may have read canonical objects before another scoped writer
    # committed (including API fact/workflow handlers). With the publication
    # fence held and our writes flushed, reconstruct from the latest database
    # values rather than an identity map retained from an earlier revision.
    session.expire_all()
    previous = session.get(BrowseGeneration, state.generation_id)
    now = datetime.now(UTC)
    if (
        previous is None
        or previous.policy_version != POLICY_VERSION
        or previous.valid_from > now
        or previous.valid_until <= now
        or state.full_revision > previous.input_revision
    ):
        return None
    if previous.input_revision == state.input_revision:
        return {"status": "current"}
    project_query = select(BrowseDirtyProject.project_id).where(
        BrowseDirtyProject.revision > previous.input_revision,
        BrowseDirtyProject.revision <= state.input_revision,
    )
    if max_projects is not None:
        project_query = project_query.limit(max_projects + 1)
    projects = list(session.scalars(project_query))
    # Interactive callers retain their small bound. Workers have an explicit
    # larger bound/budget; offline maintenance can finish the complete dirty set.
    if max_projects is not None and len(projects) > max_projects:
        return None
    need_query = (
        select(PowerNeed.id).where(PowerNeed.project_id.in_(projects)).order_by(PowerNeed.id)
    )
    if max_needs is not None:
        need_query = need_query.limit(max_needs + 1)
    need_ids = list(session.scalars(need_query))
    if max_needs is not None and len(need_ids) > max_needs:
        return None
    check_budget()
    deadline = min(previous.valid_until, clock_deadline(session, now))
    generation = BrowseGeneration(
        id=uuid4(),
        input_revision=state.input_revision,
        policy_version=POLICY_VERSION,
        built_at=now,
        valid_from=now,
        valid_until=deadline,
        row_count=0,
        digest="",
        counts={},
    )
    session.add(generation)
    session.flush()
    columns = list(BrowseRow.__table__.columns)
    session.execute(
        insert(BrowseRow).from_select(
            [column.name for column in columns],
            select(
                *[
                    literal(generation.id) if column.name == "generation_id" else column
                    for column in columns
                ]
            ).where(
                BrowseRow.generation_id == previous.id,
                BrowseRow.project_id.not_in(projects),
            ),
        )
    )
    changed_digest = hashlib.sha256()
    with evaluate_at(now):
        # The selected canonical summary path deliberately handles one bounded
        # page. Never pass a larger set and silently publish only its first page.
        for start in range(0, len(need_ids), 100):
            check_budget()
            summaries = api.opportunity_projection(
                session, summary_only=True, selected_need_ids=set(need_ids[start : start + 100])
            )
            check_budget()
            budget_args = {"check_budget": check_budget} if execution_deadline is not None else {}
            _, batch_digest = _write_rows(session, generation.id, summaries, **budget_args)
            changed_digest.update(batch_digest.encode())
            check_budget()
    generation.row_count = session.scalar(
        select(func.count()).select_from(BrowseRow).where(BrowseRow.generation_id == generation.id)
    )
    generation.digest = hashlib.sha256(
        canonical_json(
            [
                previous.digest,
                generation.input_revision,
                changed_digest.hexdigest(),
            ]
        ).encode()
    ).hexdigest()
    # A new generation otherwise looks empty to stale statistics, allowing
    # quadratic nested-loop plans in the global metadata update.
    session.execute(text("ANALYZE browse_rows"))
    generation.counts = _publish_group_metadata(session, generation.id)
    check_budget()
    if datetime.now(UTC) >= deadline:
        # Never turn an expired construction into a claimed fresh publication.
        # Its canonical write remains committed/pending; maintenance rebuilds it.
        _prune_generations(session)
        return None
    state.generation_id = generation.id
    session.flush()
    _prune_generations(session)
    check_budget()
    # Keep latest dirty revisions until a full build publishes: an older full
    # snapshot may still need to replay this transaction even after this local
    # generation has become current. One journal row per project stays bounded.
    return {
        "status": "published",
        "mode": "projects",
        "projects": len(projects),
        "needs": len(need_ids),
        "generation_id": str(generation.id),
    }


def _prune_generations(session):
    keep = (
        select(BrowseGeneration.id)
        .order_by(BrowseGeneration.built_at.desc(), BrowseGeneration.id)
        .limit(3)
    )
    active = union(
        select(BrowseState.generation_id).where(
            BrowseState.id == 1, BrowseState.generation_id.is_not(None)
        ),
        select(BrowseState.prepared_generation_id).where(
            BrowseState.id == 1, BrowseState.prepared_generation_id.is_not(None)
        ),
    )
    session.execute(
        delete(BrowseGeneration).where(
            BrowseGeneration.id.not_in(keep), BrowseGeneration.id.not_in(active)
        )
    )


def prepare_next(factory, *, lead_seconds=120, before_publish=None) -> dict:
    """Prepare exactly the next canonical clock interval, never expose it early."""
    try:
        with factory() as session:
            generation = current_generation(session)
            state = session.get(BrowseState, 1)
            candidate = (
                session.get(BrowseGeneration, state.prepared_generation_id)
                if state.prepared_generation_id
                else None
            )
            if (
                candidate is not None
                and candidate.input_revision == generation.input_revision
                and candidate.policy_version == POLICY_VERSION
                and candidate.valid_from == generation.valid_until
            ):
                return {"status": "ready", "generation_id": str(candidate.id)}
            boundary = generation.valid_until
            if (boundary - datetime.now(UTC)).total_seconds() > lead_seconds:
                return {"status": "current"}
    except HTTPException:
        return {"status": "pending"}
    return rebuild(factory, before_publish=before_publish, _prepare_at=boundary)


def maintain_once(factory) -> dict:
    # Promotion is optional for reads (they select the ready interval directly),
    # but makes it the base for subsequent maintenance and the next preparation.
    with factory.begin() as session:
        state = session.scalar(select(BrowseState).where(BrowseState.id == 1).with_for_update())
        if state is not None and state.prepared_generation_id is not None:
            try:
                selected = current_generation(session)
            except HTTPException:
                selected = None
            if selected is not None and selected.id == state.prepared_generation_id:
                state.generation_id = selected.id
                state.prepared_generation_id = None
                session.flush()
        result = refresh_project_changes(session, max_projects=None, max_needs=None)
    if result is None:
        return rebuild(factory)
    prepared = prepare_next(factory)
    return prepared if prepared["status"] in {"prepared", "ready"} else result


def rebuild(factory, *, before_publish=None, _prepare_at: datetime | None = None) -> dict:
    """Build without blocking input writers; publish a fully fenced canonical snapshot.

    A crash rolls back the unpublished generation. The advisory lock excludes other
    builders, not canonical writes. Broad changes discard the build; a bounded
    project-local tail is canonically rebased under the publication lock.
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
                evaluated_at = _prepare_at or now
                deadline = clock_deadline(session, evaluated_at)
                generation = BrowseGeneration(
                    id=generation_id,
                    input_revision=revision,
                    policy_version=POLICY_VERSION,
                    built_at=now,
                    valid_from=evaluated_at,
                    valid_until=deadline,
                    row_count=0,
                    digest="",
                    counts={},
                )
                session.add(generation)
                session.flush()
                with evaluate_at(evaluated_at):
                    summaries = api.opportunity_projection(session, summary_only=True)
                    row_count, digest = _write_rows(session, generation_id, summaries)
                generation.row_count = row_count
                generation.digest = digest
                # Fresh backfills must not depend on a later autovacuum pass for
                # usable filter/group plans. This is outside the request path.
                session.execute(text("ANALYZE browse_rows"))
                generation.counts = _publish_group_metadata(session, generation_id)
                session.commit()
            if before_publish is not None:
                before_publish()
            with factory.begin() as publication:
                state = publication.scalar(
                    select(BrowseState).where(BrowseState.id == 1).with_for_update()
                )
                published = False
                if state.input_revision == revision and datetime.now(UTC) < deadline:
                    if _prepare_at is None:
                        state.generation_id = generation_id
                    else:
                        prior = (
                            publication.get(BrowseGeneration, state.prepared_generation_id)
                            if state.prepared_generation_id
                            else None
                        )
                        if (
                            prior is not None
                            and prior.input_revision == revision
                            and prior.policy_version == POLICY_VERSION
                            and prior.valid_from <= datetime.now(UTC) < prior.valid_until
                        ):
                            state.generation_id = prior.id
                        state.prepared_generation_id = generation_id
                    published = True
                elif (
                    _prepare_at is None
                    and state.full_revision <= revision
                    and datetime.now(UTC) < deadline
                ):
                    # Rebase a bounded ordinary-write tail under the publication
                    # lock. Repeated local edits cannot continually discard a long
                    # full build; readers see neither the intermediate pointer nor
                    # a mixed revision because both publications commit together.
                    previous_pointer = state.generation_id
                    state.generation_id = generation_id
                    publication.flush()
                    rebased = refresh_project_changes(
                        publication, max_projects=None, max_needs=None
                    )
                    if rebased is not None and rebased["status"] == "published":
                        generation_id = UUID(rebased["generation_id"])
                        generation = publication.get(BrowseGeneration, generation_id)
                        revision, row_count = generation.input_revision, generation.row_count
                        published = True
                    else:
                        state.generation_id = previous_pointer
                publication.flush()
                # Retain current plus two prior snapshots. This removes only derived
                # summary generations, never canonical evidence or accepted history.
                _prune_generations(publication)
                if published and _prepare_at is None:
                    publication.execute(
                        delete(BrowseDirtyProject).where(BrowseDirtyProject.revision <= revision)
                    )
            return {
                "status": ("prepared" if _prepare_at is not None else "published")
                if published
                else "superseded",
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
        AND (b.compact->>'group_id' IS DISTINCT FROM s.gid
          OR b.compact->>'group_title' IS DISTINCT FROM s.title
          OR (b.compact->>'group_total_filtered')::bigint IS DISTINCT FROM s.group_count)
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
            SELECT coalesce(sum(group_count), 0)::bigint AS total,
                count(*) AS groups,
                count(*) FILTER (WHERE decision='SHOW') AS show,
                count(*) FILTER (WHERE decision='REVIEW') AS review,
                count(*) FILTER (WHERE decision='HOLD') AS hold FROM groups
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
    # API callers use _begin_consistent_read's repeatable-read transaction. MVCC
    # keeps this immutable cohort visible even after concurrent retention pruning.
    generation = current_generation(session)
    # Offsets larger than the entire generation are necessarily empty. Clamping
    # also preserves Python-slice semantics beyond PostgreSQL's bigint range.
    offset = min(offset, generation.row_count)
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
        session.scalar(
            select(BrowseState)
            .where(BrowseState.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        generation = session.get(BrowseGeneration, generation_id)
        if generation is None or generation.policy_version != POLICY_VERSION:
            return False
        return bool(
            session.execute(
                update(BrowseState)
                .where(
                    BrowseState.id == 1,
                    BrowseState.input_revision == generation.input_revision,
                    literal(generation.valid_from) <= datetime.now(UTC),
                    literal(generation.valid_until) > datetime.now(UTC),
                )
                .values(generation_id=generation_id)
            ).rowcount
        )


def commercial_selection(
    session,
    limit: int,
    offset: int,
    *,
    now: datetime | None = None,
    selection_metadata: dict | None = None,
) -> tuple[list[tuple[str, list[str]]], dict, int]:
    """Select canonical commercial groups from saved scalars, then bounded members.

    SQL scans scalar Signal rows to find each group's first complete priority tuple.
    Only selected groups' IDs cross into Python; evidence is read for those IDs later.
    """
    selection_instant = now or evaluation_now(datetime.now(UTC))
    generation = current_generation(session, now=selection_instant)
    if selection_metadata is not None:
        selection_metadata["generation_valid_until"] = generation.valid_until
    rows = (
        session.execute(
            text("""
            WITH heads AS (
                SELECT DISTINCT ON (commercial_group)
                    commercial_group, commercial_segment, commercial_geography,
                    commercial_date, project_id, need_id,
                    count(*) OVER (PARTITION BY commercial_group) AS members
                FROM browse_rows WHERE generation_id = :generation AND tier = 'Signal'
                ORDER BY commercial_group, commercial_segment, commercial_geography,
                    commercial_date, project_id, need_id
            ), selected AS (
                SELECT * FROM heads ORDER BY commercial_segment, commercial_geography,
                    commercial_date, project_id, need_id LIMIT :limit OFFSET :offset
            )
            SELECT selected.*, totals.total FROM (SELECT count(*) AS total FROM heads) totals
            LEFT JOIN selected ON true
            ORDER BY commercial_segment, commercial_geography, commercial_date,
                project_id, need_id
        """),
            {
                "generation": generation.id,
                "limit": limit,
                "offset": min(offset, generation.row_count),
            },
        )
        .mappings()
        .all()
    )
    total = int(rows[0]["total"])
    groups: dict[str, list[str]] = {}
    for row in rows:
        identity = row["commercial_group"]
        if identity is None:
            continue
        if row["members"] > 50:
            raise HTTPException(
                413,
                {
                    "code": "commercial_group_too_large",
                    "group_id": "cg_" + hashlib.sha256(identity.encode()).hexdigest()[:32],
                    "group_member_count": row["members"],
                    "max_group_members": 50,
                    "message": (
                        "This work group exceeds the supported card size; no evaluation was saved."
                    ),
                },
            )
        groups[identity] = []
    projects = {}
    if groups:
        for identity, need_id, project_id in session.execute(
            select(BrowseRow.commercial_group, BrowseRow.need_id, BrowseRow.project_id)
            .where(
                BrowseRow.generation_id == generation.id,
                BrowseRow.tier == "Signal",
                BrowseRow.commercial_group.in_(groups),
            )
            .order_by(BrowseRow.need_id)
        ):
            groups[identity].append(str(need_id))
            projects[need_id] = project_id
    return list(groups.items()), projects, total
