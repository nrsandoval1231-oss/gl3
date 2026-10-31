# Phase 1 draft handoff — October 31, 2026

Draft PR: https://github.com/nrsandoval1231-oss/gl3/pull/160
Commit: 78591b308aa829a25157bf3310133ed069434d3b
Tree: 125b7dc0ee61a890b1dffff40f3b2891df3be9c1 (remote tree exactly matches staged reviewed content)
Base: 593cfd516d82a12b66558f53b975ad6c2b711517
Branch: fix/phase1-reliability-20261031
GitHub CI: queued run41220159391, https://github.com/nrsandoval1231-oss/gl3/actions/runs/41220159391 — not claimed green.

Local backend: 3667 passed, one intentional live-probe skip, seven subtests, 350.31s, exit0 under four-worker480sec gate. First strict attempt3666pass/one Dallas fixture failure/one skip338.45s is preserved under backend/first-attempt. Source fixture failure reproduced on unchanged baseline; only testclock corrected.
Node22.23.4:179 browser passes/zero failures/skips/flaky144.274s; typecheck/build passed. Node24 also179pass. Fresh npmci build bytes identical to tested build. Lint/format425, mypy190, documentation links, brand216/eightAApairs, fresh migrations+isolatedrestore0049/74tables passed. Patched backend audit47/0, brand13/0. npm highgatepass, three moderate devtoolentries one minimatch chain remain/noautofix.

Independent integrated and Astra/high source reviews: no blockers; all17 non-Markdown file hashes unchanged through final validation. Reports astra-review.md, independent-candidate-review.md, independent-review-manifest.json.

Fixes: server whole-cohort company/project/ascending-priority sorts, sort cache/URL/history/detail continuity, honest empty-filter/server-page ranges, retained-binding preload query reduction, deterministic historical fixture clocks, pypdf6.21.4 security patch, narrow anti-framing policy, reconciled ops/authorization docs.
Performance: synthetic2032projects/4064needs/50companies;30warm serial in-process authenticated API samples percase, not production. Company/project medians~34/39ms; queryprofile100evidence125→25SQL; walltime improvement not established. Native authenticated productiontimings0; cache/origin attribution/backenddeployedrevision unknown. Original1sshadowfailurecause unresolved despite unchangedtestpassingfullrun.

Deferred: company-first browsing, demand/ingestion/enrichment expansion, RRC catch-up/status monitoring, merge and deployment. Later authorized release needs browse-policy-compatible generation and image/generation rollback. No production writes/providers/ingestion/credentials/PC operations, no formalPR approval/merge/auto-merge/deploy. Original worktree preserved. Publication used supported GitHub Git-object/branch/PR APIs; no force push/history rewrite.
