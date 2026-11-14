# Independent backend review — bcffe372

Reviewed exact commit `bcffe37291ad3ba355d1da70d13fa872c20106dc` in `/workspace/gl3-commercial`, including its four-file delta from `f8b4caa6f66f3a61e303f0820841db8a40c2d1c9` and the previously reviewed complete backend integration. Read-only product review; no product code changes, provider calls, deployment, outreach, or retained-data writes were performed. Test fixtures used random disposable PostgreSQL schemas.

**Disposition: correctness acceptance withheld.** The reported geographic-scope and Roman-phase findings are closed narrowly, but the scope repair introduces a verified retained-research regression. This is not whole-candidate or commercial-readiness acceptance.

## Findings

1. **Blocking regression: canonical project name followed by its retained address is rejected.** `scope_customer_facts` now passes only the project name to `_subject_predicate`. That correctly refuses city/county subjects, but also rejects `Orion Data Center at 811 Clayton Ln, Austin, TX has 400 MW of campus development capacity.` and the equivalent construction-timeline statement. Existing real retained-research-path tests now return `UNRESOLVED` instead of `ACCEPTED`. Preserve the canonical-name requirement while permitting the exact retained location only after that name; location must never be an alternate subject. Do not weaken or delete the positive integration assertions.
2. **Previous P1 geographic attribution is closed for tested cases.** `Dallas, TX`, `Midland, TX`, and `Loudoun County, Virginia` cannot authorize another named project's capacity. The bare exact project-name positive remains supported.
3. **Previous P2 Roman phase noise is closed for tested cases.** Extraction and explicit inclusion links normalize equivalent Roman/numeric phase tokens. The real material-state replacement from Phase I to Phase 1 emits no event. Invalid/unsupported phase notations are not certified by this review.

## Independent execution

From `backend/`, after sourcing the task-local environment without printing credentials:

```bash
PYTHONPATH=src .venv/bin/pytest tests/unit/test_customer_scope.py tests/integration/test_customer_material_changes.py tests/integration/test_customer_commercial_intelligence.py -q
```

Result: **2 failed, 49 passed in 78.07 seconds**. Both failures are `test_capacity_only_research_uses_existing_admission_guards`, parameterizations `capacity` and `timeline`, at the original positive acceptance assertion. The source modules were imported from the exact reviewed commit before any follow-on repair. Direct pure-code diagnostics independently reproduced geographic refusal, bare-name acceptance, and name-at-address rejection.

Earlier exact `f8b4caa6` changed-suite execution passed 159 tests in 113.42 seconds, but that result does not validate this subsequent scope edit. The coordinator's interrupted full runs are not passing receipts. Full backend, migration/recovery, frontend/browser, performance and exact-head CI acceptance remain outside this focused result.

## Commercial and evidence limits

- No real-customer published/scoped extraction coverage or verified named-contact acquisition improvement has been established. Synthetic integration positives do not close that release blocker.
- The evaluator's new `within`/`deadline` timeline qualifiers require semantic normalization against reference labels before final raw metrics; evaluator fixes and final rerun were not accepted by this backend review.
- Production non-government source authority remains conservatively unknown; evaluator fixtures labeling sources primary are a different assumption and must be disclosed.
- Commissioning positive tests establish bounded arithmetic/admission behavior on synthetic explicit engineering sections, not real engineering-source availability or customer rental demand.
- UI changes were not part of this backend commit review. Final whole-candidate acceptance requires the revised source, successful complete gates and separate UI review.

The corrected 20-record reference fixture previously checked at SHA-256 `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177` incorporates the seven prior label corrections; all 29 retained artifact hashes matched its manifest. That bounded label review is not runtime association, current contact verification or sales acceptance.
