# GL3-029 autonomous pursuit research — candidate validation

**Audit update (October 4):** The original PR24 draft head `d8b0e99897c600f32a0e00bb6770b841f2c6f907` passed hosted backend/web CI, then independent static review returned FIX for transient failure cache reuse and uncertain paid-request effects. The original retained PR23 backup was later found at `gl3-evidence-shadow/.artifacts/evidence-shadow/preserved-base.dump` (SHA-256 `828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886`) and restored to an isolated copy. Its 0011→0014 migration setup preserved 22/24 original full-table digests; migration revision changed as intended and original `change_events` columns match despite added columns. Receipts are in `gl3-repair-evidence-20261004` outside this checkout. The strongest retained Austin construction and explicit temporary scopes are already ACTION NOW and legitimately yield no research question. The five-case meaningful-investigation gate remains OPEN; the blocked-corpus wording and local figures below describe the earlier executor/candidate. Repaired-candidate final validation and independent review are pending. Draft remains not merge-ready.

**DRAFT / NOT MERGE-READY.** The final repaired candidate passed local fixture gates and independent review. Required
original retained PR #23 corpus validation is blocked. Nick explicitly authorized
publishing a draft on October 4, 2026 despite that remaining gate. No acceptance,
cloud deployment or production-proof claim is made.

Baseline main: `6c8bdf3e3163adde078f8543d43c0256bc11eb82`, verified again through
GitHub's branch API after local validation. Branch:
`feat/gl3-029-autonomous-pursuit-research`.

## Implemented flow and authority

Durable questions use one new table, existing PostgreSQL jobs/fences, canonical
Source/Observation/Evidence, existing Project/PowerNeed matching, buying-chain
semantics and shared commercial evaluation. Retained facts → at most two ranked
questions → bounded source acquisition → normal admission/quarantine → canonical
projection → deterministic reevaluation → immutable receipt/history → at most one
child. The worker never assigns pursuit disposition or qualification tier.

Typed public reports require an exact grammatical project/site subject, supported
activity predicate and date provenance. Contradictions remain conflicts; corrections
preserve old evidence. Public phase, supply, load and timing reports can answer a
question without positively qualifying a need. Construction does not establish
commissioning; permanent energization alone does not establish sufficient supply.

A narrow official-permit parser implements existing PRD Prospect/Lead criteria.
Separate exact-activity demand and unsuitable supply support Prospect. Lead additionally
requires MW/start/duration ranges, one explicit aggregate suitable-supply interval
(zero or nonzero) throughout that interval, and supported buying role. Remaining
need is calculated conservatively as demand minus suitable supply; effective Lead
visibility applies the inclusive 300 kW floor to that residual, not gross load. Canonical corrections and read-only API gate
replay remove obsolete qualification. Hypothetical, historical, conditional, quoted,
conflicting, campus/nameplate and wrong-activity claims cannot qualify.

Routing prefers retained evidence, registered exact-record adapters, eligible public
pages, then configured URL-only Firecrawl discovery. Exact native GET adapters cover
Austin, Chicago, Seattle, Boston, El Paso and Federal Register. Successful explicit
public JavaScript shells can use separately reserved Firecrawl extraction; access
restrictions and failed requests cannot trigger that fallback. Each question records planned,
checked, unavailable and skipped routes, generated/attempted/completed queries,
source checks and accepted/rejected citations. Default caps are three searches, ten
URLs, five documents, 750,000 bytes per document, 180 seconds, zero model calls and
zero paid-search budget. Searches cannot spend after the document budget is exhausted.
Reservations are not billing receipts; actual provider cost stays unknown without
billing evidence. Question, policy, registry/source selection, semantic evidence and
content/version fingerprints prevent unchanged work. Current canonical support is
rechecked before cache reuse. Reinterpretation of retained public inputs additionally
requires proof of completeness and original source/observation/evidence identity;
retrieval times and historical evidence IDs are preserved. Unrelated new facts do
not count as partial progress on the exact question. Saved targets outside the shortlist are reprojected in
one bulk pass; unchanged fresh results do not schedule more acquisition.

Morning changes count unique saved evaluation versions correlated with completed
research; concurrent operator contributions are not falsely attributed solely to
research. Commercial state and evidence tier remain separate.

## Final repaired candidate validation

All results below were rerun in this saved executor after the final code repairs.

| Gate | Final result |
|---|---|
| Backend `ruff check src tests` | PASS |
| Ruff migrations/scripts | PASS |
| Backend `mypy src` | PASS, 77 source modules |
| Backend `pytest tests` | **1112 passed, 1 skipped, 1 warning; 132.57 seconds** |
| Frontend typecheck | PASS |
| Frontend production build | PASS |
| Frontend audit, high threshold | PASS, **0 vulnerabilities** |
| Current OpenAPI versus checked-in contract | Exact match |
| Full browser suite | **38 passed, 0 failed; 46.160528 seconds** |
| Migration checks | **8 passed** |
| Existing fixture preservation | **8 rows across 7 tables**, identical digests |

The existing skip is `test_nc_commerce.py`'s optional local-access probe: its local
artifact is absent. The warning is the existing Starlette/httpx deprecation. No
failing tests were waived or disabled. Diagnostic failures were repaired and the
full suite rerun. An initial browser launch used an unwritable uv cache; the final
run used the workspace cache and passed.

The 242-file code/test manifest is
`.agent/artifacts/GL3-029-RESEARCH/CODE-MANIFEST.json`, SHA256
`974c0c6d086e3f07c1a7be219d7c5bfc01086d34344d22ec96f78fda9c29e5c9`.
This manifest identifies the final tested code bytes. Tests ran on the working
candidate before its publication commit; receipt HEAD fields name the earlier local checkpoint,
so use this content manifest, not those older HEAD labels, to identify tested code.

Full backend logs: ignored `.artifacts/autonomous-research/review-backend-final.log`.
Browser receipt: ignored `.artifacts/synthetic-browser/gl3_synthetic_browser_43acdf8a567e/`
(JSON, logs and screenshots). The runner creates a distinct synthetic database and
uses canonical ingestion, the existing worker and unchanged existing browser
assertions. It fixes missing fixture setup; it is **not original retained-corpus or
live-source proof**. The original six previously failing workflows now pass.

Migration `0014_pursuit_research_questions` follows `0013_jev_scan`; old migrations
were not edited. Checks cover clean upgrade/repeat/drift, existing 0013 setup and
upgrade/repeat/drift, plus preservation of Source, Observation, two historical
Evidence versions, Project, PowerNeed, Pursuit and call note. All eight fixture rows
in seven tables survive. Receipt: ignored
`.artifacts/autonomous-research/resumed-migrations-final.json`.
The original runtime was not upgraded or seeded.

## Fixture transitions and replay

Canonical worker fixtures cover RESEARCH→ACTION NOW/WATCH/REJECT, WATCH→RESEARCH,
insufficient-evidence no-transition, Signal remaining Signal despite ACTION NOW,
Signal→Prospect and Prospect→Lead only after official gates, corrections/demotion,
age-out, wrong-activity supply rejection, and exact 299/300/301 kW floor handling.
Examples are synthetic, not the real named projects:

| Before | New admitted evidence | Result |
|---|---|---|
| RESEARCH / Signal | Exact permit adds reachable project contractor path | ACTION NOW / Signal |
| WATCH / Signal | Exact permit adds relevant electrical construction activity | RESEARCH / Signal |
| RESEARCH / Lead | Dated exact-project completion or adequate activity supply | REJECT / Signal |
| RESEARCH / Signal | Official exact activity demand plus unsuitable supply | Prospect; pursuit reevaluated separately |
| Prospect | Official interval, duration, aggregate suitable supply and buying role | Lead only with a supported residual; no worker-assigned promotion |
| RESEARCH | Bounded checks without a supported answer | UNRESOLVED; no invented fact |

Tests cover immutable old evidence, same-URL correction, cross-URL content reuse,
current-source cache invalidation, policy/source fingerprint invalidation, no repeated
transition on unchanged replay, active cap, one child/no grandchildren, interrupted
request/lease failures and no external I/O during retained-only enrichment.

## Separate adversarial review

Independent reviewers found and repaired publisher/relationship admission bypasses,
stale contact retention, correction/deduplication hazards, blocking acquisition locks,
lease/error visibility, incidental-subject phase transfer, hypothetical/historical
qualification, dated-heading freshness leakage, optional/investigative temporary
scope, source/policy reuse gaps, shortlist starvation, unit/range floor handling,
and false corpus/harness success or duplicate metrics. Repairs have regressions and
were independently reprobed. A final narrow review confirmed the intentional
nonpolling public-source refresh exception without relaxing admission. The final repaired candidate received a separate read-only review with no remaining
material findings, followed by the full local gates above. This is not original-corpus
or production acceptance.

## Real retained corpus: historical blocked state

The preserved `gridlens` runtime remains `0007_signal_decisions`, with 13 Sources
and zero Observations, Evidence, Projects and PowerNeeds. Authorized searches of the
workspace, PR23 discussion/reviews, issues, all 13 branch trees, full history, PR21
links, releases, Actions artifacts and tags found no restorable original archive.
Older September 25 PC snapshots are not established as the PR23 corpus. This executor
did not access the PC or another environment.

The historical [PR23 report](GL3-029-commercial-pursuits.md) records backup SHA256
`828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886`, 16,960 Evidence,
1,168 active Signal needs, 50 scopes/53 needs and 9 ACTION NOW / 19 RESEARCH / 22 WATCH
/ 0 REJECT. These historical metrics were **not reproduced here**.

| Required original-corpus case | State |
|---|---|
| Austin data-center construction | BLOCKED: original retained pursuit absent |
| Austin explicit temporary-power permit | BLOCKED: original retained pursuit absent |
| Chicago data-center conversion | BLOCKED: original retained pursuit absent |
| O&G | BLOCKED: original retained pursuit absent |
| Low-quality/unresolvable case | BLOCKED: original retained pursuit absent |

Per-case queries, admitted findings, transitions, tier changes, costs, runtimes and
baseline/replay metrics are unavailable. Zero cases ran; this is not zero-cost
successful corpus validation. The new manifest/harness pins an isolated baseline,
caps aggregate execution, checks preserved history and rollback replay, and labels
operator-attested provenance separately from independently established proof.
See [validation tools](../../scripts/README-pursuit-research-validation.md).

## Provider and acquisition limits

No OpenAI, TypeSafe or Firecrawl key is configured here; no credentials were created
or changed, no paid/model calls were made. Runtime Jev architecture is unchanged and
non-authoritative. Exact native GET routes cover Austin/Chicago/Seattle/Boston/
El Paso/Federal Register. Other families need retained facts, eligible direct public
supplements or configured discovery; unavailable native routes stay explicit.
RRC form submissions and unimplemented bulk-source research adapters remain excluded.
Owned network/parser operations run in a killable subprocess with the question's
hard deadline and a 512 MiB address-space cap; no database writes run in that child.
Direct text/PDF inputs are admitted only after whole-input validation within 750,000
bytes, 30,000 extracted characters and 20 PDF pages. No OCR, encrypted-page access
or truncated-prefix admission is supported. Explicit public JavaScript shells alone
are eligible for configured bounded Firecrawl extraction. Exact registry hostnames
can support public supplements, never native-source or positive tier authority.
Strict grammars leave unsupported wording and complex/segmented supply schedules
unknown; nonzero aggregate supply requires explicit suitability throughout the exact
activity interval. These are visible limits, not proof that missing facts are false.

A separate fresh direct-source smoke made three bounded public GET queries and two
exact Austin retrievals: $0, zero models, 6.628 seconds active request time, 62.060173
seconds elapsed. It made zero canonical admissions/database writes. Chicago's exact
address filter returned no rows; Clayton's capped sample was a retaining-wall permit,
not data-center power proof. This is source-access smoke only.

The final separate review found no remaining material findings after repairs to
whole-body extraction, body-level access controls, non-text PDF content, title
bounds and capture provenance. Acquisition inputs reject oversized titles rather
than omitting their suffix. `public-document-v3` captures and versioned policy
checks exclude older main-container-only captures from current projection,
buying-chain support, retained replay and cache reuse until safe refresh. Evidence
rows remain immutable; reinterpretation history preserves prior decisions.

## Specification gap audit — current repair scope

This checklist distinguishes implementation boundaries from unfulfilled acceptance.
It does not assert that every scenario in the 30-section specification is proven.

| Specification area | Current disposition |
|---|---|
| 1, 25: reconstruction and architecture reuse | Documented; existing jobs, worker, evidence, sources, matching and evaluator retained. Acquisition child processes contain no DB or new orchestration system. |
| 2–7, 9–13, 15–21: bounded questions, routing, admission, reevaluation, UI and authority | Local implementation present; exact-question progress, historical context, source decisions and independent commercial/tier state remain inspectable. Final local gates above passed. |
| 8, 14, 19–20: budgets, one follow-up, duplication and model bounds | Implemented caps/cache/replay and one-child limit; hard acquisition termination and parser bounds added. No model authority or open research trees. Provider-backed execution is not live-proven here. |
| 22, 27–29: tests, migration discipline and separate adversarial review | Final results retained above. Current repaired candidate must rerun full required gates and close independent findings; those results are pending. |
| 23–24: five retained cases and corpus baseline/yield/cost/runtime | **OPEN:** the original PR23 archive has since been located and restored in isolation. The original PR24 candidate still lacks accepted five-case corpus evidence; see the October 4 audit update above. Historical counts, synthetic fixtures and fresh reingestion cannot establish this gate. |
| 26, 30: canonical docs and focused deliverable | Same draft PR #24; documentation distinguishes implementation/local validation/deployment/production proof. Definition of done remains unmet until required retained-corpus acceptance is completed. |

Intentional bounded UNKNOWN/unavailable outcomes include unimplemented exact native
routes (RRC form flow; Houston/Dallas bulk files; Georgia/NC/Taylor/MA research
refresh), scanned, image/form/vector-painted, encrypted or oversized PDFs, non-JavaScript unsupported page formats,
missing project/date/activity bindings, ambiguous personal assignment/authority,
and complex supply schedules that lack one explicit suitable aggregate interval.
Existing admitted facts remain available even where whole-document replay cannot
prove completeness. No fallback bypasses login, CAPTCHA, denial or access controls.

Separate external blockers are the missing retained PR23 database and unconfigured
Firecrawl/other provider access. Buying or configuring services is not authorized
by these docs. Model use is optional and absent here; zero model calls are a design
choice, not a fabricated substitute for provider validation. Cloud deployment and
production unattended proof remain explicitly separate milestones.

**No external commercial outreach occurs.** No emails, calls, commercial forms,
external CRM records, purchases, account login or access-control bypass.
**Cloud deployment remains a separate milestone.** Do not merge until required
retained-corpus and operational acceptance gates have been completed and reviewed.
