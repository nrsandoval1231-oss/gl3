# B1 saved browse implementation plan

> Execute natively under Nick's explicit implementation/review/merge/deploy authorization. Obtain an independent whole-branch review before merge.

**Goal:** Replace request-time evidence reconstruction with versioned PostgreSQL browse/ranking generations while preserving canonical semantics and the approved UI.

**Architecture:** Canonical evaluators build immutable generations outside requests. Transactional database triggers invalidate a generation on relevant writes, including SQL writes outside the ORM. Readers use indexed scalar summaries and persisted normalized search text; filtered grouping remains query-dependent. Publication compares the captured input revision atomically. No fallback to stale qualification or request-time reconstruction.

**Spec:** Current PRD, AGENTS.md and Library audit `libfile_421e8e2d551c8191866a4b6548d4818c`; bounded package B only. Baseline main `9e20bbda76e6e55c1afe2af85e81a5613e31603f`.

## Constraints and decisions

- Preserve canonical evidence, operator acceptance/rejection, correction/withdrawal, tier, buying roles, global rank and exact normalized substring search.
- Group after dimension filters, before search and decision filters. Store both project and singleton group identities; do not freeze one global grouping.
- Preserve global revision fencing. Ordinary fact/workflow transactions publish a new generation atomically using a four-table dirty-project whitelist; copy unchanged rows in SQL, canonically reconstruct all changed-project needs, recompute global scalar groups/counts. Unknown/bulk/policy/clock changes remain full-build pending. No hidden stale Lead fallback.
- Expire at the earliest UTC/local date rollover or operator fact effective boundary. A generation crossing a clock boundary during construction cannot publish.
- Retain previous generations for reversible publication only when their input revision, policy and clocks remain current. Old application image remains the deployment rollback path.
- Add migration 0021 after main's provenance 0020; leave PR72/73 untouched.
- Collection, scheduling, autonomous research and paid AI remain OFF; budgets zero. Projection maintenance performs retained-data reads only.
- No UI redesign, new infrastructure dependency, evidence deletion, credential creation/transmission, or access/network changes.

## Tasks and proof

1. Add generation/state/row models, migration, transactional invalidation triggers and publication fencing. Prove commit/rollback, bulk SQL mutations, failed build, concurrent publication and restart safety on disposable PostgreSQL.
2. Build canonical summaries, ranks, normalized historical search and compact presentation rows in bounded batches. Capture input/policy versions and clock bounds. Prove canonical parity across filters/groups, operator facts, withdrawals, buying chains and date boundaries.
3. Add indexed SQL page/cohort/group queries and selected-need detail reads. Keep legacy canonical paths available behind an explicit rollout switch for comparison and reversible deployment. Prove no evidence reconstruction on saved browse and bounded page output.
4. Add retained-data-only rebuild CLI/maintenance, pending response and operational instructions. Test migration twice and schema drift.
5. Run regression suites and realistic-history fixture benchmarks at measured cardinalities, 2x and concurrent reads; report fixture limitations, p50/p95/max, SQL counts and payload sizes.
6. Independent review; publish PR; verify exact-head CI. Merge without bypass only after correctness/performance gates pass. Backup, reversibly deploy and verify authenticated pages/persistence only using existing access. Report access blockers precisely.

## Review focus

Rejected or superseded facts must not support current qualification. Group membership must change correctly when filters remove siblings. Search must preserve cross-field/history substring behavior and Unicode normalization. Broad changes committed during a build must prevent publication; bounded scoped tails must be canonically rebased, including edits already published incrementally. No endpoint may label an expired generation as current.

## Availability repair after PR77 review

Measured initial full rebuild availability was unacceptable for ordinary edits.
The owner explicitly required mutation-to-fresh, repeated-write and expiry
measurements before merge. Added transactional incremental publication for the
proven four-table operator scope, savepoint failure isolation, conservative full
fallback, retained dirty history across concurrent builds and fenced bounded tail
rebase. Independent review reproduced and the regression now prevents a lost-edit
rebase bug. SQL cloning/pruning remains population-sized; calendar expiry still
requires full canonical rebuilding and is an explicit availability limitation.
