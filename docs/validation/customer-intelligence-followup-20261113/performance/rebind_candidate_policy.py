"""Record a test-only saved-generation policy binding after source edits."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]
from gridlens.intelligence.saved_browse import POLICY_VERSION  # noqa: E402

url = make_url(os.environ["DATABASE_URL"])
if (
    url.host not in {"127.0.0.1", "localhost", "::1"}
    or url.port != 50833
    or url.database != "gl3_perf_followup_rollup_scale_candidate_test"
    or url.query
):
    raise SystemExit("Requires the task-owned candidate clone on loopback port 50833")

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
