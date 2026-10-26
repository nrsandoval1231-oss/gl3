# Real source corpus assessment

Date: 2026-10-26. Scope: retained public-source evidence and benchmark readiness for the commercial release. No production database or paid provider was used. Workbook rows remain in isolated staging; only the retained Crusoe source was ingested into its isolated candidate database.

## Frozen eligibility result

The target is 25 distinct physical projects in TX, OK, or NM. Each counted project must have source-supported project identity and physical location, and the source evidence must establish the applicable eligibility floor (300 kW) without treating facility capacity as temporary demand or a residual gap. Selection is frozen before contact/actionability scoring. This assessment finds **0 benchmark-qualified projects** from the currently accessible retained source corpus. No partial cohort is presented as 25.

The four source workbooks are described in [the reconciliation report](../system-repair-20261026/workbook-reconciliation.md), including hashes and row counts. Although their files are unavailable under `/workspace`, the restored isolated database `gridlens_repair_workbook_actual_test` contains all four staged imports: 4 batches, 4,520 rows, 4,520 activation records (all inactive), and 4 staging events. It has no canonical projects, power needs, or evidence records. A read-only review found 3,380 project-class rows, including 518 rows across TX/OK/NM and 517 unique normalized project-name/state groups. Of those, 462 rows carry a numeric `facility_demand_mw` of at least 0.3. That field describes facility power, not proven activity-specific temporary demand or residual gap. All 517 territory rows have source columns whose retained cell value is the display text `Link`; none contains a URL target. Consequently no workbook row supplies a dereferenceable citation in staging, and these rows cannot be safely activated as qualifying projects. The prior report also records 67 cross-workbook name/state groups with disagreements.

The retained [GL3-016 JEV source corpus](../gl3-016-jev-corpus.json) contains 81 source-backed records. Only two Texas data-center records appear in the retained state classification:

| Candidate | Source-supported facts | Eligibility disposition |
| --- | --- | --- |
| Project Mustang, Taylor | City archive says the employment-center/data-center application was withdrawn; page describes a proposed site near 3301 FM 112. Retrieved 2026-10-26, 283,012 bytes, SHA-256 `cc87d214ba5133e7f51994790e75ceac17624d58989eaaa531fc2e46863e88dd`. [City archive](https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442) | Excluded: withdrawn. No supported MW, temporary power gap, or need timing. |
| Project Comal, Taylor | City page states: “On March 26, City Council approved an employment center plan for a data center at 1051 CR 401.” Retrieved 2026-10-26, 269,899 bytes, SHA-256 `c0e546499ae0e64019c2d8b70a199c49db4f6d0c714b979a4c6be578c8320dfe`. [City page](https://taylortx.gov/m/NewsFlash/Home/Detail/2032) | Candidate for future research only. The retrieved page supports project identity, location, and approval; it does not establish MW, temporary need, residual gap, or need timing. Not counted as power-floor eligible. |

The restored isolated Austin verifier database `gridlens_verify_austin_20261026` has six projects and six power-needs records, with no evidence packages. Read-only linkage to the six permit observations finds five temporary-power activity records and one facility expansion. Two permits describe temporary underground work for Project Toaster's utility plant and office foundations at the same address; they are one physical project, not two. The remaining records describe a school remodel meter loop, event generators/distribution, an ordinary warehouse, and a temporary 600A/480V loop with phase/load details missing. These are not six distinct projects that establish the 300 kW floor and current/future constrained demand. The public permit citations remain useful source leads, but the Austin set is separate from the frozen native source-project record cohort.

An isolated working clone named `gridlens_release_corpus` was created from the actual workbook staging database before activation work. Read-only verification confirms it contains the same four batches, 4,520 retained rows, and 4,520 inactive activation records, with zero canonical projects, power needs, or evidence records. It remains staging-only while the genuine public-source cohort is researched and frozen.

## Native retained-source case

The publisher-linked Crusoe 2025 Impact Report was checked against its pinned SHA-256 (`38ca3db4c94206be9e8b2ee1e3b5fa1239b00948c50b3ac0e102e6d7f1773619`) and imported from the retained local PDF through the existing fenced `retained_import` worker in the separate isolated database `gridlens_release_corpus_test`. The adapter ran with model processing disabled and made no paid calls. It created one source observation, one evidence record, one accepted interpretation, one Signal, one active `bridge-power` need, and one project:

| Project | Project ID | Source-backed assertion | Explicit unknowns |
| --- | --- | --- | --- |
| Abilene Stargate campus, near Abilene, TX | `ed50a4a7-ad0b-441f-91fe-48b76c6dc760` | Crusoe reports natural-gas turbines provide temporary bridge power while grid upgrades catch up. The adapter retains this as an in-use configuration and says it is not an open purchase. Direct publisher-linked PDF at [the retained source URL](https://cdn.prod.website-files.com/6855c1aa175582ee23e0aa19/6aa975443d2a8405e214f067_Crusoe_2025_Impact%20Report2_web_optimized.pdf); extracted spans PDF pp. 2, 15–16, and 19. | Required MW, need start/end dates, duration, utility-ready date, committed supply, residual gap, project-connected contact, business contact method, and buying authority are unknown. The 300 kW floor is not established. |

The need is persisted as `Signal` with `required_mw`, `start_window`, and `duration` null and supply `Unknown`. Regional status is `ELIGIBLE` for TX only; this does not satisfy the power floor or commercial opportunity criteria. This is a real bridge-power scenario for browsing and source-grounded research, but it is not an actionable, qualified opportunity and does not add to the frozen native source-project record cohort.

## Frozen workbook candidate sample

Before contact research, a deterministic 25-row workbook sample was frozen in [frozen-workbook-candidates.json](frozen-workbook-candidates.json). It contains 13 TX, 6 OK, and 6 NM source-row assertions. Selection required a non-empty normalized project name, territory state, valid coordinate pair, no parser errors, and a project row; candidates were deduplicated by normalized project name/state and duplicate coordinates rounded to five decimal places. A stable SHA-256 ranking selected within each state stratum. The algorithm did not inspect contact or commercial outcomes. Each row includes workbook content hash, batch ID, sheet, row, and staged row ID.

All 25 remain `UNVERIFIED_WORKBOOK_SOURCE_ROW_CANDIDATE`, with qualification `NOT_ESTABLISHED`. The staged source cells contain hyperlink display text but no retained target. The four attachments are unavailable for reparsing in this checkout, so no citation target is reconstructed. The facility-power values remain unverified workbook assertions and do not establish the 300 kW qualification floor for temporary-power opportunity scoring. Timing, temporary-power relevance, committed supply, gap, buyer organization, contacts, and authority remain unknown.

A focused reproduction verifies that openpyxl streaming cells do not expose OOXML hyperlink relationship targets and that the prior parser would have dropped such targets if these workbook cells contained embedded hyperlinks. The original XLSX bytes are unavailable here, so it is unknown whether the 517 retained `Link` labels had actual targets. The parser now extracts external OOXML hyperlink relationships without visiting their URLs and stores targets in a separate raw metadata object while preserving displayed cell values. Bounded cell-range hyperlinks are expanded only after their target count and aggregate UTF-8 output bytes are checked; malformed or over-budget ranges fail visibly. A focused workbook test confirms `HYPERLINK()` formulas remain unevaluated. Relationship metadata and expanded target bytes are each capped at 16 MiB, worksheet XML scanning at 256 MiB, and targets at 100,000; over-budget input fails visibly instead of silently dropping links. Hyperlinks beyond the 300-column import window are not attached to imported rows. The retained workbook rows were staged before this fix; original attachments are needed to inspect or reparse their targets.

The native importer activates a row only when it has a canonical company/project match; the staged rows are unmatched because the clone has no canonical project records. There is no separate activation service that promotes imported rows to canonical project, need, or evidence claims. The frozen candidates therefore remain inactive, and no activation guard was bypassed.

## Benchmark and activation status

The read-only combined native intake now has a frozen 25-record source cohort in [frozen-native-cohort.json](frozen-native-cohort.json). It contains 21 Texas RRC W-1 permit records and four TDLR data-center projects, selected before contact research and independent of contact or power outcomes. Each record carries linked source/evidence IDs, hashes, excerpts, and source locations; RRC rows also retain the official snapshot filename, ordinal, sequence, and raw segment hash. The RRC portal URL is shared, and its county-code location is jurisdiction-level: distinct physical sites are unverified for those permits. This is a source-project diagnostic cohort, not 25 proven physical sites or qualified opportunities.

All 25 have unknown or unsupported source-linked activity relevance and unknown source-linked typed required power at the 300 kW floor. Need timing, supply gap, buyer authority, and contact research are also unknown/not adjudicated at freeze time. Current organization memberships are reported only as project-organization assertions. No direct contact or attributable-method claims are counted from historical buying-chain records. Therefore no eligible-opportunity cohort is yet established for commercial scoring. The separate workbook sample remains unverified. No contacts, power, scenario coverage, or commercial-actionability rates are inferred from historical reports. Missing values remain unknown.

| Measure | Result |
| --- | --- |
| Requested distinct eligible projects | 25 |
| Accessible retained source records examined | 1,729 eligible/cited TX native projects; 81 retained JEV records; 3,380 staged project rows; 1 newly imported retained report |
| TX/OK/NM data-center candidates retained | 2 (1 withdrawn; 1 lacks supported power floor and timing) |
| Frozen workbook source-row candidate sample | 25 (unverified; 13 TX, 6 OK, 6 NM) |
| Frozen native source-project record cohort | 25 (21 RRC permit records, 4 TDLR data-center projects; physical-site distinctness unknown for county-level records) |
| Frozen eligible genuine-opportunity cohort | 0 |
| Staged territory rows | 518 rows / 517 normalized project-name/state groups; all inactive, no retained source URL targets |
| Scored projects | 0 |
| DC-owner/gap, midstream, utility-bridge, and contact-to-action | One separate source-grounded Crusoe bridge-power Signal; frozen cohort actionability remains unadjudicated |
| Contact discovery, independent verification, buyer relevance | Unknown / not measured |
| Production writes or paid calls | None |

The next valid commercial benchmark step is contact research against the frozen project IDs, with no replacements, plus adjudication of physical-site identity where source location precision is coarse. Report commercial gates as unknown/failures when evidence is absent; do not infer temporary demand from facility power or qualify a site from a project record alone.
