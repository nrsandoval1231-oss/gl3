# Runtime configuration

This page summarizes defaults defined by `backend/src/gridlens/settings.py`. That file is the authority; `.env.example`, Compose files, and old deployment pages are templates or preparation and can differ. Environment variables override the root `.env` file. Names below are the uppercase environment names accepted by Pydantic Settings.

## Required and local connection settings

`DATABASE_URL`, `APP_PASSWORD_HASH`, and `SESSION_SECRET` are required by the settings model and have no defaults. `TEST_DATABASE_URL` defaults to empty, but integration checks require it to point at a separate disposable database. The native local setup uses `127.0.0.1:55439` with databases `gridlens` and `gridlens_test`; the Compose network uses `db:5432`. See [local runtime](local-runtime.md).

## Main safety and feature defaults

| Setting | Code default | Effect |
|---|---|---|
| `COOKIE_SECURE` | `true` | Secure-only session cookie. Local HTTP setup writes `false` into the ignored local `.env`. |
| `TRUSTED_ORIGINS` / `TRUSTED_PROXY_CIDRS` | empty | No configured browser origin or trusted proxy network. Configure only for the intended deployment topology. |
| `WORKER_AUTO_REFRESH` | `true` | Worker plans due source work at startup and hourly. Starting a worker can retrieve enabled due sources. |
| `SCHEDULE_TIMEZONE` / `SCHEDULE_ANCHOR_TIME` | `America/Chicago` / `07:00:00` | Local-daily schedule timezone and anchor. These do not prove a deployed scheduler. |
| `MONITORING_ENABLED` | `false` | Scheduled monitoring planner is disabled unless explicitly enabled. |
| `SAVED_BROWSE_ENABLED` | `false` | Saved browse publication is disabled unless explicitly enabled. |
| `INTELLIGENCE_MODE` | `disabled` | Intelligence routing mode. |
| `INTELLIGENCE_ENABLED`, provider enables, `JEV_ENABLED` | `false` | Provider/model work is disabled by code default. API keys are optional `SecretStr` values; key presence is not connectivity or authorization. |
| intelligence call/cost limits | `0` | Zero limits fail closed. Configure only within separately authorized budgets. |
| `INTELLIGENCE_ENABLED_CONTRACTS` | empty | No contract is allowlisted by default. |
| `JEV_SHADOW_MODE` | `true` | Shadow behavior flag; Jev itself still defaults disabled. |
| `POWER_NEED_TITLES_ENABLED` | `false` | Optional title enrichment disabled. |
| `BRIEFS_DAILY_REQUEST_LIMIT` | `8` | Daily brief request cap; this cap does not by itself authorize provider use. |
| `PURSUITS_DAILY_FETCH_LIMIT` / `PURSUITS_DAILY_MODEL_LIMIT` | `160` / `8` | Pursuit research fetch and model caps; provider and research feature gates remain separate. |
| `AUTONOMOUS_RESEARCH_ENABLED` | `true` | Research planner feature default; public buying-chain research separately defaults false and provider keys/cost configuration still matter. Verify all gates before starting a worker. |
| `BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED` | `false` | Public buying-chain research disabled. |
| `INTELLIGENCE_OCR_ENABLED` | `false` | OCR path disabled. |
| `NTFY_URL` / `NTFY_TOKEN` | empty | No alert destination or token configured by default. |

The October 20 host snapshot reported different explicit runtime flags and budget values; those point-in-time settings are recorded in the [observation receipt](observations/2026-10-20-production-readonly.md). Do not infer production configuration from code defaults or this table.

## Environment files

- Native local runs: `scripts/setup_local.py` writes ignored root `.env` and `.artifacts/local-auth.txt`. It reads ignored `.artifacts/local-postgres/connection.env` unless `--use-environment` is supplied.
- Local Compose: `scripts/setup_compose.py` writes ignored `.env.compose` and `.artifacts/compose-auth.txt`; invoke Compose with `--env-file .env.compose`. Compose uses container DNS name `db`.
- Production: the October 20 observation reported `/etc/gridlens/runtime.env`, with a secret-manager injection context. Its approved wrapper and exact environment assembly are UNKNOWN. Never copy production values into a repository file or print them.

Current code defaults are not deployment instructions. The old `deploy/digitalocean/` secret/deploy material is preparation only; use the [operations authority](README.md) for production status and open command gaps.
