# Decisions

## 2026-11-06 — Owner-managed pursuits override the retired manual-workflow canon
Owner explicitly requested a Pursuits workspace (stages, follow-up tasks, confirmed activity logging) and a UI overhaul, reversing the canon's "no call/status/note workflows; redesign deferred". Decision: implement in phased PRs on `feat/commercial-workspace-ux`, amend canon docs in the same PRs, single-owner model (unique pursuit per opportunity, no user accounts). Alternative rejected: real user accounts (larger auth change). Scope: Pursuits workspace only; Opportunities browsing stays read-only and internal safeguards are unchanged. Nav is Opportunities | Companies | Pursuits | Reports; research view moved to `?view=research`. Not deployed: production remains at schema 0049 (PR165); 0050 not applied anywhere. Details: `docs/engineering/commercial-pursuits-20261106.md`.

## 2026-11-06 — Separate tables for commercial pursuits
New `commercial_pursuits`, `pursuit_tasks`, `pursuit_activity` (migration 0050) instead of extending research `pursuits`, because the existing table is keyed to research identity/snapshots, not to a user's execution state.

## 2026-11-06 — Never fabricate confidence
The approved designs show a "Confidence" value, but the project payload has none and the code states priority is not confidence. Cards show real priority/unknown instead.

## 2026-11-06 — Flat project cards are the default Opportunities browse
Owner decision: the flat project cards (with KPI row and restyled detail) replace the operator/customer group browse as the default (PR #183, merged to `main` as `cbe4aec`, not deployed). The released group browse is not removed: it is selected with `?groupBrowse=1` (previously the default, selected by the absence of `projectBrowse=1`), and `?projectBrowse=1` stays as an alias so old bookmarks work. Mode is derived only from the URL, so each browse writes its own parameter and back/forward preserve it. Specs and the real-backend rollup acceptance lane that relied on the old default now visit `groupBrowse=1` explicitly. Merged to `main` (PR #183), not deployed.

## 2026-11-11: Ingestion write performance, what shipped and what did not (Phase 2)
Shipped: indexed project matching (`projects.match_keys`, 0055) and statement-level, index-driven browse dirty-project triggers (0056); all-new RRC ingestion at 50k projects 1,044 s to 25 s and independent of corpus size. Not shipped: batched commits (removed from the PR; no all-new gain, FK-referencing API inserts wait for an open batch) and bulk-skip of unchanged records (an unchanged structured permit already writes no rows, about 4.7 ms). Deferred to Phase 4: a lock-free commit-time browse revision (design and prerequisites in `docs/engineering/ingestion-writes-phase2-20261111.md`), because it rewrites a pinned in-transaction revision invariant and only matters with parallel writers. Details and numbers: `experience/benchmarks.md`.

## 2026-11-11: A benchmark seeded with raw SQL can measure the fallback, not the feature
Raw INSERT seeding left the new `match_keys` NULL, which forces every row to be a candidate, so the first indexed-matching benchmark measured the full-scan fallback. Seed through the same path production data takes (or backfill the derived column) and check that the indexed path is the one being timed.
