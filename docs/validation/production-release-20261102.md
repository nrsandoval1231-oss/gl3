# Production release — November 2, 2026

**Accepted deployment:** application commit `ec6486a2726758b2a9fb64a03e99276583a27a6e` ([PR165](https://github.com/nrsandoval1231-oss/gl3/pull/165)), tree `f27b999df5f76c9aa001fe5956c9e8205574a037`, serving [GridLens](https://app.grid-lens.com/). Final runtime verification passed at 17:10:40 UTC (11:10:40 Central); authenticated post-resume checks passed at 17:17:38 UTC (11:17:38 Central). This dated receipt supersedes earlier deployment holds and release checkpoints. Later documentation commits do not change the deployed application revision.

The [tracked sanitized receipt](production-release-20261102.json) preserves exact IDs, timestamps, measurements and SHA-256 references. It contains no credentials, session tokens, contact values or private configuration. Raw receipts, dumps, screenshots, failed attempts and superseded preparation remain in ignored local/on-host release artifacts; they are not bundled into a clean clone. Their absence is explicit, not replaced by fabricated evidence.

## Changes delivered

- Default customer/operator rollups retain nested projects, unconfirmed name-group distinctions, source evidence and privacy safeguards.
- Sector/search changes immediately report loading and hide mismatched previous-cohort rows. Valid matching cache refreshes remain usable; errors and Retry survive unchanged-filter clicks and reverted search drafts.
- Project counts share aligned right edges, chevrons remain aligned, and long count labels fit without overlap. Header search is separated from decorative artwork; artwork is hidden at compact widths and input blur is removed.
- The Oil-sector query no longer redundantly rejoins the same filtered browse rows to derived asset keys. The original query exceeded a 20-second database deadline on an isolated restore; reuse completed in 423 ms there, with complete result equivalence across eight sector/search/pagination/identity scenarios. This is isolated SQL evidence, not a production timing guarantee.
- Earlier merged reliability work (PR160, PR161, PR163 and PR164), including saved-browse recovery guards, customer rollups, source continuation and conservative demand-summary contracts, is included in this deployed revision. Implementation does not establish broad scheduled-source coverage or supported portfolio demand.

## Exact runtime and recovery acceptance

| Role | Immutable image ID |
|---|---|
| API, ingestion worker, browse worker | `sha256:7f5f063403384c620a6d4dd95260b06908ac6ed3e5bd35b6116ff58caa2c53b4` |
| Web | `sha256:06f4d027e5f27be54094086087a5f18ec1966447a27d9a28a396d6f414486925` |

All four roles were running with zero restarts; readiness was READY. Schema remained `0049_scoped_identity_browse`, 74 public tables. Protected configuration and provider controls were preserved. Existing services resumed only after independently accepted authenticated canaries. No migration, downgrade, production database restore, new infrastructure or paid-provider activation occurred.

A fresh 40,995,177-byte quiesced backup had SHA-256 `bd6d3ecaf101ef952ad093fd536ac979f9cdd1194507ba5fd8fd4389cc45caf1`; an independent reviewer recomputed all 74 restored table hashes and verified exact equality. The separate fresh online-backup rehearsal proved candidate and prior-image stage → inspect → guarded publication, policy/pointer binding, authenticated reads and non-browse retention against current forward schema. Online rehearsal evidence does not substitute for the quiesced restore comparison. Prior-image recovery did not claim to fix its known Oil-query defect.

The installed protected companion retained its earlier interface. The accepted release controller invoked actual guarded recovery functions through its fixed `database-python` operation. This release did **not** establish that the newer repository companion was installed, and did not use the obsolete `rollback-browse` lane or direct pointer overrides. See the [current recovery procedure](../operations/recovery-release.md).

## Validation and live behavior

- Exact final candidate [CI41480436348](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41480436348) and merged-main [CI41481601061](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41481601061) passed. Candidate evidence includes 3,718 backend tests passed / one existing skip, 196 browser tests and three real-backend responsive journeys. Independent scoped frontend rerun: 46 passed. Local disposable-DB authentication failures were preserved and never counted as backend passes.
- Source, raw-Git package bytes, image proofs, recovery tooling, actual rehearsal, live canaries and final runtime received separate independent Astra acceptance. Review authority did not come from a builder summary.
- Forty serial authenticated API reads passed with unauthorized denial, exact session cleanup and 64 canonical retention hashes unchanged. Oil groups had a five-sample median of 787.4 ms; Data Centers 221.2 ms; All 1,277.6 ms. The mixed-route p95 was 1,671.9 ms and is not a route-specific p95 or SLA.
- Actual Chromium at 1440/1281/768/390 verified search, filters, sorting, pagination, nested groups, detail/back, sources/evidence, session continuity, count alignment and header geometry; eight screenshot hashes were checked. All 28 changed-query actions had observed busy states (68 samples), with no mismatched prior-cohort rows. There were no observed console errors.
- Post-resume authenticated reads returned 2,154 projects, 417 All groups, 301 Oil groups and 16 Data Centers groups. Oil returned in 797.6 ms and Data Centers in 202.4 ms in those single bounded reads. Every sampled sector row matched its requested sector. A fresh current-container heartbeat and current generation/policy were verified; the temporary session was deleted.

## Remaining limits and retained failures

Demand summary remained truthfully unavailable: zero supported validated equipment records at verification. Unknown is not zero, and equipment-only MW is not total portfolio demand. Provider master dispatch gates remained closed. Fresh heartbeat/current browse readiness does not prove a completed scheduled source cycle, sustained maintenance, an SLA, broad source freshness, alert delivery, retention scheduling or commercial completeness.

Before the repair, bounded QA did not reproduce a settled filter mismatch, but later measurements found a real Oil timeout. Earlier browser helper races/encoding/geometry assumptions and a post-resume DTO-validation mistake were corrected and reviewed; all failure evidence and session cleanup receipts were retained. Final acceptance applies to successful exact artifacts only. Frontend-only release preparation was superseded without execution after the backend defect was confirmed.

Next work requires a separately scoped task: sustained scheduled-source/freshness observation, broader validated equipment/buyer coverage, and evidence-based portfolio aggregation. This documentation update records progress; it does not activate providers, workers or a new deployment.
