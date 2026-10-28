# 02 — Deployment Timings: Historical Measurements and Statistics

Audit date: 2026-10-28
Evidence: GitHub Actions run data for runs 856–877 (21 completed CI runs with job/step metadata) retrieved 2026-10-28 via the public REST API. Run URLs are listed per run below. Local reproduction timings (sandbox, isolated environment) are labeled as such.

## 1. Per-run measurements

Queue = run `created_at` → backend job start. Durations are job wall time from the GitHub Actions job API.

| Run | Event | Conclusion | Queue | Backend job | Web job | Brand job | Total (created→updated) | Link |
|---|---|---|---|---|---|---|---|---|
| 877 | push | failure | 4s | 15m32s | 21s | 12s | 15m36s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40610799636 |
| 876 | pull_request | success | 8s | 15m39s | 26s | 14s | 15m47s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40587940481 |
| 875 | push | success | 3s | 11m40s | 31s | 11s | 11m43s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40587931120 |
| 874 | pull_request | success | 3s | 18m48s | 24s | 14s | 18m51s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40583725394 |
| 873 | push | success | 4s | 14m32s | 23s | 15s | 14m36s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40583644146 |
| 872 | push | success | 5s | 13m02s | 26s | 11s | 13m07s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40565271621 |
| 871 | pull_request | success | 2s | 12m25s | 37s | 26s | 12m27s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40561751032 |
| 870 | push | success | 3s | 18m18s | 26s | 13s | 18m21s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40561741935 |
| 869 | push | cancelled | 4s | 20m02s | 26s | 10s | 20m06s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40558300137 |
| 868 | pull_request | success | 3s | 16m01s | 19s | 23s | 16m04s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40554300816 |
| 867 | push | success | 2s | 19m22s | 22s | 18s | 19m24s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40554292707 |
| 866 | pull_request | success | n/a | n/a (jobs API returned no detail) | — | — | 18m49s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40551247597 |
| 865 | push | success | 3s | 18m07s | 24s | 21s | 18m12s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40551239674 |
| 864 | pull_request | success | 5s | 18m54s | 17s | 16s | 18m59s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40550670993 |
| 863 | push | success | 4s | 15m22s | 27s | 19s | 15m26s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40550661919 |
| 862 | pull_request | cancelled | 3s | 20m08s | 29s | 14s | 20m12s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40549414646 |
| 861 | push | success | 4s | 17m37s | 26s | 28s | 17m41s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40549337013 |
| 860 | pull_request | success | 3s | 17m35s | 22s | 13s | 17m37s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40467165704 |
| 859 | push | success | 7s | 14m48s | 21s | 10s | 14m51s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40467160317 |
| 858 | pull_request | failure | 5s | 15m28s | 20s | 12s | 15m31s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40466436825 |
| 857 | push | success | 3s | 17m43s | 17s | 10s | 17m46s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40466431693 |
| 856 | pull_request | success | 4s | 17m06s | 17s | 13s | 17m10s | https://github.com/nrsandoval1231-oss/GL3/actions/runs/40464646705 |

## 2. Statistics (n = 21 runs with job detail)

| Metric | Total pipeline | Backend job |
|---|---|---|
| Median | **17m10s** | **17m06s** |
| P90 | 19m24s | 19m22s |
| Minimum | 11m43s | 11m40s |
| Maximum | 20m12s | 20m08s |
| Queue (median / max) | 3s / 7s | — |

- **Pytest share of backend job: median 826s of ~1,026s = 81%** (step-level, 21 runs). Min 556s, max 907s.
- **Web job: 24s median (17–37s). Brand job: 15s median (10–28s). Both are noise on the critical path.**
- Failures/cancellations: 4 of 22 (18%) — run 877 failure, 858 failure, 862/869 **cancelled at the backend 20-minute timeout** (20m02s–20m08s backend duration). The cancellations are timeout kills, not user cancels: the suite's slow tail sits on the timeout boundary.
- There is **no queueing problem** (median 3s) and **no runner-init problem** ("Set up job" ≈ 1s). The time goes to in-job execution.
- There is **no outlier pattern**: the distribution is consistently slow (IQR ≈ 14.5–18.2 min), not occasionally catastrophic. The variability (11m40s–20m08s) tracks pytest duration (556–907s).

## 3. Step-level breakdown (backend job, medians over 21 runs)

| Step | Median | Min | Max |
|---|---|---|---|
| `pytest tests` | **13m46s** | 9m16s | 15m07s |
| `mypy src` | 1m05s | 0m29s | 1m20s |
| Browser regressions (`npm run test:ci`) | 1m09s | 0m00s* | 1m20s |
| Chromium + system deps install | 27s | 0s* | 2m14s |
| Start ephemeral Postgres | 12s | 9s | 20s |
| uv sync / pip-audit ×2 / ruff ×2 / alembic ×3 / hash / npm ci | each ≤ 7s | | |
| `alembic upgrade head` (×2 in file) | 1s each | | |

\* Zero-minute values are step-timestamp granularity artifacts on fast runs; treated as measurement noise, not real zeros.

Evidence run **40587940481** (PR run, success): pytest 12m20s, mypy 45s, browser 68s, Chromium 35s, Postgres 12s — matching the preliminary inspection in the mission brief.

## 4. Local reproduction (isolated sandbox environment, labeled local — NOT CI)

Environment: sandbox container, Python 3.11 via uv (locked), embedded PostgreSQL (pgserver binaries) on 127.0.0.1:5432, repo checkout `b428c07`. 18 local failures are environment-skew artifacts (Postgres 15 vs CI's 18.6, and host-specific Infisical test) — **CI runs are green**; timings below are valid for profiling.

| Measurement | Result |
|---|---|
| Full suite serial (`pytest tests -q --durations=60`) | **1,028s** (3,272 passed, 18 env-skew failures, 3,292 collected) |
| Unit tests only, serial | 43.5s → integration ≈ **985s for 842 tests** |
| Representative integration module (`test_saved_browse.py`, 117 tests) | 128.8s ≈ **1.10s per test**, of which setup/teardown schema rebuild ≈ 0.9s (see `03 — PYTEST_BOTTLENECKS.md`) |
| `Base.metadata.drop_all + create_all` (73 tables) | **0.46s** (median of 5, warm) |

## 5. Missing evidence (explicitly marked)

- **Host-side deployment duration**: no access to the production host; `docs/operations/README.md` states deploy/rollback commands are unverified. Time from "CI green" to "verified production availability" is **unknown**. Required to close: on-host release receipt timings or owner-authorized observation of a routine release.
- **Run 866 job detail**: GitHub jobs API returned no per-job payload at fetch time; only total elapsed (18m49s) recorded.
- **Branch protection / required checks**: not visible via repository contents; requires org settings access.
