# Decisions

## 2026-11-06 — Owner-managed pursuits override the retired manual-workflow canon
Owner explicitly requested a Pursuits workspace (stages, follow-up tasks, confirmed activity logging) and a UI overhaul, reversing the canon's "no call/status/note workflows; redesign deferred". Decision: implement in phased PRs on `feat/commercial-workspace-ux`, amend canon docs in the same PRs, single-owner model (unique pursuit per opportunity, no user accounts). Alternative rejected: real user accounts (larger auth change). Scope: Pursuits workspace only; Opportunities browsing stays read-only and internal safeguards are unchanged. Nav is Opportunities | Companies | Pursuits | Reports; research view moved to `?view=research`. Not deployed: production remains at schema 0049 (PR165); 0050 not applied anywhere. Details: `docs/engineering/commercial-pursuits-20261106.md`.

## 2026-11-06 — Separate tables for commercial pursuits
New `commercial_pursuits`, `pursuit_tasks`, `pursuit_activity` (migration 0050) instead of extending research `pursuits`, because the existing table is keyed to research identity/snapshots, not to a user's execution state.

## 2026-11-06 — Never fabricate confidence
The approved designs show a "Confidence" value, but the project payload has none and the code states priority is not confidence. Cards show real priority/unknown instead.

## 2026-11-06 — Flat project cards are the default Opportunities browse
Owner decision: the flat project cards (with KPI row and restyled detail) replace the operator/customer group browse as the default on `feat/commercial-workspace-ux`. The released group browse is not removed: it is selected with `?groupBrowse=1` (previously the default, selected by the absence of `projectBrowse=1`), and `?projectBrowse=1` stays as an alias so old bookmarks work. Mode is derived only from the URL, so each browse writes its own parameter and back/forward preserve it. Specs and the real-backend rollup acceptance lane that relied on the old default now visit `groupBrowse=1` explicitly. Not merged or deployed.
