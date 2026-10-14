# Quieter environment refinement

Baseline: main `343139041347be067f324df031c50852c9b61681` (PRs #64 and #65 merged). User approved reducing density within the locked GridLens environment.

Before, the mobile pursuit queue placed the first record below a screen of repeated statistics, research headings and queue metadata. The national overview also displayed a second full commercial preview below its featured opportunity.

Now:
- Queue statistics, evaluation and research updates sit behind a keyboard-accessible disclosure. Page scope remains explicit beside the filters.
- Closed pursuit rows emphasize identity, evidence tier, commercial disposition and the next question. Blockers remain visible; facts and rationale appear when expanded.
- Investigate this need appears before the long detailed record.
- The national commercial preview unfolds on demand. Errors and retry remain visible outside the disclosure.
- Native disclosures use the existing navigation snapshot model. A delayed preview response cannot truncate restored scroll.

No API, schema, authentication, evidence qualification, ingestion, draft persistence or legacy route behavior was changed.

## Verification

- Reproduced the crowded baseline in Chromium at 1280×900 and 390×900 before editing.
- `npm --prefix web run typecheck`: passed on final code.
- `npm --prefix web run build`: passed on final code.
- `npm --prefix web test -- --project=regression tests/environment.spec.ts tests/commercial-pursuits.spec.ts tests/autonomous-research.spec.ts`: 62 passed before the final preview-readiness fix. Includes selection beyond 200 records, filter exclusion, Back/Forward, scroll/focus, isolated drafts, delayed responses, source-health/retry, legacy routes and keyboard/reduced motion.
- Independent review found a delayed national preview restoration issue. Added a regression and reproduced expected scroll 1101 versus actual 444 before fixing the missing readiness marker.
- Final targeted run of national preview, desktop/mobile rendering, quiet queue disclosure, default preview, watch-only and malformed-preview checks: 7 passed, including the new delayed-response regression. Final screenshots use reduced motion for stable captures.
- `git diff --check`: passed. No backend changes; backend tests not rerun.
- Independent static review requested; its readiness finding was reproduced and addressed.

## Rendered evidence

All images are the actual local app with synthetic browser-test responses, not live retained data or visual acceptance. Full-page captures show the sticky command bar at the initial viewport position.

| View | Before | After |
| --- | --- | --- |
| Desktop queue | [Before](before-desktop.png) | [After](commercial-1280-fixture.png) |
| Mobile queue | [Before](before-mobile.png) | [After](commercial-390-fixture.png) |
| National desktop | — | [After](national-1280-fixture.png) |
| National mobile | — | [After](national-390-fixture.png) |

## Limits and next slice

The local PostgreSQL endpoint at 127.0.0.1:5432 is unavailable, so retained-data/authenticated production acceptance was not performed. The uploaded motion video was previously checksum-matched to the canonical manifest; the exact canonical PNG and interactive HTML remain unavailable. No exact visual-fidelity claim, regenerated substitute or deployment.

Expanded commercial records still expose substantial legacy detail. The next bounded slice should organize that evidence and commercial action around the same selected need in the canonical environment, preserving attribution, qualification and draft continuity.
