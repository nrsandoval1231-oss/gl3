# GridLens remaining audits — October 31, 2026

Audited main **`00026c758ece2bc41eea88c478cbb0112f9e0de5`**, tree **`125b7dc0ee61a890b1dffff40f3b2891df3be9c1`**. It matches the tested, clean worktree at `78591b3` byte for byte. Deployment remains on hold. No critical or high-severity defect was established in these four scoped audits.

The audit confirmed two documented ingestion recovery gaps, incompatible repository recovery tools, and misleading fallback guidance. It measured test costs and worker imbalance without establishing the original timeout’s cause. Public HTTP works; authenticated performance and production rollback readiness remain unverified for the specific reasons below.

Four scoped reviewers completed ingestion, operations, runtime, and performance reviews. A separate reviewer checked the material findings against source and raw evidence; see [independent review](independent-review.md).

## Findings and recommended priorities

P2 means medium reliability or operational risk. P3 means lower-priority documentation or validation-efficiency work. None establishes a missing production filing or a broken deployed recovery mechanism.

| Finding | Priority and classification | Recommended bounded work |
|---|---|---|
| I1. Flare acquisition cannot recover submissions outside its three-day window or recheck older status changes. | P2: documented missing recovery feature | Durable interval coverage plus a separate retained-filing status lane. |
| I2. Drilling acquisition does not recover missed archive months beyond the previous month. | P2: documented missing catch-up feature | Durable month coverage and budgeted recovery of missing official EOM products. |
| O1. The repository wrapper generator emits a command removed from the current CLI. | P2: tool compatibility defect | Archive legacy reuse or update the protected allowlist and test it against the real CLI. |
| O2. Blanket switch-off fallback guidance does not cover current project/company browsing. | P2: misleading recovery instruction | Document endpoint-specific recovery requirements and current generation dependencies. |
| O3. The release rehearsal is pinned to schema 0041 and obsolete rollback behavior. | P2 **if reused for this release**: legacy tool limitation | Explicitly archive it or build a reviewed schema/image/policy-bound replacement. |
| O4. The recovery guide still describes 0048 as a new migration. | P3: stale wording | Make that historical and require actual schema/head preflight. |
| R1. Passing diagnostics show fixture costs and worker imbalance; failed-run observability is insufficient. | P3: validation efficiency and diagnostics | Preserve bounded per-test timing, queue, resource, and database observations in ordinary validation. |

### I1: flaring recovery and status updates

Source: `config/sources/registry.v1.json:27–34`; `backend/src/gridlens/ingestion/adapters/rrc_flare_exceptions.py:282–283,314–317`; normal dispatch at `adapters/__init__.py:92–93`.

**Executed offline reproduction:** a synthetic filing submitted October 1 is returned for the September 29–October 1 query. Its publisher-shaped fixture changes from Submitted to Approved by October 6. The real adapter then requests only October 4–6 and returns zero records. Prior-success metadata does not change those dates. A submission missed during a longer outage likewise falls outside normal retries.

Status changes can change retained evidence when reacquired; stable filing IDs and mutable status hashing work (`rrc_flare_exceptions.py:187–191`). The gap is acquisition coverage, not a newly found parser failure. Schedule reconciliation does not change adapter dates (`jobs/worker.py:363–435`).

Business impact is stale or undiscovered source evidence. No actual missing production filing, physical flaring, lost electrical demand, or lost revenue was established. The registry accurately discloses this limitation. A future fix should separate completed acquisition intervals from scheduling receipts, bound catch-up work, and monitor retained IDs separately. Acceptance should include a five-day outage, late status changes, zero-result intervals, segmentation, restart replay, and immutable idempotency.

### I2: drilling archive recovery

Source: `registry.v1.json:80–85`; `rrc_drilling.py:508–522`.

**Executed offline reproduction:** on October 1, the adapter requests September 30 EOM and the current daily product. On December 1, it requests November 30 EOM and the current daily product. Recovery does not request October EOM. The real parser and consolidation ran against mocked downloads. Actual archive availability and production omissions were not inspected.

Counter-evidence: amendment precedence and same-sequence replacement are intentional (`rrc_drilling.py:160–169`); ingestion protects newer projections from older recurrences (`ingestion/service.py:3252–3294`). Exact retained-well/completion research **exists**, with enablement, budgets and refresh controls (`intelligence/rrc_well_research.py:27–32,155–209,283–290`). It can enrich known identities, but cannot discover identities that were never retained. Its production operation remains unverified.

Future catch-up should record fully acquired months, recover missing products within budgets, preserve current discovery, and report inaccessible intervals. Do not duplicate or overlook the existing exact-well lane. These two source limitations are scoped follow-on work, not a reason to make the entire target intelligence engine a gate for an early repair release.

### O1–O4: recovery tooling and guidance

**O1 reproduction:** AST extraction shows `scripts/stage_release_wrapper.py:138–160` emits `gridlens.jobs.browse rollback --generation`. The real parser choices at `backend/src/gridlens/jobs/browse.py:25–40` omit `rollback`. Feeding those literal choices to argparse rejects it with exit 2. The generator lacks the replacement stage/inspect/publish operations; its unit tests assert the obsolete suffix (`backend/tests/unit/test_stage_release_wrapper.py:151–173`). No protected wrapper or administrative command was executed.

**O2 reproduction:** `docs/operations/saved-browse-ingestion.md:40–48` and `saved-browse-b1.md:86–87` promise broad switch-off fallback. Current UI routes at `api/app.py:2041–2100` call project/customer results, which require a current generation (`intelligence/project_results.py:35`; `customer_results.py:25–30`). Pure extracted-function checks confirmed those calls occur with `saved_browse_enabled=False`. Missing or incompatible generations fail closed with 503 (`saved_browse.py:364–399`). Some older routes do have fallback; the finding concerns blanket guidance for today’s ordinary UI.

**O3 reproduction:** `scripts/rehearse_release.py:24–25,489–502,864–865` assumes schema 0041. Equal synthetic 0049 snapshots fail its comparison. It also invokes obsolete rollback behavior (`:523–551,953–960`). Current repository migration head is 0049 (`backend/migrations/versions/0049_scoped_identity_entity_browse.py:5`). Historic receipts remain valid for their exact images/dumps; this helper cannot certify a current release unchanged.

**O4:** `docs/operations/contact-suppression-rollback.md:11` retains stale 0048 rollout wording. Its stage/inspect/publish instructions at lines 15–25 otherwise describe the supported lane.

The older hardening plan explicitly marks itself historical. Actual installed host tooling might differ from the repository generator. These findings do **not** establish a deployed rollback failure. Reconcile actual capabilities before reuse; mechanically renaming `rollback` to `publish-recovery` is insufficient because the guarded receipt semantics differ.

## Runtime variability

| Preserved full-run receipt | Actual outcome |
|---|---|
| Earlier local candidate | 3,667 passed / 1 skipped; 350.31 seconds in pytest |
| Hosted PR CI `41220159391` | 3,667 passed / 1 skipped; 362.56 seconds |
| Fresh exact-command local CI | **Failed:** GNU timeout exit 124 at 480.095 seconds; 3,668 collected; last printed progress 94% |
| Single instrumented local diagnostic | 3,667 passed / 1 skipped; 336.98 seconds; unchanged four-worker/480-second gate, but added observer means not exact CI-command equivalence |
| [Merged-main CI `41226509696`](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41226509696) | 3,667 passed / 1 skipped in 346.00 seconds; all five jobs passed; 179 browser tests passed |

**No full suite was rerun for this remaining audit. The 480.095-second failure remains failed and unexplained.**

Independent raw-event analysis confirmed workers finishing at 183.41/189.83 seconds versus 317.63/335.11 seconds. At 190 seconds, 278 cases remained. Setup and teardown account for 39.6% of summed parallel phase time, not wall time. Saved-browse fixtures used 76.08 seconds across 127 cases for setup/teardown.

The slowest calls were bulk-ingestion browsing at 29.39 seconds, shadow rotation at 24.91 seconds, and consumed-prefix traversal at 12.77 seconds. The original one-second daily-lock test passed unchanged; its full call took 0.130 seconds. No hidden worker-refresh path, sustained lock defect, OOM, or causal storage explanation was established. Heavy checkpoints also occurred in passing runs.

These observations identify measurement priorities, not fixes. Failed-run queue identities and contemporaneous resources were not recorded. Xdist scheduling can leave heterogeneous assigned work on fewer workers, but actual queue history was not captured. Observer overhead beyond direct logging/query costs is unquantified. Do not increase the deadline, reduce fixture coverage, weaken isolation/assertions, or loop until green.

## Current public speed and access

Fresh cloud-proxy reads returned HTML 200, auth-session 200 with `authenticated:false`, and protected health/project-list routes 401. The latter have one sample each. These establish public reachability and those anonymous boundaries, not authenticated health or workflow acceptance.

| Resource | Samples | Median TTFB | Median total | Total range |
|---|---:|---:|---:|---:|
| HTML | 3 | 237.63 ms | 237.75 ms | 115.02–361.81 ms |
| Entry JavaScript | 3 | 155.67 ms | 225.18 ms | 184.78–467.07 ms |
| CSS | 3 | 231.03 ms | 338.10 ms | 117.56–355.16 ms |

These are fresh-process HTTP transport timings through the inherited proxy, including connection/TLS/transit. They are **not browser load, cold/warm browser cache, mobile-device, or signed-in API benchmarks**. Exactly six additional GETs expanded initial resource samples to three each; no load testing occurred.

Normal `curl --compressed` negotiation delivered hashed assets with `no-store`, no content encoding, and equal transfer/decoded bytes. This is a candidate repeat-load cost on the observed proxy path, **not origin attribution or a confirmed origin compression defect**. Preserve private API/auth/HTML cache requirements; inspect the serving layer before proposing changes.

Native Chromium with TLS verification enabled failed `ERR_CERT_AUTHORITY_INVALID` through the cloud proxy before rendering. Six bounded desktop/mobile attempts produced **zero valid render, LCP, CLS, TBT, cold/warm or screenshot samples**. No TLS/proxy bypass was used. Curl successfully verified TLS on its configured trust path, so this is not proof of an origin certificate fault.

No authorized persisted browser profile/session or secure interactive login handoff was exposed by current tools. No login or new authentication session was created. Authenticated search/filter/pagination/detail/contact latency and responsive/console checks therefore remain blocked. Public JavaScript differs from the existing candidate build while CSS matches; deployed backend SHA remains unknown. This does not establish deployment of the merged frontend and is consistent with the deployment hold.

## Production release and rollback gates

The candidate’s source-derived policy is:

`browse-b1-v1/ranking-v2-regional-geography/regional-project-scope-v1/27851625e924e8bc0e3dede6`

The fingerprint includes registry bytes and every backend Python path/byte (`saved_browse.py:64–82`). Verify packaged contents and actual runtime policy, not only SHA labels or counts. Actual deployed images/schema remain unknown; the linked PR148/0049/74-table receipt is dated history.

Current recovery checks input/full revisions, active/prepared pointers, policy, integrity/counts and a valid interval with at least 60 seconds remaining (`saved_browse.py:901–1045`). A pre-staged receipt normally becomes stale after candidate publication changes the pointers. Pure predicate checks confirmed that behavior.

A supported rollback needs the **prior backend image paired with a current-data generation compatible with its actual policy**, freshly inspected and guardedly published. Prove the exact image capabilities in an isolated rehearsal. Do not force a captured UUID, overwrite current data with an old database, downgrade schema, or remove suppression history.

Connected DigitalOcean metadata reports `gridlens-production` active in NYC1 with two backup IDs. That does not prove application health, backup freshness, restore success or retention. A backup-policy lookup returned an argument-binding error, not an access denial; no policy result was obtained.

This workspace has no configured SSH agent/socket/default identity/config, and available tools expose no SSH host executor. No host connection was attempted. Protected wrapper contents, image digests, schema, worker/provider controls, generation state, and fresh backup/rollback proof remain unverified. Future deployment still requires explicit owner instruction, reconciled recovery tooling, authorized host preflight, current backup/isolated restore, exact image/generation pairing, and authenticated canary/live acceptance. None occurred now.

## Coverage, evidence and action state

Fresh validation: **11 focused RRC tests passed**, 55 deselected, in 0.33 seconds with mocked transport and no database connection; offline adapter-window reproductions; pure AST/argparse/snapshot/fallback/CAS checks; independent runtime-event analysis; bounded public probes; and independent material-finding review. No full suite, migration, restore or production recovery was rerun.

Detailed source references, exact commands and receipts:

- [Ingestion report](ingestion/REPORT.md), `reproduce.py`, `reproduction.json`, `focused-tests.log`.
- [Operations report](operations/report.md), `static-validation.json`, `fallback-cas-validation.json`.
- [Runtime report](runtime/report.md), linking preserved full-run artifacts.
- [Performance report](performance/REPORT.md), `transport-samples-n3.json`, browser failures, response evidence and asset comparison.
- `infrastructure-observation.json`, [independent review](independent-review.md), `source-final-state.json`, `evidence-manifest.json`.

**Denied actions: none. Pending tool actions/approvals: none.** Native browser navigation failed certificate validation; authenticated coverage is blocked by that path and absence of an authorized session. The timeout cause and listed production properties remain uncertain. No production mutation has an uncertain execution outcome.

No source fixes, commits, pushes, PRs, new Actions runs, production changes, generation changes, ingestion/backfill, paid AI, credential creation or PC use occurred. Audit artifacts are outside the clean source checkouts. Deployment remains explicitly held.
