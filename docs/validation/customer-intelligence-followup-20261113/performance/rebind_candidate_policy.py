"""Record a test-only saved-generation policy binding after source edits."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[4]
from perf_db_guard import perf_database_url  # noqa: E402

candidate_database = "gl3_perf_followup_rollup_scale_candidate_test"
url = perf_database_url(
    os.environ.get("DATABASE_URL"), allowed_databases={candidate_database}
)
from gridlens.settings import settings  # noqa: E402

application_url = perf_database_url(
    settings.database_url, allowed_databases={candidate_database}
)
if application_url != url:
    raise SystemExit("Application DATABASE_URL differs from the validated process URL")

from gridlens.intelligence.saved_browse import POLICY_VERSION  # noqa: E402

engine = create_engine(url)
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
        counts_before = dict(
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
        if generation["policy_version"] != POLICY_VERSION:
            connection.execute(
                text(
                    "UPDATE browse_generations SET policy_version=:version WHERE id=:id"
                ),
                {"version": POLICY_VERSION, "id": generation["id"]},
            )
        counts_after = dict(
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
    "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "source_policy_version": POLICY_VERSION,
    "database": url.database,
    "generation_id": str(generation["id"]),
    "policy_before": generation["policy_version"],
    "policy_after": POLICY_VERSION,
    "counts_before": counts_before,
    "counts_after": counts_after,
    "counts_unchanged": counts_before == counts_after,
    "allowed_adjustment": "Only browse_generations.policy_version for the synthetic disposable generation row.",
}
out = (
    ROOT
    / "docs/validation/customer-intelligence-followup-20261113/performance/candidate-policy-rebind.json"
)
if out.exists():
    raise SystemExit("Refusing to overwrite policy-binding receipt")
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
