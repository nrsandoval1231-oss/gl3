# Browse availability repair — October 29, 2026

Owner scope: restore useful, fast project browsing during normal background work,
preserving operator/customer grouping, qualification, privacy, provenance and the
canonical interface. [Packet](../../.agent/packets/BROWSE-AVAILABILITY-20261029.md)
and [current state](../../.agent/CURRENT_STATE.md) track candidate acceptance.

## Final release status — verified October 29, 2026

PR [147](https://github.com/nrsandoval1231-oss/gl3/pull/147) merged at
`4376f4d13e0a13a0c8fb9bf7c004dbba89c5c4cb`. Deployed source
`e153cefde8ababbe23ff0a4ef48af8c98fb61d28` has the identical application tree.
At 15:14:22 UTC, API, web, ingestion worker and browse worker were running the
verified release images with zero restarts, readiness READY and external HTTPS 200.
Schema: `0049_scoped_identity_browse`. This is a dated observation, not continuous monitoring.

Final source CI run `40894911298` passed. Local backend: 3308 passed, 2 skipped,
7 subtests; browser: 158 passed. Independent source review had no unresolved
material findings. Authenticated desktop, tablet and mobile journeys passed,
including sector filters, group expansion/pagination, details, search, Signals,
Research and diagnostics. These results supersede the preliminary pending gates below.

Comparable 16-read HTTPS API median improved from 1206.8 ms to 398.45 ms;
p95 was 954.5 ms (the maximum of this small sample, not a robust tail estimate).
Oil filtering (890.1 ms median) and atomic group open (1376.8 ms median) still
miss their targets. Actual live read/update overlap and midnight rollover remain
unverified. RRC endpoint failures remain external/unknown. No full sustained
availability or commercial acceptance is claimed.

Fresh backup and isolated restore matched all 74 tables. Paid provider gates
remained closed. No credential change, provider activation or production-data
replacement was performed. Detailed owner-local release receipts are retained in
`C:\Users\nrsan\Nucleus\02_Projects\GridLens\.repair-release-20261029`.

## Pre-release investigation and measurements

The remaining sections preserve the investigation as recorded before release.
Final release results above supersede their pending deployment/QA statements.

## Verified cause

Production API, worker, browse maintenance and web ran source `37cc949b`; database
schema was `0048_browse_recovery_stages`. Actual PostgreSQL trigger definitions,
read on October 29, confirmed that every INSERT/UPDATE/DELETE on
`company_identities`, `identity_identifiers` and canonical company/project membership writes called
`invalidate_browse_generation('full')`. Routine identity reconciliation therefore
advanced the global full revision, even for an unreferenced new identity.

Readers correctly require the current input revision, policy and time interval.
The worker's scoped publication cannot repair a full invalidation. A full rebuild
can be superseded by another full invalidation. Maintenance logs recorded a
superseded generation at input 117397 and a published replacement at input 123476.
This explains the unavailable period during identity/ingestion churn; retries in
the browser cannot repair it. Generation `built_at` values are evaluation times,
not precise build-duration receipts. No current lock contention was seen in the
bounded database snapshot.

At the baseline snapshot, state input 123476/full 122577 matched generation
`90739840-55aa-4e1c-900e-010ebef29e35`, 1896 rows, with no dirty projects. Retained
data: 22576 observations, 1969 projects, 1966 needs; current All 398 groups,
Oil & Gas 281, Data Centers 18. These counts describe that snapshot, not fixed totals.

## Change

Migration 0049 scopes identity and company/project membership changes to every resolvable affected project using
OLD/NEW identities, historical buying-chain links and memberships, and retained
browse customer memberships. Valid identities with no dependency do not invalidate
unrelated results. Indeterminate payloads and TRUNCATE retain full invalidation.
Current-generation qualification/security fences remain active. Replacement
generations still publish atomically; no stale successful API fallback was added.
Clock replacement preparation starts 15 minutes before expiry, providing margin
for the previously observed multi-minute retained rebuild. Recovery-stage integrity
hashes normalize aware timestamps to UTC so database session time zones cannot
invalidate an otherwise identical stage.

Group and child pages calculate counts in their page aggregation, avoid a second
full cohort aggregate on ordinary pages, and reuse matched rows for unfiltered All.
Empty/out-of-range pages preserve exact totals. Search requests disable PostgreSQL
JIT within their transaction after measured compilation overhead; global database
settings are unchanged.

The interface debounces search 300 ms, cancels obsolete requests, preserves valid
prior summaries with an updating label, and pauses details until the requested
cohort is current. A bounded memory cache retains navigation context and expires
with backend validity. Session clearing invalidates it globally and prevents late
cleanup writes from repopulating it. Initial loading, refreshing, empty, pending
and terminal states are distinct. Signals and diagnostics no longer combine
terminal failure with loading text; More-menu contrast and navigation closure are
repaired without redesign.

## Measured performance

Baseline: 16 serial authenticated HTTPS requests from the production API container,
four per route, worker and browse services running but no dirty projects during
the sample. All returned 200. Median 1206.8 ms; nearest-rank p95 = 1648.2 ms (16th
sorted sample). Responses were 390–4688bytes. A short-lived normal persisted
session was removed after probing. These are API timings, not browser paint times.

Read-only before/after function comparison used the same 1896-row production
generation, a 5 s statement timeout and verified read-only transaction. Candidate
module source was compiled only in subprocess memory; no deployed files or data
were changed. Each group route had two measurements; report ranges, not percentiles.
IDs, totals and selected project results matched.

| Route | Baseline function ms | Candidate function ms |
| --- | ---: | ---: |
| All | 1104–1114 | 298–389 |
| Oil & Gas | 1046–1225 | 603–696 |
| Data Centers | 323–351 | 147–166 |
| Diamondback | 1209–1226 | 592–687 |
| One group expansion | 1434 | 511 |

Group calls originally ran 3 database statements: generation lookup (~1 ms), cohort
count (~549 ms) and page (~644 ms) for All. Query plans showed cached-buffer work,
no disk reads; duplicate aggregation dominated. Candidate ordinary group pages use
one aggregate plus the generation lookup. Snapshot metadata adds 198 JSON bytes.
The Diamondback range above predates the final transaction-local JIT change:
its final SQL plan measured 498 ms with JIT, including 195 ms compilation, versus 366 ms
without. This plan comparison is not a post-change full API measurement. Oil & Gas
still misses the practical 500 ms warm target; its plan remained ~630 ms with 99739
shared buffer hits and no disk reads or JIT. Live post-deployment API/browser
measurements and concurrent-ingestion acceptance remain required.

## Related operational findings

RRC drilling had an active terminal acquisition timeout after 5 attempts; two new
RRC well-research jobs failed with ConnectError. Bounded read-only production-host
GET probes found both official MFT listing endpoints timing out with and without
proxy use. The separate EWA W-1 form endpoint returned 302 in 0.36 s; this does not
identify the failing later well-research request. No timeout/budget increase,
ingestion replay, query POST or record-specific probe was used.

TCEQ NSR processed 318 retained unchanged rows and reported one summary-document404
as a partial result. Austin's 8-job chain bound intentionally pauses work with
durable cursors; its 13-test regression suite verifies that the next normal schedule
resumes the same cursor. Houston's latest check succeeded with 1128 unchanged rows;
a prior failed scheduled receipt remains in its 7-day schedule-health window.
Historical failure counts are not proof that the latest acquisition failed.

Configured-but-disabled OpenAI/Typesafe and closed paid master gates were intentional
preexisting deployment settings. No providers, budgets or credentials were changed.

## Validation and release boundary

Focused evidence: 34 PostgreSQL availability/recovery/rollover tests, 7 membership follow-up checks, 3 request-query
tests and 13 Austin collection-budget tests passed. Local validation uses disposable
databases on a dedicated loopback PostgreSQL 18.6 instance. Production data was not
used for tests. Full integrated checks and independent review are recorded in the
packet/checkpoint when finished; these focused results alone do not certify release.

Root release procedure uses the actual Docker Compose host: build immutable images
including 0049, preserve existing configuration and closed paid guards, hold workers,
take a fresh backup and verify an isolated 74-table restore, migrate 0048→0049 once,
stage/inspect/publish a retained-data generation with the candidate policy, then
canary before workers resume. Stage deadlines must accommodate the actual rebuild.
Retain previous images. Rollback uses previous images plus a freshly valid generation
for their policy; do not restore an old database over new canonical writes or
downgrade schema as an availability shortcut. Exact deployed revision, backup,
rollback receipt, live API percentiles and authenticated desktop/mobile QA remain
separate release evidence.
