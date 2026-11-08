"""Shared retained-source shortlist assessment for project and account reads."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from datetime import date
from threading import RLock
from typing import Any
from uuid import UUID

from sqlalchemy import text

from gridlens.domain.opportunity_shortlist import POLICY_VERSION, shortlist_assessment
from gridlens.intelligence.project_results import _current_jev_decisions

_CACHE: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
_INPUT_CACHE: OrderedDict[tuple, tuple[list[dict[str, Any]], list[str]]] = OrderedDict()
_CACHE_LIMIT = 8
_CACHE_LOCK = RLock()


def _physical_duplicate_components(
    duplicate_groups: dict[str, set[UUID]], rows: list[dict[str, Any]]
) -> list[set[UUID]]:
    """Close coverage groups over authoritative API identity, then fail closed."""
    physical_ids_by_project: dict[UUID, set[str]] = {}
    well_api_projects: dict[str, set[UUID]] = {}
    for row in rows:
        if row.get("physical_identity"):
            physical_ids_by_project.setdefault(row["project_id"], set()).add(
                row["physical_identity"]
            )
            kind, separator, value = row["physical_identity"].partition(":")
            if (
                separator
                and kind == "us_well_api"
                and re.fullmatch(r"[0-9]{10}(?:[0-9]{2}){0,2}", value)
            ):
                well_api_projects.setdefault(value, set()).add(row["project_id"])
    components: list[set[UUID]] = []
    coverage_projects = (
        set().union(*(projects for projects in duplicate_groups.values() if len(projects) > 1))
        if duplicate_groups
        else set()
    )
    # These validated identities already define one physical site in the shared
    # project serializer. Include every sibling before applying coverage edges,
    # so a permit pair cannot split one API asset into two account assets.
    for projects in (*duplicate_groups.values(), *well_api_projects.values()):
        if len(projects) < 2:
            continue
        overlaps = [component for component in components if component & projects]
        merged = set(projects)
        for component in overlaps:
            merged.update(component)
            components.remove(component)
        components.append(merged)
    # Validate after transitively merging every coverage edge. Checking each
    # edge independently lets a project with no ID bridge two known distinct sites.
    return [
        component
        for component in components
        if component & coverage_projects
        if len(set().union(*(physical_ids_by_project.get(project, set()) for project in component)))
        <= 1
    ]


def assess_generation(session, generation) -> dict[str, Any]:
    """Assess one saved generation without pagination truncation.

    The request/session-local reuse avoids classifying the same corpus once per
    account child page. Results contain only retained evidence assessment data.
    """
    transaction = session.get_transaction()
    request_key = (
        str(generation.id),
        generation.digest,
        date.today().isoformat(),
        POLICY_VERSION,
    )
    request_cache = session.info.get("account_shortlist_request_cache")
    if (
        transaction is not None
        and request_cache
        and request_cache[0] is transaction
        and request_cache[1] == request_key
    ):
        cached_result = request_cache[2]
        current_decisions = _current_jev_decisions(session, cached_result["evidence_ids"])
        current_digest = hashlib.sha256(
            json.dumps(sorted(current_decisions.items()), separators=(",", ":")).encode()
        ).hexdigest()
        if current_digest == cached_result["jev_map_digest"]:
            return cached_result
    input_key = request_key
    with _CACHE_LOCK:
        cached_input = _INPUT_CACHE.get(input_key)
        if cached_input is not None:
            _INPUT_CACHE.move_to_end(input_key)
    rows = None
    if cached_input is None:
        rows = (
            session.execute(
                text(
                    "SELECT need_id, project_id, summary, compact "
                    "FROM browse_rows WHERE generation_id=:generation"
                ),
                {"generation": generation.id},
            )
            .mappings()
            .all()
        )
        lightweight_rows = []
        for row in rows:
            metadata = (row["compact"] or {}).get("project_metadata") or {}
            identity = metadata.get("asset_identity") or {}
            kind = str(identity.get("kind") or "").strip().lower()
            value = str(identity.get("value") or "").strip().lower()
            physical_identity = (
                f"{kind}:{value}"
                if identity.get("identity_validated") is True and kind and value
                else None
            )
            lightweight_rows.append(
                {
                    "need_id": row["need_id"],
                    "project_id": row["project_id"],
                    "physical_identity": physical_identity,
                }
            )
        evidence_ids = sorted(
            {
                str(ev["id"])
                for row in rows
                for ev in (row["summary"] or {}).get("evidence", [])
                if ev.get("id") and ev.get("assessment_current") is True
            }
        )
    else:
        lightweight_rows, evidence_ids = cached_input
    decisions = _current_jev_decisions(session, evidence_ids) if evidence_ids else {}
    digest = hashlib.sha256(
        json.dumps(sorted(decisions.items()), separators=(",", ":")).encode()
    ).hexdigest()
    cache_key = (
        str(generation.id),
        generation.digest,
        date.today().isoformat(),
        POLICY_VERSION,
        digest,
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            _CACHE.move_to_end(cache_key)
    if cached is not None:
        session.info["account_shortlist_request_cache"] = (
            session.get_transaction(),
            request_key,
            cached,
        )
        return cached
    if rows is None:
        rows = (
            session.execute(
                text(
                    "SELECT need_id, project_id, summary, compact "
                    "FROM browse_rows WHERE generation_id=:generation"
                ),
                {"generation": generation.id},
            )
            .mappings()
            .all()
        )
    sources: dict[str, dict[str, Any]] = {}
    if evidence_ids:
        evidence = (
            session.execute(
                text("""SELECT e.id,e.title,e.abstract,e.url,e.published_at,e.event_date,
                e.event_date_label,o.source_id FROM evidence e
                JOIN observations o ON o.id=e.observation_id
            WHERE e.id=ANY(CAST(:ids AS uuid[]))"""),
                {"ids": evidence_ids},
            )
            .mappings()
            .all()
        )
        sources = {
            str(row["id"]): {
                **dict(row),
                "id": str(row["id"]),
                "text": row["abstract"],
                "jev_decision": decisions.get(str(row["id"])),
            }
            for row in evidence
        }
    else:
        decisions = {}
    assessments: dict[str, dict[str, Any]] = {}
    eligible: list[UUID] = []
    priority: dict[UUID, int] = {}
    for row in rows:
        summary = row["summary"] or {}
        refs = [
            {**sources[str(ev["id"])], "assessment_current": True}
            for ev in summary.get("evidence", [])
            if str(ev.get("id")) in sources
            and ev.get("assessment_current") is True
            and ev.get("source_id") == sources[str(ev["id"])].get("source_id")
        ]
        result = shortlist_assessment({**summary, **(row["compact"] or {})}, refs)
        assessments[str(row["need_id"])] = result
        if result.get("eligible"):
            eligible.append(row["need_id"])
            priority[row["need_id"]] = int(result.get("priority") or 0)
    duplicate_groups: dict[str, set[UUID]] = {}
    for row in rows:
        key = assessments[str(row["need_id"])].get("duplicate_key")
        if key:
            duplicate_groups.setdefault(key, set()).add(row["project_id"])
    components = _physical_duplicate_components(duplicate_groups, lightweight_rows)
    duplicate_map: dict[UUID, UUID] = {}
    for component in components:
        root = min(component, key=str)
        duplicate_map.update({project: root for project in component})
    result = {
        "rows": lightweight_rows,
        "assessments": assessments,
        "eligible_need_ids": eligible,
        "priority_by_need": priority,
        "duplicate_project_map": duplicate_map,
        "jev_map_digest": digest,
        "evidence_ids": evidence_ids,
    }
    with _CACHE_LOCK:
        _CACHE[cache_key] = result
        _CACHE.move_to_end(cache_key)
        _INPUT_CACHE[input_key] = (lightweight_rows, evidence_ids)
        _INPUT_CACHE.move_to_end(input_key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        while len(_INPUT_CACHE) > _CACHE_LIMIT:
            _INPUT_CACHE.popitem(last=False)
    session.info["account_shortlist_request_cache"] = (
        session.get_transaction(),
        request_key,
        result,
    )
    return result
