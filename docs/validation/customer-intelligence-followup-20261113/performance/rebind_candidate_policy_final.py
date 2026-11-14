"""Rebind only the disposable candidate generation policy after source freeze."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[4]
from perf_db_guard import perf_database_url  # noqa: E402

candidate_database = "gl3_perf_followup_rollup_scale_candidate_test"
env_url = perf_database_url(
    os.environ.get("DATABASE_URL"),
    allowed_databases={candidate_database},
)
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gridlens.settings import settings  # noqa: E402

url = perf_database_url(
    settings.database_url, allowed_databases={candidate_database}
)
if url != env_url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence.saved_browse import POLICY_VERSION  # noqa: E402
from gridlens.persistence.database import engine  # noqa: E402


with engine.begin() as connection:
    before = dict(
        connection.execute(text("""
            SELECT g.id, g.policy_version, g.input_revision,
                   s.input_revision AS state_revision, g.row_count
            FROM browse_state s JOIN browse_generations g ON g.id=s.generation_id
            WHERE s.id=1
        """)).mappings().one()
    )
    counts_before = dict(connection.execute(text("""
        SELECT (SELECT count(*) FROM projects) AS projects,
               (SELECT count(*) FROM browse_rows) AS browse_rows,
               (SELECT count(*) FROM evidence) AS evidence,
               (SELECT count(*) FROM power_needs) AS needs,
               (SELECT count(*) FROM browse_customer_memberships) AS memberships
    """)).mappings().one())
    connection.execute(
        text("UPDATE browse_generations SET policy_version=:policy WHERE id=:id"),
        {"policy": POLICY_VERSION, "id": before["id"]},
    )
    after = dict(connection.execute(text("""
        SELECT g.id, g.policy_version, g.input_revision,
               s.input_revision AS state_revision, g.row_count
        FROM browse_state s JOIN browse_generations g ON g.id=s.generation_id
        WHERE s.id=1
    """)).mappings().one())
    counts_after = dict(connection.execute(text("""
        SELECT (SELECT count(*) FROM projects) AS projects,
               (SELECT count(*) FROM browse_rows) AS browse_rows,
               (SELECT count(*) FROM evidence) AS evidence,
               (SELECT count(*) FROM power_needs) AS needs,
               (SELECT count(*) FROM browse_customer_memberships) AS memberships
    """)).mappings().one())

receipt = {
    "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "source_policy_version": POLICY_VERSION,
    "database": url.database,
    "generation_before": before,
    "generation_after": after,
    "counts_before": counts_before,
    "counts_after": counts_after,
    "counts_unchanged": counts_before == counts_after,
    "allowed_adjustment": "Only browse_generations.policy_version for the synthetic disposable generation row.",
}
output = ROOT / "docs/validation/customer-intelligence-followup-20261113/performance/candidate-policy-rebind-final.json"
if output.exists():
    raise SystemExit("Refusing to overwrite final policy binding receipt")
output.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2, default=str))
