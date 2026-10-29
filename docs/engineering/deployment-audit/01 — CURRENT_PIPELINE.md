# 01 — Current Pipeline: Actual Deployment Architecture and Release Critical Path

Audit date: 2026-10-28
Scope: `nrsandoval1231-oss/GL3` @ `b428c07` (main)
Method: read-only inspection of repository workflows, deployment artifacts, worker/API source, plus measurement of the 21 most recent CI runs (see `02 — DEPLOYMENT_TIMINGS.md`).

## 1. What actually exists

### Automated CI: `.github/workflows/ci.yml` (the only active gate)

Triggers: **every push to every branch, every pull request, no path filters.** The following auxiliary workflow existed at the audit baseline and was not release-relevant (archived during the October 29 cleanup):

- The former branch- and path-pinned PR87 diagnostic is archived at [publication-diagnostic.yml](../../validation/archive/pr87-publication-diagnostic/publication-diagnostic.yml), with its helper script beside it. It was not part of the release path and is no longer an active workflow.
- No deployment workflow exists in GitHub Actions. There is **no automated CD**: no `workflow_run` deploy job, no container registry push, no hosting-provider deploy step. Production release is a host-side manual procedure (Section 3).

`ci.yml` defines three jobs that all start simultaneously on ubuntu-latest runners:

| Job | What it does (sequential within the job) | Measured duration (median, 21 runs) |
|---|---|---|
| `backend` | Postgres 18.6 container start → uv sync → pip-audit (backend + brand tool) → bcrypt password hash → ruff check/format → mypy (65s) → `alembic upgrade head` **twice** → `alembic check` → create test DB → **pytest (median 826s = 81% of job)** → setup-node → `npm ci` (web) → Chromium + system deps install → Playwright browser regressions (~69s) | **17m06s** |
| `web` | checkout → setup-node (cached) → `npm ci` → `npm audit` → `tsc` typecheck → vite build | 24s |
| `brand-assets` | checkout → uv venv → install brand tool deps → `tools/brand/validate.py` | 15s |

Jobs have no `needs:` — they run concurrently, so the **release critical path is the `backend` job alone**. Queue delay measured at median 3s (max 7s), so CI wall time ≈ backend job duration.

### Release critical path (measured, median)

```
push / PR
  ├─ backend job ───────────────────────── 17m06s  ← CRITICAL PATH
  │    ├─ Postgres + deps + audits + lint + mypy   ~1m30s
  │    ├─ pytest tests                             13m46s  (81%)
  │    └─ node + Chromium + browser regressions    ~1m45s
  ├─ web job (npm ci/audit/typecheck/build)          24s
  └─ brand-assets job                                15s
merge to main
  └─ manual host-side release (Section 3) — duration UNKNOWN (evidence gap)
```

## 2. Answers to the Phase One checklist

1. **What triggers a deployment?** Nothing automatic. CI passes are the only automated gate. Production release is a manual host procedure per `docs/operations/README.md`.
2. **Workflows on commits/PRs/merges/manual:** `CI` on all pushes and all PRs (push to main included). No manual triggers anywhere.
3. **Mandatory before production:** none enforced mechanically. The only checks that exist are the three CI jobs; there is no branch protection evidence in-repo and no deploy workflow that consumes them.
4. **Sequential vs concurrent:** the three jobs are concurrent; everything inside `backend` is strictly sequential, including checks that do not depend on each other (linters, audits, migrations, pytest, browser tests).
5. **Rebuild/reinstall of unchanged things:** every run reinstalls the full Python dev environment, the full web `node_modules`, and Chromium from scratch (uv/npm caches mitigate partially: median `uv sync` step is only 2s warm). `alembic upgrade head` runs twice back-to-back (lines 127–130 of `ci.yml`), duplicating the migration.
6. **Duplicated across CI and hosting:** the web app is built at least twice per release — `npm run build` in the `web` job and again inside `deploy/Dockerfile.web` on the host at deploy time. The backend image is built on the host via compose; CI never builds or publishes a deployable artifact, so nothing CI-verified is promoted as-is (no artifact reuse).
7. **Ingestion during deployment:** no ingestion runs in CI. In production, compose defines `migrate` (one-shot alembic) gating `api`, `worker`, `browse`. The worker is checkpoint/lease-based and incremental (history cursors, fenced leases, `SourceCheckReceipt`s); a restart does not replay history (verified in `src/gridlens/jobs/worker.py`; see `04 — INFRASTRUCTURE_AUDIT.md`).
8. **Production releases waiting for unrelated jobs:** there is no automated release, so nothing waits. If a release were gated on CI, it would wait on the monolithic backend job for every change type (a brand-asset-only change runs the full backend suite today).
9. **Repeated pushes:** no `concurrency:` block exists in `ci.yml`. Runs do not cancel superseded ones; pushes queue independent runs (observed: runs 856–877 include PR-then-push pairs for the same change, each paying the full ~17 minutes). Two observed cancellations (runs 862, 869) were 20m+ jobs killed at the backend `timeout-minutes: 20` boundary, not concurrency cancellation.
10. **Deployment before availability:** unknown — host-side health verification is not observable from the repository (evidence gap; see `04 — INFRASTRUCTURE_AUDIT.md`).

## 3. Production hosting (as documented, not modified)

Per `docs/operations/README.md` and `deploy/README.md` (authoritative for this audit; the `deploy/digitalocean/` folder is explicitly "alternate preparation only"):

- Host layout observed 2026-10-20/24: prebuilt immutable images under `/opt/gridlens/releases/<tag>`, `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, Infisical-protected startup wrapper (SHA-pinned, staged by `scripts/stage_release_wrapper.py`).
- Services: `migrate` (one-shot) → `api` (uvicorn), `worker` (scheduler/ingestion), `browse` (maintenance, model keys blanked), `web` (nginx).
- Rollback/restore rehearsal tooling exists locally (`scripts/rehearse_release.py`) but deploy/rollback commands are explicitly "not verified".
- systemd timers exist for alert/backup/collect — ingestion cadence is host-managed, independent of app releases.

## 4. Key structural findings

1. **CI is the release critical path and pytest is 81% of it.** Deployment slowness is, to the extent measurable from the repository, CI slowness: median 17m06s backend job of which 13m46s is pytest.
2. **No change-type separation.** A one-line frontend change runs PostgreSQL, 3,292 Python tests, mypy, pip-audit and browser regressions. The measured floor for a web-only change today is the full 17 minutes.
3. **No build-once artifact flow.** CI builds nothing reusable; the host rebuilds the backend image and the web bundle at release time. The same commit is built at least twice (CI web build + host Docker build) with no promotion of the CI artifact.
4. **No concurrency control.** Every push spins a full run; same-change PR+push pairs double-pay CI (~34 min of runner time per change observed).
5. **Two cancelled runs** at exactly the 20-minute backend timeout show the suite is within ~3 minutes of the timeout ceiling on slow days (max observed 20m08s) — the pipeline is not just slow, it is near its failure threshold.
