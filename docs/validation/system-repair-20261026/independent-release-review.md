# Independent commercial release review

Reviewer: Astra independent reviewer. Methodology recorded: **2026-10-26 12:17 UTC**, before commercial coverage results were supplied to the reviewer.

## Authority and current decision

The latest owner directive conditionally authorizes merge and deployment **only after all commercial P0, real-corpus browser, engineering and production-safety gates pass**. It supersedes the earlier blanket release prohibition, but does not turn pending gates into approval. The prior [engineering review](independent-review.md) remains a separate historical receipt.

**Release decision: NOT ACCEPTED — commercial and production-readiness evidence is pending.** This is an evidence hold, not a rejection of the previously accepted engineering baseline. No production mutation, paid-provider call, merge or deployment was performed by this reviewer.

Baseline `29c4fe085cd261c19c4aeb7b1b4cca4dc538a006` is clean and application-source equivalent to accepted `b71306f`. The reviewer independently checked that source diff and [CI run 40267075523](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40267075523). Its exact head and successful conclusion match. Backend job logs independently retrieved through the GitHub connector report **3,101 passed, 1 skipped**, **120 browser regressions passed**, Ruff success and mypy success across **173 source files**. These checks do not establish commercial acceptance or the four real-corpus scenarios below.

## Prospective commercial methodology

The lead proposed the following coverage minimums before scoring; the independent reviewer accepted them with the definitions below. **These numbers are reviewed release minimums, not thresholds supplied by the owner, production-wide performance estimates or statistical confidence claims.** They require broad company attribution, useful named outreach for a majority of the sample, and a substantial set of project-specific actionable results while keeping precision and provenance strict.

| Gate | Required result |
|---|---|
| Genuine cohort | 25 distinct evidenced physical sites in TX/OK/NM, selected from the available real evidence corpus and frozen before research/scoring; no synthetic fillers or favorable replacements |
| Eligibility and power basis | The basis for the inclusive 300 kW floor is explicit and follows the existing qualification policy; facility/IT capacity is never relabeled as activity-specific temporary demand |
| Claim integrity | All 25 records are adjudicated; every positive field has accurate attribution, citation and type. Zero invented identity, MW, residual gap, assignment, authority or verification claims |
| Supported company identity | At least 20 of 25 projects |
| Relevant named professional with usable published business method | At least 15 of 25 projects |
| Directly project-connected buying-chain contact with usable method | At least 10 of 25 projects |
| Commercially actionable result | At least 10 of 25 projects under the definition below |
| Real persisted browser scenarios | All four scenarios below pass against the reviewed candidate and genuine persisted corpus |

Each record must expose company, distinct project/site, deduplication decision, source evidence, typed MW assertions, need-date/timing, duration, rental relevance, buying organization, contact method and verification basis. Fields are explicitly supported/verified, inferred, unknown or conflicting as appropriate. An inference must retain its assumptions and cannot be presented as a source quotation or independent verification. Missing values and failed research stay in the denominator. Source freshness is evaluated from actual source observation and published dates; a timestamp is not manufactured to meet a gate.

An actionable result requires a supported company/site and buying organization, **genuine source-supported temporary/rental-power relevance plus supported current/future timing or an ongoing constraint**, and a usable, role-relevant, cited business contact method. Merely filling the need or timing field with UNKNOWN does not satisfy actionability. An unknown residual gap remains unknown. These metrics do not promote a record to Lead or bypass existing qualification rules; no sales-ready classification is allowed without actionable contacts and the other required qualification evidence.

A named corporate professional is not automatically directly assigned to a project. The ten-project direct-contact gate requires evidence connecting the person to that physical project or its relevant project-specific buying process. It does not establish purchasing authority unless that stronger claim has explicit evidence. Published email/phone attribution is distinct from independently verified mailbox deliverability or reachability. No numeric mailbox-verification minimum is imposed without an authorized supported verification method; unsupported verification claims fail the integrity gate.

Coverage denominators are projects. Unique companies, people and methods must also be reported. A corporate contact reused across projects needs each project's buying-organization linkage and does not satisfy the direct-project gate merely because the company owns those sites. The sample should cover data centers, oil/gas, utilities, construction, commissioning and bridge-power use cases where genuine sources support them; overlapping use cases do not create extra projects. The frozen cohort manifest must document selection, exclusions, evidence provenance and any representativeness limits.

## Separate retained-candidate diagnostic

The coordinator additionally requested a frozen 25-row diagnostic drawn from retained actual workbook candidates in an isolated clone. The reviewer accepts this as useful failure measurement, **not as the 25-opportunity release cohort**. Report its dataset kind, exact source-row IDs/provenance, activation state, missing primary citations, supported versus unverified fields, planner outcomes/retries, costs and canonical counts separately. Retain failed candidates rather than replacing them with favorable results. Do not promote unverified assertions or invent a published generation to make the existing benchmark execute.

The restored staging inventory is coordinator evidence: four batches and 4,520 inactive rows survive, while original XLSX files are unavailable in the resumed filesystem. Retained display text `Link` is not a dereferenceable source URL. Whether the missing original cells contained hyperlink targets must not be invented from that display text. The six-project Austin acquisition and fixture databases do not supply the requested qualifying denominator. Candidate failure rates cannot be relabeled as verified-opportunity contact coverage or used to close the release gate.

## Four real-corpus browser gates

1. **Data center:** a genuine persisted project exposes owner, gap or its explicit limits, timing, buying organization and cited contacts.
2. **Midstream/compression/processing:** an actual project exposes supported power assertions, physical location, customer and rental relevance.
3. **Bridge power:** genuine evidence establishes delayed energization, temporary supply or a utility constraint; the product must not infer bridge demand solely from facility capacity.
4. **Contact to action:** a source-backed relevant contact has a usable outreach action with correct attribution, freshness and verification limits.

Use native Chrome where available and record the candidate revision, dataset manifest, URLs, viewport, screenshots/traces and observed result. A fixture, mocked response or preexisting generic browser regression does not substitute for these four persisted-corpus cases. The scenarios may share legitimate cohort members, but each requirement must be independently demonstrated.

## Production readiness and final review

Before release acceptance, provide the current production revision/schema/data inventory; an actual backup and demonstrated isolated restoration; reviewed additive migration and privacy-compatible rollback; preservation/idempotency/deduplication checks for evidence, contacts, corrections and source imports; and observed budget/recovery/configuration checks. Workbook assertions remain isolated until separately authorized admission through the established evidence/qualification path. Neither a new staging row nor a successful test creates commercial truth.

The independent reviewer will inspect the **final integrated candidate**, all 25 adjudications, the four browser receipts and production-readiness evidence before accepting or rejecting release. A changed source candidate requires the appropriate final engineering validation. Post-deployment service, commercial behavior, data-preservation and exact-revision receipts remain required after any authorized release. Pending access or missing evidence is a blocker, not an inferred pass.

## Interim source and repair readback

Application candidate reviewed: **`8b25d888211c90ed93b9188c698a89ec3f938277`**, including the complete source delta from baseline `29c4fe0`. **No remaining implementation blocker was found in this delta.** This accepts the source review, not full regression or commercial release. Exact-candidate full backend/browser gates and the commercial/production requirements above remain pending.

The reviewer independently checked integrated contact source/tests against `20198b1d`, and the workbook source/tests against `c776934c` plus formatting. Both files changed by formatting commit `8b25d88` have identical parsed Python ASTs before and after formatting. The reviewer ran the exact integrated workbook, frozen-selection and JETI unit suites: **32 passed in 10.07 seconds**. No database tests or production mutations were performed by this reviewer.

The last parser resource finding is **closed** in integrated `5578048`, retained by candidate `8b25d88`. Previously, the relationship XML byte limit and expanded target-cell count did not cap aggregate URL bytes emitted across cells. A small independent reproduction with a 4,096-byte input metadata budget emitted 10,210 URL bytes across ten rows; scaling a shared long target could amplify serialization/storage substantially. The fix checks cumulative UTF-8 target-byte length multiplied by expanded cells against a separate 16 MiB budget before expansion, across all ranges and sheets. Eight focused checks passed independently in the builder revision, followed by the exact integrated suite above.

- Integrated JETI transport change `b766a536` enables the configured runtime proxy and CA environment while preserving the fixed HTTPS endpoint, exact host allowlist, redirect rejection, TLS verification and response/record limits. The reviewer independently ran its five transport tests: **5 passed**. A successful index acquisition does not establish physical sites, qualification or contacts.
- Workbook changes `82f029a`, `017c2d5`, `4644c6b` and `47e2c531` retain external OOXML hyperlink targets as untrusted raw metadata, without fetching targets or evaluating formulas. Independent review reproduced a valid range-reference crash and found a reversed-range cumulative-budget bypass; the last two changes close those findings with bounded expansion and ordered positive Excel coordinates. Independently run parser/selection checks passed **25 tests** before the final coordinate-validation change; subsequent hyperlink and exact reversed-range checks passed **7 tests** at `47e2c531`. The first attempted parser test invocation failed during setup because required settings were absent; the rerun used dummy settings and no database connection. Original workbook files remain unavailable, so this reproduction cannot establish what their original hyperlink targets were.
- Contact discovery change `20198b1d` reuses current company-linked organization citations as untrusted acquisition seeds and prioritizes known contact refresh URLs. Review found shallow mutation of historical citation objects and overly broad identity-source reassignment in the initial work. The final change copies citation dictionaries and rebinds only the precise old linked source when the refreshed document still contains its exact relationship quote. Reviewed planner/worker/projection regressions cover a matching publisher with retained relationship, an unrelated publisher, and a company page that removed the project relationship, with historical citations preserved. The builder reports **36 isolated PostgreSQL tests passed**; the independent reviewer did not run those database tests. No remaining blocker was found in this narrow source delta; integrated validation is still required.

Independent retained-source checks confirmed the Oracle Project Jupiter announcement describes a **proposed** utility agreement for late-stage construction, initial commissioning and emergency backup, while Searchlight reports buildings without power and unresolved supply arrangements. Neither supplies temporary MW, a residual gap, supply dates/duration or an actionable buyer method. The retained Crusoe impact-report PDF explicitly describes Abilene natural-gas turbines providing temporary bridge power while grid upgrades catch up; this establishes a reported bridge configuration, not current unsatisfied procurement or temporary demand equal to campus capacity. These are useful real research cases, not a substitute for the frozen qualified cohort or contact gates.

The reviewer independently matched the retained Oracle, Searchlight and Crusoe raw hashes to the source lane's receipts and checked the quoted passages in the actual HTML/PDF bodies. Oracle SHA-256: `c8443f3ea5ed8018bd5d85d54471f05b68dafa543d53b02cc95d359cb6c419fe`; Searchlight: `ae1b80e1c2d99e0328cfd0ff7e79b067cf33e0e04dd00250cd6ac0832537e56d`; Crusoe: `38ca3db4c94206be9e8b2ee1e3b5fa1239b00948c50b3ac0e102e6d7f1773619`. Retrieval timestamps and public URLs belong to the source-candidate receipt. No commercial threshold or production-readiness gate is closed by these checks alone.
