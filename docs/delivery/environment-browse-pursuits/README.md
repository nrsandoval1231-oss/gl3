# Browsing and commercial pursuits in the environment

Follow-on to PR #64, based on `c1b01dd2db47223b5d49743a82fb829172f41b96`.
Main remained `298bc40c3ab88789bb1bb6e9f714c551d34b29c9` when fetched.
The previous slice was preserved on its own branch and PR.

## Behavior

Previously, All records and the commercial queue left the canonical environment.
They now expand its subject while retaining the navy canvas, branding, receding
map, command bar, and browser-history restoration. Advanced record browser,
source health, ingestion, and legacy full-record routes remain reachable.

- All records pages through the authenticated opportunity API independently of
  the map cap. Tier, lens, and search apply nationally, as explicitly labeled;
  map geography remains available on Back. A changed cohort requests a first-page
  restart rather than mixing results. Counts distinguish total matches from
  the map's loaded subset.
- Commercial disposition, paging, search, and selected need are separate scene
  fields from opportunity tier/lens/search. Search and disposition counts apply
  to the loaded commercial page. A selected pursuit outside those filters stays
  explicitly separate from the matching list/count. Investigate uses its need
  identity and returns to the expanded commercial record, scroll, and focus.
- Commercial note input and research question/result state live outside navigation
  snapshots, keyed by both need and pursuit identity. Notes and pending saves
  survive navigation; retries retain the existing client id. The same bounded
  eight-hour tab storage and logout cleanup from #64 protect refresh continuity.
  Storage failure is visible. Navigation does not save notes, accept facts,
  request research, evaluate Signals, or promote tiers.
- Research disclosures wait for their initial response and restore independently
  by question identity. Commercial read responses cannot overwrite newer pages.

The pre-change browser reproductions failed because both menu destinations
unmounted `.env`. Later regressions caught disclosure timing, label stability on
remount, and low-contrast headings inherited from the legacy shell.

## Limits

This is a bounded integration, not complete shell consolidation. Advanced browse
filters and ingestion retain their existing legacy destinations and return link.
A commercial card that leaves the saved page is identified as missing from that
page; the existing saved evaluation history remains available. No replacement
card is selected automatically. Inner saved-history query/page/expanded-version state,
the related-project picker, and the older research workspace retain their legacy
component-local behavior; this slice does not claim full restoration of those
secondary tools.

The local PostgreSQL service was unavailable during the first slice; real-data
and saved-server-result acceptance require the configured service. Fixture
browser checks do not establish that acceptance. The exact checksum-matching
canonical PNG and interactive HTML remain unavailable (see the #64 delivery
report); no substitutes were generated and visual fidelity is not asserted.

No backend, schema, ingestion, dependency, qualification, or deployment changes.
Local startup instructions remain in [the continuity report](../environment-continuity/README.md#local-startup).

## Verification

- Web typecheck, production build, and `git diff --check`: passed.
- Focused environment/commercial/autonomous-research regression run: 54 passed
  before the final two race tests were added.
- Full regression run: 122 passed, one existing skip, two failures. Real login
  returned HTTP 500 because PostgreSQL refused the connection at 127.0.0.1:5432.
  The new research-result test also expected text without its visible “Next step:”
  prefix; its assertion was corrected without changing production behavior.
- Independent static review: two research-disclosure restoration findings fixed;
  subsequent review found no additional blocking defects in this bounded slice.
- No backend/API changes; backend tests were not rerun for this follow-on.
- Desktop 1280px and mobile 390px fixture journeys, keyboard and reduced motion
  were exercised. Screenshots were visually inspected; they are not live data
  or comparison evidence against the missing canonical originals.

Next: verify the retained-data journey against the configured database and exact
reference assets, then bring secondary saved-history/related-project controls
under the same restoration model without consolidating the whole legacy shell.

Final affected run after the assertion correction:
`npm --prefix web test -- --project=regression tests/environment.spec.ts tests/commercial-pursuits.spec.ts tests/autonomous-research.spec.ts`
— **56 passed**, including both final race tests. Production code was unchanged
between the full run and this assertion correction.

[Desktop fixture screenshot](desktop-fixture.png) ·
[Mobile fixture screenshot](mobile-fixture.png)
