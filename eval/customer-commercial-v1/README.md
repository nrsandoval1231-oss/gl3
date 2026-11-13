# Customer commercial intelligence evaluation v1

For the subsequent native ingestion/API evaluation, see the [runtime receipt index](runtime/README.md). The original offline baseline below remains historical and uses a different evaluation path.

This is a reproducible, offline evaluation against retained public-source excerpts for **20 real organizations**: 17 data-center developers/operators and three generation-infrastructure owners. It is a purposive stress cohort, not a representative production sample. Source observations are dated November 12, 2026; historical announcements are not current operational verification.

## Reproduce

From the repository root, using the task's disposable environment:

```bash
source /workspace/task-runtime/env.sh
uv run --project backend pytest backend/tests/unit/test_customer_commercial_evaluation.py -q
uv run --project backend python scripts/evaluate_customer_commercial.py \
  --fixture eval/customer-commercial-v1 \
  --as-of 2026-11-12 \
  --output /tmp/customer-commercial-results.json
```

The runner requires no database, external research, credentials, model execution, production mutation or paid provider. It verifies the retained source artifact hashes before running and refuses to overwrite reference/source files. It fails if measured production modules change during the run. `source-hashes.json` hashes retained excerpt artifacts, not original HTML bytes or live websites. Some fetched pages came from the retrieval service's cache; available cache timestamps are preserved.

## Inputs and independence

`reference-customers.json` contains independently researched labels, capacity types/conditions and scope/inclusion, timeline semantics/precision, source-supported functional leaders and missingness. The r1 label revision was independently checked at SHA-256 `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177`. Current r2 gold is independently verified at `dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922`, with the sole CyrusOne deadline correction and all 29 retained source hashes checked; see `reference-review.md` for the historical findings and bounded r2 attestation. This bounded source-label review does not accept runtime identity, live contacts, extraction coverage or sales usefulness. The immutable label file retains its original pending-review metadata; the separate review evidence governs this later disposition. `evaluation_scope` is a gold comparison annotation, never input to extraction.

For each supplied organization/project assignment the runner passes **only retained excerpt text, supplied project name/location and document provenance** to the actual production extractor `domain.customer_intelligence.extract_customer_facts`. Document publication dates are independently labeled source metadata; ambiguous publication dates stay null. Expected capacity, timeline, commissioning and contact values do not enter prediction. The actual runtime `intelligence.customer_intelligence.scope_customer_facts` guard then scopes those candidates, and `resolve_customer_intelligence` produces the scoped summary. Results retain both raw candidates and publication-scoped outputs.

These are **targeted extraction results under supplied identity context**. The runner does not invoke canonical company/project matching, database identity resolution, discovery, contact acquisition or the customer browse endpoint. A fixture record key is not a canonical account ID. Label uniqueness is never reported as duplicate-customer accuracy. Identity accuracy, project association, duplicate rate, end-to-end contact verification, capacity double-counting, commercial ranking quality and salesperson usefulness remain explicitly **not evaluated**.

The evaluation supplies `authority=primary` for these independently identified official company sources. Runtime currently maps `.gov` hosts to regulatory and other hosts to unknown. This mismatch is reported in the result; these measurements do not establish live confidence, source-priority or ranking parity.

## Metric rules

- Capacity matching is one-to-one and requires the same MW value, electrical basis, scope and numeric/material qualifier. Site, phase, building, component and regional scopes cannot substitute for each other. Roman and decimal phase labels can normalize to the same phase. No numeric tolerance hides wrong capacity. A substation rating, conditional lease/option, studied power potential or merely deliverable capability cannot score as ordinary exact delivered utility service.
- Two reference claims have nonphysical/unclassified bases (QTS's approximately 4.5 MW leased amount with unspecified basis, and Fervo's approximately 900 MW contracted offtake). They are retained but excluded from the physical-capacity extraction denominator. There are **32 physical-capacity reference assertions** and **30 timeline reference assertions** in this label revision.
- Repeated semantic assertions from the same source count once; supporting quotations remain retained. Different source URLs, scopes, numeric bounds, states or dates remain distinct. The matching algorithm prevents multiple predictions from earning recall for a single reference assertion.
- Timeline matching requires event kind, value, precision, scope and deadline qualifier. Reference unspecified/exact date-label semantics normalize to production `within`; reference `at_or_before` normalizes to production `deadline`. Deadlines never normalize to within-window events. Ready for service, opening, delivery, commissioning, operational targets and first electrical energization are separate events. Approximate phrases remain approximate; quarter/year labels cannot become invented exact days. Publication or announcement dates do not become actual milestone dates.
- Empty predictions have **undefined precision (`null`)**, not 100% precision. Supported reference assertions without matching predictions are parser/scope missingness. Missing source information is a different denominator and is not a false negative.
- Provenance completeness checks source URL, evidence identifier, content hash, observation date, publication-date key (null allowed), authority, extraction version, subject binding, claim status and supporting quotation. It does not independently verify source truth or source-to-project identity.

## Source coverage and limitations

Fourteen organizations have physical-capacity assertions in these bounded sources. Aligned Conesville, Google Fort Wayne, AWS Madison County, Microsoft Fairwater and Equinix JH2 do not state MW in their retained excerpts. Digital Realty Lagos is a separate **retrieval-partial** case: the body extraction returned a shell and truncated metadata. Its title supports a new Lagos data center, but not a third facility, opening or precise event date. Do not label that source as definitively lacking MW.

Six source sets name potentially relevant functional leaders at publication. None independently verifies current employment/buyer authority or current professional contact methods. Media contacts and fictional addresses never increase commercial-contact coverage.

All 20 bounded source sets lack a documented test-load/concurrency envelope. Correct commissioning behavior is **Insufficient data**. A 20/20 abstention result does not validate positive engineering scenarios or establish rental demand.

Important stress cases include DataBank campus/phase/substation distinctions; Applied Digital leased/optional/studied capacity; Switch's multi-site ecosystem; TerraPower base versus storage-boosted output; Microsoft's offsite solar versus data-center load; Meta's compatible 5 GW and over-2 GW wording with no proven revision chronology; and Dominion's unresolved 2026/2027 completion targets. EdgeCore's 206 MW construct/commission quotation is source-reported alongside buildings still under construction, not independent present-operating verification.

## Retained results

`results/scoped-candidate-1de298af-reference-r2.json` contains an actual production-extractor/runtime-scope run at capture commit `2aea1aa08a11e1d20ad6dbacbd141c4ef0e0e345`, with all four measured backend module hashes byte-identical to backend repair commit `1de298af047f09a32e9a0349f41410a55bc1791e`, exact source/runner/reference hashes, per-organization predictions and unmatched claim indices. Its source manifest is the authority for the measured code revision; a later source edit requires a new run.

At the current r2 retained run: raw capacity precision **41.2%**, recall **21.875%**; raw timeline precision **14.3%**, recall **3.33%**. The publication scope guard withheld all candidates, producing **0% supported capacity/timeline recall**, undefined scoped precision and undefined scoped provenance coverage. Commissioning abstention was 20/20. This is a **commercial publication-coverage blocker**, not acceptance success.

`results/candidate-unscoped-b61b9778-historical.json` preserves an earlier diagnostic using older code, labels and matching rules. It was not runtime-scoped, did not enforce the final qualifier policy, and is not a comparable accepted baseline or evidence of improvement. Its hashes and limitations remain distinct from the final run.

`results/scoped-candidate-20261112.json` and `results/scoped-f8b4caa6-historical.json` retain the prior f8b4caa6 source-specific run. They and `results/scoped-candidate-bcffe372.json` are superseded by the `4b6d0f92` artifact; prior result bytes remain unchanged.

`results/scoped-diagnostic-before-date-normalization.json` preserves another intermediate source-specific diagnostic before quarter/half-year synonym normalization. It is historical and superseded by the final source-bound run. Metric controls passed **10 tests**, and the owned runner/tests passed Ruff lint and formatting checks; no full-repository or CI pass is claimed by this lane.

## Independent manual sales-usefulness rubric — not administered

Give independent reviewers the rendered customer card and its progressive detail, without gold labels. For each organization, record the evidence and score each item 0 (cannot determine), 1 (partially determine with material uncertainty) or 2 (supported and actionable):

| Item | What the reviewer must establish |
| --- | --- |
| Who | Correct owner/end customer and a currently verified relevant person or a useful explicit contact-research state |
| Why now | Source-backed material development with date and relevant construction/commissioning context |
| When | Supported construction/energization window with honest date precision and revisions |
| Power | Supported typed build capacity without included-phase double-counting; commissioning scenario or justified abstention |
| Next step | One commercially relevant action justified by the evidence and contact state |
| Five-second scan | Essential customer opportunity understandable from the initial card without raw records |

Require a separate free-text error log for wrong identity, misleading capacity, fabricated precision, unsupported rental demand and unsafe contact attribution. An unresolved material error blocks that customer's acceptance regardless of score. Keep reviewer identity/role, date, source/software hashes, time to decision and reasons. Use two independent reviewers and adjudicate disagreements; report item-level scores and coverage, never an unadministered aggregate. No reviewer or salesperson acceptance has been performed by this fixture's existence.


## Reference/scorer revision r2 — November 13, 2026

The CyrusOne retained source expressly says the facility is expected to be operational **by the fourth quarter of 2026**. Independent Astra review endorsed adding `qualifier: at_or_before` to that single reference timeline claim. Current gold is SHA-256 `dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922`, retained both as `reference-customers.json` and `reference-customers-r2.json`. The prior SHA-256 `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177` remains byte-exact in `reference-customers-243dce0a.json`. Source observations, publication dates and all 29 source artifacts are unchanged.

Scorer v1.1 removes an incorrect ordinary `operational_target` to `full_operational_target` conversion. Ordinary operation, full operation, readiness for service and electrical energization remain distinct. The new positive control recognizes the ordinary operational deadline; negative controls reject full-operation substitution, deadline/within substitution and readiness-for-service as energization. The corrected raw timeline result is one true positive (CyrusOne), six false positives and 29 missed reference assertions. Existing wrong project/phase scopes still fail. This is a reference/scorer correction, not a backend extraction gain.

The older `results/scoped-candidate-4b6d0f92.json` remains byte-exact at SHA-256 `6877cd380ef81d2ed8c7b20fc866a277757836e62a29e6b4ef6af7bb7b836fb1`, with its original gold/scorer hashes and superseded raw timeline result. Do not use its zero raw timeline score as the current result. All published/scoped results remain genuinely zero after the r2 correction.


Independent r2 attestation verified current/r2 label bytes, the exact one-field semantic diff, the preserved r1 bytes and all 29 source artifacts. The reviewer independently ran all 10 evaluator controls successfully (0.61 seconds). This approves only the bounded reference/scorer correction; it does not accept rerun metrics, runtime identity or commercial readiness. The earlier `scoped-candidate-4b6d0f92-reference-r2.json` remains byte-exact at SHA-256 `2b24a97242112b9455a5428cae2e142f7111f35bd0ee08bda13ad55c3bac97b8`; its actual capture HEAD was `953b63d4`. The current nonoverwriting repair capture is described in Retained results above.


## Backend phase-safety repair capture — November 13, 2026

`results/scoped-candidate-1de298af-reference-r2.json` reruns the unchanged independently reviewed r2 gold and unchanged scorer v1.1 against the phase-safety repair. All four measured modules match repair commit `1de298af047f09a32e9a0349f41410a55bc1791e` byte-for-byte. The actual capture HEAD is `2aea1aa08a11e1d20ad6dbacbd141c4ef0e0e345`; both identities and exact module hashes are retained in the result/validation receipt.

Raw capacity now has seven true positives, ten false positives and 25 missed reference assertions from 17 candidates. This differs from the earlier 19-candidate capture because the backend conservatively withholds ambiguous phase amounts; no gold or scoring rule changed. Raw timeline remains one true positive, six false positives and 29 missed assertions. The real publication guard still yields zero capacity/timeline claims. Ten evaluator controls passed in 1.29 seconds. This does not close commercial completeness or establish identity, contact or sales-user acceptance. All previous result bytes and source artifacts remain retained.

## Publication-scope diagnostic

The [bounded scope-gap diagnostic](scope-gap-diagnostic.md) replays the final candidates: all 24 raw assertions fail the first exact named-subject gate. It separates supplied fixture project labels from untested runtime identities, demonstrates both withheld legitimate clauses and a necessary cross-site refusal, and keeps authority confidence separate from the rejection cause. It does not claim production overall has zero facts or authorize weaker matching.
