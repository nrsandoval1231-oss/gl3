"""Conservative, reversible canonical links between source-backed power needs.

An alias is accepted only when one retained current evidence version is linked
to both needs, its structured source provenance identifies each source record
and package scope, and the retained source text explicitly contains those
references. Names, project identity, addresses, activity labels, and shared
observations are not alias evidence.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from gridlens.persistence.commercial_pursuit_models import CommercialPursuit
from gridlens.persistence.models import (
    Evidence,
    NeedAliasAssertion,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)

# Shared with commercial-pursuit creation so alias activation and pursuit
# creation cannot observe different equivalence components in one race.
NEED_ALIAS_PURSUIT_LOCK = 73510921


class NeedAliasError(ValueError):
    """An alias request is unsafe or unsupported by retained current evidence."""


@dataclass(frozen=True)
class NeedAliasResolution:
    root_need_id: UUID
    member_need_ids: tuple[UUID, ...]
    existing_pursuit: CommercialPursuit | None
    conflicted: bool = False


def lock_need_alias_pursuits(session: Session) -> None:
    """Serialize alias graph changes and pursuit creation in this transaction."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": NEED_ALIAS_PURSUIT_LOCK},
    )


def _source_ref(project: Project) -> str:
    return f"{project.source_id}:{project.external_id}"


def _need_binding(need: PowerNeed, project: Project, package_scope: str) -> dict[str, str]:
    return {
        "source_ref": _source_ref(project),
        "activity_key": need.activity_key,
        "package_scope": package_scope,
    }


def _same_package_quote(left: dict[str, str], right: dict[str, str]) -> str:
    return (
        f"Package {left['package_scope']}: {left['source_ref']} ({left['activity_key']}) and "
        f"{right['source_ref']} ({right['activity_key']}) refer to the same power package."
    )


def _retained_quote_is_unambiguous(
    evidence: Evidence, observation: Observation, package_scope: str, allowed_quotes: set[str]
) -> bool:
    # The complete, exact source line is the proof. Merely finding each token
    # separately would also accept explicitly contradictory/separate packages.
    lines = {
        line
        for text_value in (
            evidence.title,
            evidence.abstract,
            observation.title,
            observation.abstract,
        )
        if text_value
        for line in text_value.splitlines()
    }
    scoped_lines = {line for line in lines if line.startswith(f"Package {package_scope}:")}
    return bool(scoped_lines) and scoped_lines.issubset(allowed_quotes)


def _current_evidence_basis(
    session: Session,
    alias_need_id: UUID,
    canonical_need_id: UUID,
    evidence_id: UUID,
    expected_evidence_hash: str,
    package_scope: str,
) -> dict[str, object]:
    if not isinstance(package_scope, str) or not package_scope.strip():
        raise NeedAliasError("A nonblank package scope is required")
    evidence = session.get(Evidence, evidence_id)
    observation = session.get(Observation, evidence.observation_id) if evidence else None
    alias_need = session.get(PowerNeed, alias_need_id)
    canonical_need = session.get(PowerNeed, canonical_need_id)
    if evidence is None or observation is None or alias_need is None or canonical_need is None:
        raise NeedAliasError("Alias evidence and both needs must be retained")
    if not alias_need.active or not canonical_need.active:
        raise NeedAliasError("Both needs must be current and active")
    if (
        evidence.content_hash != expected_evidence_hash
        or observation.content_hash != expected_evidence_hash
        or evidence.observation_id != observation.id
    ):
        raise NeedAliasError("Alias evidence version is no longer current")
    linked_need_ids = set(
        session.scalars(
            select(NeedObservation.need_id).where(
                NeedObservation.observation_id == observation.id,
                NeedObservation.need_id.in_([alias_need_id, canonical_need_id]),
            )
        ).all()
    )
    if linked_need_ids != {alias_need_id, canonical_need_id}:
        raise NeedAliasError("Retained evidence must be linked to both needs")
    alias_project = session.get(Project, alias_need.project_id)
    canonical_project = session.get(Project, canonical_need.project_id)
    if alias_project is None or canonical_project is None:
        raise NeedAliasError("Both needs must retain their source projects")
    alias_binding = _need_binding(alias_need, alias_project, package_scope)
    canonical_binding = _need_binding(canonical_need, canonical_project, package_scope)
    bindings = [alias_binding, canonical_binding]
    if (
        alias_binding["source_ref"] == canonical_binding["source_ref"]
        and alias_binding["activity_key"] == canonical_binding["activity_key"]
    ):
        raise NeedAliasError("Alias needs must have distinct source-record and activity bindings")
    allowed_quotes = {
        _same_package_quote(alias_binding, canonical_binding),
        _same_package_quote(canonical_binding, alias_binding),
    }
    provenance = evidence.provenance if isinstance(evidence.provenance, dict) else {}
    claim = provenance.get("need_alias_assertion")
    if not isinstance(claim, dict):
        raise NeedAliasError("Evidence lacks explicit need-alias package support")
    claim_scope = claim.get("package_scope")
    claim_bindings = claim.get("need_bindings")
    source_quote = claim.get("same_package_quote")
    if (
        claim_scope != package_scope
        or not isinstance(claim_bindings, list)
        or len(claim_bindings) != 2
        or _claim_binding_keys(claim_bindings) != _binding_keys(bindings)
        or not isinstance(source_quote, str)
        or source_quote not in allowed_quotes
    ):
        raise NeedAliasError("Evidence does not support both source records in this package scope")
    if not _retained_quote_is_unambiguous(evidence, observation, package_scope, allowed_quotes):
        raise NeedAliasError("Retained source must contain one exact affirmative same-package line")
    return {
        "package_scope": package_scope,
        "need_bindings": sorted(
            bindings, key=lambda binding: (binding["source_ref"], binding["activity_key"])
        ),
        "same_package_quote": source_quote,
        "evidence_id": str(evidence.id),
        "evidence_hash": expected_evidence_hash,
    }


def _binding_key(binding: dict[str, object]) -> tuple[str, str, str] | None:
    values = tuple(binding.get(field) for field in ("source_ref", "activity_key", "package_scope"))
    if not all(isinstance(value, str) for value in values):
        return None
    return values  # type: ignore[return-value]


def _binding_keys(bindings: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {
        (binding["source_ref"], binding["activity_key"], binding["package_scope"])
        for binding in bindings
    }


def _claim_binding_keys(bindings: object) -> set[tuple[str, str, str]]:
    if not isinstance(bindings, list) or len(bindings) != 2:
        return set()
    keys = [_binding_key(binding) for binding in bindings if isinstance(binding, dict)]
    if len(keys) != 2 or any(key is None for key in keys):
        return set()
    return set(keys)  # type: ignore[arg-type]


def _current_assertions(session: Session) -> list[NeedAliasAssertion]:
    rows = session.scalars(
        select(NeedAliasAssertion).where(NeedAliasAssertion.state == "current")
    ).all()
    if not rows:
        return []
    need_ids = {row.alias_need_id for row in rows} | {row.canonical_need_id for row in rows}
    evidence_ids = {row.evidence_id for row in rows}
    evidences = {
        row.id: row
        for row in session.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids)))
    }
    observation_ids = {row.observation_id for row in evidences.values()}
    observations = {
        row.id: row
        for row in session.scalars(select(Observation).where(Observation.id.in_(observation_ids)))
    }
    linked = set(
        session.execute(
            select(NeedObservation.observation_id, NeedObservation.need_id).where(
                NeedObservation.observation_id.in_(observation_ids),
                NeedObservation.need_id.in_(need_ids),
            )
        ).all()
    )
    bindings_by_need = {
        need_id: {
            "source_ref": f"{source_id}:{external_id}",
            "activity_key": activity_key,
            "active": active,
        }
        for need_id, activity_key, active, source_id, external_id in session.execute(
            select(
                PowerNeed.id,
                PowerNeed.activity_key,
                PowerNeed.active,
                Project.source_id,
                Project.external_id,
            )
            .join(Project, Project.id == PowerNeed.project_id)
            .where(PowerNeed.id.in_(need_ids))
        ).all()
    }
    valid: list[NeedAliasAssertion] = []
    for row in rows:
        evidence = evidences.get(row.evidence_id)
        observation = observations.get(evidence.observation_id) if evidence else None
        provenance = (
            evidence.provenance
            if evidence is not None and isinstance(evidence.provenance, dict)
            else {}
        )
        claim = provenance.get("need_alias_assertion")
        alias_need_binding = bindings_by_need.get(row.alias_need_id)
        canonical_need_binding = bindings_by_need.get(row.canonical_need_id)
        alias_binding = (
            {
                "source_ref": alias_need_binding["source_ref"],
                "activity_key": alias_need_binding["activity_key"],
                "package_scope": row.package_scope,
            }
            if alias_need_binding is not None
            else None
        )
        canonical_binding = (
            {
                "source_ref": canonical_need_binding["source_ref"],
                "activity_key": canonical_need_binding["activity_key"],
                "package_scope": row.package_scope,
            }
            if canonical_need_binding is not None
            else None
        )
        expected_bindings = (
            _binding_keys([alias_binding, canonical_binding])
            if alias_binding is not None and canonical_binding is not None
            else set()
        )
        claim_bindings = claim.get("need_bindings") if isinstance(claim, dict) else None
        claim_binding_set = _claim_binding_keys(claim_bindings)
        allowed_quotes = (
            {
                _same_package_quote(alias_binding, canonical_binding),
                _same_package_quote(canonical_binding, alias_binding),
            }
            if alias_binding is not None and canonical_binding is not None
            else set()
        )
        source_quote = claim.get("same_package_quote") if isinstance(claim, dict) else None
        if (
            evidence is None
            or observation is None
            or alias_need_binding is None
            or canonical_need_binding is None
            or evidence.content_hash != row.evidence_hash
            or observation.content_hash != row.evidence_hash
            or (observation.id, row.alias_need_id) not in linked
            or (observation.id, row.canonical_need_id) not in linked
            or not isinstance(claim, dict)
            or claim.get("package_scope") != row.package_scope
            or len(expected_bindings) != 2
            or claim_binding_set != expected_bindings
            or not isinstance(source_quote, str)
            or source_quote not in allowed_quotes
            or not _retained_quote_is_unambiguous(
                evidence, observation, row.package_scope, allowed_quotes
            )
        ):
            continue
        valid.append(row)
    return valid


def _component(session: Session, need_id: UUID) -> tuple[UUID, tuple[UUID, ...], bool]:
    directed = {row.alias_need_id: row.canonical_need_id for row in _current_assertions(session)}
    if set(directed.values()).intersection(directed):
        raise NeedAliasError("Need alias graph contains a chain; do not flatten its root")
    root = need_id
    visited: set[UUID] = set()
    while root in directed:
        if root in visited:
            raise NeedAliasError("Need alias graph contains a cycle")
        visited.add(root)
        root = directed[root]

    members = {root}
    changed = True
    while changed:
        changed = False
        for alias, canonical in directed.items():
            if canonical in members and alias not in members:
                members.add(alias)
                changed = True
    if need_id not in members:
        members.add(need_id)
    latest_versions = (
        select(
            NeedAliasAssertion.alias_need_id,
            func.max(NeedAliasAssertion.version).label("latest_version"),
        )
        .where(NeedAliasAssertion.alias_need_id.in_(members))
        .group_by(NeedAliasAssertion.alias_need_id)
        .subquery()
    )
    conflict = bool(
        session.scalar(
            select(NeedAliasAssertion.id)
            .join(
                latest_versions,
                (NeedAliasAssertion.alias_need_id == latest_versions.c.alias_need_id)
                & (NeedAliasAssertion.version == latest_versions.c.latest_version),
            )
            .where(NeedAliasAssertion.state == "conflicted")
            .limit(1)
        )
    )
    return root, tuple(sorted(members, key=str)), conflict


def resolve_component(session: Session, need_id: UUID) -> NeedAliasResolution:
    """Resolve current evidence-backed aliases and return any saved pursuit."""
    root, members, conflicted = _component(session, need_id)
    if conflicted:
        # A conflicted proposal is deliberately not a redirect. Do not select
        # one of several old pursuits (or show the proposal as a current group).
        return NeedAliasResolution(root, members, None, True)
    pursuits = session.scalars(
        select(CommercialPursuit)
        .where(CommercialPursuit.need_id.in_(members))
        .order_by(CommercialPursuit.created_at, CommercialPursuit.id)
    ).all()
    if len(pursuits) > 1:
        return NeedAliasResolution(root, members, None, True)
    return NeedAliasResolution(root, members, pursuits[0] if pursuits else None, conflicted)


def canonical_need_map(session: Session) -> dict[UUID, UUID]:
    """Return strict current alias-to-persisted-root mappings for read models.

    Unaliased needs are intentionally omitted; callers use the original ID as
    their default. This batches evidence validation over the whole overlay and
    refuses to flatten any malformed chain or cycle.
    """
    directed = {row.alias_need_id: row.canonical_need_id for row in _current_assertions(session)}
    if set(directed.values()).intersection(directed):
        raise NeedAliasError("Need alias graph contains a chain or cycle; refusing to flatten")
    return directed


def need_alias_members(session: Session, need_ids: Iterable[UUID]) -> dict[UUID, tuple[UUID, ...]]:
    """Batch current alias-component membership for pursuit-list projections."""
    requested = set(need_ids)
    if not requested:
        return {}
    directed = {row.alias_need_id: row.canonical_need_id for row in _current_assertions(session)}
    if set(directed.values()).intersection(directed):
        raise NeedAliasError("Need alias graph contains a chain; do not flatten its root")
    adjacency: dict[UUID, set[UUID]] = {}
    for alias, canonical in directed.items():
        adjacency.setdefault(alias, set()).add(canonical)
        adjacency.setdefault(canonical, set()).add(alias)
    result: dict[UUID, tuple[UUID, ...]] = {}
    for need_id in requested:
        component = {need_id}
        pending = [need_id]
        while pending:
            node = pending.pop()
            for neighbor in adjacency.get(node, ()):
                if neighbor not in component:
                    component.add(neighbor)
                    pending.append(neighbor)
        result[need_id] = tuple(sorted(component, key=str))
    return result


def record_alias(
    session: Session,
    alias_need_id: UUID,
    canonical_need_id: UUID,
    evidence_id: UUID,
    expected_evidence_hash: str,
    package_scope: str,
    reason: str,
) -> NeedAliasAssertion:
    """Append a current alias version after strict evidence and pursuit checks.

    A conflict with multiple existing pursuit histories is retained in the
    ``conflicted`` state, without redirecting either saved pursuit.
    """
    if not reason.strip():
        raise NeedAliasError("Alias assertion reason is required")
    if alias_need_id == canonical_need_id:
        raise NeedAliasError("A need cannot alias itself")
    lock_need_alias_pursuits(session)
    # A correction can share the caller's read transaction; discard its projection memo.
    session.info.pop("customer_need_alias_map", None)
    basis = _current_evidence_basis(
        session,
        alias_need_id,
        canonical_need_id,
        evidence_id,
        expected_evidence_hash,
        package_scope,
    )
    incoming = session.scalar(
        select(NeedAliasAssertion.id)
        .where(
            NeedAliasAssertion.canonical_need_id == alias_need_id,
            NeedAliasAssertion.state == "current",
        )
        .limit(1)
    )
    if incoming is not None:
        raise NeedAliasError(
            "This need is already a canonical target; retract incoming aliases before reparenting"
        )
    latest = session.scalar(
        select(NeedAliasAssertion)
        .where(NeedAliasAssertion.alias_need_id == alias_need_id)
        .order_by(NeedAliasAssertion.version.desc())
        .with_for_update()
    )
    if (
        latest is not None
        and latest.state in {"current", "conflicted", "retracted"}
        and latest.canonical_need_id == canonical_need_id
        and latest.evidence_id == evidence_id
        and latest.evidence_hash == expected_evidence_hash
        and latest.package_scope == package_scope
        and latest.reason == reason.strip()
    ):
        return latest
    root, members, _ = _component(session, canonical_need_id)
    if root != canonical_need_id or alias_need_id in members:
        raise NeedAliasError("Aliases must point directly to a distinct canonical root")
    current = latest if latest is not None and latest.state == "current" else None
    if current is not None:
        current.state = "superseded"
        session.flush()
    members = tuple(set(members) | {alias_need_id})
    existing_count = (
        session.scalar(
            select(func.count(CommercialPursuit.id)).where(CommercialPursuit.need_id.in_(members))
        )
        or 0
    )
    previous_version = (
        session.scalar(
            select(func.max(NeedAliasAssertion.version)).where(
                NeedAliasAssertion.alias_need_id == alias_need_id
            )
        )
        or 0
    )
    assertion = NeedAliasAssertion(
        alias_need_id=alias_need_id,
        canonical_need_id=canonical_need_id,
        evidence_id=evidence_id,
        evidence_hash=expected_evidence_hash,
        package_scope=package_scope,
        basis=basis,
        reason=reason.strip(),
        state="conflicted" if existing_count > 1 else "current",
        version=previous_version + 1,
    )
    session.add(assertion)
    session.flush()
    return assertion


def retract_alias(session: Session, alias_need_id: UUID, reason: str) -> NeedAliasAssertion | None:
    """Append a retraction version while keeping prior assertions auditable."""
    lock_need_alias_pursuits(session)
    # A correction can share the caller's read transaction; discard its projection memo.
    session.info.pop("customer_need_alias_map", None)
    latest = session.scalar(
        select(NeedAliasAssertion)
        .where(NeedAliasAssertion.alias_need_id == alias_need_id)
        .order_by(NeedAliasAssertion.version.desc())
        .with_for_update()
    )
    if latest is None or latest.state not in {"current", "conflicted"}:
        return None
    current = latest
    if current.state == "current":
        current.state = "superseded"
        session.flush()
    version = (
        session.scalar(
            select(func.max(NeedAliasAssertion.version)).where(
                NeedAliasAssertion.alias_need_id == alias_need_id
            )
        )
        or 0
    ) + 1
    retraction = NeedAliasAssertion(
        alias_need_id=current.alias_need_id,
        canonical_need_id=current.canonical_need_id,
        evidence_id=current.evidence_id,
        evidence_hash=current.evidence_hash,
        package_scope=current.package_scope,
        basis=current.basis,
        reason=reason.strip() or "Evidence retracted",
        state="retracted",
        version=version,
    )
    session.add(retraction)
    session.flush()
    return retraction
