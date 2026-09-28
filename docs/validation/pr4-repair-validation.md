# PR 4 repair validation

Repository: `nrsandoval1231-oss/gl3`; inspected PR head
`44312fc6a9faffbcef1d90f7a930c556f56b355f` and its conversation before editing.
Work was isolated in `gl3-pr4-repair`, branch `repair/pr4-lifecycle`. The original
dirty checkout and the verified GL3-013 checkout were preserved.

## Scope

Accepted ingestion now records conservative project match decisions, with reasons
bound to retained evidence versions. Stable asset identifiers or corroborated
project/site evidence can consolidate sources; owner/company alone cannot.
Ambiguous candidates remain separate. Corrections retain prior evidence and
decisions, and shared needs remain active only while current accepted evidence
supports them. Qualification rules, source adapters/registry, monitoring, and UI
layout/style remain unchanged.

Migration 0006 follows 0005. Lifecycle occurrence dates require source event-date
support; publication dates are not occurrence dates. Explicit replay rebuilds
history from accepted, evidence-hash-bound interpretations. API history identifies
current and superseded evidence and preserves original source attribution.
Production windows are derived estimates, never proof of power demand or a gap.

## Database isolation and retained evidence

All schema creation, destructive tests, migrations, and replay used a new
PostgreSQL 18 cluster at `127.0.0.1:55434`, data directory
`gl3-pr4-repair/.artifacts/pr4/pgdata`, role `gl3_pr4_test`.
`gl3_pr4_suite_test` is exclusively the destructive suite database.
`gl3_pr4_gl3013_test` was the r2 retained-data database;
`gl3_pr4_gl3013_r3_test` is the fresh final migration/replay and browser database.
Separate `gl3_pr4_legacy_*_test` databases exercise legacy migration fixtures.
No production database was used.

The verified GL3-013 database `gridlens_verify_20260927_final` at loopback port
55439 was accessed only for read-only counts and `pg_dump`. Its retained dump SHA256
is `d352b6574fdda75ce905435fb7762b116cf105e1eb7addc19de0b4f439eeddd9`.
It contains 2,530 observations, 2,567 evidence versions, 87 projects/needs, and
87 morning changes at migration 0004. Validation restores this dump into the new
test cluster; it does not migrate or replay the original database.

## Commands and results

Controller receipts and exact candidate identity are recorded in
`.agent/artifacts/GL3-014/CONTROLLER_VALIDATION.json` and `CANDIDATE-controller-r3.json`.
The independent review is separate from builder claims. Raw command output,
database snapshots, and browser traces remain under ignored `.artifacts/pr4`.

| Working directory | Command | Result |
|---|---|---|
| backend | `uv run ruff check src tests` | PASS |
| backend | `uv run mypy src` | PASS; 34 source files |
| backend | `uv run pytest -q tests` | PASS; 220 tests, no skips |
| backend | `uv run alembic upgrade head` twice; `uv run alembic check` | PASS; 0004 through 0005 to 0006, no drift |
| root | `uv run --project backend python scripts/replay_lifecycle_history.py` twice | PASS; 87 accepted, 8 events then 0; 2 unbound, 0 unresolved projects |
| web | `npm run typecheck` | PASS |
| web | `npm run build` | PASS |
| web | `npm audit --audit-level=high` | PASS; zero vulnerabilities |
| web | `npx playwright test` | PASS; 3 authenticated desktop/mobile tests |

The schema export matches the live application OpenAPI object. All nine original
data tables retain identical normalized row hashes after migration/replay (new
project asset/identity columns excluded from the original-column comparison).
Every table has identical row hashes between the first and second replay.
No projects, evidence, or morning changes were duplicated. The targeted legacy
0005 fixture passed after repair: supported permit date/projection retained,
unsupported publication-date fallback cleared. All 15 protected source/configuration
files match the inspected PR head. Browser smoke used API port 8019 and web port
5179 against the migrated GL3-013 copy, including authentication, detail, back/focus,
search, mobile inbox/watch/health, and retained source evidence.

Backend coverage includes actual RSS-to-permit consolidation, unsafe/ambiguous
matching, retained correction decisions, shared-source withdrawal, upstream
permit/spud/completion with out-of-order arrival and corrected completion dates,
evidence-version reversion, replay, authenticated API citations, and tier separation.
The retained NC/Georgia examples supplement explicitly synthetic upstream cases.

The first integrated candidate failed an existing exact RSS duplicate regression
and independent review. Those findings and the failed browser test are retained in
`REVIEW-r1.json`. The browser failure was a test helper collapsing an already open
group before its second navigation; the helper now checks expansion and clicks the
specific member while retaining all back/focus/search assertions. A separate
legacy migration probe caught overbroad date cleanup; supported permit dates must
survive while unsupported publication-date fallbacks are removed.

The second review rejected r2 despite its green gates: a later Signal could
overwrite still-supported Prospect facts on a shared need, and an RSS article
naming two different sites could match its first address. `REVIEW-r2.json` retains
those findings. The bounded repair selects one complete current supporting claim
without combining partial claims into a Prospect, recomputes on withdrawal, and
keeps conflicting site claims separate with a recorded reason. Both arrival
orders, withdrawal, replay, repeated identical address mentions, and two-site
ingestion are tested. Those tests also exposed a matched-project key that was
only changed in memory; the final assessment JSON is now explicitly persisted
before support reconciliation.

## Hosted CI and limitations

GitHub Actions run `36417941520`, including a retry, failed before execution:
both jobs had zero steps and runner ID 0. GitHub's annotation states that recent
account payments failed or the spending limit needs increasing. This is runner
admission failure, not executed code failure. The workflow was not weakened.
Initial GraphQL inspection returned no branch protection rules; final head,
protection, and normal merge permission must be checked again before merge.

No live upstream OCC adapter or verified live upstream record is added. Illustrative
well identifiers/dates are labeled synthetic. Unbound legacy assessments are
reported and skipped rather than assigned invented evidence. Replay does not mass
merge existing projects. Broad first-production ranges are transparent heuristics.
The suite emits one dependency deprecation warning for Starlette's httpx test client.
Cloud deployment, nationwide coverage, and the parent launch Finish Contract remain
open; local acceptance of this PR does not establish them.
