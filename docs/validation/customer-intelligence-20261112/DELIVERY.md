# GridLens commercial intelligence delivery checkpoint

November 13, 2026. **Draft, undeployed, commercially blocked.** This is a reviewable implementation checkpoint, not completion of the full mission or permission to release.

## Reviewable changes

| Slice | Draft PR | Source reference |
| --- | --- | --- |
| Architecture audit and canonical contract | [195](https://github.com/nrsandoval1231-oss/gl3/pull/195) | `8d445e63bc9b2311f0c0edf6c66a3f6b992433c3` |
| Aggregation, fact resolution, scenarios, priority and performance repair | [196](https://github.com/nrsandoval1231-oss/gl3/pull/196) | Application `1de298af047f09a32e9a0349f41410a55bc1791e`; test-only follow-up `aa5f2c351c153fd7a20ce7a75292ec0a35f5a2cd` |
| Customer workspace and material UI review repairs | [198](https://github.com/nrsandoval1231-oss/gl3/pull/198) | UI `c0063c7f27dffeb591697a039a481edd1044b77e` (equivalent acceptance fixes `8db88747` + `7c85c32e`); backend-test reconciliation `ee20e8aad3944f63caf3aa83b74da4a224a40e40`; integration `5f9a271c` |

| Real-customer evaluation and full-stack integration evidence | [199](https://github.com/nrsandoval1231-oss/gl3/pull/199) | Main-base integration; exact final receipt commits are listed below |

The originally planned aggregation and commissioning PRs share one evidence contract and were combined. Evaluation, performance receipts and independent review remain separately reviewable. All branches preserve audited main `bf75d32746d28ac44effcb65989d53fdeaa765e4`. PR189 was inspected and selectively reconciled; its conflicting draft was not merged. External PR197's contact-query/JIT work was inspected and attributed in the [read performance reconciliation](../../engineering/customer-commercial-read-performance-20261113.md).

## Architecture and model

The [audit and contract](../../engineering/customer-commercial-intelligence-20261112.md) explain existing canonical identities, account grouping, ingestion, Phase2 research, evidence, Pursuits, migrations and release identity. [Retained fact publication](../../engineering/customer-facts-persistence-20261112.md) documents generation-bound projection and publication guards. No parallel identity namespace, live-navigation research, new microservice or schema migration was introduced.

The [commissioning model](../../engineering/commissioning-model-20261112.md) cites engineering references and documents a versioned deterministic equipment/test-plan scenario. Nameplate capacity alone produces no commissioning estimate. Input ratings, test fractions, electrical paths, concurrency and sequence require evidence; unknowns stay unknown. A scenario never establishes customer rental demand.

The workspace exposes existing canonical customer groups, typed capacity and precise timelines, material developments, next actions and verified contact states. Full evidence, conflicts and assumptions use customer detail. Existing authentication, Pursuits and Reports remain. [Before/after captures](README.md) cover five viewport sizes and detail using explicitly synthetic fixtures. The after fixture expanded during review; the retained before images lack those later scenario/conflict additions, so the images are illustrative states rather than a strictly matched same-input comparison. They do not establish production coverage or salesperson usefulness.

## Real-source acceptance blocker

The [20-organization evaluation](../../../eval/customer-commercial-v1/README.md) retains 29 hashed source artifacts, independently checked r2 reference labels, reproducible commands and historical result snapshots. Final backend `1de298af` measures:

- Raw capacity: 7 true positives, 10 false positives, 25 missed assertions; precision 41.18%, recall 21.875%.
- Raw timelines: 1 true positive, 6 false positives, 29 missed assertions; precision 14.29%, recall 3.33%.
- Runtime-scoped capacity/timeline output: **zero published claims**, zero recall; precision and published provenance completeness are undefined, not perfect.
- All 20 commissioning cases abstain because source excerpts lack test-plan inputs. This validates refusal behavior only.

Source-supported facts exist. The zero scoped output is an extraction/project-attribution coverage gap, not evidence that public information is unavailable. Weakening project-scope guards to improve recall would risk cross-project false facts. Runtime source authority also lacks the evaluator's independently supplied official-domain classification.

Canonical identity, project association, duplicate rate, double-counting, current contact acquisition, commercial ranking and salesperson usefulness remain explicitly not evaluated end to end. Six historical functional leaders in source excerpts are not six verified current buyers. This checkpoint does not satisfy those acceptance criteria. Safe expansion needs source-bound project context and authority resolution, independently reviewed extraction improvements, actual identity/contact journeys and salesperson acceptance against the retained reference cohort.

## Verification and performance

Historical backend `4b6d0f92` passed 178 changed tests and Astra's 52-case safety recheck. Its full GitHub CI run [43332605737](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43332605737) failed: 5,516 passed, three failed and one skipped. Two failures exposed added grouped queries; the repair keeps the original gates and removes the duplicate query. The third was a brief-refresh publication failure; four variants pass in isolation, but its cause is unproven. Interrupted local full-suite runs are not passes.

Historical scoped [Astra receipts](reviews/) retain both failed and successful source-specific reviews. The first UI review withheld acceptance for conflict visibility, a name-only contact branch, commissioning inputs and rendering defects. Those were repaired at `5a727a95`; bounded labels were clarified at `8db88747`. A subsequent complete browser run at `2aea1aa0` failed six cases (330 passed, one flaky): two empty contact-container regressions and four old brand/empty-state/layout expectations. These remain explicit failures until the final strict contact-preserving repair and rerun. Final UI repair `7c85c32e` (equivalent UI branch `c0063c7f`) suppresses empty contact containers and contact-only fallback metadata. Independent [Astra UI re-review](reviews/astra-ui-7c85c32e.md) ran 25 focused cases plus one reviewer-authored metadata-suppression case successfully. It closes the demonstrated defects, not full product/design or commercial acceptance. The frozen local generic command reported 338 tests, with an auth failure artifact caused by a confirmed local 403 Origin check; the isolated real-auth test passed 1/1 with the correct trusted local origin. No application security was relaxed. Its aggregate summary was not retained, so full-run pass/flaky counts and duration are unknown; it is not counted as a passing full-suite receipt. See the [local UI receipt](reviews/ui-final-7c85c32e-receipt.md). Final CI owns complete integration disposition.

The [machine-readable verification record](verification.json) and [affected backend test output](reviews/backend-1de298af-affected-tests.txt) retain completed results and distinguish historical failures. GitHub checks and PR199 own later full-run status.

The [performance evidence](performance/README.md) preserves exact source manifests and raw measurements. The earlier `4b6d0f92` run added 900/300/330 ingestion SQL statements for new/unchanged/amended phases, and larger card payloads. Shared load confounds timing; this is not a no-regression pass. The [fresh repaired-source read benchmark](performance/read-repair/README.md) restores steady service SQL count to53 and shrinks earlier candidate payloads by65–88%, but remaining latency overhead and ingestion SQL cost are unresolved. Astra independently verified all 15 artifact hashes and recomputed the 12 thirty-sample median/p95 sets. These bounded checks cannot erase ingestion overhead or establish a no-regression pass. Independent UI review also identifies remaining product-design acceptance work: duplicate search/next-action affordances and long mobile cards. Synthetic screenshot checks do not establish the requested five-second salesperson comprehension. The representative corpus has 2,098 presentation projects/417 groups but only 48 persisted underlying needs; it is synthetic and not a fully researched production corpus. Direct service latency excludes authentication, HTTP and browser rendering.

### Final backend repair checkpoint

Backend `1de298af` passed the integrated affected matrix: **251 passed, three warnings in 654.02 seconds**. This includes unchanged representative-scale/query-budget gates, actual native contact suppression, compact/detail projections, commissioning/phase safety and the complete power-need-brief module. The `-k` exclusion in that command named a nonexistent test and deselected nothing. Warnings were the existing TestClient deprecation and two connection/isolation warnings. Independent Astra separately ran 95 pure/scoping cases. These are not full-suite or whole-commercial acceptance.

The repaired backend full CI [43337420044](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43337420044) completed: **5,534 passed, one failed, one skipped, 22 warnings in 683.01 seconds**. Earlier query-budget and brief-refresh failures passed. The remaining `test_customer_group_routes_validate_queries_and_cohort_tokens` whole-object equality assertion predates the deliberately compact card/detail contract. Its test-only update preserves all legacy identity fields and explicitly checks commercial display parity and retained detail arrays; test-only correction `aa5f2c35` passes the entire 13-case routes/projection/query matrix and a final revised route case. Astra independently accepted the strict legacy parity and detail-preservation correction. Application source is unchanged from `1de298af`, so its source-bound benchmark remains applicable. Fresh exact-head CI is still required; the historical run remains a failure, not a pass.

## Rollback and release disposition

No production deployment, source activation, credential change or retained operational data mutation was performed. All SQL fixtures and benchmarks target disposable loopback databases. Rollback is a code revert; because Python source participates in browse-policy identity, use the existing generation rebuild/recovery mechanisms after either promotion or rollback. Evidence receipts remain immutable and the database schema stays at 0056.

Do not merge failing/unresolved drafts, activate providers or deploy based on these receipts. Production readiness remains **withheld** until commercial coverage and contact/sales acceptance, final CI, independent review and performance concerns are resolved, followed by explicit deployment authorization.
