# Controller candidate evidence

This UI uses the supplied [owner reference](../../design/references/opportunity-intelligence-approved.jpg) and [brand sheet](../../design/references/brand-system-v1-owner.jpg). It is stacked on PR102, dependency `5ef5f3f29e94fffb071351b61e186d236d40068c`. No backend, schema, provider, budget, ingestion or qualification implementation changes belong to this diff.

## Browser captures

The primary comparison uses ACS Data Center Phase I Substation, an actual API record restored from a historical real-source backup. It does not assert current project freshness. Separate synthetic captures exercise four explicitly synthetic contacts; those contacts are never presented as production records.

[Side-by-side desktop comparison](desktop-side-by-side.png) · [50% reference overlay](desktop-overlay.png) · [Measured discrepancies](VISUAL_DISCREPANCIES.md)

| Viewport | Historical real-source record | Synthetic populated contacts |
|---|---|---|
| 1648 × 928 | [Desktop](retained/desktop-1648x928.png) | [Desktop](synthetic/desktop-1648x928.png) |
| 1440 × 900 | [Desktop](retained/desktop-1440x900.png) | [Desktop](synthetic/desktop-1440x900.png) |
| 1280 × 800 | [Compact desktop](retained/desktop-1280x800.png) | [Compact desktop](synthetic/desktop-1280x800.png) |
| 768 × 1024 | [Tablet](retained/desktop-768x1024.png) | [Tablet](synthetic/desktop-768x1024.png) |
| 390 × 844 | [Mobile](retained/desktop-390x844.png) | [Mobile](synthetic/desktop-390x844.png) |

[Full mobile record](retained/desktop-390x844-full.png) · [Full mobile populated contacts](synthetic/desktop-390x844-full.png) · [Real geometry/request ledger](retained/browser-measurements.json) · [Synthetic geometry/request ledger](synthetic/browser-measurements.json)

## Validation

- Final controller frontend run: **167 passed, one gated skip**, 109.82 seconds. [Raw results](controller-browser.log), [all controller gates](controller-gates.json).
- The gated persisted case ran separately on a fresh isolated synthetic record: **one passed**. It proves authenticated fact acceptance, real status readback, lost-response retry with the same request and no duplicate event, and unchanged qualification. [Receipt](persisted-browser.json), [raw result](persisted-browser.log).
- Unchanged intelligence projection: **19 targeted backend tests passed**, including authenticated bounded reads, constant batch query scaling, verified-contact provenance and no facility-load-to-gap conversion. [Raw result](backend-projection-tests-utf8.log).
- Typecheck, production build, dependency audit, documentation links and diff checks passed. No separate frontend lint command is configured.
- Native keyboard checks passed at desktop, tablet and phone: Enter selection, Research Gaps pressed state, Back/focus restoration and account disclosure/bounds. [Receipt](keyboard-checks.json). This is not an assistive-technology user study.
- Both five-viewport capture sets have zero JavaScript errors and no horizontal document overflow. A focused tablet regression additionally checks direct-link identity position, header control bounds and Back/reselect, since width alone missed a clipped account control.

The [frontend manifest](frontend-manifest.json) binds the tested on-disk source and tests. Independent Sol review follows the frozen commit after these tracked explanatory artifacts are prepared. Its exact commit, raw verdict and findings are delivered with the PR and retained locally in `.agent/artifacts/APPROVED-UI/REVIEW.json` and `REVIEW.md`. Passing local gates alone do not establish independent acceptance.

## Performance and rendering boundary

Ten sequential desktop selections per local development runtime measured click through the selected detail response and two animation frames with the card visible. This is an observed selection/paint measurement, not a React CPU profile or production latency claim.

| Runtime | Median | p95 / maximum | Per selection |
|---|---:|---:|---|
| 12 synthetic persisted needs | 196.4 ms | 253.6 ms | Three GETs: detail, title status, brief status |
| 1,619 active historical records | 2,728.1 ms | 2,781.7 ms | Three GETs: detail, title status, brief status |

[Synthetic samples](synthetic/selection-performance.json) · [Historical samples](retained/selection-performance.json). Selected-response headers through observed paint ranged 42-105 ms for fixtures and 59-91 ms for the historical snapshot. Most elapsed selection time preceded that response. Host load was uncontrolled; earlier historical observations were faster, so these measurements establish no production SLO or causal performance comparison. No rendering mutations occurred. [Before](render-ledger-final-before.json) and [after](render-ledger-final-after.json) counts are identical: synthetic jobs/logical calls remain 0/0; historical counts remain 872/10, with no new jobs or logical calls. The backup hash is unchanged. No worker or inference provider ran.

## Open acceptance dependencies

**Exact brand acceptance is blocked.** Licensed ABC Diatype Light, Regular, Medium and Bold binaries are absent. The supplied images establish visual authority but contain no installable fonts. Browser headings resolve to Arial; existing SVG wordmarks are documented approximations. Proper fonts and the official wordmark master require integration and visual revalidation before claiming exact brand parity or a finished release candidate.

These records have no supported facility-wide demand or reliable utility energization date. Missing values stay unestablished; supported service status never becomes an invented date. Customer identity remains separate from source contractors. Only verified contact methods become links. Qualification and completeness remain distinct.

Earlier failed runs remain in local evidence: first 126 passed/39 failed/one skip; later 165 passed/one failed/one skip before the relocated warning assertion was corrected. Persisted-case failures exposed stale selectors and a mock cohort token; a partially written fixture was inspected and preserved before a fresh record was used. Backend tests first failed on non-UTF8 fixture encoding, then passed unchanged in a new UTF8 database. An obsolete ingestion fixture runner made source reads across a Windows process boundary; it was stopped and its separate mixed database excluded. Current UI proof uses direct fixtures and the separate historical backup (1,620 needs/18,016 evidence; 1,619 active entries).

No production data was mutated. The parent Finish Contract and PR102's retained/live-provider gates remain open. This evidence authorizes neither merge nor deployment.

The first independent review of05789b3 returned FIX for combining a retained record with its projection citation in one record count. The corrected caption separates retained records from intelligence-card citations and states that citations may refer to the listed records; filter options no longer sum them. The focused regression exercises both views of the same document, filtering and drill-down. The prior raw report is retained under .agent/artifacts/APPROVED-UI/review-05789b3. The new frozen commit requires its own independent verdict.

The following bounded technical PASS on9c03a52 recorded a minor singular/plural caption error. A final copy correction uses stable count-label syntax, Retained records:1 and Intelligence citations:1, with the overlap explanation preserved. The focused assertion, all controller gates, persisted case, capture matrix and browser probes were repeated before the next exact-commit review. The prior report is preserved under .agent/artifacts/APPROVED-UI/review-9c03a52.
