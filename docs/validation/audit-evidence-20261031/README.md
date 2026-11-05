# GridLens audit and validation archive — October 30–31, 2026

These are dated receipts, not current product authority, deployment authorization, or a claim that every audit item is fixed. This archive saves reports and selected machine-readable validation evidence that previously existed only in the saved cloud workspace. Existing source changes from PR160 and PR161 are already merged; this documentation branch changes no application behavior.

## Read first

| Evidence | Report | Scope and status |
|---|---|---|
| Original comprehensive audit | [October 30 audit](initial-audit/GL3-AUDIT-2026-10-30.md) | Main593cfd5; findings reflect that snapshot, before PR160/161 repairs. |
| Remaining audits | [Consolidated report](gl3-remaining-audit-20261031/REPORT.md) and [independent review](gl3-remaining-audit-20261031/independent-review.md) | Main00026c75; ingestion windows, runtime evidence, recovery tools and bounded public speed. |
| Recovery fixes | [Implementation and review summary](gl3-recovery-evidence/REPORT.md), [independent review](gl3-recovery-evidence/independent-review.md) | Validated PR161 head49fe438; code and guides merged as e0035d9e. |
| Fresh local validation | [PR161 local workload report](local-ci-pr161-20261031-1845/REPORT.md) | 3,686 backend passes/one skip;179browser passes; platform bootstrap limitation retained. |
| Exact merged-main verification | [PR161 post-merge report](pr161-postmerge-20261031/REPORT.md) | Merged e0035d9e has the tested tree; all five main CI jobs passed. |
| Original timeout investigation | [Targeted diagnostics](pr160-runtime-diagnostics-20261031/REPORT.md), [single instrumented full run](pr160-runtime-full-20261031/REPORT.md), [runtime audit](gl3-remaining-audit-20261031/runtime/report.md) | The original480.095second local failure remains unexplained. Later passes do not erase it. |
| Earlier local CI | [PR160 fresh local run](local-ci-pr160-20261031-1644/REPORT.md) | Preserves backend timeout and separately passing jobs; not an overall passing run. |
| Prior release preparation | [PR160 plan](pr160-release-readiness-20261031/PLAN.md), [main CI receipt](pr160-release-readiness-20261031/CI-RESULT.md) | Dated preparation, subsequently qualified by the recovery audit and PR161 repairs. |
| Phase1 review evidence | [Handoff](phase1-evidence/HANDOFF.md), [independent candidate review](phase1-evidence/independent-candidate-review.md), [Astra review](phase1-evidence/astra-review.md) | Historical candidate scope and validation limits are preserved. |

Supporting ingestion, operations, performance and runtime reports are under `gl3-remaining-audit-20261031/`. Initial independent, security, ingestion and frontend reports are under `initial-audit/`. Selected test/check output is retained beside its original run report.

## Status after PR160 and PR161

- Global Company/Project sorting and honest empty-filter ranges were repaired by PR160, merged as [00026c75](https://github.com/nrsandoval1231-oss/gl3/commit/00026c758ece2bc41eea88c478cbb0112f9e0de5). Reports describing the old defects remain historical evidence.
- Guarded recovery wrapper operations, endpoint-specific guidance and explicit historical-only 0041 rehearsal were addressed by PR161, merged as [e0035d9e](https://github.com/nrsandoval1231-oss/gl3/commit/e0035d9e5bfb52f92bb4d21e6de0fac16d91adff). Earlier operational findings describe the pre-repair snapshot.
- Documented RRC acquisition/catch-up limitations remain follow-on work; no missing production filing was proved.
- Test-runtime variability remains unexplained. Isolated and full passes do not prove the original timeout cause.
- Authenticated production speed, deployed image/schema/policy, protected-host tooling and actual prior-image/current-data rollback remain production-dependent gates. Public transport samples are not authenticated application acceptance.
- **Deployment remains explicitly held.** No archive receipt authorizes production writes, generation changes, paid research, ingestion/backfill, credentials or PC operations.

The current maintained procedure is [release and browse recovery](../../operations/recovery-release.md), governed by [operations authority](../../operations/README.md). Use that current guide rather than historical commands in dated reports.

## Hosted CI links

- [PR160 merged-main CI41226509696](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41226509696).
- [PR161 merged-main CI41232015032](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41232015032):all five jobs passed; backend3,686passed/one skipped in344.95seconds, browser179passed.

## Provenance and exclusions

[MANIFEST.json](MANIFEST.json) lists every copied file, its original cloud path/hash, published hash and byte count. Repository links were adapted where corresponding files were saved; source links point to dated commits. Unpublished local references are explicitly labeled. Plain-text cloud paths remain where they document original commands or artifact locations; they are not promises that those local files are in a clean clone.

One disposable local test database password was replaced with a redaction marker. No active credentials, authentication/session profiles, private dumps, raw production response bodies, raw screenshots, complete browser reports/binaries, caches, package environments or the unreviewed evidence tarball are included. Large per-test event/resource streams remain local; published aggregate analyses and source hashes preserve their conclusions and limits. Hosted log originals remain available through the CI links above. This archive is not a complete copy of the execution environment.
