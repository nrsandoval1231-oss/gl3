# Independent review of remaining audit findings — October 31, 2026

## Identity, scope and result

Reviewed requested merged main `00026c758ece2bc41eea88c478cbb0112f9e0de5` using clean worktree HEAD `78591b308aa829a25157bf3310133ed069434d3b`. Independently ran `git rev-parse 00026c75^{tree} HEAD^{tree}`: both are **125b7dc0ee61a890b1dffff40f3b2891df3be9c1**; `git diff 00026c75 HEAD` and source status were empty. Thus these findings apply to that complete merged source tree, not a guessed equivalent revision.

Read source, current AGENTS/checkpoint/canonical context, ingestion/operations/runtime drafts and available public-performance evidence. Independently reaggregated preserved runtime event files and computed the source policy fingerprint using standard-library file reads. No tests/full runs, database access, ingestion, provider calls, production requests, source/test/workflow edits, credential actions or operational commands were executed by this reviewer. This report is outside the checkout.

**Conclusion:** the material source findings are supported, with the qualifications below. No P0/P1 production defect, actual missing filing, runtime deadlock, failed live rollback or deployed policy mismatch was established. New operational findings concern current repository tools/docs and release readiness; they do not certify the installed host configuration. Runtime root cause remains unresolved.

## Ingestion findings independently accepted

### P2 designed recovery/coverage gap — RRC flare rolling submitted-date window

`config/sources/registry.v1.json:27–34` configures three calendar days and explicitly discloses absent historical backfill/older-filing status checks. `rrc_flare_exceptions.py:282–283` computes today minus2 days; `:314–317` submits only those date fields. No last-success acquisition cursor is used by this function. Ordinary adapter dispatch does not substitute an older day. `_reconcile_due` schedule history (`jobs/worker.py:363–435`) creates due obligations; that is not historical acquisition coverage and does not alter adapter date selection.

Independently read the offline reproduction and captured form data: an October1 filing is in the September29–October1 query, while October6 asks October4–6, excluding its later Approved status. Adding prior-success/checkpoint metadata leaves the same dates. This validates requested-window behavior. The mock intentionally models filtering by the form's dates; it does not demonstrate a real publisher response or a missing production record.

Severity P2 is appropriate for the missing autonomous recovery capability. State it as an already documented design limit, not a newly introduced parser regression or an assertion that a specific filing is stale. A filing can still change evidence when reacquired: stable filing identity and mutable status are retained at `:187–191`. Do not infer actual flaring, MW, rental fit, buyer authority or lost revenue from an exception application.

A bounded durable coverage cursor/catch-up lane and separately budgeted retained-ID status monitoring are reasonable follow-on recommendations. Merely widening the recent window does not solve indefinite later status changes. No backfill is authorized by this audit.

### P2 designed recovery/coverage gap — RRC drilling current/prior-month acquisition

`registry.v1.json:80–89` accurately discloses current cumulative daily plus previous-month EOM only. `rrc_drilling.py:508–522` computes exactly one previous EOM and `daf420.dat`; no missed-month archive loop or acquisition coverage cursor is present. The offline reproduction captures September30/current products for October1 and November30/current products for December1, with no October EOM requested. It characterizes selected product windows, not real archive availability or lost wells.

**Important limit on the conclusion:** exact retained-well/completion monitoring does exist. `intelligence/rrc_well_research.py:27–32,151–209,283–300` defines two active jobs,24/day and seven-day refresh; it uses source/registry/feature gates and eligible active retained project identity. This can investigate known wells. It cannot discover a wholly missing project for which no retained identity exists, and actual deployment/enablement/success is unverified. Do not claim that all older corrections are necessarily missed or that no monitoring exists.

Follow-on archive-coverage catch-up must preserve newer-amendment rules and keep inaccessible intervals explicit. Retained evidence is not deleted by snapshot absence. Registry disclosure is accurate; no live outage or specific missing correction was shown.

## Operations findings independently accepted

### O1 — P2 repository helper/current-CLI incompatibility

`stage_release_wrapper.py:138–160` emits `gridlens.jobs.browse rollback --generation ...`, but current CLI `jobs/browse.py:24–40` excludes rollback and exposes stage/inspect/publish recovery. The generator's static allowlist does not express those new guarded actions and rejects arbitrary suffixes. I also inspected stored PR148 `ca12443f` browse CLI: it likewise lacks rollback, so compatibility cannot be assumed merely by naming that prior release. Unit tests asserting the emitted obsolete suffix cannot prove compatibility with actual current CLI.

The pure AST/argparse characterization in `operations/static-validation.json` is consistent with source: rollback is an invalid parser choice. No protected wrapper was rendered, installed or executed here. Classify P2 for current helper/release readiness, **not** failed live host rollback: installed companion, image and CLI are unknown. The explicitly historical October24 plan remains historical evidence, not present authorization.

Do not mechanically replace `rollback` with `publish-recovery`. Recovery requires a fresh stage/receipt, current selected image policy and repeated CAS checks. Preserve protected input identity, operation allowlist and validation when a separately scoped replacement is built.

### O2 — P2 recovery-document promise does not cover current ordinary UI routes

`saved-browse-ingestion.md:40–48` promises canonical fallback by switching API `SAVED_BROWSE_ENABLED=false`; `saved-browse-b1.md:86–87` makes a broad disabled-feature claim. Current project route `api/app.py:2041–2073` unconditionally calls project page; `project_results.py:35` unconditionally selects current generation absent an explicitly supplied one. Current company/group `_cohort` (`customer_results.py:25–30`) does the same. The normal frontend uses those routes. Flag-gated legacy endpoint fallbacks do exist, so a claim that every endpoint lacks fallback would be wrong.

The source-derived sentinel characterization correctly demonstrates the unconditional generation call with the setting false, without claiming to exercise a live endpoint. Current generation must pass pointer/revision/policy/time checks or raises503. An operator following the broad guide can therefore retain unavailable current project/company UI after switching the flag. This is a documentation/recovery-readiness defect, not a demonstrated production outage.

Recommended correction is endpoint-specific recovery documentation, not disabling freshness fences or inventing a new unsafe fallback to satisfy old wording.

### O3 — P2 only if reused for a current release; otherwise a clearly bounded legacy-tool limitation

`rehearse_release.py:24–25` fixes expected and target schema0041. `compare_snapshots:489–492` rejects equal0049 snapshots as unexpected schema transition. The helper also invokes removed rollback at `:523–551` and checks restoration of the captured old generation. Current repo head and latest linked completed receipt are0049.

These are concrete incompatibilities for reuse with the current schema/images. Severity should remain conditional on presenting/reusing the helper as a current readiness gate. Its local-only, explicitly historical documented invocation can remain valid for its exact old images/dump. Do not retroactively invalidate that historical receipt, call the fail-closed refusal a data-loss bug, or claim the actual production restore is broken. A source/image/schema-bound current replacement and isolated prior-image proof are needed before reuse.

### O4 — P3 stale rollout wording

`contact-suppression-rollback.md:11` still says apply the normal new0048 migration, while current head/latest receipt are0049. The rest of that guide correctly describes stage/inspect/publish and explicitly rejects direct rollback. The line should become introduction history plus current-head preflight. It is not proof that Alembic replays applied revisions, that a downgrade occurs or that production is below0049.

## Recovery/policy safeguards: no bypass validated

Independently inspected `saved_browse.py:927–945,1000–1045`: stage inspection/publication compare both input/full revisions **and** active/prepared pointers, runtime policy, digest/integrity, complete nonempty rows and validity/horizon. Publication clears prepared pointer. Thus a receipt staged with activeA/preparedP normally becomes stale after candidate publication changes those pointers even if canonical revisions stay constant. A fresh stage under the selected compatible artifact is required; a captured generation UUID is not sufficient. Idempotent `already_published` is reached only after candidate validity checks and is not an indefinite expiry bypass.

Independently recomputed the checked-in source fingerprint exactly as `_policy_fingerprint`: registry bytes followed by relative names/bytes of sorted backend Python files. Expected suffix is **27851625e924e8bc0e3dede6**, yielding source expectation `browse-b1-v1/ranking-v2-regional-geography/regional-project-scope-v1/27851625e924e8bc0e3dede6`. This is **not** evidence of deployed image contents, runtime policy, DB generation or mismatch. Labels, frontend bytes and equal row counts cannot replace runtime observation.

## Runtime draft independently corroborated; cause still unproven

Reaggregated raw preserved `pr160-runtime-full-20261031/events-gw*.jsonl` using metadata start7296.962309854. Results match the draft:

|Worker|Cases|Summed phase seconds|Last teardown seconds|
|---|---:|---:|---:|
|gw0|518|183.762|189.828|
|gw1|2351|175.009|183.414|
|gw2|397|329.104|335.106|
|gw3|402|311.605|317.630|

Setup337.780s/call603.475s/teardown58.225s are concurrent summed phases; setup+teardown39.621%. At190s,278 cases remained; at317.7s,65 remained. This proves heterogeneous work and a partly occupied passing-run tail. It does not identify assignments/queue lengths or reconstruct the failed run.

Preserved exact-command local run timeout124 at480.095s remains a failed receipt. Instrumented full diagnostic336.98s is a separate passing receipt with added observer/durations flags. Hosted main CI reports3667passed/one intentional skip in346.00s on exact main00026/shared tree; prior local/full and hosted PR passes remain distinct. None explains or erases the failed local run. Original one-second shadow-lock assertion passing unchanged likewise does not prove why its earlier separate failure occurred.

P3 validation observability/efficiency is justified; no product deadlock, accidental live source activity, CPU/storage/lock cause or scheduler fix was demonstrated. Do not change timeouts, isolation, data volumes, durability or test selection based on these measurements. Sparse resource samples and background checkpoint sums cannot be assigned as foreground blocking duration. No new test or diagnostic run was performed for this review.

## Available performance/access evidence and limits

Native browser attempts failed TLS trust through the managed proxy; attempted warm reloads after a failed initial navigation are not valid warm page-load samples. No fresh LCP/CLS/TBT or authenticated interaction timing follows from those errors. HTTP fallback with normal `curl --compressed` succeeds200 for HTML/assets and sessionfalse; protected health/project reads return401. These are public availability/access-boundary observations, not authenticated QA or signed-in API performance.

Available `asset-comparison.json` independently shows public JS422484B SHA431066f1… differs from local candidate JS423022B SHA7b961176…, while unchanged CSS bytes match. State that served JavaScript does not match the locally built candidate artifact; do not use matching CSS to identify a full deployment or infer backend revision. The public script matches the previously observed older asset, but exact entire host deployment remains unverified.

Available fresh JS headers still show no-store/no Content-Encoding on this managed-proxy path. Do not attribute the headers uniquely to origin/Caddy or claim actual browser encoded sizes from curl alone. The finalized performance draft and aggregate timing claims were subsequently checked below.

Connected infrastructure observation reports one active droplet and two backup IDs. Active infrastructure is not application health; backup IDs are not verified app/database restore/retention. A backup-policy API INVALID_ARGUMENT is an unsuccessful parameter lookup, not permission denial. No configured host executor/SSH identity/agent was established; host state, fresh backups, source health and recovery remain unavailable.

## Action state

No denied action, approval request, pending operation or uncertain mutation occurred in this independent review. Remaining uncertainties are evidence limits, especially actual production state and failed-run cause. No source edits or production repairs were made or authorized by this report.


## Final performance delta review

Read `performance/REPORT.md` and all nine raw resource sample metrics in `transport-samples-n3.json`. Independently recomputed medians/ranges: HTML total237.747ms (115.023–361.813), JS225.180ms (184.776–467.066), CSS338.102ms (117.555–355.164); all n=3/status200. TTFB medians237.630/155.673/231.027ms also match. These are three fresh-process public HTTP reads per resource, not browser cold/warm, viewport-specific mobile timings, origin execution times or field percentiles. Auth/session/health/project probes remain n=1 each;401 latency is not authenticated query speed.

The report correctly identifies six failed browser attempts as zero valid native page-load/paint/layout samples, preserves TLS verification, does not blame the origin certificate or claim a successful sign-in screenshot, and leaves authenticated workflows/timing blocked. Received no-store/no-content-encoding headers on the managed proxy path and candidate/public JS mismatch are supported. The delivery layer responsible for those headers and actual deployed backend policy remain unknown. No cache, TLS or deployment change is authorized or implied.

Independent review is complete for all four final scoped reports. No material correction remains requested beyond retaining the explicit conditional severity/coverage qualifications above. No tests, new HTTP requests, DB operations, source edits or production actions were performed by this review lane; final `git status --short` remains empty.
