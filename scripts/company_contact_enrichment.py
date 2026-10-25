"""Inventory and resumably enqueue company contact discovery.

Inventory is read-only. Enqueue and job execution require an explicit loopback
database, the exact expected database name, and a manifest of URL hints only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
JOB_KIND = "company_contact_discovery"
TASK_TYPE = "company_contact_discovery"


def _database_session_factory(expected_database_name: str | None, *, apply: bool):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from gridlens.settings import settings

    parsed = make_url(settings.database_url)
    if not parsed.database:
        raise ValueError("Application database URL has no database name")
    if expected_database_name and parsed.database != expected_database_name:
        raise ValueError("Database name does not match --expected-database-name")
    host = (parsed.host or "").casefold()
    if apply and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Apply is permitted only against a loopback database")
    if apply and expected_database_name is None:
        raise ValueError("--apply requires --expected-database-name")
    engine = create_engine(settings.database_url)
    return engine, sessionmaker(engine, expire_on_commit=False)


def _inventory(session) -> dict:
    from sqlalchemy import select

    from gridlens.intelligence.company_contacts import (
        company_contacts,
        relevant_named_professional,
    )
    from gridlens.intelligence.customer_accounts import _current_customer_claims
    from gridlens.persistence.models import (
        BrowseGeneration,
        BrowseRow,
        PowerNeed,
        Project,
    )

    latest_generation = session.scalar(
        select(BrowseGeneration).order_by(BrowseGeneration.built_at.desc()).limit(1)
    )
    browse_rows = {}
    if latest_generation:
        browse_rows = {
            row.project_id: row
            for row in session.scalars(
                select(BrowseRow).where(BrowseRow.generation_id == latest_generation.id)
            )
        }

    project_rows = session.execute(
        select(Project.id, Project.name, Project.asset_type, PowerNeed.tier)
        .join(PowerNeed, PowerNeed.project_id == Project.id)
        .where(Project.region_status == "ELIGIBLE", PowerNeed.active.is_(True))
    ).all()
    projects: dict[UUID, dict] = {}
    for project_id, name, asset_type, tier in project_rows:
        browse = browse_rows.get(project_id)
        industry = browse.industry if browse else asset_type or "unknown"
        rank = browse.rank_score if browse else None
        row = projects.setdefault(
            project_id,
            {
                "project_id": str(project_id),
                "name": name,
                "tiers": set(),
                "industries": set(),
                "high_value_rank": rank,
            },
        )
        row["tiers"].add(tier)
        row["industries"].add(industry or "unknown")
    associated = _current_customer_claims(session, project_ids=set(projects))
    accounts: dict[UUID, dict] = {}
    associated_projects = set()
    for identity, project_id, claim in associated:
        associated_projects.add(project_id)
        account = accounts.setdefault(identity, {"company_id": str(identity), "projects": {}})
        account.setdefault("names", set()).add(getattr(claim, "organization", None) or "unknown")
        account["projects"][project_id] = projects[project_id]
    rows = []
    for identity, account in accounts.items():
        contact_set = company_contacts(session, identity)
        contacts = contact_set.contacts
        all_methods = _unique_contact_methods(contacts, company_identity_id=identity)
        methods = [method for _contact, method in all_methods]
        professional = any(relevant_named_professional(contact) for contact in contacts)
        direct_methods = [m for contact, m in all_methods if contact.name]
        generic_methods = [m for contact, m in all_methods if not contact.name]
        # The current evidence model does not confirm purchasing authority.
        company_methods = any(
            _method_kind(method) in {"email", "phone", "telephone"} for method in methods
        )
        tiers = sorted({t for p in account["projects"].values() for t in p["tiers"]})
        industries = sorted({i for p in account["projects"].values() for i in p["industries"]})
        rows.append(
            {
                "company_id": str(identity),
                "company_name": sorted(account["names"])[0],
                "tiers": tiers,
                "industries": industries,
                "projects": [
                    {
                        **p,
                        "tiers": sorted(p["tiers"]),
                        "industries": sorted(p["industries"]),
                    }
                    for p in sorted(account["projects"].values(), key=lambda p: p["project_id"])
                ],
                "contact_count": len(contacts),
                "verified_email": any(_method_kind(m) == "email" for m in methods),
                "verified_phone": any(_method_kind(m) in {"phone", "telephone"} for m in methods),
                "named_relevant_professional": professional,
                "source_confirmed_project_decision_maker": "UNKNOWN",
                "direct_person_email": any(_method_kind(m) == "email" for m in direct_methods),
                "direct_person_phone": any(
                    _method_kind(m) in {"phone", "telephone"} for m in direct_methods
                ),
                "generic_company_email": any(_method_kind(m) == "email" for m in generic_methods),
                "generic_company_phone": any(
                    _method_kind(m) in {"phone", "telephone"} for m in generic_methods
                ),
                "purchasing_authority": "unconfirmed",
                "company_contact_method": company_methods,
                "url_only_route": not company_methods
                and any(_has_route(contact) for contact in contacts),
                "usable_email_or_phone": company_methods,
                "research_required": contact_set.research_required,
                "priority_rank": max(
                    (
                        p["high_value_rank"]
                        for p in account["projects"].values()
                        if p["high_value_rank"] is not None
                    ),
                    default=None,
                ),
            }
        )

    def summarize(items: list[dict]) -> dict:
        n = len(items)
        metrics = (
            "verified_email",
            "verified_phone",
            "named_relevant_professional",
            "direct_person_email",
            "direct_person_phone",
            "generic_company_email",
            "generic_company_phone",
            "company_contact_method",
            "url_only_route",
            "usable_email_or_phone",
            "research_required",
        )
        return {
            "distinct_companies": n,
            "metrics": {
                key: {
                    "count": sum(bool(row[key]) for row in items),
                    "denominator": n,
                    "percent": round(100 * sum(bool(row[key]) for row in items) / n, 2)
                    if n
                    else None,
                }
                for key in metrics
            },
        }

    return {
        "scope": "Current customer identities attached to active needs in eligible projects",
        "eligible_projects": len(projects),
        "unresolved_project_count": len(set(projects) - associated_projects),
        "overall": summarize(rows),
        "by_tier": {
            tier: summarize([r for r in rows if tier in r["tiers"]])
            for tier in ("Lead", "Prospect", "Signal")
        },
        "by_industry": {
            industry: summarize([r for r in rows if industry in r["industries"]])
            for industry in sorted({i for r in rows for i in r["industries"]})
        },
        "companies": rows,
        "provider_cost_usd": "UNKNOWN",
        "notes": [
            "Professional role is not confirmed purchasing authority.",
            "Zero denominator percentages are null.",
            "Cost is UNKNOWN unless measured by the provider accounting path.",
        ],
    }


def _unique_contact_methods(contacts, *, company_identity_id: UUID | str | None = None):
    """Deduplicate repeated evidence projections by person/company and method."""
    unique = {}
    for contact in contacts:
        owner = (
            (contact.name if contact.name else str(company_identity_id or contact.company or ""))
            .strip()
            .casefold()
        )
        owner_type = "person" if contact.name else "company"
        for method in contact.methods:
            kind = _method_kind(method)
            href = str(method.get("href", "")).strip().casefold()
            method_value = str(method.get("value", "")).strip().casefold()
            key = (owner_type, owner, kind, href or method_value)
            unique.setdefault(key, (contact, method))
    return list(unique.values())


def _method_kind(method: dict) -> str:
    return str(method.get("kind", "")).strip().casefold()


def _is_usable_method(method: dict) -> bool:
    return _method_kind(method) in {"email", "phone", "telephone"}


def _has_route(contact) -> bool:
    return bool(contact.sources) or any(method.get("href") for method in contact.methods)


def _manifest_digest(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_plan_manifest(
    inventory: dict,
    *,
    limit: int = 25,
    after_company_id: str | None = None,
    expected_snapshot_sha256: str | None = None,
) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("Plan limit must be between 1 and 100")
    ordered = _priority(inventory)
    snapshot = [
        {
            "company_id": row["company_id"],
            "tiers": row["tiers"],
            "industries": row["industries"],
            "priority_rank": row.get("priority_rank"),
        }
        for row in ordered
    ]
    snapshot_sha = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected_snapshot_sha256 and snapshot_sha != expected_snapshot_sha256:
        raise ValueError("Inventory snapshot changed since the previous plan page")
    start = 0
    if after_company_id:
        positions = [i for i, row in enumerate(ordered) if row["company_id"] == after_company_id]
        if not positions:
            raise ValueError("Plan cursor company is absent from this inventory snapshot")
        start = positions[0] + 1
    page = ordered[start : start + limit]
    more = start + len(page) < len(ordered)
    return {
        "schema_version": 1,
        "selection": "Current eligible customer companies in tier and rank priority order",
        "source_snapshot_sha256": snapshot_sha,
        "plan_snapshot_sha256": snapshot_sha,
        "next_cursor": page[-1]["company_id"] if page and more else None,
        "companies": [{"company_id": row["company_id"], "candidate_urls": []} for row in page],
    }


def validate_job_binding(job, company_id: str, candidate_urls: list[str]) -> None:
    try:
        checkpoint = json.loads(job.checkpoint or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("Discovery job checkpoint is invalid") from exc
    payload = checkpoint.get("payload") or {}
    if (
        job.kind != JOB_KIND
        or str(job.target_id) != company_id
        or checkpoint.get("task_type") != TASK_TYPE
        or payload.get("company_identity_id") != company_id
        or payload.get("candidate_urls", []) != candidate_urls
    ):
        raise ValueError("Job identity or URL payload does not match the manifest")


def _load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("companies"), list):
        raise ValueError("Manifest must contain a companies array")
    if set(data) - {
        "schema_version",
        "selection",
        "source_snapshot_sha256",
        "candidate_discovery",
        "plan_snapshot_sha256",
        "next_cursor",
        "companies",
    }:
        raise ValueError("Manifest contains unsupported top-level fields")
    source_snapshot = data.get("source_snapshot_sha256")
    if source_snapshot is not None and (
        not isinstance(source_snapshot, str) or len(source_snapshot) != 64
    ):
        raise ValueError("source_snapshot_sha256 must be a SHA-256 hex digest")
    seen = set()
    runtime_rows = []
    for row in data["companies"]:
        if not isinstance(row, dict):
            raise ValueError("Manifest companies must be objects")
        allowed = {
            "company_id",
            "company_identity_id",
            "candidate_urls",
            "name",
            "tiers",
            "industries",
            "project_count",
        }
        if set(row) - allowed:
            raise ValueError(
                "Manifest rows contain unsupported fields; contact values are forbidden"
            )
        company_id = row.get("company_id", row.get("company_identity_id"))
        UUID(company_id)
        if company_id in seen:
            raise ValueError("Manifest repeats a company_id")
        seen.add(company_id)
        urls = row.get("candidate_urls", [])
        if not isinstance(urls, list) or len(urls) > 4 or not all(isinstance(u, str) for u in urls):
            raise ValueError("candidate_urls must contain at most four URL strings")
        from gridlens.ingestion.adapters.buying_chain_public import validate_public_url

        normalized_urls = [validate_public_url(url) for url in urls]
        runtime_rows.append(
            {
                "company_id": company_id,
                "candidate_urls": list(dict.fromkeys(normalized_urls)),
            }
        )
    return {
        "schema_version": data.get("schema_version"),
        "source_snapshot_sha256": source_snapshot,
        "companies": runtime_rows,
    }


def _priority(inventory: dict) -> list[dict]:
    priority = {"Lead": 0, "Prospect": 2, "Signal": 3}
    rows = inventory["companies"]
    return sorted(
        rows,
        key=lambda r: (
            min((priority.get(t, 9) for t in r["tiers"]), default=9),
            -(r["priority_rank"] or 0) if "Lead" not in r["tiers"] else 0,
            r["company_id"],
        ),
    )


def enqueue_manifest(
    session,
    manifest: dict,
    checkpoint: dict | None = None,
    *,
    company_ids: set[str] | None = None,
) -> dict:
    state = checkpoint or {
        "manifest_digest": _manifest_digest(manifest),
        "completed": {},
    }
    digest = _manifest_digest(manifest)
    if state.get("manifest_digest") != digest:
        raise ValueError("Checkpoint manifest digest does not match input manifest")
    from gridlens.intelligence.company_contact_discovery import (
        discover_company_contacts,
    )

    completed = state.setdefault("completed", {})
    outcomes = []
    for row in manifest["companies"]:
        company_id = row["company_id"]
        if company_ids is not None and company_id not in company_ids:
            continue
        if completed.get(company_id, {}).get("status") in {
            "queued",
            "succeeded",
            "complete",
        }:
            continue
        job = discover_company_contacts(
            session, UUID(company_id), candidate_urls=row.get("candidate_urls", [])
        )
        raw_job_id = (
            job.get("job_id") or job.get("id") if isinstance(job, dict) else getattr(job, "id", "")
        )
        job_id = str(raw_job_id or "")
        status = (
            getattr(job, "status", None)
            or (job.get("status") if isinstance(job, dict) else None)
            or "queued"
        )
        item = {
            "company_id": company_id,
            "job_id": job_id or None,
            "status": status,
            "provider_cost_usd": "UNKNOWN",
        }
        completed[company_id] = item
        outcomes.append(item)
    return {
        "manifest_digest": digest,
        "completed": completed,
        "enqueued_this_run": outcomes,
        "provider_cost_usd": "UNKNOWN",
        "note": "Enqueue completion is not discovery completion; inspect worker job checkpoints.",
    }


def _job_snapshot(session, job_id: UUID) -> dict | None:
    from gridlens.persistence.models import Job

    job = session.get(Job, job_id)
    if job is None:
        return None
    try:
        checkpoint = json.loads(job.checkpoint or "{}")
    except (TypeError, ValueError):
        checkpoint = {"parse_error": True}
    return {
        "job_id": str(job.id),
        "kind": job.kind,
        "target_id": str(job.target_id) if job.target_id else None,
        "job_status": job.status,
        "job_error": job.error,
        "attempts": job.attempts,
        "checkpoint": checkpoint,
    }


def _persisted_contact_metrics(session, company_id: UUID) -> dict:
    from gridlens.intelligence.company_contacts import (
        company_contacts,
        relevant_named_professional,
    )

    result = company_contacts(session, company_id)
    contacts = result.contacts
    all_methods = _unique_contact_methods(contacts, company_identity_id=company_id)
    direct = [(contact, method) for contact, method in all_methods if contact.name]
    generic = [(contact, method) for contact, method in all_methods if not contact.name]
    return {
        "contact_count": len(contacts),
        "verified_email_methods": sum(_method_kind(method) == "email" for _, method in all_methods),
        "verified_phone_methods": sum(
            _method_kind(method) in {"phone", "telephone"} for _, method in all_methods
        ),
        "named_relevant_professionals": sum(
            relevant_named_professional(contact) for contact in contacts
        ),
        "named_people_without_methods": sum(
            bool(contact.name) and not contact.methods for contact in contacts
        ),
        "direct_person_email_methods": sum(_method_kind(method) == "email" for _, method in direct),
        "direct_person_phone_methods": sum(
            _method_kind(method) in {"phone", "telephone"} for _, method in direct
        ),
        "generic_company_email_methods": sum(
            _method_kind(method) == "email" for _, method in generic
        ),
        "generic_company_phone_methods": sum(
            _method_kind(method) in {"phone", "telephone"} for _, method in generic
        ),
        "usable_email_or_phone": any(_is_usable_method(method) for _, method in all_methods),
        "url_only_route": not any(_is_usable_method(method) for _, method in all_methods)
        and any(_has_route(contact) for contact in contacts),
        "source_confirmed_project_decision_maker": "UNKNOWN",
        "purchasing_authority": "unconfirmed",
        "research_required": result.research_required,
        "contacts": [
            {
                "name": contact.name,
                "title": contact.title,
                "role": contact.role,
                "responsibility": contact.responsibility,
                "purchasing_authority": contact.purchasing_authority,
                "methods": contact.methods,
                "sources": [source.model_dump(mode="json") for source in contact.sources],
                "verified_at": contact.verified_at,
            }
            for contact in contacts
        ],
        "sources": [
            source.model_dump(mode="json") for contact in contacts for source in contact.sources
        ],
    }


def run_manifest_jobs(factory, manifest: dict, checkpoint: dict, checkpoint_path: Path) -> dict:
    """Run only exact manifest job IDs; inspect in-flight jobs without blind retry."""
    from gridlens.jobs.worker import run_one

    if checkpoint.get("manifest_digest") != _manifest_digest(manifest):
        raise ValueError("Checkpoint manifest digest does not match input manifest")
    completed = checkpoint.setdefault("completed", {})
    for row in manifest["companies"]:
        company_id = row["company_id"]
        entry = completed.get(company_id, {})
        job_id_raw = entry.get("job_id")
        if not job_id_raw:
            continue
        job_id = UUID(job_id_raw)
        elapsed: float | str = "UNKNOWN"
        with factory() as session:
            snapshot = _job_snapshot(session, job_id)
            if snapshot is not None:
                validate_job_binding(
                    SimpleNamespace(
                        kind=snapshot["kind"],
                        target_id=snapshot["target_id"],
                        checkpoint=json.dumps(snapshot["checkpoint"]),
                    ),
                    company_id,
                    row.get("candidate_urls", []),
                )
        if snapshot is None:
            entry.update(run_status="missing_job", job_status="UNKNOWN")
        elif snapshot["job_status"] == "queued":
            started = time.monotonic()
            run_one({}, job_ids=[job_id])
            elapsed = round(time.monotonic() - started, 3)
            with factory() as session:
                snapshot = _job_snapshot(session, job_id)
        elif snapshot["job_status"] == "running":
            entry.update(run_status="in_flight", job_snapshot=snapshot)
            checkpoint_path.write_text(
                json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8"
            )
            continue
        else:
            elapsed = "UNKNOWN"
        entry["job_snapshot"] = snapshot
        entry["job_status"] = snapshot["job_status"] if snapshot else "UNKNOWN"
        if snapshot and snapshot["job_status"] in {"succeeded", "failed"}:
            with factory() as session:
                entry["persisted_contacts"] = _persisted_contact_metrics(session, UUID(company_id))
            entry["run_status"] = snapshot["checkpoint"].get("status", snapshot["job_status"])
            entry["elapsed_seconds"] = (
                elapsed
                if isinstance(elapsed, float)
                else snapshot["checkpoint"].get("elapsed_seconds", "UNKNOWN")
            )
            entry["provider_cost_usd"] = snapshot["checkpoint"].get("provider_cost_usd", "UNKNOWN")
        else:
            entry["run_status"] = "pending_or_unknown"
        completed[company_id] = entry
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8"
        )
    checkpoint["provider_cost_usd"] = "UNKNOWN"
    checkpoint["run_mode"] = "worker_run_one_exact_job_ids"
    terminal = [
        row
        for row in completed.values()
        if (row.get("job_status") or (row.get("job_snapshot") or {}).get("job_status"))
        in {"succeeded", "failed"}
        and row.get("persisted_contacts")
    ]
    checkpoint["run_summary"] = {
        "companies_with_terminal_job": len(terminal),
        "metrics": {
            key: sum(int(row["persisted_contacts"].get(key, 0) or 0) for row in terminal)
            for key in (
                "verified_email_methods",
                "verified_phone_methods",
                "named_relevant_professionals",
                "named_people_without_methods",
                "direct_person_email_methods",
                "direct_person_phone_methods",
                "generic_company_email_methods",
                "generic_company_phone_methods",
            )
        },
        "companies_with_usable_method": sum(
            bool(row["persisted_contacts"]["usable_email_or_phone"]) for row in terminal
        ),
        "companies_url_only": sum(
            bool(row["persisted_contacts"]["url_only_route"]) for row in terminal
        ),
        "decision_maker_contact": "UNKNOWN",
        "purchasing_authority": "unconfirmed",
        "provider_cost_usd": "UNKNOWN",
    }
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database-name")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--after-company-id")
    parser.add_argument("--plan-snapshot-sha256")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-jobs", action="store_true")
    args = parser.parse_args()
    if args.plan_output and args.manifest:
        parser.error("--plan-output and --manifest are mutually exclusive")
    if not args.inventory and not args.manifest and not args.plan_output:
        parser.error("choose --inventory, --plan-output, or --manifest")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if args.after_company_id and not args.plan_snapshot_sha256:
        parser.error("--after-company-id requires --plan-snapshot-sha256")
    if args.run_jobs:
        args.apply = True
    if args.apply and (not args.manifest or not args.checkpoint or not args.expected_database_name):
        parser.error("--apply requires --manifest, --checkpoint, and --expected-database-name")
    engine, factory = _database_session_factory(args.expected_database_name, apply=args.apply)
    try:
        if args.inventory or args.plan_output:
            with factory.begin() as session:
                from sqlalchemy import text

                session.execute(text("SET TRANSACTION READ ONLY"))
                report = _inventory(session)
            if args.plan_output:
                plan = build_plan_manifest(
                    report,
                    limit=args.limit,
                    after_company_id=args.after_company_id,
                    expected_snapshot_sha256=args.plan_snapshot_sha256,
                )
                args.plan_output.write_text(
                    json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
                )
                report = {
                    "plan_output": str(args.plan_output),
                    "companies_in_page": len(plan["companies"]),
                    "next_cursor": plan["next_cursor"],
                    "plan_snapshot_sha256": plan["plan_snapshot_sha256"],
                    "provider_cost_usd": "UNKNOWN",
                }
        elif args.run_jobs:
            manifest = _load_manifest(args.manifest)
            checkpoint = (
                json.loads(args.checkpoint.read_text()) if args.checkpoint.exists() else None
            )
            if not checkpoint:
                raise ValueError("--run-jobs requires a prior enqueue checkpoint")
            report = run_manifest_jobs(factory, manifest, checkpoint, args.checkpoint)
            args.checkpoint.write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
        else:
            manifest = _load_manifest(args.manifest)
            checkpoint = (
                json.loads(args.checkpoint.read_text()) if args.checkpoint.exists() else None
            )
            if not args.apply:
                report = {
                    "manifest_digest": _manifest_digest(manifest),
                    "companies": len(manifest["companies"]),
                    "mode": "read-only-plan",
                    "provider_cost_usd": "UNKNOWN",
                }
            else:
                report = checkpoint or {
                    "manifest_digest": _manifest_digest(manifest),
                    "completed": {},
                    "provider_cost_usd": "UNKNOWN",
                }
                # Commit and checkpoint one company at a time. A process stop
                # cannot mark an uncommitted enqueue as complete or replay the
                # already committed earlier companies blindly.
                for row in manifest["companies"]:
                    company_id = row["company_id"]
                    if report.get("completed", {}).get(company_id, {}).get("status") in {
                        "queued",
                        "succeeded",
                        "complete",
                    }:
                        continue
                    with factory.begin() as session:
                        report = enqueue_manifest(
                            session, manifest, report, company_ids={company_id}
                        )
                    args.checkpoint.write_text(
                        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
                    )
        report["mode"] = "apply" if args.apply else "read-only"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
