# Stage2 source-quality reproducibility and resume

This procedure reproduces the frozen local review outputs from the exact Stage2 worktree candidate without issuing source requests. It requires the private ignored evidence/DB snapshots under `.artifacts/STAGE2`; never copy raw exports, authentication files, cookies, or credentials into Git. The original source requests were separately authorized and already completed; do not rerun them as a reproducibility step.

## Identity and runtime

- Repository: `C:/Users/nrsan/Nucleus/02_Projects/GridLens/gl3-stage2-source-quality-20261009`
- Branch: `acceptance/gl3-stage2-source-quality-20261009`
- Code base: `c761e38f6ac00e7d54d6f6b57959cf40cdcf4d79`
- Private original dump: `.artifacts/STAGE2/evidence/preserved-base.dump`, SHA-256 `828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886` (matching preserved source copy also recorded in `.artifacts/STAGE2/evidence/`)
- Isolated PG18: loopback `127.0.0.1:55747`; corpus DB `gl3_s2_corpus`; initial/replay comparison DBs `gl3_s2_after_initial`, `gl3_s2_after_replay`; baseline `gl3_s2_pre_migration`.
- API `127.0.0.1:8073` and Vite `127.0.0.1:5174` were created for this task. Do not stop a process unless controller first confirms ownership and no longer needs it. Current process/browser proof is controller-owned.

PowerShell, repository root:

```powershell
. ./.artifacts/STAGE2/helpers/enable-runtime.ps1
uv run --project backend --locked python -m gridlens.jobs.runtime check --source <source-id>
```

The helper is local-only and supplies blank provider key variables, zero budgets, disabled auto-refresh/autonomous research/JEV, loopback DB URLs, and the private local app hash. It does not expose values. `backend/.env` is inherited worktree material; runtime correctness requires using the explicit helper/environment, not assuming env-file absence. Do not run the source command during reproduction: its six original attempts and replay already have durable private raw logs and manifests.

## Frozen selection and sanitized outputs

Private candidate pool `.artifacts/STAGE2/evidence/full-candidate-pool.b854f043bc20aa5d.private.json` SHA-256 `b854f043bc20aa5dc1d87af3ecd67eedb6b8173d80022f7bd2cb479e3dead52c`; fixed sample SHA-256 `6c29be89fc80ebfe4779c8e4439cefe6c0457db0c1d58b74ffb59b9f2e633ccc`. The pool has 6,448 distinct observations; six records per route were selected by SHA256 UTF-8(`source_id + stable_record_id`) ascending, with present admitted/rejected/ambiguous strata reservation before filling remaining slots. Ties break on stable ID bytes. The procedure was frozen before the first source attempt; controller independently reproduced all 36 IDs and strata. Origin labels mean newly inserted on Stage2 acquisition, content-changed on Stage2 acquisition, or retained baseline. Unchanged refreshed observations remain retained; latest evidence `observed_at` alone does not mark fresh.

Selection helpers are private ignored files:

```powershell
uv run --project backend --locked python .artifacts/STAGE2/helpers/select_fixed_sample.py
uv run --project backend --locked python docs/validation/procedures/stage2-build-public-sample-20261009.py
```

The first command writes private `fixed-sample.private.json` from the current pool and is provided only to reproduce the frozen algorithm; do not overwrite the hash-bound frozen sample for an acceptance rerun. The committed `stage2-build-public-sample-20261009.py` verifies both immutable input SHA-256 values, then emits the sanitized [36-record review JSON](../stage2-review-sample-20261009.json). No personal names, personal telephone numbers, raw source payloads, or raw database dumps are included in that public JSON.

The final supplement helper `select_priority_supplement_final.py` uses the same pool, excludes the fixed 36, requires explicit activity-field scope and a source-listed organization/role, orders data-center first, commissioning/temporary second, generic construction third, then event date descending and bytewise stable keys. Its frozen result at `.artifacts/STAGE2/evidence/priority-supplement-final.private.json` was made at `2026-10-09T21:44:14.294067Z`, SHA `64092165875edfa80ee04ec8bf5b610cba2dad0c0532ad6251bef195a0693824`. Do not overwrite it. Note: its top-level `rule` prose is stale from the earlier generic-date-order implementation; the actual freeze used the executable class-first ordering and IDs unchanged. The corrected public method is [here](stage2-priority-supplement-final-20261009.md); a private correction receipt binds this note to the frozen bytes.

## Replay, source comparison, and data protection

Private replay fingerprints were produced from exact database restores:

```powershell
uv run --project backend --locked python .artifacts/STAGE2/helpers/fingerprint_replay.py
```

It reads only the named comparison databases on port 55747 and fingerprints all-column canonical row content. For an independent replay comparison, restore the private snapshots to new task-owned database names first; never reuse or mutate the 55449 listener, another worktree's database, or the saved source dump. Do not recapture the source pool from a changed DB or repeat bounded original-source requests. Public controller receipts record original-history preservation, 39-table replay, source-original comparisons, current projection and changed-version proof; they are the cross-checks for reported conclusions.

Original-source raw payloads and RRC segments, passwords/session values, authenticated API payloads, and browser screenshots remain ignored/private in `.artifacts/STAGE2`. Builder response status metadata is incomplete: native bounded reader exposes headers/body but not numeric code; RRC flare's first index GET was not captured. Do not infer HTTP status or total request count. Four old flare IDs were not retrievable in this bounded comparison; their fidelity remains UNKNOWN.

## Focused deterministic validation

From the repository root, regenerate and verify the public sanitized sample without contacting official sources:

```powershell
uv run --project backend --locked python docs/validation/procedures/stage2-build-public-sample-20261009.py
uv run --project backend --locked python -c 'import json,pathlib; p=json.loads(pathlib.Path("docs/validation/stage2-review-sample-20261009.json").read_text(encoding="utf-8")); assert len(p["records"])==36; assert len({(r["source_id"],r["stable_record_id"]) for r in p["records"]})==36; assert sum(x["pool"] for x in p["candidate_pool_by_source"].values())==6448; print("PASS: frozen sample shape")'
```

The helper checks hash-bound inputs before writing. The second command checks sample size, uniqueness, and pool total; the report retains the remaining unknowns and failure categories.

## Resuming review

Start from this exact worktree and private evidence. Read the report, fixed sample JSON, final shortlist and controller-owned receipts. Inspect public sanitized judgments first; use ignored original payloads only for specific contested rows. Keep controller browser/API ownership and exact-candidate CI/review separate. Preserve all UNKNOWNs. Any new live request, data migration/write, provider action, source expansion, qualification-policy change, Stage3 task, or deployment lies outside this packet.
