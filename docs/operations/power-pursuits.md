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
PYTHONPATH=backend/src uv run --project backend uvicorn gridlens.api.app:app --host 127.0.0.1 --port 8000 --no-proxy-headers
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


## Autonomous pursuit research candidate

GL3-029 adds `pursuit_question` jobs and migration `0014_pursuit_research_questions`.
It remains a draft candidate. The [five-category regenerated-corpus gates](../validation/gl3-029-five-category-20261007.md) pass locally; historical retained-browser proof and production deployment remain separate. Use isolated validation databases and preserve historical research receipts.

The current worker plans questions at startup and on its hourly refresh when
`worker_auto_refresh` and `autonomous_research_enabled` are enabled. Its shared
read-only projection includes the current 50-card shortlist, other active needs
supported by canonical evaluation, and every saved target outside the shortlist,
including closures and promotions. Needs already represented by a grouped card
are not scheduled twice. It caps active questions at two per pursuit and applies
the daily question cap after discovery.
Authenticated **Research missing facts** schedules the selected card; explicit refresh
bypasses freshness reuse. Unchanged completed questions wait for their category retry
window (24 hours for phase/supply/commissioning/conflicts, 72 for timing, 168 for
buyer/load/power scope). The shorter source-family window also applies (news 24
hours, permits 72). Changed semantic project/evidence, registry configuration or
policy input permits new attempts.
Unexpected question-worker failures use the same 1/6/24-hour bounded retry schedule;
after the final retry the receipt records `RETRIES_EXHAUSTED`. A fifth expired job
lease terminalizes the question and job together. If a provider reservation may have
been dispatched, the receipt retains `UNKNOWN_EFFECT` and automatic or forced
refresh stays blocked until the uncertain effect has a safe disposition.
An initial WATCH may be investigated once. A resolved root question permits one child,
with no further child branching.

Defaults: eight questions per UTC day, three searches, ten candidate URLs, five
retrieved documents, 750,000 bytes per document, 180 seconds and zero model calls
per question. `autonomous_research_daily_questions`, `autonomous_research_max_searches`,
`autonomous_research_max_urls`, `autonomous_research_max_document_bytes`,
`autonomous_research_max_documents`,
`autonomous_research_timeout_seconds` and `autonomous_research_max_cost_usd` bound
execution. Direct retrieval is free of provider search fees. Optional Firecrawl
requires an already configured `firecrawl_api_key`, explicit
`firecrawl_search_cost_usd` reservation ceiling and sufficient per-question cost budget.
Public JavaScript-shell extraction separately requires `firecrawl_scrape_cost_usd`
and an additional document/request reservation; it is not an access-control fallback.
Default cost budget is zero. Reserved cost is not actual billing; actual search cost
is marked unavailable without a provider billing receipt. No provider or credentials
are provisioned by this slice.

Questions first use retained canonical evidence and retained-only buying-chain
projection, then exact registered Austin/Chicago/Seattle/Boston/El Paso/Federal
Register records and eligible existing public pages. Discovery returns candidate URLs only; snippets are not evidence.
Unsupported source routes and provider absence are explicit receipt limitations.
The DNS-pinned public reader rejects private destinations and redirects. Owned
network/parser operations run in a killable child under the same question deadline
and a 512 MiB address-space cap; reservations and all database work remain in the
existing worker. The reader supports HTML/text and PDFs up to 20 pages and 30,000
extracted characters within the wire-byte budget. It rejects the whole input on
excess size, encryption or a page without extractable text; there is no OCR.
Firecrawl extraction is eligible only for a successful explicit public JavaScript
shell, not login/CAPTCHA/denial/error pages or private access. Unsupported native
routes, including form-based RRC downloads and bulk-source research routes, remain
visible as unavailable; they do not become evidence that a fact is false.

Retained canonical facts are checked before acquisition. Complete captured public
inputs may be reinterpreted only with verified original source/observation/evidence
identity, current hashes and one target need. The whole-input hash must match;
partial historical excerpts are not expanded into invented complete documents.
Replay preserves the original evidence identity and retrieval time. Exact registered
hostnames can support public supplements; they do not confer native permit authority.

Receipts retain original context, generated/attempted/completed queries, checked
sources, planned/checked/unavailable/skipped routes, accepted/rejected evidence
citations, before/after disposition, reason,
remaining blockers, recommended action, counts, runtime and cost reservations.
Partial evidence does not imply a resolved blocker. PARTIALLY_RESOLVED requires
progress on a component of that exact question, not an unrelated accepted fact. Missing results are UNRESOLVED,
not evidence of absence. Exhausted leases and failures remain visible. Interrupted
requests with uncertain completion are not automatically repeated. Question status
never assigns a qualification tier; accepted canonical changes go through the same
deterministic evaluator and immutable evaluation receipts.

Read-only metrics: `PYTHONPATH=backend/src uv run --project backend python scripts/pursuit_research_metrics.py`.
Run against the intended database with its existing environment. Counts are receipt
measurements, not a claim that an empty or synthetic database is the retained corpus.
No email, calls, forms, CRM writes, account login or other commercial outreach occurs.
Cloud deployment and production unattended operation remain separate milestones.

The pursuit overview includes research-related changes since local Chicago midnight,
with unique evaluation versions rather than duplicate question transitions. Original
and resulting tiers remain separate from commercial disposition. Exact dated public
reports can answer phase/supply/timing/load questions; they do not independently
qualify a need. Only current admitted official evidence meeting every existing gate
can promote Prospect/Lead, and canonical corrections can demote obsolete support.
A Lead may have explicit nonzero aggregate suitable supply throughout its evidenced
interval. The deterministic residual subtracts maximum supply from minimum demand
(and minimum supply from maximum demand); component totals and suitability are never
invented. The visible Lead floor applies to the remaining need, not campus/nameplate
or gross activity load. Crossing-floor ranges remain uncertain.

For isolated acceptance, see [corpus manifest and validation commands](../../scripts/README-pursuit-research-validation.md).
The runner refuses the original runtime and shared test database, pins its baseline,
checks preserved history, caps aggregate runtime/cost, and never calls fixtures an
original retained corpus. `scripts/seeded_browser_acceptance.py --full-suite` creates a
separate explicitly synthetic browser database through canonical ingestion. Keep
its receipts distinct from real-corpus receipts.

### Fresh regeneration (owner-authorized October 7)

Use `scripts/regenerate_pursuit_corpus.py` and its validation README for bounded native-permit collection, canonical ingestion and isolated backup/restore. Preserve new acquisition dates and hashes; never relabel a new archive as original PR23 evidence. The original recovery requirement is superseded, not passed. Unsupported cohorts remain explicit gaps. Partial diagnostic execution records the full manifest gate rejection and cannot claim five-cohort or retained-corpus acceptance. Keep full source records, credentials and database archives ignored; publish only safe review receipts and source-backed findings.

### RRC retained-native inspection

The autonomous worker can inspect complete native RRC permit bytes already retained
in canonical Evidence. It verifies the accepted interpretation and unique project/need
binding, strict raw hashes/provenance, bounded reconstruction and exact canonical
fields. Receipts retain the original observation timestamp and record inspection time
separately with `retained_native_replay:true` and `network_refresh:false`. No new
Evidence or commercial facts are created. Opaque children remain uninterpreted;
approval alone does not establish drilling underway or a power requirement.

The October 7 owner authorization permitted the existing anonymous public download
POST for corpus regeneration; it did not add an autonomous RRC network research route
or authorize other forms. Missing discovery remains visible, with existing finite
transient retries. Do not present repeated retained inspection as new acquisition.
The live five-category run ended with six UNRESOLVED blockers and no promotions.

### October 7 final local acceptance and public-search permission

All 42 browser workflows and the final fresh five-category gate pass; see [exact counts and limits](../validation/gl3-029-final-acceptance-20261007.md). At 04:30:46 UTC the owner separately approved the existing anonymous TDLR search POST solely for public-record retrieval and conditional merge. This supersedes the earlier RRC-only validation exception for that narrow route, not the prohibition on outreach, login, purchases or arbitrary forms. Browser call notes are explicitly validation-only; no call occurred. Provider configuration/spending and cloud deployment remain separate.
