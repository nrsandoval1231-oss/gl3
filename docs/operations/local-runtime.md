# Local runtime and clean-checkout setup

This guide describes a local developer environment. It does not configure production. At the October 20, 2026 packet inspection, `.artifacts/local-postgres/` was absent in this clean worktree, so the ignored database and connection file described in an older receipt were not assumed to exist.

## Prerequisites and isolation

Install Python 3.11, uv 0.7.13, Node.js 22+, npm, and PostgreSQL 18.6. `compose.yaml` uses PostgreSQL `18.6`; the repository test setup expects a loopback PostgreSQL endpoint. Use a new data directory under ignored `.artifacts/`, bind only to `127.0.0.1`, and use port `55439` so it does not collide with a system PostgreSQL service on `5432`. Do not reuse production, retained-corpus, or any existing unrelated database.

If PostgreSQL 18 is installed at the standard Windows path, these PowerShell commands initialize a **new** local cluster. Verify `$pgBin` points to the installed PostgreSQL 18 `bin` directory and that the target directory does not already exist before running `initdb`; never initialize over an existing directory.

```powershell
$pgBin = 'C:\Program Files\PostgreSQL\18\bin' # replace if PostgreSQL is installed elsewhere
$data = Join-Path $PWD '.artifacts\local-postgres\data'
if (Test-Path $data) { throw "Refusing to initialize existing cluster: $data" }
New-Item -ItemType Directory -Force (Split-Path $data) | Out-Null
& (Join-Path $pgBin 'initdb.exe') -D $data -U postgres -A scram-sha-256 -W
```

Start only this cluster on loopback port 55439, then connect as its `postgres` role. The password prompt is interactive; do not put passwords in command arguments or shell history.

```powershell
& (Join-Path $pgBin 'pg_ctl.exe') -D $data -l (Join-Path (Split-Path $data) 'server.log') -o '-h 127.0.0.1 -p 55439' start
& (Join-Path $pgBin 'psql.exe') -h 127.0.0.1 -p 55439 -U postgres -d postgres
```

In the `psql` session, create an application role and two separate databases. `\password` prompts without echoing the value.

```sql
CREATE ROLE gridlens LOGIN;
\password gridlens
CREATE DATABASE gridlens OWNER gridlens;
CREATE DATABASE gridlens_test OWNER gridlens;
\q
```

Create the ignored helper input file `.artifacts/local-postgres/connection.env` with these placeholders replaced by the same URL-encoded password. Keep it private and never commit it:

```text
DATABASE_URL=postgresql+psycopg://gridlens:<URL_ENCODED_PASSWORD>@127.0.0.1:55439/gridlens
TEST_DATABASE_URL=postgresql+psycopg://gridlens:<URL_ENCODED_PASSWORD>@127.0.0.1:55439/gridlens_test
```

Install locked dependencies and let the checked-in helper write ignored `.env` and `.artifacts/local-auth.txt`:

```powershell
uv sync --project backend --locked --extra dev
npm --prefix web ci
uv run --project backend python scripts/setup_local.py
```

`setup_local.py` refuses to overwrite existing local credentials unless `--force` is given. Do not use `--force` unless you intend to rotate them. Its `.env` is read by `backend/src/gridlens/settings.py`; environment variables take precedence over the dotenv file. The generated `.env` and local password are ignored files. Never print, commit, or attach them.

Apply migrations once and start API and web in separate terminals:

```powershell
uv run --directory backend alembic upgrade head
uv run --project backend uvicorn gridlens.api.app:app --host 127.0.0.1 --port 8000 --no-proxy-headers
npm --prefix web run dev
```

For current project/company UI reads, start the retained browse maintainer in its own terminal after migrations, even when `SAVED_BROWSE_ENABLED=false`:

```powershell
uv run --directory backend python -m gridlens.jobs.browse maintain
```

The maintainer only rebuilds retained projections; it does not start the acquisition worker.
The API keeps `SAVED_BROWSE_ENABLED=false` by default for flag-gated legacy paths. Current project/company results always require a valid generation; setting the flag false is not their fallback. Enable it explicitly when validating saved evaluation on legacy routes. The maintainer publishes an initial generation on its ordinary loop; until ready, generation-dependent reads return qualification-pending HTTP503. See the [current recovery procedure](recovery-release.md) for route boundaries and policy/CAS guards.

The browser is at `http://127.0.0.1:5173`; Vite proxies `/api` to the API on port 8000. Use the password in the ignored `.artifacts/local-auth.txt`. The direct Uvicorn command includes `--no-proxy-headers`; do not trust forwarded headers from arbitrary loopback peers.

Starting `python -m gridlens.jobs.worker` with the code default `WORKER_AUTO_REFRESH=true` plans and fetches due sources on startup and hourly. Omit the worker for UI/API development. If starting it for an approved local acquisition, set `WORKER_AUTO_REFRESH=false` first unless you intend its scheduler behavior. It does not establish a cloud schedule or seven production cycles.

For the repository's containerized local stack, use [`setup_compose.py`](../../scripts/setup_compose.py) and `docker compose --env-file .env.compose up`; that Compose network uses `db:5432`, not the native host's `127.0.0.1:55439`. Do not mix `.env` and `.env.compose`. See [runtime configuration](runtime-configuration.md) for code defaults and feature flags.

To stop only the native local cluster, use the same verified `$pgBin` and `$data`:

```powershell
& (Join-Path $pgBin 'pg_ctl.exe') -D $data stop -m fast
```
