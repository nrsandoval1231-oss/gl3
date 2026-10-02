# Today’s Power Pursuits

This view turns retained Austin/RRC Signals into bounded, source-backed qualification actions. It does not establish rental demand or promote evidence tiers. Research, source excerpts, retrieval dates, conflicts and owner call outcomes are saved in the existing PostgreSQL database.

## Open and run

On an existing installation, preserve its environment files, credentials and database volume. Update the checkout, then:

```bash
docker compose --env-file .env.compose up --build -d
```

The existing migration service applies `0010_power_pursuits`. Open **http://localhost:8080/?view=pursuits**, sign in with the existing password, and select **Today’s pursuits**. Docker must run on the same machine as this URL. This command is the existing deployment recipe; Docker deployment was not exercised in this saved executor.

For the current development runtime, open **http://127.0.0.1:5173/?view=pursuits**. Its PostgreSQL/API/Vite/worker processes run inside this executor, not on Nick’s PC. The private password remains in `.artifacts/local-auth.txt`; do not commit it. These addresses are local to the machine running the services.

A native installation uses the existing `.env` and the established PostgreSQL service:

```bash
(cd backend && uv run alembic upgrade head)
PYTHONPATH=backend/src uv run --project backend uvicorn gridlens.api.app:app --host 127.0.0.1 --port 8000
PYTHONPATH=backend/src uv run --project backend python -m gridlens.jobs.worker
npm --prefix web run dev
```

Run the API, worker and web commands in separate terminals. API-origin/cookie settings must match the existing local installation. Do not rerun credential setup over an established database. New installations can use the existing `scripts/setup_compose.py` instructions, but they do not inherit this executor’s researched corpus automatically.

## Research and saved calls

Successful Austin/RRC ingestion queues a research job in the existing worker. **Refresh pursuits** queues the same bounded job manually. Unchanged, fully successful findings are reused for 24 hours with their original retrieval times. Select **Recheck unchanged sources** to retrieve them again. Failed/partial research remains eligible; explicit deferral and failures stay visible. A completed job means the bounded batch finished, not that every source succeeded.

Each batch screens admitted current evidence, selects up to eight Austin and four RRC candidates, makes at most 48 retrieval attempts and four Jev HTTP attempts, and has a 350-second deadline under the existing fenced lease. The Chicago-calendar daily defaults are 160 retrieval attempts and eight model attempts, configurable with `PURSUITS_DAILY_FETCH_LIMIT` and `PURSUITS_DAILY_MODEL_LIMIT`. Every attempted request, including failures/retries, is debited before sending and survives crashes. This acceptance runtime explicitly used 240 retrievals/day to accommodate repeated live validation; counters were never reset. UI shows the actual configured cap and current usage. No money/cost estimate is inferred from request counts.

Official Austin permit identities are re-retrieved. Bounded address searches retrieve up to two official TDLR registrations as **unlinked context**, never automatic project merges. RRC research uses the official current daily file and, when needed, up to two cited historical EOM files per batch. Absence from today’s file does not establish completion; approvals/amendments do not prove a startup date. Corporate roles and buying authority remain unknown without separately retrieved evidence. Permit phone numbers are business routing contacts.

Expand a card to inspect evidence, relationships and unknowns. Save a call note, outcome, next action and follow-up date. Owner entries are attributed separately from public findings and do not change Signal/Prospect/Lead. Failed save retries use the same request identity. **Include dropped pursuits and saved call history** retains access to notes for withdrawn/completed work and pages through the saved history.

## Scheduling and runtime limits

`WORKER_AUTO_REFRESH=true` plans due ingestion at worker startup and hourly thereafter according to registry cadence. Successful Austin/RRC ingestion then queues research. `WORKER_AUTO_REFRESH=false` still processes manually queued jobs and was used during stable browser validation. The worker must remain alive.

`deploy/scheduler.preparation.yaml` is a suspended, undeployed 7:00 a.m. America/Chicago preparation manifest with an example image. It is not evidence of a cloud scheduler. A local PC cannot execute the worker while off, and this executor can pause/restart. Durable hosted daily operation, cloud deployment and PC-off scheduled acceptance remain open.

No Jev credential was configured in this runtime. Deterministic screening and official live retrieval work; optional Jev decisions are explicitly unavailable rather than manufactured. Corporate retrieval access remains constrained, so no current employment/title, project assignment or purchasing authority is claimed for permit people. No paid enrichment subscription, email guessing, outbound call or external message was used.

## Evidence graph and EvidenceJudge shadow

Project state and accepted material changes are available through the authenticated project APIs. EvidenceJudge is an independent, zero-authority shadow comparator; it does not feed the existing Signal adjudication, admission, tier, power math or research queue. `JEV_ENABLED=false` disables it by default and `JEV_SHADOW_MODE=true` is the required safety mode. Setting both flags does not schedule evaluations: only an explicit operator command can call the provider. The shadow path uses a maximum batch of 20, a maximum of 20 daily persisted attempts, and an overall bounded timeout. Each request reservation is retained before network I/O; an interrupted PENDING result is not automatically retried.

Use the dedicated `*_test` database for deterministic tests; use only the controller-designated retained acceptance clone for real-data shadow runs. `scripts/evidence_judge_shadow.py --mode offline` reads existing records only. `--mode runtime-live` is an explicit bounded shadow run over retained accepted evidence; `--mode benchmark-live --limit 16 --results <path>` evaluates the versioned real/synthetic fixture set and saves each attempt before requesting. `--mode benchmark-offline-results --results <path>` scores saved outcomes without provider calls. Live modes require both flags and `TYPESAFE_API_KEY` in the process environment. Do not put the key in the command line, fixture, report or committed environment file. The fixture descriptions are summaries, not verbatim excerpts; synthetic cases remain fixture-only and are not persisted as evidence or discoveries.

The TypeSafe request/response contract was checked against the official [OpenAPI document](https://api.typesafe.ai/openapi.json), snapshot SHA-256 `A191F8A7DF6BD6FEDCED8120DD0FD106F88575D1D1C8360D08900A6C7C0360D5`. Provider judgments and deterministic `research_recommended` are advisory and stored separately from accepted domain state. Missing facts and contradictions remain UNKNOWN; no outreach, task enqueue, source retrieval or tier change follows the recommendation.
