# M3-EVIDENCE — persisted source packages and one typed Jev advisory

READY; M2 independently accepted at base SHA 86a443427b97ff68d1b43bc861f2f8a2ac0cce52. Dispatch UTC 2026-10-23T19:32:07.5000519Z.
Worktree gl3-production-20261023; branch feat/production-intelligence-20261023.
Sol architecture: .agent/artifacts/PRODUCTION-M3-ARCHITECTURE.md. Owner directive
and Finish Contract govern. Opening Tribunal already completed. One Luna only.

Objective: retain schema-validated, versioned packages for existing Evidence,
with cited deterministic facts/entities, quality/coverage, missing fields and
contradictions, then reuse the existing fenced SIGNAL_ADJUDICATION path for one
exact selected Jev advisory. This is not a new freeform extraction API or model
commercial promotion. Keep all original source evidence and existing jobs.

Allowed: backend/src/gridlens/intelligence/evidence_packages.py (new);
backend/src/gridlens/persistence/models.py (new table only); one next migration
in backend/migrations/versions; scripts/materialize_evidence_package.py (new);
backend/tests/unit/test_evidence_packages.py and
backend/tests/integration/test_evidence_packages_storage.py;
docs/operations/production-pipeline-20261023.md; scripts/README.md;
.agent/artifacts/PRODUCTION-M3-EVIDENCE/*. No worker, signal_adjudication,
intelligence_jobs, provider client, policy, source adapter, acquisition comparison,
UI, API schema, credentials, canonical admission/qualification or governance
changes unless a demonstrated narrow gap is approved in a revised packet.
You are not alone. Preserve all other edits. No subagents, commits or live calls.

Use one evidence_packages PostgreSQL table, no new framework/store/ledger.
Unique version key binds evidence ID/hash, observation, project/optional need,
extractor version, question contract and pinned model. Existing versions remain
readable. Use one processing_status on both row and validated JSON payload:
PREPARED / COMPLETE_ADVISORY / INCOMPLETE / BLOCKED, atomically consistent.
Separate document_coverage (FULL_RETAINED_DOCUMENT only proven; RECORD_EXCERPT;
UNAVAILABLE), Jev-visible excerpt coverage, source collection status and missing
fields. A successful advisory never fills missing source facts. Longhorn is
RECORD_EXCERPT and source collection PARTIAL even if advisory completes.

Every asserted fact/entity has exact evidence ID/hash/URL, excerpt location,
value/unit, REPORTED/DERIVED/INFERRED/UNKNOWN label and extractor basis. Derivations
must cite inputs; do not invent confidence percentages, contradictions or units.
Applicant does not automatically mean owner/operator/customer. Only cited claims
support contradiction pairs; preserve unevaluated dimensions explicitly. Existing
permanent onsite generation is proposed supply, not rental-demand proof.

Default runner materializes/inspects only. Required --evidence-id; explicit
--execute-jev permits one job only; --replay uses the existing completed package
and proves unchanged job/call counts, dispatch timestamps and package digest.
Restrict dispatch to loopback 55443/pipeline_m3_app with no DSN query overrides,
finite caps, exact allowlisted observation, verified current hash and identity,
enabled registered source and pinned existing contract/model. Inspect exact
prior signal call/decision before enqueue; deterministic SignalDecision alone
is not prior Jev proof. Use queue_adjudication plus worker.run_one(...,
job_ids=[exact_id]); never drain four existing buying-chain jobs. Completed or
uncertain calls never create a fresh paid attempt. Policy/credentials/stale gates
persist BLOCKED; sent failures/malformed/unknown persist INCOMPLETE with reason
and call ID. No silent alternative model. Metadata output only, no secrets.

Existing Jev policy only: SIGNAL_ADJUDICATION, jev-1.13.0,
typesafe-signal-estimate-v1, max ten allowlisted observations, 16KB request,
one .01 estimated reservation. Preserve false total_input_bound_verified; this
is not a hard invoice ceiling. Existing client sends title300/abstract1500/URL500
characters and metadata; record actual sent excerpt coverage. Controller owns
pricing evidence, environment, live call, migration/retained DB and acceptance.
Builder uses only disposable pipeline_test; no retained/shared DB mutation.

Selected pilot reference (controller-only DB): pipeline_m3_app is a verified
restoration of M2 evidence with 327 Evidence/Observation versions, four projects,
four needs, five jobs and one completed Firecrawl call. Restore receipts in
.artifacts/production-pipeline/m3-restored and m3-retained-before. Longhorn evidence
9b8db416-e93c-4b1a-93d4-4328cc497649, observation
259e6a5c-7e0b-41dd-8ddf-39f2af11d759; selection artifact
.artifacts/production-pipeline/m3-longhorn-selection.json. Its abstract is 1284
characters and ends mid-word; do not claim complete PDF processing. Existing
Firecrawl call requires global total cap2/.02, TypeSafe/model cap1/.01 for pilot.
No provider calls by builder.

Acceptance: schema+citation validation; stale hash and wrong identity rejection;
immutable version history; deterministic replay; atomic status/payload consistency;
correct missing/partial/unknown labeling; exact-job execution and preserved other
jobs; no dispatch when policy/budget/credentials blocked; no new call after unknown;
matching exact call/model/decision before COMPLETE_ADVISORY. Meaningful focused
unit/storage/CLI tests; Ruff/format/mypy; fresh migration and schema drift check.
Controller reruns checks, migration on retained clone with preserved IDs/hashes,
one real Jev execution and replay, full affected gates on frozen SHA and fresh
independent Sol review. Fixtures cannot establish operational proof.

Two materially distinct repair attempts, then canonical requirement recovery.
Handoff COMPLETION.json with exact changed files, commands/results, UTC start/finish,
measured durations, lane/model, config identity, repair count, tokens UNKNOWN when
unmeasured, and remaining gaps. Do not grade own acceptance or parent completion.
