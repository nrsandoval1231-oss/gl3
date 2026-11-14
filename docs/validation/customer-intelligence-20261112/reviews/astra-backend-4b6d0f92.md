# Independent backend safety review — 4b6d0f92

Reviewed exact commit `4b6d0f92ad3d2475c9a783fe7b6bdd649ca0c74a` in `/workspace/gl3-commercial`. This review covers the complete customer-commercial backend previously inspected at `f8b4caa6`, the phase/geographic-scope correction at `bcffe372`, and the final two-file anchored-address correction. Product code was not edited by this reviewer. No deployment, outreach, provider execution or retained-data writes occurred; database tests used random disposable schemas.

**Disposition: the reviewed backend safety/correctness findings are closed at this exact source revision. No remaining material backend safety defect was identified in the inspected scope. Whole-candidate release and commercial-completeness acceptance remain withheld pending full gates and the unresolved real-source coverage requirements.** This focused disposition is not approval to merge or deploy.

## Independent validation

After sourcing `/workspace/task-runtime/env.sh` without printing credentials, from `backend/`:

```bash
PYTHONPATH=src .venv/bin/pytest tests/unit/test_customer_scope.py tests/integration/test_customer_material_changes.py tests/integration/test_customer_commercial_intelligence.py -q
```

Result: **52 passed in 57.41 seconds**. This reruns both original retained-research capacity/timeline positive tests that failed at `bcffe372`; their acceptance assertions remain intact. It also covers source/hash/project refusals, immutable receipts, narrow engineering-source admission, bounded extraction, material source causality, replay, and the repaired phase/timeline semantics.

Seven additional independent pure-code diagnostics passed: city-only and address-only subjects refused; wrong project at the same address refused; wrong address following the canonical name refused; spelled-unit quantity alternatives refused; bare canonical project and exact canonical-name-at-retained-address positives accepted.

The coordinator's retained `/workspace/task-runtime/complete-changed-safety2.log` was inspected and records **178 passed in 46.59 seconds, exit zero**. This is a coordinator-run receipt, distinct from the independent 52-case execution. Earlier independent `f8b4caa6` execution passed 159 changed-suite cases; it supports previously reviewed unchanged code but is not described as a fresh whole-suite run at this head.

## Findings closed

- **Geographic scope:** The canonical project name must be the grammatical subject. Raw city/county/address locations are not interchangeable project subjects. The exact retained location may qualify the canonical name using the anchored `name at location` form. The preceding `bcffe372` regression rejecting that legitimate form is closed without weakening the real retained-research positives.
- **Equivalent phase notation:** Roman and decimal phase identifiers normalize consistently in extracted scope and inclusion links. A real admitted-source Phase I to Phase 1 replacement does not emit a capacity change.
- **Quantity safety:** Earlier mixed-direction upper/lower bounds abstain rather than publish a false complete upper bound. Quantity alternatives/ranges using spelled units are refused. Distinct electrical bases remain separate; phase-only amounts cannot become complete campus totals; unknown overlap withholds aggregates.
- **Timeline semantics:** Deadline wording is retained separately from within-period wording and participates in conflict/material-state comparison. Deadline-to-within revisions emit the expected schedule event and replay remains quiet. Internal interval bounds do not establish exact displayed event dates.

The inspected integration preserves existing canonical identities and need-scoped Pursuits, immutable source bindings, package-as-receipt rather than package-as-authority semantics, generation-bound facts and pre-pagination ordering, existing current-generation/source/identity fences, and central contact/history privacy publication. No product-route source-fence bypass was proven. This review does not claim that every current-source withdrawal was independently exercised through every HTTP route.

## Outstanding acceptance boundaries

- Full backend/CI, migration and saved-generation recovery, authentication, realistic performance, and final frontend/browser gates were not independently completed here. Their final exact-head results must govern whole-candidate acceptance. Interrupted earlier runs are not passing receipts.
- UI work is outside this backend revision review and requires its separate frozen-source visual/interaction review.
- **Real commercial coverage remains a release/completeness blocker.** No useful published/scoped extraction coverage on the 20-organization real-source cohort or verified named-contact acquisition improvement has been established. Synthetic positives and safe abstention cannot establish the owner's completed commercial mission.
- Final evaluator metrics need their own source-manifest-bound rerun and review. The evaluator's reference authority assumptions differ from production's conservatively unknown non-government authority. Equivalent timeline qualifier spellings must be normalized without crediting deadline/within mismatches.
- Commissioning tests establish bounded deterministic scenarios on explicit synthetic engineering sections. They do not establish ordinary engineering-document extraction, real-source positive coverage, procurement intent, or a customer rental requirement.
- Geographic priority contributes only when explicitly supplied; absent configuration remains unknown. Contact/material-event priority context does not replace independently reviewed ranking usefulness.

The independently checked corrected reference fixture at SHA-256 `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177` contains 20 records and incorporates the seven earlier label corrections; all 29 source artifact hashes matched. This is bounded reference-label evidence, not runtime identity accuracy, current employment verification or salesperson acceptance.

The failed `bcffe372` report and its **2 failed / 49 passed** receipt remain historical failure evidence; this report supersedes its code-finding disposition only for the exact corrected source above.
