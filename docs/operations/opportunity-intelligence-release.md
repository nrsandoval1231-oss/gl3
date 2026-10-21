# Opportunity intelligence release and acceptance record

Date: 2026-10-21. Base audited: `1c6c1cdc5f8d831c8106d4199a49e272b852f2eb`.

**Status: draft implementation, not approved for release or production activation.** No merge, deployment, production mutation or paid inference was performed. The requested full initiative is not complete. See [architecture and explicit remaining implementation gaps](../architecture/OPPORTUNITY_INTELLIGENCE.md).

## F5 integrated implementation update (2026-10-21)

This section supersedes the older retained-corpus counts and implementation-gap descriptions below where they conflict; the earlier regression report remains as historical evidence. F1–F4/F2C are integrated with the bounded F5 workspace and snapshot work. Current local changes expose project-scoped contact correction/retraction with reason, cited-source or separately reported provenance, history readback and stale-version 409 feedback; a row-based dated schedule editor and scenario projection; schedule-independent research hashing and fingerprint-based intelligence snapshot versioning; and source-native RRC/Austin/QTS/TADG names, raw source identifiers, and the QTS narrative address. Utility supply summaries retain explicit source kind and service-ready date; only a declared `utility_grid` source is presented as reported grid energization. Operator reporter name, organization and role are carried in the typed schedule attribution. The legacy four-key commercial operator-reference shape remains unchanged.

Focused local checks before final freeze: the source/schedule/commercial/snapshot backend set passed **60 tests**. Web typecheck and production build passed after OpenAPI/type generation. Five focused browser cases passed: project-scoped contact 409/history/retraction, operator-reported contact/retraction, schedule draft/accept/correct/retract with explicit grid dates, and intelligence-card rendering at 1280px and 390px. Targeted Ruff format/check and mypy passed. The controller's frozen-candidate gates and independent review are pending. See the task-local F5 completion receipt for exact commands, outcomes, changed files and unresolved checks. No readiness is claimed from this update.

A narrow independent F3 review has since opened a separate correction repair for cumulative sparse patches, subject-change identity links and stale/uncited contact actions. That repair is outside F5 ownership and its validation remains pending controller integration; the F5 contact browser scenarios do not close that independent review item.

The latest controller read-only retained-data check uses [the independent 14-case, 79-field manifest](pr102-retained-manifest.json). Its development comparison reported **74/79 exact display agreements and zero populated fields where the reviewer expected null**; this is not a release gate pass. Three required categories remain absent: site-specific utility constraint, conflicting power dates, and legitimate bridge-power potential. The offline ten-category runner therefore remains `BLOCKED`; live Jev/OpenAI acceptance and actual inference cost remain `BLOCKED` with providers default-off and credentials/budget authorization absent. Local persisted latency/restart proof and the final frozen-candidate controller result are pending.

## Delivered and exercised

Typed authenticated card/detail and bounded batch API; exact-target asynchronous enrichment requests; default-off expanded planning; existing canonical graph and durable research/ledger integration; supported contact actions; normalized official/operator gap shapes; independent completeness; grouped gaps and responsive workspace UI. Existing correction, evidence, review and queue navigation remain available. No schema migration or new runtime service is required for this extension.

Independent review identified and repaired conflict labeling, overly broad power provenance, public-source ID ambiguity, owner selection, stale research status, response bounds, optional snapshot churn and fingerprint rollout changes. Suitability scheduling was removed because its resolver is incomplete. Rental intermediary contacts are excluded. Review did not establish production readiness or completion of the larger directive.

## Regression evidence

**Final serial full backend suite: 2,366 passed, 1 skipped, 7 subtests passed in 303.75 seconds.** Twelve existing deprecation/connection-option warnings remain visible in the log. Final independent inspection found no additional blocker for an explicitly incomplete draft PR.

The initial full backend run: **2,358 passed, 1 skipped, 2 failed**, plus 7 passing subtests. Both failures were investigated:

1. Exact-target research bypasses the old mocked top-50 shortlist. The authorization/receipt integration fixture now mocks exact evaluation. A separate test explicitly fails if the endpoint consults the shortlist.
2. Additional typed operator metadata leaked into an established commercial-card contract. The old four-key reference shape and semantic hash are preserved; the intelligence assembler consumes typed raw projection metadata separately.

The repaired modules and new contract/integration tests subsequently passed **88 tests**. Latest focused tests passed **18**, including provider-free authenticated reads, byte bounds, snapshot reload, rental exclusion, qualification separation, conflicting evidence, gap arithmetic and batch query counts.

Workspace browser regression: **39 passed**, including desktop 1280 px and mobile 390 px card controls, no horizontal overflow, citations, verified call action, absent unverified email action, queued research confirmation and Back navigation. Visual screenshots were inspected. The first browser attempt could not launch because Chromium was missing; after installation, two new tests exposed disappearing queued confirmation. That UI defect was fixed; final browser suite is green.

Locked web dependency install and production build passed. Mypy passed all 130 source files. Ruff and generated OpenAPI/types were checked. A later concurrent focused/full database run collided because existing fixtures recreate the shared test schema; those results are invalid for product validation. The final serial rerun passed; no concurrent database test process was running. Raw unsuccessful and successful run logs remain in the local ignored `.artifacts/` directory; this document preserves their findings rather than erasing failed attempts.

## Performance evidence and limits

A real local PostgreSQL query-count regression using **synthetic records** measured:

| Batch | SQL statements | End-to-end aggregate assembly |
| --- | ---: | ---: |
| 1 need | 36 | 48.55 ms |
| 10 needs | 36 | 37.43 ms |

These are single engineering measurements, not production percentiles or retained-corpus latency claims. The larger warm batch was faster than the first cold read. Query count did not grow per need or per field. Large source histories, production contention, payload distributions and production p95 remain unmeasured. Existing preflight/byte limits reject oversize complete responses instead of silently omitting provenance.

## Real-evidence gate: blocked

Read-only inspection of the attached database found **0 projects, 0 power needs and 0 evidence rows**. No ten-opportunity sample could be evaluated. No actual customer/entity/contact/MW/date field accuracy, unsupported-claim rate, retained-corpus completeness, live Jev/OpenAI cost or production latency is claimed. Synthetic tests cannot satisfy this gate.

`backend/scripts/evaluate_opportunity_intelligence.py` runs a repeatable-read, read-only transaction with a 15-second statement timeout, invokes no providers, and requires an independently labeled manifest. Without that manifest it records counts and exits 2 (`BLOCKED`). The local run returned:

```json
{"status":"BLOCKED","provider_calls":0,"inference_cost_usd":"0",
 "corpus_counts":{"projects":0,"power_needs":0,"evidence":0},
 "live_provider_acceptance":"NOT_EXECUTED","production_latency":"NOT_MEASURED"}
```

On an authorized retained-data copy, run from `backend`:

```sh
uv run python scripts/evaluate_opportunity_intelligence.py \
  --manifest /approved/path/reviewed-cases.json \
  --output /approved/path/intelligence-acceptance.json
```

The manifest needs at least ten distinct need UUIDs, reviewer identity, independent `expected_fields` (null means intentionally unresolved), and the category coverage listed by the script. One example of the **manifest shape**, not real evidence:

```json
{"reviewer":"reviewer identity","cases":[{"need_id":"retained UUID",
 "categories":["data_center","bridge_power"],
 "expected_fields":{"customer":"independently verified owner","required_mw":null}}]}
```

Field accuracy is exact agreement on labeled fields. The reported unsupported-claim rate counts populated fields whose reviewer label says unresolved, divided by populated reviewed fields; it is not an exhaustive semantic or citation audit. Review complete source passages, entity matching, contradictions and contact responsibility independently. The runner does not approve release or run provider acceptance, even when its offline checks pass.

## Controlled release gates

1. Complete globally reconciled company/person identities, broader canonical extraction, structured contact corrections and phased supply/demand calculations. Current fields without a resolver remain explicit gaps.
2. Evaluate the ten required retained-record categories. Repair discrepancies and independently review field-level evidence, including negative cases and shared-company projects.
3. Measure persisted-data reads, restart survival and real query latency on the authorized representative corpus/runtime.
4. Verify the current ledger and resolve any provider holds/uncertain calls through the established procedures. Confirm permitted sources, credentials, model contracts and caps before any live inference. No automatic spend is authorized by this document.
5. Run controlled authenticated provider acceptance, record actual ledger costs and confirm stale/new evidence invalidation without lost history.
6. Obtain owner release authorization. Only then merge/deploy under existing runtime procedures.

Keep `OPPORTUNITY_ENRICHMENT_ENABLED=false` until these gates are satisfied. Disabling it restores existing automatic planning; it does not cancel already authorized jobs or alter existing independent provider flags. Do not clear jobs, receipts or reservations as a rollback shortcut. The presentation/API changes have no migration to reverse; roll back application artifacts using the existing deployment process if necessary.
