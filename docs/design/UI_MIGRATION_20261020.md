> Historical October 20 migration. The October 21 [UI canon](UI_CANON.md) supersedes its presentation decisions. Original dated content follows unchanged.

# UI authority migration inventory — October 20, 2026

The approved v3 reference screenshot is committed at [`pursuit-workspace-v3-approved.png`](references/pursuit-workspace-v3-approved.png), with source and SHA-256 in [`pursuit-workspace-v3-reference.json`](references/pursuit-workspace-v3-reference.json) and [`references/README.md`](references/README.md). The interactive prototype remains at `../.artifacts/velto-ui-exploration-20261020/v3/` (relative to this checkout). [`UI_CANON.md`](UI_CANON.md) is the sole active presentation authority. [`PURSUIT_WORKSPACE.md`](PURSUIT_WORKSPACE.md) records the interaction contract. [`BRAND_ASSETS.md`](BRAND_ASSETS.md) and `brand.tokens.json` document the application lockup and additive application tokens.

## Kept functional requirements

All 42 PRD requirements remain in force. Qualification, evidence provenance, power-gap calculations, nationwide scope, acquisition/source requirements, independent Signal/Prospect/Lead tiers, workflow persistence, security, operations, recovery, and release acceptance are unchanged. Requirement 31 retains independent tier search/filtering and its geography, industry, activity, timing, MW, priority, and status filters; only its old primary-navigation presentation is superseded. The October 1 PRD decisions about cannabis evidence, company/site titles, and the 300 kW visibility floor remain intact.

## Retired presentation

- October 18 Direction B visual treatment and 58/42 layout: superseded by the October 20 v3 visual treatment with a 55–60/40–45 queue/context split and comfortable queue rows. Existing Opportunities/Research/Signals/Operations navigation and supported routes remain active; the v3 prototype's Pursuits/Saved navigation is not a production route change.
- Signals remains the entry to a shared grouped-source evidence browse, defaulting to Signal and retaining a local Signal/Prospect/Lead selector. Preserve grouped physical-project members, source context, group/cohort units and counts, SHOW/REVIEW/HOLD decisions, all PRD-required advanced geography/industry/activity/timing/known-MW/priority/workflow filters, and qualification-scoped CSV. Opportunities remains the separate need-level prioritized queue. Shared browse styling and tier selection do not merge group counts with need counts or weaken any PRD tier/filter requirement.
- The v3 prototype's three counters are not all current production metrics. Keep real server-backed Action now/Research/Watch disposition facets and the persisted material-change review workflow. Do not expose fictional follow-up or open-question counters.
- October 1 map-first, atmospheric/cinematic scene, animated transformations, and their browse/detail visual references: historical only.
- October 1 `canonical-ui-reference.json`: retained with hashes and provenance, relabeled `HISTORICAL_SUPERSEDED`; it is no longer an active authority.
- October 1 `BUILD_FOCUS_EXPERIENCE.md`: full original handoff retained under `docs/design/archive/` and replaced at its old path by a redirect notice.

## Historical exclusions and evidence boundary

Dated screenshots, validation receipts, audits, reports, and historical source observations retain their original contents and dates. They may describe the UI active on their own candidate/date and are not silently rewritten as if the October 20 design had already shipped. The standalone v3 prototype contains fictional examples and tab-local state; it is presentation evidence only. This migration changes no backend semantics, production state, deployment claim, or release gate. No runtime-final-proof claim is made here.
