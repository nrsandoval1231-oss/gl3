"""Sector-aware selection of one primary customer identity per project."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

CUSTOMER_ROLE_ORDER = {
    "owner_developer": 0,
    "owner_energy": 1,
    "owner_construction": 2,
    "asset_operator": 3,
}
OWNER_ROLES = ("owner_developer", "owner_energy", "owner_construction")


@dataclass(frozen=True)
class PrimaryRoleSelection:
    """The safe primary account projection for one project."""

    status: Literal["selected", "none", "conflict"]
    company_identity_id: UUID | None = None
    organization_name: str | None = None
    role: str | None = None


def project_sectors(session, project_ids, *, generation_id=None) -> dict[UUID, str]:
    """Read sector labels from the exact saved-browse generation being projected."""
    ids = set(project_ids)
    if not ids:
        return {}
    if generation_id is None:
        from gridlens.intelligence.saved_browse import current_generation

        try:
            generation_id = current_generation(session).id
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            # Raw project/account APIs remain usable before the first browse
            # generation. Unknown sector preserves conservative conflict rules.
            return {project_id: "unknown" for project_id in ids}
    rows = session.execute(
        text(
            "SELECT project_id, compact #>> '{project_metadata,sector}' AS sector "
            "FROM browse_rows WHERE generation_id=:generation AND "
            "project_id = ANY(CAST(:project_ids AS uuid[]))"
        ),
        {"generation": generation_id, "project_ids": [str(value) for value in ids]},
    ).all()
    by_project = defaultdict(set)
    for project_id, sector in rows:
        if sector:
            by_project[project_id].add(sector)
    return {
        project_id: (
            next(iter(sectors))
            if len(sectors) == 1 and next(iter(sectors)) in {"oil_gas", "data_centers"}
            else "unknown"
        )
        for project_id in ids
        for sectors in [by_project.get(project_id, set())]
    }


def select_primary_roles(
    rows,
    sectors_by_project: dict[UUID, str],
    blocked_project_ids=(),
    blocked_owner_project_ids=(),
) -> dict[UUID, PrimaryRoleSelection]:
    """Choose primary customer roles without erasing source-backed relationships.

    `rows` contains `(identity_id, project_id, claim)` triples. A blocked project
    has an authoritative retraction/conflict on its primary source relationship;
    lower-priority roles cannot silently replace it.
    """
    by_project = defaultdict(list)
    for identity_id, project_id, claim in rows:
        role = getattr(claim, "category", None)
        if identity_id is not None and role in CUSTOMER_ROLE_ORDER:
            by_project[project_id].append((identity_id, claim))

    blocked = set(blocked_project_ids)
    blocked_owners = set(blocked_owner_project_ids)
    all_projects = set(sectors_by_project) | set(by_project) | blocked | blocked_owners
    result: dict[UUID, PrimaryRoleSelection] = {}
    for project_id in all_projects:
        candidates = by_project.get(project_id, [])
        if not candidates:
            result[project_id] = PrimaryRoleSelection(
                "conflict" if project_id in blocked or project_id in blocked_owners else "none"
            )
            continue

        sector = sectors_by_project.get(project_id, "unknown")
        if sector == "oil_gas":
            if project_id in blocked:
                result[project_id] = PrimaryRoleSelection("conflict")
                continue
            operators = [row for row in candidates if row[1].category == "asset_operator"]
            if not operators and project_id in blocked_owners:
                result[project_id] = PrimaryRoleSelection("conflict")
                continue
            primary = operators or [row for row in candidates if row[1].category in OWNER_ROLES]
        elif sector == "data_centers":
            owners = [row for row in candidates if row[1].category in OWNER_ROLES]
            if not owners and (project_id in blocked or project_id in blocked_owners):
                result[project_id] = PrimaryRoleSelection("conflict")
                continue
            primary = owners or [row for row in candidates if row[1].category == "asset_operator"]
        else:
            if project_id in blocked or project_id in blocked_owners:
                result[project_id] = PrimaryRoleSelection("conflict")
                continue
            primary = candidates

        if not primary:
            result[project_id] = PrimaryRoleSelection("none")
            continue
        identities = {identity_id for identity_id, _claim in primary}
        if len(identities) != 1:
            result[project_id] = PrimaryRoleSelection("conflict")
            continue

        identity_id = next(iter(identities))
        selected_identity_rows = [row for row in primary if row[0] == identity_id]
        selected_identity_rows.sort(
            key=lambda row: (
                CUSTOMER_ROLE_ORDER[row[1].category],
                row[1].category,
                (row[1].organization or "").casefold(),
                row[1].organization or "",
            )
        )
        claim = selected_identity_rows[0][1]
        result[project_id] = PrimaryRoleSelection(
            "selected", identity_id, claim.organization, claim.category
        )
    return result
