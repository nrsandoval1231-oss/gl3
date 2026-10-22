"""Bounded, read-only projections of current source-backed customer identities."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import buying_chain_views
from gridlens.intelligence.identity_reconciliation import current_claim_identity_links
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseRow,
    BuyingChainClaim,
    BuyingChainIdentityLink,
    CompanyIdentity,
    CompanyProjectMembership,
    CompanyProjectMembershipCorrection,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)

# Only roles that can identify a customer account. Contractors remain project
# relationships and applicants alone never create a customer account.
CUSTOMER_ROLES = {"owner_developer", "owner_construction", "owner_energy", "asset_operator"}


def account_queue(
    session: Session, *, search: str | None, limit: int, offset: int
) -> dict[str, Any]:
    """SQL-bounded page of generation-bound current customer accounts."""
    from gridlens.intelligence.saved_browse import current_generation

    generation = current_generation(session)
    term = (search or "").strip().casefold()
    params = {"generation": generation.id, "term": term, "limit": limit, "offset": offset}
    base = """
      WITH matched_accounts AS MATERIALIZED (
        SELECT DISTINCT company_identity_id
        FROM browse_customer_memberships
        WHERE generation_id=:generation AND
          (:term='' OR strpos(lower(organization_name), :term)>0)
      ), matching AS (
        SELECT m.company_identity_id, m.organization_name, r.project_id, r.need_id,
               r.rank_score, r.updated_at, r.compact, m.supporting_evidence_count,
               m.last_evidence_update,
               row_number() OVER (PARTITION BY m.company_identity_id
                 ORDER BY r.rank_score DESC, r.updated_at DESC, r.need_id) best_rank
        FROM browse_customer_memberships m
        JOIN browse_rows r ON r.generation_id=m.generation_id AND r.project_id=m.project_id
        WHERE m.generation_id=:generation AND
          (:term='' OR m.company_identity_id IN (SELECT company_identity_id FROM matched_accounts))
      ), accounts AS (
        SELECT company_identity_id, min(organization_name) name,
               array_agg(DISTINCT organization_name ORDER BY organization_name) aliases,
               count(DISTINCT project_id) project_count, count(*) need_count,
               max(supporting_evidence_count) evidence_count,
               max(last_evidence_update) last_evidence_update,
               array_agg(DISTINCT compact->>'tier')
                 FILTER (WHERE compact->>'tier' IS NOT NULL) tiers
        FROM matching GROUP BY company_identity_id
      )
    """
    total = session.execute(text(base + "SELECT count(*) FROM accounts"), params).scalar_one()
    rows = (
        session.execute(
            text(
                base
                + """
          SELECT a.company_identity_id, a.name, a.aliases, a.project_count, a.need_count,
                 a.tiers, a.evidence_count, a.last_evidence_update, b.compact
          FROM accounts a JOIN matching b USING(company_identity_id)
          WHERE b.best_rank=1
          ORDER BY lower(a.name), a.company_identity_id LIMIT :limit OFFSET :offset
        """
            ),
            params,
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows:
        compact = row["compact"]
        items.append(
            {
                "company_identity_id": row["company_identity_id"],
                "name": row["name"],
                "aliases": sorted(row["aliases"] or []),
                "project_count": row["project_count"],
                "need_count": row["need_count"],
                "supporting_evidence_count": row["evidence_count"],
                "last_evidence_update": row["last_evidence_update"],
                "qualification_tiers": sorted(row["tiers"] or []),
                "highest_priority_need": _account_need(json.dumps(compact, default=str)),
            }
        )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def account_browse_page(
    session: Session,
    filters: dict[str, Any],
    *,
    limit: int,
    offset: int,
    token: str | None,
) -> dict[str, Any]:
    """SQL-group eligible saved needs by generation-bound customer membership."""
    from gridlens.intelligence.pursuit_workspace import query_plan

    generation, cohort, _cohort_base, _cohort_filtered, _cohort_params = query_plan(
        session, filters, alias="r"
    )
    cohort = f"ca1_{cohort}"
    sql_generation, _sql_cohort, base, filtered_without_search, base_params = query_plan(
        session, {**filters, "search": None}, alias="r"
    )
    if sql_generation.id != generation.id:
        raise HTTPException(409, "Customer account cohort changed; restart pagination")
    search = (filters.get("search") or "").strip().casefold()
    need_or_account_search = (
        "(:search='' OR strpos(r.search_text, :search)>0 OR EXISTS ("
        "SELECT 1 FROM browse_customer_memberships cm "
        "JOIN browse_customer_memberships sm USING(company_identity_id) "
        "WHERE cm.generation_id=r.generation_id AND cm.project_id=r.project_id "
        "AND sm.generation_id=r.generation_id "
        "AND strpos(lower(sm.organization_name), :search)>0))"
    )
    params = {**base_params, "search": search, "limit": limit, "offset": offset}
    filtered = f"({filtered_without_search}) AND ({need_or_account_search})"
    count_params = {**base_params, "search": search}
    count_base = f"({base}) AND ({need_or_account_search})"
    if token is not None and token != cohort:
        raise HTTPException(409, "Customer account cohort changed; restart pagination")
    counts = (
        session.execute(
            text(f"""
            SELECT count(*) FILTER (WHERE disposition='ACTION NOW') action_now,
              count(*) FILTER (WHERE disposition='RESEARCH') research,
              count(*) FILTER (WHERE disposition='WATCH') watch,
              count(*) FILTER (WHERE disposition='REJECT') reject
            FROM (SELECT compact->'commercial_preview'->>'disposition' disposition
                  FROM browse_rows r WHERE {count_base}) q
        """),
            count_params,
        )
        .mappings()
        .one()
    )
    sort = filters.get("sort", "priority")
    best_order = "rank_score DESC, updated_at DESC, need_id"
    account_order = {
        "priority": "b.rank_score DESC, b.updated_at DESC, a.company_identity_id",
        "project": "lower(a.account_name), a.account_name, a.company_identity_id",
        "mw": "a.max_mw DESC NULLS LAST, a.company_identity_id",
        "start": "a.start_sort ASC NULLS LAST, a.company_identity_id",
        "updated": "a.latest_update DESC, a.company_identity_id",
    }[sort]
    sql = f"""
        WITH matching AS (
          SELECT m.company_identity_id, m.organization_name, r.need_id, r.project_id,
                 r.rank_score, r.updated_at, r.mw_low, r.display_title, r.compact,
                 row_number() OVER (
                   PARTITION BY m.company_identity_id ORDER BY {best_order}
                 ) best_rank
          FROM browse_customer_memberships m
          JOIN browse_rows r ON r.generation_id=m.generation_id AND r.project_id=m.project_id
          WHERE m.generation_id=:generation AND ({base}) AND ({need_or_account_search})
        ), aggregate_matching AS (
          SELECT company_identity_id, min(organization_name) account_name,
                 count(DISTINCT project_id) matching_project_count,
                 count(*) matching_need_count, max(mw_low) max_mw,
                 min(NULLIF(NULLIF(lower(compact->>'start_window'), 'unknown'), '')) start_sort,
                 max(updated_at) latest_update
          FROM matching GROUP BY company_identity_id
        ), all_counts AS (
          SELECT m.company_identity_id, count(DISTINCT r.project_id) project_count,
                 count(r.need_id) need_count
          FROM browse_customer_memberships m
          JOIN browse_rows r ON r.generation_id=m.generation_id AND r.project_id=m.project_id
          WHERE m.generation_id=:generation GROUP BY m.company_identity_id
        ), account_support AS (
          SELECT m.company_identity_id,
                 array_agg(DISTINCT m.organization_name ORDER BY m.organization_name) aliases,
                 max(m.supporting_evidence_count) evidence_count,
                 max(m.last_evidence_update) last_evidence_update
          FROM browse_customer_memberships m
          JOIN (SELECT DISTINCT project_id FROM browse_rows WHERE generation_id=:generation) r
            ON r.project_id=m.project_id
          WHERE m.generation_id=:generation GROUP BY m.company_identity_id
        ), accounts AS (
          SELECT a.*, c.project_count, c.need_count, s.aliases, s.evidence_count,
                 s.last_evidence_update
          FROM aggregate_matching a JOIN all_counts c USING(company_identity_id)
          JOIN account_support s USING(company_identity_id)
        )
        SELECT a.company_identity_id, a.account_name, a.project_count, a.need_count,
               a.aliases, a.evidence_count, a.last_evidence_update,
               a.matching_project_count, a.matching_need_count, b.compact
        FROM accounts a JOIN matching b USING(company_identity_id)
        WHERE b.best_rank=1
        ORDER BY {account_order}
        LIMIT :limit OFFSET :offset
    """
    rows = session.execute(text(sql), params).mappings().all()
    total = session.execute(
        text(f"""
        SELECT count(*) FROM (
          SELECT m.company_identity_id FROM browse_customer_memberships m
          JOIN browse_rows r ON r.generation_id=m.generation_id AND r.project_id=m.project_id
          WHERE m.generation_id=:generation AND {filtered}
          GROUP BY m.company_identity_id
        ) q
    """),
        count_params,
    ).scalar_one()
    output = []
    for row in rows:
        compact = dict(row["compact"])
        preview = compact.pop("commercial_preview", {})
        if (
            not isinstance(preview, dict)
            or preview.get("disposition") not in {"ACTION NOW", "RESEARCH", "WATCH", "REJECT"}
            or not all(
                isinstance(preview.get(key), str)
                for key in ("reason", "next_question", "next_action")
            )
        ):
            raise HTTPException(503, "Commercial account preview unavailable; rebuild required")
        compact["evidence_count"] = compact.get("evidence_count") or len(
            compact.get("evidence", [])
        )
        compact["evidence"] = []
        output.append(
            {
                **compact,
                "commercial_disposition": preview["disposition"],
                "commercial_reason": preview["reason"],
                "commercial_next_question": preview["next_question"],
                "commercial_next_action": preview["next_action"],
                "commercial_organization": preview.get("organization"),
                "company_identity_id": row["company_identity_id"],
                "account_name": row["account_name"],
                "account_aliases": row["aliases"],
                "project_count": row["project_count"],
                "need_count": row["need_count"],
                "supporting_evidence_count": row["evidence_count"],
                "last_evidence_update": row["last_evidence_update"],
                "matching_project_count": row["matching_project_count"],
                "matching_need_count": row["matching_need_count"],
            }
        )
    next_offset = offset + len(output) if offset + len(output) < total else None
    return {
        "items": output,
        "total": total,
        "counts": dict(counts),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "cohort_token": cohort,
        "count_unit": "company accounts",
        "changes_available": False,
    }


def record_rrc_operator_membership(
    session: Session,
    *,
    project: Project,
    observation: Observation,
    evidence: Evidence,
    source_id: str,
    record: dict[str, Any],
) -> None:
    """Persist a current RRC operator role from exact source-native permit fields."""
    from gridlens.ingestion.adapters.rrc_customer_identity import rrc_operator_identity

    operator = rrc_operator_identity(source_id, record)
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    if (
        operator is None
        or project.source_id != source_id
        or project.external_id != observation.external_id
        or observation.source_id != source_id
        or interpretation is None
        or interpretation.status != "accepted"
        or interpretation.content_hash != observation.content_hash
        or (interpretation.assessment or {}).get("evidence_hash") != evidence.content_hash
        or (interpretation.assessment or {}).get("decision") != "accepted"
        or evidence.observation_id != observation.id
        or record.get("abstract") != evidence.abstract
        or evidence.abstract != observation.abstract
    ):
        return
    # Serialize refreshes for the same project/source/role before reading the
    # current row; the partial unique index is the final invariant guard.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"customer-membership:{project.id}:{source_id}:asset_operator"},
    )
    session.execute(
        pg_insert(CompanyIdentity)
        .values(rrc_operator_number=operator.operator_number)
        .on_conflict_do_nothing(index_elements=[CompanyIdentity.rrc_operator_number])
    )
    identity = session.scalar(
        select(CompanyIdentity).where(
            CompanyIdentity.rrc_operator_number == operator.operator_number
        )
    )
    if identity is None:
        return
    existing = session.scalar(
        select(CompanyProjectMembership).where(
            CompanyProjectMembership.project_id == project.id,
            CompanyProjectMembership.source_id == source_id,
            CompanyProjectMembership.state == "current",
            CompanyProjectMembership.role == "asset_operator",
        )
    )
    if (
        existing
        and existing.source_version_hash == evidence.content_hash
        and existing.company_identity_id == identity.id
    ):
        return
    if existing:
        existing.state = "superseded"
        existing.superseded_at = datetime.now(UTC)
    else:
        retracted_version = session.scalar(
            select(CompanyProjectMembership)
            .where(
                CompanyProjectMembership.project_id == project.id,
                CompanyProjectMembership.source_id == source_id,
                CompanyProjectMembership.role == "asset_operator",
                CompanyProjectMembership.state == "retracted",
            )
            .order_by(CompanyProjectMembership.created_at.desc())
            .limit(1)
        )
        if retracted_version:
            # Source refresh cannot silently undo attributed human review. A
            # newly asserted, different operator remains visibly conflicted.
            if retracted_version.operator_number != operator.operator_number:
                replayed_conflict = session.scalar(
                    select(CompanyProjectMembership.id).where(
                        CompanyProjectMembership.project_id == project.id,
                        CompanyProjectMembership.source_id == source_id,
                        CompanyProjectMembership.role == "asset_operator",
                        CompanyProjectMembership.state == "conflicted",
                        CompanyProjectMembership.company_identity_id == identity.id,
                        CompanyProjectMembership.source_version_hash == evidence.content_hash,
                    )
                )
                if replayed_conflict:
                    return
                session.add(
                    CompanyProjectMembership(
                        company_identity_id=identity.id,
                        project_id=project.id,
                        role="asset_operator",
                        organization_name=operator.operator_name,
                        source_id=source_id,
                        source_evidence_id=evidence.id,
                        source_version_hash=evidence.content_hash,
                        decision_basis="source_changed_after_retraction",
                        operator_number=operator.operator_number,
                        state="conflicted",
                    )
                )
            return
    session.add(
        CompanyProjectMembership(
            company_identity_id=identity.id,
            project_id=project.id,
            role="asset_operator",
            organization_name=operator.operator_name,
            source_id=source_id,
            source_evidence_id=evidence.id,
            source_version_hash=evidence.content_hash,
            decision_basis="typed_rrc_operator_number_v1",
            operator_number=operator.operator_number,
        )
    )
    session.flush()


def backfill_rrc_operator_memberships(session: Session, *, batch_size: int = 100) -> dict[str, int]:
    """Attach retained, current RRC observations through explicit NeedObservation project links."""
    from gridlens.ingestion.adapters.rrc_customer_identity import SOURCES

    examined = 0
    offset = 0
    while True:
        rows = session.execute(
            select(Project, Observation, Evidence)
            .join(PowerNeed, PowerNeed.project_id == Project.id)
            .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .where(
                PowerNeed.active.is_(True),
                Project.source_id == Observation.source_id,
                Project.external_id == Observation.external_id,
                Observation.source_id.in_(SOURCES),
                Interpretation.status == "accepted",
                Interpretation.content_hash == Observation.content_hash,
                Interpretation.assessment["decision"].astext == "accepted",
                Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            )
            .distinct()
            .order_by(Evidence.id)
            .limit(batch_size)
            .offset(offset)
        ).all()
        if not rows:
            break
        for project, observation, evidence in rows:
            record_rrc_operator_membership(
                session,
                project=project,
                observation=observation,
                evidence=evidence,
                source_id=observation.source_id,
                record={"abstract": evidence.abstract},
            )
        examined += len(rows)
        offset += len(rows)
        if len(rows) < batch_size:
            break
    session.flush()
    current = (
        session.scalar(
            select(func.count())
            .select_from(CompanyProjectMembership)
            .where(
                CompanyProjectMembership.state == "current",
                CompanyProjectMembership.role == "asset_operator",
            )
        )
        or 0
    )
    return {"eligible_evidence_rows_examined": examined, "current_operator_memberships": current}


def retract_customer_membership(
    session: Session,
    *,
    membership_id: UUID,
    expected_version: int,
    idempotency_key: str,
    reason: str,
    actor: str,
) -> CompanyProjectMembershipCorrection:
    """Append an attributed, expected-version retraction and invalidate browse state."""
    prior = session.scalar(
        select(CompanyProjectMembershipCorrection).where(
            CompanyProjectMembershipCorrection.membership_id == membership_id,
            CompanyProjectMembershipCorrection.idempotency_key == idempotency_key,
        )
    )
    if prior:
        return prior
    membership = session.scalar(
        select(CompanyProjectMembership)
        .where(CompanyProjectMembership.id == membership_id)
        .with_for_update()
    )
    if membership is None:
        raise LookupError("Customer membership not found")
    if membership.version != expected_version or membership.state != "current":
        raise RuntimeError("Customer membership changed; refresh before correcting")
    if not reason.strip():
        raise ValueError("A retraction reason is required")
    event = CompanyProjectMembershipCorrection(
        membership_id=membership.id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        action="retracted",
        reason=reason.strip(),
        actor=actor,
    )
    session.add(event)
    membership.state = "retracted"
    membership.superseded_at = datetime.now(UTC)
    membership.version += 1
    session.flush()
    return event


def account_projects(
    session: Session,
    company_identity_id: UUID,
    *,
    limit: int,
    offset: int,
    need_limit: int = 25,
    need_offset: int = 0,
) -> dict[str, Any]:
    from gridlens.intelligence.saved_browse import current_generation

    generation = current_generation(session)
    account_row = (
        session.execute(
            text(
                """
            WITH scoped AS (
              SELECT m.organization_name, r.project_id, r.need_id, r.rank_score,
                     r.updated_at, r.compact,
                     row_number() OVER (ORDER BY r.rank_score DESC, r.updated_at DESC, r.need_id) n
              FROM browse_customer_memberships m
              JOIN browse_rows r ON r.generation_id=m.generation_id AND r.project_id=m.project_id
              WHERE m.generation_id=:generation AND m.company_identity_id=:identity
            )
            SELECT min(organization_name) name,
                   array_agg(DISTINCT organization_name ORDER BY organization_name) aliases,
                   count(DISTINCT project_id) project_count,
                   count(*) need_count,
                   array_agg(DISTINCT compact->>'tier')
                     FILTER (WHERE compact->>'tier' IS NOT NULL) tiers,
                   max(compact::text) FILTER (WHERE n=1) best_compact,
                   (SELECT max(m.supporting_evidence_count)
                    FROM browse_customer_memberships m
                    JOIN (SELECT DISTINCT project_id FROM browse_rows
                          WHERE generation_id=:generation) er ON er.project_id=m.project_id
                    WHERE m.generation_id=:generation AND m.company_identity_id=:identity)
                     evidence_count,
                   (SELECT max(m.last_evidence_update)
                    FROM browse_customer_memberships m
                    JOIN (SELECT DISTINCT project_id FROM browse_rows
                          WHERE generation_id=:generation) er ON er.project_id=m.project_id
                    WHERE m.generation_id=:generation AND m.company_identity_id=:identity)
                     last_evidence_update
            FROM scoped
            """
            ),
            {"generation": generation.id, "identity": company_identity_id},
        )
        .mappings()
        .one()
    )
    if account_row["name"] is None:
        raise LookupError("Customer account is not present in the current browse generation")
    scope = select(BrowseCustomerMembership.project_id).where(
        BrowseCustomerMembership.generation_id == generation.id,
        BrowseCustomerMembership.company_identity_id == company_identity_id,
    )
    eligible_scope = scope.join(
        BrowseRow,
        (BrowseRow.project_id == BrowseCustomerMembership.project_id)
        & (BrowseRow.generation_id == BrowseCustomerMembership.generation_id),
    ).distinct()
    total = session.scalar(select(func.count()).select_from(eligible_scope.subquery())) or 0
    page_rows = session.execute(
        select(Project, BrowseCustomerMembership.role, func.count(BrowseRow.need_id))
        .join(BrowseCustomerMembership, BrowseCustomerMembership.project_id == Project.id)
        .join(
            BrowseRow,
            (BrowseRow.project_id == Project.id)
            & (BrowseRow.generation_id == BrowseCustomerMembership.generation_id),
        )
        .where(
            BrowseCustomerMembership.generation_id == generation.id,
            BrowseCustomerMembership.company_identity_id == company_identity_id,
        )
        .group_by(Project.id, BrowseCustomerMembership.role)
        .order_by(Project.name, Project.id)
        .offset(offset)
        .limit(limit)
    ).all()
    page = [project for project, _role, _count in page_rows]
    project_roles = {project.id: role for project, role, _count in page_rows}
    need_counts = {project.id: count for project, _role, count in page_rows}
    ids = [project.id for project in page]
    needs_by_project: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        ranked = (
            select(
                BrowseRow.project_id,
                BrowseRow.need_id,
                BrowseRow.compact,
                func.row_number()
                .over(
                    partition_by=BrowseRow.project_id,
                    order_by=(
                        BrowseRow.rank_score.desc(),
                        BrowseRow.updated_at.desc(),
                        BrowseRow.need_id,
                    ),
                )
                .label("need_rank"),
                func.count().over(partition_by=BrowseRow.project_id).label("need_count"),
            )
            .where(BrowseRow.generation_id == generation.id, BrowseRow.project_id.in_(ids))
            .subquery()
        )
        rows = session.execute(
            select(ranked.c.project_id, ranked.c.compact)
            .where(ranked.c.need_rank > need_offset, ranked.c.need_rank <= need_offset + need_limit)
            .order_by(ranked.c.project_id, ranked.c.need_rank)
        ).all()
        for project_id, compact in rows:
            need = _account_need(json.dumps(compact, default=str))
            if need is not None:
                needs_by_project[project_id].append(need)
    items = []
    for project in page:
        items.append(
            {
                "id": project.id,
                "name": project.name,
                "location": project.location,
                "customer_role": project_roles[project.id],
                "need_count": need_counts[project.id],
                "needs": needs_by_project[project.id],
                "need_next_offset": (
                    need_offset + len(needs_by_project[project.id])
                    if need_offset + len(needs_by_project[project.id]) < need_counts[project.id]
                    else None
                ),
            }
        )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(items) if offset + len(items) < total else None,
        "account": {
            "company_identity_id": company_identity_id,
            "name": account_row["name"],
            "aliases": sorted(account_row["aliases"] or []),
            "project_count": account_row["project_count"],
            "need_count": account_row["need_count"],
            "supporting_evidence_count": account_row["evidence_count"] or 0,
            "last_evidence_update": account_row["last_evidence_update"],
            "qualification_tiers": sorted(account_row["tiers"] or []),
            "highest_priority_need": _account_need(account_row["best_compact"]),
        },
    }


def unresolved_projects(
    session: Session, *, search: str | None, limit: int, offset: int
) -> dict[str, Any]:
    """Bounded unresolved research page from the current saved generation."""
    from gridlens.intelligence.saved_browse import current_generation

    generation = current_generation(session)
    term = (search or "").strip().casefold()
    params = {"generation": generation.id, "term": term, "limit": limit, "offset": offset}
    where = (
        "(:term='' OR strpos(lower(u.organization_name), :term)>0 "
        "OR strpos(lower(p.name), :term)>0)"
    )
    base = f"""
      FROM browse_unresolved_customers u JOIN projects p ON p.id=u.project_id
      WHERE u.generation_id=:generation AND {where}
    """
    total = session.execute(text("SELECT count(*) " + base), params).scalar_one()
    rows = (
        session.execute(
            text(
                """
          SELECT u.project_id, p.name project_name, p.location,
                 u.organization_name, u.role, u.reason,
                 (SELECT r.need_id FROM browse_rows r
                  WHERE r.generation_id=u.generation_id AND r.project_id=u.project_id
                  ORDER BY r.rank_score DESC, r.updated_at DESC, r.need_id LIMIT 1) need_id
        """
                + base
                + """
          ORDER BY lower(u.organization_name), u.project_id, u.role
          LIMIT :limit OFFSET :offset
        """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "project_id": row["project_id"],
                "project_name": row["project_name"],
                "location": row["location"],
                "organization": row["organization_name"],
                "role": row["role"],
                "need_id": row["need_id"],
                "no_eligible_need": row["need_id"] is None,
                "reason": row["reason"],
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _current_customer_claims(
    session: Session,
    identity_ids: set[UUID] | None = None,
    *,
    project_ids: set[UUID] | None = None,
    include_conflicts: bool = False,
):
    links_query = select(BuyingChainIdentityLink).where(
        BuyingChainIdentityLink.state == "current",
        BuyingChainIdentityLink.entity_type == "company",
        BuyingChainIdentityLink.company_identity_id.is_not(None),
    )
    if identity_ids is not None:
        links_query = links_query.where(
            BuyingChainIdentityLink.company_identity_id.in_(identity_ids)
        )
    if project_ids is not None:
        links_query = links_query.join(
            BuyingChainClaim, BuyingChainClaim.id == BuyingChainIdentityLink.claim_id
        ).where(BuyingChainClaim.project_id.in_(project_ids))
    links = session.scalars(links_query).all()
    claim_ids = {link.claim_id for link in links}
    claims = (
        {
            claim.id: claim
            for claim in session.scalars(
                select(BuyingChainClaim).where(BuyingChainClaim.id.in_(claim_ids))
            )
        }
        if claim_ids
        else {}
    )
    candidate_ids = {
        claim_id for claim_id, claim in claims.items() if claim.category in CUSTOMER_ROLES
    }
    valid = current_claim_identity_links(session, candidate_ids)
    identity_for_claim = {
        link.claim_id: link.company_identity_id
        for link in links
        if link.claim_id in valid
        and str(link.company_identity_id) == valid[link.claim_id].get("company_identity_id")
    }
    current_projects = (
        buying_chain_views(session, {claims[cid].project_id for cid in candidate_ids})
        if candidate_ids
        else {}
    )
    supported = {
        UUID(str(candidate["id"]))
        for view in current_projects.values()
        for candidate in view.get("candidates", [])
        if not candidate.get("stale")
        and not candidate.get("retracted")
        and candidate.get("category") in CUSTOMER_ROLES
        and candidate.get("organization_relationship") == "DIRECT"
    }
    linked_claims = [
        (identity_for_claim[claim_id], claims[claim_id].project_id, claims[claim_id])
        for claim_id in candidate_ids & supported
        if claim_id in identity_for_claim and identity_for_claim[claim_id] is not None
    ]
    membership_query = (
        select(CompanyProjectMembership, Project, Evidence.observed_at)
        .join(Project, Project.id == CompanyProjectMembership.project_id)
        .join(Evidence, Evidence.id == CompanyProjectMembership.source_evidence_id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            CompanyProjectMembership.state == "current",
            CompanyProjectMembership.role == "asset_operator",
            CompanyProjectMembership.source_version_hash == Evidence.content_hash,
            Project.external_id == Observation.external_id,
            Observation.source_id == CompanyProjectMembership.source_id,
            Interpretation.status == "accepted",
            Interpretation.content_hash == Observation.content_hash,
            Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            Interpretation.assessment["decision"].astext == "accepted",
        )
    )
    if identity_ids is not None:
        membership_query = membership_query.where(
            CompanyProjectMembership.company_identity_id.in_(identity_ids)
        )
    if project_ids is not None:
        membership_query = membership_query.where(
            CompanyProjectMembership.project_id.in_(project_ids)
        )
    for membership, _project, observed_at in session.execute(membership_query):
        linked_claims.append(
            (
                membership.company_identity_id,
                membership.project_id,
                _membership_claim(membership, observed_at),
            )
        )
    identities_by_project: dict[UUID, set[UUID]] = defaultdict(set)
    for identity_id, project_id, _claim in linked_claims:
        if identity_id is not None and project_id is not None:
            identities_by_project[project_id].add(identity_id)
    conflicted = {pid for pid, ids in identities_by_project.items() if len(ids) > 1}
    if include_conflicts:
        return linked_claims
    return [row for row in linked_claims if row[1] not in conflicted]


def _membership_claim(membership: CompanyProjectMembership, observed_at: datetime) -> Any:
    """Adapt a typed operator membership to the small shared account projection shape."""

    return SimpleNamespace(
        category=membership.role,
        organization=membership.organization_name,
        citations=[{"evidence_id": str(membership.source_evidence_id)}],
        observed_at=observed_at,
        membership_basis=membership.decision_basis,
        membership_version=membership.source_version_hash,
    )


def _current_conflicted_memberships(session: Session, project_ids: set[UUID] | None = None):
    query = (
        select(CompanyProjectMembership, Project)
        .join(Project, Project.id == CompanyProjectMembership.project_id)
        .join(Evidence, Evidence.id == CompanyProjectMembership.source_evidence_id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            CompanyProjectMembership.state == "conflicted",
            CompanyProjectMembership.source_version_hash == Evidence.content_hash,
            Observation.source_id == CompanyProjectMembership.source_id,
            Project.external_id == Observation.external_id,
            Interpretation.status == "accepted",
            Interpretation.content_hash == Observation.content_hash,
            Interpretation.assessment["evidence_hash"].astext == Evidence.content_hash,
            Interpretation.assessment["decision"].astext == "accepted",
        )
    )
    if project_ids is not None:
        query = query.where(CompanyProjectMembership.project_id.in_(project_ids))
    rows = session.execute(query).all()
    return [
        (membership.project_id, membership.company_identity_id, membership.organization_name)
        for membership, _project in rows
    ]


def associated_accounts_for_projects(
    session: Session, project_ids: set[UUID]
) -> dict[UUID, dict[str, Any] | None]:
    """Return current, unambiguous customer associations for a bounded project batch."""
    if not project_ids:
        return {}
    claims = _current_customer_claims(session, project_ids=project_ids, include_conflicts=True)
    conflicts = _current_conflicted_memberships(session, project_ids)
    by_project: dict[UUID, list[tuple[UUID, Any]]] = defaultdict(list)
    for identity_id, project_id, claim in claims:
        by_project[project_id].append((identity_id, claim))
    conflicted_projects = {project_id for project_id, _identity, _name in conflicts}
    links = {
        link.claim_id: link
        for link in session.scalars(
            select(BuyingChainIdentityLink)
            .join(BuyingChainClaim, BuyingChainClaim.id == BuyingChainIdentityLink.claim_id)
            .where(
                BuyingChainClaim.project_id.in_(project_ids),
                BuyingChainIdentityLink.state == "current",
                BuyingChainIdentityLink.entity_type == "company",
            )
        )
    }
    from gridlens.intelligence.buying_chain import buying_chain_views

    views = buying_chain_views(session, project_ids)
    current_refs: dict[UUID, list[dict[str, str | None]]] = defaultdict(list)
    for view in views.values():
        for candidate in view.get("candidates", []):
            if candidate.get("stale") or candidate.get("retracted"):
                continue
            for source in candidate.get("evidence", []):
                if not source.get("current_support"):
                    continue
                current_refs[UUID(str(candidate["id"]))].append(
                    {
                        "namespace": "buying-chain-evidence",
                        "id": str(source["id"]),
                        "retained_evidence_id": source.get("retained_evidence_id"),
                    }
                )
    result: dict[UUID, dict[str, Any] | None] = {}
    role_priority = {
        "owner_developer": 0,
        "owner_energy": 1,
        "owner_construction": 2,
        "asset_operator": 3,
    }
    for project_id in project_ids:
        rows = by_project.get(project_id, [])
        identity_ids = {identity_id for identity_id, _claim in rows}
        if len(identity_ids) != 1 or project_id in conflicted_projects:
            result[project_id] = None
            continue
        identity_id = next(iter(identity_ids))
        candidates = sorted(
            ((claim.category, claim) for _identity, claim in rows),
            key=lambda pair: (
                role_priority.get(pair[0], 99),
                pair[0],
                str(getattr(pair[1], "id", "")),
            ),
        )
        role, claim = candidates[0]
        if role not in CUSTOMER_ROLES:
            result[project_id] = None
            continue
        if hasattr(claim, "membership_basis"):
            refs = [
                {
                    "namespace": "retained-evidence",
                    "id": citation["evidence_id"],
                    "retained_evidence_id": citation["evidence_id"],
                }
                for citation in claim.citations
            ]
            basis = claim.membership_basis
        else:
            link = links.get(claim.id)
            refs = current_refs.get(claim.id, [])
            basis = link.basis if link is not None else "source-supported-claim"
        refs = sorted(
            {
                (ref["namespace"], ref["id"], ref["retained_evidence_id"]): ref for ref in refs
            }.values(),
            key=lambda ref: (str(ref["namespace"]), str(ref["id"])),
        )
        if not refs:
            result[project_id] = None
            continue
        result[project_id] = {
            "company_identity_id": identity_id,
            "name": claim.organization,
            "role": role,
            "basis": basis,
            "support_status": "current",
            "evidence_refs": refs,
        }
    return result


def _current_role_claims(session: Session, *, include_noncustomer: bool = False):
    all_claims = session.scalars(select(BuyingChainClaim)).all()
    candidates = [
        claim for claim in all_claims if include_noncustomer or claim.category in CUSTOMER_ROLES
    ]
    views = (
        buying_chain_views(session, {claim.project_id for claim in candidates})
        if candidates
        else {}
    )
    supported = {
        UUID(str(row["id"]))
        for view in views.values()
        for row in view.get("candidates", [])
        if not row.get("stale")
        and not row.get("retracted")
        and (include_noncustomer or row.get("category") in CUSTOMER_ROLES)
        and (include_noncustomer or row.get("organization_relationship") == "DIRECT")
    }
    projects = (
        {
            project.id: project
            for project in session.scalars(
                select(Project).where(Project.id.in_({claim.project_id for claim in candidates}))
            )
        }
        if candidates
        else {}
    )
    return [
        (projects[claim.project_id], claim)
        for claim in candidates
        if claim.id in supported and claim.project_id in projects
    ]


def _need_summary(pair: Any) -> dict[str, Any]:
    need, project = pair
    return {
        "id": need.id,
        "project_id": project.id,
        "tier": need.tier,
        "activity_key": need.activity_key,
        "required_mw": need.required_mw,
        "start_window": need.start_window,
        "duration": need.duration,
        "supply": need.supply,
    }


def _account_need(compact_text: str | None) -> dict[str, Any] | None:
    if compact_text is None:
        return None
    compact = json.loads(compact_text)
    preview = compact.get("commercial_preview") or {}
    return {
        "id": compact["id"],
        "project_id": compact["project_id"],
        "tier": compact["tier"],
        "activity_key": compact.get("activity", "unknown"),
        "required_mw": compact.get("required_mw"),
        "start_window": compact.get("start_window"),
        "duration": compact.get("duration"),
        "supply": compact.get("supply", "Unknown"),
        "commercial_disposition": preview.get("disposition"),
        "commercial_reason": preview.get("reason"),
        "commercial_next_action": preview.get("next_action"),
        "project_title": compact.get("name"),
        "industry": compact.get("industry"),
        "location": compact.get("location"),
        "rank_score": compact.get("rank_score"),
    }
