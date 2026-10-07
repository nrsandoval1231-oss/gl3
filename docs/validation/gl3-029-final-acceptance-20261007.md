# GL3-029 final local acceptance — October 7, 2026

**Historical premerge receipt.** PR24 merged at `94c3acb`. Three P1 review comments posted immediately before merge required a separate [scheduler/retry repair](gl3-029-postmerge-repair-20261007.md). The results below remain valid records of the original candidate; they do not establish correctness of the repaired boundaries or deployment.

**All required local validation gates pass.** Full browser: **42/42 passed**. Backend: **1,232 passed, one optional skip**. The final unchanged five-category validator passes **5/5** under the owner-authorized fresh-corpus amendment. Merge is authorized subject to current remote-head/protection checks; this pre-merge receipt does not itself claim a merge or deployment.

Tested repository head: `e42b4200c618155dbbf7aa5dd1d14c47cac2cf29`.
Last product change: `aa7a3464aa8f1dc681e6c37f08ed6d60df00a483`.
Source/config fingerprint: `e7c6fbd2674f275a94cda565a4faf83348c51c5be4cda4865219d0ad38cf825a`.
Publication descendants change documentation/procedure records only. Exact per-case questions, queries, source checks, admission decisions, budgets, runtimes, before/after states and artifact hashes are in the [safe JSON report](gl3-029-final-acceptance-20261007.json).

## Exact final checks

| Gate | Result |
|---|---|
| Full backend suite | 1,232 passed, one optional NC live-probe skip, one existing warning; 143.73 seconds |
| Validator subset | 71 passed; overlaps the full suite |
| Ruff / mypy | Passed; mypy checks 77 source files |
| Frontend typecheck / build | Passed |
| npm audit, high threshold | Passed; zero vulnerabilities |
| Full Playwright suite | 42 passed, zero failed/skipped/flaky; 42.65 seconds |
| Actual autonomous-research browser | Five groups passed against the final real corpus, no API mocks |
| Migration clean/existing/repeated/drift | Passed at 0014; all 28 table inventories preserved |
| Final corpus and legacy backup/restore | Exact full-table inventories preserved |
| OpenAPI | Exact match |
| Immediate same-input replay | Zero questions and identical before/after state hash |
| Historical freshness boundary | Zero while fresh; two expected O&G retries after the persisted backoff, all rolled back |

Full browser includes all six original live journeys, with their assertions unchanged: desktop browse, mobile health/inbox/history, Georgia equipment context, Chicago/Georgia buying-chain enrichment, saved call outcome across reload, and real conflicts/bounded refresh/mobile history pagination. The real worker processed the browser's queued refresh successfully; no worker errors or active jobs remain.

## Final autonomous corpus run

The actual scheduler/worker ran 04:39:08–04:39:27 UTC on a pristine isolated restore of the authorized fresh public corpus. Baseline: 15 Evidence rows and 14 Signal needs; selected pursuits were two ACTION NOW, two RESEARCH and one WATCH. Original PR23 retained recovery is superseded, not passed.

| Case | Before → after | Tier | Acceptance |
|---|---|---|---|
| 811 Clayton Ln, Austin data center | ACTION NOW → ACTION NOW | Signal → Signal | Existing narrow owner no-question/no-change exception |
| 833½ E Braker Ln, explicit temporary-power permit | ACTION NOW → ACTION NOW | Signal → Signal | Existing narrow owner no-question/no-change exception |
| 400 S La Salle, Chicago conversion | RESEARCH → RESEARCH | Signal → Signal | Two blockers meaningfully investigated, UNRESOLVED |
| RRC0919039, Sage/Pedro West EF1H | WATCH → WATCH | Signal → Signal | Retained native evidence inspected; two blockers UNRESOLVED |
| 2800 S Ashland, low-quality MEP scope | RESEARCH → RESEARCH | Signal → Signal | Two blockers meaningfully investigated, UNRESOLVED |

Six blockers attempted, six unresolved, zero partial/resolved/failed, no commercial or tier transitions. Three pursuits were investigated through explicit validation-origin jobs; this is not an unattended automatic-run count. Two native network retrieval attempts, zero executed search/model calls, $0 provider cost, four duplicate-work-avoidance events, median latency **1.2575 seconds**. All 15 prior Evidence rows and evaluation history remain intact. Exact replay hash: `9b5f4cf96a602e1bfac8661877e5e6408727ae72d7f81a112bab8ccecc1ceaf7`.

Meaningful bounded UNRESOLVED is explicitly permitted by the original specification and amendments. The separate positive new-fact-resolution objective remains unproven; unavailable providers are not presented as exhaustive negative search proof.

## Recovery of the live browser corpus

El Paso replayed a verified retained HTTP-200 response through normal ingestion. Georgia required the narrow `Company` legal-name normalization correction, retaining exact station/city checks; QTS ATL3 then entered through ordinary canonical ingestion. Required MW remained null, supply Unknown, and no invented person assignment or buying authority was introduced.

At 04:30:46 UTC, owner message `Sentinel_e58b307f03488191abf3194a12196ad4` explicitly authorized bounded anonymous TDLR public-record search after being told the original no-forms rule and RRC-only exception. The existing worker then made **43 official-source fetches across 11 candidate runs**, with zero models, within its 350-second/48-request/12-candidate batch caps. Eleven of those requests were the approved public search POSTs; all retained response hashes were independently checked.

Kramer is **Call now / Signal**, with purchasing authority still Unknown. Clayton and Stassney are **Verify first**, preserving the city/state EV-charging and manufacturing/office conflicts. These legacy labels remain separate from commercial triage states and qualification tiers.

History pagination required more than ten saved pursuits. Three bounded discovery GETs were used: temporary-power, generic new-construction, then light-manufacturing records. Three initially selected temp-abbreviation records were rejected by unchanged admission; generic construction results were also rejected in offline assessment. They were not promoted merely to fill history. Three genuine manufacturing permits were then admitted/researched: `2026-015271 EP`, `2026-015270 EP`, `2022-015372 EP`. The two Howard Lane records expressly describe different phases with separate stable IDs; they are not merged by address. Eleven genuine saved pursuits support unchanged page-two assertions. This is disclosed fresh test-data preparation, not historical PR23 proof.

The browser wrote one explicitly labelled validation-only call note and selected “Not reached”; no call was placed. All earlier Evidence, Observations and notes are preserved; six new Evidence rows came from the additional canonical imports. The original/source databases were not reset.

## Review and limits

Separate adversarial review verified the Georgia identity fix and rejection boundaries, genuine legacy source provenance, phase identities, conflict/timing semantics, exact response hashes, bounds and unchanged qualification. No material issue remained. Final independent report review verified all 30 artifact hashes and supports local source/test merge readiness; remote head/protection checks remain separate. Earlier failures and corrected diagnostic harness receipts remain available; nothing was silently waived.

No external commercial outreach occurs. No email, phone call, CRM export, login, purchase, CAPTCHA bypass, credential configuration or paid provider activation occurred. The explicit RRC and TDLR permissions cover public-data acquisition only. Cloud deployment remains a separate milestone, and unattended production operation is not proven. The focused Firecrawl/new-fact discovery limitation remains documented.

Historical bounded preparation and actual-worker browser procedures are archived as non-executable `.py.txt` records under `docs/validation/procedures/gl3-029-legacy-*` for review. Raw source responses, archives, private auth files and browser traces remain ignored in the saved executor.
