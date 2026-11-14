# Astra final integration review — November 13, 2026

**Disposition: accept the bounded implementation repairs described below; withhold commercial, performance, and release acceptance.** The original application freeze reviewed below is `605d6bcc007fab9dcf827ad88763af1259d8b9eb`. The later CI finding and separately accepted `380b0dec` source repair are recorded in the addendum; the earlier measurements are not relabeled as results for that repair. The retained evidence still does not meet the owner's customer-intelligence mission. Passing parser controls and publishing two ordinary account groups do not establish useful customer coverage, verified contacts, a useful default workspace, or production readiness.

This is an independent review receipt. The reviewer read the integrated source and retained outputs, performed the pure controls recorded during the bounded reviews, and verified the final commit/hash bindings. For this final note, the reviewer did not rerun the database suites, browser suite, native ingestion, or benchmarks. No production/retained database write, paid call, source activation, merge, or deployment was performed or approved. Only this review document was edited.

## Frozen integration and review boundaries

The following commits were verified as ancestors of the final freeze, in order:

| Commit | Included work | Disposition |
| --- | --- | --- |
| `8c299dbb6cbe7ff87cb333c903aed8505609357f` | Bounded named-role contact discovery hints | Accepted discovery-depth repair; a hint does not become a verified contact or accepted commercial yield. |
| `2281faf6e62bedaf2c3bf22119ca22c9bd64c740` | Customer presentation and supported fact labels | Accepted bounded synthetic visual/source review; no real salesperson acceptance. |
| `73e01a73fcfc9e883cb5e0e38def729f165a360f` | Retained contact and company-identity research | Inclusion verified. This final review does not independently re-attest every research assertion or turn retained research into runtime verified contacts. |
| `7f11ef12f5136c07d8cd4e99839a53cdd59d3f92` | Native evidence, subject scoping, roles, identities, priority and projection | Accepted the independently reviewed guards and controls, with the commercial limitations below. This is not an assertion that every new source form is supported. |
| `e653c78f11b48dad2926d37c72a5d35f5b1512fc` | Preloaded Project and lazy batched owner context | Accepted after correcting cross-project owner leakage and owner-antecedent omissions. Performance outcome remains a separate gate. |
| `fd2727d10aeace89d1124c7b6764716e3c9d985e` | CyrusOne literal operational-target wording | Accepted finite wording extension, retaining quarter/deadline semantics and unknown energization. |
| `605d6bcc007fab9dcf827ad88763af1259d8b9eb` | Publication-date boundary and metadata reconstruction | Accepted after rejecting event headings/prose datelines and repairing all affected metadata reconstruction paths. |

`git diff --name-status --diff-filter=MDR dc6dac3b..605d6bcc -- backend/tests web/tests` returned no changes: existing tests in the pre-series merge remain unchanged; the series adds tests. This does not imply all final repository gates have been independently run by this reviewer.

Eleven bounded source hashes below were recomputed from the working tree and compared byte-for-byte with `git show 605d6bcc:<path>`; all matched. Earlier review hashes remain historical when a later accepted change superseded them.

| Path under `backend/src/gridlens/` | SHA-256 at freeze |
| --- | --- |
| `intelligence/company_contact_discovery.py` | `0d6f04d4dd4af26fdd038f5133075394ef2d32bf6c46d5aeaef0e1fd94f38931` |
| `domain/customer_intelligence.py` | `09224de020ae458ce38346dc52631ab721a0d56094288b6dde3f363605060352` |
| `domain/customer_subjects.py` | `9fc42cf930955a92cab1b73ed403918c5905d506f4437f1a5830467f09e6635d` |
| `intelligence/customer_intelligence.py` | `eb1d3340794798e4e0de18068cf4cc25143305516e85f2dbd21ad69c96f20faa` |
| `intelligence/change_detection.py` | `94273acccf7b9d873604fffdc5d7c1f38ae43d89bee7119a3da2557d5a1169af` |
| `ingestion/adapters/retained_company_projects.py` | `5b8341c8a51d57f651c45fe126df932ad52da0017e79148dece96dcd352a397a` |
| `intelligence/buying_chain.py` | `d82ccc674df806c3f9eb28c5b308816e5e5db96695088be33f8fce3f5b5b9abd` |
| `intelligence/identity_reconciliation.py` | `b247bd51cea8a58fd9c98c2d130c51bbb2ca5052d0250a31d5a99ea94e9bff3e` |
| `intelligence/retained_project_organizations.py` | `5f738b8a7790b0b49467baf2f7830e18033ae92442afae9c82b922c8a3170b0c` |
| `intelligence/regulatory_project_organizations.py` | `edbbd724a3fed0774304588878eb20c5006e9bd008056831938e28ef91d46f3e` |
| `intelligence/research_evidence.py` | `fdbb0309ee9f9b35b776e6391e8c181d18c57d4b9c041e6ae062168b0d3d53a0` |

All seven source/test hashes and six screenshot hashes in the [frozen UI manifest](final-ui/frozen-20261113/manifest.json) were also rechecked with zero mismatches. The prior desktop/mobile/detail visual acceptance remains synthetic. The coordinator's 339-case browser receipt is retained in that manifest; the reviewer did not rerun it. The sticky-header position in the full-page detail capture limits that image, and before/after fixtures are not a matched-input usability experiment.

## Integrated evidence and identity behavior

The reviewed path remains the existing native ingestion and canonical projection path: retained source text and artifact provenance enter source admission, Observation/Evidence/Interpretation and Project/PowerNeed; existing buying-chain extraction and identity links produce source-reported organization roles; typed customer facts are revalidated into the saved browse generation; customer groups/detail consume that generation. Offline evaluation labels are comparison inputs, not runtime project/company seeds. The retained adapter is an inactive evaluation source, not a newly activated production pipeline.

Subject guards require the selected native site and its own predicate. Reviewed controls reject neighboring capacity/date contamination, acres/staff/transformer quantities licensing a later foreign MW amount, sibling alias prefixes, and foreign legal forms. Exact full source text reaches the production research scoper. DataBank phase/site bounds remain distinct; this does not establish portfolio-wide aggregation accuracy. Capacity is not required demand or rental MW.

The organization helpers emit supported roles through existing `Extracted`/buying-chain/identity machinery. A possessive association alone does not establish developer or legal-owner status. CyrusOne is the source-reported project customer, not the owner of Calpine's plant. Bare-brand publication context is bounded to independently proved issuer/domain and explicit legal publisher evidence; it is not a global name/parent/subsidiary merge. SEC identity work retains source-authority, issuer/EIN/domain, conflicting-proof and suppression restrictions. The actual native accounts in the final receipt are still project-scoped identities, not demonstrated global company matches.

The continuity repair uses the immediately prior run only. Receipts are lineage metadata with `current_support=False`; every receipt continuation requires independently current accepted replacement evidence, exact project/raw organization/role/URL binding, one unambiguous company identity, and correction/suppression checks. Person and strong/reviewed identity links are outside this fallback. Same-observation history is capped at 64 versions and fails closed on malformed/adverse history or overflow; this prevents a replayed older withdrawal from disappearing behind immutable evidence timestamps. Publication metadata is reconstructed consistently in admission, organization extraction and history validation. The [controlled comparison](identity-continuity/README.md) documents the corrected initial-transaction fixture and the original carry failure. Its 640/720 MW revisions and withdrawal titles are synthetic controls, not real DataBank developments.

The Project preload is restricted to the matching singleton; batch owner context is cached once and selected by each row's project ID. Independent pure SQL compilation showed no singleton Project-table read while preserving accepted status, project/source identity, semantic/evidence hashes and supplemental target-need restrictions. Owner lookup remains available for lowercase owner names and supported adjacent phase anaphora. No per-card query improvement is inferred from this ingestion change.

Operational/RFS proxies remain labeled separately from energization and commissioning. The CyrusOne deadline retains its July 30, 2025 publication date and “by fourth quarter of 2026” qualifier; this is a dated forecast, not verified present construction or energization. Unknown publication dates are not filled from construction, opening, update or observation dates. Commissioning remains insufficient without a documented project-specific test envelope. Priority does not convert upper-bound scale to demand, double-count scale points, or reward future actual construction starts.

The reviewer independently ran the bounded pure controls during implementation: source/legal-form/adverse scoping controls, priority controls, receipt/history controls, eight preload/cache/scope controls, eager/lazy payload parity, eight Cyrus wording/scope controls, and the final date/reparse controls. Database matrices and the actual native replay are separately retained builder/coordinator evidence; they were not rerun by this reviewer. No remaining P1/P2 was found within the accepted bounded repairs. That disposition does not waive the following integration/release blockers.

## Commercial acceptance remains unmet

Use the explicit [final publication native receipt](../../../eval/customer-commercial-v1/runtime/native-runtime-replay-publication-final-20261113.json) and [final source-text replay](../../../eval/customer-commercial-v1/runtime/source-text-scope-replay-publication-final-20261113.json). `runtime/latest.json` and several earlier README/diagnostic summaries are older captures and must not override these results.

| Measure | Final retained outcome | Acceptance implication |
| --- | --- | --- |
| Native admission | 2 of 22 document groups; 20 held, covering only 2 of 20 organizations | Sparse real-source coverage; held public facts are parser/association missingness, not proof that information is unavailable. |
| Native account path | DataBank and CyrusOne; 2 saved rows, 2 project-scoped company links, 2 WATCH account cards | Demonstrates bounded source-to-account plumbing, not global identity accuracy or useful sales coverage. |
| Primary customer workspace | Ordinary groups: 2; current default Shortlist: 0 | Material product blocker: the default view hides both admitted accounts. |
| Required demand / contacts | Both needs retain `required_mw: null`; cards report `unavailable_unverified` contacts | No fictional demand; no verified-contact or actual buyer-reachability acceptance. |
| Oracle-context capacity replay | 2 TP, 0 FP, 30 FN: 6.25% recall across 32 physical assertions | Observed precision is 100% on only two emitted claims; this is not broad accuracy or coverage acceptance. |
| Oracle-context timeline replay | 0 TP, 0 FP, 30 FN: 0% recall; precision undefined | Timeline coverage remains poor in that supplied identity context. |

The replay totals above were independently recomputed from the final JSON rows. Reference identity/location and publication context are disclosed oracle inputs in the source-text replay. Native ingestion does not receive reference labels. In particular, the repaired CyrusOne operational target reaches the native persisted/API path while the oracle-context replay still emits no matched timeline: the project naming/binding contexts differ. These are separate measurements, not interchangeable success counts.

The [default-policy blocker](customer-default-release-blocker.md) identifies an existing test contract requiring Shortlist. No exception to change that contract had been received in the reviewed freeze; neither the default nor the existing test was changed. Manufacturing eligible demand to expose accounts would be incorrect. This policy conflict must be resolved explicitly before claiming the intended customer-first workspace works.

Cross-project company deduplication, global identity accuracy, portfolio capacity double-counting, ranking usefulness, current decision-maker/contact acquisition, and independent salesperson/five-second comprehension have not been established by these receipts. Retained research and synthetic UI screenshots do not fill those measurement gaps. The source-backed coverage shortfall remains a material blocker even if all repository tests pass.

## Performance and runtime acceptance remain withheld

The [matched recheck](final-performance/recheck-20261113/README.md) compares baseline `5ee2f30c` with optimized `e653c78f`, not the final `605d6bcc` application freeze. The later Cyrus/date edits therefore do not have an exact-final-source performance rerun in this receipt. The reviewer read the raw results and independently recomputed all six retained p50/p95 sample sets; no benchmark was rerun.

| Page size | Baseline p50 / p95 ms | Candidate p50 / p95 ms | Compact bytes, baseline / candidate |
| ---: | ---: | ---: | ---: |
| 1 | 2,617 / 7,357 | 2,725 / 7,854 | 5,475 / 7,180 |
| 25 | 2,554 / 3,008 | 2,863 / 4,282 | 15,760 / 57,128 |
| 50 | 2,573 / 3,036 | 2,870 / 3,740 | 26,360 / 109,378 |

The sampled steady SQL count is 53 and flat between pages 25 and 50. This does not erase the measured page-25 median/p95 increases of 12.1%/42.4%, or payload growth of 3.62x at page 25 and 4.15x at page 50. Ten-sample nearest-rank p95 is the maximum and unstable. These are direct local service measurements on 40,000 synthetic presentation projects but only 48 persisted needs/evidence rows; HTTP, authentication, transport and browser rendering are excluded. No general no-N+1, mobile-latency, SLA or no-regression acceptance follows.

The successful ingestion recheck restores Project scan counts to baseline. Remaining SQL overhead is two statements per new/changed record: 27,067→27,667 for 300 new records, 4,887→4,917 for 15 changed records, and no delta for unchanged replay (3,927 each). Instrumented candidate timing cannot establish a causal speedup against the uninstrumented baseline.

One fresh uninstrumented candidate attempt failed while autoflushing a `NeedObservation` insert: the nested browse invalidation trigger update was canceled by the unchanged 2.5-second per-statement timeout. A later instrumented fresh run succeeded and observed no blocker PIDs, but the original cause is unresolved. Success on that retry is not evidence that the first failure was harmless or a flake. The timeout, remaining statement cost, and measured read/payload regression remain explicit release concerns.

## Final boundary

The accepted source changes are concrete, source-bound correctness and presentation improvements. The final source is reviewable and the named hashes are verified. Commercial acceptance, exact-final-source performance acceptance, sustained ingestion reliability, complete final CI disposition, and production readiness are separate outcomes and are not granted by this note. No merge, deployment, paid research, retained-data mutation or source activation is authorized here.

## Post-freeze CI finding and operational-target repair

The coordinator's full backend run against `605d6bcc` reported **1 failed, 5,760 passed, 1 skipped**. The unchanged regression `test_deadline_to_within_year_is_a_schedule_change_and_replay_is_quiet` expected a `build_timing` change from “is expected to be operational by 2027” to “is expected to be operational in 2027”; no change was emitted. This was a real source-scoping regression, not a flaky test or justification for changing the existing assertion. The earlier bounded reviews did not detect this form.

Independent pure diagnosis confirmed that the raw extractor preserved `operational_target`, `deadline` and `within`, and selected-site subject binding succeeded. The downstream owned-predicate grammar nevertheless rejected both phrases because its expected-to-be alternative omitted the leading auxiliary “is.” Both scoped material states were consequently empty. Material-state normalization and change detection did not need to change.

Commit `380b0dec` adds only an optional finite `is` / `was` / `will be` auxiliary to that existing direct expected-to-be predicate, plus a new test file. Exact re-extraction, first-event ownership, foreign-site refusal, negation controls and qualifier semantics remain in place. Reviewed SHA-256:

- `domain/customer_subjects.py`: `c73007d5686cbc2895bcf8574cfd425acbc8510cc93aa0ef7192b96a53739659`.
- New `tests/unit/test_operational_target_subject_scope.py`: `6303288f167a2a222b2e313976a52f1664306a488ce309f59df528bf90b33f58`.

The reviewer independently passed 13 pure controls: eight auxiliary/qualifier positives, three foreign-site/negation negatives, a first-2027 versus connected-South-2028 case, and the actual material-state transformation retaining distinct deadline/within `build_timing` values. The builder separately reports 11 passing cases across the new tests and the unchanged material-change integration module, including replay quietness. The reviewer did not rerun that database module. Commit inspection confirms no existing backend or web test was modified by this repair.

**The bounded repair is accepted.** The full `605d6bcc` backend run remains a failed historical run. Complete CI/browser results and the 20-organization replay for the newer source were pending at this addendum; the earlier coverage/performance receipts above do not become `380b0dec` measurements. The commercial/default/contact, read-performance and unresolved-ingestion-timeout limitations are not closed by fixing this grammar omission.
