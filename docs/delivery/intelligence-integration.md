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
- Current read-only DigitalOcean inventory confirms `gridlens-production`
  (609407604) active in nyc1, four vCPU/8 GB, droplet backup enabled weekly Sunday
  04:00 UTC with 28-day retention. Inventory lists one backup image; this is not a
  database/evidence restore or scheduler/provider receipt. The connector exposes
  no host command channel; local SSH configuration has no trusted production
  binding. No runtime secret values, flags, SHA or budgets were inspected.
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
| B | `signal_adjudication.py`, `evidence_shadow.py`, `typesafe_evidence_judge.py`, `briefs.py`, jobs | shared durable calls/caps, eight advisory contracts, strict provider transports, mode/kill switches | B2/E/B3/B4 locally verified; final review pending |
| C | `ingestion/service.py`, adapters, registry; source schedule epochs/due receipts; `worker.py`, `queue.py` | explicit watch sets, incremental monitoring, reprocessing identity, bounded recovery, no model calls unchanged | C–C5 integrated; final combined gates govern acceptance |
| D | immutable Observation/Evidence, matching, `research_evidence.py`, material-state/change services | exact span/unit/date validation; candidate/source-authority separation; extraction job/result | B2/D2/D3 integrated; OCR dormant and unverified by design |
| E | `pursuit_questions.py`, `autonomous_research.py`, buying-chain claims/runs, `power_qualification.py` | versioned six commercial questions, bounded reasoning/retrieval, citations/outcomes/backoff/context freshness | E/E3 and F3 durable buying-chain jobs integrated |
| F | authenticated API, project state/changes, pursuits and source screens, owner fact/workflow history | persisted intelligence candidates/questions/receipts, bounded request/retry, ops measurements, feedback attribution | F1/F3 integrated; exact-candidate runtime receipts govern acceptance |
| G | `evidence_evaluation.py`, research metrics, tests, DigitalOcean compose/systemd, backup runbooks | frozen four-route evaluation, receipts/reporting, runtime secret metadata/activation diff, restore/recovery, rollback | G0/G1/G2 locally verified;0028 full restore MATCH; final candidate gates pending |
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
Separate agent-proposed labels were authored from frozen evidence without candidate
outputs: 21 SHOW, 18 REVIEW, 51 HOLD; relevance YES 40/NO 50; identity-pair safety
UNKNOWN 90, promotion unsupported 90. These are excerpt-only proposed labels, not owner
review or accepted benchmark truth; 26 cases are RRC drilling, so composition is biased.
The reproducible deterministic-display-only baseline uses the current explicit rules
and REVIEW fallback: 89 UNKNOWN relevance, one bounded negative, 19/90 proposed
display labels matched. Its numerical quality gate fails; no improvement is claimed.
Three paid-model routes remain NOT_RUN, with cost/usefulness comparisons UNKNOWN.

Before evaluating candidate answers, a separate25-case retained addendum was frozen
at2026-10-18T18:28:06.215959Z:16 narrow identity pairs,7 actual evidence-version
pairs and2 source failures. Canonical sample digest
`951db93639543464a2d5f7b5ec14f454101592b96bdfe904c4b36453c48d754a`;
whole manifest-file digest
`70db9d69eecc664d9781897e85521a8e8560fa017434d1e65fdba5074f1e0e85`.
Independent Sol proposed labels retain unknown identity outcomes where location
evidence is insufficient; these remain proposed labels, not owner acceptance.
All four evaluation route templates remain NOT_RUN until actual observations are
provided. Missing claim reviews, usage, cost, latency and queue receipts cannot
become zero errors or a passing quality gate.

Initial baseline `uv run pytest tests/unit -q`: 1,235 passed, 2 skipped, 4 failed,
7 subtests passed in 11.58 seconds. Failures are existing `test_jev_runtime.py`
Windows subprocess execution/environment assumptions. They precede product edits;
full-suite acceptance still requires repair or exact platform-qualified reporting.
Baseline migration `0001 → 0024` succeeded on the dedicated application DB.

Controller repaired the existing Windows test harness by preserving required OS
paths and invoking Linux deployment scripts through Git Bash. Its original
assertions remain; all 18 affected tests pass. G0 evaluation tooling has nine
focused tests, controller rerun passing alongside those 18 tests, Ruff and mypy.
The canonical evaluation manifest uses its own canonical-JSON hash
`2fd9b6dd4d977b3acfc0c905c5bf960242dc78b8c90dd5f4a89b07c49387a594`;
the upstream export-file hash above remains separately recorded.

Controller reran B2/D's 39 focused tests at 9aa3117: durable reservations, actual worker
dispatch with fake transports, strict schemas, stale fences and crash recovery.
The builder's broader legacy test attempt collided on a shared destructive fixture
database and is inconclusive (65 failed/54 passed/19 errors), not a product/full-suite
result. Every builder now has an exclusive test database; final full-suite gates
remain required. C's 12 controller tests pass at eb2dcf0.

A fresh retained copy upgrades 0018→0027 with all original core fields preserved.
Schema drift found a monitoring index missing in ORM metadata and watch-source
Integer versus migration BIGINT Identity; C2 repaired both and controller reran
58 focused tests plus `alembic check` with no drift. A local
PostgreSQL18 dump/restore rehearsal preserved 19,326 evidence versions, 95 jobs,
two synthetic logical calls and 12 budget rows byte-for-byte in row digests. NOT_SENT
reuses its ID; SENT_OUTCOME_UNKNOWN remains reserved and rejects repeat dispatch.
This is local technical proof with zero provider calls, not a cloud restore receipt.

The later0028 migration and append-only settlement trigger pass on an isolated
copy. A fresh dump/restore preserved all50 public application tables by streamed
counts/SHA256, including19,326 evidence versions,98 jobs,5 synthetic logical calls,
18 budget rows and one explicitly synthetic settlement. Unknown dispatch and
settlement idempotency checks issue zero provider calls. The first summary-only
comparison falsely mismatched because SQL aggregate ordering differed; the failed
receipt is retained. Explicit status ordering repaired that diagnostic and the
new v3 comparison reports MATCH. No cloud restore has been claimed.

After B3 and G2/B4-H integration, the controller ran88 focused tests in40.30s
against its exclusive PostgreSQL test database. This includes actual0028 trigger
UPDATE/DELETE denial, reservation/crash paths, task-specific contexts, adversarial
authority, evaluation coverage and authenticated offline research/feedback. These
are development checkpoints; full final gates and independent review still apply.

An actual React/authenticated API/PostgreSQL cloned-corpus journey displays a saved
fake-provider UNKNOWN result, persists it after reload, and keeps disabled research
controls unavailable. Desktop/mobile screenshots show no horizontal page overflow
or JavaScript errors. No Lead or accepted claim was generated. In that disposable
clone,300 mocked RSS items ingested in27.151s; identical replay took1.569s, created
no extra facts/material changes and made zero provider calls. Eight samples per
endpoint, with reads alongside ingestion: health p50/p95 7.46/26.51ms;
operations76.41/120.89ms; changes25.16/
39.51ms;20-record opportunity page3005.69/3119.63ms. The opportunity-page latency is
a measured local limitation, not an accepted production SLO. Actual provider
usage, cost and commercial benefit remain UNKNOWN.

Current registry configuration contains 26 sources, 25 registry-enabled, spanning
eight declared families, including a California CEQAnet definition. These are
configuration counts, not verified live coverage or production enablement.
This corrects the dated milestone statement that no California source exists.

On an independently copied historical database, migrations through the new watch
schema preserve every original field/digest in all 17,776 observations, 19,326
evidence versions, 1,190 projects and 1,190 needs. Original backup and frozen corpus
remain untouched. Authenticated local read baselines (five samples, saved-browse
disabled): health median 19.31 ms/max 55.25 ms; 20-Signal opportunity page median
1,277.95 ms/max 1,311.88 ms; changes median 3.25 ms/max 5.93 ms. No production SLO,
concurrent-ingestion result or model economics is established by those samples.

First code commit `5daeb72212cf1493a714457e9be4e3b4bfe8235d` passed eight
controller-focused tests/Ruff/mypy. Independent Sol review returned **FIX** for
five ledger/migration issues; it is not accepted completion. B2 repairs are part
of the next exact candidate. Evaluation/audit checkpoint is `98d7019`. The source
strategy copy's Markdown hard-break whitespace is normalized for final diff gates;
the original Downloads file remains unchanged.

## Finish and activation boundary

Additional bounded integration repairs: C3 separates acquisition from source/database
transactions and rechecks source policy/fences;54 controller tests pass. C4 separates
source/watch/pursuit planning and heartbeat lanes;67 controller tests pass. E3 adapts
legacy research tests to the controlled acquisition boundary and bounded retry jitter;
91 builder tests pass. D3 at7187de2 adds dormant exact GovInfo PDF capture, retained
OCR_UNVERIFIED transcript and separately grounded follow-on, with45 builder tests.
Its history reads are batched. These are development results, awaiting the combined
exact-candidate full gates and independent review. C5 atbf24b07 adds finite
acquisition, shared admission and nonblocking per-source planning. The controller's
first combined run had134 passes and one pre-retrieval event timeout; the original
receipt is retained. Diagnostic-only improvement preserved the same five-second
bound. The isolated test and repeated135-test batch pass; the timeout's cause
remains UNKNOWN. No product repair or deterministic explanation is claimed.
F3 at59f4a80 moves buying-chain acquisition into fenced durable jobs and makes
authenticated enqueue network-free, with context revalidation before writes.
Builder42 PostgreSQL and5 browser tests pass; controller full gates cover it.

The prior candidate was superseded by full-suite failures and independent review
findings. B5 adds verified total billable-input bounds (2d6a89d); C6/B6 reuses exact
completed signal judgments and denies external test networking (7f69e75). Controller
focused runs pass46 and133 tests respectively. C7a adds bounded schedule progress,
truthful acquisition timing and current-window assignment (1a6249d); controller58
tests pass. C7b implements bounded durable issue/modification collection, evidence-before-cursor commits and transactional continuation. Controller128 tests pass, including nine adversarial PostgreSQL cases. Two checkpoint races were reproduced and repaired with fresh locked reads and a full immutable progress snapshot; earlier failure receipts are retained. The0029
local restore preserves all52 tables, including synthetic nonempty progress rows,
and retains UNKNOWN-call exposure without redispatch. These are development proofs.
The rejected6d88 full suite recorded2000 passed,12 failed,12 setup errors,3 skipped
and7 subtests; it was not a pass. An obsolete mock allowed at least one TypeSafe
authentication request using a synthetic key and synthetic text. No real key or
successful model response was involved; total request count and billing remain
UNKNOWN. Later fixtures deny external HTTPX, DNS and TCP. Earlier receipts remain
retained rather than being replaced by the repaired runs.
Final
validation and independent review are separately bound to the immutable commit
in `.artifacts/INTELLIGENCE-20261018/final/release-manifest.json`; absence of a
matching accepted receipt means this document grants no acceptance. The receipt
includes gate commands, runtime/browser evidence, measured limitations, and the
review identity. It does not authorize deployment, spend or outreach. This
execution record and explanatory configuration are frozen before those gates.

Implement all unblocked A–G first; freeze exact code/config/docs, run mandatory
checks and independent review. Record commands/results, migration compatibility,
responsiveness and costs as measured or UNKNOWN. Then prepare a concrete activation
diff, finite budget requirements and rollback. Actual enabled flags/budgets require
runtime receipts. Seven consecutive days and owner-reviewed commercial proof stay
OPEN until those real events occur. See this record's final validation update and
the initiative completion artifacts for accepted-candidate identity.

The2101510 freeze also failed acceptance:2054 passed,2 failed,9 setup errors,3 skipped and7 subtests. The failures exposed test assumptions around immediate eligibility, non-retroactive scheduling and log synchronization, plus a builder-specific database guard. The next candidate repairs these fixtures without weakening database isolation or timeout bounds. Raw full output remains in final-attempt3-2101510.

Independent8c review returned FIX for returned-model identity and reported usage beyond billing bounds across queued and legacy calls. B7 adds durable provider-response quarantine, conservative exposure accounting and reservation/dispatch blocking until explicit attributable reconciliation; no schema change. Its policy version prevents older completions bypassing response checks. The local V5 restore retains this quarantine and pre-reserved call, all52tables match, and no paid call is replayed. Full8c output (2064 passed,1 failed,3 skipped,7 subtests) and review remain preserved. Its last test failure was reproduced as Alembic disabling an already-imported logger; a scoped test restoration passes the predecessor sequence. Matching final receipts still govern acceptance.

B7 focused builder validation:147 tests pass, including ledger concurrency, queued worker OFF/zero-cap guards, exact-model/usage quarantine, legacy evidence-shadow and briefs. Controller V5 backup/restore checks pass; these do not substitute for the matching final full-suite, browser, runtime and independent-review receipts. No production activation or budget authority was added.

B7b closes exception paths identified by the f47f151 review: unrepresentable
exposure retains an UNKNOWN/unbounded hold; hostile response auditing stays
bounded; ordinary completion/failure cannot release quarantine; reconciliation
persists copied audit JSON and its digest. Parsed OpenAI error envelopes retain
available billing metadata across queued, legacy and OCR paths. Pricing and output
limits participate in context identity. Valid exact-model results may retain NULL
usage under independently verified conservative reservations; missing usage is
not itself a proven billing breach. The rejected f47 full run was stopped after
53.786 seconds upon review FIX, so it provides no full-suite pass. Final matching
receipts remain required.

9391984 was rejected during final verification. Additional shared-transport and legacy-wrapper repairs preserve billing metadata before semantic rejection and distinguish malformed usage from legitimate NULL measurements. The stopped backend run is not a pass; browser136 passes/10 failures/1 skip are retained. Browser failures were traced to schema-invalid synthetic health and newly unmocked intelligence GETs in navigation fixtures; these are repaired without changing product navigation. Complete final receipts remain required.
