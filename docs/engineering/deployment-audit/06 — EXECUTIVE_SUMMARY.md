# 06 — Executive Summary: Why GridLens Deployments Are Slow

Audit date: 2026-10-28 · Repository `nrsandoval1231-oss/GL3` · Read-only investigation, no production changes.

## The short version

Deployments are slow because **one monolithic CI job — dominated by the Python test suite — gates everything, and the test suite spends over half its time rebuilding the same 73-table database schema before and after nearly every test.** Nothing about the slowness is mysterious, and ingestion is *not* the problem: the intelligence pipeline is correctly decoupled from releases.

- **Current deployment (CI) time: median 17m10s, P90 19m24s** (21 measured runs; queue ≈ 3s, so CI wall time is the gate).
- **Primary root cause: pytest = 81% of the backend job (median 13m46s)**, of which ~54% is measured per-test schema drop/create overhead (~556s per run).
- **Secondary bottlenecks (measured):** browser regressions + Node/Chromium forced into the backend job (~110–140s); mypy (65s); no path filtering (a web-only change pays the full 17 minutes); no concurrency control (repeated pushes double-pay CI); backend timeout kills on slow days (2 cancelled runs at 20m+).

## Before → after architecture

```
BEFORE (measured, median 17m06s critical path)
─────────────────────────────────────────────────────────────
 every push/PR, any file
   └ backend job (one runner, everything serial)
        postgres → deps → audits → ruff → mypy ─→ pytest 13m46s
                                                  ─→ npm ci → chromium → browser 1m45s   [critical path]
   └ web job 24s      (irrelevant, parallel)
   └ brand job 15s    (irrelevant, parallel)
 merge → manual host release (unmeasured; rebuilds what CI built)

AFTER (target, ≈ 3m35s–5m05s critical path)
─────────────────────────────────────────────────────────────
 push/PR, filtered by path
   ├ backend job: postgres → deps → audits → lint → mypy → pytest-xdist (4 workers, per-worker DB)  ~2–3.5m
   ├ browser job (parallel): node → chromium → playwright regression      ~1.5m   ┐ concurrent
   ├ web job (parallel): npm ci → audit → typecheck → build               ~0.5m   ┘
   └ brand job (parallel, brand paths only)                               ~15s
 merge → CI-built artifact promoted to host (build once, deploy tag)  [phase 2 of plan]
```

## Biggest causes, ranked by measured impact

1. **Per-test schema rebuild in integration tests** — 604 of 842 integration tests each drop and recreate all 73 tables (~0.92s setup+teardown each ≈ **9m16s of every 13m46s pytest run**, measured via micro-benchmark and per-module timing).
2. **Serial execution with a single shared test database** — proven locally: naïve `-n 4` produces 46 failures from schema races. Isolated per-worker databases unlock an estimated 3–4× on top of fix #1.
3. **No change-type separation** — a one-line frontend change waits 17 minutes for Python tests it cannot affect (measured floor).
4. **Browser stack inside the backend job** — ~110–140s of frontend-only work sequenced after pytest (measured).
5. **Process gaps** — duplicate `alembic upgrade head`, no `concurrency:` cancellation, 20-minute timeout already being hit.

## What is *not* broken (verified)

- **Ingestion independence:** the worker resumes from checkpoints/fenced leases; restarts don't replay history; no reseed or materialized-view rebuild on deploy. Releases and the intelligence pipeline are correctly separated — keep it that way.
- **Dependency caching:** warm uv/npm installs are ~2s; not a bottleneck.
- **Dockerfile hygiene:** both images are layered sanely with retained immutable releases for rollback.
- **Security gates:** pip-audit/npm audit, network guards in tests, ephemeral CI secrets — all sound and all preserved in the plan.

## Recommended corrective actions (top five)

1. Replace per-test `drop_all/create_all` with per-test data reset against a persistent schema (~550s/run, measured mechanism).
2. Add pytest-xdist with per-worker test databases (~3–4× on integration, estimated).
3. Path-filter workflow triggers so frontend changes run web+brand jobs only (~16 min → ~1 min for web-only, measured).
4. Extract browser regressions into a parallel CI job (~110–140s off the critical path, measured).
5. Add concurrency cancellation + remove the duplicate migration step + raise the timeout safety valve (hours of work, stops timeout kills and duplicate runs).

**Expected result:** backend-path CI ≈ 4–5 minutes, frontend-path CI ≈ 1 minute (vs. 17m06s median today) — **~72–94% reduction depending on change type** — with every existing test, audit, and release protection intact, and a build-once/artifact-promotion path as the follow-up phase. Full evidence and the step-by-step plan: `01`–`05` in this directory.

## Known unknowns

Time from "CI green" to "verified production availability" cannot be measured from the repository — host-side release is manual and its duration was not observable without production access (see `04 — INFRASTRUCTURE_AUDIT.md`, §8 for exactly what closes this gap). All CI-side figures above are measured, not assumed.
