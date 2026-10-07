# GL3-029 fresh corpus regeneration — October 7, 2026

**Result: regeneration and local technical checks completed; commercial acceptance remains false. PR24 stays draft.** This is a new public-data corpus, not recovered PR23 evidence. The owner explicitly superseded original archive recovery with recreation. Historical R4 remains unchanged at its original dates and score. No deployment, unattended production operation, outreach, paid-provider enablement or credential creation occurred.

## Candidate and scope

Starting PR24 head: `ba959bdfedd799f82ddfe9543e7fbe5085509cd2`; remote main: `ec72912e5edfbae5d230cd443c7cc33652ccd3d2`. Frozen implementation/validation candidate: `f63eb62c28b5a24a37847cc151a70da077c5c629`, source/configuration fingerprint `7871609518176cf3e321b2bda23594b28a52a828548f090a6fcc7198ac60580a`. This report is a subsequent documentation-only receipt; it does not claim to have tested its own future commit.

The implementation already present in PR24 is reused unchanged. New tooling collects exact native permit records, uses registered sources and fenced PostgreSQL ingestion jobs, hashes complete database table contents for backup/restore, and executes explicitly partial diagnostics through the existing planner, bounded worker, admission, deterministic evaluator and replay checker. No product qualification, source authority, UI or general orchestration changes were made.

The unchanged full manifest validator rejected four cases with `Manifest requires five to ten explicit cases`. That rejection is retained. The subset runner sets `full_five_cohort_acceptance=false`, `retained_corpus_proof=false`, and original-corpus attestation false regardless of subset results. The diagnostic itself also failed its unchanged per-attempt acceptance checks. No gate was waived.

## Fresh acquisition and canonical corpus

Selection used current official Austin, Chicago, Seattle and El Paso permit records, with source-specific IDs and acquisition timestamps retained. Initial collection attempted 15 exact records under 30 seconds and 750,000 bytes per request: **14 collected, one failed**. A single bounded El Paso retry also failed with HTTP 403; no alternate access method was attempted. Scouting and collection are distinct from canonical admission. Rendered adapter JSON is labeled as rendered data, not raw HTTP bytes.

Canonical ingestion of the 14 acquired records produced **14 Observations, 14 Evidence rows, 13 Projects and 13 PowerNeeds/Signals**. Seattle `7077870-CN`, vapor-recovery control-room/site work, was retained but rejected as unsupported activity. No PowerNeed was manufactured for it. The aggregate ingestion receipt remains failed because the selected El Paso acquisition failed, even though all 14 supplied records were processed successfully.

The fresh grouped commercial baseline contains **six ACTION NOW and three RESEARCH cards**; multiple admitted Austin permit needs can be grouped. The four selected case evaluations contain two ACTION NOW and two RESEARCH pursuits. These counts are separate from the 13 canonical PowerNeeds.

Fresh archive SHA-256: `12286f372e8970e6a8bfdd3aa75ab8a8f791d7a0499c41f7f67fe404621b741d`.
Evidence inventory SHA-256: `7a1594f33a62e862121c137685f1fae1a6430ad075e1c65a4cc81987d8429d40`.
Schema: `0014_pursuit_research_questions`.

Source database: `gl3_regen_20261007_final`; research restore: `gl3_regen_20261007_r4`; separate migration and browser clones were used. All **28 public-table row inventories** match across the frozen-candidate backup/restore. Original workspace databases were not reset. Archives, full records and browser artifacts remain ignored under `.artifacts/regeneration/`; the [safe receipt](gl3-029-regeneration-20261007.json) records paths, sizes and SHA-256 hashes for 35 artifacts.

## Case outcomes

| Category | Real source scope | Before → after | Result |
| --- | --- | --- | --- |
| Austin data center | 2026-036762 EP, 811 Clayton Ln, modular data-center foundation/electrical scope | ACTION NOW → ACTION NOW; Signal → Signal | Accepted only under the existing narrow native-source, no-question/no-change exception. No research or promotion claimed. |
| Austin temporary power | 2026-127192 EP, 833 1/2 E Braker Ln, explicit temporary-power request | ACTION NOW → ACTION NOW; Signal → Signal | Same narrow exception; current public project contact supports discovery workflow, not Lead qualification. |
| Chicago conversion | 3451848, 400 S La Salle St, phase 3 office-to-data-center conversion | RESEARCH → RESEARCH; Signal → Signal | Phase and temporary-need questions remain UNRESOLVED. One queued stale-context question FAILED and its replacement completed. Strict case acceptance false. |
| Low-quality/unresolvable | 3428005, 2800 S Ashland Ave, older cooling/MEP scope without supported temporary need or reachable project contact | RESEARCH → RESEARCH; Signal → Signal | Same bounded unresolved outcome and one stale-context failure. Strict case acceptance false. |
| O&G | Seattle vapor-recovery and El Paso CNG-compressor candidates; additional bounded official-source scouting | No eligible admitted case | Missing cohort. Seattle admission rejected; El Paso exact retrieval HTTP 403. Federal Register compressor evidence does not fit the existing qualifying adapter path. |

Official exact-record citations and project-bound identifiers are in the safe receipt. Chicago native research confirmed permit-listed organizations, including electrical contractors and GC on the conversion permit. It added **two buying-chain evidence records and eight project-organization claims**, without adding duplicate canonical Evidence or assigning purchasing authority. A contractor listing does not establish ownership of temporary-generator procurement. Neither permit establishes actual work commencement, commissioning, temporary demand, or insufficient permanent supply.

The exact generated questions, queries, executed source checks, evidence IDs, acquisition timestamps, remaining unknowns, dispositions and recommended next actions are recorded per case. Discovery queries were generated but **zero web searches executed**: Firecrawl discovery was not configured. Native exact-record acquisition remains useful but does not resolve these temporary-power questions. No general web-search completeness is claimed.

## Run metrics and replay

Run: `2026-10-07T02:26:44.481840+00:00` through `2026-10-07T02:26:56.176491+00:00` (11.695 seconds).

- Six question jobs attempted across two RESEARCH pursuits: four UNRESOLVED, two FAILED; zero resolved or partially resolved.
- Two native retrieval attempts; zero searches, zero model calls; known provider cost $0. No paid requests were made.
- Average retrieval attempts per attempted question: 0.333; average unique checked URLs: 0.667; median question latency: 1.0565 seconds.
- Four duplicate-work-avoidance events reported by existing metrics. Failure rate: 2/6 (33.3%). Validation-triggered work is not counted as unattended automatic investigation.
- No commercial transitions, Signal→Prospect promotions or Prospect→Lead promotions.
- All 14 preexisting Evidence rows, project/need identities and saved evaluation history preserved. No call notes existed in this new corpus; preservation is therefore vacuous for that table.
- Dry planning replay created zero questions and produced equal before/after state hash `0944b8b9e684f479d98b4f60410fcc306c7812aa3bb526cd342d5484e9cac246`.

The first question's admitted buying-chain enrichment changed the input fingerprint of its queued sibling. The stale-input guard correctly refused that older context with `input_changed_before_research`. Settlement created replacement questions, which reused the native result and finished UNRESOLVED. Failed attempts remain visible and count against strict acceptance; a successful replacement does not erase them. This is an operational limitation requiring a separately reviewed handling of superseded queued work, without removing the guard or relaxing the acceptance predicate.

## Technical and browser validation

On frozen code candidate `f63eb62`:

| Check | Exact result |
| --- | --- |
| Backend Ruff, `src tests` | Passed |
| Backend mypy, `src` | Passed, 77 source files |
| Full backend pytest | **1,196 passed, 1 skipped** (optional local NC access probe absent), one existing deprecation warning; 137.29 seconds |
| Focused validator + regeneration tests | **71 passed**, including 27 regeneration boundary tests |
| Frontend typecheck/build | Passed |
| npm audit, high threshold | Passed, **0 vulnerabilities** |
| OpenAPI parity | Exact |
| Browser regression project | **36 passed**, 35.5 seconds |
| Fresh real-database browser check | Four check groups passed: real authentication, Chicago research history, low-quality research history, mobile reload; no API mocks |
| Six legacy live-acceptance tests | **Blocked, not run**: required named historical corpus prerequisites are missing |
| Clean upgrade | Passed through 0014 |
| Populated upgrade | Isolated fresh-data clone prepared at 0013, upgraded to 0014; all 28 full-table inventories restored exactly |
| Repeated upgrade / drift | Passed; no new upgrade operations |
| Research replay / historical-row preservation | Passed |
| Four-case diagnostic acceptance / full five cohorts | **Failed / incomplete** |

An initial regression run was 35/36 because the custom local web port was absent from trusted origins. Correcting the isolated test environment produced 36/36 without changing security checks. The supplemental real-data browser harness was corrected to select the RESEARCH filter and identify repeated question text by evidence fingerprint; it then verified all actual failed/unresolved histories. These harness corrections did not change product behavior or weaken existing tests. Screenshots were captured after authentication; raw traces and private credentials are not published.

## Independent review and remaining work

Independent read-only review found and verified fixes for: stale-worker terminal writes, success exits on failed acquisition/ingestion, incomplete restore inventories, implicit Federal Register companion retrieval outside collection limits, and potentially divergent SQLAlchemy/pg-tool endpoints. Final review found no remaining material tooling safety/preservation issue. Independent review of the actual fresh results also confirmed that stale siblings stopped before acquisition, replacements reused cache, the queue settled at zero, and no unsafe promotion or infinite loop was observed. Bare `postgresql` URLs may require an undeclared psycopg2 driver; use the verified `postgresql+psycopg` URL form.

This work proves fresh corpus acquisition, canonical admission/rejection, backup/restore, bounded real native research, preserved facts, deterministic reevaluation, failure visibility, and duplicate-free replay. It does **not** prove five-cohort commercial acceptance or production operation.

Remaining actionable gaps:

1. Supply an eligible public fixed-O&G project supported by existing adapters, or authorize a narrowly scoped source/admission extension with its own evidence-boundary tests. The rejected or blocked candidates must not be forced into Signal eligibility.
2. Resolve the stale-sibling operational limitation without hiding failed history, bypassing input fingerprints or changing the strict validation predicate; then perform fresh bounded validation.
3. Obtain the six named legacy browser prerequisites, or explicitly approve a separately specified fresh-data acceptance contract. The supplemental check is not equivalent to those tests.
4. Broader discovery was unavailable; enable only an already authorized provider with explicit bounded pricing if further discovery is desired. No provider is required to preserve truthful UNRESOLVED outcomes.

No merge, deployment, external commercial outreach or GL3-030 implementation occurred. Cloud deployment remains a separate milestone.
