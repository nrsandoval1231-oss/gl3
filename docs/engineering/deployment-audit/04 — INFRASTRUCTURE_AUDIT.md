# 04 — Infrastructure and Build Audit

Audit date: 2026-10-28
Scope: hosting/deployment artifacts in-repo, compose files, Dockerfiles, CI workflow construction, ingestion/deployment coupling. Production host was **not** touched (read-only mission).

## 1. Where things run

- **CI**: GitHub Actions `ubuntu-latest`, three concurrent jobs per run (see `01 — CURRENT_PIPELINE.md`). No self-hosted runners; queue measured at ~3s.
- **Production**: single DigitalOcean droplet per `docs/operations/README.md` (the authoritative operations doc): immutable prebuilt images under `/opt/gridlens/releases/<tag>`, `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, Infisical-wrapped startup (wrapper identity pinned and staged by `scripts/stage_release_wrapper.py`, command suffix verified as `up -d --no-build`). Cloudflare Tunnel ingress per the (explicitly non-authoritative) `deploy/digitalocean/compose.prod.yaml`.
- **No container registry or CI-to-host artifact channel exists in-repo.** CI builds nothing deployable; release images are built on the host.

## 2. Build caching assessment

| Build | Caching today | Assessment |
|---|---|---|
| CI Python deps | `astral-sh/setup-uv` with `enable-cache: true`; warm `uv sync` median **2s** | Good. Cold-cache runs pay a one-time download; not a bottleneck. |
| CI web deps | `actions/setup-node` with npm cache; warm `npm ci` median **2s** | Good, but the *backend* job also installs web deps + Chromium solely for browser tests — 60–80s of non-backend work on the backend critical path (measured 27s Chromium install + 69s browser run + setup-node/npm ci). |
| `Dockerfile.backend` | Layered correctly: `uv sync --locked --no-dev` for deps **before** copying `src/`; second `uv sync` installs the project after source copy; `UV_COMPILE_BYTECODE=1`, `UV_NO_SYNC=1` at runtime | Sound layering; dependency layer cache-hits when `uv.lock`/`pyproject.toml` unchanged. Host rebuilds are incremental per release tag. |
| `Dockerfile.web` | Multi-stage: `npm ci` before `COPY web ./` (good layer hygiene), then nginx alpine with unused modules removed | Sound. But see §3 — this build duplicates the CI web build. |
| Docker images on host | Immutable per-tag releases retained under `/opt/gridlens/releases/<tag>` | Good rollback posture; exact build/cache timing on host unmeasurable from repo (evidence gap). |

## 3. "Same app built multiple times" — confirmed

The web application is built **at least twice per release**:

1. CI `web` job: `npm run build` (tsc + vite) — ~10–20s of the 24s job (build portion; measured step totals in `02 — DEPLOYMENT_TIMINGS.md`).
2. Host release: `Dockerfile.web` stage runs the identical `npm ci && npm run build` again.

The backend is likewise compiled twice in spirit: CI installs and tests the same dependency tree the host image re-resolves via `uv sync --locked` (deterministic, so this is redundancy rather than risk). There is **no artifact promotion**: the exact bytes CI validated are not what ships. Recommendation: publish CI-built images (or at minimum the web `dist/` bundle) and have the host compose reference immutable tags — build once, promote the artifact (see `05 — OPTIMIZATION_PLAN.md`).

## 4. Startup, migrations, health

- **Migrations**: 48 alembic revisions, DDL-only (no data backfills detected in `migrations/versions`). CI applies them in **1s**; the duplicate `alembic upgrade head` in `ci.yml` (lines 127–130) is pure redundancy (~1s, trivial). Production compose runs `migrate` as a one-shot that `api`/`worker`/`browse` wait on (`service_completed_successfully`) — safe ordering, zero-downtime not proven but migrations are fast DDL.
- **API startup**: plain FastAPI app, no startup ingestion hook found in `src/gridlens/api/app.py`.
- **Health checks**: compose defines a `db` healthcheck (local compose only). **No `HEALTHCHECK` in either Dockerfile and no app-level deploy verification found in-repo.** Host-side verification is an evidence gap; the release rehearsal scripts (`scripts/rehearse_release.py`) evidence local restore/rollback drills, not production deploy gating.
- **Rollback**: retained prior images under `/opt/gridlens/releases/<tag>` + restore rehearsal tooling = good substrate; automated rollback on failed health check is not wired (nothing in CI/CD triggers it — there is no CD).

## 5. Ingestion / deployment coupling (Phase Five verification)

Verified against source, not assumed:

- `worker` (`gridlens.jobs.worker`) is **incremental and checkpoint-based**: `SourceScheduleEpoch.history_known` gating, `history_cursor` progress, fenced leases (`FencedLeaseRenewer`), `SourceCheckReceipt` dedupe, per-job retry budgets (`MAX_COLLECTION_CHAIN_JOBS = 8`). A worker restart resumes from persisted state; it does **not** replay history or trigger full ingestion.
- No "initial ingestion on boot" path exists in `api`, `worker`, or `browse` entry points; no full reseed, no materialized-view rebuilds on deploy (no materialized views exist in the schema).
- Deployment therefore does **not** restart the intelligence pipeline or reprocess history, provided releases keep schema forward-compatible (the operations docs already require proving forward-schema compatibility before rollback — keep that rule).

**Conclusion: ingestion and application releases are correctly separated in the current architecture.** The main coupling risk is *human/process*, not code: a release that ships a schema migration requiring data repair would violate this. The existing migration discipline (DDL-only history, `alembic check` in CI) plus the one-shot `migrate` service preserves it.

## 6. Environment-specific configuration

- CI: all secrets generated ephemerally on-runner (masked Postgres password, session secret, bcrypt hash); external model keys explicitly blanked in browser tests. Clean.
- Production: `.env.prod` / `runtime.env` + Infisical injection; `compose.prod.yaml` documents that compose does not forward host env into `env_file` containers (the Infisical wrapper exists precisely for this). No secrets in repo.
- `browse` service runs with all paid-model keys blanked and daily limits zeroed — defense in depth, good.

## 7. Resource and concurrency limits

- Backend job `timeout-minutes: 20` — **the suite already hits it** (runs 862 and 869 cancelled at 20m02s–20m08s). This is an operational hazard: routine variance (±3 min) now risks timeout kills.
- Brand job timeout 5 min (job takes ~15s — headroom fine).
- No `concurrency:` group in `ci.yml` — repeated pushes each run the full pipeline; observed PR+push pairs double-pay (~34 min runner time per change).
- Playwright forced to `workers: 2` in CI; webServer boots uvicorn + vite inside the backend job (measured within the 69s browser step).

## 8. Evidence gaps (exactly what is missing and what closes it)

| Gap | Why it matters | What is needed |
|---|---|---|
| Host-side build & deploy duration | "Commit → verified production availability" cannot be fully decomposed without it | On-host release receipt timings, or owner-authorized observation of one routine release using the established wrapper |
| Image sizes / layer cache hit rates on host | Quantify redundant rebuild cost | `docker images`, `docker history` on host (read-only) |
| Live health-check/rollback behavior | Confirms protections survive optimization | Host compose.app.yaml content + wrapper logs (already partially evidenced in PR120 release plan docs) |
| Branch protection / required check configuration | Determines which jobs are true release gates | Org/repo settings read access |
