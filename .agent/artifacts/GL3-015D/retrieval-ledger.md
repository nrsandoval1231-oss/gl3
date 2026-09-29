# GL3-015D retrieval ledger

All times below are retained-file UTC modification/retrieval times. The table hashes are SHA-256 computed directly from retained files. No credentials were used.

## Official RRC endpoints

- Dataset index GET: `https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/` → `rrc-download-index.html`.
- Public GoDrive listings GET: `https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml` for official folders: pending `0ad92a65-4212-49a1-98a7-d667a55fb497`, Drilling Permit Master + Trailer Daily `5f07cc72-2e79-4df8-ade1-9aeb792e03fc`, Wellbore Query `650649b7-e019-4d77-a8e0-d118d6455381`, Full Wellbore `b070ce28-5c58-4fe2-9eb7-8b70befb7af9`, and Completion Information `ed7ab066-879f-40b6-8144-2ae4b6810c04`. Captured listings are named by folder GUID; `daily-listing.html` is the selection session listing.
- Permit file selection: open a fresh public folder session, retain that session's `javax.faces.ViewState`, submit the standard single-row selection for published row 0 (`daf420.dat`) to the same GoDrive endpoint. Two separate sessions returned HTTP 200 `application/force-download`, 2,391,338 bytes; both SHA-256 values equal `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`. First completed about 2026-09-29 01:06:53 UTC; repeat about 2026-09-29 01:34:03 UTC. Listing claimed daily/nightly cumulative current-month archive.
- Official manuals fetched: drilling permit `https://www.rrc.texas.gov/media/zgccdjpi/drillingpermitmasterpluslatitudeslongitudes_oga049m_july1.pdf`; pending `https://www.rrc.texas.gov/media/pkgkvkcb/pendingdrillingpermits.pdf`; completion `https://www.rrc.texas.gov/media/ltudbyql/cmpldatasubscriptions_usermanual_20171101.pdf`; Wellbore Query `https://www.rrc.texas.gov/media/di1mm5or/og_wellbore_ewadefinitionmanual2013-10-30_subscription.pdf`.

## Retained raw source evidence (local, ignored)

Exact local directory: `C:\Users\nrsan\Nucleus\02_Projects\GridLens\gl3-015\.artifacts\GL3-015D\raw`. Root `.artifacts/` is listed in `.gitignore`; raw source files must remain untracked. Inventory names below are relative to that `raw/` directory. Ledger and sample metadata stay under `.agent/artifacts/GL3-015D/`.


| File | Bytes | SHA-256 | Retained UTC time |
|---|---:|---|---|
| `raw/0ad92a65-4212-49a1-98a7-d667a55fb497.html` | 302671 | `18106f1335e5574580df978688ae9fe1855e7d6f498c52f635c909978efd9366` | 2026-09-29T01:05:56.450732Z |
| `raw/5f07cc72-2e79-4df8-ade1-9aeb792e03fc.html` | 298699 | `19a4c7533aa8eb64c4b26eafb92f9398349813f09bb6efce0a424bd3cbf38995` | 2026-09-29T01:05:58.025836Z |
| `raw/650649b7-e019-4d77-a8e0-d118d6455381.html` | 102897 | `843b77554d91f22abfc8b0d429ca21012571c1d7d77c7ac6b2757dc636a97bf7` | 2026-09-29T01:05:59.128957Z |
| `raw/b070ce28-5c58-4fe2-9eb7-8b70befb7af9.html` | 25247 | `4aeda7c141d3b80a4002288302727a152db413653f98c7eb73c392b38ddd83f4` | 2026-09-29T01:05:58.841832Z |
| `raw/completion-data-manual.pdf` | 408177 | `ff7a8086c0e98ac76c7042c4f6c6a139a6db5ee59d5f78b6dddf74aaf8b0bb61` | 2026-09-29T01:31:43.209658Z |
| `raw/daily-listing.html` | 298699 | `d7283089c8d488e0e8cddb85ee0b48d77f134fbd7039bfa85a5b4009c7e29153` | 2026-09-29T01:06:53.604521Z |
| `raw/drilling-permit-daily-manual.pdf` | 162000 | `760a25367df8fb3bd7b240a41d9471953e2ee1eab1878d5367c673548adec874` | 2026-09-29T01:07:15.196714Z |
| `raw/ed7ab066-879f-40b6-8144-2ae4b6810c04.html` | 295913 | `e35816dff7e0722a02a6fb087dc668173cd0385e71464d7020ba71fa3a35ae25` | 2026-09-29T01:06:00.502496Z |
| `raw/pending-drilling-permits-manual.pdf` | 527431 | `ccac0371cc6ed737461e513147053ffda2b2fc118f6453b425622c3a2649a907` | 2026-09-29T01:31:43.771452Z |
| `raw/pending-last-page-response.bin` | 269 | `bd78dc46aefbd264ee7db23114451d004837b870a6c0175665fe2f3e2b64de33` | 2026-09-29T01:13:15.091225Z |
| `raw/pending-last-page-response2.bin` | 269 | `4021a668ab9ab1f4f38eda160ed74ab443d001a84a282031bea0fe754cfa3fc6` | 2026-09-29T01:14:02.275462Z |
| `raw/rrc-daily-permit-current-month-repeat.bin` | 2391338 | `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6` | 2026-09-29T01:34:04.353963Z |
| `raw/rrc-daily-permit-current-month.bin` | 2391338 | `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6` | 2026-09-29T01:06:54.125390Z |
| `raw/rrc-download-index.html` | 109439 | `d6a9db95abaa2478d4b4c40eafb03701bd50c05e4da46a3489ffe0865619ff37` | 2026-09-29T01:04:58.436640Z |
| `raw/wellbore-query-manual.pdf` | 106876 | `b6ad3c8556c45555d054f9b86d0dce77593147390c0ccce1ed12ac5708655264` | 2026-09-29T01:31:43.448580Z |

## Failed bounded probes / explicit limits

- Pending folder first listing showed 40,432 files. Two last-page selection attempts (2026-09-29 01:13:15 and 01:14:02 UTC) each returned only 269-byte ViewState XML, not an attachment. Responses are `raw/pending-last-page-response.bin` and `raw/pending-last-page-response2.bin`; current pending snapshot remains UNKNOWN. A prior browser click timed out. Stopped after these bounded attempts.
- Completion folder listing showed 2,050 ZIP files; initial page began 2022-01-01. No current ZIP downloaded: current completion snapshot UNKNOWN.
- Wellbore Query listing showed `OG_WELLBORE_EWA_Report.csv`, approximately 456.91 MB; statewide file intentionally not downloaded.
- Official RRC online query page warns automated volume retrieval can degrade its systems and characterizes query data as informational. No automated query or production pull performed; well-level production and first-production semantics UNKNOWN.

## Sample check

The retained daily file `raw/rrc-daily-permit-current-month.bin` has 29,494 physical lines, of which 29,459 are classified and 35 start with byte 0x85 (meaning UNKNOWN). The final bounded check inspected adjacent type-01/type-02 rows: 884 pairs, 884 status-number/sequence key matches. Earlier `sample-validation.json` dictionary-key summary (16 matches) was invalid due key collisions; it is corrected to the adjacent-pair result. Ten rows are listed in the sample report. Manual-to-observed offsets remain a parser-validation limitation.
