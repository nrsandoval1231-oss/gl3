# GL3-020 — Runtime recovery validation

Date: October 1, 2026. Local development acceptance on `feat/gl3-020-runtime-recovery`, based on merged main `197883b`. No production launch gate is closed by this report.

## What changed

- Added `gridlens.jobs.runtime status`, `reconcile` and explicitly selected `check` commands. Status uses a read-only transaction; reconciliation preserves existing health/jobs/content. Selected checks reuse the normal fenced worker and active jobs, honor backoff/live leases and leave unrelated queued/expired jobs untouched.
- Fixed RRC month selection to use the publisher's America/Chicago calendar. At 01:00 UTC October 1 it was September 30 in Texas, so August EOM remained the required prior-month product. The old UTC selection requested an unpublished September EOM. Missing-snapshot errors now include the filename. Required official EOM, framing, identity, freshness and request bounds remain enforced; actual post-Texas-midnight publication gaps still fail visibly.
- Fixed unchanged grouped-permit replay rotating the saved admission citation and updating opportunity timestamps. A saved basis is retained only if its linked evidence, current accepted interpretation, project/activity and current admission policy still support it. Invalid/outdated bases refresh.

No new schema, source, queue framework, qualification policy or frontend behavior was introduced. Existing pending migrations 0008/0009 were applied to the available application database before collection.

## Current runtime proof

Initial inspection found 13 persisted overdue source definitions, no jobs and no observations/evidence/projects/needs; the documented isolated `gl3_019_live` database is absent from this cluster. Registry reconciliation inserted the missing Houston/RRC definitions and synchronized the existing definitions in place, without reset or credential replacement.

All **15 enabled sources completed genuine live ordinary-worker checks** in the configured application database. Source observations were discovered by the existing bounded queries, without project-name seeding. Structured, HTML/feed and public PDF paths were exercised; Georgia retained 38 companion documents and Federal Register one eligible PDF.

| Source | New retained observations | Accepted permit observations |
|---|---:|---:|
| austin-building-permits | 2329 | 77 |
| chicago-building-permits | 1312 | 16 |
| construction-dive-news | 10 | Context |
| dcd-news | 20 | Context |
| federal-register-eis | 74 | 0 |
| georgia-air-draft-title-v | 19 | 9 |
| houston-weekly-permits | 1543 | 0 |
| manufacturing-dive-news | 10 | Context |
| mjbizdaily-news | 30 | Context |
| nc-commerce | 15 | 0 |
| ogj-exploration-news | 25 | Context |
| seattle-building-permits | 87 | 1 |
| taylor-development-newsflash | 25 | 0 |
| texas-rrc-drilling-permits | 1904 | 1880 |
| utility-dive-news | 10 | Context |

The accepted-observation column is not a count of unique project cards. Houston lacks verified issuance/current-status semantics and produced zero Signals. Supplemental feeds remain research context.

Final persisted totals: **7,413 observations, 7,452 evidence versions, 1,981 projects and 1,981 power needs**. Authenticated API returns **1,981 active Signals, zero Prospects and zero Leads**; all active needs retain UNKNOWN required MW and supply. There are zero duplicate observation identities, evidence versions, project identities, project/activity needs or buying-chain claim fingerprints, and no pending/failed interpretations.

The initial RRC failure remains in the receipt; recovery reused that same job on attempt two and retained 1,904 observations, 1,880 drill/reentry/recompletion Signals and 24 administrative records without admission. Current source health has no failure error.

## Replay defect and repair

The first strict replay returned zero new/changed records and unchanged evidence/project counts and morning digest, but the full need digest changed. Three real Austin phase permits (`2026-117984 BP`, `2026-117983 BP`, `2026-117982 BP`) support one grouped need. Reassigning its basis for each unchanged permit rotated the citation and changed `updated_at`.

An extended integration regression failed on the prior implementation. It now snapshots every PowerNeed column across normal and reversed permit order, verifies stable citations/timestamps, and proves an outdated policy can still be repaired. The repaired live replay succeeded for Austin (2,329 unchanged), RRC (1,904), Houston (1,543), Chicago (1,312) and Georgia (19), with **identical full retained content digests and identical morning digest**. The comparison does not omit PowerNeed.updated_at or admission_basis. Only Interpretation retry bookkeeping is excluded by the existing semantic digest policy.

## Validation

- Ruff (including migrations), mypy (47 source files), **427 backend tests passed / one existing missing-fixture skip**.
- Applied/repeated upgrade to head and schema drift check: pass. No new migration.
- Frontend typecheck and production build: pass; generated contracts unchanged.
- **11 repository Playwright checks passed** against the populated runtime, including real authenticated desktop/mobile browse, detail/back/search, source health, air-document context and data-center enrichment. Other interaction scenarios use explicitly synthetic API fixtures. The API was restarted with final code before the final browser run. System Chromium ran with its sandbox enabled; existing assertions/timeouts were unchanged.
- Unauthenticated health request: 401; authenticated login/health/browse: success. All returned Signals have authoritative admission origins.
- Independent Sol review/re-review: PASS on the exact code/test hashes in [the review manifest](../../.agent/artifacts/GL3-020/REVIEW.json). Final code/test hashes were checked against that manifest.
- A 7,075,353-byte custom-format runtime backup is retained locally. This is backup capture, not a new restore test or managed backup service.

The first browser run while RRC was actively adding records failed two list-consistency checks; unchanged tests passed after ingestion settled and again after the citation repair. The initial failed strict replay, browser contexts and successful receipts remain in ignored `.artifacts/gl3-020/`. Desktop permit facts and mobile source-health screenshots were manually inspected; no exhaustive device coverage is claimed.

Source hashes/counts, job IDs, first failure/recovery and replay fingerprints are in [the evidence receipt](gl3-020-runtime-evidence.json). Raw source probes, source bodies, logs, backup and screenshots remain ignored; credentials were neither printed nor committed.

## Boundaries and next slice

Manual real checks and development worker operation are established. Durable managed scheduling, 7:00 a.m. Chicago refresh, seven consecutive reliable daily cycles, alerts, managed backups/restore and production hosting remain open. The other ten sources have first-pass proof in this slice; unchanged live replay here covers the five primary permit/regulatory sources. National completeness, dedicated commissioning acquisition and Prospect/Lead evidence remain unproven.

RRC's first ingest took about 18 minutes in this executor. Inspection found a full project-candidate scan and repeated incoming-observation classification inside each new-record matching pass. The proposed [matching-performance packet (now deferred GL3-022)](../../.agent/packets/GL3-022.md) addresses that measured bottleneck while preserving every identity decision and evidence/tier rule. It is proposed work, not an implemented performance improvement.
