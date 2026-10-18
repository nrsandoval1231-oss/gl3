# Intelligence integration — execution record

Owner: full A–G build request, October 18, 2026. Product authority remains
[PRD](../product/PRD.md), [evidence architecture](../architecture/evidence-graph-jev.md),
[UI canon](../design/UI_CANON.md) and [Finish Contract](../../.agent/FINISH_CONTRACT.md).
[Strategy](../architecture/INTELLIGENCE_INTEGRATION_STRATEGY.md) is proposed design;
its original Packet-A-only instruction is superseded by this owner request.

## Exact baseline and discrepancies

- GitHub `origin/main` fetched at `49121eb14f5d090abbbbc8ebcd4bea6a4be62b21`
  (editorial removal PR83). GitHub open-PR query returned no open PRs. GitHub
  deployments endpoint returned no records; this does not prove no running app.
- Primary `gl3` remains `recovery/uncommitted-2026-09-30` at `66cd3ac` with two
  unrelated untracked paths. No reset, cleanup, runtime or data edits there.
  Isolated implementation: `gl3-intelligence-20261018`, branch
  `feat/intelligence-integration-20261018` from exact main.
- Requested `GRIDLENS_INTELLIGENCE_INTEGRATION_STRATEGY(2).md` was absent. Original
  supplied strategy was read and copied to the canonical architecture path.
- Current-state/graph described the prior editorial removal. Original bytes
  preserved under `.agent/archive/intelligence-20261018/`; new graph/packet records
  full owner scope. Milestones' `205b8e8` and prior-state `9947b21` are historical,
  not the fetched main or a verified live SHA. Existing dated reports stay intact.
- Production SHA, actual flags, budgets, credential propagation and live health
  are UNKNOWN. Earlier records say live collection/research/Jev/scheduling OFF,
  zero budgets. No direct runtime verification has occurred in this initiative.
- Local process and primary local env have no OpenAI key entry. No credentials
  were copied or printed. New isolated configuration uses no provider keys,
  collection/research OFF and zero model budgets. Account/model compatibility
  remains an activation prerequisite; new model IDs must not be guessed.
- Local Docker engine is unavailable. An isolated loopback PostgreSQL 18 cluster
  was initialized at port 55487 under ignored task artifacts. Dedicated application,
  destructive test, and read-only historical-corpus databases have distinct names.

## A–G requirement and module map

| Packet | Existing implementation | Required integration / evidence | State |
|---|---|---|---|
| A | canonical docs, `.agent`, Git/CI/deploy definitions | exact state, dependency map, frozen historical sample, checklist | audit recorded |
| B | `signal_adjudication.py`, `evidence_shadow.py`, `typesafe_evidence_judge.py`, `briefs.py`, jobs | shared durable calls/caps, eight advisory contracts, strict provider transports, mode/kill switches | B1 building |
| C | `ingestion/service.py`, adapters, registry; source schedule epochs/due receipts; `worker.py`, `queue.py` | explicit watch sets, incremental monitoring, reprocessing identity, bounded fairness/recovery, no model calls unchanged | pending integration |
| D | immutable Observation/Evidence, matching, `research_evidence.py`, material-state/change services | exact span/unit/date validation; candidate/source-authority separation; extraction job/result | pending |
| E | `pursuit_questions.py`, `autonomous_research.py`, buying-chain claims/runs, `power_qualification.py` | versioned six commercial questions, bounded reasoning/retrieval, citations/outcomes/backoff/context freshness | pending |
| F | authenticated API, project state/changes, pursuits and source screens, owner fact/workflow history | persisted intelligence candidates/questions/receipts, bounded request/retry, ops measurements, feedback attribution | pending |
| G | `evidence_evaluation.py`, research metrics, tests, DigitalOcean compose/systemd, backup runbooks | frozen four-route evaluation, receipts/reporting, runtime secret metadata/activation diff, restore/recovery, rollback | independent evaluation tooling building |
| LIVE | no new proof | authorized real changed-source journey; PC-off, alerts/restore, seven actual daily cycles, owner commercial review | OPEN |

Existing modules are capabilities to verify, not blanket acceptance. New work
must preserve narrower source/identity/qualification rules and historical receipts.

## Dependency and authority decisions

One concise opening tribunal used Luna, Terra and Sol. Decision: reuse existing
app and jobs; first freeze shared call accounting, then wire providers and grounded
candidates, incremental watches, question research, API/UI and operational tooling.
Independent evaluation fixtures/reporting can proceed without touching the shared
schema or mutable test database. No second provider platform or queue is introduced.

New calls reserve finite configured count/cost/concurrency caps before dispatch.
`SENT_OUTCOME_UNKNOWN` must be durable before remote I/O. Job fencing controls local
writes; it cannot retract a paid remote request. Unknown effects retain exposure
until explicit reconciliation. Evidence/current accepted context, task/prompt,
provider/model and policy versions determine cache identity. Source authority,
field consistency and domain gates remain separate from quote matching.

Eight owner contract IDs: `SOURCE_RELEVANCE_V1`, `EVENT_CLASS_V1`,
`MATCH_ADVISORY_V1`, `MATERIALITY_V1`, `POWER_ACTIVITY_HINT_V1`,
`RESEARCH_PRIORITY_V1`, `BUYER_ROLE_HINT_V1`, `LLM_ROUTE_V1`.
Routing promotion needs evaluation plus explicit authorization; all initial
results are advisory. Neither rejection nor uncertainty discards retained data.

No provider calls, paid probes, outreach, production writes, merge or deployment
are authorized by this build. Code/config/runbooks and local test transports are
authorized. Missing external proof never blocks completion of independent code.

## Provider contract verification

Official [TypeSafe OpenAPI](https://api.typesafe.ai/openapi.json) and
[reference](https://api.typesafe.ai/redoc) fetched October 18. Paths are
`/v1/systemone` and `/v1/models`; systemone requires model, state and questions.
Choice criteria map labels to descriptions; responses include choice, confidence,
probabilities, model and usage. Score criteria are ordered zero-based, so the
owner's 1–5 priority is represented by explicit categorical choices unless a
separately versioned conversion is justified. No pricing/model-account validation
or billable probe was performed.

Official [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
fetched October 18. Reuse the existing Responses endpoint and strict JSON schema;
no unrestricted browsing/tools. Model IDs/account support and current pricing
remain unverified and must be supplied/verified before activation.

## Frozen historical corpus and baseline

Original backup remains untouched. SHA256:
`e04f92fee4a9a26265974960a5695d088ca519fb8d0d56484199911f5db010d8`.
Restored separately from historical Stage3 authentic-r2 `after-replay.dump`, schema
`0018_interconnection_facts`: 17,776 observations, 19,326 evidence versions,
1,190 projects, 1,190 needs. This is historical retained data, not current live state.

At `2026-10-18T15:51:37.710167Z`, froze 90 cases: three per source ordered by hash
plus 36 power/utility/withdrawal text cases. Exact sample SHA256:
`da9665a186fd495cb917569d1075c03965afeef9f521772f71acf12beb6e3a54`.
Data and manifest remain ignored in `.artifacts/INTELLIGENCE-20261018/`.
Independent labels/representative-class review are PENDING; candidate outputs were
not consulted. No recall/precision/economic improvement is claimed.

Initial baseline `uv run pytest tests/unit -q`: 1,235 passed, 2 skipped, 4 failed,
7 subtests passed in 11.58 seconds. Failures are existing `test_jev_runtime.py`
Windows subprocess execution/environment assumptions. They precede product edits;
full-suite acceptance still requires repair or exact platform-qualified reporting.
Baseline migration `0001 → 0024` succeeded on the dedicated application DB.

## Finish and activation boundary

Implement all unblocked A–G first; freeze exact code/config/docs, run mandatory
checks and independent review. Record commands/results, migration compatibility,
responsiveness and costs as measured or UNKNOWN. Then prepare a concrete activation
diff, finite budget requirements and rollback. Actual enabled flags/budgets require
runtime receipts. Seven consecutive days and owner-reviewed commercial proof stay
OPEN until those real events occur. See this record's final validation update and
the initiative completion artifacts for accepted-candidate identity.
