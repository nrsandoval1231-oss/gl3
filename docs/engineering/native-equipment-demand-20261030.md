# Native equipment evidence → demand investigation

**October 30 candidate; not deployed.** This extends the [equipment-demand foundation](equipment-demand-slice-20261030.md), not the product architecture. Main was explicitly fetched at `d54646c1600ff4f658d765fa0acf749a4166803c`. Implementation baseline `1af5fa79` combines PR153 `9f77040d` and PR155 acquisition `7b0d5533`; PR154 is independent.

## Audit and reuse

| Disposition | Responsibility | Result |
|---|---|---|
| KEEP | PostgreSQL, Evidence/Project/PowerNeed/EvidencePackage, FastAPI, workers, deterministic demand model | No migration, dependency, service or provider added. |
| EVOLVE | GovInfo companion retrieval | Retain complete bounded notice text, original PDF hash, page provenance and exact document/title/footer binding. |
| EVOLVE | Discovery and ingestion/admission | Add one FERC environmental-assessment query alongside EIS under shared retrieval budgets, then admit exactly one explicit proposed electric-equipment site. |
| EVOLVE | Evidence processing | Parse a bounded native layout, validate PR152 UNVERIFIED candidates, explicitly convert supported fields to existing deterministic inputs. |
| EVOLVE | Existing intelligence card/detail | Show exact source equipment assertion, historical date, unknown capacity and investigation action without changing layout. |
| DEFER | Broader discovery/extraction, multi-site fan-out, legal company identity, verified buyer, portfolio totals/ranking | Require measured coverage and explicit physical-equipment overlap rules. |

The prior path required labeled schedules; native O&G notices also failed the mining-oriented companion-fetch gate. The later discovery extension adds the missing FERC environmental-assessment query to the existing source. Generic Federal Register admission remains context-only. The new path has its own source-bound admission and skips whole-notice legacy qualification/lifecycle inference, so other stations and publication dates cannot invent quantity or commissioning claims.

## Actual evidence and output

The retained real document is [FR-2024-12869](https://www.govinfo.gov/content/pkg/FR-2024-06-12/pdf/2024-12869.pdf), published June 12, 2024. Fixture: `backend/tests/fixtures/govinfo-complete-notice/FR-2024-12869.pdf`; 229,868 bytes; SHA256 `4d5d8293eebb47e41705b0b9f2aa027a6a898820c73913f6b33d7683b99127b6`. Original bytes and acquisition provenance are preserved.

At Compressor Station 302, Montgomery County, Texas, the notice proposes one new electric motor driven compressor rated **18,340 hp**. Existing-unit uprates/rewheels are retained separately. Compressor Station 343 in Liberty County has existing-unit rewheels; its equipment is not assigned to CS302. The title party and differing body applicant spelling are retained as separate source attributions, not silently resolved into a legal company or buyer.

Normal `process_records` produces a site-bound Signal/investigation, immutable `equipment-demand-v1` package, and existing API/card output. Status is **PARTIAL**, demand classification **UNKNOWN**, candidate verification state **UNVERIFIED**. Rating basis, motor efficiency, operating configuration, current project status, expected start, buyer and supply are unsupported. All electrical quantities remain null. Retrieval time does not become a last-verified project date. The published proposal date is an as-of date, not a start date.

This is a useful unresolved electrical requirement, not quantified facility demand. The existing foundation still performs reproducible numerical calculations when supported schedule inputs exist. No utility shortage or manual approval is required for either path.

## Verification boundaries

- Strict title, document-number/date/URL, retained PDF hash, exact evidence ID, current interpretation, observation, project/site and need bindings are checked independently of extraction. No LLM is used.
- Original source quotes and offsets accompany assertions. Internal semantic claim keys are explicitly identified as derived; they are not source equipment IDs.
- Exactly one new-electric-equipment site may qualify. Multiple qualifying sites, malformed scope, negation, contradictions and duplicate unidentified installation assertions abstain. Distinct unidentified assertions do not establish a deduplicated site total.
- Unsupported existing work remains inspectable context. It cannot supply missing rating basis, efficiency or operating assumptions. Structural errors block admission; unresolved source-party identity does not become a mandatory human queue.
- Current reads recompute payloads. Changed/missing evidence, corrected site/title or stale bindings withdraw unsupported current results while preserving immutable history and independently supported needs.
- Existing schedule keys, payloads and SQL bindings remain byte/value compatible; adding this path must not hide prior records until replay.

## Validation and delivery

The native OpenAI collaboration harness used Sol 6.1/high architecture coordination, three Luna 6/low builders with separate parser/binding/test ownership, and Astra 6/high independent review. No separate repository harness launcher was found. Review identified and prompted repairs for site scope, duplicate assertions, legacy payload compatibility, corrected-notice withdrawal and misleading verification dates/labels.

Tests use retained PDF bytes through mocked retrieval and disposable PostgreSQL. Adversarial corrections are explicitly labeled synthetic captured-text mutations, never presented as authentic source documents. Coverage includes native extraction/admission, normal ingestion, replay, source tampering, multi-site withdrawal, physical-site rebinding and legacy compatibility. Desktop/mobile detail tests check the exact source assertion, historical date, unknown capacity and overflow. Final commit hashes, full backend/browser gates, lint/type/migration/security/brand checks and independent review disposition are recorded in the delivery PR; earlier predecessor CI does not certify this extension.

Local integrated gate: **155 tests passed in 36.00 seconds** across engineering/extraction/card/regional admission and native/legacy equipment persistence/ingestion. Native DB cases alone: **8 passed**; independent unit review: **35 passed**. Existing/detail native browser cases: **2 passed in 15.7 seconds**, including desktop and mobile. Ruff lint/format, mypy (190 source files), TypeScript, web build, npm audit (zero vulnerabilities), brand validation (216 assets), maintained-doc links, Alembic drift check, API startup/unauthenticated-session and idle-worker startup/shutdown passed. The full CI gate remains separate and is recorded against the final commit in the PR.

No production configuration/data, credentials, paid providers or deployment were changed. Latest production evidence remains the dated October 29 PR148/schema0049 receipt; it was not freshly inspected.

## Discovery follow-through

The candidate extends the existing `federal-register-eis` source, preserving its ID, daily cadence, primary EIS query and rolling window. One supplemental query uses `conditions[term]=environmental assessment` with `conditions[agencies][]=federal-energy-regulatory-commission`. The checked-in configuration shares **10 request pages, 20 MB and the acquisition deadline** across both queries; empty-query probes consume the same budget. No source or production worker was activated during implementation.

Each query must complete before records are returned. Explicit zero-result responses are healthy; malformed/empty nonzero pages, count/page drift, repeated same-query records or exhausted limits fail acquisition. Exact cross-query canonical duplicates are removed without changing retained record fields. Conflicting variants remain separate so existing ingestion quarantines every conflicting variant. No lexical checkpoint is used as a retrieval cursor and no new scheduler or schema is introduced.

[Unmodified API captures and provenance](../../backend/tests/fixtures/federal-register-ferc-discovery/provenance.json) cover the same historical window, May 31–June 30, 2024. The EIS query returned **72** notices and excluded FR-2024-12869; the FERC assessment query returned **19**, including that notice. Five exact overlaps yield **86** unique notices, **14** additional to EIS. The normal acquisition/job integration test checks capture hashes/bytes and retrieves the real target PDF to produce the existing unknown-quantity CS302 investigation. Other companion PDFs are explicitly unavailable in that offline test; it does not prove extraction coverage for all 86 notices. Replay, healthy zero results and conflict quarantine are tested separately.

A read-only execution of the candidate adapter at **2026-10-30 13:16:08 UTC**, using the real September 30–October 30 query window, completed **two HTTP requests** and normalized **71 unique metadata records** without partial status. Three records matched native title/URL eligibility. These are metadata candidates, not three established power opportunities. This check performed no ingestion, job creation, paid-provider call or production write. Old same-hash truncated PDF evidence remains immutable; no historical backfill is included.

Local discovery validation: **148 passed in 30.10 seconds** across registry, adapter, native ingestion, general ingestion and collection-only regressions. A further acquisition-boundary selection passed **68 tests in 6.57 seconds**. The final captured-response integration cases passed **3 tests in 15.76 seconds**, including both capture hash checks. Ruff lint/format, mypy (190 source files), maintained-doc links (91 documents/366 targets), API startup/unauthenticated session and idle-worker startup/shutdown passed. These focused checks do not replace the full CI gate.

The predecessor `484301b6f017b8487417372db5345c369c0bcfa0` passed [CI 41058851985](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41058851985): 3,583 backend tests/one existing skip and 170 browser tests. That head includes the independent test-clock repair from PR157. The discovery extension needs its own final-head full gate, recorded on PR156; earlier results do not certify it.

## Remaining work by commercial value

1. Evaluate more engineering layouts and observe scheduled acquisition after an authorized deployment. The candidate now searches both EIS and FERC environmental assessments; read-only retrieval and historical replay do **not** establish deployed scheduling or complete equipment coverage.
2. Resolve source-attributed companies and current project status, then investigate missing specifications and verified buyers through existing budgets/privacy controls.
3. Support deliberate multi-site observation scoping and physical-unit deduplication before totals. Add demand-first portfolio ranking only with defensible overlap and timing rules.
4. Extend the shared model to further equipment/layouts and data-center phases, using a measured corpus and independent regression gates. General prose/table extraction and autonomous model promotion remain deferred.
