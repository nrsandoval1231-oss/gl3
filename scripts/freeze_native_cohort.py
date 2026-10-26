"""Freeze a source-cited, distinct-site cohort from an isolated native corpus.

Selection is read-only and independent of contacts, need size, and outcomes.
The resulting manifest is an adjudication diagnostic, not proof that selected
projects pass the power or commercial qualification gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

_MW_SCALAR = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>kw|mw|gw)?\s*$", re.I)
_MW_RANGE = re.compile(
    r"^\s*(?P<low>\d+(?:\.\d+)?)\s*(?P<unit1>kw|mw|gw)?\s*(?:-|–|—|to)\s*"
    r"(?P<high>\d+(?:\.\d+)?)\s*(?P<unit2>kw|mw|gw)?\s*$",
    re.I,
)
_UNIT_TO_MW = {"kw": Decimal("0.001"), "mw": Decimal("1"), "gw": Decimal("1000")}


def _normalize(value: object) -> str:
    plain = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", plain.casefold()).strip()


def _site_key(project: dict) -> tuple[str, ...]:
    state = str(project.get("region_state") or "").upper()
    location = _normalize(project.get("location"))
    name = _normalize(project.get("name"))
    facts = project.get("identity_facts") or {}
    lat = facts.get("latitude", facts.get("lat"))
    lon = facts.get("longitude", facts.get("lon", facts.get("lng")))
    try:
        if lat is not None and lon is not None:
            return state, "coordinates", f"{float(lat):.5f}", f"{float(lon):.5f}"
    except (TypeError, ValueError):
        pass
    if not location:
        return state, "name_only", name
    # RRC county codes are jurisdiction identifiers, not site addresses.
    # Preserve permit identity within a county and do not claim that these
    # records establish distinct physical sites.
    if re.search(r"\bcounty code\b", location):
        return state, "county_assertion", location, name
    # Exact street/route locations identify a site even when names differ.
    # At coarse city/county precision, retain project name to avoid merging
    # unrelated project assertions in one jurisdiction.
    if re.search(r"\d", location):
        return state, "precise_location", location
    return state, "coarse_location", location, name


def _rank(project: dict) -> str:
    citations = sorted(
        str(item.get("observation_hash") or item.get("evidence_hash") or "")
        for item in project.get("source_evidence", [])
    )
    key = "|".join(
        [
            str(project.get("project_id")),
            str(project.get("region_state")),
            str(project.get("asset_type")),
            *_site_key(project),
            *citations,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _required_mw_interval(value: object) -> tuple[Decimal, Decimal] | None:
    """Parse a scalar/range from the canonical required_mw field only."""
    raw = str(value or "").strip()
    range_match = _MW_RANGE.fullmatch(raw)
    scalar_match = _MW_SCALAR.fullmatch(raw)
    if not range_match and not scalar_match:
        return None
    try:
        if range_match:
            low_unit = (range_match.group("unit1") or range_match.group("unit2") or "mw").casefold()
            high_unit = (range_match.group("unit2") or range_match.group("unit1") or "mw").casefold()
            low = Decimal(range_match.group("low")) * _UNIT_TO_MW[low_unit]
            high = Decimal(range_match.group("high")) * _UNIT_TO_MW[high_unit]
            return (low, high) if low <= high else None
        unit = (scalar_match.group("unit") or "mw").casefold()
        amount = Decimal(scalar_match.group("number")) * _UNIT_TO_MW[unit]
        return amount, amount
    except (InvalidOperation, KeyError):
        return None


def _snapshot_source_provenance(abstract: str | None) -> list[dict]:
    """Extract exact RRC snapshot segment references from retained source text."""
    if not abstract:
        return []
    start_marker = "\nSource segment provenance: "
    end_marker = "\nOpaque source bytes (base64; not interpreted): "
    if abstract.count(start_marker) != 1 or abstract.count(end_marker) != 1:
        return []
    try:
        segment = abstract.split(start_marker, 1)[1].split(end_marker, 1)[0]
        records = json.loads(segment)
    except (json.JSONDecodeError, IndexError):
        return []
    allowed = ("filename", "source_url", "ordinal", "sequence", "raw_sha256")
    if not isinstance(records, list):
        return []
    return [
        {key: record[key] for key in allowed if key in record}
        for record in records
        if isinstance(record, dict)
    ]


def _temporary_activity_supported(needs: list[dict]) -> bool:
    return any(
        need.get("activity_key") in {"temporary-power", "bridge-power"}
        and re.search(
            r"\b(?:temporary|temporarily|rental|bridge power|bridge-power)\b",
            str(need.get("rationale") or ""),
            re.I,
        )
        for need in needs
    )


def select_frozen_candidates(candidates: list[dict], *, limit: int = 25) -> list[dict]:
    """Pick distinct cited TX/OK/NM sites by stable state/asset-type strata."""
    if limit < 1:
        raise ValueError("limit must be positive")
    grouped: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for candidate in candidates:
        state = str(candidate.get("region_state") or "").upper()
        if (
            candidate.get("region_status") != "ELIGIBLE"
            or state not in {"TX", "OK", "NM"}
            or not str(candidate.get("name") or "").strip()
            or not str(candidate.get("location") or "").strip()
        ):
            continue
        citations = [
            item
            for item in candidate.get("source_evidence", [])
            if item.get("url")
            and urlsplit(str(item["url"])).scheme in {"http", "https"}
            and item.get("observation_hash")
            and item.get("evidence_hash")
        ]
        if not citations:
            continue
        row = {**candidate, "source_evidence": citations}
        grouped[_site_key(row)].append(row)

    # Resolve any cross-source duplicate site to one stable canonical project
    # identity. This choice is based on IDs/citations only, never contacts,
    # power assertions, lifecycle, or benchmark outcome fields.
    unique_sites: list[dict] = []
    for site_candidates in grouped.values():
        unique_sites.append(min(site_candidates, key=_rank))

    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for candidate in unique_sites:
        strata[
            (
                str(candidate["region_state"]).upper(),
                str(candidate.get("asset_type") or "unknown").casefold(),
            )
        ].append(candidate)
    for values in strata.values():
        values.sort(key=_rank)

    # Round-robin over each observed state/asset-type stratum. This preserves
    # coverage where source diversity exists without forcing unsupported quotas.
    order = sorted(strata, key=lambda key: (-len(strata[key]), key))
    selected: list[dict] = []
    round_index = 0
    while len(selected) < limit:
        added = False
        for key in order:
            if round_index < len(strata[key]):
                candidate = strata[key][round_index]
                selected.append(
                    {
                        **candidate,
                        "selection_stratum": f"{key[0]}:{key[1]}",
                        "selection_rank": _rank(candidate),
                        "location_assertion_key": "|".join(_site_key(candidate)),
                        "project_assertion_key": (
                            f"{candidate.get('source_id')}:{candidate.get('external_id')}"
                        ),
                        "selection_basis": "source-backed distinct physical-site candidate",
                        "qualification_status": "NOT_ADJUDICATED",
                    }
                )
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        round_index += 1
    return selected


def _read_native_candidates(session) -> tuple[list[dict], dict[str, int]]:
    from sqlalchemy import and_, select, union

    from gridlens.persistence.models import (
        CompanyProjectMembership,
        Evidence,
        EvidencePackage,
        LifecycleEvent,
        NeedObservation,
        Observation,
        PowerNeed,
        Project,
        ProjectLifecycle,
        ProjectMatchDecision,
    )

    projects = list(
        session.scalars(
            select(Project)
            .where(
                Project.region_status == "ELIGIBLE",
                Project.region_state.in_(("TX", "OK", "NM")),
            )
            .order_by(Project.id)
        )
    )
    project_ids = [project.id for project in projects]
    if not projects:
        return [], {"eligible_territory_projects": 0, "cited_project_candidates": 0}

    direct_link = (
        select(Project.id.label("project_id"), Evidence.id.label("evidence_id"))
        .join(
            Observation,
            and_(
                Observation.source_id == Project.source_id,
                Observation.external_id == Project.external_id,
            ),
        )
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(Project.id.in_(project_ids))
    )
    need_link = (
        select(Project.id.label("project_id"), Evidence.id.label("evidence_id"))
        .join(PowerNeed, PowerNeed.project_id == Project.id)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(Project.id.in_(project_ids))
    )
    package_link = select(
        EvidencePackage.project_id.label("project_id"),
        EvidencePackage.evidence_id.label("evidence_id"),
    ).where(
        EvidencePackage.project_id.in_(project_ids), EvidencePackage.evidence_id.is_not(None)
    )
    match_link = select(
        ProjectMatchDecision.candidate_project_id.label("project_id"),
        ProjectMatchDecision.evidence_id.label("evidence_id"),
    ).where(
        ProjectMatchDecision.candidate_project_id.in_(project_ids),
        ProjectMatchDecision.decision == "matched",
        ProjectMatchDecision.evidence_id.is_not(None),
    )
    lifecycle_link = select(
        LifecycleEvent.project_id.label("project_id"),
        LifecycleEvent.evidence_id.label("evidence_id"),
    ).where(LifecycleEvent.project_id.in_(project_ids))
    links = union(direct_link, need_link, package_link, match_link, lifecycle_link).subquery()
    evidence_rows = session.execute(
        select(links.c.project_id, Evidence, Observation)
        .join(Evidence, Evidence.id == links.c.evidence_id)
        .join(Observation, Observation.id == Evidence.observation_id)
        .order_by(links.c.project_id, Evidence.observed_at, Evidence.id)
    ).all()
    citations_by_project: dict[str, list[dict]] = defaultdict(list)
    for project_id, evidence, observation in evidence_rows:
        if not evidence.url:
            continue
        citations_by_project[str(project_id)].append(
            {
                "evidence_id": str(evidence.id),
                "observation_id": str(observation.id),
                "source_id": observation.source_id,
                "url": evidence.url,
                "title": evidence.title,
                "excerpt": (
                    (evidence.abstract or "").split(
                        "\nOpaque source bytes (base64; not interpreted): ", 1
                    )[0]
                )[:800],
                "excerpt_truncated": len(
                    (evidence.abstract or "").split(
                        "\nOpaque source bytes (base64; not interpreted): ", 1
                    )[0]
                ) > 800,
                "published_at": evidence.published_at.isoformat()
                if evidence.published_at
                else None,
                "observed_at": evidence.observed_at.isoformat()
                if evidence.observed_at
                else None,
                "extraction_location": evidence.extraction_location,
                "evidence_hash": evidence.content_hash,
                "observation_hash": observation.content_hash,
                "source_provenance": _snapshot_source_provenance(evidence.abstract),
            }
        )

    needs_by_project: dict[str, list[dict]] = defaultdict(list)
    need_rows = session.scalars(
        select(PowerNeed)
        .where(PowerNeed.project_id.in_(project_ids), PowerNeed.active.is_(True))
        .order_by(PowerNeed.project_id, PowerNeed.activity_key)
    )
    for need in need_rows:
        needs_by_project[str(need.project_id)].append(
            {
                "need_id": str(need.id),
                "activity_key": need.activity_key,
                "tier": need.tier,
                "required_mw": need.required_mw,
                "start_window": need.start_window,
                "duration": need.duration,
                "supply": need.supply,
                "rationale": need.rationale,
                "admission_basis": need.admission_basis,
            }
        )

    memberships_by_project: dict[str, list[dict]] = defaultdict(list)
    for membership in session.scalars(
        select(CompanyProjectMembership)
        .where(
            CompanyProjectMembership.project_id.in_(project_ids),
            CompanyProjectMembership.state == "current",
        )
        .order_by(CompanyProjectMembership.project_id, CompanyProjectMembership.id)
    ):
        memberships_by_project[str(membership.project_id)].append(
            {
                "company_identity_id": str(membership.company_identity_id),
                "organization": membership.organization_name,
                "role": membership.role,
                "source_id": membership.source_id,
                "source_evidence_id": str(membership.source_evidence_id),
                "source_version_hash": membership.source_version_hash,
            }
        )

    lifecycles = {
        str(item.project_id): item
        for item in session.scalars(
            select(ProjectLifecycle).where(ProjectLifecycle.project_id.in_(project_ids))
        )
    }
    candidates = []
    for project in projects:
        candidate_id = str(project.id)
        source_evidence = citations_by_project.get(candidate_id, [])
        if not source_evidence:
            continue
        lifecycle = lifecycles.get(candidate_id)
        citation_evidence_hashes = {
            citation["evidence_hash"] for citation in source_evidence
        }
        linked_needs = [
            need
            for need in needs_by_project.get(candidate_id, [])
            if (need.get("admission_basis") or {}).get("evidence_hash")
            in citation_evidence_hashes
        ]
        supported_need_intervals: list[tuple[Decimal, Decimal]] = []
        for need in linked_needs:
            interval = _required_mw_interval(need.get("required_mw"))
            if interval:
                supported_need_intervals.append(interval)
        if any(low >= Decimal("0.3") for low, _high in supported_need_intervals):
            floor_status = "SOURCE_LINKED_TYPED_NEED_AT_OR_ABOVE_300_KW"
        elif supported_need_intervals and all(
            high < Decimal("0.3") for _low, high in supported_need_intervals
        ):
            floor_status = "SOURCE_LINKED_TYPED_NEED_BELOW_300_KW"
        elif any(low < Decimal("0.3") <= high for low, high in supported_need_intervals):
            floor_status = "SOURCE_LINKED_NEED_RANGE_CROSSES_300_KW"
        elif linked_needs:
            floor_status = "UNKNOWN_OR_UNSUPPORTED_NEED_POWER_BASIS"
        else:
            floor_status = "UNKNOWN_OR_NO_SOURCE_LINKED_TYPED_NEED"
        activity_status = (
            "SOURCE_LINKED_TEMPORARY_OR_BRIDGE_ACTIVITY"
            if _temporary_activity_supported(linked_needs)
            else "UNKNOWN_OR_UNSUPPORTED_ACTIVITY"
        )
        timing_status = (
            "HAS_TYPED_NEED_OR_LIFECYCLE_TIMING"
            if any(need.get("start_window") and need.get("duration") for need in linked_needs)
            or (
                lifecycle
                and (lifecycle.time_to_power_start or lifecycle.time_to_power_end)
            )
            else "UNKNOWN"
        )
        company_status = (
            "HAS_SOURCE_LINKED_CURRENT_PROJECT_ORGANIZATION"
            if any(
                membership["source_version_hash"] in citation_evidence_hashes
                for membership in memberships_by_project.get(candidate_id, [])
            )
            else "UNKNOWN_OR_NO_SOURCE_LINKED_ORGANIZATION"
        )
        supply_status = (
            "HAS_NON_UNKNOWN_SUPPLY_ASSERTION"
            if any(
                need.get("supply")
                and str(need.get("supply")).casefold() != "unknown"
                for need in needs_by_project.get(candidate_id, [])
            )
            else "UNKNOWN"
        )
        baseline_unknowns = ["independent project identity adjudication"]
        if activity_status == "UNKNOWN_OR_UNSUPPORTED_ACTIVITY":
            baseline_unknowns.append("source-supported temporary/rental-power relevance")
        if floor_status in {
            "UNKNOWN_OR_NO_SOURCE_LINKED_TYPED_NEED",
            "UNKNOWN_OR_UNSUPPORTED_NEED_POWER_BASIS",
            "SOURCE_LINKED_NEED_RANGE_CROSSES_300_KW",
        }:
            baseline_unknowns.append("source-supported 300 kW floor")
        if timing_status == "UNKNOWN":
            baseline_unknowns.append("current/future need date and duration")
        if supply_status == "UNKNOWN":
            baseline_unknowns.append("committed supply and residual gap")
        baseline_unknowns.append("buyer organization and buying authority")
        baseline_unknowns.extend(
            [
                "project-connected contact and attributable business method",
                "independent mailbox verification",
                "contact and buyer relevance not adjudicated at freeze time",
            ]
        )
        candidates.append(
            {
                "project_id": candidate_id,
                "name": project.name,
                "location": project.location,
                "region_status": project.region_status,
                "region_state": project.region_state,
                "region_reason": project.region_reason,
                "asset_type": project.asset_type,
                "source_id": project.source_id,
                "external_id": project.external_id,
                "identity_key": project.identity_key,
                "identity_facts": project.identity_facts or {},
                "source_evidence": source_evidence,
                "active_power_needs": needs_by_project.get(candidate_id, []),
                "company_assertions": memberships_by_project.get(candidate_id, []),
                "lifecycle": (
                    {
                        "current_state": lifecycle.current_state,
                        "expected_next_milestone": lifecycle.expected_next_milestone,
                        "expected_power_event": lifecycle.expected_power_event,
                        "time_to_power_start": lifecycle.time_to_power_start.isoformat()
                        if lifecycle.time_to_power_start
                        else None,
                        "time_to_power_end": lifecycle.time_to_power_end.isoformat()
                        if lifecycle.time_to_power_end
                        else None,
                        "open_questions": lifecycle.open_questions or [],
                    }
                    if lifecycle
                    else None
                ),
                "baseline_unknowns": baseline_unknowns,
                "baseline_status": {
                    "power_floor_300kw": floor_status,
                    "temporary_power_activity": activity_status,
                    "need_timing": timing_status,
                    "project_organization": company_status,
                    "power_supply": supply_status,
                    "contact_research": "NOT_ADJUDICATED_AT_FREEZE_TIME",
                    "buying_chain_claim_history": "EXCLUDED_FROM_BASELINE_ADJUDICATION",
                },
            }
        )
    return candidates, {
        "eligible_territory_projects": len(projects),
        "cited_project_candidates": len(candidates),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    url = make_url(args.database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or (
        url.database != args.expected_database_name
    ):
        parser.error("requires the exact loopback database identity")
    if args.output.exists():
        parser.error("refusing to overwrite frozen cohort manifest")
    if not 1 <= args.limit <= 100:
        parser.error("limit must be between 1 and 100")

    engine = create_engine(
        url,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    try:
        with Session(engine) as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            candidates, counts = _read_native_candidates(session)
            selected = select_frozen_candidates(candidates, limit=args.limit)
    finally:
        engine.dispose()

    result = {
        "kind": "frozen_native_source_project_record_cohort",
        "measured_at": datetime.now(UTC).isoformat(),
        "source_database": args.expected_database_name,
        "requested_projects": args.limit,
        "selected_projects": len(selected),
        "cohort_complete": len(selected) == args.limit,
        "selection_frozen_before_contact_research": True,
        "contact_or_commercial_outcome_fields_used_for_selection": False,
        "cohort_interpretation": (
            "25 distinct source-linked native project records; physical site distinctness "
            "is unverified where sources provide only county-level locations."
        ),
        "selection_rule": (
            "Use ELIGIBLE TX/OK/NM native canonical projects with name, physical location, "
            "and at least one linked HTTP(S) evidence URL plus observed and evidence hashes. "
            "Deduplicate by normalized location assertion (exact location for numeric street/route "
            "locations; name+location for coarse city/county locations and RRC county-code "
            "assertions). Select stable SHA-256 "
            "order round-robin across observed state/asset-type strata."
        ),
        "candidate_counts": counts,
        "stratum_counts": dict(Counter(item["selection_stratum"] for item in selected)),
        "commercial_qualification_status": "NOT_ADJUDICATED; missing thresholds remain failures/unknowns",
        "paid_calls": 0,
        "projects": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Frozen {len(selected)}/{args.limit} native source candidates: {args.output}")
    return 0 if len(selected) == args.limit else 2


if __name__ == "__main__":
    sys.exit(main())
