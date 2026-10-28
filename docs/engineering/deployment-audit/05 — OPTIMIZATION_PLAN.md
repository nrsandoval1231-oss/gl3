# 05 — Optimization Plan: Prioritized Roadmap with Quantified Savings

Audit date: 2026-10-28. All "current cost" figures are measured (see `02 — DEPLOYMENT_TIMINGS.md`, `03 — PYTEST_BOTTLENECKS.md`). Savings labeled *measured* come from local reproduction of the exact mechanism; *estimated* figures are conservative extrapolations and say so.

## 1. Ranked optimization table

| # | Finding | Evidence | Current cost | Proposed fix | Estimated savings | Risk |
|---|---|---|---|---|---|---|
| 1 | Per-test full schema rebuild in integration fixtures | 44/78 modules drop+create 73 tables per test; micro-benchmark 0.46s ×2 ×604 tests | ~556s of every run (measured overhead) | Per-test data reset (`TRUNCATE ... CASCADE` in rollback-able transaction) against persistent per-worker schema; DDL-sensitive tests keep isolated path | **~500–550s (measured mechanism)** → pytest ≈250–330s | Low — no test weakened; isolation must be verified per test |
| 2 | Serial-only execution; single shared test DB blocks parallelism | xdist experiment: `-n 4` on one module → 46 failures from schema races; unit `-n 4` ≈ no gain | integration ~985s serialized | pytest-xdist `-n 4` + per-worker DSN (`gridlens_test_gw{N}`) created in session conftest | **integration 250–330s → ~80–140s (estimated from measured 0.92s/test overhead removal + worker scaling)** | Medium-low — deterministic isolation required; flakes must be driven to zero |
| 3 | No path filtering: every change type pays the full backend job | `ci.yml` `on: push/pull_request` with no `paths:`; web-only change floor = 17m06s median | 17m for a 1-line web change (measured floor) | Path-filtered triggers: `web/**` → web+brand jobs only; `backend/**` → backend; `tools/brand/**` → brand; full run when workflows/lockfiles change or on main | Web-only changes → **~1m (measured: web 24s + brand 15s, concurrent)**; backend-only changes unchanged | Low — misses are impossible by construction if lockfile/workflow paths always trigger full CI; PR runs keep full suite pre-merge |
| 4 | Browser regressions + Node/Chromium inside backend job | measured: Chromium 27–35s + browser run ~69s + setup-node/npm ci ~5s, sequential after pytest | ~110–140s on critical path | Move to parallel `browser` job (own runner, own Postgres+backend stack, reusing CI compose patterns already in `ci.yml`) | **~110–140s (measured)** off backend job; browser job runs parallel to pytest | Low — same tests, same environment, just concurrent |
| 5 | Same commit built in CI and again on host; no artifact promotion | web built in CI `web` job AND in `Dockerfile.web` at release; no registry/promotion path exists | host build time unmeasurable (gap); duplicated compute per release | Build backend image + web bundle in CI, push to registry (or host-scp for single-droplet), compose references immutable tag; deploy = pull + migrate one-shot + up | Eliminates duplicate build (est. several minutes/host release; **estimate — host timing is an evidence gap**) | Medium — introduces a registry/channel; keep the current wrapper flow as fallback; no new paid services needed (GHCR free tier or existing droplet as registry) |
| 6 | Duplicate `alembic upgrade head`; web npm ci in backend job | `ci.yml` lines 127–130; step list | ~3–5s + maintenance confusion | Delete second upgrade; drop web npm ci once #4 lands | ~5s (measured) | Very low |
| 7 | No concurrency control; repeated pushes double-pay CI | observed PR+push pairs both running full 17m pipelines | ~17m wasted runner time per duplicate push | `concurrency: group: ci-${{ github.ref }}` with `cancel-in-progress: true` (PRs), `false` on main | Removes duplicate work; no wall-clock gain for the kept run | Low — never cancels main-branch runs |
| 8 | Backend timeout 20m is within observed variance of suite | runs 862/869 cancelled at 20m02s–20m08s | timeout kills on slow days | Short-term: raise to 30m as safety valve. Long-term: moot after #1–#4 (suite ≈ 2–3 min) | Prevents false-timeout failures | Very low |
| 9 | Extended regression placement | `publication-diagnostic.yml` exists as precedent; Playwright live/commercial-real projects need retained data | runs on every push today (part of the 69s browser step) | Keep browser regression mandatory on PR; move live-acceptance/commercial-real to nightly schedule + pre-release manual trigger | ~0–30s on PR path (measured small) | Low — risk-managed per existing project separation |

## 2. The five highest-value improvements

1. **#1 Fixture reset instead of schema rebuild** — largest single win (~550s, measured mechanism), pure test-infrastructure change, no test semantics touched.
2. **#2 xdist with per-worker databases** — multiplies the post-#1 suite (~3–4× on integration, estimated); unblocks fast feedback.
3. **#3 Path-based workflow triggering** — makes the stated mission target (frontend changes in minutes) real for the cheapest change class (~16 min → ~1 min for web-only, measured).
4. **#4 Browser tests as a parallel job** — ~110–140s measured off the critical path; also halves the backend job's dependency surface.
5. **#7 Concurrency cancellation** — cheapest possible change (3 lines); stops the observed double-payment and protects the 20m timeout (#8).

(#5 artifact promotion is architecturally important but ranks below the five above on effort/risk-adjusted value for a single-droplet setup; pursue after 1–4 are stable.)

## 3. Expected deployment time after the top five

Critical-path arithmetic (only serial dependencies counted; parallel jobs don't add):

| Stage | Today (measured median) | After #1–#4, #7–#8 |
|---|---|---|
| Queue + runner init | ~5s | ~5s |
| Postgres + uv sync + audits + ruff + mypy + migrations | ~1m30s | ~1m30s |
| pytest (serial → fixture-reset → xdist) | 13m46s | **~2m00s–3m30s (estimate; components measured)** |
| (parallel, not on critical path) browser job | 1m09s within backend job | runs concurrently |
| **CI total** | **17m06s** | **≈ 3m35s–5m05s** |
| Web-only change CI total | 17m06s (same monolith) | **≈ 45s (measured jobs: web 24s + brand 15s)** |
| Host-side deploy | unknown (evidence gap) | unchanged by this plan; #5 addresses separately |

**Realistic targets vs. mission goals:** routine frontend change ≈ 1 min CI + host deploy — comfortably inside the 2–5 min goal once host deploy is artifact-based; backend change ≈ 4–5 min CI. Savings vs. today: **≈ 12–13.5 minutes (~72–79%) per backend-path deployment, ~16 minutes (~94%) per frontend-path deployment.**

## 4. Safe, incremental implementation sequence

1. **Week 0 (hours):** #7 concurrency group, #8 timeout bump, #6 duplicate-step cleanup. Zero behavioral risk.
2. **Week 1:** #1 fixture-reset refactor, one module at a time, full suite green on each; then flip globally. Add a CI assertion that suite time < 8 min to prevent regression.
3. **Week 1–2:** #2 per-worker DSN conftest + `-n 4`; drive flakes to zero over several days of PR traffic; then #4 browser job extraction (reuses the same Postgres-bootstrap pattern).
4. **Week 2:** #3 path filters, with an escape hatch: changes to `uv.lock`, `package-lock.json`, workflows, `config/`, or `migrations/` always run the full suite; PRs to main always run the full suite regardless of path (so the merge gate never weakens).
5. **Week 3+ (after CI stable):** #5 artifact promotion as a separate reviewed change, with the existing host wrapper retained as fallback. #9 nightly extended regression.

**Validation criteria per step:** (a) full suite green before/after with identical pass counts — 3,292 collected locally; (b) no test deleted, skipped, or weakened (diff of test collection must be empty); (c) timing improvement confirmed by at least 5 subsequent CI runs; (d) production health checks and rollback path untouched until #5, which keeps the wrapper flow as fallback.

**Explicit non-goals:** no new paid services, no test deletion, no removal of security checks (pip-audit/npm audit stay on every full run), no production infrastructure modification during implementation.
