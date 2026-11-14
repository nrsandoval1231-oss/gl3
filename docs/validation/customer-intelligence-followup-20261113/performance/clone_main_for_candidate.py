"""Clone the c5 fixture and bind its test-only generation to candidate policy."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[4]
MAIN_DATABASE = "gl3_perf_followup_rollup_scale_main_test"
CANDIDATE_DATABASE = "gl3_perf_followup_rollup_scale_candidate_test"
from perf_db_guard import perf_database_url  # noqa: E402

url = perf_database_url(
    os.environ.get("DATABASE_URL"), allowed_databases={MAIN_DATABASE}
)

source = ROOT / "backend" / "src"
digest = hashlib.sha256()
for path in sorted(source.rglob("*.py")):
    digest.update(str(path.relative_to(source)).encode())
    digest.update(path.read_bytes())
source_manifest = digest.hexdigest()
from gridlens.settings import settings  # noqa: E402

application_url = perf_database_url(
    settings.database_url, allowed_databases={MAIN_DATABASE}
)
if application_url != url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence.saved_browse import POLICY_VERSION  # noqa: E402

admin_url = perf_database_url(
    url.set(database="postgres").render_as_string(hide_password=False),
    allowed_databases={"postgres"},
)
admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
try:
    with admin.connect() as connection:
        assert not connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:name"),
            {"name": CANDIDATE_DATABASE},
        ).first(), "candidate database already exists; refusing overwrite"
        connection.execute(
            text(f'CREATE DATABASE "{CANDIDATE_DATABASE}" TEMPLATE "{MAIN_DATABASE}"')
        )
finally:
    admin.dispose()

candidate_url = url.set(database=CANDIDATE_DATABASE)
candidate_url = perf_database_url(
    candidate_url.render_as_string(hide_password=False),
    allowed_databases={CANDIDATE_DATABASE},
)
engine = create_engine(candidate_url)
try:
    with engine.begin() as connection:
        generation = (
            connection.execute(
                text("""
                SELECT g.id, g.policy_version FROM browse_generations g
                JOIN browse_state s ON s.generation_id=g.id WHERE s.id=1
            """)
            )
            .mappings()
            .one()
        )
        before = dict(
            connection.execute(
                text("""
                SELECT (SELECT count(*) FROM projects) AS projects,
                       (SELECT count(*) FROM browse_rows) AS browse_rows,
                       (SELECT count(*) FROM evidence) AS evidence,
                       (SELECT count(*) FROM power_needs) AS needs,
                       (SELECT count(*) FROM browse_customer_memberships) AS memberships
            """)
            )
            .mappings()
            .one()
        )
        connection.execute(
            text("UPDATE browse_generations SET policy_version=:version WHERE id=:id"),
            {"version": POLICY_VERSION, "id": generation["id"]},
        )
        after = dict(
            connection.execute(
                text("""
                SELECT (SELECT count(*) FROM projects) AS projects,
                       (SELECT count(*) FROM browse_rows) AS browse_rows,
                       (SELECT count(*) FROM evidence) AS evidence,
                       (SELECT count(*) FROM power_needs) AS needs,
                       (SELECT count(*) FROM browse_customer_memberships) AS memberships
            """)
            )
            .mappings()
            .one()
        )
finally:
    engine.dispose()

receipt = {
    "source_root_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "source_backend_manifest_sha256": source_manifest,
    "source_policy_version": POLICY_VERSION,
    "template_database": MAIN_DATABASE,
    "candidate_database": CANDIDATE_DATABASE,
    "generation_id": str(generation["id"]),
    "template_generation_policy_version": generation["policy_version"],
    "candidate_generation_policy_version": POLICY_VERSION,
    "allowed_test_only_adjustment": "browse_generations.policy_version for the cloned generation row only",
    "table_counts_before": before,
    "table_counts_after": after,
    "counts_unchanged": before == after,
    "limitations": [
        "Disposable synthetic test databases only; no retained or production data."
    ],
}
out = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance/main-candidate-clone.json"
)
if out.exists():
    raise SystemExit("Refusing to overwrite policy-binding receipt")
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
