# Decisions

## 2026-11-06 — Owner-managed pursuits override the retired manual-workflow canon
Owner explicitly requested a Pursuits workspace (stages, follow-up tasks, confirmed activity logging) and a UI overhaul, reversing the canon's "no call/status/note workflows; redesign deferred". Decision: implement in phased PRs on `feat/commercial-workspace-ux`, amend canon docs in the same PRs, single-owner model (unique pursuit per opportunity, no user accounts). Alternative rejected: real user accounts (larger auth change).

## 2026-11-06 — Separate tables for commercial pursuits
New `commercial_pursuits`, `pursuit_tasks`, `pursuit_activity` (migration 0050) instead of extending research `pursuits`, because the existing table is keyed to research identity/snapshots, not to a user's execution state.

## 2026-11-06 — Never fabricate confidence
The approved designs show a "Confidence" value, but the project payload has none and the code states priority is not confidence. Cards show real priority/unknown instead.
