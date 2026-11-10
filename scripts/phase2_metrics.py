"""Capture and compare the same synthetic Phase 2 fixture on two code revisions.

This helper only accepts the task-owned loopback PostgreSQL databases. It leaves
database creation and schema lifecycle to the dedicated acceptance test, whose
pristine-schema guard runs before any writes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from uuid import UUID
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
DATABASES = {
    "gl3_phase2_baseline_fixture_test",
    "gl3_phase2_candidate_fixture_test",
}
APP_DATABASE = "gl3_phase2_acceptance_app"
BROWSER_APP_DATABASE = "gl3_phase2_browser_fixture_test"
BROWSER_TEST_DATABASE = "gl3_phase2_browser_backend_test"
BASE_COMMIT = "bc433650ce4706dddfb5b30d78a502e3b528f54e"


def _assert_source_checkout_matches_head(source_root: Path) -> str:
    source_root = source_root.resolve()
    checkout = source_root.parents[1]
    expected_root = (checkout / "backend" / "src").resolve()
    if source_root != expected_root:
        raise ValueError("Selected source root is not this checkout's backend/src")

    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    tracked = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "backend/src"],
        cwd=checkout,
        check=False,
    )
    if tracked.returncode:
        raise ValueError("Selected backend/src has tracked changes beyond HEAD")

    untracked = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--others",
            "--",
            "backend/src",
        ],
        cwd=checkout,
        text=True,
    ).splitlines()
    source_files = [
        item
        for item in untracked
        if Path(item).suffix.lower() in {".py", ".pyi"}
        and "__pycache__" not in Path(item).parts
    ]
    if source_files:
        raise ValueError(
            "Selected backend/src contains untracked Python source: "
            + ", ".join(sorted(source_files))
        )
    return source_commit


def _database(url: str, *, label: str, allowed: set[str]) -> str:
    parsed = make_url(url)
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError(f"{label} must use PostgreSQL")
    routing_overrides = {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "database",
        "user",
        "username",
        "password",
        "service",
        "servicefile",
        "options",
        "target_session_attrs",
    }
    if routing_overrides.intersection(parsed.query):
        raise ValueError(f"{label} contains connection-routing query overrides")
    if any(
        os.environ.get(key)
        for key in (
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGOPTIONS",
            "PGSERVICE",
            "PGSERVICEFILE",
        )
    ):
        raise ValueError(
            "Inherited libpq connection-routing environment overrides are set"
        )
    if urlsplit(url).fragment:
        raise ValueError(f"{label} may not contain a URL fragment")
    host = (parsed.host or "").lower()
    if host not in {"127.0.0.1", "::1", "localhost"} or parsed.port != 58744:
        raise ValueError(
            f"{label} must target the task-owned loopback PostgreSQL 58744"
        )
    if parsed.username != "gridlens" or parsed.password is not None:
        raise ValueError(f"{label} must use loopback trust authentication for gridlens")
    database = parsed.database or ""
    if database not in allowed:
        raise ValueError(
            f"{label} is not one of the explicitly reserved disposable databases"
        )
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    args, effective = dialect().create_connect_args(parsed)
    if args or (effective.get("host") or "").lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError(f"{label} effective connection parameters are not loopback")
    if effective.get("port") != 58744 or effective.get("dbname") != database:
        raise ValueError(
            f"{label} effective connection parameters differ from the pinned URL"
        )
    return database


def _browser_database(
    url: str, *, label: str, expected_database: str
) -> tuple[str, int]:
    parsed = make_url(url)
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError(f"{label} must use PostgreSQL")
    if parsed.password is not None or parsed.username != "gridlens":
        raise ValueError(
            f"{label} must use the reserved gridlens role and passwordless URL"
        )
    routing_keys = {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "database",
        "user",
        "username",
        "password",
        "service",
        "servicefile",
        "options",
        "target_session_attrs",
    }
    if routing_keys.intersection(parsed.query) or urlsplit(url).fragment:
        raise ValueError(f"{label} contains URL routing overrides")
    if any(
        os.environ.get(key)
        for key in (
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGOPTIONS",
            "PGSERVICE",
            "PGSERVICEFILE",
        )
    ):
        raise ValueError("Inherited libpq routing overrides are set")
    if (parsed.host or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must target loopback")
    if parsed.port not in {5432, 58744}:
        raise ValueError(f"{label} must target the approved test PostgreSQL port")
    if parsed.database != expected_database:
        raise ValueError(
            f"{label} must target exact reserved database {expected_database}"
        )
    # CI PostgreSQL uses a generated ephemeral password. Keep it out of the URL
    # and use libpq's standard environment channel; local trust auth needs none.
    if parsed.port == 5432 and not os.environ.get("PGPASSWORD"):
        raise ValueError(f"{label} on CI port 5432 requires process-local PGPASSWORD")
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    args, effective = dialect().create_connect_args(parsed)
    if (
        args
        or (effective.get("host") or "").lower()
        not in {"127.0.0.1", "localhost", "::1"}
        or effective.get("port") != parsed.port
        or effective.get("dbname") != expected_database
        or effective.get("user") != "gridlens"
    ):
        raise ValueError(
            f"{label} effective libpq route differs from the validated URL"
        )
    return expected_database, parsed.port


def _assert_migrated_pristine(engine, *, label: str) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="public"))
    schemas = set(inspector.get_schema_names()) - {
        "information_schema",
        "pg_catalog",
        "public",
    }
    if schemas or "alembic_version" not in tables:
        raise ValueError(
            f"{label} must be a migrated, public-schema disposable database"
        )
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        revisions = set(
            connection.execute(text("SELECT version_num FROM public.alembic_version"))
        )
        revisions = {str(row[0]) for row in revisions}
        if revisions != expected_heads:
            raise ValueError(
                f"{label} schema is not at the selected source's migration head"
            )
        for table in sorted(tables - {"alembic_version"}):
            quoted = '"' + table.replace('"', '""') + '"'
            count = connection.execute(
                text(f"SELECT count(*) FROM public.{quoted}")
            ).scalar_one()
            if table == "browse_state":
                # The migration chain creates exactly one empty revision
                # sentinel. It is not retained project/account evidence.
                rows = connection.execute(
                    text(
                        "SELECT id, input_revision, generation_id, full_revision, "
                        "prepared_generation_id "
                        "FROM public.browse_state"
                    )
                ).all()
                if count == 1 and rows == [(1, 4, None, 4, None)]:
                    continue
            if count:
                raise ValueError(f"{label} contains pre-existing application rows")


def capture(args: argparse.Namespace) -> int:
    app_url = os.environ.get("DATABASE_URL", "")
    test_url = os.environ.get("TEST_DATABASE_URL", "")
    if not app_url or not test_url:
        raise ValueError(
            "DATABASE_URL and TEST_DATABASE_URL must be supplied explicitly"
        )
    app_db = _database(app_url, label="DATABASE_URL", allowed={APP_DATABASE})
    test_db = _database(test_url, label="TEST_DATABASE_URL", allowed=DATABASES)
    if app_db == test_db:
        raise ValueError("Application and test databases must be distinct")
    if test_db != args.database:
        raise ValueError(
            "TEST_DATABASE_URL does not match the selected reserved fixture DB"
        )
    expected_database = {
        "baseline": "gl3_phase2_baseline_fixture_test",
        "candidate": "gl3_phase2_candidate_fixture_test",
    }[args.mode]
    if test_db != expected_database:
        raise ValueError(
            "The selected database does not match the explicit baseline/candidate mode"
        )
    source_root = args.source_root.resolve()
    if (
        source_root.name != "src"
        or not (source_root / "gridlens" / "__init__.py").is_file()
    ):
        raise ValueError(
            "--source-root must be the selected checkout's backend/src directory"
        )
    source_commit = _assert_source_checkout_matches_head(source_root)
    if args.mode == "baseline" and source_commit != BASE_COMMIT:
        raise ValueError(
            "Baseline mode requires exact base bc433650ce4706dddfb5b30d78a502e3b528f54e"
        )
    if args.mode == "candidate" and source_commit == BASE_COMMIT:
        raise ValueError("Candidate mode cannot use the baseline source checkout")
    probe = create_engine(test_url, pool_size=1)
    try:
        if inspect(probe).get_table_names(schema="public"):
            raise ValueError("Refusing a non-pristine reserved fixture database")
        user_schemas = set(inspect(probe).get_schema_names()) - {
            "information_schema",
            "pg_catalog",
            "public",
        }
        if user_schemas:
            raise ValueError(
                "Refusing a fixture database containing pre-existing user schemas"
            )
    finally:
        probe.dispose()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing receipt: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "PHASE2_ACCEPTANCE_MODE": args.mode,
        "PHASE2_RECEIPT_PATH": str(output),
        "PHASE2_EXPECTED_SOURCE_ROOT": str(source_root),
        "PHASE2_SOURCE_COMMIT": source_commit,
    }
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        f"pythonpath={source_root}",
        "tests/integration/test_phase2_acceptance.py",
        "-q",
    ]
    result = subprocess.run(command, cwd=ROOT / "backend", env=env, check=False)
    if result.returncode:
        return result.returncode
    if _assert_source_checkout_matches_head(source_root) != source_commit:
        raise RuntimeError("Selected source checkout changed during acceptance capture")
    if not output.is_file():
        raise RuntimeError("Acceptance test passed without writing its metrics receipt")
    return 0


def _read_snapshot(path: Path, expected_mode: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("mode") != expected_mode:
        raise ValueError(f"{path}: expected mode {expected_mode!r}")
    if not value.get("fixture_id"):
        raise ValueError(f"{path}: fixture_id is required")
    if expected_mode == "baseline" and value.get("source_commit") != BASE_COMMIT:
        raise ValueError(f"{path}: baseline receipt is not from the exact base commit")
    if expected_mode == "candidate" and value.get("source_commit") == BASE_COMMIT:
        raise ValueError(f"{path}: candidate receipt resolves to the base commit")
    commercial = value.get("commercial")
    if not isinstance(commercial, dict):
        raise ValueError(f"{path}: commercial metrics are required")
    fixture_sha = commercial.get("fixture_input_sha256")
    if (
        not isinstance(fixture_sha, str)
        or len(fixture_sha) != 64
        or value["fixture_id"] != f"phase2-cross-lane-v3-{fixture_sha}"
    ):
        raise ValueError(
            f"{path}: fixture_id does not bind the full fixture input SHA-256"
        )
    evaluator_sha = commercial.get("evaluator_sha256")
    if not isinstance(evaluator_sha, str) or len(evaluator_sha) != 64:
        raise ValueError(f"{path}: commercial evaluator SHA-256 is required")
    if not value.get("source_modules"):
        raise ValueError(f"{path}: imported source module hashes are required")
    imported_root = Path(value.get("imported_source_root", "")).resolve()
    if imported_root.name != "src":
        raise ValueError(f"{path}: imported source root is missing or invalid")
    for module_name, module in value["source_modules"].items():
        module_path = Path(module.get("path", "")).resolve()
        digest = module.get("sha256")
        if (
            not module_path.is_relative_to(imported_root)
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError(f"{path}: invalid imported source proof for {module_name}")
    return value


def _percent(numerator: int, denominator: int) -> str:
    return "unknown" if denominator == 0 else f"{100 * numerator / denominator:.1f}%"


def compare(args: argparse.Namespace) -> int:
    baseline = _read_snapshot(args.baseline, "baseline")
    candidate = _read_snapshot(args.candidate, "candidate")
    if baseline["fixture_id"] != candidate["fixture_id"]:
        raise ValueError("Baseline and candidate must use the same fixture_id")
    for key in ("fixture_input_sha256", "evaluator_sha256"):
        baseline_value = baseline["commercial"].get(key)
        candidate_value = candidate["commercial"].get(key)
        if not baseline_value or baseline_value != candidate_value:
            raise ValueError(f"Baseline and candidate must have identical {key}")
    for snapshot in (baseline, candidate):
        if snapshot.get("data_kind") != "SYNTHETIC fixture only":
            raise ValueError(
                "Metrics input must be explicitly labeled synthetic fixture only"
            )
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing comparison: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    def summary(snapshot: dict) -> dict:
        entity = snapshot["entities"]
        commercial = snapshot["commercial"]
        pipeline = snapshot["pipeline"]
        projects = entity["physical_project_ids"]
        accounts = entity["canonical_account_ids"]
        useful = commercial["useful_need_ids"]
        return {
            "canonical_accounts": len(set(accounts)),
            "physical_projects": len(set(projects)),
            "needs": len(set(entity["need_ids"])),
            "useful_why_now_and_next_action": len(set(useful)),
            "useful_coverage": _percent(len(set(useful)), len(set(entity["need_ids"]))),
            "amount_class_scope_counts": commercial["amount_class_scope_counts"],
            "named_contact_needs": len(set(commercial["named_contact_need_ids"])),
            "generic_contact_needs": len(set(commercial["generic_contact_need_ids"])),
            "freshness_states": commercial["freshness_states"],
            "conflict_count": commercial["conflict_count"],
            "provider_logical_requests": pipeline["provider_logical_requests"],
            "provider_cache_reuses": pipeline["provider_cache_reuses"],
            "mock_robots_requests": pipeline.get("mock_robots_requests", "unknown"),
            "mock_target_requests": pipeline.get("mock_target_requests", "unknown"),
            "synthetic_mock_cost_usd": pipeline["synthetic_mock_cost_usd"],
            "real_provider_cost": "UNKNOWN / unverified",
            "scheduled_jobs": pipeline["scheduled_jobs"],
            "successful_jobs": pipeline.get("successful_jobs", "unknown"),
            "failed_jobs": pipeline.get("failed_jobs", "unknown"),
            "recovery_completed": pipeline["recovery_completed"],
            "elapsed_ms": pipeline["elapsed_ms"],
            "read_latency_ms": pipeline.get("read_latency_ms", {}),
            "contact_methods": commercial.get("contact_counts", {}),
            "imported_source_root": snapshot.get("imported_source_root"),
            "imported_source_modules": snapshot.get("source_modules", {}),
            "structured_brief_need_count": len(
                set(commercial["structured_brief_need_ids"])
            ),
        }

    report = {
        "title": "Synthetic Phase 2 same-fixture baseline/candidate comparison",
        "fixture_id": baseline["fixture_id"],
        "fixture_input_sha256": baseline["commercial"]["fixture_input_sha256"],
        "evaluator_sha256": baseline["commercial"]["evaluator_sha256"],
        "baseline_source_commit": baseline.get("source_commit"),
        "candidate_source_commit": candidate.get("source_commit"),
        "data_kind": "SYNTHETIC fixture only; not production coverage or lead metrics",
        "baseline": summary(baseline),
        "candidate": summary(candidate),
        "interpretation": [
            "Amount coverage is counted by explicit class and scope; unsupported MW values are never summed.",
            "Provider cost values describe deterministic mocked transports only; actual provider cost is unknown.",
            "Useful coverage uses supported source-grounded WhyNow and justified NextAction for the same need.",
        ],
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path = output.with_suffix(".md")
    markdown_path.write_text(
        "# Synthetic Phase 2 comparison\n\n"
        f"Fixture: `{report['fixture_id']}`. This is fixture-only evidence, not production coverage.\n\n"
        "| Metric | Baseline | Candidate |\n|---|---:|---:|\n"
        + "".join(
            f"| {key.replace('_', ' ')} | {baseline_value} | {candidate_value} |\n"
            for key, baseline_value, candidate_value in (
                (key, baseline_value, report["candidate"][key])
                for key, baseline_value in report["baseline"].items()
            )
        )
        + "\nActual provider cost: unknown / unverified. Synthetic mock cost is reported separately.\n",
        encoding="utf-8",
    )
    return 0


def seed_browser(args: argparse.Namespace) -> int:
    app_url = os.environ.get("DATABASE_URL", "")
    test_url = os.environ.get("TEST_DATABASE_URL", "")
    if not app_url or not test_url:
        raise ValueError("DATABASE_URL and TEST_DATABASE_URL must be explicit")
    _browser_database(
        app_url, label="DATABASE_URL", expected_database=BROWSER_APP_DATABASE
    )
    _browser_database(
        test_url, label="TEST_DATABASE_URL", expected_database=BROWSER_TEST_DATABASE
    )
    if app_url == test_url:
        raise ValueError("Browser application and backend test databases must differ")
    output = args.manifest_output.resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing manifest: {output}")
    source_root = args.source_root.resolve()
    if (
        source_root.name != "src"
        or not (source_root / "gridlens" / "__init__.py").is_file()
    ):
        raise ValueError("--source-root must be a checkout backend/src directory")
    checkout = source_root.parents[1]
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    if source_commit == BASE_COMMIT:
        raise ValueError("seed-browser requires a candidate source checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(source_root))
    import importlib

    import gridlens

    imported = Path(gridlens.__file__).resolve()
    if not imported.is_relative_to(source_root):
        raise ValueError(f"Imported package is outside --source-root: {imported}")

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from gridlens.persistence.models import (
        CompanyIdentity,
        Evidence,
        Interpretation,
        Job,
        Observation,
        Project,
    )
    from gridlens.settings import settings

    # Both databases are migrated before this command. The browser app database
    # remains intact after seeding so the UI lane can inspect real persisted rows.
    app_engine = create_engine(app_url, pool_size=8)
    test_engine = create_engine(test_url, pool_size=1)
    try:
        _assert_migrated_pristine(app_engine, label="DATABASE_URL")
        _assert_migrated_pristine(test_engine, label="TEST_DATABASE_URL")

        integration_dir = ROOT / "backend" / "tests" / "integration"
        sys.path.insert(0, str(integration_dir))
        fixture = importlib.import_module("test_phase2_acceptance")
        factory = sessionmaker(app_engine, expire_on_commit=False)

        # Provider credentials stay disabled in this short-lived process. The
        # sole external simulation is the exact-host HTTP MockTransport used by
        # the same canonical worker/parser path as the focused PostgreSQL test.
        settings.worker_auto_refresh = True
        settings.autonomous_research_enabled = True
        settings.company_contact_discovery_enabled = True
        settings.firecrawl_api_key = None
        settings.openai_api_key = None
        settings.typesafe_api_key = None
        settings.autonomous_research_max_cost_usd = Decimal("0")
        settings.intelligence_max_call_usd = Decimal("0")

        fixture_id, company_id, lookalike_id = fixture._seed_fixture(factory)
        from gridlens.intelligence import saved_browse

        rebuilt = saved_browse.rebuild(factory)
        if rebuilt.get("status") != "published":
            raise RuntimeError(
                f"Initial saved-browse rebuild failed: {rebuilt.get('status')}"
            )
        from gridlens.jobs import worker
        from gridlens.intelligence.company_contact_discovery import (
            JOB_KIND as CONTACT_JOB_KIND,
        )

        transport_calls: list[str] = []
        patch_sink = type("PatchSink", (), {})()

        def set_patch(_self, target, name, value):
            # This subprocess exits after seeding; avoid restoring dynamic
            # SettingsProxy attributes, whose __delattr__ is intentionally absent.
            setattr(target, name, value)

        patch_sink.setattr = set_patch.__get__(patch_sink)
        try:
            fixture._install_http_transport(
                patch_sink,
                outage={"enabled": False},
                requests=transport_calls,
                mode="candidate",
            )
            if not worker._run_planner(
                "pursuit_questions", worker.plan_pursuit_questions
            ):
                raise RuntimeError("Scheduled pursuit-question planner did not run")
            if not worker._run_planner(
                "company_contacts", worker.plan_company_contact_jobs
            ):
                raise RuntimeError("Scheduled company-contact planner did not run")
            with factory() as session:
                initial_jobs = list(
                    session.scalars(
                        select(Job)
                        .where(Job.status.in_(("queued", "running")))
                        .order_by(Job.created_at, Job.id)
                    )
                )
                initial_ids = [row.id for row in initial_jobs]
                if not any(row.kind == CONTACT_JOB_KIND for row in initial_jobs):
                    raise RuntimeError(
                        "Scheduled company-contact lane persisted no durable job"
                    )
                if not any(row.kind == "pursuit_question" for row in initial_jobs):
                    raise RuntimeError(
                        "Scheduled pursuit-question lane persisted no durable job"
                    )
            for job_id in initial_ids:
                if not worker.run_one({}, job_ids=[job_id]):
                    raise RuntimeError(
                        "A queued fenced job could not be leased and processed"
                    )
            for _ in range(200):
                with factory() as session:
                    remaining = list(
                        session.scalars(
                            select(Job)
                            .where(Job.status.in_(("queued", "running")))
                            .order_by(Job.created_at, Job.id)
                        )
                    )
                    remaining_ids = [row.id for row in remaining]
                if not remaining_ids:
                    break
                for job_id in remaining_ids:
                    if not worker.run_one({}, job_ids=[job_id]):
                        raise RuntimeError(
                            "Bounded worker drain could not lease a queued job"
                        )
            else:
                raise RuntimeError(
                    "Browser fixture exceeded the bounded durable job drain"
                )
            rebuilt = saved_browse.rebuild(factory)
            if rebuilt.get("status") != "published":
                raise RuntimeError(
                    f"Post-worker saved-browse rebuild failed: {rebuilt.get('status')}"
                )

            from gridlens.api import app as api_module

            projection = fixture._capture_projection(
                factory, api_module, company_id, lookalike_id
            )
            if (
                projection["account"]["account"]["project_count"] != 3
                or projection["account"]["account"]["need_count"] != 4
            ):
                raise RuntimeError(
                    "Canonical account projection did not retain the 3-site / 4-need fixture"
                )
            if projection["contacts"]["lookalike"]:
                raise RuntimeError(
                    "A same-name, different RRC identity borrowed the primary contact"
                )
            if not projection["contacts"]["primary"]:
                raise RuntimeError(
                    "Exact-operator public contact validation produced no permitted route"
                )
            if not any(
                item["useful"] for item in projection["legacy_shortlist_details"]
            ):
                raise RuntimeError(
                    "Source-bound baseline WhyNow/next-action path is not useful"
                )
            if not projection["structured_brief_need_ids"]:
                raise RuntimeError(
                    "Candidate has no qualified structured commercial brief"
                )
            if projection["owner_managed_execution_rows"]:
                raise RuntimeError(
                    "Autonomous fixture wrote owner-managed pursuit/task/activity state"
                )
            if not any(not path.endswith("/robots.txt") for path in transport_calls):
                raise RuntimeError(
                    "Contact worker did not fetch an approved page after robots"
                )

            from gridlens.intelligence.customer_accounts import account_projects
            from gridlens.intelligence.customer_results import _group_id, groups
            from gridlens.intelligence.project_results import page as project_page

            with factory() as session:
                account = account_projects(session, company_id, limit=25, offset=0)
                if account["total"] != 3:
                    raise RuntimeError(
                        "Canonical account page did not expose three physical sites"
                    )
                company_identity = session.get(CompanyIdentity, company_id)
                if not company_identity or not company_identity.rrc_operator_number:
                    raise RuntimeError("Canonical operator identity is unavailable")
                expected_group_id = _group_id(
                    f"rrc:{company_identity.rrc_operator_number}"
                )
                group_page = groups(session, sector="all", limit=50, shortlist=True)
                group = next(
                    (
                        item
                        for item in group_page["items"]
                        if item.get("id") == expected_group_id
                    ),
                    None,
                )
                if group is None:
                    raise RuntimeError(
                        "Canonical group API could not resolve the account"
                    )
                group_featured = group.get("featured_project")
                if not isinstance(group_featured, dict):
                    raise RuntimeError(
                        "Canonical group API did not provide its shortlisted featured project"
                    )
                project_id = UUID(
                    str(
                        group_featured.get("project_id")
                        or group_featured.get("id")
                        or ""
                    )
                )
                account_project_ids = {str(item["id"]) for item in account["items"]}
                if str(project_id) not in account_project_ids:
                    raise RuntimeError(
                        "Featured project does not belong to the canonical account"
                    )
                need_id = UUID(str(group_featured.get("representative_need_id") or ""))
                project_projection = project_page(
                    session,
                    need_id=need_id,
                    project_ids=[project_id],
                    limit=10,
                    shortlist=True,
                    include_signals=True,
                    primary_customer_ids_by_project={str(project_id): str(company_id)},
                )
                projected_project = next(
                    (
                        item
                        for item in project_projection["items"]
                        if str(item.get("id")) == str(project_id)
                        or str(project_id)
                        in {str(value) for value in item.get("project_ids", [])}
                    ),
                    None,
                )
                if projected_project is None:
                    raise RuntimeError(
                        "Canonical project API could not project the featured project"
                    )
                projected_need = next(
                    (
                        need
                        for need in projected_project.get("needs", [])
                        if str(need.get("id")) == str(need_id)
                    ),
                    None,
                )
                if projected_need is None:
                    raise RuntimeError(
                        "Canonical project API could not project the representative need"
                    )
                featured_need = next(
                    (
                        need
                        for need in (group_featured.get("needs") or [])
                        if str(need.get("id")) == str(need_id)
                    ),
                    None,
                )
                if featured_need is None:
                    raise RuntimeError(
                        "Shortlisted account card did not expose its representative need"
                    )
                brief = group_featured.get("commercial_brief")
                if not isinstance(brief, dict):
                    raise RuntimeError(
                        "Shortlisted featured project has no commercial_brief object"
                    )
                projected_brief = projected_project.get("commercial_brief") or {}
                card_semantic = dict(brief)
                project_semantic = dict(projected_brief)
                card_freshness = dict(card_semantic.get("freshness") or {})
                project_freshness = dict(project_semantic.get("freshness") or {})
                card_freshness.pop("as_of", None)
                project_freshness.pop("as_of", None)
                card_semantic["freshness"] = card_freshness
                project_semantic["freshness"] = project_freshness
                if card_semantic != project_semantic:
                    raise RuntimeError(
                        "Account card and canonical project API brief differ"
                    )
                contact_source_need_id = None
                best_contact = brief.get("best_contact")
                if best_contact is None:
                    need_brief = featured_need.get("commercial_brief") or {}
                    best_contact = need_brief.get("best_contact")
                    if best_contact:
                        contact_source_need_id = str(need_id)
                effective_brief = {**brief, "best_contact": best_contact}
                if contact_source_need_id and contact_source_need_id != str(need_id):
                    raise RuntimeError(
                        "Contact fallback is not bound to representative need"
                    )
                why = effective_brief.get("why_now") or {}
                action = effective_brief.get("next_action") or {}
                power = effective_brief.get("power_need") or {}
                best_contact = effective_brief.get("best_contact") or {}
                freshness = effective_brief.get("freshness") or {}
                if not why.get("text") or not why.get("sources"):
                    raise RuntimeError(
                        "Featured WhyNow is not bound to a retained source"
                    )
                if not action.get("text") or not isinstance(action.get("source"), dict):
                    raise RuntimeError("Featured next action is not source justified")
                if not best_contact.get("href"):
                    raise RuntimeError(
                        "Featured brief lacks a privacy-filtered permitted contact href"
                    )
                source_ref = why["sources"][0]
                evidence_id = UUID(str(source_ref.get("evidence_id") or ""))
                evidence_row = session.get(Evidence, evidence_id)
                if evidence_row is None or evidence_row.url != source_ref.get("url"):
                    raise RuntimeError(
                        "Featured brief source does not resolve to retained evidence"
                    )
                observation = session.get(Observation, evidence_row.observation_id)
                interpretation = session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == evidence_row.observation_id
                    )
                )
                assessment = interpretation.assessment if interpretation else {}
                if not (
                    observation
                    and observation.content_hash == evidence_row.content_hash
                    and interpretation.status == "accepted"
                    and interpretation.content_hash == evidence_row.content_hash
                    and assessment.get("evidence_hash") == evidence_row.content_hash
                    and assessment.get("project_identity_key")
                    == session.get(Project, project_id).identity_key
                ):
                    raise RuntimeError(
                        "Featured source is not the current accepted project evidence version"
                    )

                # Exact fixture input hash is the suffix in the stable fixture id.
                fixture_prefix = "phase2-cross-lane-v3-"
                if not fixture_id.startswith(fixture_prefix):
                    raise RuntimeError("Unexpected fixture id version")
                fixture_hash = fixture_id.removeprefix(fixture_prefix)
                if len(fixture_hash) != 64:
                    raise RuntimeError("Fixture id does not carry a full input SHA-256")
                manifest = {
                    "schema_version": "phase2-browser-v1",
                    "synthetic_fixture": True,
                    "db_name": BROWSER_APP_DATABASE,
                    "fixture_id": fixture_id,
                    "fixture_input_sha256": fixture_hash,
                    "source_commit": source_commit,
                    "account": {
                        "company_identity_id": str(company_id),
                        "name": account["account"]["name"],
                        "group_id": group["id"],
                        "project_ids": [str(item["id"]) for item in account["items"]],
                        "need_ids": [
                            str(need["id"])
                            for item in account["items"]
                            for need in item["needs"]
                        ],
                        "projects": [
                            {"id": str(item["id"]), "name": item["name"]}
                            for item in account["items"]
                        ],
                    },
                    "lookalike_account": {
                        "company_identity_id": str(lookalike_id),
                        "name": account_projects(
                            session, lookalike_id, limit=25, offset=0
                        )["account"]["name"],
                    },
                    "featured": {
                        "project_id": str(project_id),
                        "need_id": str(need_id),
                    },
                    "source": {
                        "title": evidence_row.title,
                        "url": evidence_row.url,
                        "evidence_id": str(evidence_row.id),
                        "content_hash": evidence_row.content_hash,
                        "event_date": (
                            evidence_row.event_date or evidence_row.published_at
                        ).isoformat()
                        if (evidence_row.event_date or evidence_row.published_at)
                        else None,
                    },
                    "brief": {
                        "why_now_text": why.get("text"),
                        "why_now_source_date": why.get("source_date"),
                        "why_now_scope": why.get("scope"),
                        "power_amount_class": power.get("amount_class"),
                        "power_value": power.get("value"),
                        "power_unit": power.get("unit"),
                        "power_scope": power.get("scope"),
                        "power_status": power.get("status"),
                        "best_contact_label": best_contact.get("contact"),
                        "best_contact_href": best_contact.get("href"),
                        "best_contact_kind": best_contact.get("kind"),
                        "best_contact_route_kind": best_contact.get("route_kind"),
                        "best_contact_authority": best_contact.get("authority"),
                        "best_contact_deliverability": best_contact.get(
                            "deliverability"
                        ),
                        "contact_source_need_id": contact_source_need_id,
                        "next_action": action.get("text"),
                        "freshness_status": freshness.get("status"),
                    },
                    "pipeline": {
                        "scheduled_jobs": len(initial_ids),
                        "mock_transport_requests": len(transport_calls),
                        "real_provider_cost": "UNKNOWN / unverified",
                        "owner_managed_execution_rows": projection[
                            "owner_managed_execution_rows"
                        ],
                    },
                }
            output.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return 0
        finally:
            pass
    finally:
        app_engine.dispose()
        test_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--mode", choices=("baseline", "candidate"), required=True
    )
    capture_parser.add_argument("--database", choices=sorted(DATABASES), required=True)
    capture_parser.add_argument("--source-root", type=Path, required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.set_defaults(run=capture)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.set_defaults(run=compare)
    browser_parser = subparsers.add_parser("seed-browser")
    browser_parser.add_argument(
        "--database", choices=[BROWSER_APP_DATABASE], required=True
    )
    browser_parser.add_argument("--manifest-output", type=Path, required=True)
    browser_parser.add_argument("--source-root", type=Path, required=True)
    browser_parser.set_defaults(run=seed_browser)
    args = parser.parse_args()
    try:
        return args.run(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
