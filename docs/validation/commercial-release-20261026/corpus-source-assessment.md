# Real source corpus assessment

Date: 2026-10-26. Scope: retained public-source evidence and benchmark readiness for the commercial release. No production database, provider, or workbook data was written or activated.

## Frozen eligibility result

The target is 25 distinct physical projects in TX, OK, or NM. Each counted project must have source-supported project identity and physical location, and the source evidence must establish the applicable eligibility floor (300 kW) without treating facility capacity as temporary demand or a residual gap. Selection is frozen before contact/actionability scoring. This assessment finds **0 benchmark-qualified projects** from the currently accessible retained source corpus. No partial cohort is presented as 25.

The four source workbooks are described in [the reconciliation report](../system-repair-20261026/workbook-reconciliation.md), including hashes and row counts. Their files are unavailable under `/workspace` in this executor, so they could not be re-read or independently activated here. The report states that the lead-list layouts lack site addresses for most rows; no mapped field establishes activity-specific temporary demand, committed supply, need date, or duration. It also records 67 cross-workbook name/state groups with disagreements. Workbook rows alone therefore do not pass the project and power evidence threshold.

The retained [GL3-016 JEV source corpus](../gl3-016-jev-corpus.json) contains 81 source-backed records. Only two Texas data-center records appear in the retained state classification:

| Candidate | Source-supported facts | Eligibility disposition |
| --- | --- | --- |
| Project Mustang, Taylor | City archive says the employment-center/data-center application was withdrawn; page describes a proposed site near 3301 FM 112. Retrieved 2026-10-26, 283,012 bytes, SHA-256 `cc87d214ba5133e7f51994790e75ceac17624d58989eaaa531fc2e46863e88dd`. [City archive](https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442) | Excluded: withdrawn. No supported MW, temporary power gap, or need timing. |
| Project Comal, Taylor | City page states: “On March 26, City Council approved an employment center plan for a data center at 1051 CR 401.” Retrieved 2026-10-26, 269,899 bytes, SHA-256 `c0e546499ae0e64019c2d8b70a199c49db4f6d0c714b979a4c6be578c8320dfe`. [City page](https://taylortx.gov/m/NewsFlash/Home/Detail/2032) | Candidate for future research only. The retrieved page supports project identity, location, and approval; it does not establish MW, temporary need, residual gap, or need timing. Not counted as power-floor eligible. |

The six-project Austin verifier cited in prior validation is not available as a database artifact in this release checkout. Historical Austin permit references include multiple permits at the same address and routine/maintenance scopes; they cannot be counted as distinct qualifying projects without fresh evidence and site-level adjudication. No database connection was attempted: the only discovered local connection file points to database `gridlens`, not the isolated verifier database.

## Benchmark and activation status

No candidate selection was frozen for scoring because the eligible cohort is empty. The existing retained-evidence benchmark script requires a current published generation and a deliberately identified loopback database; neither the reported Austin verifier database nor the four workbooks is available in this executor for a valid run. No contacts, power, scenario coverage, or commercial-actionability rates are inferred from historical reports. Missing values remain unknown.

| Measure | Result |
| --- | --- |
| Requested distinct eligible projects | 25 |
| Accessible retained source records examined | 81 |
| TX/OK/NM data-center candidates retained | 2 (1 withdrawn; 1 lacks supported power floor and timing) |
| Frozen eligible cohort | 0 |
| Scored projects | 0 |
| DC / midstream / utility-bridge / contact-to-action scenarios | Not benchmarked |
| Contact discovery, independent verification, buyer relevance | Unknown / not measured |
| Production writes or paid calls | None |

The next valid run needs the actual workbook files and isolated staging database, plus fresh permitted public evidence sufficient to resolve at least 25 distinct physical projects and source-supported eligibility. If fewer than 25 qualify, report the exact count and gaps without filler, then benchmark only after the cohort and citations are fixed.
