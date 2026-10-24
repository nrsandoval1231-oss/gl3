"""Guarded, explicitly reviewed batch remapping of project-scoped company claims.

This module deliberately has no name matching. Every input row names its claim,
project, expected current link and identity, current evidence version, and target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.buying_chain import buying_chain_views
from gridlens.intelligence.identity_reconciliation import (
    _validate_claim_evidence,
    link_claim_to_identity,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    CompanyIdentity,
)


class BatchRejected(ValueError):
    """The manifest or its live database binding failed a safety check."""


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise BatchRejected(f"{field} must be a UUID") from None


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchRejected(f"{field} is required")
    return value.strip()


def _manifest_shape(manifest: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(manifest, dict):
        raise BatchRejected("manifest must be a JSON object")
    operation = manifest.get("operation")
    if operation not in {"map", "rollback"}:
        raise BatchRejected("operation must be map or rollback")
    _required_text(manifest.get("batch_id"), "batch_id")
    target = manifest.get("target")
    if operation == "map" and not isinstance(target, dict):
        raise BatchRejected("target identity evidence anchor is required")
    if operation == "rollback" and target not in (None, {}):
        raise BatchRejected(
            "rollback selects each prior identity through its exact restore_link_id"
        )
    target = target or {}
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise BatchRejected("items must be a non-empty list")
    seen: set[UUID] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise BatchRejected(f"items[{index}] must be an object")
        claim_id = _uuid(item.get("claim_id"), f"items[{index}].claim_id")
        if claim_id in seen:
            raise BatchRejected("each claim may appear only once in a batch")
        seen.add(claim_id)
        if item.get("entity_type") != "company":
            raise BatchRejected("this batch only supports explicitly reviewed company links")
        for field in (
            "project_id",
            "current_link_id",
            "current_identity_id",
            "evidence_id",
            "target_identity_id",
        ):
            _uuid(item.get(field), f"items[{index}].{field}")
        _required_text(item.get("evidence_hash"), f"items[{index}].evidence_hash")
        _required_text(item.get("reviewed_by"), f"items[{index}].reviewed_by")
        _required_text(item.get("reason"), f"items[{index}].reason")
        if operation == "rollback":
            _uuid(item.get("restore_link_id"), f"items[{index}].restore_link_id")
    if operation == "map":
        for field in (
            "company_identity_id",
            "claim_id",
            "project_id",
            "link_id",
            "evidence_id",
        ):
            _uuid(target.get(field), f"target.{field}")
        _required_text(target.get("evidence_hash"), "target.evidence_hash")
    return operation, target, items


def _candidate_index(
    session: Session, claims: list[BuyingChainClaim]
) -> dict[UUID, dict[str, Any]]:
    views = buying_chain_views(session, {claim.project_id for claim in claims})
    return {item["id"]: item for view in views.values() for item in view["candidates"]}


def _identity_field(link: BuyingChainIdentityLink) -> UUID | None:
    if link.entity_type != "company":
        return None
    return link.company_identity_id


def _validate_source(
    session: Session,
    claim: BuyingChainClaim,
    evidence_id: UUID,
    expected_hash: str,
    candidates: dict[UUID, dict[str, Any]],
) -> BuyingChainEvidence:
    candidate = candidates.get(claim.id)
    if candidate is None:
        raise BatchRejected(f"claim {claim.id} is retracted or no longer current")
    if candidate.get("stale"):
        raise BatchRejected(f"claim {claim.id} has conflicted or stale source support")
    if candidate.get("retracted"):
        raise BatchRejected(
            f"claim {claim.id} is stale, conflicted, retracted, or no longer current"
        )
    if candidate.get("correction_stale"):
        raise BatchRejected(f"claim {claim.id} has a stale or conflicting correction")
    try:
        evidence = _validate_claim_evidence(
            session, claim, "company", evidence_id, current_candidate=candidate
        )
    except ValueError as error:
        raise BatchRejected(f"claim {claim.id}: {error}") from None
    if evidence.content_hash != expected_hash:
        raise BatchRejected(f"claim {claim.id} evidence hash changed")
    return evidence


def _load_and_check_target(
    session: Session,
    target: dict[str, Any],
    candidates: dict[UUID, dict[str, Any]],
) -> UUID:
    identity_id = _uuid(target["company_identity_id"], "target.company_identity_id")
    if session.get(CompanyIdentity, identity_id) is None:
        raise BatchRejected("selected target company identity does not exist")
    claim_id = _uuid(target["claim_id"], "target.claim_id")
    project_id = _uuid(target["project_id"], "target.project_id")
    link_id = _uuid(target["link_id"], "target.link_id")
    evidence_id = _uuid(target["evidence_id"], "target.evidence_id")
    claim = session.get(BuyingChainClaim, claim_id)
    link = session.get(BuyingChainIdentityLink, link_id)
    if claim is None or claim.project_id != project_id:
        raise BatchRejected("target evidence anchor claim/project binding changed")
    if (
        link is None
        or link.claim_id != claim_id
        or link.entity_type != "company"
        or link.state != "current"
        or _identity_field(link) != identity_id
        or link.source_evidence_id != evidence_id
        or link.source_version_hash != target["evidence_hash"]
    ):
        raise BatchRejected("target is not selected by the exact current evidenced company link")
    evidence = _validate_source(
        session,
        claim,
        evidence_id,
        target["evidence_hash"],
        candidates,
    )
    if link.source_version_hash != evidence.content_hash:
        raise BatchRejected("target anchor link evidence version changed")
    return identity_id


def _check_expected_link(
    session: Session,
    item: dict[str, Any],
    claim: BuyingChainClaim,
    evidence: BuyingChainEvidence,
) -> tuple[BuyingChainIdentityLink, bool]:
    expected_link_id = _uuid(item["current_link_id"], "current_link_id")
    expected_identity_id = _uuid(item["current_identity_id"], "current_identity_id")
    desired_identity_id = _uuid(item["target_identity_id"], "target_identity_id")
    current = session.scalar(
        select(BuyingChainIdentityLink)
        .where(
            BuyingChainIdentityLink.claim_id == claim.id,
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.state == "current",
        )
        .with_for_update()
    )
    if current is None:
        raise BatchRejected(f"claim {claim.id} has no current company link")
    current_identity = _identity_field(current)
    if current.id == expected_link_id and current_identity == expected_identity_id:
        if (
            current_identity == desired_identity_id
            and current.source_evidence_id == evidence.id
            and current.source_version_hash == evidence.content_hash
        ):
            return current, True
        return current, False
    # Re-running the exact approved manifest is a no-op only when the current
    # link is already the requested reviewed mapping and its old binding remains.
    previous = session.get(BuyingChainIdentityLink, expected_link_id)
    if (
        current_identity == desired_identity_id
        and current.source_evidence_id == evidence.id
        and current.source_version_hash == evidence.content_hash
        and current.reviewed_by == item["reviewed_by"].strip()
        and current.reason == item["reason"].strip()
        and previous is not None
        and previous.claim_id == claim.id
        and previous.state == "superseded"
        and _identity_field(previous) == expected_identity_id
    ):
        return current, True
    raise BatchRejected(f"claim {claim.id} current link or identity changed since review")


def _check_rollback_source(
    session: Session,
    item: dict[str, Any],
    claim: BuyingChainClaim,
    evidence: BuyingChainEvidence,
) -> tuple[BuyingChainIdentityLink, BuyingChainIdentityLink, bool]:
    expected_link_id = _uuid(item["current_link_id"], "current_link_id")
    expected_identity_id = _uuid(item["current_identity_id"], "current_identity_id")
    restored_identity = _uuid(item["target_identity_id"], "target_identity_id")
    current = session.scalar(
        select(BuyingChainIdentityLink)
        .where(
            BuyingChainIdentityLink.claim_id == claim.id,
            BuyingChainIdentityLink.entity_type == "company",
            BuyingChainIdentityLink.state == "current",
        )
        .with_for_update()
    )
    if current is None:
        raise BatchRejected(f"claim {claim.id} has no current company link")
    restore = session.get(
        BuyingChainIdentityLink, _uuid(item["restore_link_id"], "restore_link_id")
    )
    mapping = session.get(BuyingChainIdentityLink, expected_link_id)
    if (
        restore is None
        or restore.claim_id != claim.id
        or restore.entity_type != "company"
        or restore.state != "superseded"
        or _identity_field(restore) != restored_identity
        or restore.source_evidence_id != evidence.id
        or restore.source_version_hash != evidence.content_hash
    ):
        raise BatchRejected(
            f"claim {claim.id} rollback restore link is not the exact prior binding"
        )
    # Idempotent inverse replay: the exact mapping row is now superseded and
    # the current reviewed link points back to the exact restored identity.
    if (
        current.id != expected_link_id
        and _identity_field(current) == restored_identity
        and current.source_evidence_id == evidence.id
        and current.source_version_hash == evidence.content_hash
        and current.reviewed_by == item["reviewed_by"].strip()
        and current.reason == item["reason"].strip()
        and mapping is not None
        and mapping.claim_id == claim.id
        and mapping.state == "superseded"
        and _identity_field(mapping) == expected_identity_id
    ):
        return current, restore, True
    if current.id != expected_link_id or _identity_field(current) != expected_identity_id:
        raise BatchRejected(
            f"claim {claim.id} rollback does not match its exact prior link history"
        )
    return current, restore, False


def _normalized_manifest(
    operation: str, batch_id: str, target: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any]:
    def normalized_item(item: dict[str, Any]) -> dict[str, str]:
        fields = {
            "claim_id": str(_uuid(item["claim_id"], "claim_id")),
            "project_id": str(_uuid(item["project_id"], "project_id")),
            "entity_type": item["entity_type"],
            "current_link_id": str(_uuid(item["current_link_id"], "current_link_id")),
            "current_identity_id": str(_uuid(item["current_identity_id"], "current_identity_id")),
            "evidence_id": str(_uuid(item["evidence_id"], "evidence_id")),
            "evidence_hash": item["evidence_hash"].strip(),
            "target_identity_id": str(_uuid(item["target_identity_id"], "target_identity_id")),
            "reviewed_by": item["reviewed_by"].strip(),
            "reason": item["reason"].strip(),
        }
        if operation == "rollback":
            fields["restore_link_id"] = str(_uuid(item["restore_link_id"], "restore_link_id"))
        return fields

    normalized_target = None
    if operation == "map":
        normalized_target = {
            "company_identity_id": str(
                _uuid(target["company_identity_id"], "target.company_identity_id")
            ),
            "claim_id": str(_uuid(target["claim_id"], "target.claim_id")),
            "project_id": str(_uuid(target["project_id"], "target.project_id")),
            "link_id": str(_uuid(target["link_id"], "target.link_id")),
            "evidence_id": str(_uuid(target["evidence_id"], "target.evidence_id")),
            "evidence_hash": target["evidence_hash"].strip(),
        }
    return {
        "operation": operation,
        "batch_id": _required_text(batch_id, "batch_id"),
        "target": normalized_target,
        "items": [normalized_item(item) for item in items],
    }


def _digest(snapshot: dict[str, Any], manifest: dict[str, Any]) -> str:
    body = json.dumps(
        {"snapshot": snapshot, "manifest": manifest},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def execute_batch(
    session: Session,
    manifest: dict[str, Any],
    *,
    apply: bool = False,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Validate and preview a manifest, or apply all mappings atomically.

    Caller owns the transaction. Pass a transaction-scoped Session; on any
    exception the caller must roll back the transaction.
    """
    operation, target, items = _manifest_shape(manifest)
    target_identity_id = (
        _uuid(target["company_identity_id"], "target.company_identity_id")
        if operation == "map"
        else None
    )
    claim_ids = [_uuid(item["claim_id"], "claim_id") for item in items]
    lock_claim_ids = list(claim_ids)
    if operation == "map":
        anchor_claim_id = _uuid(target["claim_id"], "target.claim_id")
        if anchor_claim_id not in lock_claim_ids:
            lock_claim_ids.append(anchor_claim_id)
    # Lock claims in stable order so concurrent remaps serialize per claim.
    claims: dict[UUID, BuyingChainClaim] = {}
    for claim_id in sorted(lock_claim_ids, key=str):
        claim = session.scalar(
            select(BuyingChainClaim).where(BuyingChainClaim.id == claim_id).with_for_update()
        )
        if claim is None:
            raise BatchRejected(f"claim {claim_id} does not exist")
        claims[claim_id] = claim
    for item, claim_id in zip(items, claim_ids, strict=True):
        if claims[claim_id].project_id != _uuid(item["project_id"], "project_id"):
            raise BatchRejected(f"claim {claim_id} project binding changed")
    candidates = _candidate_index(session, list(claims.values()))
    if operation == "map":
        target_identity_id = _load_and_check_target(session, target, candidates)

    planned: list[dict[str, Any]] = []
    validated: list[
        tuple[dict[str, Any], BuyingChainClaim, BuyingChainEvidence, BuyingChainIdentityLink, bool]
    ] = []
    for item, claim_id in zip(items, claim_ids, strict=True):
        claim = claims[claim_id]
        evidence = _validate_source(
            session,
            claim,
            _uuid(item["evidence_id"], "evidence_id"),
            item["evidence_hash"],
            candidates,
        )
        if operation == "map":
            if _uuid(item["target_identity_id"], "target_identity_id") != target_identity_id:
                raise BatchRejected(
                    f"claim {claim_id} target differs from the selected target evidence anchor"
                )
            current, replayed = _check_expected_link(session, item, claim, evidence)
        else:
            current, _, replayed = _check_rollback_source(session, item, claim, evidence)
        planned.append(
            {
                "claim_id": str(claim.id),
                "project_id": str(claim.project_id),
                "current_link_id": str(current.id),
                "current_identity_id": str(_identity_field(current)),
                "target_identity_id": str(_uuid(item["target_identity_id"], "target_identity_id")),
                "evidence_id": str(evidence.id),
                "evidence_hash": evidence.content_hash,
                "replayed": replayed,
            }
        )
        validated.append((item, claim, evidence, current, replayed))
    snapshot = {
        "operation": operation,
        "batch_id": manifest["batch_id"],
        "target_identity_id": str(target_identity_id) if target_identity_id else None,
        "target_anchor_link_id": str(target["link_id"]) if target else None,
        "items": planned,
    }
    digest = _digest(
        snapshot,
        _normalized_manifest(operation, manifest["batch_id"], target, items),
    )
    if not apply:
        return {"mode": "dry_run", "digest": digest, **snapshot}
    if not expected_digest or expected_digest != digest:
        raise BatchRejected(
            "dry-run digest differs or --expect-digest is missing; no mappings applied"
        )

    changed: list[dict[str, Any]] = []
    for item, claim, evidence, current, replayed in validated:
        if replayed:
            changed.append(
                {"claim_id": str(claim.id), "link_id": str(current.id), "replayed": True}
            )
            continue
        if operation == "rollback":
            restore = session.get(
                BuyingChainIdentityLink, _uuid(item["restore_link_id"], "restore_link_id")
            )
            if restore is None:
                raise BatchRejected(f"claim {claim.id} previous link disappeared")
        link = link_claim_to_identity(
            session,
            claim,
            "company",
            _uuid(item["target_identity_id"], "target_identity_id"),
            evidence,
            item["reason"],
            reviewed_by=item["reviewed_by"],
        )
        changed.append({"claim_id": str(claim.id), "link_id": str(link.id), "replayed": False})
    return {"mode": "applied", "digest": digest, **snapshot, "results": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "apply", "rollback"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expect-digest", help="digest emitted by the exact dry-run")
    args = parser.parse_args()
    if args.command in {"apply", "rollback"} and not args.expect_digest:
        parser.error("apply and rollback require --expect-digest from a dry-run")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"cannot read manifest: {error}")
    if args.command == "rollback" and manifest.get("operation") != "rollback":
        parser.error("rollback command requires an inverse-review manifest with operation=rollback")
    if args.command == "apply" and manifest.get("operation") != "map":
        parser.error("apply command requires operation=map")
    from sqlalchemy import create_engine

    from gridlens.settings import settings

    if not settings.database_url:
        parser.error("DATABASE_URL is not configured")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as session:
            if args.command == "dry-run":
                result = execute_batch(session, manifest)
                session.rollback()
            else:
                with session.begin():
                    result = execute_batch(
                        session,
                        manifest,
                        apply=True,
                        expected_digest=args.expect_digest,
                    )
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except Exception as error:
        print(json.dumps({"mode": "rejected", "error": str(error)}, sort_keys=True))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
