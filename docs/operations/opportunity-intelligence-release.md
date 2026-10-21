# Opportunity intelligence release and acceptance record

PR105 completes the follow-up to merged PR102 and composes the approved workspace from main `b224bbbe64cb6877e4910e05218365ec71364759`. Its release boundary is a controlled, default-off implementation with retained-data acceptance. Exact-head local gates, GitHub CI, runtime/restart receipts and independent review are recorded in [PR105](https://github.com/nrsandoval1231-oss/gl3/pull/105); earlier candidate results do not certify a changed head. Parent launch and live-provider activation remain separate, open gates.

## Implemented behavior

The authenticated horizontal Pursuit Workspace displays cited project/customer facts, research gaps, evidence and next actions. Reads are bounded and provider/job-free. Project-scoped buying-chain corrections retain reason, history, optimistic versions and idempotency, including stale-version feedback. Sparse corrections compose, subject changes supersede identity links, unverified/uncited method replacements remove old same-kind actions, and review can use current evidence after stale correction history. Selection guards prevent asynchronous correction responses from changing another selected opportunity. Operator-reported methods do not become call/email actions. Ordinary enrichment remains project-scoped; the tested strong-ID reconciliation helper is not wired into automatic enrichment. Cross-project links require attributed review through the correction API.

The power-schedule editor records attributed demand phases and supply through draft, accept, correct, retract and history. Scenarios remain separate from the current qualified gap. Supply retains source kind, ready date/basis, suitability, source reference and reporter attribution. Only explicit utility-grid entries are presented as reported energization. Unknown supply and facility-scale figures cannot produce a qualified temporary-power gap. Snapshot fingerprints and schedule-independent research hashing preserve prior semantics.

Unfiltered selected-opportunity detail avoids repeated legacy cohort work. Explicit search-scoped detail retains its separate path and performance limits. Local development timings are not production latency evidence. Approved web source is preserved from main, including mobile history and sidebar controls.

## Real retained evidence

The original retained database has 1,620 projects/needs and 18,016 evidence rows. Its original 14 independently labeled cases matched all 79 reviewed fields but lacked utility-constraint, conflicting-date and bridge-power examples. F17 retains official originals for **two distinct physical sites covering those three categories**. [Source provenance](pr105-real-evidence.json) records URLs, original-body SHA-256 hashes, reviewed PDF pages, dates, attribution and limits. The [curated manifest](pr102-retained-manifest.json) preserves the 14 baseline labels and adds independent original-document labels for two sites, totaling 16 cases and 95 fields.

- STACK's SVY02A / Memorex Junction at 1200 Memorex Drive, Santa Clara: the city-filed June 2024 claimant statement reports incompatible service schedules above 18 MVA; the February 2025 CEC filing retains additional utility correspondence. The attached September 2021 agreement is visibly a draft. These are attributed reports, not adjudicated findings. The 1100 Memorex correspondence address is distinct from the site. MVA is not converted to MW.
- Crusoe's Abilene Stargate campus: the publisher-linked report describes natural-gas turbines providing temporary bridge power while grid upgrades catch up. This establishes a historical/in-use bridge configuration. Its 350 MW on-site capacity/long-term backup figure is not temporary demand or a residual gap. Exact bridge dates, current unmet procurement and utility energization remain unknown.

Both sites retain null facility demand, temporary required MW, temporary start, qualified gap and energization in the independent labels. Customer/organization names identify source-supported owner/operator relations, not verified temporary-power purchasers. Historical legal/utility correspondents do not become current verified contacts. Publication and event dates remain separate: the city meeting date is not claim publication, and the Crusoe blog's initial release does not prove when its current PDF bytes first existed.

## Reproduce bounded import and acceptance

Preserve a `pg_dump` and the original database, restore an isolated copy, and migrate through head. The importer refuses writes outside loopback databases ending `_test` or the explicitly named F17 acceptance copy. All three registry entries remain disabled and manual-only. The command performs no new retrieval or model calls.

Retain the original PDFs at the basenames in `backend/src/gridlens/ingestion/adapters/retained_document.py`, verify pinned hashes against the public provenance record, then run from `backend` with the isolated configuration:

```powershell
uv run python scripts/import_retained_document.py --source f17-stack-city-claim --root <retained-pdf-directory>
uv run python scripts/import_retained_document.py --source f17-stack-cec-filing --root <retained-pdf-directory>
uv run python scripts/import_retained_document.py --source f17-crusoe-impact --root <retained-pdf-directory>
uv run python -m gridlens.jobs.browse rebuild
uv run python scripts/evaluate_opportunity_intelligence.py --manifest ../docs/operations/pr102-retained-manifest.json --output <evaluation-json>
```

The route verifies original bytes before parsing bounded reviewed pages, then uses Source → fenced Job → Observation → versioned Evidence → Interpretation → Project/PowerNeed and existing retained-only enrichment. Canonical writes and enrichment share one transaction; failure preserves prior accepted data and a failed job receipt. Replay reuses canonical identities and Evidence. Changed unreviewed bytes fail before database access. A newly reviewed version requires an explicit policy update and fresh validation, preserving prior Evidence; synthetic tests separately exercise this transition, rollback, stale fencing and PDF line wrapping. Rebuild the derived browse generation after intake before checking the workspace; a stale generation correctly returns 503. This retained-only maintenance creates no retrieval jobs or model calls.

Manifest IDs belong to the retained acceptance copy. Another restored/imported database must map actual IDs while preserving independent expected values and source identities. The evaluator is read-only and provider-free. Its result covers the independently labeled fields and representative categories, not every possible fact or current sales qualification.

Before freeze, actual retained evaluation passed 95/95 fields across all 16 cases and ten categories, with zero populated expected-null values. Six same-byte imports in both source orders added only six manual job receipts; every other checked table hash, including complete need rows and timestamps, remained identical. Sixteen saved snapshots also remained stable on unchanged evaluation. Final candidate receipts repeat these gates after freeze. R1 preserves a valid admission basis and its associated rationale while still repairing absent/stale provenance and reopening needs; initial and persisted admission use identical success wording without weakening full-basis comparison.

## Candidate gates and operational limits

Freeze source and explanatory documentation before `CI=true pwsh -NoProfile -File scripts/check.ps1`, using a fresh application database and a separate disposable `_test` database. Require locked dependency audits, Ruff/format/mypy, repeat migrations/schema drift, backend tests, web type/build, browser regression, exact-head GitHub CI and independent review. On the retained copy, verify authenticated actual cards/citations at desktop/tablet/mobile sizes, unauthenticated denial, replay, snapshots and PostgreSQL/API/web restart persistence. Bind every receipt to the exact SHA; earlier counts do not substitute.

Migrations `0035_reconciled_identity` then `0036_buying_chain_corrections` are required before a separately authorized rollout. Validate additive migrations on a restored copy. Rollback may restore a compatible prior app while retaining additive tables/history; do not downgrade/drop schema or clear jobs, reservations, receipts or history.

`OPPORTUNITY_ENRICHMENT_ENABLED=false` defaults off the expanded planner without disabling the UI. Autonomous research, providers/models, saved browse and public research have separate controls. Verify deployed flags independently. Live-provider acceptance, activation cost and production latency remain UNKNOWN/BLOCKED pending separate authority and evidence. This record authorizes no deployment, activation, production write or merge. Milestone A and launch requirements in the [Finish Contract](../../.agent/FINISH_CONTRACT.md) remain open.

## Preserved failures

Earlier F6C remains `PARTIAL_FAILED_BOUND`: 11 completed GETs exceeded its six-request ceiling, a timeout's network disposition was unknown, five raw snapshots were overwritten, and no missing-category Need IDs resulted. It is not acceptance evidence. F17 used a fresh owner-authorized investigation. Its initial 18-call connector allocation exceeded by one attempted call; three internal errors have unknown billing/network effects and 28 credits are known from successful responses. No refund is claimed. Primary recovery retained seven successful HTTP bodies from eight GET attempts plus one HEAD. Original bodies, excluded anonymous/unspecified context, failed receipts and corrected publisher-link provenance remain outside Git. Research connector credits are separate from application model calls.
