# Repository and production readiness audit — October 24, 2026

Release status: **BLOCKED**. Repository repairs have separate deterministic and independent acceptance gates. This record does not authorize production changes or close M6 or the parent Finish Contract.

## Repository truth and preservation

Fetched `origin/main` at `fae481db749b2e71dfb41ee63547c3fa1f6b1170`; `git fsck --full --no-dangling` exited 0. Its [main CI](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40110387381) succeeded. The original recovery checkout and all existing worktrees, tracked/untracked files, databases and ignored evidence were preserved. Work is isolated on `audit/repository-readiness-20261024`.

The canonical PRD, TX/OK/NM physical-site policy, commercial qualification, Jev → Sol advisory → deterministic validation, seven-color tokens, G/L masters and public assets remain authoritative. No source acquisition, provider dispatch, production mutation, database reset or artwork regeneration is part of this audit. Temporary brand generation uses copied inputs.

GitHub main had no branch protection or repository rulesets at inventory time. The controller must enforce exact-head review and all three CI jobs before merge; a missing/skipped check is not success. This audit does not silently change owner governance settings.

## Findings and disposition

| Priority | Finding | Disposition and evidence |
|---|---|---|
| P0 | Brand toolchain vulnerabilities in Brotli, Pillow, CairoSVG and fonttools | Remediation pins: 1.2.1, 13.0.0, 2.9.1 and 4.60.2 respectively. Resolved brand audit: 13 packages, zero known vulnerable packages. See [security completion](../../.agent/readiness-20261024/SECURITY_COMPLETION.md). Both original dependency PRs share a comprehensive candidate; their earlier standalone upgrades did not clear the graph. |
| P0/P1 | Deployed container package findings | Read-only exported image scan found web 216 package findings (2 critical/62 high), API 177 (0 critical/46 high), PostgreSQL 378 (2 critical/86 high). These are package/CVE matches, not proof of exploitability. Preserve the scanner reports and distinguish fixable findings from vendor packages with no published fix. Local container repairs and their proof are recorded separately. Production remains unchanged. |
| P1 | RRC drilling source fails with `acquisition_result_too_large` | Generic IPC 8 MiB is smaller than the legal evidence-preserving two-snapshot result. A fixed internal 64 MiB RRC-only allowance preserves all raw bytes, hashes, fetch limits, deadline and 512 MiB child memory. Generic calls stay at 8 MiB. Linux controller boundary regression: 28 passed; builder also reports 67 RRC/retained-permit cases. Full candidate validation and independent review are separate gates. See [RRC completion](../../.agent/readiness-20261024/RRC_COMPLETION.md). No source retry occurred. |
| P1 | M6 incomplete and original QA corpus absent | Albuquerque Sol remains `SENT_OUTCOME_UNKNOWN`; no retry, replacement, ledger reset or budget release. Original 446 QA records came from Grok `/workspace/gl3-qa`, report `QA Build Review`; no original export/manifest is available in the reviewed repository or production-build evidence. The 578-observation M6 and older RRC corpora are distinct and cannot substitute. |
| P1 | Production source coverage incomplete | Houston reports `publisher_stale`; Austin reports a bounded chain-budget pause; TCEQ NSR reports record-local partial failure. These visible states must not be weakened into successful acquisition. PUCT docket and filing sources, Oklahoma DEQ and Albuquerque report saved successful checks; this audit made no new acquisition. |
| P2 | Checkout credential persistence and missing brand dependency CI audit | All CI checkout steps disable persistence. A resolved brand dependency audit now retains JSON. Independent review caught a missing root output directory in its first version; the repair creates the directory before redirect. Zizmor offline final scan exits 0; online-only audits were not exercised. |
| P2 | Windows brand generation encoding | Explicit UTF-8 token/CSS I/O fixes the reproduced platform-default decoding failure. Controller reran two temporary generations: all 217 files plus CSS matched byte-for-byte; 216 assets passed structural/reference/font/token/eight AA contrast checks. Original artwork is untouched. |
| P2 | Mixed production source revisions, pending release | Web label `fae481db749b2e71dfb41ee63547c3fa1f6b1170`; API/worker/browse label `ca013d4c2dc8084a708ff5cfc092ec20b1d8c61b`. Prepare a reviewed release from the final merged revision; do not equate an image tag with validated production acceptance. |
| P2 | Container root users / missing image health checks | Static scanner observations; assess runtime requirements before changing users, storage permissions or service probes. The alternate scheduler preparation YAML is not the actual production deployment and its scanner findings are not deployed Kubernetes findings. |
| P3 | Historical evidence and duplicate-looking worktrees | Retained deliberately. Historical PR packets, fixture screenshots, source adapters outside the current enabled territory and recovery branches are not dead code merely because old. No speculative deletion or subsystem rewrite. |

## Branch hygiene

Initial 59 remote branches: main, 2 active PR heads, 25 with unique unmerged commits and 31 ancestors of main. Of those 31, 23 had an exact-tip merged PR, no open PR and no checked-out worktree. Their deletion used a single atomic push with a separate exact-SHA lease for every ref. The other eight were retained for active local worktree ownership or uncertain PR identity. All 25 unique-work branches were retained for owner review; squash/patch equivalence was not used to erase unique commits.

The [initial inventory](../../.agent/readiness-20261024/BRANCH_INVENTORY_BEFORE.json) includes each name, tip, ancestry, unique count, PR mapping and disposition. The [deletion ledger](../../.agent/readiness-20261024/BRANCHES_DELETED.json) records the 23 removed names and exact tips. Local worktrees and branches were not deleted. Audit-created refs and the final post-merge inventory are reported separately.

## Read-only production observations

Observed October 24, approximately 17:39–17:43 UTC. All six containers were running with zero restarts. PostgreSQL reported healthy; SQL read-only transactions confirmed connectivity, schema `0041_evidence_packages`, 66 public tables, 20,574 observations, 24,377 evidence rows, and 1,817 projects/power needs. No expired running job leases or queued jobs overdue by one hour were present. A valid saved generation contained 1,749 rows and expires October 25 at 00:00 UTC.

Last-24-hour source check receipts: 163 succeeded, 2 failed, 5 unknown and 2 partial. These historical counts do not establish seven-day source acceptance. Bounded database log review categorized 54 row-lock acquisition failures, 24 autovacuum cancellations, 2 lock timeouts and 1 statement timeout; three worker warnings retained canonical changes while deferring saved-browse refresh. No deadlock or connection-limit event was identified in that bounded log sample. The current generation is valid; this is not a guarantee of future renewal.

Public HTTPS smoke returned `/` 200 (0.089 s), `/api/auth/session` 200 (0.018 s), protected `/api/health` 401 (0.019 s) and protected workspace 401 (0.016 s). These are individual measurements, not an SLO or authenticated workspace proof. Required API database/auth/session/origin settings are present; OpenAI and TypeSafe key presence was verified without values; Firecrawl key is absent. No keys, secret hashes or environment values were exported. Broader provider readiness remains blocked.

## Validation and release boundary

Use independent full backend, migration-repeat/schema, API contract, frontend type/build/audit, browser/auth/responsive and brand checks on the frozen integrated candidate. Raw controller receipts are under ignored `.artifacts/readiness-20261024/`; final acceptance/review is retained under `.agent/artifacts/READINESS-20261024/`. Preserve failed attempts. A preliminary local run was interrupted when integration changed its starting SHA; it is explicitly invalidated and cannot support exact-candidate acceptance.

The tests use a newly created loopback-only PostgreSQL instance and dedicated disposable application/test databases. No retained corpus or production database is a test target. Provider keys are blank and automation disabled in test subprocesses. Fixture browser regressions and the two tests requiring live retained records/worker have separate acceptance meanings.

No migration is added by this audit; production and candidate migration heads are `0041_evidence_packages`. A future authorized deployment should keep the database/schema intact, preserve a fresh verified backup and current compose/image identities, stage the exact validated API and web images, prove startup and authenticated smoke, and retain the current image digests for application rollback. Do not run migration downgrades or rebuild canonical data as rollback. Database-image upgrades and upstream unpatched package exposure require separate release decisions. The actual host uses `/etc/gridlens/compose.app.yaml`, not the alternate preparation recipe.

Release blockers: pending final exact-candidate gates/review/CI until recorded; production patch deployment authorization and validation; remaining container vendor findings; incomplete source coverage; missing original 446-record export; Albuquerque unknown fifth provider outcome; contradiction-pair and broader M6/Finish Contract requirements. Passing repository tests does not remove these gates.
