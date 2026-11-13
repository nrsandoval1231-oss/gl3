# GridLens commercial intelligence delivery checkpoint

November 13, 2026. **Draft, undeployed, commercially blocked.** This is a reviewable implementation checkpoint, not completion of the full mission or permission to release.

## Reviewable changes

| Slice | Draft PR | Source reference |
| --- | --- | --- |
| Architecture audit and canonical contract | [195](https://github.com/nrsandoval1231-oss/gl3/pull/195) | `8d445e63bc9b2311f0c0edf6c66a3f6b992433c3` |
| Aggregation, fact resolution, scenarios, priority and performance repair | [196](https://github.com/nrsandoval1231-oss/gl3/pull/196) | `1de298af047f09a32e9a0349f41410a55bc1791e` |
| Customer workspace and material UI review repairs | [198](https://github.com/nrsandoval1231-oss/gl3/pull/198) | UI `5a727a95`; reconciled backend merge `2aea1aa08a11e1d20ad6dbacbd141c4ef0e0e345` |

The originally planned aggregation and commissioning PRs share one evidence contract and were combined. Evaluation, performance receipts and independent review remain separately reviewable. All branches preserve audited main `bf75d32746d28ac44effcb65989d53fdeaa765e4`. PR189 was inspected and selectively reconciled; its conflicting draft was not merged. External PR197's contact-query/JIT work was inspected and attributed in the [read performance reconciliation](../../engineering/customer-commercial-read-performance-20261113.md).

## Architecture and model

The [audit and contract](../../engineering/customer-commercial-intelligence-20261112.md) explain existing canonical identities, account grouping, ingestion, Phase2 research, evidence, Pursuits, migrations and release identity. [Retained fact publication](../../engineering/customer-facts-persistence-20261112.md) documents generation-bound projection and publication guards. No parallel identity namespace, live-navigation research, new microservice or schema migration was introduced.

The [commissioning model](../../engineering/commissioning-model-20261112.md) cites engineering references and documents a versioned deterministic equipment/test-plan scenario. Nameplate capacity alone produces no commissioning estimate. Input ratings, test fractions, electrical paths, concurrency and sequence require evidence; unknowns stay unknown. A scenario never establishes customer rental demand.

The workspace exposes existing canonical customer groups, typed capacity and precise timelines, material developments, next actions and verified contact states. Full evidence, conflicts and assumptions use customer detail. Existing authentication, Pursuits and Reports remain. [Before/after captures](README.md) cover five viewport sizes and detail using explicitly synthetic fixtures; they do not establish production coverage or salesperson usefulness.

## Real-source acceptance blocker

The [20-organization evaluation](../../../eval/customer-commercial-v1/README.md) retains 29 hashed source artifacts, independently checked r2 reference labels, reproducible commands and historical result snapshots. Final backend `1de298af` measures:

- Raw capacity: 7 true positives, 10 false positives, 25 missed assertions; precision 41.18%, recall 21.875%.
- Raw timelines: 1 true positive, 6 false positives, 29 missed assertions; precision 14.29%, recall 3.33%.
- Runtime-scoped capacity/timeline output: **zero published claims**, zero recall; precision and published provenance completeness are undefined, not perfect.
- All20 commissioning cases abstain because source excerpts lack test-plan inputs. This validates refusal behavior only.

Source-supported facts exist. The zero scoped output is an extraction/project-attribution coverage gap, not evidence that public information is unavailable. Weakening project-scope guards to improve recall would risk cross-project false facts. Runtime source authority also lacks the evaluator's independently supplied official-domain classification.

Canonical identity, project association, duplicate rate, double-counting, current contact acquisition, commercial ranking and salesperson usefulness remain explicitly not evaluated end to end. Six historical functional leaders in source excerpts are not six verified current buyers. This checkpoint does not satisfy those acceptance criteria. Safe expansion needs source-bound project context and authority resolution, independently reviewed extraction improvements, actual identity/contact journeys and salesperson acceptance against the retained reference cohort.

## Verification and performance

Historical backend `4b6d0f92` passed 178 changed tests and Astra's 52-case safety recheck. Its full GitHub CI run [43332605737](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43332605737) failed: 5,516 passed, three failed and one skipped. Two failures exposed added grouped queries; the repair keeps the original gates and removes the duplicate query. The third was a brief-refresh publication failure; four variants pass in isolation, but its cause is unproven. Interrupted local full-suite runs are not passes.

Historical scoped [Astra receipts](reviews/) retain both failed and successful source-specific reviews. The first UI review withheld acceptance for conflict visibility, a name-only contact branch, commissioning inputs and rendering defects. Those were repaired at `5a727a95`; a fresh review and final CI own their eventual disposition.

The [performance evidence](performance/README.md) preserves exact source manifests and raw measurements. The earlier `4b6d0f92` run added 900/300/330 ingestion SQL statements for new/unchanged/amended phases, and larger card payloads. Shared load confounds timing; this is not a no-regression pass. A fresh repaired-source read benchmark is recorded separately and cannot erase ingestion overhead. The representative corpus has 2,098 presentation projects/417 groups but only48 persisted underlying needs; it is synthetic and not a fully researched production corpus. Direct service latency excludes authentication, HTTP and browser rendering.

## Rollback and release disposition

No production deployment, source activation, credential change or retained operational data mutation was performed. All SQL fixtures and benchmarks target disposable loopback databases. Rollback is a code revert; because Python source participates in browse-policy identity, use the existing generation rebuild/recovery mechanisms after either promotion or rollback. Evidence receipts remain immutable and the database schema stays at0056.

Do not merge failing/unresolved drafts, activate providers or deploy based on these receipts. Production readiness remains **withheld** until commercial coverage and contact/sales acceptance, final CI, independent review and performance concerns are resolved, followed by explicit deployment authorization.
