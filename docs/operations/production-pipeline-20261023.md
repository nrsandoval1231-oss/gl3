# Production intelligence implementation record — October 23, 2026

The [owner directive](../../.agent/PRODUCTION_INTELLIGENCE_DIRECTIVE.md) defines
six sequential milestones. This branch begins with Milestone 1: PUCT docket
retrieval, normal saved-browse startup, and the approved desktop detail layout.
The full live Firecrawl → Jev → OpenAI → verified commercial record acceptance
remains open. This record does not authorize a production deployment.

## Milestone 1 implementation

- PUCT docket searches now use the official direct `/search/dockets/` endpoint
  with `ItemMatch=Equal`. The obsolete endpoint redirects. Exact-host/public-IP
  validation, rejection of redirects, bounded queries, and agreement between
  HTML and spreadsheet rows remain enforced. Docket evidence does not by itself
  establish a commercial opportunity.
- Local and production Compose start the existing provider-disabled browse
  maintainer after migrations. The API saved-browse feature flag retains its
  default. When enabled, the maintainer publishes the first generation without
  a manual rebuild; the API retains its pending response until publication.
  See [local startup](local-runtime.md) and [saved browse](saved-browse-b1.md).
- At 1280×800, the five metric cards retain the approved layout and complete
  values. Long evidence identifiers wrap within their cards; compact desktop
  values use 15px text. A cited synthetic fixture exercises long values,
  1648px geometry, and 390×844 horizontal bounds. These screenshots are layout
  evidence, not real-project acceptance.

## Local runtime evidence

The isolated loopback PostgreSQL cluster uses port 55443. Existing checkouts,
databases, and the separately running application are preserved. No paid model
or Firecrawl generation request was made for this repair milestone.

Fresh migrated startup was observed with real authentication: login 200,
unauthenticated Opportunities 401, enabled saved browse initially 503, then
Opportunities 200 with an empty list after ordinary `python -m
gridlens.jobs.browse maintain`. No manual rebuild was invoked. One intermediate
503 came from an API process holding a pre-edit policy fingerprint; restarting
that process at the matching revision resolved it without weakening the fence.

The first public PUCT adapter check returned ten unique dockets across the two
bounded queries. In the fresh UTF-8 database, the ordinary worker persisted ten
observations and ten evidence records in 2.606 seconds. Replay succeeded in
2.402 seconds with zero new records and ten unchanged records; semantic content
digests were stable. Both jobs are terminal successes. Actual HTTP request
count was not instrumented in the worker child process and remains UNKNOWN;
the adapter bounds each pass to four logical requests before transport retries.
These docket-index records remain evidence-only. Raw local receipts and layout images remain outside
Git under `.artifacts/production-pipeline/` and
`.agent/artifacts/PRODUCTION-M1-UI/`.

The validation harness encountered two local setup failures: a missing Windows
multiprocessing main guard, then a database created with Windows' default
WIN1252 encoding. The latter job committed ten evidence records before JSON
decoding failed in the receipt collector. The databases and failed receipts
were preserved. Empty receipt arrays cannot prove that a job had no effects;
durable job and content state must be inspected before retrying. Revised
verification databases use explicit UTF-8 encoding. No application evidence
was deleted to obtain a passing result.

## Verification and remaining work

The first full backend run reported 2,750 passing tests, three skips, seven
passing subtests, and one cached-receipt test failure: an immediately enqueued
job was not yet claimable. The single test passed in isolation. Inspection
showed its due time came from PostgreSQL while the claim checked the process
clock. The receipt test now explicitly makes its fixture job due; all cache,
provider-call, and receipt assertions remain. Production scheduling is unchanged.
The seven-test receipt file passed after this test-only correction. The original
failure and independent `FIX` review remain retained; a new frozen candidate
must pass the full gate and review before acceptance.

Controller gates bind to the frozen Git candidate: Ruff/format/mypy, fresh and
repeat migrations with drift check, complete backend tests, dependency audits,
TypeScript/build, browser regressions including real authentication, and
documentation/diff checks. Independent review is required before accepting the
milestone. Exact command results and review identity are retained in the
candidate's ignored evidence directory and PR, rather than asserted in advance.

Milestones 2–6 remain open: five-source native/Firecrawl comparison, live Jev
evidence processing, actual configured OpenAI reasoning model, customer/project
and buying-chain resolution, classification investigation, regional source
coverage, and five-project live acceptance with measured costs and recovery.
Read-only provider metadata confirmed Firecrawl account access and Jev model
aliases; it does not prove either integration operational. OpenAI key setup is
pending. Credentials must stay in the secure local destination, never in Git
or validation output. No merge or production deployment has occurred.

## Milestone 2 accepted state

M2 was accepted at `86a443427b97ff68d1b43bc861f2f8a2ac0cce52`. Its recorded CI run was 40009230663, with 2,779 backend tests and 191 browser tests passing. This acceptance advances the work graph to M3 and does not close the overall live-pipeline Finish Contract.

## Milestone 3 evidence packages

`materialize_evidence_package.py` creates a versioned JSON package from one retained `Evidence` version. Every emitted source fact or project identity candidate points back to the exact evidence ID, hash, URL, and field location. Unparsed buyer, load, schedule, duration, and supply remain `UNKNOWN`; the package does not promote a Signal or establish a commercial role.

The package reports document coverage separately from source collection and advisory processing. An excerpt may support a `PREPARED` package while `document_coverage` remains `RECORD_EXCERPT` and source collection remains `PARTIAL`. Deterministic labeled-field extraction includes applicant, facility, permit numbers, application received/stage, location, and stated purpose. Jev sees at most 300 title characters, 1,500 abstract characters, and 500 URL characters. Omitted tails and source excerpt scope stay explicit; full-document coverage requires producer proof and is not asserted by this excerpt parser.

Use the default mode to materialize and inspect metadata without a provider request:

```powershell
uv run --project backend python scripts/materialize_evidence_package.py --evidence-id <evidence-uuid>
```

Replay an already stored package to check its digest and confirm that job and logical-call counts and dispatch timestamps did not change:

```powershell
uv run --project backend python scripts/materialize_evidence_package.py --evidence-id <evidence-uuid> --replay
```

`--execute-jev` is restricted to the isolated loopback `pipeline_m3_app` database. The runner checks the exact retained hash, enabled registered source, existing `SIGNAL_ADJUDICATION` contract/model policy, exact prior decision and call ledger, and then dispatches at most one exact queued job. It will not retry completed or uncertain calls. Configure finite budgets and the selected observation allowlist before attempting dispatch. The current estimate policy is a reservation, not a hard invoice ceiling. The runner never prints credentials or retained source text.

```powershell
uv run --project backend python scripts/materialize_evidence_package.py --evidence-id <evidence-uuid> --execute-jev
```

### M3 observed pilot and replay

Controller evidence recorded 2026-10-23 shows one completed Jev `1.13.0` advisory for evidence `9b8db416-e93c-4b1a-93d4-4328cc497649`. Package `082295b4-26eb-4414-a57b-af66fdb6e9f1` is `COMPLETE_ADVISORY`; its exact logical call is `ac6f6237-165b-441a-8102-68bb421ee589`. Schema and source-span validation passed. The package contains seven cited `REPORTED` facts: applicant, facility, permit numbers, application received date, application stage, location, and stated purpose. It records `document_coverage=RECORD_EXCERPT` and `source_collection_status=PARTIAL`; the retained excerpt does not establish full-document review.

The advisory decision is `SHOW`, which is a display decision only. It does not establish qualification, buyer identity, or confirmed rental-power demand. Buyer, required load, start timing, duration, and supply remain explicitly `UNKNOWN`. The call reserved $0.01; actual invoice cost is `UNKNOWN`, and this estimate is not a hard invoice ceiling. Reported usage was 976 input and 120 output tokens. Operator execution took 1.675 seconds and replay took 1.114 seconds; these are command durations, not provider latency.

Replay created no new calls and left the package payload, dispatch timestamps, retained evidence IDs/hashes, canonical projects and needs, and existing jobs—including the four queued buying-chain jobs—unchanged. The real zero-cap worker/ledger check also passed with `BLOCKED:GLOBAL_DAILY_CAP_ZERO`, zero logical-call rows, and zero provider attempts. Fresh and retained database migrations each passed twice with schema-drift checks. The focused evidence and signal/logical-call suite passed 64 tests.

These results establish the observed M3 pilot and replay only. Frozen-candidate gates and independent review remain pending, as do M4–M6 and the overall Finish Contract. This record does not assert final milestone acceptance or authorize a deployment.

## M4 commercial assessment implementation

`COMMERCIAL_ASSESSMENT_V1` adds a bounded, advisory-only assessment for an exact
current M3 package and PowerNeed. The operator runner requires `--package-id`;
its default mode inspects metadata, `--execute` queues and runs only the exact
need job, and `--replay` reads existing job/call metadata without dispatch or
creating a replacement job. The task remains disabled unless explicitly named
in `INTELLIGENCE_ENABLED_CONTRACTS` and intelligence is enabled in evaluation
or advisory mode. It requires an eligible project and a current package whose
database row and payload both say `COMPLETE_ADVISORY`.

Before dispatch and again during the existing worker freshness check, the
package is revalidated against retained evidence identity, hash, citation
spans, exact need/project, and current regional eligibility. Excerpt and
partial-source states remain visible in the model input. Output is a strict
enumerated disposition, selected cited package fact IDs, bounded research
dimensions, and one existing research question ID. The server constructs the
explanatory action text. Unknown MW, start window, buyer authority, supply gap,
duration, and rental-versus-permanent status remain unknown unless current
deterministic need facts establish them. This advisory cannot change canonical
facts, tiers, pursuits, or customer identity.

The Responses request pins `gpt-6.1-sol`, default service tier, medium reasoning,
30-minute prompt cache, `store:false`, no tools, and a 6,000-token output bound.
The existing logical-call ledger enforces finite global/provider/model/source/
project scopes and its uncertain-send quarantine. Reservation uses $2.50/M for
all serialized request bytes and $10/M for 6,000 output tokens, capped at $0.25
per call. The receipt records returned service tier and raw reported usage.
Derived cost is a conservative usage estimate, never an invoice. Replay of an
identical request reads the existing result and makes no provider call.

Usage:

```powershell
uv run --project backend python scripts/run_commercial_assessment.py --package-id <package-uuid>
uv run --project backend python scripts/run_commercial_assessment.py --package-id <package-uuid> --execute
uv run --project backend python scripts/run_commercial_assessment.py --package-id <package-uuid> --replay
```

Fixture tests and a completed model response do not establish live M4
acceptance. The controller owns retained-database preflight, the single capped
pilot, exact replay proof, frozen-candidate gates, and independent review.

### M4 bounded live pilot and replay

The controller completed one capped live M4 assessment for package
`082295b4-26eb-4414-a57b-af66fdb6e9f1` and need
`97845fc4-9a71-4725-8c7e-52959816b1cd`. Logical call
`d776be18-16b4-42b0-9888-b6f2e5678a6f` completed job
`d4b8eaea-76e9-43cd-a75e-2e3c22f1be61` with `gpt-6.1-sol`, actual service
tier `default`, and provider request ID `req_0d1a311d583a4c33a3f951667cd51787`.
Reported usage was 2,705 input and 257 output tokens, including 133 reasoning
tokens; 2,702 input tokens were written to the 30-minute cache, with zero
cached tokens and zero 12-hour cache writes. Provider latency was 6,936 ms and
the CLI run took 8.372 seconds. The logical-call database ceiling was $0.085483
against a $0.0854825 reservation. The reported-usage estimate was $0.0093325;
actual invoice cost remains `UNKNOWN`.

The validated result was `UNRESOLVED` / `EXCERPT_INSUFFICIENT`, citing only
`f-e92124bc36e1a311` (the retained stated-purpose fact). Buyer authority,
duration, rental-versus-permanent status, required MW, start window, and supply
gap remain unknown. The server-rendered next question was: “What dated evidence
establishes commissioning or test-power timing for this exact need?” This
result is advisory and does not establish rental demand or promote canonical
qualification.

A keys-disabled replay completed in 1.233 seconds without creating calls or
jobs. The exact call and result payload, timestamps, evidence and canonical
table hashes, existing jobs, and original M3 database remained unchanged. The
inspect, execute, replay, final-preflight, and controller focused-gate receipts
are preserved under ignored `.artifacts/production-pipeline/m4-live-*`,
`m4-policy-preflight-final-r1.json`, and `m4-controller-checks-r1`. The
controller's final focused suite reported 86 passed with tests, Ruff, format,
and targeted mypy all green. Earlier builder receipts still record the prior
lint/format-only failures and their subsequent fixes; they were not discarded.

This proves one bounded live M4 path and exact replay only. Full repository
finish gates and independent review remain pending; M4 acceptance and parent
M5–M6 milestones remain open.

### M4 review repair: source version and unevaluated contradictions

M4 currentness now verifies the package row's Evidence and Observation identities,
the source-reference Observation ID against the retained Evidence relationship,
and the current Observation hash against the cited Evidence hash. This uses the
same equality invariant enforced by the deterministic M3 package builder; it
does not introduce a new hash field or alter the successful live request
identity. A post-dispatch version change preserves the provider usage and cost
receipt as `STALE_CONTEXT` and removes the advisory disposition. Keys-disabled
replay refuses the stale package.

The accepted M3 package contract currently emits an empty `contradiction_pairs`
list and rejects nonempty pairs without deterministic cited-claim validation.
Accordingly, cross-claim contradictions remain explicitly unevaluated and M4
rejects `CONFLICTING_EVIDENCE` without validated pairs. The existing empty-pair
representation is preserved, including its request identity. A cited
contradiction producer and validator remain an open upstream capability.

The backend dependency pin and lock entry now use pypdf 6.21.2, resolving the
three CI-reported pypdf advisories without suppressions. The live M4 result and
keys-disabled replay evidence above remain unchanged; new-candidate gates and
independent review are still pending.

### M4 publication transaction repair candidate

The M4 repair candidate settles the already-dispatched logical call and its job
checkpoint in one final PostgreSQL `REPEATABLE READ` transaction. It locks the
running job fence and the exact need, project, package, evidence, observation,
and source identities before rebuilding the current request payload. A matching
snapshot publishes `VALIDATED`; a changed or malformed current snapshot
publishes a metadata-only `STALE_CONTEXT` receipt with reported usage and no
accepted advisory. The call settlement uses an opt-in deferred commit, so the
logical-call terminal state, checkpoint, and job status commit or roll back
together. A serialization retry re-runs only this final settlement and never
re-dispatches the provider request. Fence loss or an existing terminal call
rolls back publication. This is local repair evidence only; controller gates,
the retained zero-call replay, and independent review remain required.
