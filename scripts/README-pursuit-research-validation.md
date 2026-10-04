# Bounded pursuit research validation tools

`pursuit_research_metrics.py` is read-only. It counts commercial and tier changes
from consecutive immutable Pursuit evaluation versions. Two questions observing
one transition do not count twice; an initial saved state is not a transition.
Unknown prior tiers never become promotion baselines. Scheduling origins remain
separate. Use `--since <timezone-aware ISO timestamp>` to select recent activity.
Question counters cover the cumulative receipts of questions created, attempted,
or completed in that window; they are not a provider billing export for that window.
Actual cost remains unknown when only a reservation exists.

The shared `gridlens.intelligence.research_metrics.research_overview` additionally
returns one morning item per saved version correlated with completed research by
input hash and execution interval. This is correlation, not proof of sole causation
when manual evaluation runs concurrently. Items preserve before/after tier separately
from commercial state, source differences, next action, and question IDs.

## Corpus manifest and isolated database

Copy `pursuit-research-manifest.example.json` into an ignored local artifact directory.
Replace every UUID, category rationale, database name and corpus ID. Use exactly the
five documented categories and five to ten distinct PowerNeeds. Category declarations
are checked against current source/project data; the low-quality rationale still
requires operator review. The selected cases must have actual unresolved questions;
the runner never fabricates blockers to make an ACTION NOW card researchable.

Set the application's existing `DATABASE_URL` to a separately restored validation
clone. The tools do not restore data, change credentials or reset budgets. They reject
the original `gridlens`, shared `gridlens_test`, and `postgres` database names.
Stop unrelated workers on the clone; the baseline refuses queued/running jobs.
The manifest run_budget adds aggregate max_total_cost_usd (default0; maximum20) and
max_wall_clock_seconds (default3600; maximum7200). Preflight reserves the configured
per-question cost ceiling across at most four jobs per selected need; it refuses a
cohort exceeding the explicit aggregate cost cap. Before starting each job it requires
enough remaining wall time for the full question timeout. These are ceilings, not
actual provider bills. Baseline configuration includes all acquisition limits and
provider availability; changes require a fresh baseline.
Configured question/day, search, document, timeout and cost limits still apply. A
cohort that exceeds those limits produces an incomplete report, not relaxed limits.

Manifest `kind` must be `fixture`, `reingested`, or `retained_pr23`. Fixture/reingested
runs can never set `retained_corpus_proof=true`. For `retained_pr23`, add:

```json
"provenance": {
  "backup_path": "original-retained.dump",
  "backup_sha256": "828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886",
  "restore_receipt_path": "authorized-restore-receipt.json"
}
```

Paths are relative to the manifest. The backup bytes must match the known historical
hash. The separately supplied restore receipt must contain `database_name`, the same
`backup_sha256`, and `evidence_inventory_sha256`. The latter is the SHA256 of the
canonical sorted JSON mapping of Evidence UUID to SHA256 of that row's canonical
JSON (`database_snapshot`/`digest` implement the algorithm). Recovery should capture
this inventory immediately after restoring, before research. The baseline checks
16,960 historical Evidence rows and the inventory against the live clone. This
verifies supplied provenance assertions; it does not invent a missing restore receipt
or replace the original archive with a fresh ingestion.

## Read-only baseline

```bash
PYTHONPATH=backend/src uv run --project backend python scripts/validate_pursuit_research.py baseline \
  --manifest .artifacts/autonomous-research/corpus.json \
  --corpus-id YOUR_EXPLICIT_CORPUS_ID \
  --baseline .artifacts/autonomous-research/baseline.json
```

Baseline files are created exclusively and never overwritten. They retain the exact
manifest/candidate identity, five-category case projections, metrics, Evidence and
call-note row digests, project/need identities and saved evaluation versions.
The printed baseline digest can be retained in an independent review receipt.
Changing code, manifest, existing research or canonical case data requires a new
baseline. No source request or job is created by `baseline`.

## Explicit bounded execution and dry replay

```bash
PYTHONPATH=backend/src uv run --project backend python scripts/validate_pursuit_research.py run \
  --manifest .artifacts/autonomous-research/corpus.json \
  --corpus-id YOUR_EXPLICIT_CORPUS_ID \
  --baseline .artifacts/autonomous-research/baseline.json \
  --report .artifacts/autonomous-research/report.json \
  --execute --allow-public-research
```

Both execution flags are required even for a fixture manifest. Only selected
questions and their bounded follow-ups enter the worker; unrelated queued jobs are
not drained. The runner stops after at most four jobs per selected need and reports
unfinished/failed/budget-limited cases as incomplete. It does not reset counters or
modify freshness. Public-provider access uses existing configuration and per-question
limits. Missing providers and unsupported routes remain in the question receipts.

The report contains each initial/final pursuit, evidence tier, missing facts, generated
and executed queries, inspected sources/documents, accepted/rejected evidence,
actual/unknown/reserved costs, runtime and exact transition reason. A planning-only
replay checks evidence IDs, question/job IDs and full saved evaluation receipts. Its
transaction rolls back, including any unexpected duplicate work; such work fails the
replay proof. Historical Evidence/call notes, existing project/need identities and
prior evaluation versions must remain preserved.

`mechanical_gates_passed` means the bounded runner, preservation and replay checks
passed. It does not substitute for reviewing source quality or commercial usefulness.
`retained_corpus_proof` remains false: this runner does not independently restore
the archive or verify original project/need bindings. A successful retained run
sets `operator_attested_retained_corpus_validation` when the archive hash and live
evidence inventory match the separately supplied operator restore receipt. This
distinction prevents an operator-supplied inventory from becoming independent
retained-corpus proof. Neither flag is a deployment or overall acceptance claim. Fixture mechanics tests
use fake in-memory sessions and a fake worker, make no network/database writes, and
are labeled accordingly. They verify the runner's accounting and rejection boundaries,
not PostgreSQL ingestion or the five real retained cases.

An unresolved outcome passes the mechanical investigation gate only with a completed
retrieval receipt or a completed discovery query (including a genuine zero-hit search).
Unavailable, skipped, failed, or merely selected routes cannot manufacture this proof.
Run transition metrics include only selected pursuits; retries are selected through
newly created job IDs even when the durable question predates the validation baseline.
