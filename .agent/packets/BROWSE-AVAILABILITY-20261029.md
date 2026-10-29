# Browse availability repair — 2026-10-29

Status: historical execution packet. PR147 is merged and deployed; final gates and
live journeys completed. See [current checkpoint](../CURRENT_STATE.md) and
[final release evidence](../../docs/validation/browse-availability-repair-20261029.md)
for remaining limits. Pending/next statements below describe earlier checkpoints,
and former worktree paths now map through the owner-local cleanup archive.

READY packet: owner requests end-to-end live browsing repair, bounded performance work,
operational diagnosis, authenticated QA and PR. Base `37cc949b4c230851c88f4181966b888a26e1f037`,
branch `fix/browse-availability-20261029`; dedicated worktree `browse-availability-20261029`.
Product authority: [AGENTS](../../AGENTS.md), [results canon](../../docs/product/PROJECT_FIRST_RESULTS_CANON.md),
[finish contract](../FINISH_CONTRACT.md). Preserve qualification, provenance, deletion,
privacy, authentication, operator grouping, source budgets and canonical visual identity.

Sol coordinates four independent Luna/low lanes: browse invalidation/publication;
frontend context/loading; source operational diagnosis; grouped request SQL performance.
File ownership is disjoint. Root Astra independently reviews actual integrated bytes;
root controls production recovery/deployment. No paid providers, ingestion replay or
destructive retained-data changes. The existing dirty `gl3` checkout is outside scope.

Acceptance: current complete generation during ordinary scoped ingestion; atomic publish;
safe expiry preparation; full/indeterminate changes remain fenced; meaningful PostgreSQL
and browser regressions; full repository gates; actual authenticated live journeys and
safe API timing samples. Targets are first results <=2s, warm search/filter <=500ms,
detail/open <=1s and immediate cached Back. Misses remain explicit.

Initial evidence: all deployed roles `37cc949b`, schema `0048_browse_recovery_stages`.
13:33 UTC state input123476/full122577, current generation90739840 at input123476,
1896 rows, no dirties; 22576 observations,1969 projects,1966 needs. Maintenance logged
superseded input117397 then published123476. Generation evaluation timestamps alone
do not measure build duration. Continuous full revision invalidation of company identity
and identifier statements is the code-level availability cause under investigation.

Baseline: sixteen serial authenticated HTTPS requests from production API container,
four each All/Oil & Gas/Data Centers/Diamondback, running worker and browse services,
all200. Combined median1206.8ms; nearest-rank p95 (16th sorted sample)1648.2ms.
All1184.1–1429.5; Oil & Gas1248.1–1648.2; Data Centers351.1–422.6;
Diamondback1166.3–1265.6ms. Response390–4688bytes. Production was dirty0 during
this sample; this is no proof of concurrent ingestion availability. A short-lived ordinary
persisted session was removed after the probe. SQL profiling confirms duplicate cohort
count/page aggregation dominates these requests (~1.2s database of ~1.2s total).

Operational findings: RRC MFT endpoints timeout even with proxy disabled; TCEQ retains
318valid rows and reports one summary404; Austin intentionally pauses an eight-job chain
with persisted cursors; Houston latest successful check and earlier failed schedule receipt
describe different time windows. Paid master gates intentionally remain closed.

Validation uses an isolated native PostgreSQL18 cluster at loopback port55441, dedicated
`gridlens_browse_test` and `gridlens_browse_browser_test`; ignored environment contains
generated test secrets and no retained settings. No production database used for tests.

Next: integrate lane fixes, deterministic gates, independent review, safe deploy and live QA.
Unknown: after-change timing, long-running ingestion/rollover behavior, authenticated
desktop/mobile detail journeys, live release revision and external RRC recovery.


## Integrated checkpoint — 14:15 UTC

All four implementation lanes delivered. Root Astra independently inspected the
actual backend invalidation OLD/NEW/history/fallback mapping and strict generation
fences, rollover/future interval safety and UTC recovery receipt normalization;
the SQL window totals, ordering/cohort semantics and empty-page fallback; and
frontend logout/version fencing, independent parent/child expiry, fail-closed dates
and the Signals Back repair. No material code finding remains from those reviews.
Acceptance remains conditional on exact integrated full gates and live operation.

Static gates pass: Ruff/format401 files, mypy183 source files, repeated migration
upgrade and Alembic drift check, backend/brand dependency audits, npm audit, maintained
doc links, canonical216-asset brand verification, web typecheck/build. Full browser
rerun passed156/156 in55.4s after two Signals Back regressions were repaired without
weakening assertions. The popstate listener now reads current filters via a ref.
One final diagnostics label clarification is being applied for the explicitly
reported latest-check versus schedule-window status confusion.

First backend full run:3294 passed/2 skipped/9 setup errors/1 failed in829.66s.
Nine setup errors were a controller environment mistake: adversarial safety fixture
rejects application names ending `_test`, despite distinct isolated DBs. Fixed
using dedicated empty `gridlens_browse_app`. The failure was manual cancellation of
one owned native PostgreSQL preflight query after >10min without lock wait; no
assertion failure. All ten affected cases then passed in15.83s without source/test
changes. A complete corrected-environment rerun is in progress. Failed receipts are
retained, not replaced by later passing claims.

Release, current policy rebuild, production API timing percentiles, representative
authenticated browser journeys and actual ingestion/rollover read continuity remain
pending. Root owns production writes and the already-authenticated browser session.


## Freeze checkpoint

The remaining ordinary RRC company_project_memberships full invalidation was identified
before release and is now scoped through OLD/NEW project owners. Source-policy/global
unknown changes remain full. Retained editorial tables have no current writer calls.
Seven focused membership tests, actual0048→0049 migration cycle and installer parity
passed; root reviewed the final mapping with no material finding. Membership deletion
is safely project-scoped, not exempt from invalidation. Full malformed/TRUNCATE fences
remain. Final diagnostics labels passed affected browser, typecheck and build checks.

Second backend full run:3300 passed,2 skipped,4 failed in414.49s. All four failures
were UndefinedTable on the newly created, unmigrated app auth schema (controller
harness mistake). The dedicated loopback app schema was then migrated and the eight
auth/origin/source-route checks passed in1.62s with unchanged assertions. No application
security or test semantics were relaxed. The final full gate uses the migrated app
schema and a separate dedicated test database. Previous failed runs remain evidence.
