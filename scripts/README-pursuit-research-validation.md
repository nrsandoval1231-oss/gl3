# Bounded autonomous research validation tools

These are internal isolated validation utilities. The [Autonomous Intelligence Canon](../docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md) supersedes historical manually submitted research and evaluation workflows. Historical call notes remain protected evidence; this guide does not authorize their user-facing creation or public mutation routes.

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
uv run --project backend python scripts/validate_pursuit_research.py baseline \
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
uv run --project backend python scripts/validate_pursuit_research.py run \
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

## Fresh corpus regeneration (October 7 authorization)

`regenerate_pursuit_corpus.py` creates a **new** `reingested` corpus; its receipts
never establish original PR23/R4 archive preservation. Use a new output directory
under ignored `.artifacts/` for each command. Each file is written exclusively.
Freeze the script and candidate before validator baseline capture.

```bash
python scripts/regenerate_pursuit_corpus.py collect --selection selection.json --output .artifacts/new-collection
python scripts/regenerate_pursuit_corpus.py ingest --collection .artifacts/new-collection/collection.json --output .artifacts/new-ingestion
python scripts/regenerate_pursuit_corpus.py snapshot --output .artifacts/new-snapshot
python scripts/regenerate_pursuit_corpus.py backup-restore --target-db gl3_regen_restored --pg-bin /usr/bin --output .artifacts/new-restore
```

Run with the existing backend environment and `DATABASE_URL` pointing to a migrated,
quiescent, isolated `gl3_regen_*` database. Selection is a JSON list (or an object
with `records`) of at most 40 unique `{source_id, external_id}` pairs supported by
existing exact native acquisition. Each request is bounded to 30 seconds and
750,000 bytes. The collection preserves request URLs/times, typed failures, and
hashes of **adapter-rendered canonical records, not raw HTTP response bodies**.
Ingestion verifies artifact hashes, native identities and current registry bindings,
requires an initially empty Observation table, and uses canonical `process_records`
with models disabled and exact queued/leased jobs. Rejected native records remain
visible in counts/observations; they are not fabricated into accepted needs. No
unrelated jobs are drained. Ingestion receipts expose all canonical observations,
evidence, projects, needs, current cards and outstanding jobs for operator review.

Backup/restore uses the authorized connection with passwords only in subprocess
environment, creates a fresh target (never drops one), and records command exit
codes, dump hash and source/restored inventories. Sources and Observations join the
validator's evidence, call-note, identity and saved-evaluation checks. Source changes
during backup or any inventory mismatch fail the receipt. No credentials or raw
subprocess error text are persisted. A failed target is left for inspection.

Point `DATABASE_URL` at the restored clone before preparing a `kind: reingested`
five-category manifest and running the existing baseline/run commands above.
Keep collection/ingestion/restore receipt hashes alongside baseline/report hashes.
The meaningful-investigation, Austin exception, preservation and replay gates are
unchanged; unsupported O&G discovery or failed routes remain explicit gaps.

### Partial execution diagnostics

When only one to four real canonical cases are available, use the explicitly scoped
`diagnostic` command with a `kind: reingested` subset manifest. This preserves the
full validator's rejection in `full-gate.json`; it does **not** redefine that gate.

```bash
python scripts/regenerate_pursuit_corpus.py diagnostic --manifest partial.json --output .artifacts/partial-diagnostic --execute --allow-public-research
```

The database must match the manifest and use `gl3_regen_*`. The original canonical
category checks, research budgets, baseline, execution, preservation and replay
helpers run unchanged. Baseline/report files retain detailed attempts and evidence.
Every report declares `scope: partial_diagnostic`, explicit `missing_categories`,
`full_five_cohort_acceptance: false`, and both retained-proof flags false, even when
subset mechanics pass. Candidate changes fail diagnostic mechanics. A successful
exit means only the subset diagnostic completed successfully, never five-cohort
acceptance. Use the existing validator for a full five-category manifest.

Collection and ingestion now set `passed: false` and exit nonzero for any failed
attempt (including upstream collection failures), while preserving partial successes.
An empty successful collection cannot start ingestion. Native rejection is recorded
in canonical ingestion counts and does not itself imply an acquisition error.
Acquisition failures retain only the exception class and, when available, the adapter's
safe enum code. Ingestion terminal writes recheck the worker fence; lost ownership
leaves the newer worker's lease untouched.

Restore snapshots additionally hash every row of every actual public table,
including mutable Project/PowerNeed fields and job/question receipts. These full
inventories are for backup parity only; they do not expand the research validator's
immutable-table rules. Canonical row hashes are sorted with duplicates preserved,
and table names are obtained from SQLAlchemy inspection and dialect-quoted.

This wrapper excludes `federal-register-eis` from both collection and imported
collection ingestion: its canonical ingestion can implicitly fetch companion PDFs
outside this wrapper's exact-request bound. Native permit adapters remain supported.
PDF links are never silently stripped to force records through this restriction.

Connection URLs must use `postgresql` or `postgresql+psycopg` with an explicit
host, port and username. Passwords may be omitted. Only scalar `sslmode`,
`sslrootcert`, `sslcert` and `sslkey` query options are accepted; host overrides,
service aliases and other query options are refused so SQLAlchemy snapshots and
PostgreSQL command-line tools cannot silently select different servers.

The seeded browser harness now targets `first_path.spec.ts` and `autonomous-research.spec.ts` by default. The removed manual-pursuit test is not an acceptance target. Fixture mode disables external autonomous research and clears provider keys; it verifies source/browse/research UI mechanics only, with no claim of real contacts, live collection, scheduler cadence or production readiness.
